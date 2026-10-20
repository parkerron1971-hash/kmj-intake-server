"""
group_gatherings.py — when a church group meets, who's coming, who came.

Part 3 of the approved canvas "Church Groups, Together" (boards Meet, Roll
and Settings: "A real schedule, so RSVPs, reminders and attendance all line
up"). The group page's Meet tab:

  * the next gathering from the group's regular time (groups.meet_day /
    meet_time, the church's own clock), its street address and the host's
    directions — shown only to people in the group
  * Going / Maybe / Can't make it (group_rsvps), with who else is coming
  * "I'm here", from 30 minutes before to 4 hours after the start: counted
    in the same group_meetings / group_meeting_attendance the office reads
    (how = 'self'), so the office's attendance and "missing lately" line up
  * a leader takes the roll from their phone on the day (how = 'leader'),
    with a guest count and a note; skips a week; sets the regular time
  * the last few gatherings: how many came, and whether you were there
  * a reminder (member_push "groups"): 5 PM on the day of an evening
    gathering, 5 PM the day before an earlier one; never to someone who
    said they can't make it

The routes live in member_portal_groups (/my/groups/meet...).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger(__name__)

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
ANSWERS = ("going", "maybe", "no")
HERE_BEFORE = timedelta(minutes=30)
HERE_AFTER = timedelta(hours=4)
REMIND_AT = 17                 # 5 PM
EVENING = time(18, 0)          # a gathering from 6 PM is reminded the same day
PAST_SHOWN = 4
ADDRESS_MAX, NOTE_MAX, ROLL_NOTE_MAX = 200, 300, 2000


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    """The one clock the schedule reads (tests pin it)."""
    return datetime.now(timezone.utc)


def zone(business: Dict[str, Any]):
    """The church's clock (business_marketing.business_tz; the owner's
    profile when its availability has none). None when it can't be read:
    a gathering is never placed on a guessed clock."""
    import business_marketing
    row = business
    if "owner_id" not in row:
        got = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{_q(business.get('id') or '')}&select=id,settings,owner_id&limit=1")
        if not isinstance(got, list):
            return None
        if got:
            row = {**business, **got[0]}
    try:
        return business_marketing.business_tz(row)
    except Exception:
        return None


def _time(g: Dict[str, Any]) -> Optional[time]:
    raw = str(g.get("meet_time") or "")
    try:
        return time.fromisoformat(raw[:8]) if raw else None
    except ValueError:
        return None


def scheduled(g: Dict[str, Any]) -> bool:
    return g.get("meet_day") is not None and _time(g) is not None


def starts_at(g: Dict[str, Any], day: date, tz) -> datetime:
    return datetime.combine(day, _time(g), tzinfo=tz)


def next_on(g: Dict[str, Any], now_local: datetime) -> Tuple[Optional[date], Optional[date]]:
    """(the next gathering, a skipped one before it) from now on the
    church's clock. A gathering stays "next" until 4 hours after it starts."""
    if not scheduled(g):
        return None, None
    skips = {str(d)[:10] for d in (g.get("meet_skips") or [])}
    skipped = None
    for i in range(0, 63):
        day = now_local.date() + timedelta(days=i)
        if day.weekday() != int(g["meet_day"]):
            continue
        if starts_at(g, day, now_local.tzinfo) + HERE_AFTER < now_local:
            continue
        if day.isoformat() in skips:
            skipped = skipped or day
            continue
        return day, skipped
    return None, skipped


def can_say_here(g: Dict[str, Any], day: Optional[date], now_local: datetime) -> bool:
    if not day:
        return False
    start = starts_at(g, day, now_local.tzinfo)
    return start - HERE_BEFORE <= now_local <= start + HERE_AFTER


def when_text(g: Dict[str, Any], day: date) -> str:
    t = _time(g)
    clock = t.strftime("%I:%M %p").lstrip("0") if t else ""
    return f"{DAYS[day.weekday()]}, {day.strftime('%B')} {day.day}" + (f" · {clock}" if clock else "")


