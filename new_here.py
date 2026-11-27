"""
new_here.py — "New here": a guest texts a word to the church's own number.

Kevin, 2026-11-14: "the new here for guest is very important"; the canvas
"New Here Guest Texts" (QKF6rdSMuGtLp74RtVEy4Z), then "build this". What big
churches do on Sunday ("New here? Text NEW to ..."), done our way:

  THE WORD     a guest texts the church's word (NEW unless it picks another)
               to the church's OWN number. sms_routing answers it beside GIVE
               and DAILY, never on the shared number, where a word belongs to
               one church at a time. on_text() makes them a guest (a contact,
               status lead, source new_here) if they're new, and returns the
               welcome: the church's words with the card's link, carrying the
               words carriers ask of a keyword sign-up (how many texts, rates,
               STOP, HELP), so the welcome is always on.
  THE CARD     /new/<code> on the church's own site: name, email, first time
               or been before, how they heard, kids, and a prayer request
               only the pastors see. Saving it names the guest, tags a first
               timer "first-time guest", keeps the prayer as a care request
               (church_prayer, pastors only), and hands the follow-up to a
               leader through church_follow_up.start, routed like a first
               text (the welcome role first). The code is random and is all
               the address carries: never a name or a number.
  THE TEXTS    three more, each the church's own words, each on or off:
                 thanks   after church, `hours` after their text (3 unless
                          the church picks 1 to 6), never in the last 15
                          minutes of its texting hours
                 monday   the note: the next Monday, 10 AM
                 invite   the Thursday before the next Sunday, 6 PM, skipped
                          when they've checked in since
               (days, times and hours are the church's own: texting_hours)
               each a chief_scheduled_actions row of type KIND, sent by
               chief_scheduler through run_scheduled(), which reads the
               church's words, the switch, STOP and the guest again at send
               time. All on the church's clock, between 9 AM and 8 PM.
  THE ROOM     GET/PUT /new-here/{business_id}: the church's word, number and
               texts, and this week's guests with where each one stands.
               POST /new-here/{business_id}/screen: its slide on Sunday's
               announcements (waiting for Media & Communications when the
               login doesn't plan Sunday). Who changes them: _may_edit (the
               weekly text's login, and since 2026-11-17 the first-time
               guests', church_duties first_guests).
  EVERY DOOR   since 2026-11-20 (the Welcome Path, guest_path.py): a guest
               from the kids desk, the welcome desk, the website's connect
               card, a church's guest card or the member app joins the same
               path and gets these texts once they've said yes ("Text me");
               see "every door" below (enroll).
  WEEKS TWO TO SIX  with the Welcome Path on (guest_path_weeks.py): the two
               roads' texts (back, thinking, next_step, door_open), the
               Monday note signed by the senior pastor (signature), the
               Saturday heads-up (heads_up), all in settings.new_here; a
               guest's hold holds every text here too, and none goes past
               the week's limits (run_scheduled asks guest_path_weeks).

Who: NEW_HERE = off | owner | on; unset is "owner", the platform's own
church (member_asks.platform_church). A church also turns it on itself
(settings.new_here.on), and it needs its own active number.

Costs: the welcome is the TwiML reply, metered like every text; each
scheduled text is one more. A guest's own texts aren't metered.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("new_here")

router = APIRouter(tags=["new-here"])

SWITCH = "NEW_HERE"
KIND = "new_here_text"                  # chief_scheduled_actions action.type
STEPS = ("thanks", "monday", "invite")
CARD_PATH = "/new"
CARD_KEY = "text:new_here"              # church_follow_ups.card_key
CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 8
LIST_DAYS = 7                           # "this week's new guests"
REVISIT_DAYS = 7                        # a second NEW inside this is the same visit
FALLBACK_TZ = ZoneInfo("America/New_York")
MAX_TEXT = 480
FIRST_NAME = "{first name}"
CARD_LINK = "{card link}"
FIRST_GUESTS = "first_guests"           # church_duties: who changes New here beside the weekly text
NOT_YOURS = ("Only the owner, an admin, or whoever does the first-time guests or the weekly text "
             "changes New here.")
SCREEN_REF = "new_here"                 # worship_announcements.source_ref of the room's Sunday slide
SCREEN_TITLE = "New here? We’d love to meet you."
SCREEN_QR_LABEL = "Scan, then send the text"

DEFAULTS: Dict[str, Any] = {
    "on": False,
    "word": "NEW",
    "welcome": ("Welcome! So glad you're here. Tell us about you: {card link} Up to 4 msgs. "
                "Msg&data rates may apply. STOP to end, HELP for help."),
    "thanks": {"on": True, "hours": 3,
               "text": ("Thank you for worshiping with us today, {first name}! It was a joy to have you. "
                        "Our door is always open.")},
    "monday": {"on": True,
               "text": ("Hi {first name}, is there anything we can pray with you about this week? Just reply. "
                        "A real person reads every text.")},
    "invite": {"on": True,
               "text": "We'd love to see you again this Sunday. Reply and we'll save you a seat and meet you at the door."},
    # Weeks two to six (the Welcome Path, guest_path_weeks.py): the two roads.
    "back": {"on": True,
             "text": "So good to see you again, {first name}! We'd love to help you find your place here."},
    "thinking": {"on": True,
                 "text": "Thinking of you this week, {first name}. No need to reply. We're glad you came."},
    "next_step": {"on": True, "event_id": None,
                  "text": ("{first name}, our {event} is {when}. We'd love for you to come. Just reply and we'll save "
                           "your seats.")},
    "door_open": {"on": True,
                  "text": "We're still so glad you visited, {first name}. Our door is always open, any Sunday."},
    # The Monday note signed by the senior pastor: `name` is the church's own
    # words for the signature ("Pastor James"); empty is whoever holds the
    # senior role (guest_path_weeks.signer).
    "signature": {"on": True, "name": ""},
    # The Saturday heads-up to the team: the greeters, and the kids desk for
    # families with kids.
    "heads_up": {"greeters": True, "kids": True},
}
# The road texts (weeks two to six), each {on, text}; next_step adds event_id.
PATH_TEXTS = ("back", "thinking", "next_step", "door_open")
EVENT = "{event}"
WHEN = "{when}"
SIGNER_MAX = 40
HEARD =("A friend or family", "Online", "Drove by", "Social media", "Other")
KIDS = ("None", "1", "2", "3 or more")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _e(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    # No "+00:00": a raw "+" in a PostgREST query string reads as a space.
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ─── the switch and the church's words ────────────────────────────────

def mode() -> str:
    m = (os.environ.get(SWITCH) or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switched_on(business_id: Any) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(business_id)
    return False


def is_church(business: Optional[Dict[str, Any]]) -> bool:
    try:
        import church_follow_up
        return church_follow_up.is_church(business or {})
    except Exception:  # noqa: BLE001
        return False


def reserved_words() -> set:
    import devotional_daily
    import sms_routing as sr
    return set(sr.STOP_WORDS) | set(sr.START_WORDS) | set(sr.HELP_WORDS) | set(sr.GIVE_WORDS) | set(
        devotional_daily.DAILY_WORDS)


def settings_of(business: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The church's New here, its saved choices over DEFAULTS, tidied: a
    saved value that isn't the right shape is the default."""
    saved = ((business or {}).get("settings") or {}).get("new_here")
    saved = saved if isinstance(saved, dict) else {}
    out: Dict[str, Any] = {"on": bool(saved.get("on", DEFAULTS["on"]))}
    word = str(saved.get("word") or "").strip().upper()
    out["word"] = word if re.fullmatch(r"[A-Z]{2,12}", word) and word not in reserved_words() else DEFAULTS["word"]
    welcome = str(saved.get("welcome") or "").strip()
    out["welcome"] = welcome[:MAX_TEXT] if welcome else DEFAULTS["welcome"]
    for step in STEPS:
        mine = saved.get(step) if isinstance(saved.get(step), dict) else {}
        base = DEFAULTS[step]
        text = str(mine.get("text") or "").strip()
        out[step] = {"on": bool(mine.get("on", base["on"])), "text": text[:MAX_TEXT] if text else base["text"]}
        if step == "thanks":
            try:
                hours = int(mine.get("hours", base["hours"]))
            except (TypeError, ValueError):
                hours = base["hours"]
            out[step]["hours"] = min(6, max(1, hours))
    for step in PATH_TEXTS:
        mine = saved.get(step) if isinstance(saved.get(step), dict) else {}
        base = DEFAULTS[step]
        text = str(mine.get("text") or "").strip()
        out[step] = {"on": bool(mine.get("on", base["on"])), "text": text[:MAX_TEXT] if text else base["text"]}
        if step == "next_step":
            event = str(mine.get("event_id") or "").strip()
            out[step]["event_id"] = event if re.fullmatch(r"[0-9a-fA-F-]{36}", event) else None
            if EVENT not in out[step]["text"] or WHEN not in out[step]["text"]:
                out[step]["text"] = base["text"]
    sig = saved.get("signature") if isinstance(saved.get("signature"), dict) else {}
    out["signature"] = {"on": bool(sig.get("on", DEFAULTS["signature"]["on"])),
                        "name": " ".join(str(sig.get("name") or "").split())[:SIGNER_MAX]}
    heads = saved.get("heads_up") if isinstance(saved.get("heads_up"), dict) else {}
    out["heads_up"] = {k: bool(heads.get(k, v)) for k, v in DEFAULTS["heads_up"].items()}
    return out


def is_word(settings: Dict[str, Any], body: str) -> bool:
    """'new', 'NEW!', ' New. ': one word, punctuation ignored."""
    words = re.sub(r"[^A-Za-z ]", " ", body or "").split()
    return len(words) == 1 and words[0].upper() == settings.get("word")


def first_name(name: Any) -> str:
    import text_room
    if text_room.nameless(name):
        return ""
    return str(name or "").strip().split()[0][:40]


