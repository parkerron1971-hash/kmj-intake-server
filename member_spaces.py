"""
member_spaces.py — Church, Youth and Kids: three spaces in the member app.

Kevin, 2026-10-15: teens and kids "should have their own access point",
and the group leaders, who are adults, "the ability to access each side".
He approved the concept (https://claude.ai/artifact/74AnMSE4vsHyEFdpxLaKDi)
and its five calls the same day:

  1. Teens 13 to 17 (by birthdate) sign in themselves and land in Youth.
     Under 13 there is no sign-in of their own (US child-privacy law): kids
     come in through a parent's Kids space. contacts_for_ident drops anyone
     under 13, so a child's record never gets a code.
  2. The church office approves leaders per space, with the date of their
     background check (space_leaders; admin seats and the owner, through
     /member-portal/{biz}/leaders). Leaders must be adults.
  3. Kids leaders see first names, allergies and the pickup check; medical
     and custody notes stay with the office (kids_checkin keeps that rule).
  4. Kids mode is left by holding a button for three seconds.
  5. Youth's colour is volt green unless the church picks its own
     (member_portal.youth_color).

Which space a page is in: a teen is always in Youth. Anyone else is in
Church unless they switched (GET /my/space?to=…, a sol_space cookie) to a
space they belong to: Youth as an approved leader; Kids as a parent (a
household adult with children) or an approved Kids leader. The space sets
the look, the tab bar and what Home (/my) is.

Leaders talk with teens in group chats only — the messaging rules
(member_messaging_rules) are unchanged. A leader's post to Youth is checked
by msg_screen before it shows, like every message.
"""
from __future__ import annotations

import contextvars
import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("member_spaces")
router = APIRouter(tags=["member-portal"])

YOUTH_MIN, ADULT_AGE = 13, 18
SPACES = ("church", "youth", "kids")
COOKIE = "sol_space"
POST_MAX = 600
YOUTH_DEFAULT_COLOUR = "#d4ff3a"
# The Kids space (member_spaces_kids): a parent's family, the Sunday
# pass, Kids mode, and a Kids leader's room. On since its pages shipped.
KIDS_READY = True
# Events and groups that read as Youth's.
YOUTH_RE = re.compile(r"\b(youth|teens?|students?|next ?gen|middle school|high school)\b", re.I)

# The page being drawn: its space ('church' | 'youth' | 'kids') and who
# the member is in it. member_portal sets it per request; _shell reads it.
CURRENT: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar("member_space", default={})


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def age(person: Optional[Dict[str, Any]], today: Optional[date] = None) -> Optional[int]:
    import member_messaging_rules as rules
    return rules.age((person or {}).get("birthdate"), today)


def is_youth(person: Optional[Dict[str, Any]], today: Optional[date] = None) -> bool:
    a = age(person, today)
    return a is not None and YOUTH_MIN <= a < ADULT_AGE


def is_child(person: Optional[Dict[str, Any]], today: Optional[date] = None) -> bool:
    a = age(person, today)
    return a is not None and a < YOUTH_MIN


def is_adult(person: Optional[Dict[str, Any]], today: Optional[date] = None) -> bool:
    a = age(person, today)
    return a is not None and a >= ADULT_AGE


def youth_colour(biz: Dict[str, Any]) -> str:
    cfg = ((biz or {}).get("settings") or {}).get("member_portal") or {}
    c = str((cfg if isinstance(cfg, dict) else {}).get("youth_color") or "")
    return c if re.fullmatch(r"#[0-9a-fA-F]{6}", c) else YOUTH_DEFAULT_COLOUR


# ─── who belongs where ───────────────────────────────────────────────