def regular_text(g: Dict[str, Any]) -> str:
    t = _time(g)
    if not scheduled(g):
        return ""
    return f"{DAYS[int(g['meet_day'])]}s · {t.strftime('%I:%M %p').lstrip('0')}"


# ─── reading ─────────────────────────────────────────────────────────


def _meeting(business_id: str, group_id: str, day: date) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/group_meetings?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}&met_on=eq.{day.isoformat()}"
        f"&select=id,met_on,visitors,notes&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else {}


def _came(business_id: str, meeting_ids: List[str]) -> Optional[List[Dict[str, Any]]]:
    if not meeting_ids:
        return []
    rows = sb_clients.sb_get_as_service(
        f"/group_meeting_attendance?business_id=eq.{_q(business_id)}&meeting_id=in.({','.join(meeting_ids)})"
        f"&select=meeting_id,contact_id,how&limit=20000")
    return rows if isinstance(rows, list) else None


def view(business: Dict[str, Any], g: Dict[str, Any], me_id: str, people: List[Dict[str, Any]],
         now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The Meet tab's data, or None when a read failed (the page says try
    again, never "no gathering")."""
    biz_id = str(business["id"])
    tz = zone(business)
    if tz is None:
        return None
    now_local = (now or _now()).astimezone(tz)
    nxt, skipped = next_on(g, now_local)
    out: Dict[str, Any] = {"next": nxt, "skipped": skipped, "tz": tz, "now": now_local, "rsvps": {},
                           "mine": None, "here": False, "can_here": False, "came": set(), "self_n": 0, "past": []}
    if nxt:
        rows = sb_clients.sb_get_as_service(
            f"/group_rsvps?business_id=eq.{_q(biz_id)}&group_id=eq.{_q(g['id'])}&met_on=eq.{nxt.isoformat()}"
            f"&select=contact_id,answer&limit=5000")
        if not isinstance(rows, list):
            return None
        in_group = {p["id"] for p in people}
        out["rsvps"] = {str(r["contact_id"]): r["answer"] for r in rows if str(r["contact_id"]) in in_group}
        out["mine"] = out["rsvps"].get(str(me_id))
        m = _meeting(biz_id, str(g["id"]), nxt)
        if m is None:
            return None
        if m:
            came = _came(biz_id, [str(m["id"])])
            if came is None:
                return None
            out["came"] = {str(c["contact_id"]) for c in came}
            out["self_n"] = sum(1 for c in came if c.get("how") == "self")
            out["meeting"] = m
        out["here"] = str(me_id) in out["came"]
        out["can_here"] = can_say_here(g, nxt, now_local)
        out["today"] = nxt == now_local.date()
    past = sb_clients.sb_get_as_service(
        f"/group_meetings?business_id=eq.{_q(biz_id)}&group_id=eq.{_q(g['id'])}&met_on=lt.{now_local.date().isoformat()}"
        f"&select=id,met_on,visitors,notes&order=met_on.desc&limit={PAST_SHOWN}")
    if not isinstance(past, list):
        return None
    came = _came(biz_id, [str(m["id"]) for m in past])
    if came is None:
        return None
    for m in past:
        who = {str(c["contact_id"]) for c in came if str(c["meeting_id"]) == str(m["id"])}
        out["past"].append({**m, "n": len(who), "me": str(me_id) in who})
    return out


# ─── writing ─────────────────────────────────────────────────────────


def _member(business_id: str, group_id: str, contact_id: str) -> Optional[Optional[str]]:
    """Their role in the group ('leader' / 'member'), '' when not in it,
    None on a failed read."""
    rows = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}&contact_id=eq.{_q(contact_id)}"
        f"&select=role&limit=1")
    if not isinstance(rows, list):
        return None
    return str(rows[0].get("role") or "member") if rows else ""


def _group(business_id: str, group_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/groups?id=eq.{_q(group_id)}&business_id=eq.{_q(business_id)}&active=eq.true"
        f"&select=id,name,meet_day,meet_time,meet_skips,location&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else {}


def _ready(business: Dict[str, Any], me: Dict[str, Any], group_id: str, *, leader: bool = False):
    """(group, now_local, role) or (None, None, code)."""
    biz_id = str(business["id"])
    g = _group(biz_id, group_id)
    role = _member(biz_id, group_id, me["id"]) if g else ""
    if g is None or role is None:
        return None, None, "error"
    if not g:
        return None, None, "group_gone"
    if not role:
        return None, None, "not_in_group"
    if leader and role != "leader":
        return None, None, "not_group_leader"
    tz = zone(business)
    if tz is None:
        return None, None, "error"
    return g, _now().astimezone(tz), role


def rsvp(business: Dict[str, Any], me: Dict[str, Any], group_id: str, answer: str) -> Tuple[bool, str]:
    if answer not in ANSWERS:
        return False, "error"
    g, now_local, role = _ready(business, me, group_id)
    if not g:
        return False, role
    nxt, _ = next_on(g, now_local)
    if not nxt:
        return False, "no_gathering"
    rows = sb_clients.sb_post_as_service(
        "/group_rsvps?on_conflict=group_id,met_on,contact_id",
        {"business_id": str(business["id"]), "group_id": str(g["id"]), "met_on": nxt.isoformat(),
         "contact_id": str(me["id"]), "answer": answer, "updated_at": datetime.now(timezone.utc).isoformat()},
        prefer="resolution=merge-duplicates,return=representation")
    return (True, f"rsvp_{answer}") if isinstance(rows, list) and rows else (False, "error")


def _meeting_id(business_id: str, group_id: str, day: date) -> Optional[str]:
    """The gathering's group_meetings row, made once."""
    m = _meeting(business_id, group_id, day)
    if m is None:
        return None
    if m:
        return str(m["id"])
    sb_clients.sb_post_as_service(
        "/group_meetings?on_conflict=group_id,met_on",
        {"business_id": business_id, "group_id": group_id, "met_on": day.isoformat()},
        prefer="resolution=ignore-duplicates,return=representation")
    m = _meeting(business_id, group_id, day)
    return str(m["id"]) if m else None


