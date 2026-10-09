"""outreach_journeys.py — Outreach that runs by itself.

The Reach plan's step 2 (Kevin, 2026-10-08: "Offers + the after-visit review
ask on EVERY plan; automatic win-back/rebook/birthday texts from Week level
up"; 2026-10-09, on how texts go out: "Build now, texts after").

  review_ask  after a visit, a short thank-you with the business's review
              link (its Google review link, settings.get_found.review_url).
              Every plan. Once per visit, at most once per contact in
              REVIEW_EVERY days, so a regular is not asked every week.
  win_back    a client whose last visit is `days` ago (default 60) and who
              has nothing booked: a note with the booking link. Week level up.
  rebook      a client whose last visit is `days` ago (default 35) and who
              has nothing booked: time for the next one. Week level up.
  birthday    a contact whose birthday (contacts.birthdate) is today on the
              business's clock: a happy-birthday note. Week level up.

THE OWNER'S OK. Nothing runs until the owner switches a journey on, on the
page that shows its exact words (Grow → Outreach → Automatic); the words
are theirs to change. That switch, with the words in front of them, is the
standing approval: a note goes out exactly as written, with the person's
first name, the business's name and its links filled in.

HOW IT GOES OUT (Kevin, 2026-10-09).
  * By email, now: the business's own sender identity and reply routing,
    the platform suppression list, and a one-click unsubscribe
    (email_sender.send_via_resend), never to a contact who opted out.
  * By text only when ALL of: texts for journeys are switched on for the
    platform (JOURNEY_TEXTS=on, which waits until the shared number's 10DLC
    registration covers marketing), the person ticked the optional "texts
    about offers" box when they booked (sms_consents source
    'booking_marketing'), they have not opted out (STOP always wins), and
    it is daytime on the business's clock. Otherwise the note goes by email.
  * Any note only between 9 AM and 8 PM on the business's clock; at most
    DAILY_CAP notes per business per day; never while the practitioner has
    paused their automations (settings.automations_paused).

EXACTLY ONCE. journey_sends is claimed BEFORE a note is sent (UNIQUE
business, journey, key), so a crash or a second worker never sends the same
note twice; a lost note costs less than a duplicate.

LINKS. {{link}} is the journey's own tracked link to the booking page
(business_marketing_sent_links, kind 'journey'), so the visits, bookings and
payments that follow are counted for the journey. {{review_link}} is the
business's review page, off its own site, so it is not tracked.

Kill switch: JOURNEYS=off (the routes keep working; the sweep does nothing).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit
from uuid import UUID

import sb_clients

logger = logging.getLogger("outreach_journeys")

JOURNEYS = ("review_ask", "win_back", "rebook", "birthday")
WEEK_ONLY = frozenset({"win_back", "rebook", "birthday"})
WEEK_LEVELS = frozenset({"week", "openings", "autopilot"})
DAILY_CAP = 40                    # notes per business per day, every journey together
TICK_BUDGET = 300                 # notes per sweep, every business together
REVIEW_EVERY = timedelta(days=120)
REVIEW_WITHIN = timedelta(days=3)  # a visit older than this is not asked about
LAPSE_WINDOW = timedelta(days=14)  # win-back: from `days` to `days` + this
REBOOK_WINDOW = timedelta(days=7)
HISTORY = timedelta(days=400)
SEND_START, SEND_END = 9, 20      # the business's clock, 9 AM to 8 PM
LIMITS = {"subject": 150, "email": 2000, "text": 320}
DAYS = {"win_back": (21, 365), "rebook": (7, 180)}
HOURS_AFTER = (1, 72)
MARKETING_CONSENT = "booking_marketing"

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "review_ask": {
        "on": False, "hours_after": 3,
        "subject": "Thank you for coming in",
        "email": ("Hi {{first_name}},\n\nThank you for coming in. If you have a minute, a short review helps "
                  "other people find us:\n{{review_link}}\n\nThank you,\n{{business}}"),
        "text": "Thanks for coming in, {{first_name}}! A quick review helps others find us: {{review_link}}",
    },
    "win_back": {
        "on": False, "days": 60,
        "subject": "We'd love to see you again",
        "email": ("Hi {{first_name}},\n\nIt's been a while, and we'd love to see you again. Pick a time that "
                  "suits you:\n{{link}}\n\n{{business}}"),
        "text": "It's been a while, {{first_name}}! We'd love to see you again. Book here: {{link}}",
    },
    "rebook": {
        "on": False, "days": 35,
        "subject": "Time for your next visit?",
        "email": ("Hi {{first_name}},\n\nIt's about time for your next visit. Pick a time here:\n{{link}}\n\n"
                  "{{business}}"),
        "text": "Time for your next visit, {{first_name}}? Book here: {{link}}",
    },
    "birthday": {
        "on": False,
        "subject": "Happy birthday from {{business}}",
        "email": ("Hi {{first_name}},\n\nHappy birthday from all of us at {{business}}! We hope it's a great "
                  "one.\n\n{{business}}"),
        "text": "Happy birthday, {{first_name}}, from all of us at {{business}}!",
    },
}
WORDS = ("subject", "email", "text")


class JourneyError(ValueError):
    """A change the owner asked for that cannot be saved, in plain words:
    422 for a value out of range, 409 for a switch that can't go on yet."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def enabled() -> bool:
    return (os.environ.get("JOURNEYS") or "on").strip().lower() not in ("off", "0", "false", "no")