def leader_rows(business_id: str, contact_id: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """{space: row} for the spaces this person is an approved leader of;
    None when the read failed."""
    rows = sb_clients.sb_get_as_service(
        f"/space_leaders?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}"
        f"&select=space,rooms,background_check_on,approved_at")
    if not isinstance(rows, list):
        return None
    return {str(r["space"]): r for r in rows}


def has_children(business_id: str, contact_id: str) -> Optional[bool]:
    """Whether this person is a household adult with a child the church
    has on record (kids check-in's families)."""
    links = sb_clients.sb_get_as_service(
        f"/household_adults?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}&select=household_id")
    if not isinstance(links, list):
        return None
    if not links:
        return False
    ids = ",".join(_q(l["household_id"]) for l in links)
    kids = sb_clients.sb_get_as_service(
        f"/children?business_id=eq.{_q(business_id)}&household_id=in.({ids})&active=eq.true&select=id&limit=1")
    if not isinstance(kids, list):
        return None
    return bool(kids)


def resolve(business_id: str, me: Dict[str, Any], wanted: str = "") -> Dict[str, Any]:
    """The space this member is in, and the ones they may switch to.
    {space, youth, leader: {space: row}, kids_parent, options: [...]}.
    A read that fails leaves them in Church (never somewhere they may not be)."""
    if is_youth(me):
        return _placed(me, wanted, {}, False)
    # A leader must be an adult, whatever the table says (the office's
    # approval checked the birthdate; this holds if it later changes).
    leaders = (leader_rows(business_id, str(me["id"])) or {}) if is_adult(me) else {}
    parent = bool(has_children(business_id, str(me["id"]))) if KIDS_READY else False
    return _placed(me, wanted, leaders, parent)


async def resolve_async(business_id: str, me: Dict[str, Any], wanted: str = "") -> Dict[str, Any]:
    """resolve, with its two reads (leader of a space? a parent?) made at
    once rather than one after the other: every member page waits on this."""
    import asyncio
    if is_youth(me):
        return _placed(me, wanted, {}, False)

    async def nothing():
        return None
    leaders, parent = await asyncio.gather(
        asyncio.to_thread(leader_rows, business_id, str(me["id"])) if is_adult(me) else nothing(),
        asyncio.to_thread(has_children, business_id, str(me["id"])) if KIDS_READY else nothing())
    return _placed(me, wanted, leaders or {}, bool(parent))


def _placed(me: Dict[str, Any], wanted: str, leaders: Dict[str, Dict[str, Any]], parent: bool) -> Dict[str, Any]:
    if is_youth(me):
        return {"space": "youth", "youth": True, "leader": {}, "kids_parent": False, "options": []}
    options = ["church"]
    if "youth" in leaders:
        options.append("youth")
    if KIDS_READY and (parent or "kids" in leaders):
        options.append("kids")
    space = wanted if wanted in options else "church"
    return {"space": space, "youth": False, "leader": leaders, "kids_parent": parent, "options": options}


def switcher(ctx: Dict[str, Any], church_name: str) -> str:
    """The one place a member changes sides: a menu, top left on Home.
    Nothing for someone with only one space (a teen, most members)."""
    import member_app_ui as ui
    from html import escape
    opts = ctx.get("options") or []
    if len(opts) < 2:
        return ""
    cur = ctx.get("space") or "church"
    leader = ctx.get("leader") or {}
    meta = {
        "church": ("Church", escape(church_name or "Your church"), "LC"),
        "youth": ("Youth", "Leading Youth", "Y"),
        "kids": ("Kids", "Your kids" if ctx.get("kids_parent") else "Your rooms", "★"),
    }
    rows = []
    for key in opts:
        label, sub, dot = meta[key]
        lead = '<span class="mb-sp-lead">Leader</span>' if key in leader else ""
        here = ' aria-current="true"' if key == cur else ""
        rows.append(f'<a class="mb-sp mb-sp-{key}" href="/my/space?to={key}"{here}><i>{dot}</i>'
                    f'<span><b>{label}</b><small>{sub}</small></span>{lead}</a>')
    bg = leader.get("youth") or leader.get("kids")
    note = (f'<p class="mb-sp-note">Approved to lead by the church office. Background check on file, '
            f'{_month(bg.get("background_check_on"))}.</p>' if bg else "")
    label, _sub, dot = meta[cur]
    return (f'<details class="mb-spaces"><summary class="mb-switch mb-sp-{cur}"><i>{dot}</i>{label}'
            f'{ui.icon("down", 16)}</summary><div class="mb-spaces-menu" role="menu"><p class="mb-sp-h">Switch to</p>'
            f'{"".join(rows)}{note}</div></details>')


def _month(d: Any) -> str:
    try:
        return date.fromisoformat(str(d)[:10]).strftime("%B %Y")
    except ValueError:
        return "on record"


# ─── Youth ───────────────────────────────────────────────────────────


def youth_events(occasions: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return [o for o in (occasions or []) if YOUTH_RE.search(str(o.get("title") or ""))]


def youth_groups(groups: Optional[Dict[str, List[Dict[str, Any]]]], key: str) -> List[Dict[str, Any]]:
    return [g for g in (groups or {}).get(key, []) if g.get("youth") or YOUTH_RE.search(str(g.get("name") or ""))]


def posts(business_id: str, space: str, limit: int = 3, room: Optional[str] = None,
          kind: str = "post") -> Optional[List[Dict[str, Any]]]:
    room_q = f"&room=in.({_q(room)},%22%22)" if room is not None else ""
    rows = sb_clients.sb_get_as_service(
        f"/space_posts?business_id=eq.{_q(business_id)}&space=eq.{_q(space)}&kind=eq.{_q(kind)}{room_q}"
        f"&select=id,title,body,scripture,verse,questions,video_url,room,posted_by,created_at"
        f"&order=created_at.desc&limit={int(limit)}")
    if not isinstance(rows, list):
        return None
    ids = sorted({str(r["posted_by"]) for r in rows if r.get("posted_by")})
    names: Dict[str, str] = {}
    if ids:
        people = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(business_id)}&id=in.({','.join(_q(i) for i in ids)})&select=id,name")
        if isinstance(people, list):
            names = {str(p["id"]): str(p.get("name") or "") for p in people}
    for r in rows:
        r["author"] = (names.get(str(r.get("posted_by") or ""), "") or "A leader").split(" ")[0]
    return rows


def _ago(iso: Any) -> str:
    try:
        then = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    mins = int((datetime.now(timezone.utc) - then).total_seconds() // 60)
    if mins < 60:
        return "just now" if mins < 2 else f"{mins} min ago"
    if mins < 60 * 24:
        return f"{mins // 60} h ago"
    days = mins // (60 * 24)
    return "yesterday" if days == 1 else f"{days} days ago"


def _post_card(p: Dict[str, Any], mine: bool = False) -> str:
    from member_portal import _e
    remove = (f'<form method="post" action="/my/youth/post/remove" class="y-post-x"><input type="hidden" name="id" value="{_e(p["id"])}">'
              f'<button class="mp-link" type="submit">Remove</button></form>' if mine else "")
    return (f'<article class="y-post"><p class="y-post-who">{_e(p.get("author") or "A leader")}'
            f'<span class="mb-sp-lead">Leader</span><span class="y-post-t">{_e(_ago(p.get("created_at")))}</span></p>'
            f'<p class="y-post-b">{_e(p.get("body") or "")}</p>{remove}</article>')


def render_youth_home(biz: Dict[str, Any], site, *, me: Dict[str, Any], occasions, groups,
                      youth_posts: Optional[List[Dict[str, Any]]], reading: str = "", bible: str = "kjv",
                      leader: Optional[Dict[str, Any]] = None, flash: str = "") -> str:
    """Youth's Home — for a teen ("What's up, Tia"), or for an approved
    leader (their tools: post to Youth, meetings, chats, who's coming)."""
    import member_app_ui as ui
    import member_app_photos as photos
    import member_portal_bible as mpb
    import member_portal_church as mpc
    from member_portal import _e, _shell, first_name
    church = (biz.get("name") or "").strip() or "the church"
    pool = photos.photos(biz, site)
    used: set = set()
    events = youth_events(occasions) or list(occasions or [])
    lead = events[0] if events else None
    pic, look = photos.choose(biz, "youth", pool, fallback=photos.named(biz, site, ("youth", "teen", "student")),
                              used=used)
    art = ui.picture(pic, look, "youth", eager=True, night=True)
    hero = ""
    if lead:
        d = mpc._day(lead.get("date") or "")
        when = (f'{d.strftime("%A")} · {d.strftime("%b")} {d.day}' if d else lead.get("date_label") or "")
        count = int(lead.get("attending") or 0)
        mine = (lead.get("mine") or {}).get("status") == "yes"
        if leader:
            act = f'<span class="y-count">{count} coming</span>' if count else ""
        elif mine:
            act = (f'<span class="y-in">{ui.icon("check", 16)}You\'re in</span>'
                   f'{f"<span class=y-count>{count} going</span>" if count >= 2 else ""}')
        else:
            act = (f'<form method="post" action="/my/rsvp"><input type="hidden" name="entry_id" value="{_e(lead.get("entry_id"))}">'
                   f'<input type="hidden" name="back" value="/my"><input type="hidden" name="action" value="coming">'
                   f'<button class="y-btn" type="submit">I\'m in</button></form>'
                   f'{f"<span class=y-count>{count} going</span>" if count >= 2 else ""}')
        where = f'<p>{_e(lead.get("location"))}</p>' if lead.get("location") else ""
        hero = (f'<section class="y-hero" aria-labelledby="y-hero-h">{art}<div class="y-hero-in">'
                f'<span class="y-when">{_e(when)}</span><h2 id="y-hero-h">{_e(lead.get("title"))}</h2>'
                f'{where}<div class="y-go">{act}</div></div></section>')
    colours = ("var(--hot)", "var(--acc-fill)", "#7c5cff")
    rest = [o for o in events[1:5]]
    rail = "".join(
        f'<a class="y-card" href="/my/events" style="background:{colours[i % 3]};{"color:#0b0b0b" if i % 3 == 1 else ""}">'
        f'<small>{_e((mpc._day(o.get("date") or "") or date.today()).strftime("%a · %b %d"))}</small><b>{_e(o.get("title"))}</b></a>'
        for i, o in enumerate(rest))
    rail = f'{ui.section("This week")}<div class="mb-rail">{rail}</div>' if rail else ""
    def crew_card(g: Dict[str, Any]) -> str:
        lab = "You lead" if g.get("role") == "leader" else "Your crew"
        facts = " · ".join(x for x in (g.get("meets"), g.get("location")) if x)
        led = (f'<p class="y-led">{_e(", ".join(g.get("leaders") or []))} lead</p>'
               if g.get("leaders") and g.get("role") != "leader" else "")
        return (f'<a class="y-crew" href="/my/groups"><span class="y-lab">{lab}</span>'
                f'<h3>{_e(g.get("name"))}</h3><p>{_e(facts)}</p>{led}</a>')
    crews = "".join(crew_card(g) for g in youth_groups(groups, "mine")[:3])
    open_ = youth_groups(groups, "open")
    if not crews and open_:
        crews = (f'<a class="y-crew" href="/my/groups"><span class="y-lab">Find your crew</span>'
                 f'<h3>{_e(open_[0].get("name"))}</h3><p>{_e(open_[0].get("meets") or "Join a youth group")}</p></a>')
    notes = "".join(_post_card(p, mine=bool(leader) and str(p.get("posted_by")) == str(me.get("id")))
                    for p in (youth_posts or []))
    notes = f'{ui.section("From your leaders")}{notes}' if notes else ""
    daily = reading or mpb.verse_card(bible)
    hello = first_name(me.get("name") or "") or "there"
    if leader:
        led = [g.get("name") for g in youth_groups(groups, "mine") if g.get("role") == "leader"]
        head = (f'<h1 class="y-hello">Leading<br><span>{_e(led[0] if led else "Youth")}</span></h1>')
        tools = (f'<form class="y-compose" method="post" action="/my/youth/post">'
                 f'<label for="y-say">Post to Youth</label>'
                 f'<textarea class="mp-input" id="y-say" name="body" maxlength="{POST_MAX}" rows="3" '
                 f'placeholder="Rides leave at 6:30. Bring a friend!" required></textarea>'
                 f'<button class="y-btn" type="submit">{ui.icon("send", 16)}Post</button>'
                 f'<p class="y-fine">Everyone in Youth sees it on their Home. It\'s checked before it shows, like every message.</p></form>'
                 f'<div class="y-tools"><a href="/my/groups">{ui.icon("video", 22)}<b>Start a meeting</b><span>Opens when a 2nd adult joins</span></a>'
                 f'<a href="/my/messages">{ui.icon("chat", 22)}<b>Group chats</b><span>The ones you lead</span></a>'
                 f'<a href="/my/events">{ui.icon("calendar", 22)}<b>Who\'s coming</b><span>Youth events</span></a>'
                 f'<a href="/my/groups">{ui.icon("users", 22)}<b>Your groups</b><span>Meetings and members</span></a></div>')
        safe = (f'<p class="y-safe">{ui.icon("shield", 17)}<span>Leaders talk with teens in group chats only, never one to one. '
                f'Background check on file, {_e(_month(leader.get("background_check_on")))}.</span></p>')
        body = f'{head}{flash}{hero}{tools}{notes}{rail}{crews}{safe}'
    else:
        head = f'<h1 class="y-hello">What\'s up,<br><span>{_e(hello)}</span></h1>'
        talk = (f'<a class="mb-row y-talk" href="/my/prayer?for=youth"><span class="mb-row-ic">{ui.icon("pray", 21)}</span>'
                f'<span class="mb-row-t"><strong>Talk to a youth leader</strong><span>Private. Goes to the pastors at {_e(church)}.</span></span>'
                f'{ui.icon("chevron", 18)}</a>')
        body = (f'{head}{flash}{hero}{notes}{rail}'
                f'{ui.section("Your crew") if crews else ""}{crews}'
                f'{ui.section("Today")}{daily}{talk}')
    return _shell(biz, site, "Youth", body, tab="home", who=me)


def safety_banner() -> str:
    import member_app_ui as ui
    return (f'<p class="y-safe">{ui.icon("shield", 17)}<span>Your parents can read your chats. '
            f'Group chats always have two adult leaders in them.</span></p>')


# ─── a leader's post ─────────────────────────────────────────────────


@router.post("/my/youth/post", include_in_schema=False)
async def youth_post(request: Request):
    import asyncio
    import member_portal_church as mpc
    import msg_screen
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return mpc._back("/my", err="preview" if unavailable == "preview" else "error")
    if not me:
        return mpc._back("/my")
    biz_id = church["business"]["id"]
    leaders = await asyncio.to_thread(leader_rows, biz_id, str(me["id"]))
    if not leaders or "youth" not in leaders or not is_adult(me):
        return mpc._back("/my", err="not_leader")
    if not mpc._allowed(church, me):
        return mpc._back("/my", err="slow")
    form = await request.form()
    text = re.sub(r"\s+\n", "\n", str(form.get("body") or "")).strip()[:POST_MAX]
    if not text:
        return mpc._back("/my", err="empty_post")
    try:
        verdict = await msg_screen.screen(biz_id, text)
    except msg_screen.ScreenUnavailable:
        return mpc._back("/my", err="post_busy")
    if verdict != "ok":
        return mpc._back("/my", err="post_no")
    rows = await asyncio.to_thread(sb_clients.sb_post_as_service, "/space_posts", {
        "business_id": str(biz_id), "space": "youth", "kind": "post", "body": text, "posted_by": str(me["id"])})
    if not (isinstance(rows, list) and rows):
        return mpc._back("/my", err="error")
    import member_push
    member_push.tell_youth_post(church["business"], str(rows[0].get("id") or ""), me)
    return mpc._back("/my", done="posted")


@router.post("/my/youth/post/remove", include_in_schema=False)
async def youth_post_remove(request: Request):
    import asyncio
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return mpc._back("/my", err="preview" if unavailable == "preview" else "error")
    if not me:
        return mpc._back("/my")
    form = await request.form()
    pid = str(form.get("id") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", pid):
        return mpc._back("/my")
    biz_id = church["business"]["id"]
    # Only the author removes their own post.
    gone = await asyncio.to_thread(
        sb_clients.sb_delete_as_service,
        f"/space_posts?id=eq.{_q(pid)}&business_id=eq.{_q(biz_id)}&posted_by=eq.{_q(me['id'])}")
    return mpc._back("/my", **({"done": "post_removed"} if gone else {"err": "error"}))


# ─── the office: who leads ───────────────────────────────────────────


def _office():
    import business_access
    return business_access.business_access("admin")


def _rooms(raw: Any) -> List[str]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise HTTPException(400, "rooms must be a list of room names")
    out: List[str] = []
    for r in raw[:12]:
        name = re.sub(r"\s+", " ", str(r or "")).strip()[:60]
        if name and name.lower() not in [x.lower() for x in out]:
            out.append(name)
    return out


@router.get("/member-portal/{business_id}/leaders")
def list_leaders(business_id: str, biz: dict = Depends(_office())):
    """Who leads Youth and Kids, and the rooms the church's children are in
    (for choosing a Kids leader's rooms)."""
    rows = sb_clients.sb_get_as_service(
        f"/space_leaders?business_id=eq.{_q(business_id)}&select=contact_id,space,rooms,background_check_on,approved_at"
        f"&order=approved_at.desc")
    if not isinstance(rows, list):
        raise HTTPException(503, "Leaders couldn't load just now. Please try again.")
    ids = sorted({str(r["contact_id"]) for r in rows})
    names: Dict[str, str] = {}
    if ids:
        people = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(business_id)}&id=in.({','.join(_q(i) for i in ids)})&select=id,name")
        names = {str(p["id"]): str(p.get("name") or "") for p in (people or [])}
    kids = sb_clients.sb_get_as_service(f"/children?business_id=eq.{_q(business_id)}&active=eq.true&select=room&limit=2000")
    rooms = sorted({str(k.get("room") or "").strip() for k in (kids or []) if str(k.get("room") or "").strip()})
    return {"leaders": [{**r, "name": names.get(str(r["contact_id"]), "")} for r in rows], "rooms": rooms}


@router.post("/member-portal/{business_id}/leaders")
def approve_leader(business_id: str, body: Dict[str, Any], biz: dict = Depends(_office()),
                   user: AuthedUser = Depends(require_user)):
    """Approve (or update) a leader for one space. Body: {contact_id, space:
    'youth'|'kids', background_check_on: 'YYYY-MM-DD', rooms?: [str]}."""
    body = body or {}
    cid = str(body.get("contact_id") or "")
    space = str(body.get("space") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", cid):
        raise HTTPException(400, "Choose the person to approve.")
    if space not in ("youth", "kids"):
        raise HTTPException(400, "space must be youth or kids")
    try:
        checked = date.fromisoformat(str(body.get("background_check_on") or "")[:10])
    except ValueError:
        raise HTTPException(400, "Add the date of their background check.")
    if checked > date.today() or checked.year < 2000:
        raise HTTPException(400, "The background check date can't be in the future.")
    rooms = _rooms(body.get("rooms")) if space == "kids" else []
    people = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{_q(business_id)}&id=eq.{_q(cid)}&select=id,name,birthdate&limit=1")
    if not isinstance(people, list):
        raise HTTPException(503, "That didn't save. Please try again.")
    if not people:
        raise HTTPException(404, "That person isn't in this church's records.")
    if not is_adult(people[0]):
        raise HTTPException(400, "Leaders must be 18 or older. Add their birthdate to their record first.")
    saved = sb_clients.sb_post_as_service(
        "/space_leaders?on_conflict=business_id,contact_id,space",
        {"business_id": business_id, "contact_id": cid, "space": space, "rooms": rooms,
         "background_check_on": checked.isoformat(), "approved_by": str(user.id),
         "approved_at": datetime.now(timezone.utc).isoformat()},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Please try again.")
    return {"ok": True, "leader": {**saved[0], "name": people[0].get("name") or ""}}


@router.delete("/member-portal/{business_id}/leaders/{contact_id}/{space}")
def remove_leader(business_id: str, contact_id: str, space: str, biz: dict = Depends(_office())):
    if space not in ("youth", "kids") or not re.fullmatch(r"[0-9a-fA-F-]{36}", contact_id or ""):
        raise HTTPException(400, "Not a leader.")
    gone = sb_clients.sb_delete_as_service(
        f"/space_leaders?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}&space=eq.{_q(space)}")
    if not gone:
        raise HTTPException(503, "That didn't save. Please try again.")
    return JSONResponse({"ok": True})