def here(business: Dict[str, Any], me: Dict[str, Any], group_id: str) -> Tuple[bool, str]:
    """"I'm here": counted at today's gathering, in its window only."""
    g, now_local, role = _ready(business, me, group_id)
    if not g:
        return False, role
    nxt, _ = next_on(g, now_local)
    if not can_say_here(g, nxt, now_local):
        return False, "here_closed"
    biz_id = str(business["id"])
    mid = _meeting_id(biz_id, str(g["id"]), nxt)
    if not mid:
        return False, "error"
    rows = sb_clients.sb_post_as_service(
        "/group_meeting_attendance?on_conflict=meeting_id,contact_id",
        {"meeting_id": mid, "contact_id": str(me["id"]), "business_id": biz_id, "how": "self"},
        prefer="resolution=ignore-duplicates,return=representation")
    return (True, "here") if isinstance(rows, list) else (False, "error")


def roll(business: Dict[str, Any], me: Dict[str, Any], group_id: str, present: List[str], visitors: int,
         note: str) -> Tuple[bool, str]:
    """A leader's roll for today's gathering: exactly the people ticked
    (someone who said "I'm here" stays ticked unless the leader unticks
    them), a guest count, and a note for next time."""
    g, now_local, role = _ready(business, me, group_id, leader=True)
    if not g:
        return False, role
    nxt, _ = next_on(g, now_local)
    if not nxt or nxt != now_local.date():
        return False, "roll_closed"
    biz_id = str(business["id"])
    roster = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{_q(biz_id)}&group_id=eq.{_q(g['id'])}&select=contact_id&limit=5000")
    mid = _meeting_id(biz_id, str(g["id"]), nxt)
    if not isinstance(roster, list) or not mid:
        return False, "error"
    members = {str(r["contact_id"]) for r in roster}
    keep = {c for c in present if c in members}
    came = _came(biz_id, [mid])
    if came is None:
        return False, "error"
    had = {str(c["contact_id"]) for c in came}
    gone = sorted(had - keep)
    if gone:
        if not sb_clients.sb_delete_as_service(
                f"/group_meeting_attendance?business_id=eq.{_q(biz_id)}&meeting_id=eq.{_q(mid)}&contact_id=in.({','.join(gone)})"):
            return False, "error"
    new = sorted(keep - had)
    if new:
        rows = sb_clients.sb_post_as_service(
            "/group_meeting_attendance?on_conflict=meeting_id,contact_id",
            [{"meeting_id": mid, "contact_id": c, "business_id": biz_id, "how": "leader"} for c in new],
            prefer="resolution=ignore-duplicates,return=representation")
        if not isinstance(rows, list):
            return False, "error"
    patch: Dict[str, Any] = {"visitors": max(0, min(int(visitors or 0), 500)), "updated_at": datetime.now(timezone.utc).isoformat()}
    if note.strip():
        patch["notes"] = note.strip()[:ROLL_NOTE_MAX]
    saved = sb_clients.sb_patch_as_service(f"/group_meetings?id=eq.{_q(mid)}&business_id=eq.{_q(biz_id)}", patch)
    return (True, "roll_saved") if isinstance(saved, list) and saved else (False, "error")


