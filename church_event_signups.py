"""church_event_signups.py — paid sign-ups for church events, with a waitlist.

The Church Menu Gaps check (https://claude.ai/artifact/4oXF1Be46RddJxXnKAHodn,
"The other doors", the Sunday card) found that RSVP had capacity and serving
roles but no payment and no waitlist, so Bible school, camp and a retreat
went through a paper form and a cash box. Kevin approved the build list and
said "ok continue" on 2026-10-27. Planning Center Registrations and Subsplash
event payments are the bar. Lane: Build, under "Love City leaves Subsplash
(M-1)".

    a SETUP ........ an event (one Services & Events entry) that takes sign-ups:
                     its ticket types (Adult $25, Child $10, Family $60 for 4
                     places; a $0 type is fine), how many places, a deadline,
                     the questions (allergies, T-shirt size, emergency
                     contact), whether a full event keeps a waitlist, how long
                     a waitlist offer lasts, and what to bring
    a SIGN-UP ...... one person's registration: their tickets, the places they
                     take, the amount the SERVER priced (a client-sent amount
                     is never read), their answers. Status is held, paid,
                     confirmed (free), waiting, offered, expired, cancelled or
                     refunded (supabase/APPLY-2026-10-27-church-event-signups.sql)
    a HOLD ......... while someone pays, their places are kept HOLD_MINUTES; the
                     Stripe Checkout page itself closes after CHECKOUT_MINUTES,
                     so a payment can't arrive long after the place went back
    the WAITLIST ... a full event's line, first come first served. When places
                     free up (a hold runs out, a refund, the office cancels one,
                     more places), the person at the front is offered a place:
                     an email (and a text when they asked for one) with a link
                     to pay within the event's offer_hours. A free place is
                     simply theirs. Who gets a place is decided in one locked
                     step per event in the database (church_event_take /
                     church_event_settle), so the last place goes to one person

PAID means Stripe said so: only the Connect webhook (stripe_connect_router →
record_checkout) marks a sign-up paid, after checking that the payment came
in on the connected Stripe account of the church the sign-up belongs to (as
gifts do since #1418; a church holds its own account's keys, so metadata
alone proves nothing), that the amount is the one the server priced, and
only from a held, offered, expired or cancelled sign-up — so a second
delivery of the same event changes nothing. A refund (charge.refunded) is
checked the same way; a full refund frees the places.

Refunds in v1 are made in the church's own Stripe dashboard: each paid
sign-up in the office links to its payment there, and the webhook brings the
refund back.

Free events (no setup) keep working exactly as before: the public RSVP and
the member app's "I'm coming". An event with an open setup refuses the free
RSVP for attending (serving in a role still works) and shows its sign-up.

  GET  /church/events/signups/status?business_id=          {enabled, can_price, connected}
  GET  /church/events/signups/summary?business_id=         each event's line for its card
  GET  /church/events/signups?business_id=&entry_id=       one event: setup, sign-ups, totals
  PUT  /church/events/signups/setup                        {business_id, entry_id, ...}   owner, admin
  POST /church/events/signups/{id}/cancel                  {business_id}                  owner, admin
  GET  /church/events/signups/export?business_id=&entry_id=   a CSV

  POST /public/events/{slug}/signup      {entry_id, tickets: {type_id: qty}, name, email, phone?,
                                          texts_ok?, answers?, waitlist?, request_id?}
  POST /public/events/{slug}/release     {entry_id, request_id}   give back a hold (Stripe's Back)
  GET  /public/events/{slug}/claim/{token}                        what a waitlist offer is for
  POST /public/events/{slug}/claim       {token}                  pay for an offered place
  GET  /public/events/{slug}/receipt/{session_id}                 what was bought (after Stripe)
  POST /my/events/signup                 the member app's form (a signed-in member)

Switched by CHURCH_PAID_SIGNUPS: off | owner | on, owner by default. Owner:
only a church owned by the platform owner can set a price or take a sign-up
(read from the owner's sign-in address, fail-closed). Off: no prices; an
event set up earlier shows "sign-ups aren't open online" rather than turning
free. Until the migration is applied, status says enabled: false, the office
routes answer 503 and free RSVP is unchanged; nothing 500s.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import html as _html
import io
import json
import logging
import os
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["church"])

HOLD_MINUTES = 40           # places kept while someone pays
CHECKOUT_MINUTES = 31       # Stripe's page closes first (its minimum is 30)
OFFER_HOURS = 24            # a waitlist offer's default window
OFFER_RANGE = (2, 72)
MAX_TYPES = 8
MAX_QUESTIONS = 10
MAX_OPTIONS = 12
MAX_SEATS = 20              # places one sign-up may take
MAX_PRICE_CENTS = 1_000_000
MAX_TOTAL_CENTS = 2_500_000
LABEL_MAX, QUESTION_MAX, OPTION_MAX, ANSWER_MAX, BRING_MAX = 60, 120, 40, 500, 500
NAME_MAX, EMAIL_MAX, PHONE_MAX = 120, 200, 40

STATUSES = ("held", "paid", "confirmed", "waiting", "offered", "expired", "cancelled", "refunded")
LIVE = ("held", "offered", "paid", "confirmed", "waiting")
QUESTION_KINDS = ("text", "choice", "yes_no")
VIEWERS = ("owner", "admin", "manager")     # who sees the sign-ups
KEEPERS = ("owner", "admin")                # who sets prices, cancels, exports

SETUP_FIELDS = "id,entry_id,open,capacity,deadline,questions,waitlist,offer_hours,bring,updated_at"
TYPE_FIELDS = "id,setup_id,label,price_cents,seats,max_per_signup,active,sort_order"
REG_FIELDS = ("id,entry_id,event_title,contact_id,name,email,phone,texts_ok,tickets,seats,amount_cents,answers,"
              "status,hold_expires_at,offered_at,paid_at,refunded_cents,refunded_at,stripe_payment_intent,"
              "source,created_at")
BIZ_FIELDS = "id,name,type,owner_id,settings,stripe_account_id"


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_PAID_SIGNUPS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def _platform_email() -> str:
    return (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()


_OWNER_TTL = 600
_owner_seen: Dict[str, Tuple[float, bool]] = {}


def _owner_email(owner_id: str) -> Optional[str]:
    """The sign-in address of a business's owner, or None when it can't be
    read (never a guess)."""
    import httpx
    base = sb_clients.sb_url()
    if not base:
        return None
    try:
        r = httpx.get(f"{base}/auth/v1/admin/users/{uuid.UUID(str(owner_id))}",
                      headers=sb_clients.sb_headers_service(), timeout=10)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    return str((r.json() or {}).get("email") or "").strip().lower() or None


def owned_by_platform_owner(biz: Dict[str, Any]) -> bool:
    """Fail-closed: an address that can't be read is "no" (and asked again
    next time; only a real answer is kept for ten minutes)."""
    oid = str((biz or {}).get("owner_id") or "")
    if not oid:
        return False
    seen = _owner_seen.get(oid)
    if seen and time.time() - seen[0] < _OWNER_TTL:
        return seen[1]
    email = _owner_email(oid)
    if email is None:
        return False
    yes = email == _platform_email()
    _owner_seen[oid] = (time.time(), yes)
    return yes


def business_open(biz: Dict[str, Any]) -> bool:
    """May this church set prices and take sign-ups? on: every church;
    owner: a church the platform owner owns; off: none."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        return owned_by_platform_owner(biz)
    return False


# ─── Small things ─────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _at(v: Any) -> Optional[datetime]:
    s = str(v or "").strip().replace("Z", "+00:00")
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def _uuid(v: Any, what: str = "event") -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, f"That {what} isn't one we know.")


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _need(path: str) -> List[Dict[str, Any]]:
    """A read that must answer: a failed one (or the tables before their
    migration) is a 503, never an empty list of sign-ups."""
    rows = _rows(path)
    if rows is None:
        raise HTTPException(503, "Sign-ups couldn't be read just now. Try again.")
    return rows


def money(cents: Any) -> str:
    c = int(cents or 0)
    return f"${c // 100:,}" if c % 100 == 0 else f"${c / 100:,.2f}"


def tables_ready(biz_id: str) -> bool:
    return _rows(f"/church_event_registrations?business_id=eq.{_q(biz_id)}&select=id&limit=1") is not None


def _business(biz_id: str) -> Optional[Dict[str, Any]]:
    rows = _rows(f"/businesses?id=eq.{_q(biz_id)}&select={BIZ_FIELDS}&limit=1")
    if rows is None:
        raise HTTPException(503, "The church couldn't be read just now. Try again.")
    return rows[0] if rows else None


def _can_charge(biz: Dict[str, Any]) -> bool:
    import payments_core
    return payments_core.can_charge(biz)


# ─── The event (a Services & Events entry) ────────────────────────────

def _event(biz_id: str, entry_id: str) -> Optional[Dict[str, Any]]:
    """An active entry of one of this church's Services & Events rooms, with
    its title, day and place read through the room's own fields. None when
    it isn't one (another church's entry included)."""
    import events_rsvp_router as er
    rows = _rows(f"/module_entries?id=eq.{_q(entry_id)}&business_id=eq.{_q(biz_id)}&status=eq.active"
                 "&select=id,module_id,data,updated_at&limit=1")
    if rows is None:
        raise HTTPException(503, "That event couldn't be read just now. Try again.")
    if not rows:
        return None
    entry = rows[0]
    mods = _rows(f"/custom_modules?id=eq.{_q(entry.get('module_id'))}&business_id=eq.{_q(biz_id)}"
                 "&archetype=eq.event_roster&is_active=eq.true&select=id,name,archetype_params&limit=1")
    if mods is None:
        raise HTTPException(503, "That event couldn't be read just now. Try again.")
    if not mods:
        return None
    f = er.resolve_fields(mods[0].get("archetype_params"))
    data = entry.get("data") or {}
    day = er._parse_day(data.get(f["date_field"]))
    return {
        "id": str(entry["id"]), "module_id": str(entry.get("module_id")), "data": data, "fields": f,
        "title": _plain(data.get(f["title_field"]), 200) or "Event",
        "date": day.isoformat() if day else None,
        "date_label": f"{day.strftime('%A, %B')} {day.day}" if day else "",
        "location": _plain(data.get(f["location_field"]), 200),
        "capacity_field": data.get(f["capacity_field"]),
    }


# ─── Setups ───────────────────────────────────────────────────────────

def setups_for(biz_id: str, entry_ids: Optional[Iterable[str]] = None) -> Optional[Dict[str, Dict[str, Any]]]:
    """{entry_id: setup with its "types"} for a church, or None when the
    tables can't be read (before the migration, or a blip)."""
    path = f"/church_event_signup_setups?business_id=eq.{_q(biz_id)}&select={SETUP_FIELDS}&limit=500"
    ids = sorted({str(e) for e in (entry_ids or []) if e})
    if entry_ids is not None:
        if not ids:
            return {}
        path += f"&entry_id=in.({','.join(_q(i) for i in ids)})"
    rows = _rows(path)
    if rows is None:
        return None
    out = {str(s["entry_id"]): {**s, "types": []} for s in rows}
    if not out:
        return out
    by_setup = {str(s["id"]): s for s in out.values()}
    types = _rows(f"/church_event_ticket_types?business_id=eq.{_q(biz_id)}"
                  f"&setup_id=in.({','.join(_q(i) for i in by_setup)})&select={TYPE_FIELDS}&limit=2000")
    if types is None:
        return None
    for t in sorted(types, key=lambda t: (int(t.get("sort_order") or 0), str(t.get("label") or "").lower())):
        s = by_setup.get(str(t.get("setup_id")))
        if s is not None:
            s["types"].append(t)
    return out


def _setup(biz_id: str, entry_id: str) -> Optional[Dict[str, Any]]:
    got = setups_for(biz_id, [entry_id])
    if got is None:
        raise HTTPException(503, "Sign-ups couldn't be read just now. Try again.")
    return got.get(str(entry_id))