def fill(text: str, *, name: str = "", link: str = "") -> str:
    """The church's words with the guest's first name and the card's link.
    No name yet: the name goes, with the comma or space before it
    ("Hi {first name}," reads "Hi,"; "today, {first name}!" reads "today!")."""
    out = text.replace(CARD_LINK, link)
    if name:
        out = out.replace(FIRST_NAME, name)
    else:
        out = re.sub(r"[ ,]*\{first name\}", "", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


# ─── reads ────────────────────────────────────────────────────────────

def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _business(business_id: str) -> Optional[Dict[str, Any]]:
    rows = _rows(f"/businesses?id=eq.{_q(business_id)}&select=id,name,type,settings,owner_id&limit=1")
    return rows[0] if rows else None


def own_number(business_id: str) -> str:
    rows = _rows(f"/sms_numbers?business_id=eq.{_q(business_id)}&status=eq.active&select=phone_number&limit=1")
    return str(rows[0].get("phone_number") or "") if rows else ""


def pretty_phone(e164: str) -> str:
    d = re.sub(r"\D", "", e164 or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if len(d) == 10 else e164


def tz_of(business: Dict[str, Any]) -> ZoneInfo:
    """The church's clock; America/New_York when it can't be read."""
    try:
        import business_marketing
        return business_marketing.business_tz(business)
    except Exception:  # noqa: BLE001
        return FALLBACK_TZ


def _origin(business_id: str) -> str:
    import church_follow_up
    return church_follow_up.site_origin(business_id)


def card_link(business_id: str, code: str) -> str:
    return f"{_origin(business_id)}{CARD_PATH}/{code}"


def new_code() -> str:
    return "".join(secrets.choice(CODE_CHARS) for _ in range(CODE_LEN))


# ─── when the texts go ────────────────────────────────────────────────

def plan_times(business: Dict[str, Any], texted_at: datetime, settings: Dict[str, Any]) -> Dict[str, datetime]:
    """{step: when, in UTC} for each step that's on and has a time to go, on
    the church's clock and inside its automatic-text hours (texting_hours:
    9 AM to 8 PM, the note Monday 10 AM, the invite Thursday 6 PM, unless the
    church picked others)."""
    import texting_hours
    hours = texting_hours.of(business)
    tz = tz_of(business)
    local = texted_at.astimezone(tz)
    day = local.date()
    earliest, latest = time(hours["auto_from"], 0), time(hours["auto_until"] - 1, 45)
    out: Dict[str, datetime] = {}

    def at(d: date, t: time) -> datetime:
        return datetime.combine(d, t, tzinfo=tz)

    if settings["thanks"]["on"]:
        when = local + timedelta(hours=settings["thanks"]["hours"])
        when = max(when, at(day, earliest))
        when = min(when, at(day, latest))
        if when >= local + timedelta(minutes=30):       # texted too late in the day: no thank-you
            out["thanks"] = when
    if settings["monday"]["on"]:
        note = hours["note"]
        ahead = (note["day"] - local.weekday()) % 7 or 7     # the next one, never today
        out["monday"] = at(day + timedelta(days=ahead), time(note["hour"], 0))
    if settings["invite"]["on"]:
        invite = hours["invite"]
        ahead = (invite["day"] - local.weekday()) % 7
        if ahead < 2:                                        # never the next day
            ahead += 7
        out["invite"] = at(day + timedelta(days=ahead), time(invite["hour"], 0))
    return {k: v.astimezone(timezone.utc) for k, v in out.items()}


# ─── a guest texts the word ───────────────────────────────────────────

def _guest(business_id: str, phone: str) -> Optional[Dict[str, Any]]:
    """The church's contact for this number, or a new guest. None when a
    read or write failed."""
    found = _rows(f"/contacts?business_id=eq.{_q(business_id)}&phone=eq.{_q(phone)}"
                  "&select=id,name,phone,tags,metadata,updated_at&order=created_at.asc&limit=1")
    if found is None:
        return None
    if found:
        return found[0]
    made = sb_clients.sb_post_as_service("/contacts", {
        "business_id": business_id, "name": phone, "phone": phone, "status": "lead", "source": "new_here"})
    return made[0] if isinstance(made, list) and made else None


def _keep(business_id: str, contact: Dict[str, Any], mine: Dict[str, Any]) -> bool:
    """contacts.metadata.new_here = mine, the rest of metadata as it was."""
    meta = dict(contact.get("metadata") or {})
    meta["new_here"] = mine
    saved = sb_clients.sb_patch_as_service(
        f"/contacts?id=eq.{_q(contact['id'])}&business_id=eq.{_q(business_id)}", {"metadata": meta})
    return saved is not None


def _schedule(business: Dict[str, Any], contact_id: str, phone: str, texted_at: datetime,
              settings: Dict[str, Any]) -> int:
    """One chief_scheduled_actions row per step that's on. Returns how many."""
    n = 0
    for step, when in plan_times(business, texted_at, settings).items():
        row = sb_clients.sb_post_as_service("/chief_scheduled_actions", {
            "business_id": str(business["id"]),
            "label": f"New here: {step}",
            "action": {"type": KIND, "step": step, "contact_id": contact_id, "phone": phone,
                       "texted_at": _iso(texted_at)},
            "run_at": when.isoformat(),
        })
        n += bool(isinstance(row, list) and row)
    return n


def on_text(business_id: str, phone: str, body: str) -> Optional[Dict[str, str]]:
    """{name, text} for the welcome when this text is the church's New here
    word, or None (not a church, not on, not its word, they said STOP, a read
    failed): the text then goes on as any other. Sync; call it in a thread.
    The caller puts the sender's name in front (sms_routing's rule)."""
    # Every text to a church's own number comes through here: anything that
    # isn't one short word (nearly every text) stops before a read.
    words = re.sub(r"[^A-Za-z ]", " ", body or "").split()
    if len(words) != 1 or not 2 <= len(words[0]) <= 12 or words[0].upper() in reserved_words():
        return None
    business = _business(business_id)
    if not business or not is_church(business) or not switched_on(business_id):
        return None
    settings = settings_of(business)
    if not settings["on"] or not is_word(settings, body):
        return None
    out = _rows(f"/sms_opt_outs?phone=eq.{_q(phone)}&or=(business_id.is.null,business_id.eq.{_q(business_id)})"
                "&select=phone&limit=1")
    if out is None or out:
        return None
    contact = _guest(business_id, phone)
    if not contact:
        return None
    mine = dict((contact.get("metadata") or {}).get("new_here") or {})
    now = _now()
    last = _parse(mine.get("texted_at"))
    on_path = bool(last and now - last < timedelta(days=REVISIT_DAYS))
    # With the Welcome Path on (guest_path), the word is also a door. A guest
    # already on another door's path this week whose texts never started
    # (no yes there) said yes by texting the word: the texts start now, on
    # that same path. One guest, one path: anyone else this week is the
    # same visit, as before.
    path = path_on(business_id)
    again = on_path and (not path or _texting(mine))
    mine["code"] = mine.get("code") or new_code()
    if not on_path:
        mine["texted_at"] = _iso(now)
        mine["visits"] = int(mine.get("visits") or 0) + 1
        if path:
            mine["door"] = "text"
    if path and not again:
        mine.update(texts_ok=True, texts="on", welcome_at=_iso(now))
    if not _keep(business_id, contact, mine):
        return None
    if not again:
        _schedule(business, str(contact["id"]), phone, now, settings)
    name = str(business.get("name") or "").strip() or "the church"
    return {"name": name, "text": fill(settings["welcome"], name=first_name(contact.get("name")),
                                       link=card_link(business_id, mine["code"])),
            "contact_id": str(contact["id"])}


# ─── the scheduled texts ──────────────────────────────────────────────

def _came_back(business_id: str, contact_id: str, texted_at: Optional[datetime]) -> bool:
    """Checked in on a later day than the one they texted. A read that fails
    is a no: the invite still goes."""
    if not texted_at:
        return False
    since = _iso(texted_at + timedelta(hours=20))
    rows = _rows(f"/attendance?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}"
                 f"&checked_in_at=gte.{_q(since)}&select=id&limit=1")
    return bool(rows)


async def run_scheduled(business: Dict[str, Any], action: Dict[str, Any]) -> Tuple[bool, str]:
    """chief_scheduler's runner for a New here text. Everything is read again
    now: the switch, the church's words, the guest, STOP. A text that
    shouldn't go any more is done, not failed. (ok, what happened)."""
    import httpx
    import sms_alerts
    import sms_routing
    import sms_service
    biz_id = str(business.get("id") or "")
    step = str(action.get("step") or "")
    contact_id, phone = str(action.get("contact_id") or ""), str(action.get("phone") or "")
    if step not in PATH_STEPS + (CONFIRM,) or not contact_id or not phone:
        return True, "Not a New here text; nothing sent."
    fresh = await asyncio.to_thread(_business, biz_id)
    if not fresh:
        return False, "The church couldn't be read; not sent."
    settings = settings_of(fresh)
    first = step in (WELCOME, CONFIRM)          # the path's first text: the welcome, or the YES question
    if not switched_on(biz_id) or not settings["on"] or (not first and not settings[step]["on"]):
        return True, "New here, or this text, is off now; not sent."
    # A guest from a door that isn't a text is on the Welcome Path: turned
    # off, its texts stop too (the text door's go on as they always did).
    door = str(action.get("door") or "text")
    path = await asyncio.to_thread(path_on, biz_id)
    if (first or door != "text") and not path:
        return True, "The Welcome Path is off now; not sent."
    if not sms_alerts.alerts_enabled():
        return True, "Automated texts are paused; not sent."
    people = await asyncio.to_thread(
        _rows, f"/contacts?id=eq.{_q(contact_id)}&business_id=eq.{_q(biz_id)}&select=id,name,phone,metadata&limit=1")
    if people is None:
        return False, "The guest couldn't be read; not sent."
    if not people:
        return True, "The guest is no longer on the church's list; not sent."
    gpw = None
    if path:
        # The Welcome Path's rules (guest_path_weeks): a reply waiting on a
        # person holds every automatic text (it waits, never dropped), and
        # no more than the week's texts the guest said yes to.
        import guest_path_weeks as gpw
        mine = (people[0].get("metadata") or {}).get("new_here") or {}
        if isinstance(mine, dict) and mine.get("hold"):
            kept = await asyncio.to_thread(gpw.wait_for_hold, fresh, people[0], action, _now())
            if kept is not None:
                return kept
            # The hold was cleared a moment ago: the text goes on now.
        if not first:
            why = gpw.limit_says(mine if isinstance(mine, dict) else {}, _now())
            if why:
                return True, gpw.LIMIT_WORDS[why]
    if step == CONFIRM:
        # Asked once, and only while the answer is still waiting: a YES that
        # came already, or another door that started the texts, needs no question.
        mine = (people[0].get("metadata") or {}).get("new_here") or {}
        if not isinstance(mine, dict) or mine.get("texts") != CONFIRM:
            return True, "Already answered; the YES question isn't needed."
    import texting_hours
    local = _now().astimezone(tz_of(fresh))
    if not texting_hours.in_auto_window(fresh, local):
        if first:
            # The welcome (or the YES question) never just goes missing: it waits for the morning.
            when = welcome_time(fresh, _now())
            row = await asyncio.to_thread(sb_clients.sb_post_as_service, "/chief_scheduled_actions", {
                "business_id": biz_id, "label": f"New here: {step}", "action": dict(action),
                "run_at": when.isoformat()})
            what = "welcome" if step == WELCOME else "YES question"
            if not (isinstance(row, list) and row):
                return False, f"Outside the church's texting hours, and the {what} couldn't be moved."
            return True, f"Outside the church's texting hours; the {what} waits for the morning."
        return True, "Outside the church's texting hours; not sent."
    if step == "invite" and await asyncio.to_thread(
            _came_back, biz_id, contact_id, _parse(action.get("texted_at"))):
        return True, "They came back; the invite isn't needed."
    name = str(fresh.get("name") or "").strip()
    guest_name = first_name(people[0].get("name"))
    if step == CONFIRM:
        words = CONFIRM_WORDS.format(church=name or "the church")
    elif step == WELCOME:
        code = str(((people[0].get("metadata") or {}).get("new_here") or {}).get("code") or "")
        if not code:
            return True, "The guest has no card to send; not sent."
        words = fill(settings["welcome"], name=guest_name,
                     link=await asyncio.to_thread(card_link, biz_id, code))
    else:
        words = fill(settings[step]["text"], name=guest_name)
        if step == "monday" and gpw is not None:
            # The Monday note, signed by the senior pastor (a setting, on
            # unless the church turned it off; no name found, no signature).
            words = gpw.sign(words, await asyncio.to_thread(gpw.signer, fresh, settings))
    body = sms_service.compose_outbound_body(name, words)
    async with httpx.AsyncClient(timeout=15) as client:
        if await sms_service.is_opted_out(client, phone, biz_id):
            return True, "They said STOP; not sent."
        try:
            sid = await sms_routing._send_platform_sms(phone, body, business_id=biz_id, client=client)
            await sms_service._store_sms(client, biz_id, contact_id, phone, body, "outbound",
                                         telnyx_id=sid or "", sent_by="system")
        except Exception as e:  # noqa: BLE001
            return False, f"The text didn't go: {e}"[:240]
    if gpw is not None and step != CONFIRM:     # the question isn't one of the week's texts
        await asyncio.to_thread(gpw.log_sent, biz_id, contact_id, _now())
    return True, f"Sent the New here {step} text."


# ─── every door: the Welcome Path ─────────────────────────────────────
#
# Kevin, 2026-11-20, on the Welcome Path mock: "capture visitors, place them
# in a flow where they receive automated texts from the church", then
# "build". Until now only a guest who texted the word got these texts; the
# kids desk, the welcome desk's First time, the website's connect card, a
# church's guest cards (Plan your visit, the bulletin's card) and the member
# app's "I'm new here" each handed the guest to a leader and texted nothing.
# Every door now joins the same path, through the code above:
#
#   enroll()        a guest from any door (guest_path.DOORS) is put on the
#                   path: contacts.metadata.new_here gets `door`, `texted_at`
#                   (the path's start, for every door), `texts_ok` (they said
#                   yes) and a card code, beside New here's own keys; and
#                   `texts`: "on", or why the texts didn't start (WHY_NOT).
#                   When they can go, the welcome (the church's welcome words,
#                   its card link and the carrier words) is queued for now,
#                   inside the church's automatic-text hours, else the next
#                   morning's; then the Monday note and the invite, as the
#                   text door plans them, and the thank-you only for a guest
#                   who was at church that day (the kids desk, the welcome
#                   desk). When they can't, the guest is on the path anyway,
#                   so they're listed and still get their call.
#                   One guest is one path: a second door inside REVISIT_DAYS
#                   never starts a second set of texts (it starts the first
#                   set when the first door had no yes and this one has).
#   keep_yes()      a door's "Text me" yes, as an sms_consents row
#                   (YES_SOURCES), with the request's address and browser.
#   text_me_words() the box's words, the way the phone companies ask for
#                   them, shown only where a yes would bring these texts.
#   second_door()   a second door's card is a note on the guest's open
#                   welcome follow-up, never a second follow-up.
#
# All of it is behind guest_path.switched_on (path_on): off, every door does
# exactly what it did before.

WELCOME = "welcome"                         # the welcome as a scheduled step (doors that aren't a text)
PATH_STEPS = (WELCOME,) + STEPS
WELCOME_SPARE = timedelta(minutes=10)       # less than this left in the hours: the next morning's
# sms_consents.source for a yes given at each door.
YES_SOURCES = {"kids": "kids_checkin", "web": "connect_card", "form": "guest_form", "app": "member_app_new"}
# A box ticked on a public web page (the website's connect card, a church's
# guest card) is a request, not a yes (M-5, 2026-11-27): anyone can type
# anyone's number. Those doors' texts start only once the phone itself
# replies YES to one question (CONFIRM); the yes is kept then (on_yes). The
# kids desk and the member app ask the person in front of them.
CONFIRM = "confirm"                         # the one question, as a scheduled step
CONFIRM_DOORS = ("web", "form")
CONFIRM_DAYS = 7                            # a YES later than this starts nothing
CONFIRM_WORDS = ("Reply YES to get texts from {church} about your visit and next steps, up to 4 msgs a "
                 "week. Msg & data rates may apply. Reply STOP to end.")
TEXT_ME = "Text me."
TEXT_ME_WORDS = ("Yes, {church} may text me about my visit and next steps, up to 4 msgs a week. "
                 "Msg & data rates may apply. Reply STOP to end, HELP for help.")
# The kids desk asks out loud: the person at the desk ticks it for the family.
TEXT_ME_ASK = ("Ask first, and tick only if they say yes: “May {church} text you about your visit and "
               "next steps? Up to 4 msgs a week. Msg & data rates may apply. Reply STOP to end, HELP for "
               "help.”")
WHY_NOT = {
    "new_here_off": "New here is off",
    "no_yes": "No yes to texts",
    "no_phone": "No mobile number",
    "no_number": "No church texting number",
    "stopped": "Said STOP",
    "unread": "Couldn't be checked or queued",
    "confirm": "Asked to reply YES",
}
# A card that says they're a regular isn't a first-time guest's.
_VISIT_Q = re.compile(r"visit|first time|been here|been before|attend|how (long|often)", re.I)
_REGULAR_A = re.compile(r"\bregular\b|\bmember\b|\ba while\b|\byears\b", re.I)


def path_on(business_id: Any) -> bool:
    """guest_path.switched_on: the Welcome Path for this church. A read
    that fails is a no: every door does what it did before."""
    try:
        import guest_path
        return bool(guest_path.switched_on(business_id))
    except Exception:  # noqa: BLE001
        return False


def mobile(phone: Any) -> str:
    """A number a text can go to (+1 and ten digits), or "". An office's
    "x2" extension is dropped first, as the kids desk reads one."""
    from sms_service import normalize_phone
    raw = re.split(r"(?i)\s*(?:x|ext\.?|extension)\s*\d", str(phone or ""))[0]
    out = normalize_phone(re.sub(r"[^\d+]", "", raw))
    return out if re.fullmatch(r"\+1[2-9]\d{9}", out or "") else ""


def says_regular(answers: Any) -> bool:
    """A card whose answer about visiting says they're a regular (or a
    member, or coming for years): not a first-time guest's path."""
    for a in answers or []:
        if isinstance(a, dict) and _VISIT_Q.search(str(a.get("q") or "")) and _REGULAR_A.search(str(a.get("a") or "")):
            return True
    return False


def can_text(business: Optional[Dict[str, Any]], number: Optional[str] = None) -> bool:
    """Whether a guest's yes would bring New here's texts from this church
    now: the Welcome Path on, New here open (NEW_HERE) and switched on by the
    church, and its own active number. A "Text me" box shows only then."""
    if not business or not is_church(business):
        return False
    biz = str(business.get("id") or "")
    if not biz or not path_on(biz) or not switched_on(biz) or not settings_of(business)["on"]:
        return False
    return bool(number if number is not None else own_number(biz))


def text_me_words(business: Optional[Dict[str, Any]], *, ask: bool = False) -> str:
    """The "Text me" box's words for this church: who texts, about how many
    a week, rates, STOP and HELP. "" where the box doesn't show (can_text).
    `ask`: the kids desk's, read out to the family. Never raises."""
    try:
        if not can_text(business):
            return ""
    except Exception:  # noqa: BLE001
        return ""
    church = " ".join(str((business or {}).get("name") or "").split()) or "our church"
    return (TEXT_ME_ASK if ask else TEXT_ME_WORDS).format(church=church)


def form_door(business: Optional[Dict[str, Any]], form: Optional[Dict[str, Any]]) -> bool:
    """A church card that is a guest door: a connect card or a Plan your
    visit card (church_follow_up.kind_for_form), or the card the church
    picked for its bulletin's guest code (guest_card.py), with the path on."""
    try:
        if not business or not form or not is_church(business) or not path_on(business.get("id")):
            return False
        import church_follow_up
        import guest_path
        if church_follow_up.kind_for_form(form) in guest_path.GUEST_FORM_KINDS:
            return True
        picked = (((business.get("settings") or {}).get("new_here") or {}).get("guest_form"))
        return bool(picked) and str(picked) == str(form.get("id") or "")
    except Exception:  # noqa: BLE001
        return False


def text_me_for_form(business: Optional[Dict[str, Any]], form: Optional[Dict[str, Any]]) -> str:
    """The box's words for a church card's public page, or "": only a guest
    door (form_door) that asks for a phone (the field the intake endpoint
    reads, "phone"), at a church whose texts would go (can_text)."""
    try:
        if not form_door(business, form):
            return ""
        if not any(isinstance(f, dict) and str(f.get("name") or "").strip() == "phone"
                   for f in (form or {}).get("fields") or []):
            return ""
        return text_me_words(business)
    except Exception:  # noqa: BLE001
        return ""


def _asks_first(source: str) -> bool:
    return str(source or "") in {YES_SOURCES[d] for d in CONFIRM_DOORS if d in YES_SOURCES}


def keep_yes(business_id: Any, phone: Any, *, source: str, name: str = "", ip: str = "",
             user_agent: str = "", confirmed: bool = False) -> bool:
    """A guest's "Text me" yes, kept as an sms_consents row: the number,
    their name, where they said it (`source`, YES_SOURCES), when, and the
    address and browser the request came from where it has them. The same
    yes from the same door is kept once. False when there's no number a text
    can go to, or it didn't save. Sync; never raises.

    A door that asks first (CONFIRM_DOORS: a box ticked on a web page) keeps
    nothing here: True says only that there's a number to ask. Its yes is
    kept when the phone replies YES (on_yes, `confirmed=True`)."""
    try:
        number = mobile(phone)
        if not number or not source:
            return False
        if _asks_first(source) and not confirmed:
            return True
        biz = str(business_id)
        had = _rows(f"/sms_consents?business_id=eq.{_q(biz)}&phone=eq.{_q(number)}&source=eq.{_q(source)}"
                    "&select=id&limit=1")
        if had:
            return True
        saved = sb_clients.sb_post_as_service("/sms_consents", {
            "phone": number, "name": " ".join(str(name or "").split())[:120] or None, "source": str(source)[:40],
            "business_id": biz, "consented_at": _iso(_now()),
            "ip": (ip or "")[:64] or None, "user_agent": (user_agent or "")[:300] or None})
        return isinstance(saved, list) and bool(saved)
    except Exception as e:  # noqa: BLE001
        print(f"[new_here] {str(business_id)[:8]}: a yes to texts wasn't kept ({type(e).__name__})", flush=True)
        return False


def has_yes(business_id: Any, phone: Any) -> Optional[bool]:
    """Whether this number has a yes to this church's texts (an sms_consents
    row of the church's). None when it couldn't be read."""
    number = mobile(phone)
    if not number:
        return False
    rows = _rows(f"/sms_consents?business_id=eq.{_q(business_id)}&phone=eq.{_q(number)}&select=id&limit=1")
    return None if rows is None else bool(rows)


def on_yes(business_id: Any, phone: Any) -> Optional[Dict[str, Any]]:
    """The phone replied YES (sms_routing, the church's own number): every
    guest of this church asked about this number in the last CONFIRM_DAYS
    has their yes kept (sms_consents, their door's source) and their
    Welcome Path texts start now, as their door would have started them.
    {"contact_ids": [...]} for the ones started, or None (nobody was asked,
    or it couldn't be read). Sync; never raises."""
    biz = str(business_id or "")
    try:
        number = mobile(phone)
        if not biz or not number:
            return None
        people = _rows(f"/contacts?business_id=eq.{_q(biz)}&phone=eq.{_q(number)}"
                       f"&metadata->new_here->>texts=eq.{CONFIRM}&select=id,name,phone,status,metadata&limit=5")
        if not people:
            return None
        business = _business(biz)
        if not business or not is_church(business) or not path_on(biz):
            return None
        settings = settings_of(business)
        now = _now()
        started: List[str] = []
        for contact in people:
            mine = dict((contact.get("metadata") or {}).get("new_here") or {})
            asked = _parse(mine.get("confirm_at"))
            if not asked or now - asked > timedelta(days=CONFIRM_DAYS):
                continue
            if str(contact.get("status") or "").strip().lower() in ("inactive", "churned"):
                continue
            door = str(mine.get("door") or "web")
            if not keep_yes(biz, number, source=YES_SOURCES.get(door, YES_SOURCES["web"]),
                            name=str(contact.get("name") or ""), user_agent="Replied YES by text", confirmed=True):
                continue
            why = _why_not(business, settings, number, True)
            welcome = None if why else welcome_time(business, now)
            mine.pop("confirm_at", None)
            mine.update(texts_ok=True, yes_at=_iso(now))
            if welcome:
                mine.update(texts="on", welcome_at=_iso(welcome))
            else:
                mine["texts"] = why
            if not _keep(biz, contact, mine):
                continue
            if welcome:
                saved = _queue(business, str(contact["id"]), number,
                               plan_path(business, now, settings, welcome=welcome),
                               door=door, texted_at=now)
                if WELCOME not in saved:
                    mine["texts"] = "unread"
                    mine.pop("welcome_at", None)
                    _keep(biz, contact, mine)
                    continue
            started.append(str(contact["id"]))
        return {"contact_ids": started} if started else None
    except Exception as e:  # noqa: BLE001: a YES is an ordinary text if this fails
        print(f"[new_here] {biz[:8]}: a YES reply wasn't taken ({type(e).__name__})", flush=True)
        return None


def _stopped(business_id: str, phone: str) -> Optional[bool]:
    rows = _rows(f"/sms_opt_outs?phone=eq.{_q(phone)}&or=(business_id.is.null,business_id.eq.{_q(business_id)})"
                 "&select=phone&limit=1")
    return None if rows is None else bool(rows)


def _texting(mine: Dict[str, Any]) -> bool:
    """Whether this path's texts started: a door's whose texts went on, and
    the text door's always (the word is the yes, and every path before the
    Welcome Path was the text door's)."""
    if mine.get("texts") == "on":
        return True
    return bool(mine.get("texted_at")) and str(mine.get("door") or "text") == "text"


def welcome_time(business: Dict[str, Any], now: datetime) -> datetime:
    """When a door's welcome goes (UTC): now when it's inside the church's
    automatic-text hours with a little to spare, else when they next open."""
    import texting_hours
    hours = texting_hours.of(business)
    tz = tz_of(business)
    local = now.astimezone(tz)
    opens = datetime.combine(local.date(), time(hours["auto_from"], 0), tzinfo=tz)
    closes = datetime.combine(local.date(), time(hours["auto_until"], 0), tzinfo=tz)
    if opens <= local and local + WELCOME_SPARE <= closes:
        return now.astimezone(timezone.utc)
    if local < opens:
        return opens.astimezone(timezone.utc)
    return datetime.combine(local.date() + timedelta(days=1), time(hours["auto_from"], 0),
                            tzinfo=tz).astimezone(timezone.utc)


def plan_path(business: Dict[str, Any], start: datetime, settings: Dict[str, Any], *, welcome: datetime,
              visit_at: Optional[datetime] = None) -> Dict[str, datetime]:
    """{step: when, in UTC} for a guest from a door that isn't a text: the
    welcome at `welcome`; the Monday note and the invite from the path's
    start, as plan_times plans the text door's, never within an hour of the
    welcome; and the thank-you only for a guest who was at church
    (`visit_at`: the kids desk, the welcome desk), `hours` after the visit,
    on that day, at least an hour after the welcome."""
    import texting_hours
    gap = timedelta(hours=1)
    out: Dict[str, datetime] = {WELCOME: welcome}
    later = plan_times(business, start, settings)
    for step in ("monday", "invite"):
        if step in later:
            out[step] = max(later[step], welcome + gap)
    if visit_at and settings["thanks"]["on"]:
        thanks = plan_times(business, visit_at, settings).get("thanks")
        if thanks:
            tz = tz_of(business)
            latest = datetime.combine(visit_at.astimezone(tz).date(),
                                      time(texting_hours.of(business)["auto_until"] - 1, 45), tzinfo=tz)
            thanks = max(thanks, welcome + gap)
            if thanks <= latest:
                out["thanks"] = thanks.astimezone(timezone.utc)
    return out


def _why_not(business: Dict[str, Any], settings: Dict[str, Any], number: str, texts_ok: Optional[bool]) -> str:
    """"" when a door's texts can go to this guest now, else why not (a
    WHY_NOT key). `texts_ok` None: their yes couldn't be read ("unread")."""
    biz = str(business["id"])
    if not switched_on(biz) or not settings["on"]:
        return "new_here_off"
    if texts_ok is None:
        return "unread"
    if not texts_ok:
        return "no_yes"
    if not number:
        return "no_phone"
    if not own_number(biz):
        return "no_number"
    stopped = _stopped(biz, number)
    if stopped is None:
        return "unread"
    return "stopped" if stopped else ""


def _queue(business: Dict[str, Any], contact_id: str, phone: str, plan: Dict[str, datetime], *,
           door: str, texted_at: datetime) -> List[str]:
    """One chief_scheduled_actions row per planned step, the welcome first:
    a welcome that doesn't save queues nothing after it. The steps saved."""
    saved: List[str] = []
    for step in sorted(plan, key=lambda s: s != WELCOME):
        row = sb_clients.sb_post_as_service("/chief_scheduled_actions", {
            "business_id": str(business["id"]),
            "label": f"New here: {step}",
            "action": {"type": KIND, "step": step, "contact_id": contact_id, "phone": phone,
                       "texted_at": _iso(texted_at), "door": door},
            "run_at": plan[step].isoformat(),
        })
        if isinstance(row, list) and row:
            saved.append(step)
        elif step == WELCOME:
            break
    return saved


def enroll(business: Optional[Dict[str, Any]], contact: Optional[Dict[str, Any]], *, door: str,
           texts_ok: Optional[bool], phone: Optional[str] = None, visit_at: Optional[datetime] = None,
           now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Put a guest from any door on the Welcome Path (see above). `phone` is
    the number they said yes for (the contact's own when not given);
    `visit_at` when they were at church, for a door that saw them there.
    `texts_ok` None: whether they said yes couldn't be read. They're on the
    path with texts "unread", never "no yes", and the next door this week
    (or the same one again) tries again; a door that says no never settles
    it either way. A path whose welcome couldn't be queued is "unread" too.
    New here's metadata as saved, or what it already was when they're on a
    path this week; None when it isn't this path's (not a church, the path
    is off, not a door) or the guest couldn't be saved. Sync; never raises."""
    import guest_path
    biz = str((business or {}).get("id") or "")
    try:
        if door not in guest_path.DOORS or not biz or not contact or not contact.get("id"):
            return None
        if not is_church(business) or not path_on(biz):
            return None
        now = now or _now()
        mine = guest_path.guest_meta(contact)
        last = _parse(mine.get("texted_at"))
        on_path = bool(last and now - last < timedelta(days=REVISIT_DAYS))
        # One guest, one path: on a path this week nothing starts again, but
        # for texts the earlier door had no yes for (a yes now), or couldn't
        # read (read again now).
        if on_path and (_texting(mine) or texts_ok is False
                        or (texts_ok is None and mine.get("texts") != "unread")
                        or (mine.get("texts") == CONFIRM and door in CONFIRM_DOORS)):
            return mine
        if not on_path:
            mine.update(door=door, texted_at=_iso(now), visits=int(mine.get("visits") or 0) + 1)
            for key in ("texts", "welcome_at", "confirm_at"):
                mine.pop(key, None)
        mine["texts_ok"] = bool(texts_ok)
        mine["code"] = mine.get("code") or new_code()
        number = mobile(contact.get("phone") if phone is None else phone)
        settings = settings_of(business)
        why = _why_not(business, settings, number, texts_ok)
        ask = None
        if not why and door in CONFIRM_DOORS:
            # Typed on a web page: ask the phone first, unless this number
            # already said yes to the church (texted the word, the kids desk,
            # a YES before). A yes that can't be read is never a no.
            had = has_yes(biz, number)
            if had is None:
                why = "unread"
            elif not had:
                ask = welcome_time(business, now)
        welcome = None if (why or ask) else welcome_time(business, now)
        if welcome:
            mine.update(texts="on", welcome_at=_iso(welcome))
        elif ask:
            mine.update(texts=CONFIRM, confirm_at=_iso(ask))
        else:
            mine["texts"] = why
        if not _keep(biz, contact, mine):
            print(f"[new_here] {biz[:8]}: a guest from the {door} door wasn't saved to the path", flush=True)
            return None
        if ask:
            saved = _queue(business, str(contact["id"]), number, {CONFIRM: ask},
                           door=str(mine.get("door") or door), texted_at=now)
            if CONFIRM not in saved:
                print(f"[new_here] {biz[:8]}: the YES question for a guest from the {door} door wasn't queued",
                      flush=True)
                mine["texts"] = "unread"
                mine.pop("confirm_at", None)
                _keep(biz, contact, mine)
            return mine
        if welcome:
            saved = _queue(business, str(contact["id"]), number,
                           plan_path(business, now, settings, welcome=welcome, visit_at=visit_at),
                           door=str(mine.get("door") or door), texted_at=visit_at or now)
            if WELCOME not in saved:
                # Nothing is queued: never "texts on" for texts that won't go.
                print(f"[new_here] {biz[:8]}: the welcome for a guest from the {door} door wasn't queued",
                      flush=True)
                mine["texts"] = "unread"
                mine.pop("welcome_at", None)
                _keep(biz, contact, mine)
        return mine
    except Exception as e:  # noqa: BLE001 — a door never fails for the path
        print(f"[new_here] {biz[:8]}: a guest from the {door} door wasn't put on the path "
              f"({type(e).__name__})", flush=True)
        return None


def enroll_by_id(business_id: Any, contact_id: Any, *, door: str, texts_ok: Optional[bool],
                 phone: Optional[str] = None, visit_at: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """enroll() for a door that has ids: the church and the guest read
    fresh. `texts_ok` None reads it: whether their number already has a yes
    to the church's texts (the kids desk's box, the welcome desk's office),
    tried twice; a read that still fails is "unread", never a no. Sync;
    never raises."""
    biz = str(business_id or "")
    try:
        if not biz or not contact_id or not path_on(biz):
            return None
        business = _business(biz)
        people = _rows(f"/contacts?id=eq.{_q(contact_id)}&business_id=eq.{_q(biz)}"
                       "&select=id,name,phone,metadata&limit=1")
        if not business or not people:
            return None
        if texts_ok is None:
            number = people[0].get("phone") if phone is None else phone
            texts_ok = has_yes(biz, number)
            if texts_ok is None:            # one more try: a blip shouldn't decide it
                texts_ok = has_yes(biz, number)
        return enroll(business, people[0], door=door, texts_ok=texts_ok, phone=phone, visit_at=visit_at)
    except Exception as e:  # noqa: BLE001
        print(f"[new_here] {biz[:8]}: a guest from the {door} door wasn't read for the path "
              f"({type(e).__name__})", flush=True)
        return None


def second_door(business_id: Any, contact_id: Any, card_key: str, answers: List[Dict[str, str]],
                said: str) -> bool:
    """With the Welcome Path on: a guest whose welcome follow-up from another
    door is open gets a note on it with what this door said (`said`, then the
    answers), never a second follow-up. One guest, one path, one caller. True
    when that note went on; False to start one as before (the path is off,
    none is open, the open one is this card's own, or the read failed: then
    church_follow_up.start decides as it always has). Never raises."""
    biz, cid = str(business_id or ""), str(contact_id or "")
    try:
        if not biz or not cid or not path_on(biz):
            return False
        import church_follow_up
        import guest_path
        rows = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}"
                     "&status=in.(open,handed_back)&select=id,card_key,path_kind&order=created_at.asc&limit=20")
        first = next((r for r in rows or [] if guest_path.is_guest_follow_up(r)
                      and str(r.get("card_key") or "") != str(card_key)), None)
        if not first:
            return False
        text = "; ".join(f"{a.get('q')} {a.get('a')}" for a in answers or [] if isinstance(a, dict))
        note = church_follow_up._note(biz, str(first["id"]), "chief", "note",
                                      (said + (f" {text}" if text else ""))[:1800])
        return note is not None
    except Exception as e:  # noqa: BLE001
        print(f"[new_here] {biz[:8]}: a second door's note wasn't added ({type(e).__name__})", flush=True)
        return False


# ─── the card ─────────────────────────────────────────────────────────

_CSS = """
:root{color-scheme:light dark;--bg:#faf7f1;--ink:#1d1a15;--muted:#655f55;--line:#ddd6c8;--card:#fff;--gold:#9a6b12;--btn:#1d1a15;--btnink:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#0e0f12;--ink:#f4f1ea;--muted:#b3ada1;--line:#34353c;--card:#16171b;--gold:#f0c46a;--btn:#e8b65a;--btnink:#1a1306}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:520px;margin:0 auto;padding:32px 20px 48px}
.k{font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--gold)}
h1{font:500 32px/1.1 Georgia,"Times New Roman",serif;margin:10px 0 6px}
p{color:var(--muted);margin:0 0 18px}
form{display:grid;gap:16px}
label{display:grid;gap:6px;font-weight:600;font-size:14px}
input[type=text],input[type=email],select,textarea{font:inherit;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--ink);width:100%}
fieldset{border:0;margin:0;padding:0;display:grid;gap:8px}legend{font-weight:600;font-size:14px;margin-bottom:8px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.opt{display:flex;gap:10px;align-items:center;font-weight:500;border:1px solid var(--line);border-radius:12px;padding:12px;background:var(--card)}
button{font:700 16px system-ui,sans-serif;padding:14px 18px;border-radius:14px;border:0;background:var(--btn);color:var(--btnink);cursor:pointer;min-height:48px}
.note{padding:12px 14px;border-radius:12px;border:1px solid var(--line);background:var(--card);margin-bottom:16px}
.small{font-size:12px;color:var(--muted)}
.hp{position:absolute;left:-10000px;width:1px;height:1px;overflow:hidden}
a{color:inherit}
.opt input[type=checkbox]{width:18px;height:18px;margin:0;accent-color:var(--gold)}
.opt-tag{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin-left:6px}
.kidsnames{display:grid}
form:has(select[name=kids] option[value="None"]:checked) .kidsnames{display:none}
"""


def _page(church_name: str, title: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{_e(title)} · {_e(church_name)}</title><style>{_CSS}</style></head>
<body><main><div class="k">{_e(church_name)}</div>{body}</main></body></html>"""


CARD_ERRORS = {
    "name": "Add your name, so we know who to welcome.",
    "email": "That email doesn't look right. Leave it empty if you'd rather.",
    "busy": "Too many tries from here just now. Try again in a minute.",
    "error": "That didn't save just now. Try again in a minute.",
}


# The Welcome Path's questions on the card (guest_brief.py reads them for the
# caller's brief): who invited them, the kids' names and ages, what they'd
# like (the member app's own choices, member_im_new.WANTS), and the best way
# to reach them. Shown only while the path is on (path_on).
REACH = {"call": "A call is fine", "text": "Text me instead"}
WANTS_SHOWN = ("group", "serve", "baptism", "class", "pastor")
INVITED_MAX, KID_NAMES_MAX = 120, 200


def _path_questions() -> str:
    import member_im_new
    wants = "".join(f'<label class="opt"><input type="checkbox" name="wants" value="{k}">'
                    f'{_e(member_im_new.WANTS[k])}</label>' for k in WANTS_SHOWN)
    reach = "".join(f'<label class="opt"><input type="radio" name="reach" value="{k}"{" checked" if k == "call" else ""}>'
                    f'{_e(v)}</label>' for k, v in REACH.items())
    return f"""<label>Who invited you?<span class="opt-tag">Optional</span>
<input type="text" name="invited" autocomplete="off" maxlength="{INVITED_MAX}"></label>
<label class="kidsnames">Your kids' names and ages<input type="text" name="kid_names" autocomplete="off" maxlength="{KID_NAMES_MAX}" placeholder="Like Sofia, 7 and Mateo, 4"></label>
<fieldset><legend>What would you like?</legend><div class="two">{wants}</div></fieldset>
<fieldset><legend>Best way to reach you</legend><div class="two">{reach}</div></fieldset>"""


def card_html(church_name: str, code: str, *, name: str = "", note: str = "", path: bool = False) -> str:
    shown = f'<div class="note" role="alert">{_e(CARD_ERRORS[note])}</div>' if note in CARD_ERRORS else ""
    heard = "".join(f"<option>{_e(h)}</option>" for h in HEARD)
    kids = "".join(f'<option value="{_e(k)}">{_e(k)}</option>' for k in KIDS)
    more = _path_questions() if path else ""
    body = f"""<h1>We're so glad you came.</h1>
<p>Tell us a little about you. It takes 30 seconds.</p>{shown}
<form method="post" action="{CARD_PATH}/{_e(code)}">
<label>Your name<input type="text" name="name" autocomplete="name" maxlength="120" value="{_e(name)}" required></label>
<label>Email (if you'd like)<input type="email" name="email" autocomplete="email" maxlength="200"></label>
<fieldset><legend>Is this your first time?</legend><div class="two">
<label class="opt"><input type="radio" name="first" value="yes" checked>First time</label>
<label class="opt"><input type="radio" name="first" value="no">I've been before</label></div></fieldset>
<div class="two"><label>How did you hear?<select name="heard">{heard}</select></label>
<label>Kids with you?<select name="kids">{kids}</select></label></div>{more}
<label>Anything we can pray for?<textarea name="prayer" rows="3" maxlength="1500" placeholder="Only our pastors see this."></textarea></label>
<div class="hp" aria-hidden="true"><label>Leave this empty<input type="text" name="website" tabindex="-1" autocomplete="off"></label></div>
<button type="submit">Send</button>
<div class="small">We'll text you up to 4 times this week. Reply STOP anytime.
<a href="/texting-terms">Texting terms</a> · <a href="/texting-privacy">Privacy</a></div>
</form>"""
    return _page(church_name, "Tell us about you", body)


def thanks_html(church_name: str, name: str) -> str:
    who = f", {_e(name)}" if name else ""
    return _page(church_name, "Thank you", f"<h1>Thank you{who}!</h1><p>We're so glad you're here. "
                                           "Someone from our church will be in touch this week.</p>")


def nothing_html(church_name: str, number: str, word: str = "") -> str:
    """/new without a card: where the Sunday slide's QR code lands. One tap
    starts the text, so a phone that scanned it is a Send away."""
    if not number:
        return _page(church_name or "Welcome", "Welcome", "<h1>Welcome!</h1><p>This link isn't working any more.</p>")
    w = _e(word or DEFAULTS["word"])
    tap = (f'<p><a href="sms:{_e(number)}?&amp;body={w}" style="display:inline-block;padding:14px 20px;'
           f'border-radius:14px;background:var(--btn);color:var(--btnink);font-weight:700;text-decoration:none">'
           f'Text {w} to {_e(pretty_phone(number))}</a></p>')
    return _page(church_name or "Welcome", "Welcome",
                 f"<h1>We're so glad you're here.</h1><p>Text <b>{w}</b> to {_e(pretty_phone(number))} and we'll "
                 f"text you back a short card to fill in.</p>{tap}")


def _church(request: Request) -> Optional[Dict[str, Any]]:
    import member_portal
    church = member_portal._church_for_request(request)
    if not church or not is_church(church["business"]) or not switched_on(church["business"].get("id")):
        return None
    return church


def _by_code(business_id: str, code: str) -> Optional[Dict[str, Any]]:
    if not re.fullmatch(rf"[{CODE_CHARS}]{{{CODE_LEN}}}", code or ""):
        return {}
    rows = _rows(f"/contacts?business_id=eq.{_q(business_id)}&metadata->new_here->>code=eq.{_q(code)}"
                 "&select=id,name,email,phone,tags,metadata&limit=1")
    if rows is None:
        return None
    return rows[0] if rows else {}


def is_card_path(path: str) -> bool:
    return path == CARD_PATH or path.startswith(CARD_PATH + "/")


async def page_for(business_id: str, path: str, query: str = "") -> Optional[Tuple[str, int]]:
    """(html, status) for /new or /new/<code> on a church's site, or None when
    it isn't this page's (not a church, not switched on): public_site then
    serves the address as it would anyway. A church's own hand-built /new
    page wins before this is asked. The card keeps working for a guest who
    got its link even after the church turns New here off."""
    from urllib.parse import parse_qs
    business = await asyncio.to_thread(_business, str(business_id))
    if not business or not is_church(business) or not switched_on(business_id):
        return None
    church_name = str(business.get("name") or "")
    code = path[len(CARD_PATH) + 1:].strip("/").upper() if path != CARD_PATH else ""
    if not code:
        number = await asyncio.to_thread(own_number, str(business_id))
        return nothing_html(church_name, number, settings_of(business)["word"]), 200
    guest = await asyncio.to_thread(_by_code, str(business_id), code)
    if guest is None:
        return _page(church_name, "One moment", "<h1>One moment</h1><p>This page couldn't load just now. "
                                                "Try again in a minute.</p>"), 503
    if not guest:
        number = await asyncio.to_thread(own_number, str(business_id))
        return nothing_html(church_name, number, settings_of(business)["word"]), 404
    q = parse_qs(query or "")
    if (q.get("done") or [""])[0] == "1":
        return thanks_html(church_name, first_name(guest.get("name"))), 200
    import text_room
    full = "" if text_room.nameless(guest.get("name")) else str(guest.get("name") or "")
    path = await asyncio.to_thread(path_on, str(business_id))
    return card_html(church_name, code, name=full, note=(q.get("note") or [""])[0], path=path), 200


def path_answers(form: Dict[str, Any]) -> Dict[str, Any]:
    """The Welcome Path's questions from a card, tidied: invited_by,
    kids_names, wants (the member app's keys), reach ("call" or "text").
    Anything that isn't one of the choices is dropped; an empty answer is
    left out."""
    import member_im_new
    out: Dict[str, Any] = {}
    invited = " ".join(str(form.get("invited") or "").split())[:INVITED_MAX]
    if invited:
        out["invited_by"] = invited
    names = " ".join(str(form.get("kid_names") or "").split())[:KID_NAMES_MAX]
    if names and str(form.get("kids") or "") not in ("", "None"):
        out["kids_names"] = names
    raw = form.get("wants") or []
    picked = {str(w) for w in (raw if isinstance(raw, (list, tuple)) else [raw])}
    wants = [k for k in member_im_new.WANTS if k in picked]
    if wants:
        out["wants"] = wants
    if str(form.get("reach") or "") in REACH:
        out["reach"] = str(form.get("reach"))
    return out


def path_lines(asked: Dict[str, Any]) -> List[Dict[str, str]]:
    """What the caller reads on the follow-up for those answers."""
    import member_im_new
    out: List[Dict[str, str]] = []
    if asked.get("invited_by"):
        out.append({"q": "Who invited them", "a": asked["invited_by"]})
    if asked.get("kids_names"):
        out.append({"q": "Their kids", "a": asked["kids_names"]})
    wants = [member_im_new.WANT_WORDS[k] for k in asked.get("wants") or [] if k in member_im_new.WANT_WORDS]
    if wants:
        said = ", ".join(wants[:-1]) + (" and " if len(wants) > 1 else "") + wants[-1]
        out.append({"q": "They'd like to", "a": said[0].upper() + said[1:]})
    if asked.get("reach"):
        out.append({"q": "Best way to reach them", "a": REACH[asked["reach"]]})
    return out


def save_card(business: Dict[str, Any], guest: Dict[str, Any], form: Dict[str, str]) -> bool:
    """Name the guest, keep what the card said, keep a prayer for the pastors,
    and hand the follow-up to a leader. False when the guest couldn't be
    saved (the rest is best-effort and never undoes it)."""
    import text_room
    biz, cid = str(business["id"]), str(guest["id"])
    name = " ".join(str(form.get("name") or "").split())[:120]
    email = str(form.get("email") or "").strip()[:200]
    first = str(form.get("first") or "yes") == "yes"
    heard = str(form.get("heard") or "")
    heard = heard if heard in HEARD else ""
    kids = str(form.get("kids") or "")
    kids = kids if kids in KIDS else ""
    prayer = str(form.get("prayer") or "").strip()[:1500]
    mine = dict((guest.get("metadata") or {}).get("new_here") or {})
    mine["card_at"] = _iso(_now())
    mine["card"] = {"first_time": first, "heard": heard, "kids": kids, "prayer": bool(prayer)}
    # The Welcome Path's questions (the card asks them only while it's on):
    # who invited them, the kids' names and ages, what they'd like, and the
    # best way to reach them. Never the prayer: that stays the pastors'.
    asked = path_answers(form) if path_on(biz) else {}
    mine["card"].update(asked)
    meta = dict(guest.get("metadata") or {})
    meta["new_here"] = mine
    patch: Dict[str, Any] = {"metadata": meta}
    if text_room.nameless(guest.get("name")) and name:
        patch["name"] = name
    if email and not guest.get("email"):
        patch["email"] = email.lower()
    tags = [t for t in (guest.get("tags") or []) if isinstance(t, str)]
    if first and "first-time guest" not in tags:
        patch["tags"] = tags + ["first-time guest"]
    if sb_clients.sb_patch_as_service(f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz)}", patch) is None:
        return False
    phone = str(guest.get("phone") or "")
    if phone:   # their texts so far are tied to them, so it stays one conversation
        sb_clients.sb_patch_as_service(
            f"/sms_messages?business_id=eq.{_q(biz)}&phone_number=eq.{_q(phone)}&contact_id=is.null",
            {"contact_id": cid})
    if prayer:
        try:
            import church_prayer
            submission = {"name": name, "email": email, "phone": phone, "prayer_request": prayer,
                          "confidential": "yes", "source": "New here card"}
            rows = sb_clients.sb_post_as_service("/ministry_care_requests", {
                "business_id": biz, "form_id": None, "contact_id": cid, "status": "new",
                "submission": submission, **church_prayer.consent_columns(submission, share=False)})
            if isinstance(rows, list) and rows:
                church_prayer.on_new(biz, rows[0])
        except Exception as e:  # noqa: BLE001
            logger.warning("new here: prayer not kept for %s: %s", biz[:8], e)
    try:
        import church_follow_up
        # The leader reads what the card said, never the prayer: prayer is
        # the pastors', never a follow-up's (church_follow_up's rule).
        answers = [{"q": "First time?", "a": "Yes" if first else "Been before"}]
        if heard:
            answers.append({"q": "How they heard", "a": heard})
        if kids and kids != "None":
            answers.append({"q": "Kids with them", "a": kids})
        answers += path_lines(asked)
        visit = str(mine.get("texted_at") or "")[:10]
        # A guest who came in by another door (the kids desk, the website's
        # card) already has someone on it: the card is a note on that one.
        if not second_door(biz, cid, CARD_KEY, answers, "Filled in the New here card."):
            church_follow_up.start(biz, cid, card_key=CARD_KEY, card_name="New here card", kind="connect",
                                   answers=answers, source_event=f"new-here:{cid}:{visit}"[:80],
                                   what="New here cards", route_answers=[])
    except Exception as e:  # noqa: BLE001
        logger.warning("new here: follow-up not started for %s: %s", biz[:8], e)
    return True


@router.post(CARD_PATH + "/{code}", include_in_schema=False)
async def card_send(code: str, request: Request):
    import rate_limit
    church = await asyncio.to_thread(_church, request)
    if not church:
        raise HTTPException(404, "Page not found")
    code = code.upper()

    def back(**q: str) -> RedirectResponse:
        query = "&".join(f"{k}={v}" for k, v in q.items())
        return RedirectResponse(f"{CARD_PATH}/{code}" + (f"?{query}" if query else ""), status_code=303)

    form = await request.form()
    if str(form.get("website") or "").strip():
        return back(done="1")                       # a bot filled the hidden box; nothing saved
    if not rate_limit.allow_strict("new_here_card", rate_limit.trusted_client_ip(request)):
        return back(note="busy")
    if not " ".join(str(form.get("name") or "").split()):
        return back(note="name")
    email = str(form.get("email") or "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return back(note="email")
    biz = church["business"]
    guest = await asyncio.to_thread(_by_code, str(biz["id"]), code)
    if guest is None:
        return back(note="error")
    if not guest:
        raise HTTPException(404, "Page not found")
    data = {k: str(form.get(k) or "") for k in ("name", "email", "first", "heard", "kids", "prayer",
                                                 "invited", "kid_names", "reach")}
    data["wants"] = [str(w) for w in (form.getlist("wants") if hasattr(form, "getlist") else [])]
    if not await asyncio.to_thread(save_card, biz, guest, data):
        return back(note="error")
    return back(done="1")


# ─── the room (Text, New here) ────────────────────────────────────────

def _may_read(business_id: str, user: AuthedUser) -> None:
    import business_access
    business_access.assert_access(business_id, user, "viewer")


def _may_edit(business_id: str, user: AuthedUser) -> bool:
    """Who changes it: who sends announcements (the owner, an admin, or the
    office login that does the weekly text), and the church Manager that
    does the first-time guests (church_duties FIRST_GUESTS: People & Care's
    by default, or whoever it was given to). Kevin, 2026-11-17: "make sure
    that Tiara also has the ability to make sure that things like qr code and
    stuff is made for guest as well." The weekly text itself stays the
    Office's (sms_routing._may_announce is unchanged). A duty that can't be
    read is a 503, never a yes."""
    import sms_routing
    try:
        sms_routing._may_announce(business_id, user)
        return True
    except HTTPException as no:
        if no.status_code == 503:
            raise
        if no.status_code != 403:
            return False            # below a Manager, or not a church: no duty decides it
    # A church's Manager that doesn't do the weekly text (its 403).
    import church_duties
    return church_duties.holds(business_id, user, FIRST_GUESTS)


def _may_edit_quietly(business_id: str, user: AuthedUser) -> bool:
    """The room's can_edit: a duty that can't be read hides the buttons and
    the room still reads (a change asks again, and is a 503)."""
    try:
        return _may_edit(business_id, user)
    except HTTPException as e:
        if e.status_code != 503:
            raise
        return False


def _uuid(v: Any) -> str:
    from uuid import UUID
    try:
        return str(UUID(str(v)))
    except (TypeError, ValueError):
        raise HTTPException(404, "Church not found")


def _app_of(person: Dict[str, Any]) -> Dict[str, Any]:
    """What a member told the church in the member app's "I'm new here"
    (member_im_new: contacts.metadata.new_here.app), or {}."""
    app = ((person.get("metadata") or {}).get("new_here") or {}).get("app")
    return app if isinstance(app, dict) and app.get("at") else {}


def _app_card(app: Dict[str, Any]) -> Dict[str, Any]:
    """The member app's answers in the shape the room reads a card in (kids
    "None" when they have none, as the card's list says it)."""
    kids = (app.get("ages") or "Yes") if app.get("kids") == "yes" else "None"
    return {"first_time": bool(app.get("first_time")), "heard": app.get("heard") or "", "kids": kids,
            "prayer": bool(app.get("prayer")), "wants": list(app.get("wants") or [])}


def guests_of(business: Dict[str, Any], *, days: int = LIST_DAYS) -> Optional[List[Dict[str, Any]]]:
    """This week's guests, newest first, with where each one stands: the
    ones who texted the word, and (since 2026-11-19) members who said "I'm
    new here" in the member app (member_im_new), each with `from` ("text" or
    "app") and `app_at`. Since the Welcome Path (2026-11-20), every door's
    guest (their texted_at is the path's start), each with `door` (a
    guest_path.DOORS key: metadata door, else "text" for one who texted the
    word and "app" for the member app), `texts_ok` and `texts` (WHY_NOT), and
    the follow-up any door made for them. None when it couldn't be read."""
    import guest_path
    import member_im_new
    biz = str(business["id"])
    welcome_path = path_on(biz)
    since_dt = _now() - timedelta(days=days)
    since = _iso(since_dt)
    people = _rows(f"/contacts?business_id=eq.{_q(biz)}&metadata->new_here->>texted_at=gte.{_q(since)}"
                   "&select=id,name,phone,metadata&order=updated_at.desc&limit=100")
    if people is None:
        return None
    # The member app's: a failed read leaves them out, never the list.
    told = _rows(f"/contacts?business_id=eq.{_q(biz)}&metadata->new_here->app->>at=gte.{_q(since)}"
                 "&select=id,name,phone,metadata&order=updated_at.desc&limit=100") or []
    texted_ids = {str(p["id"]) for p in people}
    app_only = [p for p in told if str(p.get("id")) not in texted_ids
                and (_parse(_app_of(p).get("at")) or since_dt) > since_dt]
    people = people + app_only
    if not people:
        return []
    ids = ",".join(_q(p["id"]) for p in people)
    if welcome_path:
        # Every door's welcome follow-up (the kids desk's, the website's, a
        # church card's, New here's, the member app's), the newest first.
        follows = [f for f in _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&contact_id=in.({ids})"
                                    "&select=contact_id,status,step,leader_contact_id,created_at,card_key,path_kind"
                                    "&order=created_at.desc") or [] if guest_path.is_guest_follow_up(f)]
    else:
        follows = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&contact_id=in.({ids})"
                        f"&card_key=eq.{_q(CARD_KEY)}&select=contact_id,status,step,leader_contact_id,created_at"
                        "&order=created_at.desc") or []
    if app_only and not welcome_path:
        # The member app's own follow-up first (someone who texted long ago
        # and has that one open got a note on it instead: it shows then).
        app_ids = ",".join(_q(p["id"]) for p in app_only)
        follows = (_rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&contact_id=in.({app_ids})"
                         f"&card_key=eq.{_q(member_im_new.CARD_KEY)}"
                         "&select=contact_id,status,step,leader_contact_id,created_at"
                         "&order=created_at.desc") or []) + follows
    by_contact: Dict[str, Dict[str, Any]] = {}
    for f in follows:
        by_contact.setdefault(str(f.get("contact_id")), f)
    leader_ids = sorted({str(f["leader_contact_id"]) for f in by_contact.values() if f.get("leader_contact_id")})
    leaders: Dict[str, str] = {}
    if leader_ids:
        for r in _rows(f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in leader_ids)})"
                       "&select=id,name") or []:
            leaders[str(r["id"])] = str(r.get("name") or "")
    import text_room
    out = []
    for p in people:
        mine = (p.get("metadata") or {}).get("new_here") or {}
        card = mine.get("card") if isinstance(mine.get("card"), dict) else None
        app = _app_of(p)
        texted = bool(mine.get("texted_at"))
        door = str(mine.get("door") or ("text" if texted else "app"))
        door = door if door in guest_path.DOORS else "text"
        f = by_contact.get(str(p["id"]))
        reached = bool(f and (f.get("status") == "done" or int(f.get("step") or 0) >= 1))
        out.append({
            "contact_id": str(p["id"]),
            "name": "" if text_room.nameless(p.get("name")) else str(p.get("name") or ""),
            "phone_last4": re.sub(r"\D", "", str(p.get("phone") or ""))[-4:],
            "texted_at": mine.get("texted_at"),
            # A member who told the church in the app: their answers are the card.
            "card_at": mine.get("card_at") or (app.get("at") if door == "app" or not texted else None),
            "card": card or (_app_card(app) if app else None),
            "from": "app" if door == "app" else "text",
            "door": door,
            "texts_ok": bool(mine["texts_ok"]) if "texts_ok" in mine else door == "text",
            "texts": mine.get("texts") or ("on" if door == "text" else None),
            "app_at": app.get("at"),
            "follow_up": None if not f else {
                "leader": leaders.get(str(f.get("leader_contact_id") or ""), ""),
                "status": f.get("status"), "reached": reached},
        })
    out.sort(key=lambda g: str(g.get("texted_at") or g.get("app_at") or ""), reverse=True)
    return out