def set_schedule(business: Dict[str, Any], me: Dict[str, Any], group_id: str, day: str, at: str,
                 address: str, note: str) -> Tuple[bool, str]:
    """A leader sets the regular gathering (or clears it with no day)."""
    g, _, role = _ready(business, me, group_id, leader=True)
    if not g:
        return False, role
    body: Dict[str, Any] = {"meet_address": " ".join(address.split())[:ADDRESS_MAX],
                            "meet_note": " ".join(note.split())[:NOTE_MAX], "updated_at": datetime.now(timezone.utc).isoformat()}
    if day == "":
        body.update(meet_day=None, meet_time=None)
    else:
        try:
            d = int(day)
            t = time.fromisoformat(at[:5]) if at else None
        except ValueError:
            return False, "schedule_bad"
        if not 0 <= d <= 6 or t is None:
            return False, "schedule_bad"
        body.update(meet_day=d, meet_time=t.strftime("%H:%M"))
    saved = sb_clients.sb_patch_as_service(
        f"/groups?id=eq.{_q(g['id'])}&business_id=eq.{_q(business['id'])}", body)
    return (True, "schedule_saved") if isinstance(saved, list) and saved else (False, "error")


def skip(business: Dict[str, Any], me: Dict[str, Any], group_id: str, day: str, on: bool) -> Tuple[bool, str]:
    """A leader skips one gathering (or brings it back)."""
    g, now_local, role = _ready(business, me, group_id, leader=True)
    if not g:
        return False, role
    try:
        d = date.fromisoformat(day[:10])
    except ValueError:
        return False, "error"
    if d < now_local.date():
        return False, "error"
    skips = {str(x)[:10] for x in (g.get("meet_skips") or [])}
    keep = sorted(x for x in skips if x >= now_local.date().isoformat())   # old skips fall away
    keep = sorted(set(keep) | {d.isoformat()}) if on else [x for x in keep if x != d.isoformat()]
    saved = sb_clients.sb_patch_as_service(
        f"/groups?id=eq.{_q(g['id'])}&business_id=eq.{_q(business['id'])}", {"meet_skips": keep})
    return (True, "skipped" if on else "unskipped") if isinstance(saved, list) and saved else (False, "error")


# ─── the reminder (member_push.sweep_tick) ───────────────────────────


def remind_day(g: Dict[str, Any], day: date) -> date:
    """5 PM on the day of an evening gathering; the day before otherwise."""
    return day if (_time(g) or EVENING) >= EVENING else day - timedelta(days=1)


