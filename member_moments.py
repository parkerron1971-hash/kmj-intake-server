"""
member_moments.py — a pastor or a leader posts their own moment (Look 5.1).

The pastor, on the mock "Next: a pastor or leader posts their own moment"
(2026-11-20): "i like it lets do it". A photo and one line at the start of
their church's Home, for a day, until Sunday, or for three days, seen by the
whole church or by one group they lead, the way a phone's stories are.

  GET  /my/moment/new           the composer (the new look only)
  GET  /my/moment/<id>/photo    its photo: a short signed link, for whoever may see it
  POST /my/moment               a moment
  POST /my/moment/seen          {id}: this member saw it (sent once, from the viewer)
  POST /my/moment/love          {id, on}: this member loves it, or takes it back
  POST /my/moment/remove        {id}: its poster, a pastor, or the church's owner takes it down

WHO POSTS. Whoever church_news.can_post says may post News: the church's
pastors and the people the office picked post to the whole church, or to a
group they lead; someone who only leads a group posts only to their own
groups. Nobody else sees the composer, and every POST asks again (fresh).

WHAT A MOMENT CARRIES. One photo (required: checked and kept as News photos
are, member_portal_write._photos), one line (required, up to LINE_MAX
characters), and at most one button picked from this week: Sunday's service
("I'm coming"), an event's sign-up or "I'm coming", or a gathering of the
group it is for ("I'll be there"). The button is drawn for each member from
Home's own This week records and posts to the same routes Home's cards do
(/my/rsvp, /my/groups/meet/rsvp, /my/here, Events): no new action route. A
member the button isn't for (a gathering of a group they aren't in, an event
already past) sees no button. No video in this build: media_kind is 'photo'
(the column is ready for 'video').

HOW LONG. A day (the default), until Sunday (the end of the church's coming
Sunday on the church's clock: today, on a Sunday), or three days. It ends on
its own when ends_at passes: an ended moment is never read for Home.

THE CHECK. The line goes through msg_screen like comments and members'
posts. 'ok' shows. 'harm' is held: only its poster sees it, with the held
wording, and the church's safety officers find it in church_news' held list
beside the held comments and members' posts (kind "moment"; Let it through
shows it for the time it has left, Keep it hidden takes it down).
'self_harm' is held the same way, the pastor is told through Prayer & care
(member_portal_messaging.care_alert) and the poster is shown 988. If the
check can't run, nothing posts. The photo is checked as a News photo, for a
church that includes teens; a moment for a group with a teen in it is
refused the way members' posting refuses photos there (member_posts:
"Photos can't be shared in a group with teens in it."), so a group with a
teen gets no moments.

WHAT MEMBERS SEE. Home's moments row (member_lumen_stories): one circle a
person, their moments as segments, newest last; a pastor's derived moment
(today's devotional, or their recent post) joins their own circle after
their moments. Leader circles come first, pastors first. A group's moment
only reaches that group's people. The viewer: the photo, "<Name> · 20m",
"A word from your pastor" (a pastor's for the whole church) or "<Group> ·
from <Name>", the line, the button, a private reply pill only where member
messaging lets this member write to the poster (member_pastor.may_message,
kept: member_portal_lumen.may_write), and Love. NEVER Share: a leader's
moment has no public page.

THE POSTER. Their own circle ("Your moment", with a + to add another)
opens their moments with a sheet: "Seen by N" (a count only, never a name),
"Replies come to your Messages" (no number: a reply is an ordinary message
and nothing ties it to the moment), "N loved it", and Take it down. The
header says how long it has left ("3h · 21h left"). A card under the
greeting ("Say something to your church today") shows to someone who may
post and has no moment showing.

TAKING IT DOWN. Its poster, a pastor, or the church's owner (from their
preview, or their own member record: settings.church_owner_contact_id).
The office's Mission Control removal is a later piece.

THE TABLES. church_moments and church_moment_marks
(supabase/APPLY-2026-11-21-church-moments.sql), server-only, read and
written with the service role. Until that file is applied every read answers
"not there" (Postgres 42P01 / PostgREST PGRST205), which is kept
MISSING_SECONDS so it isn't asked on every page: no circle to post from,
no card, no leader moments, every page exactly as before.

READS ON HOME. One read for the church's moments still showing (kept
LIVE_SECONDS per church, with their posters and groups), the church's
pastors and picked posters (kept PEOPLE_SECONDS per church), and, only when
someone else's moment is showing, this member's own marks for those ids;
the poster's counts only while their own moment shows. All inside Home's
one gather (member_portal).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time as clock
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import sb_clients

logger = logging.getLogger("member_moments")
router = APIRouter(tags=["member-portal"])

LINE_MAX = 120
LASTS = (("day", "A day"), ("sunday", "Until Sunday"), ("three", "3 days"))
LAST_KEYS = tuple(k for k, _ in LASTS)
BUTTON_KINDS = ("service", "event", "gathering")
WEEK_DAYS = 7
# The church's moments still showing, kept this long per church (Home's other gathers keep 30 s).
LIVE_SECONDS = 30.0
# Who the church's pastors and picked posters are, kept this long per church.
PEOPLE_SECONDS = 600.0
# "The tables aren't there yet", kept this long, so a church before the
# migration isn't asked on every page.
MISSING_SECONDS = 300.0
READ_MOST = 100
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Home's flash after a write (member_portal: the new look's Home).
FRESH_DONE = ("moment_up", "moment_held", "moment_care", "moment_down")

CARE = ("You're not alone. If you're thinking about hurting yourself, call or text 988 (the Suicide & Crisis "
        "Lifeline) any time. Your pastor has been told so they can reach out.")
HELD = "A safety officer looks at this one before it shows."
DONE = {
    "moment_up": "It's up. It's at the start of Home now.",
    "moment_held": "Thanks. " + HELD,
    "moment_care": CARE,
    "moment_down": "Taken down.",
}
ERRORS = {
    "moment_who": "Moments are for your pastors and the leaders they pick, and for group leaders in their own groups.",
    "moment_where": "Choose who sees it: the whole church, or one of the groups you lead.",
    "moment_empty": "Say one thing first.",
    "moment_long": f"That's a little long. Keep it to {LINE_MAX} letters.",
    "moment_photo": "Add a photo first.",
    "moment_teens": "Photos can't be shared in a group with teens in it.",
    "moment_button": "That button isn't on this week any more. Choose another, or none.",
    "moment_busy": "We couldn't check your words just now, so nothing was posted. Please try again.",
    "moment_soon": "Moments are being switched on at your church. Try again soon.",
    "moment_gone": "That moment isn't there any more, or it isn't yours to take down.",
    "photo_bad": "That file isn't a photo we can use. Choose a JPG, PNG or WebP photo under 12 MB.",
    "photo_no": "That photo can't be posted here. Nothing was posted. Choose another and try again.",
    "photo_busy": "We couldn't check the photo just now, so nothing was posted. Please try again.",
    "preview": "This is a preview, so nothing is saved.",
    "slow": "That was quick. Wait a moment and try again.",
    "error": "Something went wrong, so nothing was posted. Please try again.",
}


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _e(v: Any) -> str:
    from html import escape
    return escape(str(v if v is not None else ""), quote=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _at(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _ids(xs) -> str:
    return ",".join(_q(x) for x in sorted({str(x) for x in xs if x}))


# ─── are the tables there ────────────────────────────────────────────

_STATE = {"missing_until": 0.0}


def _no_table(err: Optional[Dict[str, Any]]) -> bool:
    """PostgREST saying the table isn't there: Postgres's 42P01, or its own
    "not in the schema cache" (PGRST205, a 404). church_schedule's rule."""
    if not err:
        return False
    code = str(err.get("code") or "")
    return code in ("42P01", "PGRST205") or "42P01" in str(err.get("message") or "") \
        or (err.get("status") == 404 and code.startswith("PGRST"))


def missing() -> bool:
    """A read said the tables aren't there, less than MISSING_SECONDS ago."""
    return clock.monotonic() < _STATE["missing_until"]


def _saw(rows: Any) -> None:
    """After a request to one of the two tables: a "no such table" answer is
    kept MISSING_SECONDS; any other failure is a blip and keeps nothing."""
    if rows is not None:
        return
    try:
        err = sb_clients.last_error()
    except Exception:  # noqa: BLE001 — a fake client says nothing
        err = None
    if isinstance(err, dict) and _no_table(err):
        _STATE["missing_until"] = clock.monotonic() + MISSING_SECONDS


def _read(path: str) -> Optional[Any]:
    """A read of church_moments or church_moment_marks; None while the
    tables aren't there (asks nothing) and on a failed read."""
    if missing():
        return None
    rows = sb_clients.sb_get_as_service(path)
    _saw(rows)
    return rows


def ready() -> bool:
    """Whether the tables are there: no while a read said they aren't
    (kept), else one row asked. The composer and the routes ask it; Home
    learns it from its own read."""
    return isinstance(_read("/church_moments?select=id&limit=1"), list)


# ─── the church's moments (kept per church) ──────────────────────────

_LIVE = None
_PEOPLE = None
MOMENT_SELECT = "id,posted_by,group_id,line,media_path,media_kind,button_kind,button_ref,starts_at,ends_at,status,held_reason,created_at"


