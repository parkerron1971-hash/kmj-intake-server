"""refer_a_friend.py — give $10, get $10.

The Reach plan's step 3, second part. The approved Offers board: "Every
regular gets their own link. Their friend saves $10 on a first cut; they
save $10 on their next one after the friend's visit is paid." Kevin,
2026-10-10, "go" on default 3: the friend's code works on a first visit
only, and the regular's thank-you is sent when the friend's visit is paid.

THE PROGRAM. The business's one offer with source 'referral' (offers.py's
table): on or paused, what the friend gets (amount_cents, a first visit,
once per person) and what the regular gets (reward_cents). in_notes: each
client's own link rides on their "Time for your next visit?" note
(outreach_journeys, rebook) as a P.S. whose exact words the owner sees on
the switch, so nobody gets an extra message. Turning it on needs card
payments connected, like any offer (default 4).

THE LINKS. Each client's own code (ANDRE-7K) in referral_links, made the
first time it's needed; their link is the booking page with ?offer=CODE,
so the booking page fills it in and shows "$10 off your first visit, from
Andre". The code also works said at the counter.

AT BOOKING. offers.evaluate hands over any code that isn't one of the
owner's offers:
  * a client's code is the friend's offer, with the program's rules (on, a
    first visit, once per person) and never the client's own link. The
    booking keeps data.offer with source 'referral', part 'friend', the
    referrer and the visit's time.
  * a thank-you code (THANKS-7KQ2) is the regular's reward: for that
    regular only, once (a cancelled booking gives it back).
Both come off online only on a booking paid in full online, like any
offer (default 1); otherwise the appointment's note tells the counter.

THE THANK-YOU. A friend's booking that used a client's code and is still
booked counts as paid when
  (online)  it was paid in full online and its time has passed,
  (invoice) an invoice for the friend was marked paid after they booked, or
  (owner)   the owner says so on the Offers page ("Their visit is paid").
Then referral_rewards gets exactly one row (UNIQUE per friend booking and
per friend) with a THANKS-XXXX code, and the regular is told by email, or
by text only under the journeys' text rules, in daytime on the business's
clock. The row is claimed (sent_at) before anything is sent: a lost note
costs less than a duplicate. With no way to reach them, the Offers page
says "tell them at the counter".

Kill switch: REFER_A_FRIEND=off (the sweep does nothing; codes still work).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

import offers
import sb_clients
from business_access import business_access

logger = logging.getLogger("refer_a_friend")

router = APIRouter(prefix="/offers", tags=["offers"])

PROGRAM_CODE = "REFER-A-FRIEND"     # the program row's own code; never one anyone can use
DEFAULT_CENTS = 1000
SAFE = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I/L: read aloud at the counter
WINDOW = timedelta(days=180)        # a friend's booking older than this earns nothing new
SEND_WITHIN = timedelta(days=30)    # an unsent thank-you older than this stays for the counter
TICK_LIMIT = 500
COLUMNS = offers.COLUMNS + ",reward_cents,in_notes,thanks_words,thanks_days"


def enabled() -> bool:
    return (os.environ.get("REFER_A_FRIEND") or "on").strip().lower() not in ("off", "0", "false", "no")


def _read(path: str) -> List[Dict[str, Any]]:
    """A service read that raises on failure (offers._read, one door)."""
    return offers._read(path)


def _iso(d: datetime) -> str:
    return d.isoformat().replace("+", "%2B")


def _ids(values: Iterable[Any]) -> str:
    return ",".join(sorted({str(UUID(str(v))) for v in values if v}))


# ── the words ─────────────────────────────────────────────────────────

def first_name(name: Any) -> str:
    return (str(name or "").strip().split(" ") or [""])[0]


def friend_title(program: Dict[str, Any], referrer_name: Any) -> str:
    """"$10 off your first visit, from Andre"."""
    base = f"{offers.money(program['amount_cents'])} off your first visit"
    who = first_name(referrer_name)
    return f"{base}, from {who}" if who else base


def thanks_title(amount_cents: int) -> str:
    return f"{offers.money(amount_cents)} off your next visit, for sending a friend"


def ps_words(program: Dict[str, Any], link: str, channel: str = "email") -> str:
    """The P.S. on a client's "Time for your next visit?" note. The owner
    reads these exact words on the switch before any go out."""
    give = offers.money(program.get("amount_cents") or DEFAULT_CENTS)
    get = offers.money(program.get("reward_cents") or DEFAULT_CENTS)
    if channel == "sms":
        return f"Bring a friend: {give} off for them, {get} off for you. {link}"
    return (f"P.S. Bring a friend: they get {give} off their first visit, and you get {get} off your next "
            f"one once they've been in. Your own link: {link}")


# The thank-you's words: the owner's own (offers.thanks_words) over these.
# {{code}} must stay in the email and the text, so the regular always gets
# their code. A line holding a link or the end day that this thank-you
# doesn't have ({{book_link}} with nothing bookable online, {{own_link}}
# that couldn't be made, {{ends}} with no end) is left out whole.
THANKS_DEFAULTS: Dict[str, str] = {
    "subject": "Thank you for sending {{friend}}",
    "email": ("Hi {{first_name}},\n\n{{friend}} came in, thanks to you. Here's {{amount}} off your next visit: "
              "use the code {{code}} when you book, or say it at the counter.\n{{book_link}}\n"
              "It's good through {{ends}}.\n\n"
              "Know someone else who'd like {{business}}? Your own link still works: {{own_link}}\n\n{{business}}"),
    "text": ("Thanks for sending {{friend}}, {{first_name}}! {{amount}} off your next visit with the code {{code}}.\n"
             "Good through {{ends}}.\nBook: {{book_link}}"),
}
THANKS_LIMITS = {"subject": 150, "email": 2000, "text": 320}
DROP_WHEN_EMPTY = ("book_link", "own_link", "ends")
THANKS_DAYS = (7, 365)


def check_words(words: Dict[str, Any]) -> Dict[str, str]:
    """The owner's thank-you words, checked: what they may change, within
    the limits, with {{code}} kept where the code must go. Raises ValueError
    in plain words."""
    out: Dict[str, str] = {}
    for k, v in (words or {}).items():
        if k not in THANKS_DEFAULTS:
            raise ValueError("Change the subject, the email or the text.")
        text = str(v or "").strip()
        if not text:
            raise ValueError("The words can't be empty. Use the suggested words to start again.")
        if len(text) > THANKS_LIMITS[k]:
            raise ValueError(f"That's longer than {THANKS_LIMITS[k]} characters.")
        if k != "subject" and "{{code}}" not in text:
            raise ValueError("Keep {{code}} in the email and the text, so they get their code.")
        out[k] = text
    return out


def ends_words(expires_on: Any) -> str:
    d = offers._date(expires_on)
    return d.strftime("%a, %b ") + str(d.day) if d else ""


def _fill(template: str, values: Dict[str, str]) -> str:
    lines = []
    for line in template.split("\n"):
        if any(f"{{{{{k}}}}}" in line and not values.get(k) for k in DROP_WHEN_EMPTY):
            continue
        opens_with_friend = line.startswith("{{friend}}")     # "your friend came in" opens a sentence
        for k, v in values.items():
            line = line.replace(f"{{{{{k}}}}}", v)
        line = line.rstrip()
        lines.append(line[:1].upper() + line[1:] if opens_with_friend else line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def thanks_words(*, business: Dict[str, Any], referrer: Dict[str, Any], friend: Optional[Dict[str, Any]],
                 reward: Dict[str, Any], book: Optional[str], own_link: Optional[str],
                 words: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """The thank-you the regular gets: subject, email and text, in the
    owner's words (words) over the suggested ones. A part that comes out
    without the code falls back to the suggested words, so the code always
    reaches them."""
    code = reward["code"]
    values = {"first_name": first_name(referrer.get("name")) or "there",
              "friend": first_name((friend or {}).get("name")) or "your friend",
              "amount": offers.money(reward["amount_cents"]), "code": code,
              "business": (business.get("name") or "us").strip(),
              "book_link": f"{book}?offer={code}" if book else "", "own_link": own_link or "",
              "ends": ends_words(reward.get("expires_on"))}
    mine = {k: v for k, v in (words or {}).items() if k in THANKS_DEFAULTS and isinstance(v, str) and v.strip()}
    out = {}
    for part, default in THANKS_DEFAULTS.items():
        filled = _fill(mine.get(part) or default, values)
        if part != "subject" and code not in filled:
            filled = _fill(default, values)
        out[part] = filled[:THANKS_LIMITS[part]] if part == "subject" else filled
    return out


# ── codes ─────────────────────────────────────────────────────────────

def _random(n: int) -> str:
    return "".join(secrets.choice(SAFE) for _ in range(n))


def name_code(name: Any) -> str:
    """ANDRE-7K from "Andre Smith"; FRIEND-7KQ2 when the name has no letters
    a code can carry."""
    plain = unicodedata.normalize("NFKD", first_name(name)).encode("ascii", "ignore").decode().upper()
    lead = re.sub(r"[^A-Z]", "", plain)[:10]
    return f"{lead}-{_random(2)}" if len(lead) >= 2 else f"FRIEND-{_random(4)}"


def code_in_use(business_id: str, code: str) -> bool:
    """The code is already an offer, a client's link or a thank-you here.
    Raises on a failed read."""
    for table in ("offers", "referral_links", "referral_rewards"):
        if _read(f"/{table}?business_id=eq.{business_id}&code=eq.{code}&select=code&limit=1"):
            return True
    return False


def booking_page(business: Dict[str, Any]) -> Optional[str]:
    """The booking page's address, or None when nothing can be booked online
    (the codes still work at the counter). Raises on a failed read."""
    import business_marketing_links as links
    bid = str(UUID(str(business["id"])))
    site = links.site_for(bid)
    if not site or not links.bookable(bid, business):
        return None
    return f"{links.origin(site)}/book"


def code_for(business_id: str, contact: Dict[str, Any]) -> str:
    """The client's own code, made the first time. Raises when it can't be
    read or made."""
    cid = str(UUID(str(contact["id"])))
    rows = _read(f"/referral_links?business_id=eq.{business_id}&contact_id=eq.{cid}&select=code&limit=1")
    if rows:
        return rows[0]["code"]
    for _ in range(6):
        code = name_code(contact.get("name"))
        if code_in_use(business_id, code):
            continue
        saved = sb_clients.sb_post_as_service(
            "/referral_links", {"business_id": business_id, "contact_id": cid, "code": code})
        if saved:
            return saved[0]["code"]
        rows = _read(f"/referral_links?business_id=eq.{business_id}&contact_id=eq.{cid}&select=code&limit=1")
        if rows:                                    # made by another request just now
            return rows[0]["code"]
    raise RuntimeError("no code could be made")


# ── the program ───────────────────────────────────────────────────────

def program(business_id: str) -> Optional[Dict[str, Any]]:
    """The business's refer-a-friend offer, on or paused, or None. Raises on
    a failed read."""
    rows = _read(f"/offers?business_id=eq.{business_id}&source=eq.referral&select={COLUMNS}&limit=1")
    return rows[0] if rows else None


def for_notes(business_id: str) -> Optional[Dict[str, Any]]:
    """The program when it is on and its P.S. rides on the rebook note."""
    try:
        p = program(business_id)
    except Exception as e:
        logger.warning("referral program unread biz=%s: %s", business_id[:8], e)
        return None
    return p if p and p.get("status") == "on" and p.get("in_notes") else None


def ps_for(business: Dict[str, Any], prog: Dict[str, Any], contact: Dict[str, Any], book: Optional[str],
           channel: str) -> Optional[str]:
    """The P.S. for one client's rebook note, with their own link; None when
    there is no booking page or the link can't be made (the note goes
    without it)."""
    if not book:
        return None
    try:
        return ps_words(prog, f"{book}?offer={code_for(str(business['id']), contact)}", channel)
    except Exception as e:
        logger.warning("referral link not made biz=%s: %s", str(business["id"])[:8], e)
        return None


def _names(business_id: str, ids: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    """{contact id: contact} for this business; {} when the read fails."""
    out: Dict[str, Dict[str, Any]] = {}
    ids = [i for i in {str(x) for x in ids if x}]
    try:
        for i in range(0, len(ids), 100):
            rows = _read(f"/contacts?business_id=eq.{business_id}&id=in.({_ids(ids[i:i + 100])})"
                         "&select=id,name,email,phone,status,metadata")
            out.update({str(r["id"]): r for r in rows})
    except Exception as e:
        logger.warning("referral names unread biz=%s: %s", business_id[:8], e)
    return out


# ── at booking ────────────────────────────────────────────────────────

def evaluate(business: Dict[str, Any], code: Any, *, contact_id: Optional[str], slot_iso: Optional[str],
             service_cents: Optional[int], now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """A client's code or a thank-you code, decided like any offer (see the
    module notes); None when the code is neither. Never raises."""
    bid = str(business["id"])
    code = str(code or "").strip().upper()
    if not offers.CODE.match(code):
        return None
    try:
        link = _read(f"/referral_links?business_id=eq.{bid}&code=eq.{code}&select=contact_id,code&limit=1")
        reward = [] if link else _read(
            f"/referral_rewards?business_id=eq.{bid}&code=eq.{code}"
            "&select=id,code,referrer_contact_id,amount_cents,expires_on&limit=1")
    except Exception as e:
        logger.warning("referral code unread biz=%s: %s", bid[:8], e)
        return None
    now = now or datetime.now(timezone.utc)
    if link:
        return _friend(business, link[0], contact_id=contact_id, slot_iso=slot_iso, service_cents=service_cents,
                       now=now)
    if reward:
        return _thanks(business, reward[0], contact_id=contact_id, service_cents=service_cents, now=now)
    return None


def _friend(business: Dict[str, Any], link: Dict[str, Any], *, contact_id: Optional[str], slot_iso: Optional[str],
            service_cents: Optional[int], now: datetime) -> Optional[Dict[str, Any]]:
    bid = str(business["id"])
    try:
        prog = program(bid)
    except Exception as e:
        logger.warning("referral program unread biz=%s: %s", bid[:8], e)
        return None
    if not prog:
        return None
    referrer = str(link["contact_id"])
    name = _names(bid, [referrer]).get(referrer, {}).get("name")
    out = {"id": str(prog["id"]), "code": link["code"], "title": friend_title(prog, name), "kind": "amount_off",
           "source": "referral", "part": "friend", "referrer_contact_id": referrer, "at": slot_iso or None,
           "applies": False, "why": None, "discount_cents": 0}
    try:
        if contact_id and str(contact_id) == referrer:
            applies, why = False, "That's your own link. Share it with a friend, and the thank-you comes to you."
        else:
            import business_marketing
            past, used_before = offers.history(bid, contact_id, str(prog["id"]), now)
            applies, why = offers.check(prog, now=now, tz=business_marketing.business_tz(business), slot=None,
                                        past_visits=past, used_before=used_before, uses=0)
    except Exception as e:
        logger.warning("referral check failed biz=%s: %s", bid[:8], e)
        applies, why = False, "This offer couldn't be checked just now. Ask about it when you come in."
    out["applies"], out["why"] = applies, why
    if applies:
        out["discount_cents"] = offers.discount_cents(prog, service_cents)
    return out


def _thanks(business: Dict[str, Any], reward: Dict[str, Any], *, contact_id: Optional[str],
            service_cents: Optional[int], now: datetime) -> Dict[str, Any]:
    bid = str(business["id"])
    rid = str(UUID(str(reward["id"])))
    out = {"id": rid, "code": reward["code"], "title": thanks_title(reward["amount_cents"]), "kind": "amount_off",
           "source": "referral", "part": "thanks", "applies": False, "why": None, "discount_cents": 0}
    try:
        ends = offers._date(reward.get("expires_on"))
        if not contact_id or str(contact_id) != str(reward["referrer_contact_id"]):
            why = ("This thank-you is for the client who sent a friend. Book with the email they use here, "
                   "or say the code at the counter.")
        elif ends and _today(business, now) > ends:
            why = f"This thank-you ended {ends.strftime('%b')} {ends.day}."
        elif _read(f"/module_entries?business_id=eq.{bid}&data->offer->>id=eq.{rid}"
                   "&data->offer->>applies=eq.true&status=eq.active&select=id&limit=1"):
            why = "You've already used this thank-you."
        else:
            why = None
    except Exception as e:
        logger.warning("thank-you check failed biz=%s: %s", bid[:8], e)
        why = "This thank-you couldn't be checked just now. Say the code when you come in."
    out["applies"], out["why"] = why is None, why
    if why is None and service_cents and service_cents > 0:
        out["discount_cents"] = min(int(reward["amount_cents"]), int(service_cents))
    return out


def public_words(business_id: str, code: Any) -> Optional[Dict[str, Any]]:
    """What the booking page shows for ?offer= a client's code or a
    thank-you code, or None. Raises on a failed read."""
    code = str(code or "").strip().upper()
    if not offers.CODE.match(code):
        return None
    link = _read(f"/referral_links?business_id=eq.{business_id}&code=eq.{code}&select=contact_id,code&limit=1")
    if link:
        prog = program(business_id)
        if not prog or prog.get("status") != "on":
            return None
        name = _names(business_id, [link[0]["contact_id"]]).get(str(link[0]["contact_id"]), {}).get("name")
        return {"code": code, "title": friend_title(prog, name), "when": ""}      # the title says when
    reward = _read(f"/referral_rewards?business_id=eq.{business_id}&code=eq.{code}"
                   "&select=amount_cents,expires_on&limit=1")
    if reward:
        ends = offers._date(reward[0].get("expires_on"))
        if ends and ends < datetime.now(timezone.utc).date() - timedelta(days=1):
            return None
        return {"code": code, "title": thanks_title(reward[0]["amount_cents"]),
                "when": f"Through {ends_words(ends)}" if ends else ""}
    return None


def _today(business: Dict[str, Any], now: datetime) -> date:
    import business_marketing
    return now.astimezone(business_marketing.business_tz(business)).date()


def expiry(prog: Dict[str, Any], business: Dict[str, Any], now: datetime) -> Optional[date]:
    """The last day a thank-you made now works: thanks_days from today on the
    business's clock, or None (no end)."""
    days = prog.get("thanks_days")
    return _today(business, now) + timedelta(days=int(days)) if days else None