def active_types(setup: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [t for t in (setup or {}).get("types") or [] if t.get("active", True) is not False]


def blocks_free_rsvp(business_id: str, entry_id: str) -> bool:
    """An event with an open setup takes its sign-ups (and payment) through
    the sign-up, not the free RSVP. A read that fails, or tables that don't
    exist yet, block nothing: free RSVP stays exactly as it was."""
    try:
        got = setups_for(str(business_id), [str(entry_id)])
    except Exception:
        return False
    s = (got or {}).get(str(entry_id))
    return bool(s and s.get("open") and active_types(s))


# ─── Pure rules (unit-tested) ─────────────────────────────────────────

def clean_types(raw: Any) -> List[Dict[str, Any]]:
    """What a place costs. One to MAX_TYPES types; a price in cents from $0
    to $10,000; places per ticket (a family ticket takes 4); an optional
    most-per-sign-up."""
    if not isinstance(raw, list) or not raw:
        raise HTTPException(400, "Add at least one ticket (it can be free).")
    if len(raw) > MAX_TYPES:
        raise HTTPException(400, f"An event has at most {MAX_TYPES} kinds of ticket.")
    out: List[Dict[str, Any]] = []
    seen = set()
    for i, t in enumerate(raw):
        if not isinstance(t, dict):
            raise HTTPException(400, "That ticket doesn't look right.")
        label = _plain(t.get("label"), LABEL_MAX)
        if not label:
            raise HTTPException(400, "Name each ticket (Adult, Child, Family).")
        if label.lower() in seen:
            raise HTTPException(400, f"\"{label}\" is listed twice.")
        seen.add(label.lower())
        try:
            price = int(t.get("price_cents"))
            seats = int(t.get("seats") or 1)
            most = t.get("max_per_signup")
            most = None if most in (None, "", 0) else int(most)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Check the price and places for {label}.")
        if not 0 <= price <= MAX_PRICE_CENTS:
            raise HTTPException(400, f"{label}'s price is from $0 to $10,000.")
        if not 1 <= seats <= MAX_SEATS:
            raise HTTPException(400, f"One {label} ticket takes from 1 to {MAX_SEATS} places.")
        if most is not None and not 1 <= most <= MAX_SEATS:
            raise HTTPException(400, f"The most {label} tickets in one sign-up is from 1 to {MAX_SEATS}.")
        tid = t.get("id")
        try:
            tid = str(uuid.UUID(str(tid))) if tid else None
        except (ValueError, TypeError):
            tid = None
        out.append({"id": tid, "label": label, "price_cents": price, "seats": seats,
                    "max_per_signup": most, "sort_order": i})
    return out


def _question_id(raw: Any, taken: set) -> str:
    qid = str(raw or "")
    if not re.fullmatch(r"q[a-z0-9]{1,16}", qid) or qid in taken:
        qid = "q" + uuid.uuid4().hex[:8]
    taken.add(qid)
    return qid


def clean_questions(raw: Any) -> List[Dict[str, Any]]:
    """The questions a sign-up answers: a line of text, a choice (T-shirt
    size) or yes/no, each optional or required."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_QUESTIONS:
        raise HTTPException(400, f"An event asks at most {MAX_QUESTIONS} questions.")
    out, ids = [], set()
    for q in raw:
        if not isinstance(q, dict):
            raise HTTPException(400, "That question doesn't look right.")
        label = _plain(q.get("label"), QUESTION_MAX)
        if not label:
            continue
        kind = q.get("kind") or "text"
        if kind not in QUESTION_KINDS:
            raise HTTPException(400, "A question is a line of text, a choice or yes/no.")
        item: Dict[str, Any] = {"id": _question_id(q.get("id"), ids), "label": label, "kind": kind,
                                "required": q.get("required") is True}
        if kind == "choice":
            opts, seen = [], set()
            for o in q.get("options") or []:
                o = _plain(o, OPTION_MAX)
                if o and o.lower() not in seen:
                    seen.add(o.lower())
                    opts.append(o)
            if not 2 <= len(opts) <= MAX_OPTIONS:
                raise HTTPException(400, f"\"{label}\" needs from 2 to {MAX_OPTIONS} choices.")
            item["options"] = opts
        out.append(item)
    return out


def clean_answers(questions: List[Dict[str, Any]], raw: Any) -> Dict[str, str]:
    """Answers to this event's own questions only, each checked against its
    kind; a required one left blank is refused by name."""
    raw = raw if isinstance(raw, dict) else {}
    out: Dict[str, str] = {}
    for q in questions or []:
        v = str(raw.get(q["id"]) or "").strip()[:ANSWER_MAX]
        if q.get("kind") == "yes_no":
            v = v.lower() if v.lower() in ("yes", "no") else ""
        elif q.get("kind") == "choice":
            v = next((o for o in q.get("options") or [] if o.lower() == v.lower()), "")
        if not v and q.get("required"):
            raise HTTPException(400, f"Please answer: {q['label']}")
        if v:
            out[q["id"]] = v
    return out


def price_order(types: List[Dict[str, Any]], picks: Any) -> Tuple[List[Dict[str, Any]], int, int]:
    """(lines, places, amount in cents) for the tickets someone chose, from
    the event's own prices. The only place an amount is worked out: the
    client sends ticket counts, never money."""
    if not isinstance(picks, dict):
        raise HTTPException(400, "Choose your tickets.")
    by_id = {str(t["id"]): t for t in types if t.get("active", True) is not False}
    lines: List[Dict[str, Any]] = []
    seats = amount = 0
    for tid, raw in picks.items():
        try:
            qty = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(400, "Choose how many of each ticket.")
        if qty == 0:
            continue
        t = by_id.get(str(tid))
        if t is None:
            raise HTTPException(400, "That ticket isn't one this event offers.")
        most = t.get("max_per_signup") or MAX_SEATS
        if qty < 0 or qty > most:
            raise HTTPException(400, f"Choose from 1 to {most} {t['label']} tickets.")
        each = int(t.get("seats") or 1)
        price = int(t.get("price_cents") or 0)
        lines.append({"type_id": str(t["id"]), "label": t["label"], "qty": qty, "price_cents": price,
                      "seats": each, "_order": int(t.get("sort_order") or 0)})
        seats += qty * each
        amount += qty * price
    if not lines:
        raise HTTPException(400, "Choose at least one ticket.")
    if seats > MAX_SEATS:
        raise HTTPException(400, f"One sign-up holds up to {MAX_SEATS} places. For a bigger group, call the church office.")
    if amount > MAX_TOTAL_CENTS:
        raise HTTPException(400, "That's more than one sign-up can pay online. Call the church office.")
    lines.sort(key=lambda l: (l.pop("_order"), l["label"].lower()))
    return lines, seats, amount


def tally(regs: List[Dict[str, Any]], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Counts for one event's sign-ups, by the database's own rule: paid and
    free sign-ups take places, and so do holds and offers that haven't run
    out (church_event_taken)."""
    now = now or _now()
    t = {"taken": 0, "paid": 0, "paid_seats": 0, "paid_cents": 0, "confirmed": 0, "confirmed_seats": 0,
         "held": 0, "held_seats": 0, "offered": 0, "waiting": 0, "waiting_seats": 0,
         "refunded": 0, "refunded_cents": 0}
    for r in regs or []:
        st, seats = r.get("status"), int(r.get("seats") or 0)
        live_hold = st in ("held", "offered") and (_at(r.get("hold_expires_at")) or now) > now
        if st in ("paid", "confirmed") or live_hold:
            t["taken"] += seats
        if st == "paid":
            t["paid"] += 1
            t["paid_seats"] += seats
            t["paid_cents"] += int(r.get("amount_cents") or 0)
        elif st == "confirmed":
            t["confirmed"] += 1
            t["confirmed_seats"] += seats
        elif st == "held" and live_hold:
            t["held"] += 1
            t["held_seats"] += seats
        elif st == "offered" and live_hold:
            t["offered"] += 1
        elif st == "waiting":
            t["waiting"] += 1
            t["waiting_seats"] += seats
        if int(r.get("refunded_cents") or 0):
            t["refunded_cents"] += int(r.get("refunded_cents") or 0)
            if st == "refunded":
                t["refunded"] += 1
    t["collected_cents"] = t["paid_cents"] - t["refunded_cents"] + sum(
        int(r.get("amount_cents") or 0) for r in regs or [] if r.get("status") == "refunded")
    return t


def capacity_of(setup: Dict[str, Any], event: Optional[Dict[str, Any]] = None) -> Optional[int]:
    try:
        n = int(setup.get("capacity")) if setup.get("capacity") is not None else None
    except (TypeError, ValueError):
        n = None
    return n if n and n > 0 else None


def public_view(setup: Dict[str, Any], counts: Dict[str, Any], *, now: Optional[datetime] = None,
                event_day: Optional[str] = None, open_here: bool = True, tz: Optional[str] = None) -> Dict[str, Any]:
    """What the public page and the member app show for one event's sign-up.
    `closed` names why no one can sign up now: paused (the switch), closed,
    deadline, past."""
    now = now or _now()
    types = active_types(setup)
    cap = capacity_of(setup)
    taken = int(counts.get("taken") or 0)
    waiting = int(counts.get("waiting") or 0)
    left = None if cap is None else max(0, cap - taken)
    full = (cap is not None and left == 0) or waiting > 0
    deadline = _at(setup.get("deadline"))
    closed = None
    if not open_here:
        closed = "paused"
    elif not setup.get("open") or not types:
        closed = "closed"
    elif deadline and deadline <= now:
        closed = "deadline"
    elif event_day and event_day < now.date().isoformat():
        closed = "past"
    prices = [int(t.get("price_cents") or 0) for t in types]
    return {
        "setup_id": str(setup.get("id") or ""),
        "closed": closed,
        "types": [{"id": str(t["id"]), "label": t["label"], "price_cents": int(t.get("price_cents") or 0),
                   "seats": int(t.get("seats") or 1), "max": int(t.get("max_per_signup") or MAX_SEATS)}
                  for t in types],
        "price_from": min(prices) if prices else 0,
        "priced": any(p > 0 for p in prices),
        "questions": setup.get("questions") or [],
        "capacity": cap,
        "places_left": 0 if (full and cap is not None) else left,
        "full": bool(full),
        "waitlist": bool(setup.get("waitlist")),
        "waiting": waiting,
        "deadline": _iso(deadline) if deadline else None,
        "deadline_label": deadline_words(_iso(deadline), tz) if deadline else "",
        "offer_hours": int(setup.get("offer_hours") or OFFER_HOURS),
        "bring": str(setup.get("bring") or ""),
    }


def price_words(view: Dict[str, Any]) -> str:
    """'Free', '$25', or 'Adult $25 · Child $10'."""
    types = view.get("types") or []
    if not types:
        return ""
    if not view.get("priced"):
        return "Free"
    if len(types) == 1:
        return money(types[0]["price_cents"])
    return " · ".join(f"{t['label']} {money(t['price_cents']) if t['price_cents'] else 'free'}" for t in types)


def lines_words(lines: Any) -> str:
    """'2 Adult, 1 Child'."""
    return ", ".join(f"{int(l.get('qty') or 0)} {l.get('label')}" for l in (lines or []) if isinstance(l, dict))


def deadline_words(iso: Optional[str], tz: Optional[str] = None) -> str:
    d = _at(iso)
    if not d:
        return ""
    try:
        from zoneinfo import ZoneInfo
        d = d.astimezone(ZoneInfo(tz)) if tz else d
    except Exception:
        pass
    return f"{d.strftime('%a, %b')} {d.day}"


def stripe_payment_link(pi: Optional[str]) -> Optional[str]:
    """The payment in the church's own Stripe dashboard (refunds in v1)."""
    if not pi:
        return None
    from stripe_connect_helpers import is_live_mode
    return f"https://dashboard.stripe.com/{'' if is_live_mode() else 'test/'}payments/{_q(pi)}"


# ─── Registrations ────────────────────────────────────────────────────

def _regs(biz_id: str, entry_ids: Iterable[str], statuses: Optional[Iterable[str]] = None,
          fields: str = REG_FIELDS, limit: int = 2000) -> Optional[List[Dict[str, Any]]]:
    ids = sorted({str(e) for e in entry_ids if e})
    if not ids:
        return []
    st = f"&status=in.({','.join(statuses)})" if statuses else ""
    return _rows(f"/church_event_registrations?business_id=eq.{_q(biz_id)}"
                 f"&entry_id=in.({','.join(_q(i) for i in ids)}){st}&select={fields}&order=created_at.asc&limit={limit}")


def _reg(path_filter: str) -> Optional[Dict[str, Any]]:
    rows = _rows(f"/church_event_registrations?{path_filter}&select=*&limit=1")
    if rows is None:
        raise HTTPException(503, "That sign-up couldn't be read just now. Try again.")
    return rows[0] if rows else None


def _rpc(name: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    out = sb_clients.sb_post_as_service(f"/rpc/{name}", args)
    return out if isinstance(out, dict) else None


def settle(biz_id: str, entry_id: str) -> List[Dict[str, Any]]:
    """Give back what ran out and move the waitlist; returns who was just
    offered or confirmed (and tells them). Fail-soft: [] when it can't."""
    out = _rpc("church_event_settle", {"p_business": str(biz_id), "p_entry": str(entry_id)})
    offers = list((out or {}).get("offers") or [])
    if offers:
        tell_offers(str(biz_id), str(entry_id), offers)
    return offers


def annotate(business_id: str, occasions: List[Dict[str, Any]], contact_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Adds o["signup"] (public_view, and o["signup"]["mine"] for a member)
    to each occasion that takes sign-ups. Never raises: a read that fails
    leaves the occasions as they were."""
    try:
        ids = [str(o.get("entry_id")) for o in occasions or [] if o.get("entry_id")]
        if not ids:
            return occasions
        setups = setups_for(str(business_id), ids)
        if not setups:
            return occasions
        biz = _business(str(business_id)) or {}
        here = business_open(biz)
        tz = _church_tz(str(business_id))
        regs = _regs(str(business_id), list(setups), LIVE,
                     fields="id,entry_id,contact_id,status,seats,amount_cents,tickets,hold_expires_at,"
                            "refunded_cents,created_at") or []
        now = _now()
        for o in occasions:
            s = setups.get(str(o.get("entry_id")))
            if not s or not s.get("open"):
                continue
            mine_rows = [r for r in regs if str(r["entry_id"]) == str(s["entry_id"])]
            view = public_view(s, tally(mine_rows, now), now=now, event_day=o.get("date"), open_here=here, tz=tz)
            if contact_id:
                view["mine"] = _mine(mine_rows, contact_id, now)
                if view["mine"] and view["mine"].get("hold_expires_at"):
                    view["mine"]["until_label"] = _until_words(view["mine"]["hold_expires_at"], tz)
            o["signup"] = view
    except Exception:
        logger.warning("[signups] annotate failed (fail-soft)", exc_info=True)
    return occasions


def _mine(rows: List[Dict[str, Any]], contact_id: str, now: datetime) -> Optional[Dict[str, Any]]:
    """This member's own sign-up for the event: the newest live one."""
    mine = [r for r in rows if str(r.get("contact_id") or "") == str(contact_id)]
    for r in sorted(mine, key=lambda r: str(r.get("created_at") or ""), reverse=True):
        st = r.get("status")
        if st in ("held", "offered") and (_at(r.get("hold_expires_at")) or now) <= now:
            continue
        out = {"id": r["id"], "status": st, "lines": r.get("tickets") or [], "seats": r.get("seats"),
               "amount_cents": r.get("amount_cents"), "hold_expires_at": r.get("hold_expires_at")}
        if st == "waiting":
            ahead = [x for x in rows if x.get("status") == "waiting"
                     and str(x.get("created_at") or "") < str(r.get("created_at") or "")]
            out["position"] = len(ahead) + 1
        return out
    return None


# ─── Starting a sign-up ───────────────────────────────────────────────

def _find_or_create_person(biz_id: str, name: str, email: str) -> Optional[str]:
    """The person's contact, by email within the church (the RSVP's own
    discipline); None when that write fails (the sign-up still stands)."""
    import events_rsvp_router as er
    try:
        pattern = _q(er._escape_ilike(email))
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(biz_id)}&email=ilike.{pattern}&select=id&limit=1") or []
        if rows:
            return rows[0]["id"]
        made = sb_clients.sb_post_as_service("/contacts", {
            "business_id": biz_id, "name": name or email.split("@")[0], "email": email,
            "status": "lead", "source": "event_signup", "last_interaction": _iso(_now()),
        })
        if isinstance(made, list) and made:
            return made[0]["id"]
    except Exception as e:
        logger.warning(f"[signups] contact find-or-create failed: {e}")
    return None


def _clean_phone(v: Any) -> Optional[str]:
    s = re.sub(r"[^0-9+()\-. ]", "", str(v or "")).strip()[:PHONE_MAX]
    return s or None


def prepare(biz: Dict[str, Any], ev: Dict[str, Any], setup: Dict[str, Any], body: Dict[str, Any], *,
            source: str, me: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Everything church_event_take needs, checked and priced here. Raises
    HTTPException with a sentence a person can act on."""
    if me:
        name = _plain(me.get("name"), NAME_MAX) or "A member"
        email = str(me.get("email") or "").strip().lower()[:EMAIL_MAX]
    else:
        name = _plain(body.get("name"), NAME_MAX)
        email = str(body.get("email") or "").strip().lower()[:EMAIL_MAX]
        if not name:
            raise HTTPException(400, "Please tell us your name.")
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "That email doesn't look right.")
    lines, seats, amount = price_order(active_types(setup), body.get("tickets"))
    answers = clean_answers(setup.get("questions") or [], body.get("answers"))
    if amount > 0 and not _can_charge(biz):
        raise HTTPException(409, "This church can't take payments online right now. Please call the church office.")
    phone = _clean_phone(body.get("phone") if not me else (body.get("phone") or me.get("phone")))
    texts_ok = bool(phone) and body.get("texts_ok") in (True, "true", "on", "yes", "1")
    rid = str(body.get("request_id") or "").strip()
    key = f"{source}:{rid}" if re.fullmatch(r"[A-Za-z0-9-]{8,64}", rid) else None
    contact_id = str(me["id"]) if me else _find_or_create_person(str(biz["id"]), name, email)
    return {"name": name, "email": email, "phone": phone, "texts_ok": texts_ok, "tickets": lines,
            "seats": seats, "amount_cents": amount, "answers": answers, "source": source,
            "request_key": key, "contact_id": contact_id, "event_title": ev["title"][:200]}


def take(biz_id: str, entry_id: str, row: Dict[str, Any], waitlist: bool) -> Dict[str, Any]:
    out = _rpc("church_event_take", {"p_business": str(biz_id), "p_entry": str(entry_id), "p_row": row,
                                     "p_waitlist": bool(waitlist), "p_hold_minutes": HOLD_MINUTES})
    if out is None:
        raise HTTPException(503, "Sign-ups couldn't be saved just now. Please try again in a minute.")
    offers = list(out.get("offers") or [])
    if offers:
        tell_offers(str(biz_id), str(entry_id), offers)
    return out


def _release(reg_id: str, biz_id: str) -> None:
    """A hold whose payment page never opened gives its places back."""
    sb_clients.sb_patch_as_service(
        f"/church_event_registrations?id=eq.{_q(reg_id)}&business_id=eq.{_q(biz_id)}&status=eq.held",
        {"status": "cancelled", "updated_at": _iso(_now())})


async def open_checkout(biz: Dict[str, Any], ev_title: str, reg_id: str, entry_id: str,
                        lines: List[Dict[str, Any]], email: str, *, success_url: str, cancel_url: str,
                        expires_at: datetime) -> Dict[str, Any]:
    """Stripe Checkout on the church's own connected account, for the
    lines the server priced. Saves the session on the sign-up."""
    from payments_core import provider_for
    session = await provider_for(biz).create_event_signup_checkout(
        biz, registration_id=str(reg_id), business_id=str(biz["id"]), entry_id=str(entry_id),
        event_title=ev_title, lines=lines, customer_email=email,
        success_url=success_url, cancel_url=cancel_url, expires_at=int(expires_at.timestamp()))
    url = (session or {}).get("url")
    if not url or not (session or {}).get("id"):
        raise RuntimeError("no checkout url")
    await asyncio.to_thread(sb_clients.sb_patch_as_service,
                            f"/church_event_registrations?id=eq.{_q(reg_id)}&business_id=eq.{_q(biz['id'])}",
                            {"stripe_session_id": session["id"], "checkout_url": url,
                             "stripe_account_id": biz.get("stripe_account_id"), "updated_at": _iso(_now())})
    return session


def _fail(status: int, code: str, detail: str, **extra) -> JSONResponse:
    return JSONResponse({"ok": False, "code": code, "detail": detail, **extra}, status_code=status)


CLOSED_WORDS = {
    "paused": "Sign-ups for this event aren't open online right now. Please call the church office.",
    "closed": "Sign-ups for this event are closed.",
    "deadline": "Sign-ups for this event have closed.",
    "past": "This event has already happened.",
    "none": "This event doesn't take sign-ups online.",
}


def waitlist_words(hours: int) -> str:
    return (f"If a place opens, we'll email you a link to pay. You'll have {hours} hours to take it before "
            "it goes to the next person. You won't be charged unless you take it.")


async def run_signup(biz: Dict[str, Any], ev: Dict[str, Any], setup: Dict[str, Any], body: Dict[str, Any], *,
                     source: str, me: Optional[Dict[str, Any]], return_base: str, success_path: str,
                     cancel_path: str) -> Dict[str, Any]:
    """The whole sign-up, shared by the public page and the member app:
    price it, decide the place under the event's lock, then open Stripe for
    a held place. Returns {kind: checkout|confirmed|waiting|already|full|closed, ...}."""
    view = public_view(setup, {}, event_day=ev.get("date"), open_here=True)
    if view["closed"] in ("closed", "past"):
        return {"kind": "closed", "why": view["closed"]}
    row = await asyncio.to_thread(prepare, biz, ev, setup, body, source=source, me=me)
    want_wait = body.get("waitlist") in (True, "true", "on", "yes", "1")
    got = await asyncio.to_thread(take, str(biz["id"]), ev["id"], row, want_wait)
    state = got.get("state")
    if state == "held":
        try:
            await open_checkout(biz, ev["title"], got["id"], ev["id"], row["tickets"], row["email"],
                                success_url=return_base + success_path, cancel_url=return_base + cancel_path,
                                expires_at=_now() + timedelta(minutes=CHECKOUT_MINUTES))
        except HTTPException:
            await asyncio.to_thread(_release, got["id"], str(biz["id"]))
            raise
        except Exception as e:
            logger.warning(f"[signups] checkout open failed biz={str(biz['id'])[:8]}: {e}")
            await asyncio.to_thread(_release, got["id"], str(biz["id"]))
            raise HTTPException(502, "We couldn't open the payment page. Please try again.")
        reg = await asyncio.to_thread(_reg, f"id=eq.{_q(got['id'])}&business_id=eq.{_q(biz['id'])}")
        return {"kind": "checkout", "url": (reg or {}).get("checkout_url"), "id": got["id"]}
    if state == "already":
        st = got.get("status")
        if st == "held" and got.get("checkout_url") and (_at(got.get("hold_expires_at")) or _now()) > _now():
            return {"kind": "checkout", "url": got["checkout_url"], "id": got["id"]}
        if st in ("paid", "confirmed", "waiting", "offered"):
            return {"kind": "already", "status": st, "id": got["id"]}
        return {"kind": "closed", "why": "stale"}
    if state == "confirmed":
        tell_confirmed(str(biz["id"]), ev, {**row, "id": got["id"], "status": "confirmed"}, setup)
        return {"kind": "confirmed", "id": got["id"], "lines": row["tickets"], "amount_cents": 0}
    if state == "waiting":
        tell_waiting(str(biz["id"]), ev, {**row, "id": got["id"]}, int(got.get("position") or 1),
                     int(setup.get("offer_hours") or OFFER_HOURS))
        return {"kind": "waiting", "id": got["id"], "position": int(got.get("position") or 1),
                "offer_hours": int(setup.get("offer_hours") or OFFER_HOURS)}
    if state == "full":
        return {"kind": "full", "waitlist": bool(got.get("waitlist"))}
    return {"kind": "closed", "why": got.get("why") or "closed"}


# ─── The public page's routes ─────────────────────────────────────────

def _limited(bucket: str, request: Request) -> bool:
    import rate_limit
    return not rate_limit.allow_strict(bucket, rate_limit.trusted_client_ip(request))


def _public_church(slug: str) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """(site, business, roster modules) for a public slug, gated like the
    events page itself."""
    import events_rsvp_router as er
    sites = _rows(f"/business_sites?slug=eq.{_q(slug)}&order=updated_at.desc&limit=1"
                  "&select=business_id,slug,site_config")
    if sites is None:
        raise HTTPException(503, "Please try again in a minute.")
    if not sites:
        raise HTTPException(404, "not found")
    biz = _business(str(sites[0]["business_id"]))
    if not biz:
        raise HTTPException(404, "not found")
    modules = er.roster_modules_for(str(biz["id"]))
    if not er.events_public_is_active(biz, modules):
        raise HTTPException(404, "event signups aren't available here")
    return sites[0], biz, modules


def _return_base(site: Dict[str, Any], request: Request) -> str:
    from giving_router import app_return_base
    return app_return_base(site.get("slug") or "", site.get("site_config"), request.headers.get("origin") or "")


def _public_result(out: Dict[str, Any], setup: Dict[str, Any]) -> Any:
    kind = out["kind"]
    if kind == "checkout":
        return {"ok": True, "url": out["url"]}
    if kind == "confirmed":
        return {"ok": True, "confirmed": True, "lines": out.get("lines") or [],
                "bring": str(setup.get("bring") or "")}
    if kind == "waiting":
        return {"ok": True, "waiting": True, "position": out["position"],
                "next": waitlist_words(out["offer_hours"])}
    if kind == "already":
        words = {"paid": "You're already signed up and paid.", "confirmed": "You're already signed up.",
                 "waiting": "You're already on the waitlist.", "offered": "A place is waiting for you: check your email for the link to pay."}
        return {"ok": True, "already": True, "status": out["status"], "detail": words.get(out["status"], "")}
    if kind == "full":
        return _fail(409, "full", "This event just filled up." + (" You can join the waitlist." if out.get("waitlist") else ""),
                     waitlist=bool(out.get("waitlist")))
    why = out.get("why") or "closed"
    if why == "stale":
        return _fail(409, "stale", "That sign-up timed out. Please start again.")
    return _fail(409, "closed", CLOSED_WORDS.get(why, CLOSED_WORDS["closed"]))


@router.post("/public/events/{slug}/signup")
async def public_signup(slug: str, body: Dict[str, Any], request: Request):
    """Anonymous: sign up for one event (and pay on Stripe when it costs).
    Rate-limited first, before any read or write."""
    import events_rsvp_router as er
    if _limited("event_signup", request):
        raise HTTPException(429, "Too many tries. Please wait a few minutes, then try again.")
    body = body if isinstance(body, dict) else {}
    entry_id = _uuid(body.get("entry_id"))
    site, biz, _mods = await asyncio.to_thread(_public_church, slug)
    if not business_open(biz):
        return _fail(409, "closed", CLOSED_WORDS["paused"])
    ev = await asyncio.to_thread(_event, str(biz["id"]), entry_id)
    if not ev or not er.is_public(ev["data"]):
        raise HTTPException(404, "that event wasn't found")
    setup = await asyncio.to_thread(_setup, str(biz["id"]), entry_id)
    if not setup:
        return _fail(409, "closed", CLOSED_WORDS["none"])
    base = await asyncio.to_thread(_return_base, site, request)
    out = await run_signup(biz, ev, setup, body, source="public", me=None, return_base=base,
                           success_path="/events?signed_up={CHECKOUT_SESSION_ID}",
                           cancel_path=f"/events?signup_back={entry_id}")
    return _public_result(out, setup)


@router.post("/public/events/{slug}/release")
async def public_release(slug: str, body: Dict[str, Any], request: Request):
    """Stripe's Back button: the person's own browser (it alone knows the
    request id) gives their unpaid hold back at once."""
    if _limited("event_signup_read", request):
        raise HTTPException(429, "Too many tries. Please wait a few minutes, then try again.")
    body = body if isinstance(body, dict) else {}
    entry_id = _uuid(body.get("entry_id"))
    rid = str(body.get("request_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", rid):
        raise HTTPException(400, "Nothing to give back.")
    _site, biz, _m = await asyncio.to_thread(_public_church, slug)
    done = await asyncio.to_thread(
        sb_clients.sb_patch_as_service,
        f"/church_event_registrations?business_id=eq.{_q(biz['id'])}&entry_id=eq.{_q(entry_id)}"
        f"&request_key=eq.{_q('public:' + rid)}&status=eq.held",
        {"status": "cancelled", "updated_at": _iso(_now())})
    if isinstance(done, list) and done:
        await asyncio.to_thread(settle, str(biz["id"]), entry_id)
    return {"ok": True, "released": bool(isinstance(done, list) and done)}


def _token_hash(token: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", token or ""):
        raise HTTPException(404, "That link isn't one we know.")
    return hashlib.sha256(token.encode()).hexdigest()


def _summary(reg: Dict[str, Any], ev: Optional[Dict[str, Any]], setup: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What a person may see about their own sign-up on a public page: no
    one else's name, their first name only."""
    return {
        "status": reg.get("status"),
        "title": (ev or {}).get("title") or reg.get("event_title") or "",
        "date_label": (ev or {}).get("date_label") or "",
        "location": (ev or {}).get("location") or "",
        "lines": [{"label": l.get("label"), "qty": l.get("qty")} for l in reg.get("tickets") or [] if isinstance(l, dict)],
        "amount_cents": int(reg.get("amount_cents") or 0),
        "bring": str((setup or {}).get("bring") or ""),
        "first": _plain(reg.get("name"), NAME_MAX).split(" ")[0],
        "hold_expires_at": reg.get("hold_expires_at"),
    }


def _offer_for(biz_id: str, token: str) -> Dict[str, Any]:
    reg = _reg(f"business_id=eq.{_q(biz_id)}&claim_hash=eq.{_token_hash(token)}")
    if not reg:
        raise HTTPException(404, "That link isn't one we know.")
    return reg


@router.get("/public/events/{slug}/claim/{token}")
async def public_claim_view(slug: str, token: str, request: Request):
    if _limited("event_signup_read", request):
        raise HTTPException(429, "Too many tries. Please wait a few minutes, then try again.")
    _site, biz, _m = await asyncio.to_thread(_public_church, slug)
    reg = await asyncio.to_thread(_offer_for, str(biz["id"]), token)
    ev = await asyncio.to_thread(_event, str(biz["id"]), str(reg["entry_id"]))
    setup = await asyncio.to_thread(_setup, str(biz["id"]), str(reg["entry_id"]))
    out = _summary(reg, ev, setup)
    if reg.get("status") == "offered" and (_at(reg.get("hold_expires_at")) or _now()) <= _now():
        out["status"] = "expired"
    return {"ok": True, **out}


@router.post("/public/events/{slug}/claim")
async def public_claim(slug: str, body: Dict[str, Any], request: Request):
    """Pay for a place the waitlist offered. The amount is the one priced
    when they joined the line; the place stays theirs while Stripe's page
    is open."""
    if _limited("event_signup", request):
        raise HTTPException(429, "Too many tries. Please wait a few minutes, then try again.")
    body = body if isinstance(body, dict) else {}
    site, biz, _m = await asyncio.to_thread(_public_church, slug)
    if not business_open(biz):
        return _fail(409, "closed", CLOSED_WORDS["paused"])
    reg = await asyncio.to_thread(_offer_for, str(biz["id"]), str(body.get("token") or ""))
    base = await asyncio.to_thread(_return_base, site, request)
    out = await claim(biz, reg, return_base=base, success_path="/events?signed_up={CHECKOUT_SESSION_ID}",
                      cancel_path="/events")
    return out


async def claim(biz: Dict[str, Any], reg: Dict[str, Any], *, return_base: str, success_path: str,
                cancel_path: str) -> Any:
    st = reg.get("status")
    if st == "paid":
        return {"ok": True, "already": True, "status": "paid", "detail": "You're already signed up and paid."}
    until = _at(reg.get("hold_expires_at"))
    now = _now()
    if st != "offered" or not until or until <= now:
        return _fail(410, "gone", "That place has gone to the next person on the waitlist. "
                                  "Please call the church office if you still want to come.")
    if not _can_charge(biz):
        return _fail(409, "closed", "This church can't take payments online right now. Please call the church office.")
    # The page stays open up to the offer's end (at least Stripe's minimum,
    # at most its 24 hours); the place is kept at least as long as the page.
    closes = min(max(until, now + timedelta(minutes=CHECKOUT_MINUTES)), now + timedelta(hours=23, minutes=50))
    keep = max(until, closes + timedelta(minutes=HOLD_MINUTES - CHECKOUT_MINUTES))
    await asyncio.to_thread(sb_clients.sb_patch_as_service,
                            f"/church_event_registrations?id=eq.{_q(reg['id'])}&business_id=eq.{_q(biz['id'])}&status=eq.offered",
                            {"hold_expires_at": _iso(keep), "updated_at": _iso(now)})
    ev = await asyncio.to_thread(_event, str(biz["id"]), str(reg["entry_id"]))
    try:
        await open_checkout(biz, (ev or {}).get("title") or reg.get("event_title") or "Event", reg["id"],
                            str(reg["entry_id"]), reg.get("tickets") or [], reg.get("email") or "",
                            success_url=return_base + success_path, cancel_url=return_base + cancel_path,
                            expires_at=closes)
    except Exception as e:
        logger.warning(f"[signups] claim checkout failed biz={str(biz['id'])[:8]}: {e}")
        raise HTTPException(502, "We couldn't open the payment page. Please try again.")
    fresh = await asyncio.to_thread(_reg, f"id=eq.{_q(reg['id'])}&business_id=eq.{_q(biz['id'])}")
    return {"ok": True, "url": (fresh or {}).get("checkout_url")}


@router.get("/public/events/{slug}/receipt/{session_id}")
async def public_receipt(slug: str, session_id: str, request: Request):
    """After Stripe: what was bought. Pending until the verified webhook
    lands (seconds); the page asks again."""
    if _limited("event_signup_read", request):
        raise HTTPException(429, "Too many tries. Please wait a few minutes, then try again.")
    if not re.fullmatch(r"cs_[A-Za-z0-9_]{10,200}", session_id or ""):
        raise HTTPException(404, "not found")
    _site, biz, _m = await asyncio.to_thread(_public_church, slug)
    reg = await asyncio.to_thread(_reg, f"business_id=eq.{_q(biz['id'])}&stripe_session_id=eq.{_q(session_id)}")
    if not reg:
        raise HTTPException(404, "not found")
    ev = await asyncio.to_thread(_event, str(biz["id"]), str(reg["entry_id"]))
    setup = await asyncio.to_thread(_setup, str(biz["id"]), str(reg["entry_id"]))
    out = _summary(reg, ev, setup)
    out["state"] = "paid" if reg.get("status") == "paid" else "pending"
    return {"ok": True, **out}


# ─── The member app's form ────────────────────────────────────────────

@router.post("/my/events/signup", include_in_schema=False)
async def member_signup(request: Request):
    """A signed-in member signs up (or pays for an offered place) from
    Coming up. Same-origin form POST, the member's own record, the member
    rate limit; back to Coming up with a short code, or on to Stripe."""
    import member_portal_church as mpc
    from fastapi.responses import RedirectResponse
    church, me, unavailable = await mpc._signed_in(request)
    form = await request.form()
    if unavailable:
        return mpc._back("/my/events", err="preview" if unavailable == "preview" else "error")
    if not me:
        return mpc._back("/my")
    if not mpc._allowed(church, me):
        return mpc._back("/my/events", err="slow")
    biz_id = str(church["business"]["id"])
    try:
        entry_id = _uuid(form.get("entry_id"))
        biz = await asyncio.to_thread(_business, biz_id)
        if not biz or not business_open(biz):
            return mpc._back("/my/events", err="signup_closed")
        ev = await asyncio.to_thread(_event, biz_id, entry_id)
        if not ev or not mpc.can_see(ev["data"], ev["fields"], me):
            return mpc._back("/my/events", err="gone")
        from giving_router import app_return_base
        base = app_return_base(church["site"].get("slug") or "", church["site"].get("site_config"),
                               request.headers.get("origin") or "")
        if form.get("claim"):
            regs = await asyncio.to_thread(
                _rows, f"/church_event_registrations?business_id=eq.{_q(biz_id)}&entry_id=eq.{_q(entry_id)}"
                       f"&contact_id=eq.{_q(me['id'])}&status=eq.offered&select=*&limit=1")
            if not regs:
                return mpc._back("/my/events", err="signup_gone")
            out = await claim(biz, regs[0], return_base=base, success_path="/my/events?done=signup_paid",
                              cancel_path="/my/events")
            if isinstance(out, dict) and out.get("url"):
                return RedirectResponse(out["url"], status_code=303)
            return mpc._back("/my/events", err="signup_gone")
        setup = await asyncio.to_thread(_setup, biz_id, entry_id)
        if not setup:
            return mpc._back("/my/events", err="signup_closed")
        tickets = {k[4:]: v for k, v in form.items() if k.startswith("qty_")}
        answers = {k[2:]: v for k, v in form.items() if k.startswith("a_")}
        body = {"tickets": tickets, "answers": answers, "phone": form.get("phone"),
                "texts_ok": form.get("texts_ok"), "waitlist": form.get("waitlist"),
                "request_id": form.get("request_id")}
        out = await run_signup(biz, ev, setup, body, source="member", me=me, return_base=base,
                               success_path="/my/events?done=signup_paid", cancel_path="/my/events")
    except HTTPException as e:
        return mpc._back("/my/events", err={400: "signup_check", 409: "signup_closed", 404: "gone",
                                            429: "slow"}.get(e.status_code, "error"))
    kind = out["kind"]
    if kind == "checkout" and out.get("url"):
        return RedirectResponse(out["url"], status_code=303)
    if kind == "confirmed":
        return mpc._back("/my/events", done="signup_done")
    if kind == "waiting":
        return mpc._back("/my/events", done="signup_waiting")
    if kind == "already":
        return mpc._back("/my/events", done="signup_already")
    if kind == "full":
        return mpc._back("/my/events", err="signup_full")
    return mpc._back("/my/events", err="signup_closed")


# ─── The Connect webhook (stripe_connect_router calls these) ──────────

def _account_matches(business_id: Any, account_id: Optional[str]) -> bool:
    if not business_id or not account_id:
        return False
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{_q(business_id)}&select=stripe_account_id&limit=1") or []
    return bool(rows) and rows[0].get("stripe_account_id") == account_id


def record_checkout(session: Dict[str, Any], account_id: Optional[str]) -> Optional[str]:
    """checkout.session.completed for a sign-up. Marks it paid only when the
    payment came in on the connected account of the church the sign-up is
    for, for the amount the server priced. Raises (the webhook answers 500,
    records the error, and the sign-up stays unpaid) on any mismatch. A
    sign-up already paid is left alone, so a repeated event is a no-op.
    Returns the business id when it changed something."""
    md = session.get("metadata") or {}
    reg_id = str(md.get("source_id") or "")
    try:
        uuid.UUID(reg_id)
    except ValueError:
        raise ValueError("Sign-up payment without a sign-up id")
    if session.get("payment_status") != "paid":
        logger.info(f"[signups] session {session.get('id')} not paid yet ({session.get('payment_status')})")
        return None
    rows = sb_clients.sb_get_as_service(
        f"/church_event_registrations?id=eq.{_q(reg_id)}&select=*&limit=1")
    if not isinstance(rows, list):
        raise ValueError("Sign-ups couldn't be read")
    if not rows:
        raise ValueError("Sign-up payment for a sign-up we don't have")
    reg = rows[0]
    biz_id = str(reg.get("business_id") or "")
    if str(md.get("business_id") or "") != biz_id:
        raise ValueError("Sign-up payment names a different church")
    if not _account_matches(biz_id, account_id):
        raise ValueError("Sign-up paid on a different payment account")
    if (session.get("currency") or "usd").lower() != "usd" or int(session.get("amount_total") or 0) < int(reg.get("amount_cents") or 0):
        raise ValueError("Sign-up payment doesn't match its price")
    if reg.get("status") == "paid":
        return None
    now = _iso(_now())
    done = sb_clients.sb_patch_as_service(
        f"/church_event_registrations?id=eq.{_q(reg_id)}&business_id=eq.{_q(biz_id)}"
        "&status=in.(held,offered,expired,cancelled)",
        {"status": "paid", "paid_at": now, "updated_at": now, "stripe_session_id": session.get("id"),
         "stripe_payment_intent": session.get("payment_intent"), "stripe_account_id": account_id,
         "hold_expires_at": None})
    if done is None:
        raise ValueError("Sign-up couldn't be marked paid")
    if not done:
        return None     # paid by another delivery a moment ago, or refunded
    try:
        ev = _event(biz_id, str(reg["entry_id"]))
        setup = (setups_for(biz_id, [str(reg["entry_id"])]) or {}).get(str(reg["entry_id"]))
        tell_confirmed(biz_id, ev or {"title": reg.get("event_title") or "your event"}, {**reg, "status": "paid"}, setup or {})
    except Exception:
        logger.warning("[signups] paid confirmation failed (fail-soft)", exc_info=True)
    return biz_id


ANY_ACCOUNT = object()


def record_refund(charge: Dict[str, Any], account_id: Any = ANY_ACCOUNT) -> Optional[str]:
    """charge.refunded for a sign-up: the refunded amount; a full refund
    gives the places back (and moves the waitlist). Only the church whose
    account refunded it is touched."""
    md = charge.get("metadata") or {}
    reg_id = str(md.get("source_id") or "")
    try:
        uuid.UUID(reg_id)
    except ValueError:
        return None
    rows = sb_clients.sb_get_as_service(f"/church_event_registrations?id=eq.{_q(reg_id)}&select=*&limit=1")
    if not isinstance(rows, list):
        raise ValueError("Sign-ups couldn't be read")
    if not rows:
        return None
    reg = rows[0]
    biz_id = str(reg.get("business_id") or "")
    if account_id is not ANY_ACCOUNT and not _account_matches(biz_id, account_id):
        logger.warning(f"[signups] refund of {reg_id} from another account; ignored")
        return None
    cents = int(charge.get("amount_refunded") or 0)
    full = bool(charge.get("refunded")) or cents >= int(reg.get("amount_cents") or 0) > 0
    patch: Dict[str, Any] = {"refunded_cents": cents, "refunded_at": _iso(_now()), "updated_at": _iso(_now())}
    if full and reg.get("status") == "paid":
        patch["status"] = "refunded"
    sb_clients.sb_patch_as_service(f"/church_event_registrations?id=eq.{_q(reg_id)}&business_id=eq.{_q(biz_id)}", patch)
    if patch.get("status") == "refunded":
        settle(biz_id, str(reg["entry_id"]))
    return biz_id


def sweep_tick() -> int:
    """Every few minutes (the leader): holds and offers that ran out give
    their places back, and the waitlist moves. Quiet before the migration."""
    if mode() == "off":
        return 0
    rows = _rows(f"/church_event_registrations?status=in.(held,offered)&hold_expires_at=lt.{_q(_iso(_now()))}"
                 "&select=business_id,entry_id&limit=500")
    if not rows:
        return 0
    pairs = sorted({(str(r["business_id"]), str(r["entry_id"])) for r in rows})
    n = 0
    for biz_id, entry_id in pairs:
        try:
            n += len(settle(biz_id, entry_id))
        except Exception:
            logger.warning("[signups] sweep settle failed", exc_info=True)
    return n


# ─── Telling people ───────────────────────────────────────────────────

def _run(coro) -> None:
    """Fire and forget from a request (a running loop), or run to the end
    from a worker thread (the sweep, a thread a route handed work to)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    try:
        if loop:
            loop.create_task(coro)
        else:
            asyncio.run(coro)
    except Exception:
        logger.warning("[signups] notification failed (fail-soft)", exc_info=True)


async def _send_email(biz_id: str, to: str, name: str, subject: str, html_body: str, key: str) -> None:
    from email_sender import send_via_resend
    rows = await asyncio.to_thread(_rows, f"/businesses?id=eq.{_q(biz_id)}&select=name&limit=1")
    church = ((rows or [{}])[0].get("name") or "Your church").strip()
    try:
        await send_via_resend(
            to_email=to, to_name=name or None,
            from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
            from_name=church, subject=subject.replace("{church}", church), body=html_body,
            reply_to=None, business_id=biz_id, idempotency_key=key[:200])
    except Exception as e:
        logger.warning(f"[signups] email failed (fail-soft): {e}")


async def _send_text(biz_id: str, to: str, message: str) -> None:
    import httpx
    import sms_service
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            await sms_service.send_sms_core(client, business_id=biz_id, to=to, message=message, sent_by="system")
    except Exception as e:
        logger.warning(f"[signups] text failed (fail-soft): {e}")


def _e(s: Any) -> str:
    return _html.escape(str(s or ""), quote=True)


def _event_lines(ev: Dict[str, Any]) -> str:
    bits = [b for b in (ev.get("date_label"), ev.get("location")) if b]
    return f"<p>{_e(' · '.join(bits))}</p>" if bits else ""


def confirmation_email(ev: Dict[str, Any], reg: Dict[str, Any], setup: Dict[str, Any]) -> Tuple[str, str]:
    first = _plain(reg.get("name"), NAME_MAX).split(" ")[0] or "Friend"
    amount = int(reg.get("amount_cents") or 0)
    paid = f" &mdash; {money(amount)} paid" if amount and reg.get("status") == "paid" else ""
    bring = str((setup or {}).get("bring") or "").strip()
    body = (f"<p>Hi {_e(first)},</p><p>You're signed up for <strong>{_e(ev.get('title'))}</strong>.</p>"
            f"{_event_lines(ev)}<p>{_e(lines_words(reg.get('tickets')))}{paid}</p>"
            + (f"<p><strong>What to bring:</strong> {_e(bring)}</p>" if bring else "")
            + "<p>See you there!</p>")
    return f"You're signed up for {ev.get('title')}", body


def waitlist_email(ev: Dict[str, Any], reg: Dict[str, Any], position: int, hours: int) -> Tuple[str, str]:
    first = _plain(reg.get("name"), NAME_MAX).split(" ")[0] or "Friend"
    body = (f"<p>Hi {_e(first)},</p><p><strong>{_e(ev.get('title'))}</strong> is full, so you're on the "
            f"waitlist: number {position}.</p>{_event_lines(ev)}<p>{_e(lines_words(reg.get('tickets')))}</p>"
            f"<p>{_e(waitlist_words(hours))}</p>")
    return f"You're on the waitlist for {ev.get('title')}", body


def offer_email(ev: Dict[str, Any], offer: Dict[str, Any], link: str, until_words: str) -> Tuple[str, str]:
    first = _plain(offer.get("name"), NAME_MAX).split(" ")[0] or "Friend"
    body = (f"<p>Hi {_e(first)},</p><p>A place opened up at <strong>{_e(ev.get('title'))}</strong>, and it's "
            f"yours if you want it.</p>{_event_lines(ev)}"
            f"<p>{_e(lines_words(offer.get('tickets')))} &mdash; {money(offer.get('amount_cents'))}</p>"
            f"<p><a href=\"{_e(link)}\">Pay and keep my place</a></p>"
            f"<p>Please pay by {_e(until_words)}. After that, the place goes to the next person on the waitlist.</p>")
    return f"A place opened up at {ev.get('title')}", body


def _church_tz(biz_id: str) -> Optional[str]:
    try:
        import outside_calendar
        return outside_calendar.business_timezone(biz_id)
    except Exception:
        return None


def _until_words(iso: Any, tz: Optional[str]) -> str:
    d = _at(iso)
    if not d:
        return "the time in your email"
    try:
        from zoneinfo import ZoneInfo
        d = d.astimezone(ZoneInfo(tz)) if tz else d
    except Exception:
        pass
    return f"{d.strftime('%A, %B')} {d.day} at {d.strftime('%I:%M %p').lstrip('0')}"


def _events_url(biz_id: str) -> str:
    from business_sites_helpers import PUBLIC_DOMAIN
    rows = _rows(f"/business_sites?business_id=eq.{_q(biz_id)}&order=updated_at.desc&select=slug&limit=1") or []
    slug = (rows[0].get("slug") if rows else "") or ""
    return f"https://{slug}.{PUBLIC_DOMAIN}/events"


def tell_offers(biz_id: str, entry_id: str, offers: List[Dict[str, Any]]) -> None:
    """The waitlist moved: an offer (email, and a text when they asked) or a
    free place confirmed."""
    try:
        ev = _event(biz_id, entry_id) or {"title": "your event"}
    except Exception:
        ev = {"title": "your event"}
    tz = _church_tz(biz_id)
    url = _events_url(biz_id)
    setup = None
    for o in offers:
        if not o.get("email"):
            continue
        if o.get("status") == "confirmed":
            if setup is None:
                setup = (setups_for(biz_id, [entry_id]) or {}).get(entry_id) or {}
            subject, body = confirmation_email(ev, {**o, "status": "confirmed"}, setup)
            _run(_send_email(biz_id, o["email"], o.get("name") or "", subject, body, f"evs-confirmed-{o['id']}"))
            continue
        token = o.get("token")
        if not token:
            continue
        link = f"{url}?claim={token}"
        until = _until_words(o.get("hold_expires_at"), tz)
        subject, body = offer_email(ev, o, link, until)
        _run(_send_email(biz_id, o["email"], o.get("name") or "", subject, body, f"evs-offer-{o['id']}-{token[:12]}"))
        if o.get("texts_ok") and o.get("phone"):
            _run(_send_text(biz_id, str(o["phone"]),
                            f"A place opened up at {ev.get('title')}. Pay by {until} to keep it: {link}"))


def tell_confirmed(biz_id: str, ev: Dict[str, Any], reg: Dict[str, Any], setup: Dict[str, Any]) -> None:
    if not reg.get("email"):
        return
    subject, body = confirmation_email(ev, reg, setup)
    _run(_send_email(biz_id, reg["email"], reg.get("name") or "", subject, body,
                     f"evs-{reg.get('status')}-{reg.get('id')}"))


def tell_waiting(biz_id: str, ev: Dict[str, Any], reg: Dict[str, Any], position: int, hours: int) -> None:
    if not reg.get("email"):
        return
    subject, body = waitlist_email(ev, reg, position, hours)
    _run(_send_email(biz_id, reg["email"], reg.get("name") or "", subject, body, f"evs-waiting-{reg.get('id')}"))
    if reg.get("texts_ok") and reg.get("phone"):
        try:
            from sms_service import normalize_phone
            phone = normalize_phone(str(reg["phone"]))
            if phone:
                sb_clients.sb_post_as_service("/sms_consents", {
                    "phone": phone, "name": _plain(reg.get("name"), NAME_MAX) or None,
                    "source": "event_waitlist", "business_id": biz_id})
        except Exception:
            logger.warning("[signups] text consent not recorded (fail-soft)", exc_info=True)


# ─── The office ───────────────────────────────────────────────────────

def _in_office(biz_id: str, uid: str, role: str) -> bool:
    """The owner and admins always; a manager login when Who sees what is
    off, or its areas are the whole church or include the Office."""
    if role in KEEPERS:
        return True
    import church_areas
    if church_areas.mode() != "on":
        return True
    view = church_areas.my_areas(biz_id, uid, role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    return view.get("areas") is None or "office" in (view.get("areas") or [])


def _office(business_id: Any, user: AuthedUser, *, keep: bool = False) -> Dict[str, Any]:
    import business_access
    import church_follow_up as cfu
    biz_id = _uuid(business_id, "church")
    role = business_access.assert_access(biz_id, user, "viewer")
    biz = _business(biz_id)
    if not biz or not cfu.is_church(biz):
        raise HTTPException(404, "Sign-ups are for churches")
    if not business_open(biz):
        raise HTTPException(404, "Not Found")
    if role not in VIEWERS or not _in_office(biz_id, str(user.id), role):
        raise HTTPException(403, "Event sign-ups belong to the office. An admin can add the Office to your areas.")
    if keep and role not in KEEPERS:
        raise HTTPException(403, "Only the owner and admins can change sign-ups and prices.")
    return {"biz": biz, "role": role, "uid": str(user.id)}


@router.get("/church/events/signups/status")
def signups_status(business_id: str, user: AuthedUser = Depends(require_user)):
    """Quietly false for a closed switch, a business that isn't a church, a
    login outside the office, or tables not made yet."""
    try:
        me = _office(business_id, user)
    except HTTPException as e:
        if e.status_code == 503:
            raise
        return {"enabled": False, "can_price": False, "connected": False}
    if not tables_ready(me["biz"]["id"]):
        return {"enabled": False, "can_price": False, "connected": False}
    return {"enabled": True, "can_price": me["role"] in KEEPERS, "connected": _can_charge(me["biz"])}


@router.get("/church/events/signups/summary")
def signups_summary(business_id: str, user: AuthedUser = Depends(require_user)):
    """Each event that takes sign-ups, in a line for its card."""
    me = _office(business_id, user)
    biz_id = me["biz"]["id"]
    setups = setups_for(biz_id)
    if setups is None:
        raise HTTPException(503, "Sign-ups couldn't be read just now. Try again.")
    regs = _regs(biz_id, list(setups), LIVE, fields="entry_id,status,seats,amount_cents,hold_expires_at,refunded_cents")
    if regs is None:
        raise HTTPException(503, "Sign-ups couldn't be read just now. Try again.")
    now = _now()
    out = {}
    for eid, s in setups.items():
        t = tally([r for r in regs if str(r["entry_id"]) == eid], now)
        v = public_view(s, t, now=now)
        out[eid] = {"open": bool(s.get("open")), "price": price_words(v), "priced": v["priced"],
                    "paid": t["paid"], "confirmed": t["confirmed"], "held": t["held"] + t["offered"],
                    "waiting": t["waiting"], "taken": t["taken"], "capacity": v["capacity"],
                    "places_left": v["places_left"]}
    return {"entries": out}


def _reg_view(r: Dict[str, Any], position: Optional[int], now: datetime) -> Dict[str, Any]:
    st = r.get("status")
    if st in ("held", "offered") and (_at(r.get("hold_expires_at")) or now) <= now:
        st = "expired"
    return {
        "id": r["id"], "name": r.get("name"), "email": r.get("email"), "phone": r.get("phone"),
        "contact_id": r.get("contact_id"), "status": st, "seats": int(r.get("seats") or 0),
        "lines": r.get("tickets") or [], "amount_cents": int(r.get("amount_cents") or 0),
        "refunded_cents": int(r.get("refunded_cents") or 0), "answers": r.get("answers") or {},
        "created_at": r.get("created_at"), "paid_at": r.get("paid_at"), "hold_expires_at": r.get("hold_expires_at"),
        "source": r.get("source"), "position": position,
        "stripe_link": stripe_payment_link(r.get("stripe_payment_intent")) if st in ("paid", "refunded") else None,
    }


def detail(me: Dict[str, Any], entry_id: str) -> Dict[str, Any]:
    biz = me["biz"]
    biz_id = str(biz["id"])
    ev = _event(biz_id, entry_id)
    if not ev:
        raise HTTPException(404, "That event isn't one of this church's.")
    setup = _setup(biz_id, entry_id)
    regs = _need(f"/church_event_registrations?business_id=eq.{_q(biz_id)}&entry_id=eq.{_q(entry_id)}"
                 f"&select={REG_FIELDS}&order=created_at.asc&limit=3000") if setup else []
    now = _now()
    t = tally(regs, now)
    queue = [r["id"] for r in regs if r.get("status") == "waiting"]
    view = public_view(setup, t, now=now, event_day=ev.get("date")) if setup else None
    cap_field = ev.get("capacity_field")
    try:
        roster_cap = int(cap_field) if cap_field not in (None, "") else None
    except (TypeError, ValueError):
        roster_cap = None
    return {
        "enabled": True, "can_price": me["role"] in KEEPERS, "connected": _can_charge(biz),
        "event": {"id": ev["id"], "title": ev["title"], "date": ev["date"], "date_label": ev["date_label"],
                  "location": ev["location"], "capacity": roster_cap},
        "setup": ({k: setup.get(k) for k in ("id", "open", "capacity", "deadline", "questions", "waitlist",
                                               "offer_hours", "bring", "updated_at")} if setup else None),
        "types": ([{k: x.get(k) for k in ("id", "label", "price_cents", "seats", "max_per_signup", "active")}
                   for x in setup.get("types") or []] if setup else []),
        "view": view,
        "registrations": [_reg_view(r, (queue.index(r["id"]) + 1) if r["id"] in queue else None, now)
                          for r in regs],
        "totals": t,
        "hold_minutes": HOLD_MINUTES,
    }


@router.get("/church/events/signups")
def signups_detail(business_id: str, entry_id: str, user: AuthedUser = Depends(require_user)):
    me = _office(business_id, user)
    entry_id = _uuid(entry_id)
    if _setup(str(me["biz"]["id"]), entry_id):
        settle(str(me["biz"]["id"]), entry_id)
    return detail(me, entry_id)


def setup_fields(body: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"open": body.get("open") is not False, "waitlist": body.get("waitlist") is not False}
    cap = body.get("capacity")
    if cap in (None, ""):
        out["capacity"] = None
    else:
        try:
            n = int(cap)
        except (TypeError, ValueError):
            raise HTTPException(400, "Places is how many people can come.")
        if not 1 <= n <= 100_000:
            raise HTTPException(400, "Places is how many people can come.")
        out["capacity"] = n
    dl = body.get("deadline")
    if dl in (None, ""):
        out["deadline"] = None
    else:
        d = _at(dl)
        if not d:
            raise HTTPException(400, "That sign-up deadline isn't a date we can read.")
        out["deadline"] = _iso(d)
    try:
        hours = int(body.get("offer_hours") or OFFER_HOURS)
    except (TypeError, ValueError):
        raise HTTPException(400, "A waitlist offer lasts from 2 to 72 hours.")
    if not OFFER_RANGE[0] <= hours <= OFFER_RANGE[1]:
        raise HTTPException(400, "A waitlist offer lasts from 2 to 72 hours.")
    out["offer_hours"] = hours
    out["bring"] = str(body.get("bring") or "").strip()[:BRING_MAX]
    out["questions"] = clean_questions(body.get("questions"))
    return out


@router.put("/church/events/signups/setup")
def save_setup(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Prices, places, the deadline and the questions for one event. The
    owner and admins; a price above $0 needs Stripe connected. A type taken
    off the list is retired, not deleted: sign-ups keep what they bought."""
    body = body if isinstance(body, dict) else {}
    me = _office(body.get("business_id"), user, keep=True)
    biz = me["biz"]
    biz_id = str(biz["id"])
    entry_id = _uuid(body.get("entry_id"))
    if not tables_ready(biz_id):
        raise HTTPException(503, "Sign-ups aren't ready on this account yet.")
    ev = _event(biz_id, entry_id)
    if not ev:
        raise HTTPException(404, "That event isn't one of this church's.")
    fields = setup_fields(body)
    types = clean_types(body.get("types"))
    if any(t["price_cents"] > 0 for t in types) and not _can_charge(biz):
        raise HTTPException(409, "Connect Stripe in Payments first, so people can pay. Free tickets work now.")
    now = _iso(_now())
    saved = sb_clients.sb_post_as_service(
        "/church_event_signup_setups?on_conflict=business_id,entry_id",
        {"business_id": biz_id, "entry_id": entry_id, **fields, "updated_by": me["uid"], "updated_at": now},
        prefer="return=representation,resolution=merge-duplicates")
    if not (isinstance(saved, list) and saved):
        raise HTTPException(503, "Those sign-up settings didn't save. Try again.")
    setup_id = str(saved[0]["id"])
    old = _need(f"/church_event_ticket_types?business_id=eq.{_q(biz_id)}&setup_id=eq.{_q(setup_id)}&select=id&limit=100")
    old_ids = {str(o["id"]) for o in old}
    keep = set()
    for t in types:
        row = {k: t[k] for k in ("label", "price_cents", "seats", "max_per_signup", "sort_order")}
        if t["id"] and t["id"] in old_ids:
            keep.add(t["id"])
            done = sb_clients.sb_patch_as_service(
                f"/church_event_ticket_types?id=eq.{_q(t['id'])}&business_id=eq.{_q(biz_id)}",
                {**row, "active": True, "updated_at": now})
        else:
            done = sb_clients.sb_post_as_service(
                "/church_event_ticket_types", {**row, "business_id": biz_id, "setup_id": setup_id})
        if done is None:
            raise HTTPException(503, f"The {t['label']} ticket didn't save. Try again.")
    gone = old_ids - keep
    if gone:
        sb_clients.sb_patch_as_service(
            f"/church_event_ticket_types?business_id=eq.{_q(biz_id)}&id=in.({','.join(_q(g) for g in sorted(gone))})",
            {"active": False, "updated_at": now})
    settle(biz_id, entry_id)
    return detail(me, entry_id)


@router.post("/church/events/signups/{reg_id}/cancel")
def cancel_signup(reg_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Take a hold, an offer, a waitlist place or a free sign-up off. A paid
    one is refunded in Stripe instead, and the refund frees its places."""
    body = body if isinstance(body, dict) else {}
    me = _office(body.get("business_id"), user, keep=True)
    biz_id = str(me["biz"]["id"])
    reg = _reg(f"id=eq.{_q(_uuid(reg_id, 'sign-up'))}&business_id=eq.{_q(biz_id)}")
    if not reg:
        raise HTTPException(404, "That sign-up isn't one of this church's.")
    if reg.get("status") == "paid":
        raise HTTPException(409, "This one is paid. Refund it in Stripe, and its places free up when the refund goes through.")
    done = sb_clients.sb_patch_as_service(
        f"/church_event_registrations?id=eq.{_q(reg['id'])}&business_id=eq.{_q(biz_id)}"
        "&status=in.(held,offered,waiting,confirmed)",
        {"status": "cancelled", "updated_at": _iso(_now())})
    if done is None:
        raise HTTPException(503, "That didn't save. Try again.")
    if not done:
        raise HTTPException(409, "That sign-up changed a moment ago. The latest list is shown.")
    settle(biz_id, str(reg["entry_id"]))
    return detail(me, str(reg["entry_id"]))


STATUS_WORDS = {"held": "Paying now", "paid": "Paid", "confirmed": "Signed up (free)", "waiting": "Waitlist",
                "offered": "Offered a place", "expired": "Didn't finish", "cancelled": "Cancelled",
                "refunded": "Refunded"}


def _cell(v: Any) -> str:
    """A spreadsheet cell that can't run as a formula."""
    s = str(v if v is not None else "")
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def csv_text(d: Dict[str, Any]) -> str:
    qs = (d.get("setup") or {}).get("questions") or []
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Email", "Phone", "Status", "Waitlist #", "Places", "Tickets", "Amount", "Refunded",
                "Signed up", "Paid"] + [q["label"] for q in qs])
    for r in d.get("registrations") or []:
        w.writerow([_cell(x) for x in [
            r.get("name"), r.get("email"), r.get("phone") or "", STATUS_WORDS.get(r["status"], r["status"]),
            r.get("position") or "", r.get("seats"), lines_words(r.get("lines")),
            f"{int(r.get('amount_cents') or 0) / 100:.2f}", f"{int(r.get('refunded_cents') or 0) / 100:.2f}",
            str(r.get("created_at") or "")[:16].replace("T", " "), str(r.get("paid_at") or "")[:16].replace("T", " "),
        ] + [(r.get("answers") or {}).get(q["id"], "") for q in qs]])
    return buf.getvalue()


@router.get("/church/events/signups/export")
def export_signups(business_id: str, entry_id: str, user: AuthedUser = Depends(require_user)):
    me = _office(business_id, user, keep=True)
    d = detail(me, _uuid(entry_id))
    name = re.sub(r"[^A-Za-z0-9]+", "-", d["event"]["title"]).strip("-").lower()[:60] or "event"
    return Response(content="﻿" + csv_text(d), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}-sign-ups.csv"',
                             "Cache-Control": "no-store"})


