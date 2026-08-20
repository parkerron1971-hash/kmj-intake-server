"""outcome_watch.py — THE FOLLOW-THROUGH (2026-08-20, Kevin).

THE GAP THIS CLOSES
  Chief acts and then goes quiet. It sends the invoice, mails the
  purchase order, launches the campaign — and never comes back to say
  how any of it landed. Every loop Chief opens is closed by the
  practitioner remembering to look, or it is not closed at all.

  This module holds those loops open and closes them out loud. Chief
  notices the invoice got paid; Chief notices the restock never
  arrived; and on a miss the notification's one tap is the next move.

THE PIECES
  • chief_outcome_watches — one row per open loop, opened by the
    handler that did the thing (APPLY-2026_08_20_outcome_watches.sql
    carries the why-a-row-and-not-a-query reasoning).
  • KINDS — the four loops and their resolvers. A resolver never
    trusts a number cached at open time; it re-reads the live table,
    so a watch reports what is true NOW.
  • follow_through_sweep() — the hourly worker job: resolve, then
    announce.
  • open_watches() — the read behind Chief's `follow_through` verb and
    the Home panel.

RESOLVE ALWAYS, ANNOUNCE ONLY WHEN AWAKE
  The reorder sweep skips entirely outside waking hours, which is right
  for a job whose only output is an alert. This one also feeds a panel,
  so resolving at 3am is useful and free while WAKING somebody at 3am
  is not. The two halves are therefore split: resolution runs every
  pass, and `announced_at is null` is what carries a 3am resolution
  forward to the 8am pass rather than losing it.

CHIEF SPEAKS ONCE
  `announced_at` is the whole guard. Without it every resolved row
  re-announces on every pass, which is precisely how a notification
  surface teaches people to ignore it. And announcements roll up: five
  invoices paid overnight is ONE notification that says five, never
  five notifications — the lead-sweep doctrine, same as reorder.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

import sb_clients

logger = logging.getLogger("outcome_watch")

TABLE = "/chief_outcome_watches"

# How many open loops one pass will resolve. Generous — the set is
# small by construction (a loop leaves it as soon as it closes) — but
# bounded so a pathological tenant cannot make the pass unbounded.
MAX_RESOLVE_PER_PASS = 400

# Per business, per pass. Beyond this the roll-up says "and N more"
# rather than the pass emitting a wall of cards.
MAX_ANNOUNCE_PER_BUSINESS = 2

# Default windows, in days, when a kind has nothing better to go on.
# An invoice with a real due date uses THAT plus the grace below; these
# are the fallbacks, not the policy.
INVOICE_FALLBACK_DAYS = 14
INVOICE_GRACE_DAYS = 3
RESTOCK_DAYS = 10
CAMPAIGN_DAYS = 7
EMAIL_REPLY_DAYS = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _z(d: datetime) -> str:
    """PostgREST query-string form. A '+00:00' offset reads as a space
    once it is in a URL and the filter silently matches nothing."""
    return d.isoformat().replace("+00:00", "Z")


def _parse(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _days_between(a: Optional[datetime], b: Optional[datetime]) -> Optional[int]:
    if not a or not b:
        return None
    return max(0, int((b - a).total_seconds() // 86400))


def _plural(n: int, one: str, many: Optional[str] = None) -> str:
    return one if n == 1 else (many or one + "s")


def _money(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return f"${f:,.0f}" if f == int(f) else f"${f:,.2f}"


# ═══════════════════════════════════════════════════════════════════════
# THE RESOLVERS
#
# Each takes the watch row and `now`, re-reads the live table, and
# returns a verdict:
#
#   state  — 'open' (nothing decided yet), 'landed', 'missed', or
#            'void' (the subject went away or was cancelled; the loop
#            stops without a verdict, because "your deleted invoice
#            went unpaid" is noise, not news)
#   line   — one sentence quoting the evidence, for the notification
#   facts  — what was actually read, stored on the row so the panel and
#            any later dispute can see the numbers the verdict used
#   action — an action_payload for the one-tap next move, on a miss
#
# A resolver that cannot read its subject returns 'open', never a
# verdict. An outcome nobody could measure must not be reported as an
# outcome that did not happen.
# ═══════════════════════════════════════════════════════════════════════

def _verdict(state: str, line: str, facts: Optional[Dict[str, Any]] = None,
             action: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"state": state, "line": line, "facts": facts or {}, "action": action}


def _resolve_invoice_paid(w: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/invoices?id=eq.{w['subject_id']}&business_id=eq.{w['business_id']}"
        "&select=id,invoice_number,status,total,paid_at,sent_at,viewed_at,"
        "due_date,contact_id&limit=1") or []
    if not rows:
        return _verdict("void", "")
    inv = rows[0]
    status = (inv.get("status") or "").lower()
    number = inv.get("invoice_number") or "the invoice"
    amount = _money(inv.get("total"))
    who = _contact_name(w["business_id"], inv.get("contact_id"))
    to_who = f" to {who}" if who else ""

    if status in ("cancelled", "canceled", "void", "voided", "draft"):
        # Back to draft or cancelled after sending: the loop the
        # practitioner opened no longer exists to close.
        return _verdict("void", "")

    paid_at = _parse(inv.get("paid_at"))
    if paid_at or status == "paid":
        sent = _parse(inv.get("sent_at")) or _parse(w.get("opened_at"))
        days = _days_between(sent, paid_at or now)
        took = (f" — {days} {_plural(days, 'day')} after you sent it"
                if days is not None else "")
        return _verdict("landed",
                        f"{number}{to_who} was paid. {amount}{took}.",
                        {"total": inv.get("total"), "paid_at": inv.get("paid_at"),
                         "days_to_pay": days})

    due = _parse(w.get("due_at"))
    if due and now >= due:
        sent = _parse(inv.get("sent_at")) or _parse(w.get("opened_at"))
        ago = _days_between(sent, now)
        due_date = _parse(inv.get("due_date"))
        overdue = _days_between(due_date, now) if due_date else None
        # viewed_at is the difference between "they are ignoring you"
        # and "it never reached them", and the practitioner's next move
        # is not the same in those two cases. Say which one it is.
        seen = ("They've opened it." if inv.get("viewed_at")
                else "It hasn't been opened yet — worth checking it reached them.")
        bits = [f"{number}{to_who} — {amount}" if amount else f"{number}{to_who}"]
        if ago is not None:
            bits.append(f"sent {ago} {_plural(ago, 'day')} ago")
        if overdue:
            bits.append(f"{overdue} {_plural(overdue, 'day')} past due")
        line = ", ".join(bits) + f". Not paid. {seen}"
        action = None
        if inv.get("contact_id"):
            action = {"type": "draft_email",
                      "contact_id": str(inv["contact_id"]),
                      "subject": f"Following up on {number}",
                      "reason": (f"A friendly payment reminder for invoice "
                                 f"{number} ({amount}), which is still "
                                 f"unpaid. Warm, brief, no pressure.")}
        return _verdict("missed", line,
                        {"total": inv.get("total"), "days_since_sent": ago,
                         "days_overdue": overdue,
                         "viewed": bool(inv.get("viewed_at"))},
                        action)
    return _verdict("open", "")


def _resolve_restock_arrived(w: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/offerings?id=eq.{w['subject_id']}&business_id=eq.{w['business_id']}"
        "&select=id,name,inventory_qty,reorder_at,reorder_pending_at&limit=1") or []
    if not rows:
        return _verdict("void", "")
    o = rows[0]
    name = o.get("name") or "the product"
    qty = o.get("inventory_qty")

    # reorder_engine clears reorder_pending_at from every stock-RAISING
    # path the moment the restock lifts stock back above the reorder
    # point. That clear IS the arrival signal — this module does not
    # invent a second definition of "the stock came in".
    if not o.get("reorder_pending_at"):
        back = f" — {name} is back to {qty}" if qty is not None else ""
        return _verdict("landed", f"Your restock arrived{back}.",
                        {"inventory_qty": qty})

    due = _parse(w.get("due_at"))
    if due and now >= due:
        opened = _parse(w.get("opened_at"))
        ago = _days_between(opened, now)
        left = (f" — {qty} left" if isinstance(qty, int) else "")
        po = (w.get("outcome") or {}).get("po_number") or ""
        po_bit = f"{po} " if po else "The purchase order "
        return _verdict("missed",
                        f"{po_bit}went out {ago} {_plural(ago or 0, 'day')} ago "
                        f"and {name}'s stock hasn't moved{left}. Worth chasing "
                        f"the supplier.",
                        {"inventory_qty": qty, "days_since_order": ago})
    return _verdict("open", "")


def _resolve_campaign_replies(w: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/campaigns?id=eq.{w['subject_id']}&business_id=eq.{w['business_id']}"
        "&select=*&limit=1") or []
    if not rows:
        return _verdict("void", "")
    camp = rows[0]
    name = camp.get("name") or "the campaign"
    try:
        # campaigns_router owns what counts as a reply (and already
        # says out loud that this is activity among the audience, not
        # claimed attribution). Reusing it means the number the
        # follow-up quotes is the same number campaign_status quotes —
        # two definitions of "it worked" would be one too many.
        from campaigns_router import _campaign_results
        res = _campaign_results(camp)
    except Exception as e:
        logger.warning(f"[follow-through] campaign results failed: {e}")
        return _verdict("open", "")

    reached = res.get("people_reached") or 0
    replies = res.get("replies_since_launch") or 0
    bookings = res.get("bookings_since_launch") or 0
    facts = {"people_reached": reached, "replies": replies,
             "bookings": bookings, "emails_sent": res.get("emails_sent"),
             "texts_sent": res.get("texts_sent")}

    # A campaign is judged at its checkpoint, not the moment the first
    # reply lands — otherwise "1 reply" closes the loop and the other
    # 39 people are never reported on.
    due = _parse(w.get("due_at"))
    if not due or now < due:
        return _verdict("open", "")

    if replies or bookings:
        parts = []
        if replies:
            parts.append(f"{replies} {_plural(replies, 'reply', 'replies')}")
        if bookings:
            parts.append(f"{bookings} {_plural(bookings, 'booking')}")
        return _verdict("landed",
                        f"'{name}' — {' and '.join(parts)} from "
                        f"{reached} {_plural(reached, 'person', 'people')} reached.",
                        facts)
    return _verdict("missed",
                    f"'{name}' reached {reached} "
                    f"{_plural(reached, 'person', 'people')} and got no replies. "
                    f"The audience or the offer is worth another look.",
                    facts,
                    {"type": "campaign_status",
                     "campaign_id": str(camp.get("id"))})


def _resolve_email_reply(w: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    contact_id = w["subject_id"]
    opened = _parse(w.get("opened_at")) or now
    # email_sender writes `email_replied` when a reply lands and
    # sms_routing writes `sms_received`; campaigns_router already reads
    # exactly this pair. One definition of "they got back to you".
    ev = sb_clients.sb_get_as_service(
        f"/events?business_id=eq.{w['business_id']}"
        f"&contact_id=eq.{contact_id}"
        f"&created_at=gte.{_z(opened)}"
        f"&event_type=in.(email_replied,email_reply_received,sms_received)"
        f"&select=event_type,created_at&order=created_at.asc&limit=1") or []
    who = _contact_name(w["business_id"], contact_id) or "They"
    if ev:
        at = _parse(ev[0].get("created_at"))
        days = _days_between(opened, at)
        when = ("the same day" if days == 0
                else f"{days} {_plural(days or 0, 'day')} later"
                if days is not None else "since")
        return _verdict("landed", f"{who} wrote back — {when}.",
                        {"replied_at": ev[0].get("created_at"), "days": days})

    due = _parse(w.get("due_at"))
    if due and now >= due:
        ago = _days_between(opened, now)
        subject = (w.get("outcome") or {}).get("subject") or ""
        about = f' about "{subject}"' if subject else ""
        action = {"type": "draft_email", "contact_id": str(contact_id),
                  "subject": (f"Re: {subject}" if subject else "Following up"),
                  "reason": (f"A short, warm follow-up because they haven't "
                             f"replied in {ago} days. No pressure, just a nudge.")}
        return _verdict("missed",
                        f"You had me email {who}{about} {ago} "
                        f"{_plural(ago or 0, 'day')} ago. No reply yet.",
                        {"days_waiting": ago}, action)
    return _verdict("open", "")


def _contact_name(business_id: str, contact_id: Any) -> str:
    if not contact_id:
        return ""
    rows = sb_clients.sb_get_as_service(
        f"/contacts?id=eq.{contact_id}&business_id=eq.{business_id}"
        "&select=name&limit=1") or []
    return (rows[0].get("name") or "").strip() if rows else ""


# ═══════════════════════════════════════════════════════════════════════
# THE KIND REGISTRY
#
# `verb` is documentation of who opens this kind, not a gate — the
# opener passes the kind explicitly. `window` computes due_at at open
# time from whatever the subject itself knows (an invoice's own due
# date beats any flat window we could pick).
# ═══════════════════════════════════════════════════════════════════════

def _window_invoice(subject: Dict[str, Any], now: datetime) -> datetime:
    due = _parse(subject.get("due_date"))
    if due:
        return due + timedelta(days=INVOICE_GRACE_DAYS)
    return now + timedelta(days=INVOICE_FALLBACK_DAYS)


KINDS: Dict[str, Dict[str, Any]] = {
    "invoice_paid": {
        "verb": "send_invoice",
        "subject_type": "invoice",
        "resolver": _resolve_invoice_paid,
        "window": _window_invoice,
        "noun": "invoice",
    },
    "restock_arrived": {
        "verb": "send_purchase_order",
        "subject_type": "offering",
        "resolver": _resolve_restock_arrived,
        "window": lambda s, now: now + timedelta(days=RESTOCK_DAYS),
        "noun": "purchase order",
    },
    "campaign_replies": {
        "verb": "launch_campaign",
        "subject_type": "campaign",
        "resolver": _resolve_campaign_replies,
        "window": lambda s, now: now + timedelta(days=CAMPAIGN_DAYS),
        "noun": "campaign",
    },
    "email_reply": {
        "verb": "approve_draft",
        "subject_type": "contact",
        "resolver": _resolve_email_reply,
        "window": lambda s, now: now + timedelta(days=EMAIL_REPLY_DAYS),
        "noun": "email",
    },
}


# ═══════════════════════════════════════════════════════════════════════
# OPENING A LOOP
# ═══════════════════════════════════════════════════════════════════════

def open_watch(business_id: Any, kind: str, subject_id: Any, *,
               label: str = "", subject: Optional[Dict[str, Any]] = None,
               facts: Optional[Dict[str, Any]] = None,
               ledger_id: Optional[str] = None) -> bool:
    """Open one loop. Best-effort by construction: this is called from
    the success path of a send that has ALREADY happened, and a
    follow-up that failed to open must never turn a completed send into
    a reported failure. Returns whether the row landed.

    Idempotent through the partial unique index: a second open on a
    subject that already has an open loop is rejected by the database
    and reported here as a no-op, so two taps of "send it" cannot
    become two follow-ups nagging about the same money.
    """
    try:
        cfg = KINDS.get(kind)
        if not cfg or not business_id or not subject_id:
            return False
        now = _now()
        row = {
            "business_id": str(business_id),
            "kind": kind,
            "verb": cfg["verb"],
            "subject_type": cfg["subject_type"],
            "subject_id": str(subject_id),
            "label": (label or "")[:240],
            "opened_at": _iso(now),
            "due_at": _iso(cfg["window"](subject or {}, now)),
            "status": "open",
            "outcome": facts or {},
        }
        if ledger_id:
            row["ledger_id"] = str(ledger_id)
        written = sb_clients.sb_post_as_service(
            TABLE + "?select=id", row, prefer="return=representation")
        if not written:
            # Either the unique index refused a duplicate (expected and
            # fine) or the write genuinely failed. Both are non-fatal
            # here; DEBUG rather than ERROR because the common case is
            # the guard doing its job.
            logger.debug(f"[follow-through] no watch opened for {kind}/{subject_id}")
            return False
        return True
    except Exception as e:
        logger.warning(f"[follow-through] open_watch({kind}) failed (non-fatal): {e}")
        return False


async def open_watch_async(*args, **kwargs) -> bool:
    """Thread-offloaded open, for the async handlers that do the sends."""
    return await asyncio.to_thread(open_watch, *args, **kwargs)


# ═══════════════════════════════════════════════════════════════════════
# READING
# ═══════════════════════════════════════════════════════════════════════

def open_watches(business_id: str, limit: int = 25) -> List[Dict[str, Any]]:
    """Loops still open for this business, oldest first — the ones a
    practitioner would want chased are the ones that have been waiting
    longest."""
    return sb_clients.sb_get_as_service(
        f"{TABLE}?business_id=eq.{business_id}&status=eq.open"
        f"&order=due_at.asc&limit={limit}"
        "&select=id,kind,verb,subject_type,subject_id,label,opened_at,"
        "due_at,status,outcome") or []


def recent_closed(business_id: str, days: int = 14,
                  limit: int = 25) -> List[Dict[str, Any]]:
    """Loops that closed recently — how the last fortnight's actions
    actually landed."""
    cutoff = _z(_now() - timedelta(days=days))
    return sb_clients.sb_get_as_service(
        f"{TABLE}?business_id=eq.{business_id}"
        f"&status=in.(landed,missed)&resolved_at=gte.{cutoff}"
        f"&order=resolved_at.desc&limit={limit}"
        "&select=id,kind,verb,subject_type,subject_id,label,opened_at,"
        "due_at,status,outcome,resolved_at") or []


def summary(business_id: str) -> Dict[str, Any]:
    """The shape Chief's `follow_through` verb and the Home panel both
    read. One place computes it so the number in chat and the number on
    the card cannot disagree."""
    open_rows = open_watches(business_id, limit=50)
    closed = recent_closed(business_id, limit=50)
    now = _now()
    overdue = [w for w in open_rows
               if (_parse(w.get("due_at")) or now) < now]
    return {
        "open": open_rows,
        "closed": closed,
        "counts": {
            "open": len(open_rows),
            "overdue": len(overdue),
            "landed": sum(1 for c in closed if c.get("status") == "landed"),
            "missed": sum(1 for c in closed if c.get("status") == "missed"),
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# THE SWEEP
# ═══════════════════════════════════════════════════════════════════════

def _resolve_one(w: Dict[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
    """Resolve one watch and persist the verdict. Returns the verdict
    when the loop CLOSED this pass (so the caller can announce it),
    None when it is still open or the resolver failed."""
    cfg = KINDS.get(w.get("kind") or "")
    if not cfg:
        return None
    resolver: Callable[..., Dict[str, Any]] = cfg["resolver"]
    try:
        v = resolver(w, now)
    except Exception as e:
        logger.warning(f"[follow-through] resolver {w.get('kind')} raised "
                       f"for {str(w.get('id'))[:8]}: {e}")
        return None

    state = v.get("state") or "open"
    if state == "open":
        sb_clients.sb_patch_as_service(
            f"{TABLE}?id=eq.{w['id']}", {"checked_at": _iso(now)})
        return None

    patch: Dict[str, Any] = {
        "status": state,
        "checked_at": _iso(now),
        "resolved_at": _iso(now),
        # Merge, never replace: open_watch stored facts the resolver
        # cannot re-derive (the PO number, the email subject) and a
        # wholesale overwrite would drop them.
        "outcome": {**(w.get("outcome") or {}), **(v.get("facts") or {})},
    }
    if state == "void":
        # Nothing to say about a subject that no longer exists. Stamp
        # announced so the announce pass never picks it up.
        patch["announced_at"] = _iso(now)
    sb_clients.sb_patch_as_service(f"{TABLE}?id=eq.{w['id']}", patch)
    if state == "void":
        return None
    return {**v, "watch": w}


def _title_for(state: str, kind: str, n: int) -> str:
    cfg = KINDS.get(kind) or {}
    noun = cfg.get("noun") or "action"
    if n > 1:
        return (f"{n} things landed" if state == "landed"
                else f"{n} follow-ups need you")
    return ("That %s landed" % noun if state == "landed"
            else "Your %s hasn't landed" % noun)


async def _announce(client, business_id: str,
                    closed: List[Dict[str, Any]], now: datetime) -> int:
    """One notification per outcome kind per pass, capped. Misses ride
    the urgent-alert rail (they are actionable and inherit its
    per-business enable toggle); wins are their own low-priority type
    so a win can never wear the red icon."""
    from notification_engine import create_urgent_alert, _insert_notification

    wins = [c for c in closed if c["state"] == "landed" and c.get("line")]
    misses = [c for c in closed if c["state"] == "missed" and c.get("line")]
    sent = 0

    for group, state in ((misses, "missed"), (wins, "landed")):
        if not group or sent >= MAX_ANNOUNCE_PER_BUSINESS:
            continue
        head = group[0]
        kind = head["watch"].get("kind") or ""
        title = _title_for(state, kind, len(group))
        lines = [c["line"] for c in group[:3]]
        body = " ".join(lines)
        if len(group) > 3:
            body += f" And {len(group) - 3} more."

        ids = [str(c["watch"]["id"]) for c in group]
        ok = False
        if state == "missed":
            action = head.get("action")
            alert = await create_urgent_alert(
                client, business_id,
                title=title, body=body,
                # Per WATCH, not per business: two different unpaid
                # invoices are two different facts and must not
                # suppress each other. Chief still speaks once about
                # each, because announced_at retires the row.
                dedup_key=f"follow_through:{state}:{ids[0]}",
                dedup_hours=24 * 30,
                priority="high",
                suggested_action=(head.get("suggested") or
                                  ("Draft the follow-up" if action else None)),
                action_payload=action,
            )
            ok = bool(alert)
        else:
            inserted = await _insert_notification(client, business_id, {
                "type": "follow_through",
                "title": title[:200],
                "body": body[:2000],
                "priority": "low",
            })
            ok = bool(inserted)

        # Stamp announced ONLY on the rows this notification actually
        # covered. A row stamped without a notification is a loop that
        # closed and never got reported — the exact failure this
        # module exists to prevent, so the stamp follows the send.
        if ok:
            sent += 1
            for wid in ids:
                await asyncio.to_thread(
                    sb_clients.sb_patch_as_service,
                    f"{TABLE}?id=eq.{wid}", {"announced_at": _iso(now)})
        elif state == "missed":
            # create_urgent_alert returns None when the practitioner
            # has urgent alerts switched off, or on a dedup hit. Either
            # way this row will never be announced, and leaving it
            # unstamped means retrying it forever.
            for wid in ids:
                await asyncio.to_thread(
                    sb_clients.sb_patch_as_service,
                    f"{TABLE}?id=eq.{wid}", {"announced_at": _iso(now)})
    return sent


async def follow_through_sweep(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Hourly worker job. Two halves, deliberately split (see module
    docstring): resolve every open loop, then announce the closed ones
    that nobody has been told about — the second half only inside
    waking hours."""
    from notification_engine import _within_waking_hours
    now = now or _now()

    rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"{TABLE}?status=eq.open&order=due_at.asc"
        f"&limit={MAX_RESOLVE_PER_PASS}&select=*") or []

    closed_by_biz: Dict[str, List[Dict[str, Any]]] = {}
    for w in rows:
        v = await asyncio.to_thread(_resolve_one, w, now)
        if v:
            closed_by_biz.setdefault(str(w.get("business_id")), []).append(v)

    resolved = sum(len(v) for v in closed_by_biz.values())
    if not _within_waking_hours(now):
        # Everything resolved above stays announced_at IS NULL and is
        # picked up by the first waking pass. Nothing is lost by being
        # quiet at 3am.
        return {"open": len(rows), "resolved": resolved,
                "announced": 0, "skipped": "quiet_hours"}

    # Loops that closed on an EARLIER pass and were never announced —
    # resolved overnight, or announced-and-failed. They are the reason
    # the announce pass reads the table rather than only this pass's
    # results.
    pending = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"{TABLE}?status=in.(landed,missed)&announced_at=is.null"
        f"&order=resolved_at.asc&limit={MAX_RESOLVE_PER_PASS}&select=*") or []
    seen = {str(v["watch"].get("id")) for vs in closed_by_biz.values() for v in vs}
    for w in pending:
        if str(w.get("id")) in seen:
            continue
        cfg = KINDS.get(w.get("kind") or "")
        if not cfg:
            continue
        try:
            v = await asyncio.to_thread(cfg["resolver"], w, now)
        except Exception:
            continue
        # Re-resolved, not replayed. A loop that was recorded MISSED
        # overnight and has since been paid must be announced as the
        # win it now is — pairing the stored verdict with a freshly
        # written line is how you ship "unpaid" over evidence that
        # says paid. The fresh read wins, and the row is corrected.
        state = v.get("state")
        if state not in ("landed", "missed") or not v.get("line"):
            continue
        if state != w.get("status"):
            await asyncio.to_thread(
                sb_clients.sb_patch_as_service, f"{TABLE}?id=eq.{w['id']}",
                {"status": state, "resolved_at": _iso(now),
                 "outcome": {**(w.get("outcome") or {}), **(v.get("facts") or {})}})
        closed_by_biz.setdefault(str(w.get("business_id")), []).append(
            {**v, "watch": w})

    announced = 0
    if closed_by_biz:
        async with httpx.AsyncClient() as client:
            for bid, group in closed_by_biz.items():
                try:
                    announced += await _announce(client, bid, group, now)
                except Exception as e:
                    logger.exception(f"[follow-through] announce failed for {bid}: {e}")

    return {"open": len(rows), "resolved": resolved,
            "carried": len(pending), "announced": announced}