def texts_on() -> bool:
    """Journey texts wait for the shared number's 10DLC registration to cover
    marketing (Kevin's step); until then every note goes by email."""
    return (os.environ.get("JOURNEY_TEXTS") or "off").strip().lower() in ("on", "1", "true", "yes")


# ── settings ──────────────────────────────────────────────────────────

def review_url(settings: Optional[Dict[str, Any]]) -> Optional[str]:
    url = ((settings or {}).get("get_found") or {}).get("review_url")
    return url if valid_review_url(url) else None


def valid_review_url(url: Any) -> bool:
    if not isinstance(url, str) or len(url) > 500:
        return False
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname) and not parts.username


def config(settings: Optional[Dict[str, Any]], kind: str) -> Dict[str, Any]:
    """A journey's settings as saved, over its defaults."""
    saved = ((settings or {}).get("journeys") or {}).get(kind) or {}
    out = dict(DEFAULTS[kind])
    for k in out:
        if k in saved and saved[k] is not None:
            out[k] = saved[k]
    return out


def week_level(business: Dict[str, Any]) -> bool:
    import business_marketing
    return business_marketing.level_for(business)["level"] in WEEK_LEVELS


def allowed(business: Dict[str, Any], kind: str) -> bool:
    return kind not in WEEK_ONLY or week_level(business)