def _kept(name: str, seconds: float):
    import member_cache
    return member_cache.Kept(name, seconds)


def forget(business_id: Any) -> None:
    """This church's kept moments, dropped after a write on this replica
    (the others see it within LIVE_SECONDS)."""
    if _LIVE is not None:
        bid = str(business_id or "")
        _LIVE.forget(lambda _k, tag: tag == bid)


def live(business_id: str, *, fresh: bool = False) -> Optional[Dict[str, Any]]:
    """The church's moments that haven't ended (shown, and held: a held one
    reaches only its poster), oldest first, with what Home draws them with:
    {moments, people: {contact id: {id, name, birthdate, metadata}},
    groups: {group id: name}}. Kept LIVE_SECONDS per church; None while
    the tables aren't there or a read failed (Home then shows no leader
    moments, as before)."""
    global _LIVE
    if missing():
        return None
    if _LIVE is None:
        _LIVE = _kept("church_moments", LIVE_SECONDS)
    bid = str(business_id)
    if not fresh:
        hit, got = _LIVE.get(bid)
        if hit:
            return got
    rows = _read(f"/church_moments?business_id=eq.{_q(bid)}&status=in.(shown,held)"
                 f"&ends_at=gt.{_q(_now().isoformat())}&select={MOMENT_SELECT}&order=created_at.asc&limit={READ_MOST}")
    if not isinstance(rows, list):
        return None
    out: Dict[str, Any] = {"moments": rows, "people": {}, "groups": {}}
    if rows:
        who = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(bid)}&id=in.({_ids(r.get('posted_by') for r in rows)})"
            f"&select=id,name,birthdate,metadata")
        gids = [r.get("group_id") for r in rows if r.get("group_id")]
        groups = (sb_clients.sb_get_as_service(
            f"/groups?business_id=eq.{_q(bid)}&id=in.({_ids(gids)})&select=id,name") if gids else [])
        if who is None or groups is None:
            return None
        out["people"] = {str(p["id"]): p for p in who}
        out["groups"] = {str(g["id"]): g.get("name") or "Your group" for g in groups}
    _LIVE.put(bid, out, tag=bid)
    return out


def church_people(business_id: str) -> Optional[Dict[str, List[str]]]:
    """{pastors: [contact ids], picked: [contact ids]}: who holds an active
    senior or pastoral role (church_news.is_pastoral's rule, for everyone at
    once) and whom the office picked to post to the whole church. Kept
    PEOPLE_SECONDS per church; None on a failed read."""
    global _PEOPLE
    import church_roles as cr
    import messaging_router as mr
    if _PEOPLE is None:
        _PEOPLE = _kept("moment_people", PEOPLE_SECONDS)
    bid = str(business_id)
    hit, got = _PEOPLE.get(bid)
    if hit:
        return got
    roles = sb_clients.sb_get_as_service(
        f"/church_leader_roles?business_id=eq.{_q(bid)}&status=eq.active&select=contact_id,role&limit=2000")
    picked = sb_clients.sb_get_as_service(
        f"/church_news_posters?business_id=eq.{_q(bid)}&select=contact_id&limit=2000")
    if roles is None or picked is None:
        return None
    pastors: List[str] = []
    if roles:
        defs = cr.defs(bid)
        if defs is None:
            return None
        by = cr.by_key(defs)
        pastors = sorted({str(r["contact_id"]) for r in roles
                          if (by.get(r["role"]) or cr.LEGACY.get(r["role"]) or {}).get("job") in mr.PASTORAL_JOBS})
    out = {"pastors": pastors, "picked": sorted({str(r["contact_id"]) for r in picked})}
    _PEOPLE.put(bid, out, tag=bid)
    return out


def marks_for(business_id: str, me_id: str, ids: List[str]) -> Optional[Dict[str, Dict[str, bool]]]:
    """This member's own marks on these moments: {moment id: {seen, loved}}."""
    if not ids:
        return {}
    rows = _read(f"/church_moment_marks?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(me_id)}"
                 f"&moment_id=in.({_ids(ids)})&select=moment_id,seen_at,loved_at&limit={READ_MOST}")
    if not isinstance(rows, list):
        return None
    return {str(r["moment_id"]): {"seen": bool(r.get("seen_at")), "loved": bool(r.get("loved_at"))} for r in rows}


def counts_for(business_id: str, ids: List[str]) -> Optional[Dict[str, Dict[str, int]]]:
    """How many saw and loved each of these moments (the poster's own):
    {moment id: {seen, loved}}. Counts only: no person is read."""
    if not ids:
        return {}
    rows = _read(f"/church_moment_marks?business_id=eq.{_q(business_id)}&moment_id=in.({_ids(ids)})"
                 f"&select=moment_id,seen_at,loved_at&limit=20000")
    if not isinstance(rows, list):
        return None
    out = {str(i): {"seen": 0, "loved": 0} for i in ids}
    for r in rows:
        c = out.get(str(r.get("moment_id")))
        if c is None:
            continue
        c["seen"] += 1 if r.get("seen_at") else 0
        c["loved"] += 1 if r.get("loved_at") else 0
    return out