def counts_of(business: Dict[str, Any], guests: List[Dict[str, Any]]) -> Dict[str, int]:
    tz = tz_of(business)
    today = _now().astimezone(tz).date()
    sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    # The texts' numbers: a member who told the church in the app is listed,
    # never counted as a text.
    guests = [g for g in guests if g.get("texted_at")]
    on_sunday = [g for g in guests if (_parse(g.get("texted_at")) or _now()).astimezone(tz).date() == sunday]
    month_start = datetime.combine(today.replace(day=1), time(0, 0), tzinfo=tz)
    month = _rows(f"/contacts?business_id=eq.{_q(business['id'])}"
                  f"&metadata->new_here->>texted_at=gte.{_q(_iso(month_start))}&select=id&limit=1000")
    return {"sunday": len(on_sunday),
            "card": sum(1 for g in on_sunday if g.get("card_at")),
            "reached": sum(1 for g in on_sunday if (g.get("follow_up") or {}).get("reached")),
            "month": len(month) if month is not None else len(guests)}


def _hours(business: Dict[str, Any]) -> Dict[str, Any]:
    import texting_hours as th
    h = th.of(business)
    return {**h, "words": {
        "window": f"{th.hour_words(h['auto_from'])} to {th.hour_words(h['auto_until'])}",
        "latest": f"{th.hour_words(h['auto_until'] - 1).split()[0]}:45 {th.hour_words(h['auto_until'] - 1).split()[-1]}",
        "note": f"{th.DAY_NAMES[h['note']['day']]} at {th.hour_words(h['note']['hour'])}",
        "invite": f"{th.DAY_NAMES[h['invite']['day']]} at {th.hour_words(h['invite']['hour'])}"}}


