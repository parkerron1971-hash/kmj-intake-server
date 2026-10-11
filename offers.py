"""offers.py — a reason to come in: a code, a link and a QR code in one.

The Reach plan's step 3 (the approved Offers board; Kevin, 2026-10-10:
"go" on the four money defaults):

  1. An offer comes off the ONLINE payment only when the booking is paid in
     full online (no deposit); otherwise it is saved on the appointment and
     taken off at the counter.
  2. Who and when (first visit, regulars, slow hours, one per person, up to
     N uses) are checked by our own booking page: the payment processor
     can't, so the offer is never a code anyone can type at checkout.
  3. (refer-a-friend: its own module.)
  4. Offers need card payments connected (Payments); without them the
     Offers page says so and links there.

THE OFFER. What they get (an amount off, a percent off, or a free item),
who can use it (anyone, a first visit, regulars), when (optionally only
some days and hours on the business's clock, from a start day to an end
day), once per person or not, up to N uses, on or paused.

AT BOOKING. The booking page arrives with ?offer=CODE (the offer's link or
its printed QR, each tracked apart). The booking sends offer_code; evaluate()
decides, from this business's own records, whether it applies and why not,
and the booking keeps that decision in data.offer (id, code, title,
discount_cents, applies, why). A code that isn't one of the business's
offers changes nothing. The decision is frozen: the checkout reads it, and
the owner sees it on the appointment ("Offer FIRST10: $10 off. Take it off
at the counter unless they paid online.").

AT CHECKOUT (stripe_payments_router.booking_checkout). An offer that applies,
with a discount, on a booking paid in full online (no deposit): the service
line is charged less, named with the offer, a tip stays whole, and typed
codes are switched off for that payment so nothing stacks. Free items, and
anything that would bring the payment under 50 cents, are taken at the
counter.

RESULTS. Taps on its link and its QR (marketing_link_hits, by link id),
bookings that used it, what they were booked for, and what was paid
online for them.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

import sb_clients
from business_access import business_access

logger = logging.getLogger("offers")

router = APIRouter(prefix="/offers", tags=["offers"])

KINDS = ("amount_off", "percent_off", "free_item")
WHO = ("anyone", "first_visit", "regulars")
CODE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,23}$")
MIN_ONLINE_CENTS = 50
COLUMNS = ("id,business_id,code,kind,amount_cents,percent,free_item,title,who,hours,starts_on,ends_on,"
           "one_per_person,max_uses,status,source,created_at")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class Hours(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: List[int] = Field(min_length=1, max_length=7)          # ISO weekdays, 1 = Monday
    start: str
    end: str

    @model_validator(mode="after")
    def check(self):
        if any(d < 1 or d > 7 for d in self.days):
            raise ValueError("Days are 1 (Monday) to 7 (Sunday).")
        self.days = sorted(set(self.days))
        if not HHMM.match(self.start) or not HHMM.match(self.end) or self.start >= self.end:
            raise ValueError("Choose a start time before the end time, like 14:00 to 17:00.")
        return self


class OfferIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    amount_cents: Optional[int] = Field(default=None, ge=1, le=10_000_000)
    percent: Optional[int] = Field(default=None, ge=1, le=100)
    free_item: Optional[str] = Field(default=None, max_length=80)
    who: str = "anyone"
    hours: Optional[Hours] = None
    starts_on: Optional[date] = None
    ends_on: Optional[date] = None
    one_per_person: bool = True
    max_uses: Optional[int] = Field(default=None, ge=1, le=100_000)
    code: Optional[str] = Field(default=None, max_length=24)
    title: Optional[str] = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def check(self):
        if self.kind not in KINDS:
            raise ValueError("Choose an amount off, a percent off, or a free item.")
        if self.who not in WHO:
            raise ValueError("Choose who can use it: anyone, a first visit, or regulars.")
        needs = {"amount_off": self.amount_cents, "percent_off": self.percent,
                 "free_item": (self.free_item or "").strip() or None}[self.kind]
        if needs is None:
            raise ValueError("Say how much it takes off, or what's free.")
        if self.ends_on and self.starts_on and self.ends_on < self.starts_on:
            raise ValueError("The offer can't end before it starts.")
        if self.code is not None:
            self.code = self.code.strip().upper()
            if not CODE.match(self.code):
                raise ValueError("Use 2 to 24 letters, numbers or dashes for the code.")
        return self


class OfferChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Optional[str] = None
    ends_on: Optional[date] = None
    max_uses: Optional[int] = Field(default=None, ge=1, le=100_000)
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def check(self):
        if self.status is not None and self.status not in ("on", "paused"):
            raise ValueError("An offer is on or paused.")
        return self


# ── the words ─────────────────────────────────────────────────────────

def money(cents: int) -> str:
    dollars, rest = divmod(int(cents), 100)
    return f"${dollars:,}" + (f".{rest:02d}" if rest else "")


def what_words(offer: Dict[str, Any]) -> str:
    """"$10 off", "15% off", "A free beard line-up"."""
    if offer.get("kind") == "amount_off":
        return f"{money(offer['amount_cents'])} off"
    if offer.get("kind") == "percent_off":
        return f"{offer['percent']}% off"
    item = (offer.get("free_item") or "").strip()
    return f"A free {item[0].lower() + item[1:]}" if item else "Something free"


def default_title(offer: Dict[str, Any]) -> str:
    """"$10 off your first visit", "15% off your next visit", "A free beard
    line-up with your first visit"."""
    who = offer.get("who") or "anyone"
    if offer.get("kind") == "free_item":
        return what_words(offer) + {"first_visit": " with your first visit", "regulars": " with your next visit",
                                    "anyone": ""}[who]
    return what_words(offer) + {"first_visit": " your first visit", "regulars": " your next visit", "anyone": ""}[who]