def showing(m: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """Not ended (a kept list can hold one that ended since it was read)."""
    end = _at(m.get("ends_at"))
    return bool(end and end > (now or _now()))


async def home_data(biz: Dict[str, Any], me: Dict[str, Any], *, preview: bool = False,
                    fresh: bool = False) -> Optional[Dict[str, Any]]:
    """What Home draws leaders' moments from (member_portal's one gather):
    {moments, people, groups, pastors, picked, marks, counts, write}, or
    None while the tables aren't there or a read failed (Home is then
    exactly as before). `moments` holds every moment of the church still
    showing that this member might see, and their own held ones; Home
    leaves out the groups they aren't in (it has their groups)."""
    import member_portal_lumen as mlp
    bid, mid = str(biz["id"]), str(me["id"])
    if missing():
        return None

    def both():
        # The church's moments first: before the tables are there, nothing else is asked.
        church_ = live(bid, fresh=fresh)
        return church_, (church_people(bid) if church_ is not None else None)
    try:
        church, people = await asyncio.to_thread(both)
        if church is None or people is None:
            return None
        now = _now()
        mine_or_shown = [m for m in church["moments"] if showing(m, now)
                         and (m.get("status") == "shown" or str(m.get("posted_by")) == mid)]
        others = [str(m["id"]) for m in mine_or_shown if str(m.get("posted_by")) != mid]
        own = [str(m["id"]) for m in mine_or_shown if str(m.get("posted_by")) == mid and m.get("status") == "shown"]
        posters = sorted({str(m["posted_by"]) for m in mine_or_shown if str(m.get("posted_by")) != mid})
        marks, counts, *writes = await asyncio.gather(
            asyncio.to_thread(marks_for, bid, mid, others) if others else _nothing({}),
            asyncio.to_thread(counts_for, bid, own) if own else _nothing({}),
            *[asyncio.to_thread(mlp.may_write, biz, me, p) for p in (posters if not preview else [])])
        return {**church, "moments": mine_or_shown, "pastors": set(people["pastors"]),
                "picked": set(people["picked"]), "marks": marks or {}, "counts": counts,
                "write": dict(zip(posters if not preview else [], (bool(w) for w in writes)))}
    except Exception:  # noqa: BLE001 — leaders' moments are left out; Home is as before
        logger.warning("home: leaders' moments skipped", exc_info=True)
        return None


async def _nothing(v: Any = None):
    return v


# ─── who may post (fresh, for the composer and the POST) ─────────────


def rights(business_id: str, me_id: str) -> Optional[Dict[str, Any]]:
    """church_news.can_post: {church: bool, pastoral: bool, groups: [{id,
    name}]}; None on a failed read."""
    import church_news as cn
    return cn.can_post(str(business_id), str(me_id))


def may_post(r: Optional[Dict[str, Any]]) -> bool:
    return bool(r and (r.get("church") or r.get("groups")))


def ends_for(lasts: str, biz: Dict[str, Any], now: Optional[datetime] = None) -> datetime:
    """When a moment stops showing: a day, three days, or the end of the
    church's coming Sunday on the church's clock (tonight, on a Sunday)."""
    from zoneinfo import ZoneInfo
    import church_checkin as cc
    now = now or _now()
    if lasts == "three":
        return now + timedelta(days=3)
    if lasts == "sunday":
        here = now.astimezone(ZoneInfo(cc.church_zone_name(biz)))
        sunday = here.date() + timedelta(days=(6 - here.weekday()) % 7)
        return datetime.combine(sunday, time(23, 59, 59), tzinfo=here.tzinfo).astimezone(timezone.utc)
    return now + timedelta(days=1)


def teens_in(business_id: str, group_id: str) -> Optional[bool]:
    """Whether the group has a teen in it, as members' posting sees ages
    (member_posts._as_posting: the office's birthdate, or a birthday the
    person gave that says they're a teen). None on a failed read."""
    import member_messaging_rules as mr_rules
    import member_portal_groups as mpg
    import member_posts
    people = mpg.roster(str(business_id), str(group_id))
    if people is None:
        return None
    return any(mr_rules.is_teen(member_posts._as_posting(p)) for p in people)


def week_choices(biz: Dict[str, Any], me: Dict[str, Any], led: List[Dict[str, Any]],
                 now: Optional[datetime] = None) -> List[Tuple[str, str, str]]:
    """The buttons a moment may carry, picked from this week:
    [(value, label, group id or '')]: Sunday's service ("service:<entry>"),
    the church's events ("event:<entry>"), and each led group's next
    gathering ("gathering:<group>@<day>", only for a moment for that group).
    Reads the member's upcoming list and the led groups' schedules."""
    import member_app_samples as samples
    import member_lumen_home as lh
    import member_portal_church as mpc
    import member_portal_lumen as mlp
    import group_gatherings as gg
    now = now or mlp.church_now(biz)
    day0 = now.date()
    occ = mpc.upcoming_for(str(biz["id"]), me) or []
    out: List[Tuple[str, str, str]] = []
    svc = lh.service_next(None, None, occ, now)
    sid = str((svc or {}).get("entry_id") or "")
    if svc and sid:
        name = "Sunday" if svc["day"].weekday() == 6 else f"{svc['day']:%A}"
        out.append((f"service:{sid}", f"{name} · I'm coming", ""))
    for o in occ:
        d = lh._day(o.get("date"))
        eid = str(o.get("entry_id") or "")
        if not d or not eid or eid == sid or samples.is_sample(o) or not 0 <= (d - day0).days < WEEK_DAYS:
            continue
        if any(v == f"event:{eid}" for v, _l, _g in out):
            continue
        say = "Sign up" if o.get("signup") else "I'm coming"
        out.append((f"event:{eid}", f"{o.get('title') or 'Event'} · {say}", ""))
    if led:
        rows = sb_clients.sb_get_as_service(
            f"/groups?business_id=eq.{_q(biz['id'])}&id=in.({_ids(g['id'] for g in led)})&select=id,name,{mpc._SCHEDULE}")
        for g in rows or []:
            sched = {k: g.get(k) for k in mpc._SCHEDULE.split(",")}
            if not gg.scheduled(sched):
                continue
            day, _skipped = gg.next_on(sched, now)
            if day and 0 <= (day - day0).days < WEEK_DAYS:
                out.append((f"gathering:{g['id']}@{day.isoformat()}", f"{g.get('name') or 'Your group'} · I'll be there",
                            str(g["id"])))
    return out


def check_button(raw: str, choices: List[Tuple[str, str, str]], group_id: str) -> Tuple[str, str, str]:
    """(kind, ref, '') for a button picked from this week's choices; ('',
    '', '') for none; ('', '', 'moment_button') for one that isn't on this
    week, or a gathering of another group than the one the moment is for."""
    raw = str(raw or "").strip()
    if not raw or raw == "none":
        return "", "", ""
    hit = next((c for c in choices if c[0] == raw), None)
    if not hit:
        return "", "", "moment_button"
    kind, _, ref = raw.partition(":")
    if kind not in BUTTON_KINDS or not ref:
        return "", "", "moment_button"
    if kind == "gathering" and hit[2] != str(group_id or ""):
        return "", "", "moment_button"
    return kind, ref, ""


# ─── posting ─────────────────────────────────────────────────────────


def clean(text: Any) -> str:
    return " ".join(str(text or "").split())


async def post(biz: Dict[str, Any], me: Dict[str, Any], *, to: str, line: str, photo: Optional[bytes],
               button: str, lasts: str) -> Tuple[bool, str]:
    """A leader's moment. (ok, code): moment_up, moment_held, moment_care,
    or one of ERRORS' keys. Nothing is saved unless the words are checked
    and the photo is checked and kept."""
    import member_portal_write as mpw
    import msg_screen
    bid, mid = str(biz["id"]), str(me["id"])
    if not await asyncio.to_thread(ready):
        return False, "moment_soon"
    r = await asyncio.to_thread(rights, bid, mid)
    if r is None:
        return False, "error"
    if not may_post(r):
        return False, "moment_who"
    if to == "church":
        if not r.get("church"):
            return False, "moment_where"
        gid = ""
    else:
        led = {str(g["id"]) for g in r.get("groups") or []}
        if not UUID.match(str(to or "")) or str(to) not in led:
            return False, "moment_where"
        gid = str(to)
    line = clean(line)
    if not line:
        return False, "moment_empty"
    if len(line) > LINE_MAX:
        return False, "moment_long"
    if not photo:
        return False, "moment_photo"
    if gid:
        teens = await asyncio.to_thread(teens_in, bid, gid)
        if teens is None:
            return False, "error"
        if teens:
            return False, "moment_teens"
    kind, ref = "", ""
    if str(button or "").strip() not in ("", "none"):
        choices = await asyncio.to_thread(week_choices, biz, me, r.get("groups") or [])
        kind, ref, why = check_button(button, choices, gid)
        if why:
            return False, why
    try:
        verdict = await msg_screen.screen(bid, line)
    except msg_screen.ScreenUnavailable:
        return False, "moment_busy"
    pics, code = await mpw._photos(bid, [photo])
    if pics is None:
        return False, code or "error"
    held = verdict in ("harm", "self_harm")
    now = _now()
    row = {"business_id": bid, "posted_by": mid, "group_id": gid or None, "line": line,
           "media_path": pics[0]["path"], "media_kind": "photo", "button_kind": kind or None, "button_ref": ref or None,
           "starts_at": now.isoformat(), "ends_at": ends_for(lasts if lasts in LAST_KEYS else "day", biz, now).isoformat(),
           "status": "held" if held else "shown", "held_reason": verdict if held else None}
    got = await asyncio.to_thread(sb_clients.sb_post_as_service, "/church_moments", row)
    _saw(got)
    if not got:
        import chat_photos
        await asyncio.to_thread(chat_photos.drop, pics[0]["path"])
        return False, "moment_soon" if missing() else "error"
    forget(bid)
    if verdict == "self_harm":
        import member_portal_messaging as mpm
        try:
            await asyncio.to_thread(mpm.care_alert, bid, me)
        except Exception:  # noqa: BLE001 — the moment is saved and held; the alert is best effort, and logged
            logger.warning("moment care alert failed", exc_info=True)
        return True, "moment_care"
    return True, ("moment_held" if held else "moment_up")


def _visible_to(business_id: str, me_id: str, moment_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """(the moment, '') when this member may see it now: theirs (shown or
    held), or shown and for the whole church or a group they're in;
    (None, 'gone') otherwise; (None, 'error') on a failed read. Asks the
    church's kept moments; only a group's moment reads their groups."""
    import church_news as cn
    if not UUID.match(str(moment_id or "")):
        return None, "gone"
    church = live(business_id)
    if church is None:
        return None, "error"
    m = next((x for x in church["moments"] if str(x.get("id")) == str(moment_id)), None)
    if not m or not showing(m):
        return None, "gone"
    if str(m.get("posted_by")) == str(me_id):
        return m, ""
    if m.get("status") != "shown":
        return None, "gone"
    if m.get("group_id"):
        mine = cn.my_groups(business_id, me_id)
        if mine is None:
            return None, "error"
        if str(m["group_id"]) not in set(mine):
            return None, "gone"
    return m, ""


def mark(business_id: str, me_id: str, moment_id: str, *, love: Optional[bool] = None) -> str:
    """This member saw a moment (love None: one row, written once, never
    over an earlier one) or loves it / takes it back (one upsert, seen
    with it). Their own row only, on a moment they may see, never their
    own moment. 'ok', 'gone' or 'error'."""
    m, why = _visible_to(business_id, me_id, moment_id)
    if not m:
        return why
    if str(m.get("posted_by")) == str(me_id):
        return "gone"
    now = _now().isoformat()
    # The seen row, written once: a later one never moves when they first saw it.
    row: Dict[str, Any] = {"moment_id": str(m["id"]), "business_id": str(business_id), "contact_id": str(me_id),
                           "seen_at": now}
    got = sb_clients.sb_post_as_service("/church_moment_marks?on_conflict=moment_id,contact_id", row,
                                        prefer="resolution=ignore-duplicates,return=minimal")
    if got is None and _failed():
        return "error"
    if love is None:
        return "ok"
    # Love, or taking it back: only loved_at changes on that row (seen_at stays as it was).
    got = sb_clients.sb_patch_as_service(
        f"/church_moment_marks?moment_id=eq.{_q(str(m['id']))}&contact_id=eq.{_q(str(me_id))}"
        f"&business_id=eq.{_q(str(business_id))}", {"loved_at": now if love else None})
    if got is None and _failed():
        return "error"
    return "ok"


def _failed() -> bool:
    """Whether the write just made was refused (sb_clients.last_error); a
    quiet answer (return=minimal) is not a failure."""
    try:
        err = sb_clients.last_error()
    except Exception:  # noqa: BLE001
        err = None
    if err is not None:
        _saw(None)
        return True
    return False


def may_take_down(biz: Dict[str, Any], me: Optional[Dict[str, Any]], *, owner: bool = False) -> Optional[bool]:
    """Whether this person may take down anyone's moment here: a pastor
    (fresh), or the church's owner (their preview, or their own member
    record). None on a failed read."""
    import church_news as cn
    if owner:
        return True
    if not me:
        return False
    settings = (biz or {}).get("settings") or {}
    if str(settings.get("church_owner_contact_id") or "") == str(me.get("id")):
        return True
    return cn.is_pastoral(str(biz["id"]), str(me["id"]))


def remove(biz: Dict[str, Any], me: Optional[Dict[str, Any]], moment_id: str, *, owner: bool = False) -> Tuple[bool, str]:
    """Take a moment down: its poster, a pastor, or the church's owner.
    (ok, code)."""
    import chat_photos
    bid = str(biz["id"])
    if not UUID.match(str(moment_id or "")):
        return False, "moment_gone"
    rows = _read(f"/church_moments?id=eq.{_q(moment_id)}&business_id=eq.{_q(bid)}&status=in.(shown,held)"
                 f"&select=id,posted_by,media_path&limit=1")
    if rows is None:
        return False, "moment_soon" if missing() else "error"
    if not rows:
        return False, "moment_gone"
    m = rows[0]
    if me and str(m.get("posted_by")) == str(me.get("id")):
        by = "poster"
    else:
        ok = may_take_down(biz, me, owner=owner)
        if ok is None:
            return False, "error"
        if not ok:
            return False, "moment_gone"
        by = "owner" if owner else f"leader:{me['id']}"
    done = sb_clients.sb_patch_as_service(
        f"/church_moments?id=eq.{_q(m['id'])}&business_id=eq.{_q(bid)}&status=in.(shown,held)",
        {"status": "removed", "removed_at": _now().isoformat(), "removed_by": by[:80]})
    if done is None:
        return False, "error"
    path = str(m.get("media_path") or "")
    if path.startswith(f"{bid}/news-photos/"):
        chat_photos.drop(path)
    forget(bid)
    return True, "moment_down"


# ─── the safety officers' held list (church_news) ────────────────────


def held(business_id: str) -> Optional[List[Dict[str, Any]]]:
    """Moments the check held that haven't ended, newest first, for the
    safety officers beside the held comments: {id, post_id, body,
    contact_id, created_at, kind: 'moment', post_title}. [] before the
    tables are there; None on a failed read (never "nothing is held")."""
    rows = _read(f"/church_moments?business_id=eq.{_q(business_id)}&status=eq.held"
                 f"&ends_at=gt.{_q(_now().isoformat())}&select=id,posted_by,group_id,line,created_at"
                 f"&order=created_at.desc&limit=50")
    if not isinstance(rows, list):
        return [] if missing() else None
    gids = sorted({str(r["group_id"]) for r in rows if r.get("group_id")})
    names: Dict[str, str] = {}
    if gids:
        got = sb_clients.sb_get_as_service(f"/groups?business_id=eq.{_q(business_id)}&id=in.({_ids(gids)})&select=id,name")
        names = {str(g["id"]): g.get("name") or "" for g in (got or [])}
    return [{"id": str(r["id"]), "post_id": str(r["id"]), "body": r.get("line") or "", "contact_id": r.get("posted_by"),
             "created_at": r.get("created_at"), "kind": "moment",
             "post_title": (f"their moment for {names.get(str(r['group_id'])) or 'a group'}" if r.get("group_id")
                            else "their moment for the whole church")} for r in rows]


def decide_held(business_id: str, moment_id: str, show: bool) -> Optional[bool]:
    """A safety officer's answer on a held moment: Let it through (shown
    for the time it has left) or Keep it hidden (taken down). True done,
    False no such held moment, None on a failed write."""
    if not UUID.match(str(moment_id or "")):
        return False
    rows = _read(f"/church_moments?id=eq.{_q(moment_id)}&business_id=eq.{_q(business_id)}&status=eq.held&select=id&limit=1")
    if rows is None:
        return False if missing() else None
    if not rows:
        return False
    now = _now().isoformat()
    patch = ({"status": "shown", "held_reason": None, "decided_at": now, "decided_by": "officer"} if show else
             {"status": "removed", "removed_at": now, "removed_by": "officer", "decided_at": now, "decided_by": "officer"})
    done = sb_clients.sb_patch_as_service(
        f"/church_moments?id=eq.{_q(moment_id)}&business_id=eq.{_q(business_id)}&status=eq.held", patch)
    if done is None:
        return None
    forget(business_id)
    return True


# ─── its photo ───────────────────────────────────────────────────────


def photo_link(business_id: str, me_id: str, moment_id: str) -> Optional[str]:
    """A short signed link to a moment's photo for someone who may see it
    ('' for anyone else; None when a read failed)."""
    import member_photos
    import news_share as ns
    import storage_links
    m, why = _visible_to(business_id, me_id, moment_id)
    if not m:
        return None if why == "error" else ""
    path = str(m.get("media_path") or "")
    if not path.startswith(f"{business_id}/news-photos/"):
        return ""
    return storage_links.signed_url_sync(member_photos.BUCKET, path, ttl=ns.LINK_TTL) or None


def photo_href(moment_id: Any) -> str:
    return f"/my/moment/{_q(moment_id)}/photo"


# ─── Home: the circles (member_portal_lumen.render_home) ─────────────

TITLES = ("pastor", "pastora", "rev", "rev.", "reverend", "dr", "dr.", "bishop", "elder", "minister", "apostle",
          "evangelist", "prophet", "prophetess", "deacon", "deaconess", "mother", "father", "brother", "sister")
EYE = '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'
TRASH = ('<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/>'
         '<path d="M14 11v6"/>')


def _svg(paths: str, size: int = 22) -> str:
    return (f'<svg class="lm-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" '
            f'focusable="false">{paths}</svg>')


def _ic(name: str, size: int = 22) -> str:
    import member_lumen_ui as lm
    return lm.ic(name, size)


def _words(name: Any) -> List[str]:
    return [w for w in str(name or "").lower().replace(",", " ").split() if w not in TITLES]


def same_person(author: Any, name: Any) -> bool:
    """Whether a devotional's author line names this person: every word of
    their name, titles aside ("Pastor James Carter" and "James Carter")."""
    a, n = _words(author), _words(name)
    return len(n) >= 2 and all(w in a for w in n)


def left(end: Optional[datetime], now: datetime) -> str:
    """How long a moment has left: '21h', '2d', '35m'."""
    if not end:
        return ""
    s = max(0, int((end - now).total_seconds()))
    if s >= 2 * 86400:
        return f"{s // 86400}d"
    if s >= 3600:
        return f"{s // 3600}h"
    return f"{max(1, s // 60)}m"


def home_rights(data: Optional[Dict[str, Any]], me: Dict[str, Any], groups: Optional[Dict[str, Any]]) -> str:
    """'church' (a pastor or someone the office picked), 'groups' (leads a
    group), or '' (can't post), from what Home already has."""
    if not data:
        return ""
    mid = str(me.get("id"))
    if mid in data["pastors"] or mid in data["picked"]:
        return "church"
    if any((g or {}).get("role") == "leader" for g in (groups or {}).get("mine") or []):
        return "groups"
    return ""


def own_showing(data: Optional[Dict[str, Any]], me: Dict[str, Any]) -> bool:
    return any(str(m.get("posted_by")) == str(me.get("id")) and m.get("status") == "shown"
               for m in (data or {}).get("moments") or [])


def soft_card(can: str) -> str:
    """Under the greeting: an invitation to post, for someone who may and
    has no moment showing."""
    if not can:
        return ""
    where = "everyone's Home" if can == "church" else "your group's Home"
    return (f'<a class="lm-mtip" href="/my/moment/new"><span class="lm-di" aria-hidden="true">{_ic("camera", 21)}</span>'
            f'<span><b>Say something to your church today</b><small>A photo and one line, at the start of {where} '
            f'for a day.</small></span></a>')


def _love(mid: str, on: bool) -> str:
    """Love on a leader's moment: answered in place (Home's RX_JS, the
    feed's own reaction script); the viewer's script sets `on` first."""
    return (f'<form method="post" action="/my/moment/love" class="nw-rxf lm-mvlove lm-mlove">'
            f'<input type="hidden" name="id" value="{_e(mid)}"><input type="hidden" name="on" value="{"0" if on else "1"}">'
            f'<button class="lm-mvac" type="submit" aria-pressed="{"true" if on else "false"}" aria-label="Love">'
            f'{_ic("heart", 24)}</button></form>')


def _down(mid: str) -> str:
    return (f'<form method="post" action="/my/moment/remove" class="lm-mdown"><input type="hidden" name="id" value="{_e(mid)}">'
            f'<button class="lm-mvac" type="submit" aria-label="Take it down">{_svg(TRASH, 22)}</button></form>')


def _sheet(m: Dict[str, Any], counts: Optional[Dict[str, int]]) -> str:
    """The poster's own sheet: how many saw it and loved it (counts only),
    where replies go, and Take it down. A held one says it's held. Counts
    None (the read failed): no numbers at all, never a made-up zero."""
    mid = str(m["id"])
    down = (f'<form method="post" action="/my/moment/remove"><input type="hidden" name="id" value="{_e(mid)}">'
            f'<button class="lm-mvrow red" type="submit">{_svg(TRASH, 22)}<span>Take it down</span></button></form>')
    head = ('<div class="lm-mvsheet" role="group" aria-label="Your moment"><span class="lm-mvgrab" aria-hidden="true">'
            '</span><h3>Your moment</h3>')
    if m.get("status") == "held":
        say = CARE if m.get("held_reason") == "self_harm" else HELD
        return f'{head}<p class="lm-mvnote">{_e(say)}</p>{down}</div>'
    replies = (f'<div class="lm-mvrow">{_ic("chat", 22)}<span>Replies come to your Messages<small>One conversation each, '
               f'only you and them</small></span></div>')
    if counts is None:
        return f'{head}{replies}{down}</div>'
    seen, loved = int(counts.get("seen") or 0), int(counts.get("loved") or 0)
    nobody = "A count only. Nobody&#x27;s name is shown."
    return (f'{head}<div class="lm-mvrow">{_svg(EYE, 22)}<span>Seen by {seen}<small>{nobody}</small></span></div>'
            f'{replies}<div class="lm-mvrow">{_ic("heart", 22)}<span>{loved} loved it</span></div>{down}</div>')


def circles(data: Dict[str, Any], *, me: Dict[str, Any], groups: Optional[Dict[str, Any]], now: datetime,
            church: str, button, derived: Optional[Dict[str, Any]] = None, derived_who: Optional[Dict[str, str]] = None,
            owner: bool = False, owner_contact: str = "") -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
    """Leaders' circles for Home's row: (first: the member's own circle and
    the pastors', after: the other leaders', took: whether the derived
    pastor moment joined one of them). One circle a person, their moments
    as its slides oldest first; a group's moment only for that group's
    people; their own held one only for them. `button(kind, ref)` draws a
    moment's button from Home's This week records ('' when it isn't for
    this member). A pastor, or the church's owner (`owner`: their preview;
    `owner_contact`: their own member record), sees Take it down on the
    others' moments."""
    import member_app_ui as ui
    import member_lumen_stories as mls
    import member_photos as ph
    mid = str(me.get("id"))
    mine_g = {str(g.get("id")) for g in (groups or {}).get("mine") or []}
    pastors, marks, counts, write = data["pastors"], data["marks"], data["counts"], data["write"]
    can = home_rights(data, me, groups)
    lead_down = owner or mid in pastors or (bool(owner_contact) and owner_contact == mid)
    by: Dict[str, List[Dict[str, Any]]] = {}
    for m in data["moments"]:
        pid = str(m.get("posted_by"))
        if pid != mid and (m.get("status") != "shown" or (m.get("group_id") and str(m["group_id"]) not in mine_g)):
            continue
        if showing(m, now):
            by.setdefault(pid, []).append(m)

    def face_of(pid: str, person: Dict[str, Any]) -> str:
        own = ph.src(person) if pid == mid or ph.shown_to_members(person) else ""
        return ui.photo(own, look="colour") if own else mls.ring_initials(person.get("name"))

    made: Dict[str, Dict[str, Any]] = {}
    for pid, ms in by.items():
        person = me if pid == mid else (data["people"].get(pid) or {})
        name = " ".join(str(person.get("name") or "").split()) or "A leader"
        first = name.split()[0]
        face = face_of(pid, person)
        slides = []
        for m in sorted(ms, key=lambda x: str(x.get("created_at") or "")):
            if m.get("group_id"):
                gname = data["groups"].get(str(m["group_id"]), "") or "Your group"
                kicker = f"{gname} · from {mls.short_name(name)}"
            elif pid in pastors:
                kicker = "A word from your pastor"
            else:
                kicker = f"For everyone at {church}"
            bg = ui.photo(photo_href(m["id"]), look="colour")
            when = mls.ago(m.get("created_at"), now)
            if pid == mid:
                held_ = m.get("status") == "held"
                s = mls.moment(mid=f"lm:{m['id']}", label="Your moment", ring=face, bg=bg, face=face, name="Your moment",
                               href=photo_href(m["id"]), kicker="Only you can see this" if held_ else kicker,
                               line=m.get("line") or "", when=f"{when} · {left(_at(m.get('ends_at')), now)} left")
                s.update(sheet=_sheet(m, None if counts is None else (counts.get(str(m["id"])) or {})), mine=True)
            else:
                mk = marks.get(str(m["id"])) or {}
                reply = (f"/my/messages/to/{pid}", f"Send {first} a note…") if write.get(pid) else None
                act = button(m.get("button_kind"), str(m.get("button_ref") or "")) if m.get("button_kind") else ""
                s = mls.moment(mid=f"lm:{m['id']}", label=mls.short_name(name), ring=face, bg=bg, face=face, name=name,
                               href=photo_href(m["id"]), kicker=kicker, line=m.get("line") or "", when=when,
                               action=act, reply=reply, love=_love(str(m["id"]), bool(mk.get("loved"))))
                s.update(seen_id=str(m["id"]), was=bool(mk.get("seen")), down=_down(str(m["id"])) if lead_down else "")
            slides.append(s)
        made[pid] = {"id": f"lp:{pid}", "label": "Your moment" if pid == mid else mls.short_name(name), "ring": face,
                     "href": photo_href(ms[-1]["id"]), "name": "Your moment" if pid == mid else name,
                     "line": slides[-1]["line"], "slides": slides, "mine": pid == mid, "plus": pid == mid and bool(can),
                     "newest": max(str(x.get("created_at") or "") for x in ms), "pastor": pid in pastors, "pid": pid}
    # The derived pastor moment joins its pastor's own circle (never two circles for one pastor).
    took = False
    if derived and derived_who:
        hit = None
        if derived_who.get("id"):
            hit = made.get(str(derived_who["id"]))
        elif derived_who.get("name"):
            for c in made.values():
                who = me if c["mine"] else (data["people"].get(c["pid"]) or {})
                if (c["pastor"] or c["mine"]) and same_person(derived_who["name"], who.get("name")):
                    hit = c
                    break
        if hit:
            hit["slides"].append(derived)
            took = True
    own = made.pop(mid, None)
    if own is None and can:
        # Their circle before they post: their photo and a +, to the composer.
        own = {"id": "lp:me", "label": "Your moment", "ring": face_of(mid, me), "href": "/my/moment/new",
               "name": "Add your moment", "line": "", "slides": None, "mine": True, "plus": True, "compose": True}
    rest = sorted(made.values(), key=lambda c: c["newest"], reverse=True)
    return ([own] if own else []) + [c for c in rest if c["pastor"]], [c for c in rest if not c["pastor"]], took


def flash(request: Request) -> str:
    """Home's line after a moment was posted or taken down."""
    done = DONE.get(request.query_params.get("done") or "")
    if done:
        return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>'
    code = str(request.query_params.get("err") or "")
    err = ERRORS.get(code) if code.startswith("moment") else ""
    return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>' if err else ""


# ─── the row, when it has people (member_lumen_stories.row hands over) ──


def people_row(items: List[Dict[str, Any]]) -> str:
    """Home's moments row with leaders' circles: one circle a person, each
    a run of slides in the viewer (a lone moment is a circle of one), and
    the member's own circle first (its + opens the composer). The viewer is
    member_lumen_stories', its segments the open circle's; the script marks
    a leader's moment seen on the server once (data-seen), beside the
    phone's own rings."""
    import member_lumen_stories as mls
    plus = _ic("plus", 14)
    circles_html: List[str] = []
    slides: List[str] = []
    segs: List[str] = []
    ci = 0
    for it in items:
        if it.get("compose"):
            circles_html.append(
                f'<a class="lm-mo lm-mome lm-monew" href="/my/moment/new" aria-label="Add your moment">'
                f'<span class="lm-mor"><span><span class="lm-mop">{it["ring"]}</span></span></span>'
                f'<i class="lm-moplus" aria-hidden="true">{plus}</i><b>Your moment</b></a>')
            continue
        run = it["slides"] if it.get("slides") is not None else [it]
        cls = "lm-mo lm-mome" if it.get("mine") else "lm-mo"
        circle = (f'<a class="{cls}" href="{_e(it["href"])}" data-mo="{_e(it["id"])}" aria-label="{_e(it["name"])}: '
                  f'{_e(it["line"])}"><span class="lm-mor"><span><span class="lm-mop">{it["ring"]}</span></span></span>'
                  f'<b>{_e(it["label"])}</b></a>')
        if it.get("mine") and it.get("plus"):
            circle = (f'<span class="lm-mow">{circle}<a class="lm-moadd" href="/my/moment/new" aria-label="Add a moment">'
                      f'{plus}</a></span>')
        circles_html.append(circle)
        for m in run:
            n = len(slides) + 1
            reply = m.get("reply")
            pill = f'<a class="lm-mvre" href="{_e(reply[0])}">{_e(reply[1])}</a>' if reply else ""
            acts = f'{pill}<span class="lm-mvacts">{m.get("love") or ""}{m.get("share") or ""}{m.get("down") or ""}</span>'
            when = f'<small>{_e(m["when"])}</small>' if m.get("when") else ""
            sub = f'<p class="lm-mvp">{_e(m["sub"])}</p>' if m.get("sub") else ""
            act = f'<div class="lm-mvdo">{m["action"]}</div>' if m.get("action") else ""
            seen = f' data-seen="{_e(m["seen_id"])}"' if m.get("seen_id") else ""
            was = ' data-was="1"' if m.get("was") else ""
            foot = m["sheet"] if m.get("sheet") else f'<div class="lm-mvft">{acts}</div>'
            slides.append(
                f'<section class="lm-mvs{" mine" if m.get("mine") else ""}" role="group" aria-roledescription="moment" '
                f'aria-label="{n} of %N%: {_e(m["name"])}" data-c="{ci}" data-mo="{_e(m["id"])}"{seen}{was} hidden>'
                f'<span class="lm-mvbg">{m["bg"]}</span><span class="lm-mvsh" aria-hidden="true"></span>'
                f'<header class="lm-mvhd"><span class="lm-mvf">{m["face"]}</span><span class="lm-mvn"><b>{_e(m["name"])}</b>'
                f'{when}</span></header>'
                f'<div class="lm-mvbd"><p class="lm-mvk">{_e(m["kicker"])}</p><h2 class="lm-mvh">{_e(m["line"])}</h2>{sub}'
                f'{act}</div>{foot}</section>')
            segs.append(f'<i data-c="{ci}"></i>')
        ci += 1
    total = str(len(slides))
    viewer = ""
    if slides:
        viewer = (f'<div class="lm-mv" id="lm-mv" role="dialog" aria-modal="true" aria-label="Moments" hidden>'
                  f'<div class="lm-mvst"><div class="lm-mvg" aria-hidden="true">{"".join(segs)}</div>'
                  f'<button class="lm-mvl" type="button" aria-label="Previous moment"></button>'
                  f'<button class="lm-mvr" type="button" aria-label="Next moment"></button>'
                  f'{"".join(s.replace("%N%", total) for s in slides)}'
                  f'<button class="lm-mvx" type="button" aria-label="Close">{mls._ic("x", 24)}</button></div></div>{JS}')
    return f'<nav class="lm-mos" id="lm-mos" aria-label="Moments from your church">{"".join(circles_html)}</nav>{viewer}'


# The viewer with circles of several slides (member_lumen_stories.JS, made
# for runs): a circle opens at its first slide not yet seen; the segments
# are the open circle's; a circle is seen when all its slides are; a
# leader's moment is marked seen on the server once (POST /my/moment/seen,
# never again once the phone or the server knows it); Love sets what it
# asks for before Home's reaction script sends it. Seen rings stay on the
# phone (localStorage "lm-seen", two weeks), as before.
JS = r"""<script>(function(){
var d=document,row=d.getElementById('lm-mos'),v=d.getElementById('lm-mv');if(!row||!v)return;
d.body.appendChild(v);
var K='lm-seen',S=null,AGE=1209600000,DUR=6000;try{S=window.localStorage;}catch(e){}
function load(){try{var m=JSON.parse((S&&S.getItem(K))||'{}');return m&&typeof m==='object'?m:{};}catch(e){return {};}}
var cs=[].slice.call(row.querySelectorAll('.lm-mo[data-mo]')),ss=[].slice.call(v.querySelectorAll('.lm-mvs')),
 gs=[].slice.call(v.querySelectorAll('.lm-mvg i')),seen=load();
function cOf(k){return +ss[k].getAttribute('data-c');}
function idOf(k){return ss[k].getAttribute('data-mo');}
function was(k){return !!seen[idOf(k)]||ss[k].hasAttribute('data-was');}
function done(c){for(var k=0;k<ss.length;k++){if(cOf(k)===c&&!was(k))return false;}return true;}
cs.forEach(function(c,i){if(done(i))c.classList.add('seen');});
function tell(k){var s=ss[k],m=s.getAttribute('data-seen');if(!m||s.hasAttribute('data-was'))return;s.setAttribute('data-was','1');
 try{var f=new FormData();f.append('id',m);fetch('/my/moment/seen',{method:'POST',body:f,credentials:'same-origin',
  redirect:'manual',keepalive:true}).catch(function(){});}catch(e){}}
function mark(k){var id=idOf(k),now=Date.now();if(!id)return;seen=load();var knew=!!seen[id];seen[id]=now;
 for(var x in seen){if(!(now-seen[x]<AGE))delete seen[x];}
 try{if(S)S.setItem(K,JSON.stringify(seen));}catch(e){}
 if(!knew)tell(k);var c=cOf(k);if(cs[c]&&done(c))cs[c].classList.add('seen');}
var still=!!(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches);
var at=-1,t=null,held=false,pushed=false,from=null,go2=null;
function stop(){clearTimeout(t);t=null;}
function arm(){stop();if(still||held||at<0)return;t=setTimeout(function(){step(1);},DUR);}
function show(i){at=i;var c=cOf(i);ss.forEach(function(s,k){s.hidden=k!==i;});
 gs.forEach(function(g,k){g.hidden=cOf(k)!==c;g.className=k<i||(k===i&&still)?'full':'';});
 if(!still&&gs[i]){void gs[i].offsetWidth;gs[i].className='on';}
 mark(i);arm();}
function step(n){var i=at+n;if(i<0)i=0;if(i>=ss.length){close();return;}held=false;show(i);}
function start(c){var f=-1;for(var k=0;k<ss.length;k++){if(cOf(k)===c){if(f<0)f=k;if(!was(k))return k;}}return f;}
function open(i,c){var k=start(i);if(k<0)return;from=c;held=false;v.hidden=false;d.body.classList.add('lm-mvon');
 try{history.pushState({lmmv:1},'');pushed=true;}catch(e){pushed=false;}
 show(k);var x=v.querySelector('.lm-mvx');try{x.focus({preventScroll:true,focusVisible:false});}catch(e){x.focus();}}
function shut(){stop();gs.forEach(function(g){g.className='';});v.hidden=true;d.body.classList.remove('lm-mvon');at=-1;
 if(from){try{from.focus({preventScroll:true});}catch(e){}}}
function close(){if(pushed){pushed=false;history.back();return;}shut();}
window.addEventListener('popstate',function(){if(v.hidden)return;pushed=false;shut();
 if(go2){var g=go2;go2=null;g();}});
window.addEventListener('pageshow',function(e){if(e.persisted&&!v.hidden){pushed=false;shut();}});
window.addEventListener('pagehide',function(){stop();gs.forEach(function(g){g.className='';});});
cs.forEach(function(c,i){c.addEventListener('click',function(e){
 if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||e.button)return;e.preventDefault();open(i,c);});});
v.querySelector('.lm-mvx').addEventListener('click',close);
v.querySelector('.lm-mvl').addEventListener('click',function(){step(-1);});
v.querySelector('.lm-mvr').addEventListener('click',function(){step(1);});
function hold(){held=true;stop();if(gs[at])gs[at].className='full';}
function leave(fn){if(!pushed){fn();return;}pushed=false;go2=fn;history.back();}
function away(u){if(pushed){pushed=false;location.replace(u);}else{location.href=u;}}
v.addEventListener('click',function(e){var a=e.target.closest?e.target.closest('a[href]'):null;
 if(!a||e.defaultPrevented)return;hold();
 if(a.hasAttribute('data-share-kind'))return;
 if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();away(a.href);});
v.addEventListener('submit',function(e){var f=e.target;hold();if(e.defaultPrevented)return;
 if(f.classList.contains('lm-mlove')){var b=f.querySelector('button'),o=f.querySelector('input[name=on]');
  if(b&&o)o.value=b.getAttribute('aria-pressed')==='true'?'0':'1';}
 if(f.classList.contains('nw-rxf'))return;
 e.preventDefault();leave(function(){HTMLFormElement.prototype.submit.call(f);});});
v.addEventListener('pointerdown',function(e){var b=e.target.closest?e.target.closest('button,a,form,.lm-mvsheet'):null;
 if(b&&!b.matches('.lm-mvl,.lm-mvr,.lm-mvx'))hold();});
d.addEventListener('keydown',function(e){if(v.hidden)return;
 if(!v.contains(d.activeElement)&&e.key==='Tab'){e.preventDefault();var x=v.querySelector('.lm-mvx');if(x)x.focus();return;}
 if(e.key==='Escape'){e.preventDefault();close();return;}
 if(e.key==='ArrowRight'){step(1);return;}if(e.key==='ArrowLeft'){step(-1);return;}
 if(e.key!=='Tab')return;var f=[].filter.call(v.querySelectorAll('a[href],button'),function(x){return x.offsetParent!==null;});
 if(!f.length)return;var a=f[0],z=f[f.length-1];
 if(e.shiftKey&&d.activeElement===a){e.preventDefault();z.focus();}else if(!e.shiftKey&&d.activeElement===z){e.preventDefault();a.focus();}});
d.addEventListener('visibilitychange',function(){if(at<0)return;if(d.hidden)stop();else arm();});
})();</script>"""


# ─── the composer ────────────────────────────────────────────────────


def _flash_page(request: Request) -> str:
    q = request.query_params
    err = ERRORS.get(q.get("err") or "")
    return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>' if err else ""


def render(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], r: Dict[str, Any],
           choices: List[Tuple[str, str, str]]) -> str:
    """New moment: the photo and its preview, one line, an optional button
    from this week, who sees it, how long it shows, the check's promise,
    and Share moment."""
    from member_portal import _shell
    church = (biz.get("name") or "").strip() or "your church"
    groups = r.get("groups") or []
    to_church = bool(r.get("church"))
    first_to = "church" if to_church else (str(groups[0]["id"]) if groups else "")
    who = []
    if to_church:
        who.append(f'<label class="lm-pchip"><input type="radio" name="to" value="church" checked>'
                   f'<span>Everyone at {_e(church)}</span></label>')
    for g in groups:
        on = " checked" if str(g["id"]) == first_to else ""
        who.append(f'<label class="lm-pchip"><input type="radio" name="to" value="{_e(g["id"])}"{on}>'
                   f'<span>{_e(g.get("name") or "Your group")}</span></label>')
    buttons = ['<label class="lm-pchip"><input type="radio" name="button" value="none" checked><span>None</span></label>']
    for value, label, gid in choices:
        data_g = f' data-g="{_e(gid)}"' if gid else ""
        buttons.append(f'<label class="lm-pchip"{data_g}><input type="radio" name="button" value="{_e(value)}" '
                       f'data-say="{_e(label.split(" · ", 1)[-1])}"><span>{_e(label)}</span></label>')
    lasts = "".join(f'<label class="lm-pchip"><input type="radio" name="lasts" value="{k}"{" checked" if k == "day" else ""}>'
                    f'<span>{_e(label)}</span></label>' for k, label in LASTS)
    body = (f'<header class="lm-mkhd"><a class="lm-mkx" href="/my">Cancel</a><h1>New moment</h1><span></span></header>'
            f'{_flash_page(request)}'
            f'<form class="lm-mk" id="lm-mk" method="post" action="/my/moment" enctype="multipart/form-data">'
            f'<div class="lm-mkrow"><label class="lm-mkpv" for="lm-mkf"><span class="lm-mkimg" id="lm-mkimg">'
            f'{_ic("image", 28)}<small>Add a photo</small></span><span class="lm-mksh" aria-hidden="true"></span>'
            f'<span class="lm-mkseg" aria-hidden="true"></span><span class="lm-mkln" id="lm-mkln" aria-hidden="true"></span>'
            f'<span class="lm-mkbt" id="lm-mkbt" aria-hidden="true" hidden></span></label>'
            f'<div class="lm-mkside"><p class="lm-mklbl" id="lm-mksay">Say one thing</p>'
            f'<div class="lm-mksay"><textarea name="line" rows="3" maxlength="{LINE_MAX}" required aria-labelledby="lm-mksay" '
            f'aria-describedby="lm-mkn" placeholder="Praying for you this morning."></textarea>'
            f'<small id="lm-mkn">0 / {LINE_MAX}</small></div>'
            f'<label class="lm-mkmb"><input type="file" id="lm-mkf" name="photo" accept="image/jpeg,image/png,image/webp" '
            f'required>{_ic("image", 20)}<span>Photo</span><small id="lm-mkpic">Choose one</small></label></div></div>'
            f'<fieldset class="lm-pset"><legend>Add a button</legend><div class="lm-pchips">{"".join(buttons)}</div></fieldset>'
            f'<fieldset class="lm-pset"><legend>Who sees it</legend><div class="lm-pchips">{"".join(who)}</div></fieldset>'
            f'<fieldset class="lm-pset"><legend>Shows for</legend><div class="lm-pchips">{lasts}</div></fieldset>'
            f'<p class="lm-pguard">{_ic("shield", 16)}<span>Checked like every post before anyone sees it. '
            f'Replies come to you privately, in Messages.</span></p>'
            f'<button class="lm-cpill pri lm-mkgo" type="submit">Share moment</button></form>')
    return _shell(biz, site, "New moment", f'<div class="lm-cx lm-mkpage">{body}</div>', tab="home", who=me,
                  bare=True, bar=False, script=MK_JS)


# The photo and the line as they'll look, the count, the button's words; a
# gathering's button only for a moment for that group (without script every
# choice shows, and the server says so).
MK_JS = r"""<script>(function(){var f=document.getElementById('lm-mk');if(!f)return;f.classList.add('js');
var t=f.querySelector('textarea'),n=document.getElementById('lm-mkn'),ln=document.getElementById('lm-mkln'),
 im=document.getElementById('lm-mkimg'),bt=document.getElementById('lm-mkbt'),pic=document.getElementById('lm-mkpic'),
 fi=document.getElementById('lm-mkf'),url=null;
function say(){var v=(t.value||'').replace(/\s+/g,' ').trim();n.textContent=v.length+' / 120';ln.textContent=v;}
function who(){var w=f.querySelector('input[name=to]:checked'),g=w?w.value:'';
 [].forEach.call(f.querySelectorAll('.lm-pchip[data-g]'),function(c){var on=c.getAttribute('data-g')===g;c.hidden=!on;
  var i=c.querySelector('input');if(!on&&i.checked){i.checked=false;var z=f.querySelector('input[name=button][value=none]');if(z)z.checked=true;}});
 btn();}
function btn(){var b=f.querySelector('input[name=button]:checked'),s=b&&b.value!=='none'?b.getAttribute('data-say'):'';
 bt.textContent=s||'';bt.hidden=!s;}
fi.addEventListener('change',function(){var x=fi.files&&fi.files[0];if(url){try{URL.revokeObjectURL(url);}catch(e){}url=null;}
 if(!x){im.classList.remove('on');im.style.backgroundImage='';pic.textContent='Choose one';return;}
 try{url=URL.createObjectURL(x);im.style.backgroundImage='url("'+url+'")';im.classList.add('on');}catch(e){}
 pic.textContent='Chosen';f.querySelector('.lm-mkmb').classList.add('on');});
t.addEventListener('input',say);f.addEventListener('change',function(e){if(e.target.name==='to')who();if(e.target.name==='button')btn();});
say();who();
f.addEventListener('submit',function(){var b=f.querySelector('button[type=submit]');if(b){b.disabled=true;b.textContent='Sharing…';}});})();</script>"""


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any]) -> Tuple[str, int]:
    """GET /my/moment/new (member_portal.serve; the new look only): the
    composer for someone who may post, once the tables are there. Anyone
    else goes Home."""
    ok, r = await asyncio.gather(asyncio.to_thread(ready), asyncio.to_thread(rights, str(biz["id"]), str(me["id"])))
    if not ok or not may_post(r):
        return "", 303
    choices = await asyncio.to_thread(week_choices, biz, me, (r or {}).get("groups") or [])
    return render(biz, site, request, me, r, choices), 200