def reminders(business: Dict[str, Any], now: Optional[datetime] = None) -> int:
    """At 5 PM on the church's clock: each gathering whose reminder is due,
    to its people who haven't said they can't come. Once (ref_id)."""
    import member_push
    tz = zone(business)
    if tz is None:
        return 0
    now_local = (now or _now()).astimezone(tz)
    if now_local.hour != REMIND_AT:
        return 0
    groups = sb_clients.sb_get_as_service(
        f"/groups?business_id=eq.{_q(business['id'])}&active=eq.true&meet_day=not.is.null"
        f"&select=id,name,meet_day,meet_time,meet_skips,location&limit=500")
    if not isinstance(groups, list):
        return 0
    sent = 0
    for g in groups:
        for ahead in (0, 1):
            day = now_local.date() + timedelta(days=ahead)
            if not scheduled(g) or day.weekday() != int(g["meet_day"]) or remind_day(g, day) != now_local.date():
                continue
            if day.isoformat() in {str(x)[:10] for x in (g.get("meet_skips") or [])}:
                continue
            members = sb_clients.sb_get_as_service(
                f"/group_members?business_id=eq.{_q(business['id'])}&group_id=eq.{_q(g['id'])}&select=contact_id&limit=5000")
            noes = sb_clients.sb_get_as_service(
                f"/group_rsvps?business_id=eq.{_q(business['id'])}&group_id=eq.{_q(g['id'])}&met_on=eq.{day.isoformat()}"
                f"&answer=eq.no&select=contact_id&limit=5000")
            if not isinstance(members, list) or not isinstance(noes, list):
                continue
            who = sorted({str(r["contact_id"]) for r in members} - {str(r["contact_id"]) for r in noes})
            if not who:
                continue
            t = _time(g)
            clock = t.strftime("%I:%M %p").lstrip("0") if t else ""
            when = ("Tonight" if ahead == 0 else "Tomorrow") + (f" at {clock}" if clock else "")
            body = when + (f" · {g['location']}" if g.get("location") else "")
            sent += member_push.send(business, "groups", title=str(g.get("name") or "Your group"), body=body,
                                     url=f"/my/groups/{g['id']}/meet", contact_ids=who,
                                     ref_id=f"gathering:{g['id']}:{day.isoformat()}", tag=f"gathering-{g['id']}")
    return sent


# ─── the Meet tab ────────────────────────────────────────────────────