def when_words(offer: Dict[str, Any]) -> str:
    """"Tue to Thu, 2 PM to 5 PM · through Sun, Nov 1"."""
    parts = []
    hours = offer.get("hours")
    if hours:
        days = hours.get("days") or []
        span = (f"{DAY_NAMES[days[0] - 1]} to {DAY_NAMES[days[-1] - 1]}"
                if days == list(range(days[0], days[-1] + 1)) and len(days) > 2
                else ", ".join(DAY_NAMES[d - 1] for d in days))
        parts.append(f"{span}, {_clock(hours['start'])} to {_clock(hours['end'])}")
    ends = _date(offer.get("ends_on"))
    if ends:
        parts.append("through " + ends.strftime("%a, %b ") + str(ends.day))
    return " · ".join(parts) or "Always on"


def _clock(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    return f"{h % 12 or 12}{':%02d' % m if m else ''} {'AM' if h < 12 else 'PM'}"


def _date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def suggest_code(offer: Dict[str, Any], taken: set) -> str:
    """FIRST10, BACK5, SAVE15, FREE…: short, sayable at the counter."""
    lead = {"first_visit": "FIRST", "regulars": "BACK", "anyone": "SAVE"}[offer.get("who") or "anyone"]
    if offer.get("kind") == "amount_off":
        n = str(int(offer["amount_cents"]) // 100 or 1)
    elif offer.get("kind") == "percent_off":
        n = str(offer["percent"])
    else:
        lead, n = "FREE", ""
    base = (lead + n)[:20]
    code, i = base, 2
    while code in taken or not CODE.match(code):
        code, i = f"{base}-{i}", i + 1
    return code


# ── the rules ─────────────────────────────────────────────────────────

def discount_cents(offer: Dict[str, Any], service_cents: Optional[int]) -> int:
    """What the offer takes off this service's price (0 for a free item:
    that is given at the counter)."""
    if not service_cents or service_cents <= 0:
        return 0
    if offer.get("kind") == "amount_off":
        return min(int(offer["amount_cents"]), int(service_cents))
    if offer.get("kind") == "percent_off":
        return min(int(service_cents), int(round(service_cents * int(offer["percent"]) / 100)))
    return 0


def check(offer: Dict[str, Any], *, now: datetime, tz, slot: Optional[datetime], past_visits: int,
          used_before: bool, uses: int) -> Tuple[bool, Optional[str]]:
    """(applies, why not) for one booking. Every rule the board names, in
    plain words for the customer."""
    if offer.get("status") != "on":
        return False, "This offer is paused right now."
    today = now.astimezone(tz).date()
    starts, ends = _date(offer.get("starts_on")), _date(offer.get("ends_on"))
    if starts and today < starts:
        return False, f"This offer starts {starts.strftime('%b')} {starts.day}."
    if ends and today > ends:
        return False, "This offer has ended."
    if offer.get("max_uses") and uses >= int(offer["max_uses"]):
        return False, "This offer has been used up."
    if offer.get("who") == "first_visit" and past_visits > 0:
        return False, "This offer is for a first visit."
    if offer.get("who") == "regulars" and past_visits == 0:
        return False, "This offer is for returning clients."
    if offer.get("one_per_person") and used_before:
        return False, "You've already used this offer."
    hours = offer.get("hours")
    if hours and slot is not None:
        local = slot.astimezone(tz)
        start = time.fromisoformat(hours["start"])
        end = time.fromisoformat(hours["end"])
        if local.isoweekday() not in (hours.get("days") or []) or not (start <= local.time() < end):
            return False, f"This offer is for {when_words({'hours': hours})}."
    return True, None


def _when(value: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _read(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise RuntimeError("read failed")
    return rows


def find(business_id: str, code: Any) -> Optional[Dict[str, Any]]:
    code = str(code or "").strip().upper()
    if not CODE.match(code):
        return None
    rows = _read(f"/offers?business_id=eq.{business_id}&code=eq.{code}&select={COLUMNS}&limit=1")
    return rows[0] if rows else None


def evaluate(business: Dict[str, Any], code: Any, *, contact_id: Optional[str], slot_iso: Optional[str],
             service_cents: Optional[int], now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The booking's offer decision (stored on the booking as data.offer), or
    None when the code isn't one of this business's offers. Never raises:
    a read that fails records the offer as not applied, with why."""
    bid = str(business["id"])
    try:
        offer = find(bid, code)
    except Exception:
        logger.warning("offer read failed for %s", bid[:8])
        return None
    if not offer:
        return None
    out = {"id": str(offer["id"]), "code": offer["code"], "title": offer["title"], "kind": offer["kind"],
           "applies": False, "why": None, "discount_cents": 0}
    try:
        import business_marketing
        now = now or datetime.now(timezone.utc)
        tz = business_marketing.business_tz(business)
        oid = str(UUID(str(offer["id"])))
        past = 0
        used_before = False
        if contact_id:
            cid = str(UUID(str(contact_id)))
            past = len(_read(f"/sessions?business_id=eq.{bid}&contact_id=eq.{cid}&status=in.(scheduled,completed)"
                             f"&scheduled_for=lt.{now.isoformat().replace('+', '%2B')}&select=id&limit=5"))
            used_before = bool(_read(f"/module_entries?business_id=eq.{bid}&data->offer->>id=eq.{oid}"
                                     f"&data->offer->>applies=eq.true&data->>contact_id=eq.{cid}&select=id&limit=1"))
        limit = int(offer.get("max_uses") or 0)
        uses = len(_read(f"/module_entries?business_id=eq.{bid}&data->offer->>id=eq.{oid}"
                         f"&data->offer->>applies=eq.true&status=eq.active&select=id&limit={limit + 1}")) if limit else 0
        applies, why = check(offer, now=now, tz=tz, slot=_when(slot_iso), past_visits=past,
                             used_before=used_before, uses=uses)
    except Exception as e:
        logger.warning("offer check failed for %s: %s", bid[:8], e)
        applies, why = False, "This offer couldn't be checked just now. Ask about it when you come in."
    out["applies"], out["why"] = applies, why
    if applies:
        out["discount_cents"] = discount_cents(offer, service_cents)
    return out


def public_answer(decision: Optional[Dict[str, Any]], *, deposit: bool = False) -> Optional[Dict[str, Any]]:
    """What the booking page says about the offer after booking."""
    if not decision:
        return None
    return {"code": decision["code"], "title": decision["title"], "applies": decision["applies"],
            "why": decision.get("why"), "discount_cents": decision.get("discount_cents") or 0}


def counter_note(decision: Optional[Dict[str, Any]]) -> Optional[str]:
    """The line the owner sees on the appointment."""
    if not decision or not decision.get("applies"):
        return None
    took = f" ({money(decision['discount_cents'])})" if decision.get("discount_cents") else ""
    return (f"Offer {decision['code']}: {decision['title']}{took}. If they paid online it's already taken off; "
            "otherwise take it off at the counter.")


def online_discount(decision: Optional[Dict[str, Any]], *, amount_cents: int, deposit_cents: Optional[int]) -> int:
    """The cents the online payment takes off: only for an offer that
    applies, on a booking paid in full online (no deposit), leaving at least
    MIN_ONLINE_CENTS to charge. 0 otherwise (the counter takes it)."""
    if not decision or not decision.get("applies") or deposit_cents:
        return 0
    off = int(decision.get("discount_cents") or 0)
    if off <= 0 or amount_cents - off < MIN_ONLINE_CENTS:
        return 0
    return off


# ── the owner's page ──────────────────────────────────────────────────

def payments_ready(business: Dict[str, Any]) -> bool:
    import payments_core
    try:
        provider = payments_core.provider_for(business)
        return provider.id == "stripe" and provider.is_connected(business)
    except Exception:
        return False


async def results(business_id: str, offer_ids: List[str], since: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
    """Per offer: bookings that used it, what they were booked for, what was
    paid online for them, and taps on its link and its QR. A read that fails
    is None, never 0."""
    import business_marketing_outcomes as outcomes
    import business_marketing_sent_links as sent_links
    out: Dict[str, Dict[str, Any]] = {oid: {"used": None, "booked_cents": None, "paid_cents": None,
                                            "opened": None, "scanned": None} for oid in offer_ids}
    if not offer_ids:
        return out
    ids = ",".join(str(UUID(o)) for o in offer_ids)
    try:
        rows = await asyncio.to_thread(
            _read, f"/module_entries?business_id=eq.{business_id}&data->offer->>id=in.({ids})"
                   f"&data->offer->>applies=eq.true&select=id,paid_at,offer:data->offer->>id,"
                   f"price:data->>price_at_booking,charged:data->>amount_charged_cents&limit=10000")
        for oid in offer_ids:
            out[oid].update(used=0, booked_cents=0, paid_cents=0)
        for r in rows:
            o = out.get(str(r.get("offer")))
            if o is None:
                continue
            o["used"] += 1
            try:
                o["booked_cents"] += int(round(float(r.get("price") or 0) * 100))
            except (TypeError, ValueError):
                pass
            if r.get("paid_at"):
                try:
                    o["paid_cents"] += max(0, int(r.get("charged") or 0))
                except (TypeError, ValueError):
                    pass
    except Exception as e:
        logger.warning("offer uses unread for %s: %s", business_id[:8], e)
    try:
        link_ids = {sent_links.link_id("offer", oid, part): (oid, part) for oid in offer_ids for part in (0, 1)}
        since = since or datetime.now(timezone.utc) - timedelta(days=365)
        measured = await outcomes.for_links(business_id, list(link_ids), since)
        if measured["sources"]["clicks"] != "unavailable":
            for lid, (oid, part) in link_ids.items():
                n = (measured["per_link"].get(lid) or {}).get("clicks") or 0
                key = "opened" if part == 0 else "scanned"
                out[oid][key] = (out[oid][key] or 0) + n
    except Exception as e:
        logger.warning("offer taps unread for %s: %s", business_id[:8], e)
    return out


def _public(offer: Dict[str, Any]) -> Dict[str, Any]:
    return {**{k: offer.get(k) for k in COLUMNS.split(",")}, "what": what_words(offer), "when": when_words(offer)}


async def overview(business: Dict[str, Any]) -> Dict[str, Any]:
    import business_marketing_sent_links as sent_links
    bid = str(business["id"])
    try:
        rows = await asyncio.to_thread(
            _read, f"/offers?business_id=eq.{bid}&source=eq.owner&select={COLUMNS}&order=created_at.desc&limit=200")
    except RuntimeError:
        raise HTTPException(503, "Your offers couldn't be read just now. Try again in a minute.") from None
    measured = await results(bid, [str(r["id"]) for r in rows])
    out = []
    for r in rows:
        try:
            share = await sent_links.offer_link(business, r, 0)
            printed = await sent_links.offer_link(business, r, 1)
        except Exception as e:
            logger.warning("offer link not made for %s: %s", bid[:8], e)
            share = printed = None
        out.append({**_public(r), "link": share, "print_link": printed, "results": measured.get(str(r["id"]))})
    return {"offers": out, "payments_ready": payments_ready(business)}


@router.get("/{business_id}")
async def list_offers(business_id: str, biz: dict = Depends(business_access("viewer"))):
    return {"ok": True, **await overview(biz)}


@router.post("/{business_id}")
async def create_offer(business_id: str, body: OfferIn, biz: dict = Depends(business_access("owner"))):
    if not payments_ready(biz):
        raise HTTPException(409, "Connect card payments in Payments first, so an offer can be taken off at booking.")
    bid = str(biz["id"])
    try:
        taken = {r["code"] for r in await asyncio.to_thread(
            _read, f"/offers?business_id=eq.{bid}&select=code&limit=1000")}
    except RuntimeError:
        raise HTTPException(503, "Your offers couldn't be read just now. Nothing was made.") from None
    row = body.model_dump(mode="json", exclude={"code", "title"})
    row["hours"] = body.hours.model_dump() if body.hours else None
    if row.get("free_item"):
        row["free_item"] = row["free_item"].strip()
    code = body.code or suggest_code(row, taken)
    if code in taken:
        raise HTTPException(409, f"You already have an offer with the code {code}. Choose another.")
    row.update(business_id=bid, code=code, title=(body.title or "").strip() or default_title(row),
               status="on", source="owner")
    saved = await asyncio.to_thread(sb_clients.sb_post_as_service, "/offers", row)
    if not saved:
        raise HTTPException(503, "That offer didn't save. Nothing was made. Try again in a minute.")
    return {"ok": True, **await overview(biz)}


@router.patch("/{business_id}/{offer_id}")
async def change_offer(business_id: str, offer_id: str, body: OfferChange,
                       biz: dict = Depends(business_access("owner"))):
    try:
        oid = str(UUID(offer_id))
    except ValueError:
        raise HTTPException(404, "That offer isn't one of yours.") from None
    patch = body.model_dump(mode="json", exclude_unset=True)
    if not patch:
        raise HTTPException(422, "Change the status, the end day, the uses or the title.")
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    saved = await asyncio.to_thread(
        sb_clients.sb_patch_as_service, f"/offers?id=eq.{oid}&business_id=eq.{biz['id']}", patch)
    if not saved:
        raise HTTPException(404, "That offer isn't one of yours, or it couldn't be changed just now.")
    return {"ok": True, **await overview(biz)}


@router.get("/public/{business_id}/{code}")
async def public_offer(business_id: str, code: str):
    """What the booking page shows for ?offer=CODE: the offer's words, when
    it's on. Nothing about who can use it is decided here (the booking
    decides, with the person's records)."""
    try:
        bid = str(UUID(business_id))
    except ValueError:
        raise HTTPException(404, "No such offer.") from None
    try:
        offer = await asyncio.to_thread(find, bid, code)
    except RuntimeError:
        raise HTTPException(503, "Offers couldn't be read just now.") from None
    if not offer or offer.get("status") != "on" or offer.get("source") != "owner":
        raise HTTPException(404, "No such offer.")
    ends = _date(offer.get("ends_on"))
    if ends and ends < datetime.now(timezone.utc).date() - timedelta(days=1):
        raise HTTPException(404, "No such offer.")
    return {"ok": True, "code": offer["code"], "title": offer["title"], "when": when_words(offer)}