def overview(business: Dict[str, Any], *, can_edit: bool) -> Dict[str, Any]:
    biz = str(business["id"])
    settings = settings_of(business)
    number = own_number(biz)
    guests = guests_of(business)
    return {
        "switched_on": switched_on(biz),
        "can_edit": can_edit,
        "settings": settings,
        "defaults": DEFAULTS,
        "number": number,
        "number_pretty": pretty_phone(number) if number else "",
        "sms_link": f"sms:{number}?&body={settings['word']}" if number else "",
        # The church's /new: where the Sunday slide's QR code points (the
        # announcement board takes only https links), and a sample card link
        # so the room can count the welcome's length as it will leave.
        "card_home": f"{_origin(biz)}{CARD_PATH}",
        "card_sample": f"{_origin(biz)}{CARD_PATH}/ABCD2345",
        "guests": guests,
        "counts": counts_of(business, guests or []),
        "texts_per_guest": 1 + sum(1 for s in STEPS if settings[s]["on"]),
        # When the texts go (Text → Texting hours): the room says it in words.
        "hours": _hours(business),
        # Weeks two to six, the signature and the Saturday heads-up, only
        # where the Welcome Path is on: a room that doesn't get this shows
        # week one alone, as before.
        **({"path": _path_view(business, settings)} if path_on(biz) else {}),
    }