# ═══════════════════════════════════════════════════════════════════════
# CHIEF'S VERB
#
# The sweep is how Chief speaks first. This is how it answers when
# asked — "did that invoice ever get paid?", "how did last week land?"
# Both read summary() so the number in chat and the number on the Home
# card cannot disagree.
# ═══════════════════════════════════════════════════════════════════════

def _describe_open(w: Dict[str, Any], now: datetime) -> str:
    due = _parse(w.get("due_at"))
    label = w.get("label") or (KINDS.get(w.get("kind") or "") or {}).get("noun") or "an action"
    opened = _parse(w.get("opened_at"))
    ago = _days_between(opened, now)
    when = f" — {ago} {_plural(ago or 0, 'day')} ago" if ago else " — today"
    if due and now >= due:
        over = _days_between(due, now)
        return f"{label}{when}, and it's {over} {_plural(over or 0, 'day')} past when I'd expect an answer"
    return f"{label}{when}, still inside its window"


async def handle_follow_through(client, biz, action) -> Dict[str, Any]:
    """What Chief is still waiting on, and how the recently-closed loops
    landed. Pure read — every figure comes from the watch rows the sweep
    resolved against the live tables."""
    data = await asyncio.to_thread(summary, str(biz["id"]))
    counts = data["counts"]
    now = _now()

    if not data["open"] and not data["closed"]:
        return {
            "type": "follow_through",
            "result": ("nothing outstanding — I'm not waiting on any "
                       "invoice, order, campaign or reply right now. Once "
                       "you have me send something, I'll watch it and tell "
                       "you how it lands."),
            "label": "Nothing outstanding",
            "nav": {"tab": "home"},
        }

    lines: List[str] = []
    if data["open"]:
        overdue = [w for w in data["open"]
                   if (_parse(w.get("due_at")) or now) < now]
        lines.append(
            f"STILL OPEN ({counts['open']}"
            + (f", {counts['overdue']} past due" if overdue else "") + "):")
        # Past-due first — those are the ones with a decision attached.
        ordered = overdue + [w for w in data["open"] if w not in overdue]
        for w in ordered[:8]:
            lines.append("  • " + _describe_open(w, now))

    if data["closed"]:
        lines.append("")
        lines.append(f"CLOSED IN THE LAST FORTNIGHT "
                     f"({counts['landed']} landed, {counts['missed']} didn't):")
        for c in data["closed"][:8]:
            mark = "✓" if c.get("status") == "landed" else "✗"
            lines.append(f"  {mark} {c.get('label') or c.get('kind')}")

    label = (f"{counts['open']} open"
             + (f", {counts['overdue']} past due" if counts["overdue"] else ""))
    return {
        "type": "follow_through",
        "result": "\n".join(lines),
        "label": f"Follow-through — {label}",
        "nav": {"tab": "home"},
        "signal": {"follow_through_open": counts["open"],
                   "follow_through_overdue": counts["overdue"]},
    }