# ─── The public page's card and script (events_rsvp_router draws them) ─

def public_card(o: Dict[str, Any], esc) -> str:
    """One event that takes sign-ups, on the public events page: the price,
    the places left and the deadline in one line, then the form (tickets,
    who, the questions), or the waitlist when it's full, or why it's closed."""
    v = o["signup"]
    eid = esc(str(o["entry_id"]))
    facts = [price_words(v)]
    if v.get("capacity") is not None and not v["full"]:
        n = v["places_left"]
        facts.append(f"{n} place{'s' if n != 1 else ''} left")
    elif v["full"]:
        facts.append("Full")
    if v.get("deadline") and not v.get("closed"):
        facts.append(f"Sign up by {v.get('deadline_label') or deadline_words(v['deadline'])}")
    fact_html = "".join(f'<span class="ev-su-fact">{esc(f)}</span>' for f in facts if f)
    loc = f'<div class="ev-loc">{esc(o["location"])}</div>' if o.get("location") else ""
    head = (f'<div class="ev-when">{esc(o["date_label"])}</div><h2 class="ev-title" id="ev-t-{eid}">{esc(o["title"])}</h2>'
            f'{loc}<div class="ev-su-facts">{fact_html}</div>')
    if v.get("closed"):
        return (f'<article class="ev-card ev-su" aria-labelledby="ev-t-{eid}">{head}'
                f'<p class="ev-fullnote">{esc(CLOSED_WORDS.get(v["closed"], CLOSED_WORDS["closed"]))}</p></article>')
    if v["full"] and not v.get("waitlist"):
        return (f'<article class="ev-card ev-su" aria-labelledby="ev-t-{eid}">{head}'
                '<p class="ev-fullnote">This one is full. Check back in case a place opens.</p></article>')
    rows = []
    for t in v["types"]:
        tid = esc(t["id"])
        price = money(t["price_cents"]) if t["price_cents"] else "Free"
        per = f' <span class="ev-su-per">· {t["seats"]} places</span>' if t["seats"] > 1 else ""
        start = 1 if len(v["types"]) == 1 else 0
        rows.append(
            f'<div class="ev-su-row" data-type="{tid}" data-price="{t["price_cents"]}" data-max="{t["max"]}">'
            f'<span class="ev-su-label" id="ev-l-{eid}-{tid}">{esc(t["label"])}{per}</span>'
            f'<span class="ev-su-price">{esc(price)}</span>'
            f'<span class="ev-su-step" role="group" aria-labelledby="ev-l-{eid}-{tid}">'
            f'<button type="button" class="ev-su-btn" data-d="-1" aria-label="One fewer {esc(t["label"])}">&minus;</button>'
            f'<output class="ev-su-qty" aria-live="polite">{start}</output>'
            f'<button type="button" class="ev-su-btn" data-d="1" aria-label="One more {esc(t["label"])}">+</button>'
            '</span></div>')
    qs = []
    for q in v.get("questions") or []:
        qid = f"ev-q-{eid}-{esc(q['id'])}"
        req = " required" if q.get("required") else ""
        star = "" if q.get("required") else ' <span class="ev-su-opt">(optional)</span>'
        if q["kind"] == "choice":
            opts = "".join(f'<option value="{esc(x)}">{esc(x)}</option>' for x in q.get("options") or [])
            field = f'<select class="ev-input" id="{qid}" data-q="{esc(q["id"])}"{req}><option value="">Choose…</option>{opts}</select>'
        elif q["kind"] == "yes_no":
            field = (f'<select class="ev-input" id="{qid}" data-q="{esc(q["id"])}"{req}><option value="">Choose…</option>'
                     '<option value="yes">Yes</option><option value="no">No</option></select>')
        else:
            field = f'<input class="ev-input" id="{qid}" data-q="{esc(q["id"])}" maxlength="{ANSWER_MAX}"{req}>'
        qs.append(f'<label class="ev-su-q" for="{qid}">{esc(q["label"])}{star}</label>{field}')
    full = v["full"]
    wait_note = (f'<p class="ev-su-note"><strong>This event is full.</strong> {esc(waitlist_words(v["offer_hours"]))}</p>'
                 if full else "")
    pay_note = ("" if full or not v["priced"] else
                f'<p class="ev-su-small">You\'ll pay on Stripe\'s secure page. Your place is kept for '
                f'{HOLD_MINUTES} minutes while you pay.</p>')
    go = "Join the waitlist" if full else ("Continue to payment" if v["priced"] else "Sign up")
    text_ok = ('<label class="ev-su-check"><input type="checkbox" name="texts_ok"> Text me too if a place opens '
               '(reply STOP to stop)</label>') if full else ""
    return f"""<article class="ev-card ev-su" aria-labelledby="ev-t-{eid}">
    {head}
    <form class="ev-form ev-su-form" data-entry="{eid}" data-full="{1 if full else 0}" data-priced="{1 if v['priced'] else 0}" novalidate>
      {wait_note}
      <fieldset class="ev-su-tickets"><legend class="ev-su-legend">Tickets</legend>{''.join(rows)}
        <div class="ev-su-total" aria-live="polite"><span>{'If you take a place' if full else 'Total'}</span><strong class="ev-su-sum">{'' if v['priced'] else 'Free'}</strong></div>
      </fieldset>
      <input type="text" name="name" class="ev-input" placeholder="Your name" aria-label="Your name" autocomplete="name" maxlength="{NAME_MAX}" required>
      <input type="email" name="email" class="ev-input" placeholder="Email" aria-label="Email" autocomplete="email" maxlength="{EMAIL_MAX}" required>
      <input type="tel" name="phone" class="ev-input" placeholder="Phone (optional)" aria-label="Phone, optional" autocomplete="tel" maxlength="{PHONE_MAX}">
      {''.join(qs)}
      {text_ok}
      <button type="submit" class="ev-go" data-label="{esc(go)}">{esc(go)}</button>
      {pay_note}
      <div class="ev-msg" role="status"></div>
    </form>
  </article>"""