async def photo(biz: Dict[str, Any], me: Dict[str, Any], moment_id: str):
    """GET /my/moment/<id>/photo: a short signed link, for whoever may see it."""
    from fastapi.responses import Response
    from member_portal import _SECURE_HEADERS
    link = await asyncio.to_thread(photo_link, str(biz["id"]), str(me["id"]), moment_id)
    if link is None:
        return Response(status_code=503, headers=_SECURE_HEADERS)
    if not link:
        return Response(status_code=404, headers=_SECURE_HEADERS)
    return RedirectResponse(link, status_code=302, headers={**_SECURE_HEADERS, "Cache-Control": "private, max-age=300"})


# ─── the routes ──────────────────────────────────────────────────────


def _go(path: str = "/my/moment/new", **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    path = path if path in ("/my", "/my/moment/new") else "/my"
    qs = "&".join(f"{k}={v}" for k, v in q.items() if v)
    return RedirectResponse(path + (f"?{qs}" if qs else ""), status_code=303, headers=_SECURE_HEADERS)


async def _member(request: Request, bucket: str):
    """(church, sess, me, stop): this church's address and the same site
    (member_portal._church_or_404), a live session (never the owner's
    preview), the new look showing to it, and the per-person limit."""
    import member_lumen
    import member_portal as mp
    import rate_limit
    church = await mp._church_or_404(request)
    sess = await asyncio.to_thread(mp._session_for, request, church)
    if sess and sess.get("unavailable"):
        return church, sess, None, "error"
    if sess and sess.get("preview"):
        return church, sess, None, "preview"
    if not sess or not sess.get("me"):
        return church, sess, None, "signin"
    if not await member_lumen.decide(request, {"business": church["business"], "session": sess}):
        return church, sess, None, "signin"
    if not rate_limit.allow_strict(bucket, f"{church['business']['id']}|{sess['me']['id']}"):
        return church, sess, None, "slow"
    return church, sess, sess["me"], ""


@router.post("/my/moment", include_in_schema=False)
async def post_route(request: Request):
    import member_photos
    church, _sess, me, stop = await _member(request, "member_action")
    if stop:
        return _go("/my") if stop == "signin" else _go(err=stop)
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return _go(err="error")
    raw = None
    up = form.get("photo")
    if hasattr(up, "read"):
        raw = await up.read(member_photos.MAX_BYTES + 1)
        if raw and len(raw) > member_photos.MAX_BYTES:
            return _go(err="photo_bad")
    ok, code = await post(church["business"], me, to=str(form.get("to") or ""), line=str(form.get("line") or ""),
                          photo=raw or None, button=str(form.get("button") or ""), lasts=str(form.get("lasts") or "day"))
    return _go("/my", done=code) if ok else _go(err=code)


async def _mark_route(request: Request, love: bool):
    from fastapi.responses import Response
    from member_portal import _SECURE_HEADERS
    church, _sess, me, stop = await _member(request, "moment_mark")
    if stop:
        return Response(status_code=204 if stop in ("preview", "signin") else 429 if stop == "slow" else 503,
                        headers=_SECURE_HEADERS)
    form = await request.form()
    on = None if not love else str(form.get("on") or "1") != "0"
    got = await asyncio.to_thread(mark, str(church["business"]["id"]), str(me["id"]), str(form.get("id") or ""), love=on)
    if "application/json" in (request.headers.get("accept") or "") or not love:
        return Response(status_code=204 if got == "ok" else 404 if got == "gone" else 503, headers=_SECURE_HEADERS)
    return _go("/my")


@router.post("/my/moment/seen", include_in_schema=False)
async def seen_route(request: Request):
    """The viewer's mark that this member saw a leader's moment (sent once)."""
    return await _mark_route(request, False)


@router.post("/my/moment/love", include_in_schema=False)
async def love_route(request: Request):
    """Love on a leader's moment, or taking it back (answered in place)."""
    return await _mark_route(request, True)


@router.post("/my/moment/remove", include_in_schema=False)
async def remove_route(request: Request):
    """Take a moment down: its poster, a pastor, or the church's owner (from
    their preview too). Works whatever the look."""
    import member_app_pictures as mapic
    import member_portal as mp
    import rate_limit
    church = await mp._church_or_404(request)
    biz = church["business"]
    sess = await asyncio.to_thread(mp._session_for, request, church)
    if not sess or sess.get("unavailable"):
        return _go("/my", err="error") if sess else _go("/my")
    owner = bool(sess.get("preview")) and str(mapic.may_edit(sess, biz) or "").startswith("owner:")
    me = None if sess.get("preview") else sess.get("me")
    if not me and not owner:
        return _go("/my")
    who = f"owner:{(sess.get('claims') or {}).get('own') or ''}" if owner else str(me["id"])
    if not rate_limit.allow_strict("member_action", f"{biz['id']}|moment_down|{who}"):
        return _go("/my", err="slow")
    form = await request.form()
    ok, code = await asyncio.to_thread(remove, biz, me, str(form.get("id") or ""), owner=owner)
    return _go("/my", **({"done": code} if ok else {"err": code}))


# Joins /my/lumen.<hash>.css (member_lumen_ui.templates), after the
# moments' own block; every rule under .lm or one of the row's own classes;
# tokens only, so Light, Dark and Same as my phone draw it. The poster's
# sheet is the page's own surface (light in Light, dark in Dark) over the
# viewer's photo.
CSS = """
/* Look 5.1: a pastor's or a leader's own moment (member_moments) */
.lm-mome{position:relative;}
.lm-monew .lm-mor{background:none;}
.lm-moplus,.lm-moadd{position:absolute;left:48px;top:48px;z-index:1;width:24px;height:24px;border-radius:50%;display:grid;
  place-items:center;background:var(--acc-fill);color:var(--on-acc);box-shadow:0 0 0 3px var(--bg);text-decoration:none;}
.lm-moplus svg,.lm-moadd svg{width:14px;height:14px;stroke-width:2.6;}
.lm-mow{position:relative;flex:none;display:flex;}
.lm-moadd:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
.lm-mvg i[hidden]{display:none;}
.lm-mvacts form{margin:0;}
.lm-mvs.mine .lm-mvbd{bottom:calc(318px + env(safe-area-inset-bottom,0px));}
.lm-mvsheet{position:absolute;left:0;right:0;bottom:0;z-index:6;padding:10px 0 calc(20px + env(safe-area-inset-bottom,0px));
  border-radius:22px 22px 0 0;background:var(--bg);color:var(--fg);box-shadow:0 -12px 40px rgba(0,0,0,.25);}
.lm-mvgrab{display:block;width:38px;height:5px;margin:0 auto 10px;border-radius:3px;background:var(--s2);}
.lm-mvsheet h3{margin:0;padding:0 16px 12px;border-bottom:1px solid var(--lm-line);text-align:center;font:700 15px/1.2 var(--mb-ui);
  color:var(--fg);}
.lm-mvsheet form{margin:0;}
.lm-mvrow{display:flex;align-items:center;gap:14px;width:100%;padding:14px 20px;border:0;background:none;color:var(--fg);
  font:600 15px/1.25 var(--mb-ui);text-align:left;}
.lm-mvrow>span{min-width:0;}
.lm-mvrow small{display:block;margin-top:2px;font:500 13px/1.3 var(--mb-ui);color:var(--fg3);}
.lm-mvrow .lm-ic{flex:none;}
.lm-mvsheet button{cursor:pointer;}
.lm-mvrow.red{color:var(--lm-coral);}
.lm-mvrow:focus-visible{outline:2px solid var(--acc);outline-offset:-2px;}
.lm-mvnote{margin:0;padding:14px 20px 4px;font:400 14.5px/1.45 var(--mb-ui);color:var(--fg2);}
.lm .lm-mtip{display:flex;gap:12px;align-items:flex-start;margin:16px 0 0;padding:14px 16px;border-radius:18px;background:var(--s1);
  color:var(--fg);text-decoration:none;}
.lm .lm-mtip .lm-di{flex:none;width:36px;height:36px;margin:0;border-radius:12px;}
.lm .lm-mtip b{display:block;font:700 14.5px/1.3 var(--mb-ui);}
.lm .lm-mtip small{display:block;margin-top:2px;font:400 13.5px/1.4 var(--mb-ui);color:var(--fg2);}
.lm .lm-mtip:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}

/* the composer, /my/moment/new */
.lm .lm-mkpage{padding-bottom:20px;}
.lm .lm-mkhd{position:relative;display:flex;align-items:center;justify-content:center;height:56px;margin:0 -20px;padding:0 16px;
  border-bottom:1px solid var(--lm-line);}
.lm .lm-mkhd h1{margin:0;font:750 17px/1 var(--mb-ui);color:var(--fg);}
.lm .lm-mkx{position:absolute;left:16px;top:50%;transform:translateY(-50%);padding:10px 0;font:550 15px/1 var(--mb-ui);
  color:var(--fg2);text-decoration:none;}
.lm .lm-mk{margin-top:18px;display:flex;flex-direction:column;min-height:calc(100vh - 94px);}
@supports (min-height:100svh){.lm .lm-mk{min-height:calc(100svh - 94px);}}
.lm .lm-mkrow{display:flex;gap:16px;}
.lm .lm-mkpv{position:relative;flex:none;width:132px;height:234px;border-radius:16px;overflow:hidden;background:#000;color:#fff;
  cursor:pointer;}
.lm .lm-mkimg{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;
  background:var(--s2) center/cover no-repeat;color:var(--fg2);font:600 12px/1 var(--mb-ui);}
.lm .lm-mkimg.on>*{visibility:hidden;}
.lm .lm-mksh{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,0) 45%,rgba(0,0,0,.78) 100%);pointer-events:none;}
.lm .lm-mkseg{position:absolute;left:7px;right:7px;top:7px;height:2px;border-radius:1px;background:rgba(255,255,255,.55);}
.lm .lm-mkln{position:absolute;left:10px;right:10px;bottom:30px;font:400 13px/1.25 var(--mb-serif);color:#fff;overflow-wrap:anywhere;}
.lm .lm-mkbt{position:absolute;left:10px;bottom:9px;max-width:112px;height:18px;padding:0 8px;border-radius:9px;background:#fff;
  color:#111;font:700 8.5px/18px var(--mb-ui);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lm .lm-mkbt[hidden]{display:none;}
.lm .lm-mkside{flex:1;min-width:0;display:flex;flex-direction:column;gap:10px;}
.lm .lm-mklbl{margin:0;font:650 12px/1.2 var(--mb-ui);letter-spacing:.08em;text-transform:uppercase;color:var(--fg3);}
.lm .lm-mksay{padding:12px 13px 8px;border-radius:14px;background:var(--s1);}
.lm .lm-mksay:focus-within{box-shadow:0 0 0 2px var(--acc);}
.lm .lm-mksay textarea{display:block;width:100%;min-height:72px;margin:0;padding:0;border:0;resize:none;background:none;color:var(--fg);
  font:400 15px/1.35 var(--mb-serif);outline:none;}
.lm .lm-mksay small{display:block;margin-top:6px;text-align:right;font:500 11.5px/1 var(--mb-ui);color:var(--fg3);}
.lm .lm-mkmb{position:relative;height:58px;border-radius:14px;box-shadow:inset 0 0 0 1.5px var(--lm-line);display:flex;
  flex-direction:column;align-items:center;justify-content:center;gap:2px;font:650 12px/1.2 var(--mb-ui);color:var(--fg);cursor:pointer;}
.lm .lm-mkmb input{position:absolute;opacity:0;width:1px;height:1px;}
.lm .lm-mkmb small{font:500 10.5px/1 var(--mb-ui);color:var(--fg3);}
.lm .lm-mkmb.on{background:var(--lm-tint-10);box-shadow:inset 0 0 0 1.5px var(--acc-fill);color:var(--acc);}
.lm .lm-mkmb.on small{color:var(--acc);}
.lm .lm-mkmb:focus-within{outline:2px solid var(--acc);outline-offset:2px;}
.lm .lm-mk .lm-pchip[hidden]{display:none;}
.lm .lm-mk .lm-mkgo{flex:none;height:52px;margin-top:auto;padding-top:0;font-size:16px;}
.lm .lm-mk .lm-pguard{margin-bottom:24px;}
.lm .lm-mk .lm-mkgo[disabled]{opacity:.65;}
@media (prefers-reduced-motion:no-preference){
  .lm .lm-mtip{transition:transform .2s ease-out;}
  .lm .lm-mtip:active{transform:scale(.98);}
}
"""