MEET_CSS = """
.gm-next{display:flex;flex-direction:column;gap:12px;}
.gm-kick{font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--teal-ink,var(--acc));}
.gm-when{margin:0;font-size:22px;font-weight:700;letter-spacing:-.02em;line-height:1.2;}
.gm-where{display:flex;gap:10px;align-items:flex-start;margin:0;font-size:15px;color:var(--fg2);line-height:1.4;}
.gm-where .mb-ic{flex:none;margin-top:2px;color:var(--fg3);}
.gm-where a{color:var(--teal-ink,var(--acc));font-weight:650;text-decoration:none;}
.gm-note{margin:0;padding:10px 12px;border-radius:var(--r-md);background:var(--s2);font-size:14px;line-height:1.4;color:var(--fg2);}
.gm-note b{color:var(--fg);}
.gm-rsvp{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:0;}
.gm-rsvp button{min-height:44px;border-radius:999px;border:0;background:var(--s2);color:var(--fg);font:inherit;font-size:14px;font-weight:650;
  cursor:pointer;box-shadow:inset 0 0 0 1px var(--line);}
.gm-rsvp button[aria-pressed=true]{background:var(--teal-deep);color:var(--teal-ink);box-shadow:inset 0 0 0 1.5px var(--teal-ink,var(--acc));}
.gm-count{display:flex;align-items:center;gap:8px;margin:0;font-size:13.5px;color:var(--fg2);}
.gm-count .gs-faces .gs-av{width:24px;height:24px;font-size:9.5px;}
.gm-fine{margin:0;font-size:12.5px;color:var(--fg3);}
.gm-here{display:flex;align-items:center;gap:14px;}
.gm-here .gs-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.gm-here .gs-t span{font-size:13px;color:var(--fg2);}
.gm-done{display:flex;align-items:center;gap:10px;color:var(--teal-ink,var(--acc));font-weight:650;}
.gm-roll{display:flex;flex-direction:column;gap:8px;}
.gm-roll-list{display:flex;flex-direction:column;gap:2px;margin:0;padding:0;list-style:none;}
.gm-roll-list label{display:flex;align-items:center;gap:12px;min-height:48px;padding:4px 2px;cursor:pointer;}
.gm-roll-list input{width:22px;height:22px;flex:none;margin:0;accent-color:var(--teal);}
.gm-roll-list .gs-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px;}
.gm-roll-list small{font-size:12px;color:var(--fg3);}
.gm-row{display:flex;gap:10px;flex-wrap:wrap;}
.gm-row label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--fg2);flex:1;min-width:120px;}
.gm-row input,.gm-row select,.gm-roll textarea{min-height:44px;border:0;outline:none;border-radius:var(--r-md);background:var(--s2);color:var(--fg);
  padding:0 12px;font:inherit;font-size:15px;box-shadow:inset 0 0 0 1px var(--line);}
.gm-roll textarea{padding:10px 12px;min-height:70px;}
.gm-past{display:flex;flex-direction:column;gap:2px;}
.gm-past-row{display:flex;align-items:center;gap:14px;padding:10px 2px;border-bottom:.5px solid var(--line);}
.gm-date{width:46px;flex:none;display:flex;flex-direction:column;align-items:center;line-height:1;}
.gm-date small{font-size:11px;font-weight:700;letter-spacing:.08em;color:var(--fg3);}
.gm-date b{font-size:20px;font-weight:700;}
.gm-past-row .gs-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.gm-past-row .gs-t span{font-size:13px;color:var(--fg2);}
.gm-you{font-size:12px;font-weight:700;color:var(--teal-ink,var(--acc));}
.gm-set summary{list-style:none;cursor:pointer;}
.gm-set summary::-webkit-details-marker{display:none;}
.gm-set form{display:flex;flex-direction:column;gap:10px;margin-top:12px;}
"""