PUBLIC_CSS = """
.ev-su-facts{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;}
.ev-su-fact{font-size:12.5px;font-weight:600;color:var(--text-secondary);border:1px solid var(--border);border-radius:999px;padding:3px 10px;}
.ev-su-fact:first-child{color:var(--accent);border-color:var(--accent);}
.ev-su-tickets{border:0;margin:0;padding:0;display:flex;flex-direction:column;gap:2px;}
.ev-su-legend{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);padding:0;margin-bottom:6px;}
.ev-su-row{display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:10px;min-height:48px;border-bottom:1px solid var(--border);}
.ev-su-label{font-size:15px;font-weight:600;}
.ev-su-per{font-weight:500;color:var(--text-muted);font-size:13px;}
.ev-su-price{font-size:15px;color:var(--text-secondary);font-variant-numeric:tabular-nums;}
.ev-su-step{display:inline-flex;align-items:center;gap:4px;}
.ev-su-btn{width:44px;height:44px;border-radius:50%;border:1.5px solid var(--border);background:var(--input-surface);color:var(--text-primary);font-size:20px;line-height:1;cursor:pointer;font-family:var(--font-body);}
.ev-su-btn:disabled{opacity:.4;cursor:default;}
.ev-su-btn:focus-visible{outline:2px solid var(--focus);outline-offset:2px;}
.ev-su-qty{min-width:22px;text-align:center;font-weight:700;font-variant-numeric:tabular-nums;}
.ev-su-total{display:flex;justify-content:space-between;align-items:baseline;padding:10px 0 4px;font-size:15px;}
.ev-su-total strong{font-size:18px;font-variant-numeric:tabular-nums;}
.ev-su-q{font-size:13px;font-weight:600;color:var(--text-secondary);margin:6px 0 -2px;}
.ev-su-opt{font-weight:500;color:var(--text-muted);}
.ev-su-check{display:flex;gap:10px;align-items:flex-start;font-size:14px;line-height:1.45;color:var(--text-secondary);}
.ev-su-check input{width:20px;height:20px;margin:1px 0 0;accent-color:var(--accent);flex:none;}
.ev-su-note{margin:0 0 4px;font-size:14px;line-height:1.55;color:var(--text-primary);padding:12px 14px;border:1px solid var(--border);border-radius:var(--radius);}
.ev-su-small{margin:2px 0 0;font-size:12.5px;line-height:1.5;color:var(--text-muted);text-align:center;}
.ev-banner{border:1.5px solid var(--accent);border-radius:var(--radius);padding:18px 16px;margin-bottom:18px;}
.ev-banner h2{font-family:var(--font-heading);font-size:19px;margin:0 0 6px;}
.ev-banner p{margin:6px 0 0;font-size:14px;line-height:1.55;color:var(--text-secondary);}
.ev-banner .ev-banner-what{color:var(--text-primary);font-weight:600;}
.ev-banner .ev-go{margin-top:12px;}
@media (prefers-reduced-motion:no-preference){.ev-banner{animation:evIn .3s ease-out;}@keyframes evIn{from{opacity:0;transform:translateY(-4px);}to{opacity:1;transform:none;}}}
"""