def change(business: Dict[str, Any], kind: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """The business's settings with one journey changed (and the review link,
    for the review ask). Raises JourneyError for anything that cannot be
    saved. Nothing is written here."""
    if kind not in JOURNEYS:
        raise JourneyError("There's no such automatic note.")
    settings = dict(business.get("settings") or {})
    journeys = dict(settings.get("journeys") or {})
    mine = dict(journeys.get(kind) or {})
    if "review_url" in body and kind == "review_ask":
        url = (body.get("review_url") or "").strip()
        if url and not valid_review_url(url):
            raise JourneyError("Paste your review link as it starts, with https://.")
        get_found = dict(settings.get("get_found") or {})
        get_found["review_url"] = url or None
        settings["get_found"] = get_found
    if body.get("reset_words"):
        for w in WORDS:
            mine.pop(w, None)
    for w in WORDS:
        if w in body and body[w] is not None:
            text = str(body[w]).strip()
            if not text:
                raise JourneyError("The words can't be empty. Reset them to start again.")
            if len(text) > LIMITS[w]:
                raise JourneyError(f"That's longer than {LIMITS[w]} characters.")
            mine[w] = text
    if "days" in body and body["days"] is not None:
        lo, hi = DAYS.get(kind, (None, None))
        if lo is None:
            raise JourneyError("This note doesn't take a number of days.")
        days = int(body["days"])
        if not lo <= days <= hi:
            raise JourneyError(f"Choose between {lo} and {hi} days.")
        mine["days"] = days
    if "hours_after" in body and body["hours_after"] is not None:
        if kind != "review_ask":
            raise JourneyError("Only the review ask waits a number of hours.")
        hours = int(body["hours_after"])
        if not HOURS_AFTER[0] <= hours <= HOURS_AFTER[1]:
            raise JourneyError(f"Choose between {HOURS_AFTER[0]} and {HOURS_AFTER[1]} hours.")
        mine["hours_after"] = hours
    if "on" in body and body["on"] is not None:
        on = bool(body["on"])
        if on and not allowed(business, kind):
            raise JourneyError("This note comes with the Week level of marketing. Upgrade to switch it on.", 409)
        if on and kind == "review_ask" and not review_url(settings):
            raise JourneyError("Add your review link first, so the note has somewhere to send people.", 409)
        mine["on"] = on
    journeys[kind] = mine
    settings["journeys"] = journeys
    if kind == "review_ask" and not review_url(settings) and mine.get("on"):
        mine["on"] = False                     # the link was taken away: the note stops
    return settings


# ── the words ─────────────────────────────────────────────────────────

def first_name(contact: Dict[str, Any]) -> str:
    name = (contact.get("name") or "").strip()
    return name.split(" ")[0] if name else "there"


def fill(text: str, *, contact: Dict[str, Any], business: Dict[str, Any], link: Optional[str],
         review: Optional[str]) -> str:
    out = (text or "").replace("{{first_name}}", first_name(contact))
    out = out.replace("{{business}}", (business.get("name") or "us").strip())
    out = out.replace("{{review_link}}", review or "")
    import business_marketing_sent_links as sent_links
    return re.sub(r"[ \t]+\n", "\n", sent_links.fill(out, link)).strip()


# ── who is due ────────────────────────────────────────────────────────

def _when(value: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def visits(sessions: Iterable[Dict[str, Any]], now: datetime) -> Tuple[Dict[str, Dict[str, Any]], set, List[Dict[str, Any]]]:
    """(each contact's last visit that has ended, the contacts with something
    booked ahead, the visits that ended) from the business's sessions
    (scheduled or completed; online bookings mirror into sessions)."""
    last: Dict[str, Dict[str, Any]] = {}
    ahead, ended = set(), []
    for s in sessions:
        start = _when(s.get("scheduled_for"))
        cid = s.get("contact_id")
        if not start or not cid:
            continue
        try:
            minutes = max(5, int(s.get("duration_minutes") or 60))
        except (TypeError, ValueError):
            minutes = 60
        end = start + timedelta(minutes=minutes)
        if start > now:
            ahead.add(str(cid))
            continue
        if end > now:
            continue                                   # still going on
        visit = {"id": str(s["id"]), "contact_id": str(cid), "end": end}
        ended.append(visit)
        if str(cid) not in last or end > last[str(cid)]["end"]:
            last[str(cid)] = visit
    return last, ahead, ended


def due(kind: str, cfg: Dict[str, Any], *, now: datetime, local_today: date, last: Dict[str, Dict[str, Any]],
        ahead: set, ended: List[Dict[str, Any]], birthdays: List[Dict[str, Any]],
        sent: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """[(contact id, key)] for one journey, oldest reason first; what was sent
    before (journey_sends) is left out."""
    done = {(r.get("journey"), r.get("key")) for r in sent}
    out: List[Tuple[str, str]] = []
    if kind == "review_ask":
        wait = timedelta(hours=int(cfg.get("hours_after") or 3))
        asked = {}
        for r in sent:
            if r.get("journey") == "review_ask":
                at = _when(r.get("sent_at"))
                if at and (str(r.get("contact_id")) not in asked or at > asked[str(r.get("contact_id"))]):
                    asked[str(r.get("contact_id"))] = at
        for v in sorted(ended, key=lambda v: v["end"]):
            if not (now - REVIEW_WITHIN <= v["end"] <= now - wait):
                continue
            key = f"visit:{v['id']}"
            recent = asked.get(v["contact_id"])
            if ("review_ask", key) in done or (recent and now - recent < REVIEW_EVERY):
                continue
            out.append((v["contact_id"], key))
            asked[v["contact_id"]] = now                # one ask per person per sweep
    elif kind in ("win_back", "rebook"):
        days = timedelta(days=int(cfg.get("days") or DEFAULTS[kind]["days"]))
        window = LAPSE_WINDOW if kind == "win_back" else REBOOK_WINDOW
        for cid, v in sorted(last.items(), key=lambda kv: kv[1]["end"]):
            if cid in ahead or not (now - days - window <= v["end"] <= now - days):
                continue
            key = f"last:{v['id']}"
            if (kind, key) not in done:
                out.append((cid, key))
    elif kind == "birthday":
        for c in birthdays:
            born = c.get("birthdate")
            try:
                b = date.fromisoformat(str(born)[:10])
            except (TypeError, ValueError):
                continue
            if (b.month, b.day) == (local_today.month, local_today.day) or (
                    b.month == 2 and b.day == 29 and local_today.month == 3 and local_today.day == 1
                    and not _leap(local_today.year)):
                key = f"birthday:{local_today.year}"
                if ("birthday", f"{c['id']}:{key}") not in done:
                    out.append((str(c["id"]), f"{c['id']}:{key}"))
    return out


def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


# ── sending ───────────────────────────────────────────────────────────

async def marketing_text_consent(client, business_id: str, phone: str) -> bool:
    """The person ticked "texts about offers" for this business, and has not
    opted out (STOP always wins)."""
    import sms_alerts
    from sms_service import normalize_phone
    phone = normalize_phone(phone) or ""
    if not phone or await sms_alerts.is_opted_out(client, phone, business_id):
        return False
    rows = await sms_alerts._sb_get(
        client, f"/sms_consents?phone=eq.{sms_alerts._pq(phone)}&business_id=eq.{business_id}"
                f"&source=eq.{MARKETING_CONSENT}&select=id&limit=1") or []
    return bool(rows)


def daytime(now: datetime, tz) -> bool:
    return SEND_START <= now.astimezone(tz).hour < SEND_END


async def _channel(client, business: Dict[str, Any], contact: Dict[str, Any]) -> Optional[str]:
    """'sms' when every text rule holds, else 'email' when the person can be
    emailed, else None (nothing is claimed)."""
    import contact_fields
    import email_sender
    phone = (contact.get("phone") or "").strip()
    if texts_on() and phone and not contact_fields.sms_opted_out(contact):
        if await marketing_text_consent(client, str(business["id"]), phone):
            return "sms"
    email = (contact.get("email") or "").strip()
    if email and not contact_fields.email_opted_out(contact) and not await email_sender.is_suppressed(email):
        return "email"
    return None


def _claim(business_id: str, kind: str, contact_id: str, key: str, channel: str) -> bool:
    saved = sb_clients.sb_post_as_service("/journey_sends", {
        "business_id": business_id, "journey": kind, "contact_id": contact_id, "key": key, "channel": channel})
    return bool(saved)


async def _deliver(client, business: Dict[str, Any], kind: str, cfg: Dict[str, Any], contact: Dict[str, Any],
                   channel: str, link: Optional[str], review: Optional[str]) -> None:
    words = {"contact": contact, "business": business, "link": link, "review": review}
    if channel == "email":
        import email_sender
        await email_sender.send_via_resend(
            to_email=contact["email"].strip(), to_name=contact.get("name"),
            from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
            from_name=business.get("name") or None,
            subject=fill(cfg["subject"], **words), body=fill(cfg["email"], **words),
            reply_to=email_sender.build_routed_reply_to(str(business["id"]), str(contact["id"])) or None,
            business_id=str(business["id"]))
    else:
        from sms_routing import _send_platform_sms
        from sms_service import _store_sms, compose_outbound_body, normalize_phone
        phone = normalize_phone(contact.get("phone") or "")
        body = compose_outbound_body(business.get("name"), fill(cfg["text"], **words), include_optout=True)
        msg_id = await _send_platform_sms(phone, body, business_id=str(business["id"]))
        await _store_sms(client, str(business["id"]), str(contact["id"]), phone, body, "outbound",
                         telnyx_id=msg_id or "", sent_by="system")
    try:
        sb_clients.sb_post_as_service("/events", {
            "business_id": str(business["id"]), "contact_id": str(contact["id"]), "event_type": "journey_sent",
            "source": "journeys", "data": {"journey": kind, "channel": channel}})
    except Exception as e:  # pragma: no cover - the note went out; the log is best-effort
        logger.warning(f"journey event log failed: {e}")


# ── the sweep ─────────────────────────────────────────────────────────

def _reads(business_id: str, now: datetime) -> Tuple[List, List]:
    since = (now - HISTORY).isoformat().replace("+", "%2B")
    sessions = sb_clients.sb_get_as_service(
        f"/sessions?business_id=eq.{business_id}&contact_id=not.is.null&status=in.(scheduled,completed)"
        f"&scheduled_for=gte.{since}&select=id,contact_id,scheduled_for,duration_minutes"
        f"&order=scheduled_for.desc&limit=5000")
    sent = sb_clients.sb_get_as_service(
        f"/journey_sends?business_id=eq.{business_id}&sent_at=gte.{since}"
        f"&select=journey,key,contact_id,channel,sent_at&limit=10000")
    if sessions is None or sent is None:
        raise RuntimeError("a read failed")
    return sessions, sent


def _contacts(business_id: str, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), 100):
        chunk = ",".join(str(UUID(x)) for x in ids[i:i + 100])
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{business_id}&id=in.({chunk})&select=id,name,email,phone,status,metadata") or []
        out.update({str(r["id"]): r for r in rows})
    return out


def _birthdays(business_id: str) -> Optional[List[Dict[str, Any]]]:
    return sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{business_id}&birthdate=not.is.null&select=id,birthdate&limit=10000")


def _sent_today(sent: List[Dict[str, Any]], now: datetime, tz) -> int:
    today = now.astimezone(tz).date()
    return sum(1 for r in sent if (_when(r.get("sent_at")) or now).astimezone(tz).date() == today)


async def run_business(business: Dict[str, Any], *, now: datetime, budget: int) -> Dict[str, int]:
    """One business's due notes, sent. Returns counters."""
    import business_marketing
    import business_marketing_sent_links as sent_links
    import httpx
    stats = {"email": 0, "sms": 0, "skipped": 0}
    bid = str(business["id"])
    settings = business.get("settings") or {}
    asked = [k for k in JOURNEYS if config(settings, k).get("on")]
    if not asked:
        return stats
    week = week_level(business) if any(k in WEEK_ONLY for k in asked) else False
    on = [k for k in asked if k not in WEEK_ONLY or week]
    if not on:
        return stats
    tz = await asyncio.to_thread(business_marketing.business_tz, business)
    if not daytime(now, tz):
        return stats
    sessions, sent = await asyncio.to_thread(_reads, bid, now)
    room = min(budget, DAILY_CAP - _sent_today(sent, now, tz))
    if room <= 0:
        return stats
    last, ahead, ended = visits(sessions, now)
    birthdays = await asyncio.to_thread(_birthdays, bid) if "birthday" in on else []
    if birthdays is None:
        birthdays = []
        on = [k for k in on if k != "birthday"]
    review = review_url(settings)
    todo: List[Tuple[str, str, str]] = []
    for kind in on:
        if kind == "review_ask" and not review:
            continue
        for cid, key in due(kind, config(settings, kind), now=now, local_today=now.astimezone(tz).date(),
                            last=last, ahead=ahead, ended=ended, birthdays=birthdays, sent=sent):
            todo.append((kind, cid, key))
    if not todo:
        return stats
    contacts = await asyncio.to_thread(_contacts, bid, sorted({c for _, c, _ in todo}))
    links: Dict[Tuple[str, str], Optional[str]] = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for kind, cid, key in todo:
            if room <= 0:
                break
            contact = contacts.get(cid)
            if not contact:
                stats["skipped"] += 1
                continue
            channel = await _channel(client, business, contact)
            if not channel:
                stats["skipped"] += 1
                continue
            cfg = config(settings, kind)
            if (kind, channel) not in links:
                try:
                    wants = sent_links.wants_link(cfg["email" if channel == "email" else "text"])
                    links[(kind, channel)] = (await sent_links.journey_link(business, kind, channel)) if wants else None
                except Exception as e:
                    logger.warning(f"journey link not made biz={bid[:8]} {kind}/{channel}: {e}")
                    links[(kind, channel)] = "HOLD"
            if links[(kind, channel)] == "HOLD":
                stats["skipped"] += 1               # this journey waits for a later sweep: no dead link
                continue
            if not await asyncio.to_thread(_claim, bid, kind, cid, key, channel):
                stats["skipped"] += 1               # already sent (or claimed by another worker)
                continue
            try:
                await _deliver(client, business, kind, cfg, contact, channel, links[(kind, channel)], review)
            except Exception as e:
                logger.warning(f"journey note failed biz={bid[:8]} {kind}: {e}")
                stats["skipped"] += 1
                continue
            stats[channel] += 1
            room -= 1
    return stats


async def journeys_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every business with a journey switched on: its due notes. Never raises."""
    stats = {"businesses": 0, "email": 0, "sms": 0, "skipped": 0}
    if not enabled():
        return stats
    now = now or datetime.now(timezone.utc)
    try:
        rows = sb_clients.sb_get_as_service("/businesses?settings->journeys=not.is.null&select=*&limit=1000") or []
    except Exception as e:
        logger.warning(f"journeys_tick list failed: {e}")
        return stats
    budget = TICK_BUDGET
    import rules_engine
    for business in rows:
        if budget <= 0:
            break
        try:
            if rules_engine.business_paused(business):
                continue
            got = await run_business(business, now=now, budget=budget)
        except Exception as e:
            logger.warning(f"journeys for {str(business.get('id'))[:8]} skipped: {e}")
            continue
        if got["email"] or got["sms"] or got["skipped"]:
            stats["businesses"] += 1
        for k in ("email", "sms", "skipped"):
            stats[k] += got[k]
        budget -= got["email"] + got["sms"]
    if stats["email"] or stats["sms"]:
        logger.info(f"journeys_tick: {stats}")
    return stats


# ── what the owner reads ──────────────────────────────────────────────

async def overview(business: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Each journey: whether it's on or locked, its settings and words (and
    the defaults), and what it did in the last 30 days: notes sent by
    channel, and what came through its link."""
    import business_marketing
    import business_marketing_outcomes as outcomes
    import business_marketing_sent_links as sent_links
    now = now or datetime.now(timezone.utc)
    bid = str(business["id"])
    settings = business.get("settings") or {}
    since = now - timedelta(days=30)
    sent = sb_clients.sb_get_as_service(
        f"/journey_sends?business_id=eq.{bid}&sent_at=gte.{since.isoformat().replace('+', '%2B')}"
        f"&select=journey,channel&limit=10000")
    level = business_marketing.level_for(business)
    week = level["level"] in WEEK_LEVELS
    out = []
    for kind in JOURNEYS:
        ok = kind not in WEEK_ONLY or week
        cfg = config(settings, kind)
        counts = None if sent is None else {
            "email": sum(1 for r in sent if r.get("journey") == kind and r.get("channel") == "email"),
            "sms": sum(1 for r in sent if r.get("journey") == kind and r.get("channel") == "sms")}
        through = None
        if kind != "review_ask":
            ids = [sent_links.link_id("journey", sent_links.journey_ref(bid, kind), part) for part in (0, 1)]
            try:
                measured = await outcomes.for_links(bid, ids, since)
                through = {"totals": measured["totals"], "sources": measured["sources"]}
            except Exception as e:
                logger.warning(f"journey results unread biz={bid[:8]} {kind}: {e}")
        out.append({"kind": kind, "on": bool(cfg.get("on")) and ok, "locked": not ok,
                    "settings": {k: cfg[k] for k in ("days", "hours_after") if k in cfg},
                    "words": {w: cfg[w] for w in WORDS}, "defaults": {w: DEFAULTS[kind][w] for w in WORDS},
                    "sent": counts, "through_link": through})
    return {"journeys": out, "review_url": review_url(settings), "texts_on": texts_on(),
            "level": level["level"], "upgrade": level["upgrade"], "daily_cap": DAILY_CAP}
