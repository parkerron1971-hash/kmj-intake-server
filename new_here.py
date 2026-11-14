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
                          the church picks 1 to 6), never after 7:45 PM
                 monday   the next Monday, 10 AM
                 invite   the Thursday before the next Sunday, 6 PM, skipped
                          when they've checked in since
               each a chief_scheduled_actions row of type KIND, sent by
               chief_scheduler through run_scheduled(), which reads the
               church's words, the switch, STOP and the guest again at send
               time. All on the church's clock, between 9 AM and 8 PM.
  THE ROOM     GET/PUT /new-here/{business_id}: the church's word, number and
               texts, and this week's guests with where each one stands.

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

from fastapi import APIRouter, Depends, HTTPException, Request
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
EARLIEST, LATEST = time(9, 0), time(19, 45)   # inside texting's 9 AM to 8 PM
FALLBACK_TZ = ZoneInfo("America/New_York")
MAX_TEXT = 480
FIRST_NAME = "{first name}"
CARD_LINK = "{card link}"

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
}
HEARD = ("A friend or family", "Online", "Drove by", "Social media", "Other")
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


def card_link(business_id: str, code: str) -> str:
    import church_follow_up
    return f"{church_follow_up.site_origin(business_id)}{CARD_PATH}/{code}"


def new_code() -> str:
    return "".join(secrets.choice(CODE_CHARS) for _ in range(CODE_LEN))


# ─── when the texts go ────────────────────────────────────────────────

def plan_times(business: Dict[str, Any], texted_at: datetime, settings: Dict[str, Any]) -> Dict[str, datetime]:
    """{step: when, in UTC} for each step that's on and has a time to go."""
    tz = tz_of(business)
    local = texted_at.astimezone(tz)
    day = local.date()
    out: Dict[str, datetime] = {}

    def at(d: date, t: time) -> datetime:
        return datetime.combine(d, t, tzinfo=tz)

    if settings["thanks"]["on"]:
        when = local + timedelta(hours=settings["thanks"]["hours"])
        when = max(when, at(day, EARLIEST))
        when = min(when, at(day, LATEST))
        if when >= local + timedelta(minutes=30):       # texted too late in the day: no thank-you
            out["thanks"] = when
    if settings["monday"]["on"]:
        ahead = (0 - local.weekday()) % 7 or 7          # the next Monday, never today
        out["monday"] = at(day + timedelta(days=ahead), time(10, 0))
    if settings["invite"]["on"]:
        ahead = (3 - local.weekday()) % 7               # Thursday
        if ahead < 2:
            ahead += 7
        out["invite"] = at(day + timedelta(days=ahead), time(18, 0))
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
    again = bool(last and now - last < timedelta(days=REVISIT_DAYS))
    mine["code"] = mine.get("code") or new_code()
    if not again:
        mine["texted_at"] = _iso(now)
        mine["visits"] = int(mine.get("visits") or 0) + 1
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
    if step not in STEPS or not contact_id or not phone:
        return True, "Not a New here text; nothing sent."
    fresh = await asyncio.to_thread(_business, biz_id)
    if not fresh:
        return False, "The church couldn't be read; not sent."
    settings = settings_of(fresh)
    if not switched_on(biz_id) or not settings["on"] or not settings[step]["on"]:
        return True, "New here, or this text, is off now; not sent."
    if not sms_alerts.alerts_enabled():
        return True, "Automated texts are paused; not sent."
    people = await asyncio.to_thread(
        _rows, f"/contacts?id=eq.{_q(contact_id)}&business_id=eq.{_q(biz_id)}&select=id,name,phone&limit=1")
    if people is None:
        return False, "The guest couldn't be read; not sent."
    if not people:
        return True, "The guest is no longer on the church's list; not sent."
    local = _now().astimezone(tz_of(fresh))
    if not (sms_alerts.QUIET_SEND_START_HOUR <= local.hour < sms_alerts.QUIET_SEND_END_HOUR):
        return True, "Quiet hours at the church; not sent."
    if step == "invite" and await asyncio.to_thread(
            _came_back, biz_id, contact_id, _parse(action.get("texted_at"))):
        return True, "They came back; the invite isn't needed."
    name = str(fresh.get("name") or "").strip()
    body = sms_service.compose_outbound_body(name, fill(settings[step]["text"], name=first_name(people[0].get("name"))))
    async with httpx.AsyncClient(timeout=15) as client:
        if await sms_service.is_opted_out(client, phone, biz_id):
            return True, "They said STOP; not sent."
        try:
            sid = await sms_routing._send_platform_sms(phone, body, business_id=biz_id, client=client)
            await sms_service._store_sms(client, biz_id, contact_id, phone, body, "outbound",
                                         telnyx_id=sid or "", sent_by="system")
        except Exception as e:  # noqa: BLE001
            return False, f"The text didn't go: {e}"[:240]
    return True, f"Sent the New here {step} text."


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