def public_script(api_origin: str, slug: str) -> str:
    """The sign-up forms' behaviour, the waitlist offer and the receipt
    after Stripe. Plain DOM, no library; every message is a sentence."""
    return """<script>
(function(){
  var API = %s, SLUG = %s;
  function money(c){ c = c|0; return '$' + (c %% 100 ? (c/100).toFixed(2) : String(c/100)).replace(/\\B(?=(\\d{3})+(?!\\d))/g, ','); }
  function el(t, cls, txt){ var e = document.createElement(t); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; }
  function rid(){ try { return crypto.randomUUID(); } catch (e) { return String(Date.now()) + '-' + Math.random().toString(16).slice(2); } }
  function store(k, v){ try { if (v == null) sessionStorage.removeItem(k); else sessionStorage.setItem(k, v); } catch (e) {} }
  function stored(k){ try { return sessionStorage.getItem(k); } catch (e) { return null; } }
  function call(method, path, body){
    return fetch(API + '/public/events/' + SLUG + path, {method: method, headers: {'Content-Type': 'application/json'},
      body: body ? JSON.stringify(body) : undefined})
      .then(function(r){ return r.json().catch(function(){ return {}; }).then(function(j){ return {ok: r.ok, status: r.status, j: j}; }); });
  }
  function banner(kicker, what, lines){
    var b = el('section', 'ev-banner'); b.setAttribute('role', 'status');
    b.appendChild(el('h2', null, kicker));
    if (what) b.appendChild(el('p', 'ev-banner-what', what));
    (lines || []).forEach(function(l){ if (l) b.appendChild(el('p', null, l)); });
    var head = document.querySelector('.ev-header'); head.parentNode.insertBefore(b, head.nextSibling);
    return b;
  }
  function linesText(ls){ return (ls || []).map(function(l){ return l.qty + ' ' + l.label; }).join(', '); }
  document.querySelectorAll('.ev-su-form').forEach(function(form){
    var entry = form.getAttribute('data-entry'), priced = form.getAttribute('data-priced') === '1';
    var go = form.querySelector('.ev-go'), msg = form.querySelector('.ev-msg'), sum = form.querySelector('.ev-su-sum');
    var waitlist = form.getAttribute('data-full') === '1';
    function picks(){ var p = {}; form.querySelectorAll('.ev-su-row').forEach(function(r){ var n = +r.querySelector('.ev-su-qty').textContent; if (n) p[r.getAttribute('data-type')] = n; }); return p; }
    function refresh(){
      var total = 0, any = 0;
      form.querySelectorAll('.ev-su-row').forEach(function(r){
        var n = +r.querySelector('.ev-su-qty').textContent, max = +r.getAttribute('data-max');
        total += n * (+r.getAttribute('data-price')); any += n;
        r.querySelector('[data-d="-1"]').disabled = n <= 0; r.querySelector('[data-d="1"]').disabled = n >= max;
      });
      if (sum) sum.textContent = priced ? money(total) : 'Free';
      var base = go.getAttribute('data-label');
      go.textContent = (!waitlist && priced && total) ? base + ' \\u2014 ' + money(total) : base;
      go.disabled = !any;
    }
    form.querySelectorAll('.ev-su-btn').forEach(function(b){
      b.addEventListener('click', function(){ var o = b.parentNode.querySelector('.ev-su-qty'); o.textContent = Math.max(0, (+o.textContent) + (+b.getAttribute('data-d'))); store('evs-req-' + entry, null); refresh(); });
    });
    refresh();
    form.addEventListener('submit', function(ev){
      ev.preventDefault();
      msg.className = 'ev-msg';
      var name = form.querySelector('[name=name]').value.trim(), email = form.querySelector('[name=email]').value.trim();
      if (!name) { msg.textContent = 'Please tell us your name.'; msg.className = 'ev-msg err'; return; }
      if (!email) { msg.textContent = 'Please add your email.'; msg.className = 'ev-msg err'; return; }
      var answers = {}, missing = null;
      form.querySelectorAll('[data-q]').forEach(function(q){ var v = q.value.trim(); if (v) answers[q.getAttribute('data-q')] = v; else if (q.required && !missing) missing = q; });
      if (missing) { msg.textContent = 'Please answer: ' + form.querySelector('label[for="' + missing.id + '"]').firstChild.textContent.trim(); msg.className = 'ev-msg err'; missing.focus(); return; }
      var key = stored('evs-req-' + entry) || rid(); store('evs-req-' + entry, key);
      var texts = form.querySelector('[name=texts_ok]');
      go.disabled = true; go.textContent = 'One moment\\u2026';
      call('POST', '/signup', {entry_id: entry, tickets: picks(), name: name, email: email,
        phone: form.querySelector('[name=phone]').value.trim(), texts_ok: !!(texts && texts.checked),
        answers: answers, waitlist: waitlist, request_id: key})
        .then(function(res){
          var j = res.j || {};
          if (res.ok && j.url) { window.location.href = j.url; return; }
          if (res.ok && j.ok) {
            store('evs-req-' + entry, null);
            var done = el('div', 'ev-su-note');
            if (j.waiting) { done.textContent = 'You\\u2019re on the waitlist: number ' + j.position + '. ' + j.next + ' We emailed you the details.'; }
            else if (j.confirmed) { done.textContent = 'You\\u2019re signed up: ' + linesText(j.lines) + '.' + (j.bring ? ' What to bring: ' + j.bring + '.' : '') + ' We emailed you the details.'; }
            else { done.textContent = j.detail || 'You\\u2019re signed up.'; }
            form.replaceWith(done); return;
          }
          if (j.code === 'full' && j.waitlist && !waitlist) {
            waitlist = true; go.setAttribute('data-label', 'Join the waitlist'); store('evs-req-' + entry, null);
            msg.textContent = 'It just filled up. You can join the waitlist: you\\u2019ll only pay if a place opens and you take it.';
            msg.className = 'ev-msg err'; refresh(); return;
          }
          msg.textContent = (typeof j.detail === 'string' && j.detail) || 'Something went wrong. Please try again.';
          msg.className = 'ev-msg err'; refresh();
        })
        .catch(function(){ msg.textContent = 'Network hiccup. Please try again.'; msg.className = 'ev-msg err'; refresh(); });
    });
  });
  var qs = new URLSearchParams(location.search);
  var back = qs.get('signup_back');
  if (back && stored('evs-req-' + back)) { call('POST', '/release', {entry_id: back, request_id: stored('evs-req-' + back)}); store('evs-req-' + back, null); }
  var paid = qs.get('signed_up');
  if (paid) {
    var tries = 0, b = banner('Thank you', 'Confirming your payment\\u2026', []);
    (function ask(){
      call('GET', '/receipt/' + encodeURIComponent(paid)).then(function(res){
        var j = res.j || {};
        if (!res.ok) { b.querySelector('.ev-banner-what').textContent = 'Your payment went through. We\\u2019ll email you the details.'; return; }
        if (j.state !== 'paid' && tries++ < 6) { setTimeout(ask, 1500); return; }
        b.innerHTML = '';
        b.appendChild(el('h2', null, j.state === 'paid' ? 'You\\u2019re signed up, ' + (j.first || 'friend') + '.' : 'Payment received'));
        b.appendChild(el('p', 'ev-banner-what', j.title + (j.date_label ? ' \\u00b7 ' + j.date_label : '') + (j.location ? ' \\u00b7 ' + j.location : '')));
        b.appendChild(el('p', null, linesText(j.lines) + ' \\u2014 ' + money(j.amount_cents) + (j.state === 'paid' ? ' paid.' : '. We\\u2019re confirming it now.')));
        if (j.bring) b.appendChild(el('p', null, 'What to bring: ' + j.bring));
        b.appendChild(el('p', null, 'Your receipt and the details are on their way to your email.'));
      }).catch(function(){ b.querySelector('.ev-banner-what').textContent = 'Your payment went through. We\\u2019ll email you the details.'; });
    })();
  }
  var token = qs.get('claim');
  if (token) {
    call('GET', '/claim/' + encodeURIComponent(token)).then(function(res){
      var j = res.j || {};
      if (!res.ok) { banner('That link didn\\u2019t work', 'Please call the church office if you still want a place.', []); return; }
      if (j.status === 'paid') { banner('You\\u2019re already signed up', j.title, ['See you there!']); return; }
      if (j.status !== 'offered') { banner('This place has gone to the next person', j.title, ['Offers last a set time so the waitlist keeps moving. Please call the church office if you still want to come.']); return; }
      var until = j.hold_expires_at ? new Date(j.hold_expires_at).toLocaleString([], {weekday: 'long', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit'}) : '';
      var b = banner('A place opened up for you, ' + (j.first || 'friend'), j.title + (j.date_label ? ' \\u00b7 ' + j.date_label : ''),
        [linesText(j.lines) + ' \\u2014 ' + money(j.amount_cents), until ? 'Pay by ' + until + ' to keep it. After that it goes to the next person on the waitlist.' : '']);
      var btn = el('button', 'ev-go', 'Pay ' + money(j.amount_cents) + ' and keep my place'); btn.type = 'button'; b.appendChild(btn);
      var m = el('div', 'ev-msg'); m.setAttribute('role', 'status'); b.appendChild(m);
      btn.addEventListener('click', function(){
        btn.disabled = true;
        call('POST', '/claim', {token: token}).then(function(r){
          if (r.ok && r.j && r.j.url) { location.href = r.j.url; return; }
          m.textContent = (r.j && r.j.detail) || 'Something went wrong. Please try again.'; m.className = 'ev-msg err'; btn.disabled = false;
        }).catch(function(){ m.textContent = 'Network hiccup. Please try again.'; m.className = 'ev-msg err'; btn.disabled = false; });
      });
    });
  }
})();
</script>""" % (json.dumps(api_origin), json.dumps(slug))