def _path_view(business: Dict[str, Any], settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """guest_path_weeks.room_view, or None when it couldn't be read (the room
    says so and keeps week one)."""
    try:
        import guest_path_weeks
        return guest_path_weeks.room_view(business, settings)
    except Exception as e:  # noqa: BLE001 — the room still reads week one
        print(f"[new_here] {str(business.get('id'))[:8]}: the path's view wasn't read ({type(e).__name__})",
              flush=True)
        return None


@router.get("/new-here/{business_id}")
def get_new_here(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _may_read(biz, user)
    business = _business(biz)
    if not business:
        raise HTTPException(503, "The church couldn't be read just now. Try again in a minute.")
    if not is_church(business):
        raise HTTPException(404, "New here is for churches.")
    return overview(business, can_edit=_may_edit_quietly(biz, user))


class StepIn(BaseModel):
    on: bool = True
    text: str = Field("", max_length=MAX_TEXT)
    hours: Optional[int] = None


class PathStepIn(BaseModel):
    on: bool = True
    text: str = Field("", max_length=MAX_TEXT)
    event_id: Optional[str] = Field(None, max_length=40)


class SignatureIn(BaseModel):
    on: bool = True
    name: str = Field("", max_length=SIGNER_MAX)


class HeadsUpIn(BaseModel):
    greeters: bool = True
    kids: bool = True


class NewHereIn(BaseModel):
    on: bool
    word: str = Field("NEW", max_length=12)
    welcome: str = Field("", max_length=MAX_TEXT)
    thanks: StepIn
    monday: StepIn
    invite: StepIn
    # Weeks two to six, the signature and the Saturday heads-up (the Welcome
    # Path). Each is optional: a room that doesn't send one (Text › New here,
    # an app from before) leaves what's saved exactly as it was.
    back: Optional[PathStepIn] = None
    thinking: Optional[PathStepIn] = None
    next_step: Optional[PathStepIn] = None
    door_open: Optional[PathStepIn] = None
    signature: Optional[SignatureIn] = None
    heads_up: Optional[HeadsUpIn] = None


# "Reply YES": YES is a word the phone companies read as "start my texts
# again" (sms_routing.START_WORDS), never a church's reply word.
_REPLY_START = re.compile(r"\breply\s+(?:with\s+)?[\"'“‘]?(?:yes|start|join|unstop)\b", re.I)


def _path_text(step: str, s: PathStepIn) -> Dict[str, Any]:
    text = " ".join((s.text or DEFAULTS[step]["text"]).split())
    if CARD_LINK in text:
        raise HTTPException(400, "Only the welcome carries the card's link.")
    if _REPLY_START.search(text):
        raise HTTPException(400, "YES means \"start my texts again\" to the phone companies. Ask them to just "
                                 "reply instead.")
    out: Dict[str, Any] = {"on": bool(s.on), "text": text}
    if step == "next_step":
        if EVENT not in text or WHEN not in text:
            raise HTTPException(400, "Keep {event} and {when} in the next step's words: they become your event's "
                                     "name and its day.")
        event = (s.event_id or "").strip()
        if event and not re.fullmatch(r"[0-9a-fA-F-]{36}", event):
            raise HTTPException(400, "Pick one of your church's upcoming events.")
        out["event_id"] = event or None
    return out


def clean(body: NewHereIn) -> Dict[str, Any]:
    """What gets saved, or a 400 that says what to change. The Welcome
    Path's keys only when the room sent them (merge never touches a key it
    isn't given)."""
    word = re.sub(r"[^A-Za-z]", "", body.word or "").upper()
    if not re.fullmatch(r"[A-Z]{2,12}", word):
        raise HTTPException(400, "The word is 2 to 12 letters, like NEW or HELLO.")
    if word in reserved_words():
        raise HTTPException(400, f"{word} already means something to the phone companies or the church's "
                                 "number. Pick another word.")
    welcome = " ".join((body.welcome or DEFAULTS["welcome"]).split())
    if CARD_LINK not in welcome:
        raise HTTPException(400, "Keep {card link} in the welcome: it's how a guest gets to the card.")
    if "STOP" not in welcome.upper():
        raise HTTPException(400, "Keep \"STOP to end\" in the welcome: the phone companies require it.")
    out: Dict[str, Any] = {"on": bool(body.on), "word": word, "welcome": welcome}
    for step in STEPS:
        s: StepIn = getattr(body, step)
        text = " ".join((s.text or DEFAULTS[step]["text"]).split())
        if CARD_LINK in text:
            raise HTTPException(400, "Only the welcome carries the card's link.")
        out[step] = {"on": bool(s.on), "text": text}
        if step == "thanks":
            out[step]["hours"] = min(6, max(1, int(s.hours or DEFAULTS["thanks"]["hours"])))
    for step in PATH_TEXTS:
        s = getattr(body, step)
        if s is not None:
            out[step] = _path_text(step, s)
    if body.signature is not None:
        out["signature"] = {"on": bool(body.signature.on), "name": " ".join((body.signature.name or "").split())}
    if body.heads_up is not None:
        out["heads_up"] = {"greeters": bool(body.heads_up.greeters), "kids": bool(body.heads_up.kids)}
    return out


@router.put("/new-here/{business_id}")
def put_new_here(business_id: str, body: NewHereIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _may_read(biz, user)
    if not _may_edit(biz, user):
        raise HTTPException(403, NOT_YOURS)
    business = _business(biz)
    if not business:
        raise HTTPException(503, "The church couldn't be read just now. Try again in a minute.")
    if not is_church(business):
        raise HTTPException(404, "New here is for churches.")
    # Only New here's own keys, laid over settings.new_here in one write
    # (business_settings.merge): the rest of the row, and a key another
    # endpoint keeps inside new_here (the church's guest card, guest_card.py),
    # stay as they are, whatever was written a moment ago.
    import business_settings
    saving = clean(body)
    picked = (saving.get("next_step") or {}).get("event_id")
    if picked and picked != settings_of(business)["next_step"]["event_id"]:
        # A newly picked next step is one of the church's own upcoming events.
        import guest_path_weeks
        coming = guest_path_weeks.events_coming(business)
        if coming is None:
            raise HTTPException(503, "Your events couldn't be read just now. Try again in a minute.")
        if not any(e["entry_id"] == picked for e in coming):
            raise HTTPException(400, "That event isn't coming up in Services & Events. Pick another.")
    settings = business_settings.merge(biz, set=saving, under=["new_here"])
    if settings is None:
        raise HTTPException(503, "That didn't save just now. Try again in a minute.")
    return overview({**business, "settings": settings}, can_edit=True)


# ─── "Put it on Sunday's screen" ──────────────────────────────────────

def _asker(biz: str, user: AuthedUser) -> str:
    """Who sent the slide, as the app greets them, for the board's Waiting
    for you; the part of their email before the @ when no name is found."""
    try:
        import business_users_router
        name = str((business_users_router.seat_person(biz, str(user.id)) or {}).get("name") or "").strip()
    except Exception:  # noqa: BLE001 — a name is a courtesy; the request still goes
        name = ""
    return (name or (user.email or "").split("@")[0] or "Someone on the team")[:80]


def screen_slide(business: Dict[str, Any], number: str, today: date) -> Dict[str, Any]:
    """The room's slide as an announcement (worship_announce.clean): the
    church's word and number, a QR code to its /new when the church has an
    https address, in the room and the lobby, from today until it's taken off."""
    import worship_announce as wa
    word = settings_of(business)["word"]
    raw: Dict[str, Any] = {
        "title": SCREEN_TITLE, "body": f"Text {word} to {pretty_phone(number)}", "design": "side",
        "shows": {"room": True, "lobby": True, "online": False, "phones": False},
        "show_from": today.isoformat(),
    }
    home = f"{_origin(str(business['id']))}{CARD_PATH}"
    if home.startswith("https://"):
        raw["qr"] = {"kind": "link", "url": home, "label": SCREEN_QR_LABEL}
    return wa.clean(raw)


def _from_lane(biz: str, user: AuthedUser) -> str:
    """The lane the slide comes from, in the line Media reads: People & Care's
    for whoever does the first-time guests, Office & Leadership's for the
    weekly text. "" when neither can be said."""
    import church_duties
    try:
        for duty in (FIRST_GUESTS, "weekly_text"):
            if church_duties.holds(biz, user, duty):
                return church_duties.lane_label(church_duties.CATALOG[duty]["lanes"][0])
    except HTTPException:
        pass
    return ""


def waiting_line(sent_by: Optional[Dict[str, Any]]) -> str:
    """The one line whoever puts a waiting slide on reads (My week, the push)."""
    frm = str((sent_by or {}).get("from") or "").strip()
    return (f"A guest slide from {frm} is waiting for you to put on Sunday’s screen." if frm
            else "A New here guest slide is waiting for you to put on Sunday’s screen.")


def _plan_duties() -> Tuple[str, ...]:
    """The duties that give a Manager the plan's part (worship_team
    PARTS_FROM_DUTIES: sunday_plan, production_schedule, churchsavvy_team;
    Media & Communications' by default)."""
    import worship_team as wt
    return tuple(d for d, parts in wt.PARTS_FROM_DUTIES.items() if wt.can(set(parts), "plan"))


def decides(biz: str, user_id: Any, role: Optional[str]) -> bool:
    """Whether this login puts a waiting slide on: the board's decide gate
    (worship_team's plan part), by its seat. The owner and the admins; a
    Manager by the duties that give the part; anyone by their ChurchSavvy
    team parts. A read that fails is a 503."""
    import worship_team as wt
    if role in ("owner", "admin"):
        return True
    if role == "manager":
        import church_duties
        if set(church_duties.standing(biz, str(user_id))["duties"]) & set(_plan_duties()):
            return True
    return wt.can(wt.parts_of(biz, user_id), "plan")


def deciders(biz: str) -> List[str]:
    """Who hears that a slide waits: the Manager logins whose duties give the
    plan's part and the ChurchSavvy team's planners, worship leaders and
    admins with a login; with no one there, the owner (as a late office task
    goes up to the owner with no Executive Pastor). A read that fails is a 503."""
    import church_duties
    import worship_team as wt
    out: List[str] = []
    for duty in _plan_duties():
        for uid in church_duties.manager_holders(biz, duty):
            if uid not in out:
                out.append(uid)
    team = sb_clients.sb_get_as_service(f"/worship_team?business_id=eq.{_q(biz)}&status=eq.active"
                                        "&user_id=not.is.null&select=user_id,roles&limit=100")
    if not isinstance(team, list):
        raise HTTPException(503, "The team couldn't be read just now.")
    for r in team:
        uid = str(r.get("user_id") or "")
        if uid and uid not in out and wt.can({p for p in r.get("roles") or [] if p in wt.ROLES}, "plan"):
            out.append(uid)
    if not out:
        owner = str((_business(biz) or {}).get("owner_id") or "")
        out = [owner] if owner else []
    return out


SCREEN_NAV = "operate:worship-announcements"    # church_my_week DOOR["announcements"]


def tell_deciders(biz: str, sent_by: Dict[str, Any], asker_id: str) -> int:
    """One push to each login that puts the waiting slide on (never the one
    who sent it). Best effort: a failure is a log line, the slide still
    waits on the board and in their My week."""
    try:
        import push_notifications
        line = waiting_line(sent_by)
        return sum(push_notifications.send_to_user(uid, title="Sunday’s screen", body=line, nav=SCREEN_NAV,
                                                   tag="new-here-slide", business_id=biz)
                   for uid in deciders(biz) if uid != str(asker_id))
    except Exception as e:  # noqa: BLE001 — telling is a courtesy; the request already answered
        print(f"[new_here] {biz[:8]}: the waiting slide's push didn't go: {e}", flush=True)
        return 0


def week_item(business: Dict[str, Any], user_id: Any, role: Optional[str]) -> Optional[Dict[str, Any]]:
    """My week's line (church_my_week.build) for whoever puts a waiting New
    here slide on (decides), until it's put on or left off. Nothing when none
    waits, for anyone else, and when a read fails: the week stands, the log
    says so."""
    if not is_church(business):
        return None
    biz = str(business["id"])
    rows = _rows(f"/worship_announcements?business_id=eq.{_q(biz)}&source_ref=eq.{_q(SCREEN_REF)}"
                 "&status=eq.waiting&archived_at=is.null&select=id,sent_by&order=created_at.desc&limit=1")
    if rows is None:
        print(f"[new_here] {biz[:8]}: a waiting slide wasn't read for My week", flush=True)
        return None
    if not rows:
        return None
    try:
        if not decides(biz, user_id, role):
            return None
    except HTTPException:
        print(f"[new_here] {biz[:8]}: who puts the slide on wasn't read for My week", flush=True)
        return None
    import church_my_week
    sent = rows[0].get("sent_by") if isinstance(rows[0].get("sent_by"), dict) else {}
    who = str(sent.get("name") or "").split(" ")[0]
    return {"kind": "screen", "late": False, "area": "worship_media", "title": waiting_line(sent),
            "detail": (f"{who} sent it from New here. " if who else "") + "Put it on in Announcements, under Waiting for you.",
            "door": church_my_week.DOOR["announcements"]}


def sunday_cards(business: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """The first-time guests' Sunday line in How your week goes
    (church_my_week.rhythm): the New here cards out on the welcome table and
    the seats (Kevin approved, 2026-11-17). Never judged done: nothing counts
    cards on a table. None where New here isn't open for the church (the
    NEW_HERE switch); while the church has it off, the line says to switch it
    on first."""
    try:
        if not is_church(business) or not switched_on(business.get("id")):
            return None
    except Exception:  # noqa: BLE001 — a line on My week never fails the week
        return None
    if settings_of(business)["on"]:
        does = ("The New here cards (QR) are out on the welcome table and the seats. Print seat cards is in "
                "Text, New here.")
    else:
        does = ("New here is off: switch it on in Text, New here, then put its cards (QR) out on the welcome "
                "table and the seats.")
    return {"label": "The New here cards", "does": does}


@router.post("/new-here/{business_id}/screen")
def put_on_screen(business_id: str, background: BackgroundTasks, user: AuthedUser = Depends(require_user)):
    """The room's "Put it on Sunday's screen": its slide on the announcements
    board (worship_announce_router). Whoever plans Sunday (the plan's part: a
    planner, the worship leader, an admin, the owner) puts it straight on, as
    the board itself does. Whoever else changes New here (the first-time
    guests' login, the weekly text's) sends it waiting, and whoever plans
    Sunday puts it on from the board's Waiting for you (its decide route, the
    plan's part, unchanged). Sunday's announcements stay Media &
    Communications' job: this asks, it never approves. Only this slide: its
    words are the room's, never the caller's, and one waits at a time."""
    import church_duties
    import worship_announce as wa
    import worship_announce_router as war
    import worship_router
    import worship_team
    biz = _uuid(business_id)
    _may_read(biz, user)
    if not _may_edit(biz, user):
        raise HTTPException(403, NOT_YOURS)
    business = _business(biz)
    if not business:
        raise HTTPException(503, "The church couldn't be read just now. Try again in a minute.")
    if not is_church(business):
        raise HTTPException(404, "New here is for churches.")
    number = own_number(biz)
    if not number:
        raise HTTPException(409, "New here works on your church’s own texting number. Set one up in Texting "
                                 "settings first.")
    if not worship_router.open_to(user):
        raise HTTPException(404, "Sunday’s screens aren’t open for your church yet.")
    # The parts the board goes by (a 503 when they can't be read; a 402 when a
    # church on ChurchSavvy alone hasn't the screens in its plan).
    plans = worship_team.can(worship_team.roles_of(biz, user), "plan")
    media = church_duties.lane_label("media_comms")
    today = war.church_today(biz)
    try:
        row = screen_slide(business, number, today)
    except ValueError as e:
        raise HTTPException(400, str(e))
    have = war._read(f"/worship_announcements?business_id=eq.{_q(biz)}&archived_at=is.null"
                     f"&select=id,status,source_ref,show_from,show_until&limit={wa.MAX_PER_CHURCH}",
                     "The announcements")
    if not plans:
        mine = [a for a in have if a.get("source_ref") == SCREEN_REF]
        if any(a.get("status") == "waiting" for a in mine):
            return {"status": "waiting", "already": True,
                    "said": f"It’s already waiting for {media} to put on Sunday’s screen."}
        if any(a.get("status") == "on" and wa.state(a, today) in ("now", "soon") for a in mine):
            return {"status": "on", "already": True, "said": "It’s already on Sunday’s screen."}
    if len(have) >= wa.MAX_PER_CHURCH:
        raise HTTPException(400, f"A church keeps up to {wa.MAX_PER_CHURCH} announcements. Take a few old ones "
                                 "off first.")
    now = war._now()
    status = "on" if plans else "waiting"
    rec: Dict[str, Any] = {"business_id": biz, **row, "status": status, "source": "typed",
                           "source_ref": SCREEN_REF, "created_at": now, "updated_at": now}
    if not plans:
        rec["sent_by"] = {"ministry": "New here", "name": _asker(biz, user), "from": _from_lane(biz, user),
                          "at": now}
    saved = sb_clients.sb_post_as_service("/worship_announcements?select=id,status", rec,
                                          prefer="return=representation")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "It wasn’t sent just now. Try again.")
    if not plans:
        # Whoever puts it on hears once, after the answer (a push never holds it up).
        background.add_task(tell_deciders, biz, rec["sent_by"], str(user.id))
    if plans:
        return {"status": "on", "already": False,
                "said": "Added to your announcements. It shows on Sunday’s screen until you take it off."}
    return {"status": "waiting", "already": False,
            "said": f"Sent to {media} to put on Sunday’s screen. It shows once they put it on."}


class ResendIn(BaseModel):
    contact_id: str


@router.post("/new-here/{business_id}/resend")
async def resend_card(business_id: str, body: ResendIn, user: AuthedUser = Depends(require_user)):
    """Text a guest the card's link again (they didn't fill it in)."""
    import business_access
    import httpx
    import sms_routing
    import sms_service
    biz = _uuid(business_id)
    business_access.assert_access(biz, user, "member")
    business = await asyncio.to_thread(_business, biz)
    if not business or not is_church(business):
        raise HTTPException(404, "New here is for churches.")
    cid = _uuid(body.contact_id)
    people = await asyncio.to_thread(
        _rows, f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz)}&select=id,name,phone,metadata&limit=1")
    if people is None:
        raise HTTPException(503, "The guest couldn't be read just now. Try again in a minute.")
    mine = ((people[0].get("metadata") or {}).get("new_here") or {}) if people else {}
    if not people or not mine.get("code") or not people[0].get("phone"):
        raise HTTPException(404, "That guest didn't come through New here.")
    # A guest from another door who never said yes to texts (the Welcome
    # Path's texts_ok) is called, never texted.
    if mine.get("texts_ok") is False:
        raise HTTPException(409, "They haven't said yes to the church's texts, so the card can't be texted to them.")
    phone = str(people[0]["phone"])
    link = await asyncio.to_thread(card_link, biz, mine["code"])
    text = sms_service.compose_outbound_body(
        str(business.get("name") or ""), f"Here's the card again, whenever you have 30 seconds: {link}")
    async with httpx.AsyncClient(timeout=15) as client:
        if await sms_service.is_opted_out(client, phone, biz):
            raise HTTPException(409, "They said STOP, so the church can't text them.")
        sid = await sms_routing._send_platform_sms(phone, text, business_id=biz, client=client)
        await sms_service._store_sms(client, biz, cid, phone, text, "outbound", telnyx_id=sid or "",
                                     sent_by="practitioner")
    return {"ok": True}