def card_html(church_name: str, code: str, *, name: str = "", note: str = "") -> str:
    shown = f'<div class="note" role="alert">{_e(CARD_ERRORS[note])}</div>' if note in CARD_ERRORS else ""
    heard = "".join(f"<option>{_e(h)}</option>" for h in HEARD)
    kids = "".join(f"<option>{_e(k)}</option>" for k in KIDS)
    body = f"""<h1>We're so glad you came.</h1>
<p>Tell us a little about you. It takes 30 seconds.</p>{shown}
<form method="post" action="{CARD_PATH}/{_e(code)}">
<label>Your name<input type="text" name="name" autocomplete="name" maxlength="120" value="{_e(name)}" required></label>
<label>Email (if you'd like)<input type="email" name="email" autocomplete="email" maxlength="200"></label>
<fieldset><legend>Is this your first time?</legend><div class="two">
<label class="opt"><input type="radio" name="first" value="yes" checked>First time</label>
<label class="opt"><input type="radio" name="first" value="no">I've been before</label></div></fieldset>
<div class="two"><label>How did you hear?<select name="heard">{heard}</select></label>
<label>Kids with you?<select name="kids">{kids}</select></label></div>
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


def nothing_html(church_name: str, number: str) -> str:
    how = (f"<p>New here? Text the word on the screen to {_e(pretty_phone(number))} and we'll send you a "
           "card to fill in.</p>") if number else "<p>This link isn't working any more.</p>"
    return _page(church_name or "Welcome", "Welcome", f"<h1>Welcome!</h1>{how}")


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
        return nothing_html(church_name, number), 200
    guest = await asyncio.to_thread(_by_code, str(business_id), code)
    if guest is None:
        return _page(church_name, "One moment", "<h1>One moment</h1><p>This page couldn't load just now. "
                                                "Try again in a minute.</p>"), 503
    if not guest:
        number = await asyncio.to_thread(own_number, str(business_id))
        return nothing_html(church_name, number), 404
    q = parse_qs(query or "")
    if (q.get("done") or [""])[0] == "1":
        return thanks_html(church_name, first_name(guest.get("name"))), 200
    import text_room
    full = "" if text_room.nameless(guest.get("name")) else str(guest.get("name") or "")
    return card_html(church_name, code, name=full, note=(q.get("note") or [""])[0]), 200


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
        visit = str(mine.get("texted_at") or "")[:10]
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
    data = {k: str(form.get(k) or "") for k in ("name", "email", "first", "heard", "kids", "prayer")}
    if not await asyncio.to_thread(save_card, biz, guest, data):
        return back(note="error")
    return back(done="1")


# ─── the room (Text, New here) ────────────────────────────────────────

def _may_read(business_id: str, user: AuthedUser) -> None:
    import business_access
    business_access.assert_access(business_id, user, "viewer")


def _may_edit(business_id: str, user: AuthedUser) -> bool:
    """Who changes it: who sends announcements (the owner, an admin, or the
    office login that does the weekly text)."""
    import sms_routing
    try:
        sms_routing._may_announce(business_id, user)
        return True
    except HTTPException:
        return False


def _uuid(v: Any) -> str:
    from uuid import UUID
    try:
        return str(UUID(str(v)))
    except (TypeError, ValueError):
        raise HTTPException(404, "Church not found")


def guests_of(business: Dict[str, Any], *, days: int = LIST_DAYS) -> Optional[List[Dict[str, Any]]]:
    """This week's guests, newest first, with where each one stands. None
    when it couldn't be read."""
    biz = str(business["id"])
    since = _iso(_now() - timedelta(days=days))
    people = _rows(f"/contacts?business_id=eq.{_q(biz)}&metadata->new_here->>texted_at=gte.{_q(since)}"
                   "&select=id,name,phone,metadata&order=updated_at.desc&limit=100")
    if people is None:
        return None
    if not people:
        return []
    ids = ",".join(_q(p["id"]) for p in people)
    follows = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&contact_id=in.({ids})"
                    f"&card_key=eq.{_q(CARD_KEY)}&select=contact_id,status,step,leader_contact_id,created_at"
                    "&order=created_at.desc") or []
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
        f = by_contact.get(str(p["id"]))
        reached = bool(f and (f.get("status") == "done" or int(f.get("step") or 0) >= 1))
        out.append({
            "contact_id": str(p["id"]),
            "name": "" if text_room.nameless(p.get("name")) else str(p.get("name") or ""),
            "phone_last4": re.sub(r"\D", "", str(p.get("phone") or ""))[-4:],
            "texted_at": mine.get("texted_at"),
            "card_at": mine.get("card_at"),
            "card": card,
            "follow_up": None if not f else {
                "leader": leaders.get(str(f.get("leader_contact_id") or ""), ""),
                "status": f.get("status"), "reached": reached},
        })
    out.sort(key=lambda g: str(g.get("texted_at") or ""), reverse=True)
    return out