# ─── The member app's card (member_portal_church draws it) ────────────

MEMBER_CSS = """<style>
.mpe-facts{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 2px;}
.mpe-fact{display:inline-flex;align-items:center;height:28px;padding:0 11px;border-radius:999px;font-size:13px;font-weight:600;background:var(--s2,var(--mb-surface-2));color:var(--fg);}
.mpe-fact.is-price{background:var(--acc-soft,var(--mb-soft));color:var(--acc);}
.mpe details{margin-top:12px;}
.mpe summary{list-style:none;cursor:pointer;}
.mpe summary::-webkit-details-marker{display:none;}
.mpe summary.mp-go{width:auto;display:inline-flex;min-height:44px;padding:0 18px;border-radius:999px;font-size:15px;}
.mpe details[open] summary{margin-bottom:12px;}
.mpe-row{display:grid;grid-template-columns:1fr auto 92px;align-items:center;gap:10px;min-height:52px;border-bottom:1px solid var(--line,var(--mb-line));}
.mpe-row label{font-weight:600;}
.mpe-row small{display:block;font-weight:500;color:var(--fg2);font-size:13px;}
.mpe-price{color:var(--fg2);font-variant-numeric:tabular-nums;}
.mpe .mp-input{background:var(--s2,var(--mb-surface-2));}
.mpe-row select.mp-input{min-height:44px;padding:0 10px;}
.mpe-q{font-size:14px;font-weight:600;color:var(--fg2);margin:10px 0 4px;display:block;}
.mpe-note{margin:12px 0 0;padding:12px 14px;border-radius:14px;background:var(--s2,var(--mb-surface-2));color:var(--fg);font-size:14.5px;line-height:1.5;}
.mpe-small{margin:8px 0 0;font-size:13px;line-height:1.5;color:var(--fg2);}
.mpe-mine{margin:12px 0 0;padding:14px;border-radius:16px;background:var(--acc-soft,var(--mb-soft));}
.mpe-mine strong{display:block;font-size:15.5px;}
.mpe-mine p{margin:4px 0 0;font-size:14px;line-height:1.5;color:var(--fg);}
.mpe-mine .mp-go{margin-top:10px;width:auto;min-height:44px;padding:0 18px;border-radius:999px;}
.mpe-form .mp-go{margin-top:12px;}
</style>"""


