"""
client_timeline.py — one dated record per client, assembled from every
table that knows them.

WHY THIS EXISTS. The vision doc ranks operational data gravity — ledgers,
bookings, client history — as moat #1, and until now there was no single
place that history could be read. It was scattered across eleven tables
that each know a contact by a different key: `events` (the de facto
timeline, FK'd to contacts), `sessions`, `invoices`, `time_entries`,
`customer_ledger`, `sms_messages`, `email_replies`, `mailbox_messages`,
`agent_queue`, `orders`, `campaign_sends`, and `module_entries` (a jsonb
key, no FK). Contracts (`esign_documents`) know the signer only by
email. contact_deep_dive read four of those and returned four separate
arrays in four different orders.

WHAT IT DOES. `assemble(business_id, contact_id)` reads every source in
parallel, normalises each row into one entry shape, drops the event rows
that merely mirror a table row (an sms_sent event beside its
sms_messages row would show the same text twice), sorts by time, and
returns the merged list with a short summary. Both the practitioner
endpoint (contacts_router: GET /contacts/{id}/timeline) and Chief's
contact_deep_dive call this one function — the surface-freedom rule:
spine logic is not allowed to live in a router.

WHAT IT DOES NOT DO. It never writes. It never widens: every read is
scoped by business_id as well as contact_id, and a contact id that is
not a uuid is refused before it reaches a query string. A refused read
(the helper returns None, not []) is reported as a missing source, not
as "this client has no history" — the difference between a quiet
client and a broken read is the whole point of a record.

ENTRY SHAPE
  id          "<table>:<row id>" — stable, so a UI can key on it
  kind        booking | form | invoice | payment | order | contract |
              email | sms | note | activity | time | balance | lead |
              file | campaign | record | event
  at          ISO-8601, the moment the thing happened: scheduled_for
              for a booking, occurred_on for time, received_at for
              inbound mail, completed_at for a signed contract,
              created_at otherwise (each normaliser names its column)
  title       one line, practitioner-readable
  detail      optional second line (subject, preview, amount…)
  direction   in | out | None — for messages
  status      the row's own status word where it has one
  source      the table it came from
  source_id   the row id
  ref         small dict of ids a UI can navigate with (invoice_id,
              session_id, module_id, …)
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import sb_clients

logger = logging.getLogger("client_timeline")

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# Event types whose row is a mirror of a typed table row — the table row
# is the entry, the event is skipped. Anything not listed here is kept.
_MIRRORED_EVENTS = frozenset({
    "sms_sent", "sms_received",          # sms_messages
    "email_replied",                     # email_replies
    "booking_created",                   # sessions
    "agent_message_sent",                # agent_queue (status=sent)
    "invoice_sent",                      # invoices carry status
})

# Every other event type → kind. Unlisted types fall through as "event".
_EVENT_KINDS = {
    "form_submit": "form", "contact_form_submitted": "form",
    "concierge_lead_captured": "form", "module_entry_from_intake": "form",
    "invoice_paid": "payment", "invoice_paid_auto": "payment",
    "payment_received": "payment", "booking_paid": "payment",
    "order_paid": "payment", "payment_refunded": "payment",
    "giving_received": "payment", "product_sold": "payment",
    "contract_signed": "contract", "contract_draft_created": "contract",
    "document_generated": "file", "document_uploaded": "file",
    "resource_download": "file", "order_download": "file",
    "contact_note": "note",
    "activity_logged": "activity",
    "lead_scored": "lead", "contact_status_changed": "lead",
    "session_no_show": "booking",
    "batch_email_sent": "email", "email_sent": "email",
    "report_sent": "email",
    "sms_reminder_sent": "sms",
    "campaign_sent": "campaign",
}

_HUMANE = {
    "form_submit": "Submitted a form",
    "contact_form_submitted": "Sent a message through the site",
    "concierge_lead_captured": "Left details with the site concierge",
    "module_entry_from_intake": "A record was created from their intake",
    "invoice_paid": "Paid an invoice", "invoice_paid_auto": "Paid an invoice",
    "payment_received": "Payment received", "booking_paid": "Paid for a booking",
    "order_paid": "Paid for an order", "payment_refunded": "Refunded",
    "giving_received": "Gift received", "product_sold": "Bought a product",
    "contract_signed": "Signed a contract",
    "contract_draft_created": "A contract was drafted for them",
    "document_generated": "A document was generated for them",
    "document_uploaded": "A file was added to their record",
    "resource_download": "Downloaded a resource",
    "order_download": "Downloaded a purchase",
    "contact_note": "Note", "activity_logged": "Activity logged",
    "lead_scored": "Lead scored", "contact_status_changed": "Status changed",
    "session_no_show": "Did not show for a session",
    "batch_email_sent": "Emailed", "email_sent": "Emailed",
    "report_sent": "Report sent", "sms_reminder_sent": "Reminder texted",
}


# ─── Normalisers: one row in, one entry (or None) out ───────────────────

def _iso(v: Any) -> Optional[str]:
    """Normalise a PostgREST timestamp/date to ISO with a Z. Dates
    (occurred_on) become midnight UTC so they sort among timestamps."""
    if not v:
        return None
    s = str(v)
    if len(s) == 10:            # YYYY-MM-DD
        return s + "T00:00:00Z"
    return s.replace("+00:00", "Z")


def _money(amount: Any, currency: Any = "usd") -> str:
    try:
        a = float(amount or 0)
    except (TypeError, ValueError):
        return str(amount)
    cur = (currency or "usd").upper()
    return f"${a:,.2f}" if cur == "USD" else f"{a:,.2f} {cur}"


def _short(text: Any, n: int = 140) -> Optional[str]:
    if not text:
        return None
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _entry(kind: str, at: Optional[str], title: str, *, source: str,
           source_id: Any, detail: Optional[str] = None,
           direction: Optional[str] = None, status: Optional[str] = None,
           ref: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not at:
        return None
    return {
        "id": f"{source}:{source_id}",
        "kind": kind, "at": at, "title": title, "detail": detail,
        "direction": direction, "status": status,
        "source": source, "source_id": str(source_id),
        "ref": ref or {},
    }


def _n_event(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    et = r.get("event_type") or "event"
    if et in _MIRRORED_EVENTS:
        return None
    d = r.get("data") or {}
    kind = _EVENT_KINDS.get(et, "event")
    title = _HUMANE.get(et) or et.replace("_", " ").capitalize()
    detail = None
    if et == "contact_note":
        detail = _short(d.get("note"))
    elif et == "activity_logged":
        title = f"{(d.get('activity_type') or 'activity').capitalize()} logged"
        detail = _short(d.get("notes"))
    elif et in ("form_submit",):
        title = f"Submitted {d.get('form_name') or 'a form'}"
    elif et in ("contact_form_submitted", "concierge_lead_captured"):
        detail = _short(d.get("message_preview"))
    elif et == "contact_status_changed":
        detail = f"{d.get('from') or d.get('from_status') or '?'} → {d.get('to') or d.get('to_status') or '?'}"
    elif et == "lead_scored":
        detail = f"{d.get('priority') or ''} {d.get('score') or ''}".strip() or None
    elif et in ("invoice_paid", "invoice_paid_auto", "payment_received"):
        amt = d.get("total") if d.get("total") is not None else d.get("amount")
        detail = (_money(amt) if amt is not None else None)
        if d.get("invoice_number"):
            detail = f"#{d['invoice_number']}" + (f" · {detail}" if detail else "")
    elif et == "payment_refunded":
        cents = d.get("refunded_cents")
        detail = _money((cents or 0) / 100) if cents is not None else None
    elif et == "contract_signed":
        detail = _short(d.get("title"))
    elif et in ("document_uploaded", "document_generated"):
        detail = _short(d.get("file_name") or d.get("title"))
    elif et in ("batch_email_sent", "email_sent", "report_sent"):
        detail = _short(d.get("subject"))
    elif et == "session_no_show":
        detail = _short(d.get("title"))
    ref = {k: d[k] for k in ("invoice_id", "booking_id", "order_id",
                             "form_id", "conversation_id", "contract_ref")
           if d.get(k)}
    return _entry(kind, _iso(r.get("created_at")), title, source="events",
                  source_id=r.get("id"), detail=detail, ref=ref,
                  direction=("out" if kind in ("email", "sms") else None))


def _n_session(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    status = r.get("status") or "scheduled"
    mins = r.get("duration_minutes")
    title = r.get("title") or (r.get("session_type") or "session").replace("_", " ").capitalize()
    detail = (f"{mins} min" if mins else None)
    if r.get("notes"):
        detail = (detail + " · " if detail else "") + (_short(r["notes"], 100) or "")
    return _entry("booking", _iso(r.get("scheduled_for")), title,
                  source="sessions", source_id=r.get("id"), detail=detail,
                  status=status, ref={"session_id": r.get("id")})


def _n_invoice(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    num = r.get("invoice_number")
    title = f"Invoice #{num}" if num else "Invoice"
    detail = _money(r.get("total"), r.get("currency"))
    if r.get("due_date"):
        detail += f" · due {r['due_date']}"
    return _entry("invoice", _iso(r.get("created_at")), title,
                  source="invoices", source_id=r.get("id"), detail=detail,
                  status=r.get("status"), ref={"invoice_id": r.get("id")})


def _n_time(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    mins = int(r.get("minutes") or 0)
    hrs = f"{mins/60:.1f}h" if mins >= 60 else f"{mins}m"
    title = f"{hrs} logged"
    return _entry("time", _iso(r.get("occurred_on") or r.get("created_at")),
                  title, source="time_entries", source_id=r.get("id"),
                  detail=_short(r.get("description")), status=r.get("status"),
                  ref={"time_entry_id": r.get("id"),
                       "invoice_id": r.get("invoice_id")} if r.get("invoice_id")
                  else {"time_entry_id": r.get("id")})


def _n_ledger(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        delta = float(r.get("delta") or 0)
    except (TypeError, ValueError):
        delta = 0.0
    unit = r.get("unit") or "money"
    kind_word = (r.get("kind") or "balance").replace("_", " ")
    if unit == "money":
        amt = _money(abs(delta), r.get("currency"))
    else:
        amt = f"{abs(delta):g} {unit}{'s' if abs(delta) != 1 else ''}"
    title = f"{kind_word.capitalize()}: {'+' if delta > 0 else '−'}{amt}"
    return _entry("balance", _iso(r.get("created_at")), title,
                  source="customer_ledger", source_id=r.get("id"),
                  detail=_short(r.get("reason")),
                  ref={k: r[k] for k in ("invoice_id", "offering_id", "booking_id")
                       if r.get(k)})


def _n_sms(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    inbound = (r.get("direction") or "") == "inbound"
    title = "Texted you" if inbound else "You texted"
    if not inbound and r.get("sent_by") == "chief":
        title = "Chief texted"
    return _entry("sms", _iso(r.get("created_at")), title,
                  source="sms_messages", source_id=r.get("id"),
                  detail=_short(r.get("message")),
                  direction="in" if inbound else "out", status=r.get("status"))


def _n_email_reply(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return _entry("email", _iso(r.get("received_at")), "Emailed you",
                  source="email_replies", source_id=r.get("id"),
                  detail=_short(r.get("subject")), direction="in",
                  status="unread" if r.get("read") is False else None)


def _n_mailbox(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return _entry("email", _iso(r.get("received_at")), "Emailed you",
                  source="mailbox_messages", source_id=r.get("id"),
                  detail=_short(r.get("subject")), direction="in")


def _n_queue(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    channel = (r.get("channel") or "email").lower()
    kind = "sms" if channel == "sms" else "email"
    who = "Chief" if (r.get("agent") or "") not in ("", "practitioner") else "You"
    title = f"{who} {'texted' if kind == 'sms' else 'emailed'}"
    return _entry(kind, _iso(r.get("reviewed_at") or r.get("created_at")), title,
                  source="agent_queue", source_id=r.get("id"),
                  detail=_short(r.get("subject")), direction="out",
                  status=r.get("status"), ref={"queue_id": r.get("id")})


def _n_esign(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    status = r.get("status") or "sent"
    done = status == "completed"
    title = ("Signed: " if done else f"Contract {status}: ") + (r.get("title") or "document")
    return _entry("contract", _iso(r.get("completed_at") if done else r.get("sent_at")),
                  title, source="esign_documents", source_id=r.get("id"),
                  status=status, ref={"document_id": r.get("document_id")})


def _n_order(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cents = r.get("total_cents") or 0
    return _entry("order", _iso(r.get("paid_at") or r.get("created_at")),
                  "Order", source="orders", source_id=r.get("id"),
                  detail=_money(cents / 100, r.get("currency")),
                  status=r.get("status"), ref={"order_id": r.get("id")})


def _n_campaign(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return _entry("campaign", _iso(r.get("sent_at")),
                  f"Campaign touch {int(r.get('touch_idx') or 0) + 1} sent",
                  source="campaign_sends", source_id=r.get("id"),
                  direction="out", detail=(r.get("channel") or None),
                  ref={"campaign_id": r.get("campaign_id")})


def _n_module_entry(modules: Dict[str, Dict[str, Any]]) -> Callable:
    def _n(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        m = modules.get(r.get("module_id") or "") or {}
        d = r.get("data") or {}
        name = m.get("name") or "Record"
        # a human-ish label: the first short string field that isn't an id
        label = None
        for k, v in d.items():
            if k in ("contact_id", "id") or not isinstance(v, str):
                continue
            if 0 < len(v) <= 80:
                label = v
                break
        return _entry("record", _iso(r.get("created_at")), f"{name} record",
                      source="module_entries", source_id=r.get("id"),
                      detail=label, status=r.get("status"),
                      ref={"module_id": r.get("module_id"),
                           "module_slug": m.get("slug"),
                           "entry_id": r.get("id")})
    return _n


# ─── The sources ────────────────────────────────────────────────────────

def _q(v: str) -> str:
    """Quote a value for a PostgREST filter (commas, parens, quotes)."""
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _sources(biz: str, cid: str, contact: Dict[str, Any], per: int
             ) -> List[Tuple[str, Optional[str]]]:
    """(key, path) per source. A None path means the source does not
    apply to this contact (no email → no contracts lookup)."""
    scope = f"business_id=eq.{biz}&contact_id=eq.{cid}"
    email = (contact.get("email") or "").strip()
    esign = None
    if email:
        esign = (f"/esign_documents?business_id=eq.{biz}"
                 f"&or=(signer_email.eq.{_q(email)},signer_email.eq.{_q(email.lower())})"
                 f"&order=sent_at.desc&limit={per}"
                 f"&select=id,document_id,title,status,sent_at,completed_at")
    return [
        ("events", f"/events?{scope}&order=created_at.desc&limit={per}"
                   f"&select=id,event_type,data,source,created_at"),
        ("sessions", f"/sessions?{scope}&order=scheduled_for.desc&limit={per}"
                     f"&select=id,title,session_type,status,scheduled_for,duration_minutes,notes,created_at"),
        ("invoices", f"/invoices?{scope}&order=created_at.desc&limit={per}"
                     f"&select=id,invoice_number,status,total,currency,due_date,paid_at,created_at"),
        ("time_entries", f"/time_entries?{scope}&order=occurred_on.desc&limit={per}"
                         f"&select=id,description,minutes,billable,status,occurred_on,invoice_id,created_at"),
        ("customer_ledger", f"/customer_ledger?{scope}&order=created_at.desc&limit={per}"
                            f"&select=id,kind,unit,delta,currency,reason,invoice_id,offering_id,booking_id,created_at"),
        ("sms_messages", f"/sms_messages?{scope}&order=created_at.desc&limit={per}"
                         f"&select=id,direction,message,status,sent_by,created_at"),
        ("email_replies", f"/email_replies?{scope}&order=received_at.desc&limit={per}"
                          f"&select=id,subject,from_email,read,received_at"),
        ("mailbox_messages", f"/mailbox_messages?{scope}&order=received_at.desc&limit={per}"
                             f"&select=id,subject,from_email,received_at"),
        ("agent_queue", f"/agent_queue?{scope}&status=eq.sent&order=created_at.desc&limit={per}"
                        f"&select=id,agent,action_type,subject,channel,status,created_at,reviewed_at"),
        ("orders", f"/orders?{scope}&order=created_at.desc&limit={per}"
                   f"&select=id,status,total_cents,currency,paid_at,created_at"),
        ("campaign_sends", f"/campaign_sends?{scope}&order=sent_at.desc&limit={per}"
                           f"&select=id,campaign_id,touch_idx,channel,sent_at"),
        ("module_entries", f"/module_entries?business_id=eq.{biz}&data->>contact_id=eq.{cid}"
                           f"&order=created_at.desc&limit={per}"
                           f"&select=id,module_id,data,status,created_at"),
        ("custom_modules", f"/custom_modules?business_id=eq.{biz}&select=id,name,slug,icon"),
        ("esign_documents", esign),
    ]


_NORMALISERS: Dict[str, Callable] = {
    "events": _n_event, "sessions": _n_session, "invoices": _n_invoice,
    "time_entries": _n_time, "customer_ledger": _n_ledger,
    "sms_messages": _n_sms, "email_replies": _n_email_reply,
    "mailbox_messages": _n_mailbox, "agent_queue": _n_queue,
    "orders": _n_order, "campaign_sends": _n_campaign,
    "esign_documents": _n_esign,
}

_CONTACT_SELECT = ("id,name,email,phone,status,tags,source,health_score,"
                   "lead_score,last_interaction,first_response_at,created_at")

# Kinds that count as "the last time you and they were in touch".
_TOUCH_KINDS = frozenset({"booking", "email", "sms", "note", "activity", "form"})


async def _read(path: str) -> Optional[List[Dict[str, Any]]]:
    """Service-role read off the event loop. None = the read was refused
    or failed; [] = it ran and found nothing. Callers keep the difference."""
    try:
        rows = await asyncio.to_thread(sb_clients.sb_get_as_service, path)
    except Exception as e:  # network / auth — never a 500 for the whole record
        logger.warning(f"[timeline] read failed {path.split('?')[0]}: {e}")
        return None
    if rows is None:
        return None
    return list(rows) if isinstance(rows, list) else []


async def fetch_contact(business_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    if not (_UUID.match(str(contact_id or "")) and _UUID.match(str(business_id or ""))):
        return None
    rows = await _read(f"/contacts?id=eq.{contact_id}&business_id=eq.{business_id}"
                       f"&select={_CONTACT_SELECT}&limit=1")
    return (rows or [None])[0] if rows else None


async def assemble(business_id: str, contact_id: str, *, limit: int = 200,
                   kinds: Optional[List[str]] = None, per_source: int = 200,
                   contact: Optional[Dict[str, Any]] = None
                   ) -> Optional[Dict[str, Any]]:
    """The one merged, dated record for a contact. None when the contact
    is not in this business (or the ids are not uuids). Otherwise:

      { contact, entries[≤limit, newest first], summary,
        sources: {key: row count | None when that read was refused},
        partial: bool, raw: {key: rows} }

    `raw` is the per-table rows as read, for callers that still want the
    typed arrays (contact_deep_dive keeps its old keys from it). Pass
    `contact` when the caller has already validated it, to skip one read."""
    if not (_UUID.match(str(contact_id or "")) and _UUID.match(str(business_id or ""))):
        return None
    if contact is None:
        contact = await fetch_contact(business_id, contact_id)
    if not contact:
        return None
    specs = _sources(business_id, contact_id, contact, per_source)
    results = await asyncio.gather(*[
        _read(path) if path else asyncio.sleep(0, result=[]) for _, path in specs
    ])
    raw: Dict[str, Optional[List[Dict[str, Any]]]] = {k: v for (k, _), v in zip(specs, results)}

    modules = {m["id"]: m for m in (raw.get("custom_modules") or []) if m.get("id")}
    norms = dict(_NORMALISERS)
    norms["module_entries"] = _n_module_entry(modules)

    entries: List[Dict[str, Any]] = []
    for key, rows in raw.items():
        fn = norms.get(key)
        if not fn or not rows:
            continue
        for r in rows:
            try:
                e = fn(r)
            except Exception as ex:  # one malformed row must not hide the rest
                logger.warning(f"[timeline] skipped {key} row {r.get('id')}: {ex}")
                e = None
            if e:
                entries.append(e)

    if kinds:
        want = {k.strip() for k in kinds if k and k.strip()}
        entries = [e for e in entries if e["kind"] in want]
    entries.sort(key=lambda e: e["at"], reverse=True)

    sources = {k: (len(v) if v is not None else None) for k, v in raw.items()
               if k != "custom_modules"}
    summary = _summarise(entries, raw)
    return {
        "contact": contact,
        "entries": entries[:limit],
        "summary": summary,
        "sources": sources,
        "partial": any(v is None for v in sources.values()),
        "raw": raw,
    }


def _summarise(entries: List[Dict[str, Any]], raw: Dict[str, Any]) -> Dict[str, Any]:
    by_kind = Counter(e["kind"] for e in entries)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    # "last in touch" is about the past; a booking next month is not a touch yet.
    touches = [e for e in entries if e["kind"] in _TOUCH_KINDS and e["at"] <= now]
    invoices = raw.get("invoices") or []
    open_inv = [i for i in invoices if (i.get("status") or "") in ("sent", "overdue", "viewed", "partial")]
    times = raw.get("time_entries") or []
    unbilled = sum(int(t.get("minutes") or 0) for t in times if (t.get("status") or "") == "unbilled")
    balances: Dict[str, float] = {}
    for l in raw.get("customer_ledger") or []:
        try:
            balances[l.get("unit") or "money"] = balances.get(l.get("unit") or "money", 0.0) + float(l.get("delta") or 0)
        except (TypeError, ValueError):
            pass
    upcoming = [e for e in entries if e["kind"] == "booking" and e["at"] > now
                and (e.get("status") or "") not in ("cancelled", "canceled")]
    return {
        "count": len(entries),
        "by_kind": dict(by_kind),
        "first_at": entries[-1]["at"] if entries else None,
        "last_at": entries[0]["at"] if entries else None,
        "last_touch_at": touches[0]["at"] if touches else None,
        "last_touch": touches[0]["title"] if touches else None,
        "next_booking_at": upcoming[-1]["at"] if upcoming else None,
        "open_invoices": len(open_inv),
        "open_invoice_total": round(sum(float(i.get("total") or 0) for i in open_inv), 2),
        "unbilled_minutes": unbilled,
        "balances": balances,
    }


def narrate(record: Dict[str, Any], max_lines: int = 40) -> str:
    """A plain-text rendering for a model or a log: one line per entry,
    newest first, plus the summary line. Names and message previews are
    third-party text; the caller decides whether to defuse them."""
    c = record.get("contact") or {}
    s = record.get("summary") or {}
    head = [f"{c.get('name') or 'This contact'} — {s.get('count', 0)} entries"]
    bits = []
    if s.get("last_touch_at"):
        bits.append(f"last in touch {s['last_touch_at'][:10]} ({s.get('last_touch')})")
    if s.get("next_booking_at"):
        bits.append(f"next booking {s['next_booking_at'][:16].replace('T', ' ')}")
    if s.get("open_invoices"):
        bits.append(f"{s['open_invoices']} open invoice(s), {_money(s.get('open_invoice_total'))}")
    if s.get("unbilled_minutes"):
        bits.append(f"{s['unbilled_minutes']} unbilled minutes")
    for unit, v in (s.get("balances") or {}).items():
        if v:
            bits.append(f"balance {v:g} {unit}")
    if bits:
        head.append("; ".join(bits))
    lines = []
    for e in (record.get("entries") or [])[:max_lines]:
        when = e["at"][:16].replace("T", " ")
        arrow = {"in": "←", "out": "→"}.get(e.get("direction") or "", "·")
        line = f"{when} {arrow} [{e['kind']}] {e['title']}"
        if e.get("detail"):
            line += f" — {e['detail']}"
        if e.get("status") and e["status"] not in e["title"].lower():
            line += f" ({e['status']})"
        lines.append(line)
    if record.get("partial"):
        missing = [k for k, v in (record.get("sources") or {}).items() if v is None]
        lines.append(f"(could not read: {', '.join(missing)})")
    return "\n".join(head + lines)