# ── the thank-you ─────────────────────────────────────────────────────

def _when(value: Any) -> Optional[datetime]:
    return offers._when(value)


def paid_how(entry: Dict[str, Any], invoices: List[Dict[str, Any]], now: datetime) -> Optional[str]:
    """'online', 'invoice' or None for one friend's booking (see the module
    notes). invoices: the friend's paid invoices."""
    at = _when((entry.get("offer") or {}).get("at"))
    if entry.get("paid_at") and not entry.get("deposit") and at is not None and at <= now:
        return "online"
    booked = _when(entry.get("created_at"))
    if booked is None or not entry.get("contact_id"):
        return None
    for i in invoices:
        paid = _when(i.get("paid_at"))
        if str(i.get("contact_id")) == str(entry["contact_id"]) and paid is not None and paid >= booked:
            return "invoice"
    return None


def issue(business_id: str, entry: Dict[str, Any], how: str, reward_cents: int, *,
          expires_on: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """The thank-you for one friend's booking: one row, made once. None when
    it exists already (this booking or this friend), the friend used their
    own link, or nothing could be saved. expires_on: its last day (expiry)."""
    offer = entry.get("offer") or {}
    referrer = offer.get("referrer_contact_id")
    friend = entry.get("contact_id")
    if not referrer or (friend and str(friend) == str(referrer)):
        return None
    eid = str(UUID(str(entry["id"])))
    seen = f"friend_booking_id.eq.{eid}" + (f",friend_contact_id.eq.{UUID(str(friend))}" if friend else "")
    if _read(f"/referral_rewards?business_id=eq.{business_id}&or=({seen})&select=id&limit=1"):
        return None
    for _ in range(4):
        code = f"THANKS-{_random(4)}"
        if code_in_use(business_id, code):
            continue
        saved = sb_clients.sb_post_as_service("/referral_rewards", {
            "business_id": business_id, "referrer_contact_id": str(UUID(str(referrer))),
            "friend_contact_id": str(UUID(str(friend))) if friend else None, "friend_booking_id": eid,
            "code": code, "amount_cents": int(reward_cents), "paid_how": how,
            "expires_on": expires_on.isoformat() if expires_on else None})
        if saved:
            return saved[0]
        if _read(f"/referral_rewards?business_id=eq.{business_id}&or=({seen})&select=id&limit=1"):
            return None                              # made by another worker just now
    logger.warning("thank-you not saved biz=%s booking=%s", business_id[:8], eid[:8])
    return None


FRIEND_SELECT = ("id,business_id,created_at,paid_at,status,offer:data->offer,contact_id:data->>contact_id,"
                 "deposit:data->>deposit_paid_at")


def issue_paid(now: datetime) -> int:
    """Every friend's booking that is now paid gets its thank-you. Raises on
    a failed read of the bookings."""
    rows = _read(f"/module_entries?data->offer->>part=eq.friend&data->offer->>applies=eq.true&status=eq.active"
                 f"&created_at=gte.{_iso(now - WINDOW)}&select={FRIEND_SELECT}&order=created_at.asc&limit={TICK_LIMIT}")
    if not rows:
        return 0
    done = set()
    for i in range(0, len(rows), 100):
        done |= {str(r["friend_booking_id"]) for r in _read(
            f"/referral_rewards?friend_booking_id=in.({_ids(r['id'] for r in rows[i:i + 100])})"
            "&select=friend_booking_id")}
    todo = [r for r in rows if str(r["id"]) not in done]
    by_biz: Dict[str, List[Dict[str, Any]]] = {}
    for r in todo:
        by_biz.setdefault(str(r["business_id"]), []).append(r)
    made = 0
    for bid, entries in by_biz.items():
        try:
            prog = program(bid)
            if not prog:
                continue
            friends = [e["contact_id"] for e in entries if e.get("contact_id")]
            invoices = _read(f"/invoices?business_id=eq.{bid}&contact_id=in.({_ids(friends)})&status=eq.paid"
                             "&select=contact_id,paid_at&limit=1000") if friends else []
            ends = None
            if prog.get("thanks_days"):
                business = _read(f"/businesses?id=eq.{bid}&select=*&limit=1")
                ends = expiry(prog, business[0], now) if business else None
            for e in entries:
                how = paid_how(e, invoices, now)
                if how and issue(bid, e, how, int(prog.get("reward_cents") or DEFAULT_CENTS), expires_on=ends):
                    made += 1
        except Exception as e:
            logger.warning("thank-yous skipped biz=%s: %s", bid[:8], e)
    return made


async def send_unsent(now: datetime) -> Dict[str, int]:
    """Each thank-you not yet sent, in daytime on its business's clock:
    claimed, then sent by email (or text, under the journeys' rules), or
    marked 'none' for the counter."""
    import business_marketing
    import httpx
    import outreach_journeys as journeys
    import rules_engine
    stats = {"email": 0, "sms": 0, "none": 0}
    rows = await asyncio.to_thread(
        _read, f"/referral_rewards?sent_at=is.null&issued_at=gte.{_iso(now - SEND_WITHIN)}"
               "&select=*&order=issued_at.asc&limit=200")
    if not rows:
        return stats
    businesses = {str(b["id"]): b for b in await asyncio.to_thread(
        _read, f"/businesses?id=in.({_ids(r['business_id'] for r in rows)})&select=*")}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for bid, business in businesses.items():
            mine = [r for r in rows if str(r["business_id"]) == bid]
            if rules_engine.business_paused(business):
                continue
            tz = await asyncio.to_thread(business_marketing.business_tz, business)
            if not journeys.daytime(now, tz):
                continue
            people = await asyncio.to_thread(
                _names, bid, [r["referrer_contact_id"] for r in mine] + [r.get("friend_contact_id") for r in mine])
            try:
                book = await asyncio.to_thread(booking_page, business)
            except Exception:
                book = None
            try:
                own_words = ((await asyncio.to_thread(program, bid)) or {}).get("thanks_words")
            except Exception:
                own_words = None                      # the suggested words still carry the code
            for r in mine:
                referrer = people.get(str(r["referrer_contact_id"]))
                channel = (await journeys._channel(client, business, referrer) if referrer else None) or "none"
                claimed = await asyncio.to_thread(
                    sb_clients.sb_patch_as_service, f"/referral_rewards?id=eq.{r['id']}&sent_at=is.null",
                    {"sent_at": now.isoformat(), "sent_by": channel})
                if not claimed:
                    continue                          # another worker has it
                if channel == "none":
                    stats["none"] += 1
                    continue
                own = None
                if book:
                    try:
                        own = f"{book}?offer={await asyncio.to_thread(code_for, bid, referrer)}"
                    except Exception:
                        own = None
                words = thanks_words(business=business, referrer=referrer,
                                     friend=people.get(str(r.get("friend_contact_id"))), reward=r, book=book,
                                     own_link=own, words=own_words)
                try:
                    await journeys.send(client, business, referrer, channel, subject=words["subject"],
                                        email=words["email"], text=words["text"],
                                        event={"journey": "referral_thanks", "channel": channel})
                    stats[channel] += 1
                except Exception as e:
                    logger.warning("thank-you not sent biz=%s: %s", bid[:8], e)
                    await asyncio.to_thread(sb_clients.sb_patch_as_service, f"/referral_rewards?id=eq.{r['id']}",
                                            {"sent_by": "none"})
                    stats["none"] += 1
    return stats


async def rewards_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """The sweep: thank-yous for friends whose visits are now paid, then the
    unsent ones out. Never raises."""
    stats = {"issued": 0, "email": 0, "sms": 0, "none": 0}
    if not enabled():
        return stats
    now = now or datetime.now(timezone.utc)
    try:
        stats["issued"] = await asyncio.to_thread(issue_paid, now)
    except Exception as e:
        logger.warning("referral thank-yous not issued: %s", e)
    try:
        stats.update(await send_unsent(now))
    except Exception as e:
        logger.warning("referral thank-yous not sent: %s", e)
    if any(stats.values()):
        logger.info("referral rewards_tick: %s", stats)
    return stats


# ── the owner's card ──────────────────────────────────────────────────

def _uses(business_id: str, reward_ids: List[str]) -> Optional[set]:
    try:
        used = set()
        for i in range(0, len(reward_ids), 100):
            used |= {str(r["offer"]) for r in _read(
                f"/module_entries?business_id=eq.{business_id}&data->offer->>id=in.({_ids(reward_ids[i:i + 100])})"
                "&data->offer->>applies=eq.true&status=eq.active&select=offer:data->offer->>id")}
        return used
    except Exception as e:
        logger.warning("thank-you uses unread biz=%s: %s", business_id[:8], e)
        return None


async def overview(business: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The Offers page's refer-a-friend card: the program, the P.S. words,
    whether the rebook note is on, what came of it, friends waiting for their
    visit to count as paid, and the thank-yous made."""
    import outreach_journeys as journeys
    now = now or datetime.now(timezone.utc)
    bid = str(business["id"])
    try:
        prog = await asyncio.to_thread(program, bid)
    except Exception as e:
        logger.warning("referral program unread biz=%s: %s", bid[:8], e)
        return {"readable": False}
    shown = prog or {"amount_cents": DEFAULT_CENTS, "reward_cents": DEFAULT_CENTS, "in_notes": True}
    rebook = journeys.config(business.get("settings") or {}, "rebook")
    out: Dict[str, Any] = {
        "readable": True, "made": bool(prog), "on": bool(prog and prog.get("status") == "on"),
        "friend_cents": shown["amount_cents"], "reward_cents": shown["reward_cents"],
        "in_notes": bool(shown.get("in_notes")), "ps": ps_words(shown, "(their own link)"),
        "rebook_on": bool(rebook.get("on")) and journeys.allowed(business, "rebook"),
        "thanks_days": shown.get("thanks_days"),
        "thanks_words": {**THANKS_DEFAULTS, **{k: v for k, v in (shown.get("thanks_words") or {}).items()
                                               if k in THANKS_DEFAULTS}},
        "thanks_defaults": THANKS_DEFAULTS,
        "results": None, "waiting": [], "thanks": []}
    if not prog:
        return out
    try:
        measured = (await offers.results(bid, [str(prog["id"])])).get(str(prog["id"])) or {}
        rewards = await asyncio.to_thread(
            _read, f"/referral_rewards?business_id=eq.{bid}&select=*&order=issued_at.desc&limit=500")
        friends = await asyncio.to_thread(
            _read, f"/module_entries?business_id=eq.{bid}&data->offer->>part=eq.friend"
                   f"&data->offer->>applies=eq.true&status=eq.active&created_at=gte.{_iso(now - WINDOW)}"
                   f"&select={FRIEND_SELECT}&order=created_at.desc&limit=200")
        links_made = len(await asyncio.to_thread(
            _read, f"/referral_links?business_id=eq.{bid}&select=id&limit=10000"))
    except Exception as e:
        logger.warning("referral results unread biz=%s: %s", bid[:8], e)
        return out
    used = await asyncio.to_thread(_uses, bid, [str(r["id"]) for r in rewards])
    rewarded = {str(r["friend_booking_id"]) for r in rewards}
    waiting = [f for f in friends if str(f["id"]) not in rewarded
               and (_when((f.get("offer") or {}).get("at")) or now) <= now][:10]
    people = await asyncio.to_thread(
        _names, bid, [r["referrer_contact_id"] for r in rewards[:10]] + [r.get("friend_contact_id") for r in rewards[:10]]
        + [(f.get("offer") or {}).get("referrer_contact_id") for f in waiting] + [f.get("contact_id") for f in waiting])

    def name(cid: Any) -> Optional[str]:
        return (people.get(str(cid)) or {}).get("name") if cid else None

    out["results"] = {"links": links_made, "booked": measured.get("used"), "booked_cents": measured.get("booked_cents"),
                      "paid_online_cents": measured.get("paid_cents"), "thanks": len(rewards),
                      "thanks_used": None if used is None else len(used)}
    out["waiting"] = [{"booking_id": str(f["id"]), "friend": name(f.get("contact_id")),
                       "referrer": name((f.get("offer") or {}).get("referrer_contact_id")),
                       "at": (f.get("offer") or {}).get("at")} for f in waiting]
    out["thanks"] = [{"id": str(r["id"]), "code": r["code"], "amount_cents": r["amount_cents"],
                      "referrer": name(r["referrer_contact_id"]), "friend": name(r.get("friend_contact_id")),
                      "issued_at": r["issued_at"], "sent_by": r.get("sent_by"), "sent_at": r.get("sent_at"),
                      "expires_on": r.get("expires_on"),
                      "used": None if used is None else str(r["id"]) in used} for r in rewards[:10]]
    return out


class ReferralIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on: bool
    friend_cents: Optional[int] = Field(default=None, ge=100, le=100_000)
    reward_cents: Optional[int] = Field(default=None, ge=100, le=100_000)
    in_notes: Optional[bool] = None
    # The thank-you: how many days a new code is good for (0 = no end), and
    # the owner's words (any of subject / email / text; reset_words goes back
    # to the suggested ones).
    thanks_days: Optional[int] = Field(default=None, ge=0, le=THANKS_DAYS[1])
    thanks_words: Optional[Dict[str, str]] = None
    reset_words: bool = False

    @model_validator(mode="after")
    def check(self):
        if self.thanks_days and self.thanks_days < THANKS_DAYS[0]:
            raise ValueError(f"A thank-you is good for at least {THANKS_DAYS[0]} days, or has no end.")
        if self.thanks_words is not None:
            self.thanks_words = check_words(self.thanks_words)
        return self


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contact_id: UUID


class PaidIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    booking_id: UUID


@router.put("/{business_id}/referral")
async def set_referral(business_id: str, body: ReferralIn, biz: dict = Depends(business_access("owner"))):
    """Turn refer-a-friend on or off, and set what each side gets and the
    thank-you (its words, how long it's good for). Settings save while it's
    off too: the program is made paused, and turning it on later keeps them."""
    bid = str(biz["id"])
    if body.on and not offers.payments_ready(biz):
        raise HTTPException(409, "Connect card payments in Payments first, so the friend's offer can be taken off "
                                 "at booking.")
    try:
        prog = await asyncio.to_thread(program, bid)
    except RuntimeError:
        raise HTTPException(503, "Refer a friend couldn't be read just now. Nothing changed.") from None
    settings: Dict[str, Any] = {}
    if body.friend_cents is not None:
        settings["amount_cents"] = body.friend_cents
    if body.reward_cents is not None:
        settings["reward_cents"] = body.reward_cents
    if body.in_notes is not None:
        settings["in_notes"] = body.in_notes
    if body.thanks_days is not None:
        settings["thanks_days"] = body.thanks_days or None
    if body.reset_words:
        settings["thanks_words"] = None
    elif body.thanks_words:
        settings["thanks_words"] = {**((prog or {}).get("thanks_words") or {}), **body.thanks_words}
    if prog is None:
        if not body.on and not settings:
            return {"ok": True, "referral": await overview(biz)}
        code = PROGRAM_CODE
        if await asyncio.to_thread(code_in_use, bid, code):
            code = f"{PROGRAM_CODE}-{_random(4)}"
        row = {"business_id": bid, "code": code, "kind": "amount_off", "amount_cents": DEFAULT_CENTS,
               "title": "Refer a friend", "who": "first_visit", "one_per_person": True,
               "status": "on" if body.on else "paused", "source": "referral", "reward_cents": DEFAULT_CENTS,
               "in_notes": True, **settings}
        saved = await asyncio.to_thread(sb_clients.sb_post_as_service, "/offers", row)
        if not saved:
            raise HTTPException(503, "That didn't save. Nothing changed. Try again in a minute.")
    else:
        patch: Dict[str, Any] = {"status": "on" if body.on else "paused",
                                 "updated_at": datetime.now(timezone.utc).isoformat(), **settings}
        saved = await asyncio.to_thread(
            sb_clients.sb_patch_as_service, f"/offers?id=eq.{prog['id']}&business_id=eq.{bid}&source=eq.referral",
            patch)
        if not saved:
            raise HTTPException(503, "That didn't save. Nothing changed. Try again in a minute.")
    return {"ok": True, "referral": await overview(biz)}


@router.post("/{business_id}/referral/link")
async def client_link(business_id: str, body: LinkIn, biz: dict = Depends(business_access("owner"))):
    """One client's own link, to copy and send them yourself."""
    bid = str(biz["id"])
    try:
        prog = await asyncio.to_thread(program, bid)
        rows = await asyncio.to_thread(
            _read, f"/contacts?business_id=eq.{bid}&id=eq.{body.contact_id}&select=id,name&limit=1")
    except RuntimeError:
        raise HTTPException(503, "That couldn't be read just now. Try again in a minute.") from None
    if not prog or prog.get("status") != "on":
        raise HTTPException(409, "Turn on Refer a friend first.")
    if not rows:
        raise HTTPException(404, "That client isn't one of yours.")
    try:
        code = await asyncio.to_thread(code_for, bid, rows[0])
        book = await asyncio.to_thread(booking_page, biz)
    except Exception:
        raise HTTPException(503, "Their link couldn't be made just now. Try again in a minute.") from None
    return {"ok": True, "name": rows[0].get("name"), "code": code, "link": f"{book}?offer={code}" if book else None}


@router.post("/{business_id}/referral/paid")
async def friend_paid(business_id: str, body: PaidIn, biz: dict = Depends(business_access("owner"))):
    """The owner says a friend's visit is paid (cash, or a payment the app
    didn't see): the regular's thank-you is made now and sent in daytime."""
    bid = str(biz["id"])
    try:
        prog = await asyncio.to_thread(program, bid)
        rows = await asyncio.to_thread(
            _read, f"/module_entries?id=eq.{body.booking_id}&business_id=eq.{bid}&select={FRIEND_SELECT}&limit=1")
    except RuntimeError:
        raise HTTPException(503, "That couldn't be read just now. Nothing changed.") from None
    entry = rows[0] if rows else None
    offer = (entry or {}).get("offer") or {}
    if not entry or entry.get("status") != "active" or offer.get("part") != "friend" or not offer.get("applies"):
        raise HTTPException(404, "That isn't a booking a friend made with a client's link.")
    ends = expiry(prog, biz, datetime.now(timezone.utc)) if prog else None
    reward = await asyncio.to_thread(lambda: issue(bid, entry, "owner",
                                                   int((prog or {}).get("reward_cents") or DEFAULT_CENTS),
                                                   expires_on=ends))
    if reward is None:
        raise HTTPException(409, "Their thank-you was already made.")
    return {"ok": True, "referral": await overview(biz)}