def render_tab(biz: Dict[str, Any], g: Dict[str, Any], v: Optional[Dict[str, Any]], *, me_id: str, leader: bool,
               people: List[Dict[str, Any]], live: Optional[Dict[str, Any]], ic, face, esc, name) -> str:
    """The Meet tab's html. `ic`, `face`, `esc`, `name` are the group page's
    helpers (icons, avatars, escaping, names the way the group shows them)."""
    gid = esc(g["id"])
    if v is None:
        return '<p class="mp-err" role="alert">Gatherings couldn’t load just now. Please try again in a moment.</p>'
    parts: List[str] = []
    nxt = v.get("next")
    hidden = f'<input type="hidden" name="group_id" value="{gid}">'
    lead_names = [name(p) for p in people if p.get("role") == "leader"]
    if nxt:
        kick = "Today" if v.get("today") else ("This week" if (nxt - v["now"].date()).days < 7 else "Next")
        where = []
        if g.get("location") or g.get("meet_address"):
            addr = g.get("meet_address") or ""
            maps = (f' · <a href="https://www.google.com/maps/search/?api=1&query={_q(addr)}" target="_blank" rel="noopener">Directions</a>'
                    if addr else "")
            where.append(f'<p class="gm-where">{ic("pin", 18)}<span>{esc(" · ".join(x for x in (g.get("location"), addr) if x))}{maps}'
                         f'{"<br><small class=gm-fine>The street address shows only to the group.</small>" if addr else ""}</span></p>')
        note = (f'<p class="gm-note"><b>From your leaders:</b> {esc(g["meet_note"])}</p>' if g.get("meet_note") else "")
        mine = v.get("mine")
        buttons = "".join(
            f'<button type="submit" name="answer" value="{a}" aria-pressed="{"true" if mine == a else "false"}">{label}</button>'
            for a, label in (("going", "Going"), ("maybe", "Maybe"), ("no", "Can’t make it")))
        rs = v.get("rsvps") or {}
        going = [p for p in people if rs.get(p["id"]) == "going"]
        maybe = sum(1 for a in rs.values() if a == "maybe")
        others = len([p for p in going if p["id"] != me_id])
        if mine == "going":
            count = "You" + (f" and {others} other{'s' if others != 1 else ''}" if others else "")
        else:
            count = f"{len(going)} going" if going else "No one has said yet"
        if maybe:
            count += f" · {maybe} maybe"
        faces = "".join(face(p) for p in going[:4])
        when = when_text(g, nxt)
        skipped = (f'<p class="gm-fine">No gathering {esc(when_text(g, v["skipped"]).split(" · ")[0])}.</p>'
                   if v.get("skipped") and v["skipped"] < nxt else "")
        remind = remind_day(g, nxt)
        remind_line = "A reminder comes at 5 PM" + ("" if remind == nxt else " the day before")
        parts.append(
            f'<section class="gs-card gm-next" aria-labelledby="gm-when"><span class="gm-kick">{kick}</span>'
            f'<h2 class="gm-when" id="gm-when">{esc(when)}</h2>{skipped}{"".join(where)}{note}'
            f'<form class="gm-rsvp" method="post" action="/my/groups/meet/rsvp" aria-label="Are you coming?">{hidden}{buttons}</form>'
            f'<p class="gm-count">{f"<span class=gs-faces aria-hidden=true>{faces}</span>" if faces else ""}{esc(count)}</p>'
            f'<p class="gm-fine">{remind_line}.</p></section>')
        if v.get("today"):
            # On the day, being counted comes first.
            if v.get("here"):
                parts.insert(0, f'<section class="gs-card"><p class="gm-done">{ic("check", 20)}You’re counted. Welcome!</p></section>')
            elif v.get("can_here"):
                parts.insert(0, f'<section class="gs-card gm-here"><span class="gs-t"><b>Made it?</b>'
                             f'<span>It counts toward your attendance, like Sunday check-in.</span></span>'
                             f'<form method="post" action="/my/groups/meet/here">{hidden}'
                             f'<button class="gs-btn" type="submit">{ic("check", 16)}I’m here</button></form></section>')
            else:
                by = f" {esc(lead_names[0])} can also mark you." if lead_names else ""
                parts.append(f'<p class="gs-note">{ic("clock", 15)}<span>“I’m here” opens 30 minutes before.{by}</span></p>')
    elif scheduled(g):
        parts.append('<p class="gs-empty">No gathering is coming up right now.</p>')
    else:
        lead = "Set when you meet below, and everyone can say if they’re coming." if leader else \
            "Your leaders will share when you meet."
        parts.append(f'<p class="gs-empty">No regular time yet. {lead}</p>')
    if live:
        parts.append(f'<a class="gs-btn tint sm" href="/my/groups/live/{esc(live["id"])}">{ic("video", 15)}Join on video</a>')
    if leader and nxt and v.get("today"):
        came = v.get("came") or set()
        rs = v.get("rsvps") or {}
        rows = "".join(
            f'<li><label><input type="checkbox" name="here" value="{esc(p["id"])}"{" checked" if p["id"] in came else ""}>'
            f'{face(p)}<span class="gs-t"><b>{esc(name(p))}</b>'
            f'<small>{"Checked themselves in" if p["id"] in came else {"going": "Said going", "maybe": "Said maybe", "no": "Said they can’t"}.get(rs.get(p["id"]), "")}</small>'
            f'</span></label></li>'
            for p in sorted(people, key=lambda x: ({"going": 0, "maybe": 1}.get(rs.get(x["id"]), 2), name(x).lower())))
        m = v.get("meeting") or {}
        parts.append(
            f'<section class="gs-card gm-roll" aria-labelledby="gm-roll"><h2 id="gm-roll" style="margin:0;font-size:17px">Take attendance</h2>'
            f'<p class="gm-fine">{len(came)} here so far · {v.get("self_n", 0)} checked themselves in</p>'
            f'<form method="post" action="/my/groups/meet/roll" class="gm-roll">{hidden}<ul class="gm-roll-list">{rows}</ul>'
            f'<div class="gm-row"><label>Guests<input type="number" name="visitors" min="0" max="500" inputmode="numeric" value="{int(m.get("visitors") or 0)}"></label></div>'
            f'<label class="mp-sr" for="gm-note">A note for next time</label>'
            f'<textarea id="gm-note" name="note" maxlength="{ROLL_NOTE_MAX}" placeholder="A note for next time (only leaders and the office see it)">{esc(m.get("notes") or "")}</textarea>'
            f'<button class="gs-btn" type="submit">Save attendance</button>'
            f'<p class="gm-fine">It counts toward each person’s attendance, the same as Sunday check-in.</p></form></section>')
    if leader:
        days = "".join(f'<option value="{i}"{" selected" if g.get("meet_day") is not None and int(g["meet_day"]) == i else ""}>{d}</option>'
                       for i, d in enumerate(DAYS))
        t = _time(g)
        skip_form = ""
        if nxt:
            skip_form = (f'<form method="post" action="/my/groups/meet/skip">{hidden}<input type="hidden" name="day" value="{nxt.isoformat()}">'
                         f'<input type="hidden" name="on" value="1"><button class="gs-mini" type="submit">Skip {esc(when_text(g, nxt).split(" · ")[0])}</button></form>')
        parts.append(
            f'<details class="gs-card gm-set"><summary class="gs-ph"><span class="gs-t"><b>When and where you meet</b>'
            f'<small>{esc(regular_text(g) or "Not set yet")}</small></span>{ic("chevron", 18)}</summary>'
            f'<form method="post" action="/my/groups/meet/schedule">{hidden}<div class="gm-row">'
            f'<label>Day<select name="day"><option value="">No regular time</option>{days}</select></label>'
            f'<label>Time<input type="time" name="time" value="{t.strftime("%H:%M") if t else ""}"></label></div>'
            f'<div class="gm-row"><label>Street address (only the group sees it)'
            f'<input type="text" name="address" maxlength="{ADDRESS_MAX}" value="{esc(g.get("meet_address") or "")}" autocomplete="street-address"></label></div>'
            f'<div class="gm-row"><label>Directions or a note<input type="text" name="note" maxlength="{NOTE_MAX}" value="{esc(g.get("meet_note") or "")}" '
            f'placeholder="Park on Maple, ring the side door"></label></div>'
            f'<button class="gs-btn soft sm" type="submit">Save</button></form>{skip_form}</details>')
    past = v.get("past") or []
    if past:
        rows = "".join(_past_row(m, leader, esc) for m in past)
        parts.append(f'<div class="mb-sh"><h2>Before</h2></div><div class="gm-past">{rows}</div>')
    return "".join(parts)


def _past_row(m: Dict[str, Any], leader: bool, esc) -> str:
    """One gathering that happened: how many came; its note for leaders."""
    day = date.fromisoformat(str(m["met_on"])[:10])
    guests = int(m.get("visitors") or 0)
    came = f"{m['n']} came"
    if guests:
        came += f" · {guests} guest" + ("s" if guests > 1 else "")
    note = f"<span>{esc(m['notes'])}</span>" if leader and m.get("notes") else ""
    you = '<span class="gm-you">You were there</span>' if m.get("me") else ""
    return (f'<div class="gm-past-row"><span class="gm-date"><small>{day.strftime("%b").upper()}</small><b>{day.day}</b></span>'
            f'<span class="gs-t"><b>{came}</b>{note}</span>{you}</div>')