def member_block(o: Dict[str, Any], esc) -> str:
    """For one event that takes sign-ups, on Coming up: the facts in one
    line, then this member's own sign-up, or the form (tickets and the
    questions; their name and email are already known), or the waitlist,
    or why it's closed. A form post; no script."""
    v = o["signup"]
    eid = esc(str(o["entry_id"]))
    facts = [f'<span class="mpe-fact is-price">{esc(price_words(v))}</span>']
    if v.get("capacity") is not None and not v["full"]:
        n = v["places_left"]
        facts.append(f'<span class="mpe-fact">{n} place{"s" if n != 1 else ""} left</span>')
    elif v["full"]:
        facts.append('<span class="mpe-fact">Full</span>')
    if v.get("deadline") and not v.get("closed"):
        facts.append(f'<span class="mpe-fact">Sign up by {esc(v.get("deadline_label") or deadline_words(v["deadline"]))}</span>')
    head = f'<div class="mpe-facts">{"".join(facts)}</div>'
    mine = v.get("mine")
    if mine:
        st = mine["status"]
        what = esc(lines_words(mine.get("lines")))
        bring = f'<p>What to bring: {esc(v["bring"])}</p>' if v.get("bring") else ""
        if st in ("paid", "confirmed"):
            paid = f" &middot; {money(mine.get('amount_cents'))} paid" if st == "paid" and mine.get("amount_cents") else ""
            return f'<div class="mpe">{head}<div class="mpe-mine"><strong>You\'re signed up</strong><p>{what}{paid}</p>{bring}</div></div>'
        if st == "waiting":
            return (f'<div class="mpe">{head}<div class="mpe-mine"><strong>You\'re number {int(mine.get("position") or 1)} '
                    f'on the waitlist</strong><p>{what}</p><p>{esc(waitlist_words(v["offer_hours"]))}</p></div></div>')
        if st == "offered":
            return (f'<div class="mpe">{head}<div class="mpe-mine"><strong>A place opened up for you</strong>'
                    f'<p>{what} &mdash; {money(mine.get("amount_cents"))}. Pay by {esc(mine.get("until_label") or deadline_words(mine.get("hold_expires_at")))} '
                    'to keep it; after that it goes to the next person.</p>'
                    f'<form method="post" action="/my/events/signup"><input type="hidden" name="entry_id" value="{eid}">'
                    '<input type="hidden" name="claim" value="1">'
                    f'<button class="mp-go" type="submit">Pay {money(mine.get("amount_cents"))} and keep my place</button></form></div></div>')
        if st == "held":
            return (f'<div class="mpe">{head}<div class="mpe-mine"><strong>Your place is held while you pay</strong>'
                    f'<p>{what}. If you closed the payment page, it opens again in a few minutes.</p></div></div>')
    if v.get("closed"):
        return f'<div class="mpe">{head}<p class="mpe-note">{esc(CLOSED_WORDS.get(v["closed"], CLOSED_WORDS["closed"]))}</p></div>'
    if v["full"] and not v.get("waitlist"):
        return f'<div class="mpe">{head}<p class="mpe-note">This one is full. Check back in case a place opens.</p></div>'
    rows = []
    for t in v["types"]:
        tid = esc(t["id"])
        start = 1 if len(v["types"]) == 1 else 0
        opts = "".join(f'<option value="{n}"{" selected" if n == start else ""}>{n}</option>' for n in range(0, t["max"] + 1))
        per = f'<small>{t["seats"]} places each</small>' if t["seats"] > 1 else ""
        rows.append(f'<div class="mpe-row"><label for="mpe-{eid}-{tid}">{esc(t["label"])}{per}</label>'
                    f'<span class="mpe-price">{esc(money(t["price_cents"]) if t["price_cents"] else "Free")}</span>'
                    f'<select class="mp-input" id="mpe-{eid}-{tid}" name="qty_{tid}">{opts}</select></div>')
    qs = []
    for q in v.get("questions") or []:
        qid = f"mpe-{eid}-{esc(q['id'])}"
        req = " required" if q.get("required") else ""
        opt = "" if q.get("required") else " (optional)"
        if q["kind"] in ("choice", "yes_no"):
            choices = q.get("options") if q["kind"] == "choice" else ["Yes", "No"]
            vals = choices if q["kind"] == "choice" else ["yes", "no"]
            opts = "".join(f'<option value="{esc(val)}">{esc(lab)}</option>' for lab, val in zip(choices, vals))
            field = f'<select class="mp-input" id="{qid}" name="a_{esc(q["id"])}"{req}><option value="">Choose…</option>{opts}</select>'
        else:
            field = f'<input class="mp-input" id="{qid}" name="a_{esc(q["id"])}" maxlength="{ANSWER_MAX}"{req}>'
        qs.append(f'<label class="mpe-q" for="{qid}">{esc(q["label"])}{opt}</label>{field}')
    full = v["full"]
    label = ("Join the waitlist" if full else (f"Sign up · {price_words(v)}" if v["priced"] and len(v["types"]) == 1
                                                   else "Sign up"))
    go = "Join the waitlist" if full else ("Continue to payment" if v["priced"] else "Sign up")
    note = (f'<p class="mpe-note">This event is full. {esc(waitlist_words(v["offer_hours"]))}</p>' if full else "")
    pay = ("" if full or not v["priced"] else
           f'<p class="mpe-small">You\'ll pay on Stripe\'s secure page; your place is kept {HOLD_MINUTES} minutes while you do.</p>')
    texts = ('<label class="mp-check" style="margin-top:10px"><input type="checkbox" name="texts_ok" value="yes"> '
             'Text me too if a place opens (reply STOP to stop)</label>') if full else ""
    return f"""<div class="mpe"><div>{head}</div><details><summary class="mp-go mb-soft">{esc(label)}</summary>
<form class="mp-form mpe-form" method="post" action="/my/events/signup">
<input type="hidden" name="entry_id" value="{eid}"><input type="hidden" name="request_id" value="{uuid.uuid4()}">
{'<input type="hidden" name="waitlist" value="yes">' if full else ''}{note}
<div role="group" aria-label="Tickets">{''.join(rows)}</div>
{''.join(qs)}{texts}
<button class="mp-go" type="submit">{esc(go)}</button>{pay}
</form></details></div>"""