def counts_of(business: Dict[str, Any], guests: List[Dict[str, Any]]) -> Dict[str, int]:
    tz = tz_of(business)
    today = _now().astimezone(tz).date()
    sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    on_sunday = [g for g in guests if (_parse(g.get("texted_at")) or _now()).astimezone(tz).date() == sunday]
    month_start = datetime.combine(today.replace(day=1), time(0, 0), tzinfo=tz)
    month = _rows(f"/contacts?business_id=eq.{_q(business['id'])}"
                  f"&metadata->new_here->>texted_at=gte.{_q(_iso(month_start))}&select=id&limit=1000")
    return {"sunday": len(on_sunday),
            "card": sum(1 for g in on_sunday if g.get("card_at")),
            "reached": sum(1 for g in on_sunday if (g.get("follow_up") or {}).get("reached")),
            "month": len(month) if month is not None else len(guests)}


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
        "guests": guests,
        "counts": counts_of(business, guests or []),
        "texts_per_guest": 1 + sum(1 for s in STEPS if settings[s]["on"]),
    }


@router.get("/new-here/{business_id}")
def get_new_here(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _may_read(biz, user)
    business = _business(biz)
    if not business:
        raise HTTPException(503, "The church couldn't be read just now. Try again in a minute.")
    if not is_church(business):
        raise HTTPException(404, "New here is for churches.")
    return overview(business, can_edit=_may_edit(biz, user))


class StepIn(BaseModel):
    on: bool = True
    text: str = Field("", max_length=MAX_TEXT)
    hours: Optional[int] = None


class NewHereIn(BaseModel):
    on: bool
    word: str = Field("NEW", max_length=12)
    welcome: str = Field("", max_length=MAX_TEXT)
    thanks: StepIn
    monday: StepIn
    invite: StepIn


def clean(body: NewHereIn) -> Dict[str, Any]:
    """What gets saved, or a 400 that says what to change."""
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
    return out


@router.put("/new-here/{business_id}")
def put_new_here(business_id: str, body: NewHereIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _may_read(biz, user)
    if not _may_edit(biz, user):
        raise HTTPException(403, "Only someone who sends the church's announcements can change New here.")
    business = _business(biz)
    if not business:
        raise HTTPException(503, "The church couldn't be read just now. Try again in a minute.")
    if not is_church(business):
        raise HTTPException(404, "New here is for churches.")
    settings = dict(business.get("settings") or {})
    settings["new_here"] = clean(body)
    if sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(biz)}", {"settings": settings}) is None:
        raise HTTPException(503, "That didn't save just now. Try again in a minute.")
    return overview({**business, "settings": settings}, can_edit=True)


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
