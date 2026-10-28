"""member_portal_lead.py — the Lead tab: a leader's side of a member page.

Kevin, 2026-10-17: leaders "see assigned work that chief gives, make
comments from conversations they had with members". They are members first,
so it lives in the member page they already sign in to (a code, no
password), as a Lead tab; on a computer the list and the person sit side by
side (design canvas LG4Q97HqtEM4ByyXmmSrCP, boards 3-6).

    GET  /my/lead                 my people (and an invitation to answer)
    GET  /my/lead/<follow_up_id>  one person: the card, the path, the notes
    GET  /my/lead/prayer          prayer requests handed to me (role library,
                                  canvas BKNqVVNiyxfAGAa7UAVWUC board 7)
    POST /my/lead/answer          yes or not now to a role
    POST /my/lead/note            log a conversation
    POST /my/lead/step            mark the current step done
    POST /my/lead/handback        hand them back to the office
    POST /my/lead/prayer/prayed | note | pass   I prayed, send a note, pass on
    GET  /my/lead/families        the families a pastor or elder shepherds
                                  (church_shepherding; canvas
                                  31su6kdYmYecH5b2NxjBJN boards 6-7)
    GET  /my/lead/family/<id>     one family: who's in it, log a touch
    GET  /my/lead/sundays         a Sunday team's leader schedules their team
                                  (member_portal_leading; ChurchSavvy Planning)
    POST /my/lead/family/<id>/touch   a call, a visit, a text or a talk at
                                  church, and "needs a pastor"
    GET  /my/lead/tasks           the tasks the office handed to me (My tasks
                                  for leaders, church_leader_tasks)
    POST /my/lead/tasks/<id>/done mark one done

A leader only ever sees the follow-ups handed to them (church_follow_up
checks every read and write against leader_contact_id), and never another
person's pastors-only note. Prayer: only requests the person shared with the
prayer team and that were handed to them (church_prayer), a first name, and
how to reach them only when they asked for a call. A shepherd sees only
the families given to them: the adults by name, a child by first name and
age, never giving, prayer kept for the pastors or a child's care notes. A
leader sees only the tasks handed to them (church_leader_tasks checks every
read and write against the church and their contact id). The owner's
preview reads and never writes.
"""
from __future__ import annotations

import asyncio
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

import church_follow_up as cfu

logger = logging.getLogger(__name__)
router = APIRouter()

_FID = re.compile(r"^[0-9a-fA-F-]{36}$")
# Whether this leader leads a Sunday team (sunday_leading): read once per
# request in serve(), so every page's section switcher can offer Sundays.
SUNDAYS: ContextVar[bool] = ContextVar("lead_sundays", default=False)
# Who sees what (2026-10-26): the other parts this member holds, read once per
# request in serve() when the tab is the Serve tab, so every page's section
# switcher can offer them: their Sundays (sunday_serving) and a kids room.
PARTS: ContextVar[Dict[str, Any]] = ContextVar("lead_parts", default={})
# Get paid back (church_checks, 2026-10-27): its door, set once per request
# in serve() where the switch shows it. Whoever reaches the tab serves.
PAID_BACK: ContextVar[str] = ContextVar("lead_paid_back", default="")
# My tasks for leaders (church_leader_tasks, 2026-10-27): {"open": n} when
# this member has tasks the office handed them, read once per request in
# serve(), so every page's section switcher can offer Tasks; None when not.
TASKS: ContextVar[Optional[Dict[str, int]]] = ContextVar("lead_tasks", default=None)


def _word() -> str:
    """The tab's name, said in its header: Serve once Who sees what is on."""
    import member_app_ui
    return "Serve" if member_app_ui.serve_mode() else "Lead"


def parts(biz: Dict[str, Any], me_id: str, email: Optional[str] = None) -> Dict[str, Any]:
    """The parts besides a role or a group: a place on a Sunday team (or an
    ask), a kids room (space_leaders), and a part on ChurchSavvy's Sunday
    team (`team`: booth, media, worship, planner, by the email the church
    has for them). A read that fails is no part."""
    out: Dict[str, Any] = {"serving": False, "kids": False, "team": team_parts(biz, email)}
    try:
        import sunday_serving
        out["serving"] = bool(sunday_serving.serves(biz, me_id))
    except Exception:
        logger.warning("serve tab: serving read failed (business %s)", str(biz.get("id"))[:8])
    try:
        import sb_clients
        rows = sb_clients.sb_get_as_service(
            f"/space_leaders?business_id=eq.{cfu._q(biz['id'])}&contact_id=eq.{cfu._q(me_id)}&select=contact_id&limit=1")
        out["kids"] = bool(isinstance(rows, list) and rows)
    except Exception:
        logger.warning("serve tab: kids read failed (business %s)", str(biz.get("id"))[:8])
    return out

# ChurchSavvy's Sunday team (worship_team.ROLES), said as the work.
SAVVY_WORK = {"booth": "the screens", "media": "sermons, live and clips", "worship": "the songs",
              "planner": "the order of service", "admin": "the team and the screens"}


def team_parts(biz: Dict[str, Any], email: Optional[str]) -> List[str]:
    """Their parts on ChurchSavvy's Sunday team, while ChurchSavvy is on for
    every church (WORSHIP_SONGS=on). A read that fails is no part.

    By email, the only key: a member is a church contact, not a sign-in, so
    worship_team.user_id (their ChurchSavvy sign-in) has nothing to meet.
    The member app proves the email with a code. What it can reveal is the
    part in words, on a door that only links out."""
    import worship_router
    em = (email or "").strip().lower()
    if worship_router.mode() != "on" or "@" not in em:
        return []
    try:
        import sb_clients
        import church_areas
        rows = sb_clients.sb_get_as_service(
            f"/worship_team?business_id=eq.{cfu._q(biz['id'])}&email=ilike.{cfu._q(church_areas._escape_ilike(em))}"
            "&status=eq.active&select=roles&limit=1")
    except Exception:
        rows = None
    if not isinstance(rows, list):
        logger.warning("serve tab: team read failed (business %s)", str(biz.get("id"))[:8])
        return []
    have = set((rows[0].get("roles") or []) if rows else [])
    return [p for p in SAVVY_WORK if p in have]


def savvy_door(team: List[str]) -> str:
    """ChurchSavvy's door, for someone on its Sunday team. It opens in its
    own app with the same email; nothing here changes what they can do."""
    if not team:
        return ""
    import churchsavvy_billing
    from member_app_ui import icon
    title = "Open the booth" if "booth" in team else "Open ChurchSavvy"
    work = _and([SAVVY_WORK[p] for p in team])
    return (f'<a class="sf-door" href="{_e(churchsavvy_billing.app_url())}">{icon("video", 20)}'
            f'<span><b>{title}</b><small>Your part on Sunday: {_e(work)}</small></span>{icon("chevron", 18)}</a>')


DONE = {
    "saved": "Saved. The pastors can see it on their page.",
    "step": "Step done.",
    "finished": "That’s the whole path. Thank you.",
    "back": "Handed back to the office.",
    "yes": "You’re leading now. People Chief hands to you show up here.",
    "no": "Got it. Nothing changes for you.",
    "prayed": "Thank you for praying.",
    "noted": "Your note is on its way.",
    "passed": "Passed on. They’ll pray over it today.",
    "touched": "Saved. The pastors can read it.",
    "pastor": "Saved. The Lead Pastor has been told.",
    "pastor_unsent": "Saved, but no pastor could be emailed. Please tell the office.",
    "task_done": "Done. The church office can see it.",
}
ERRORS = {
    "error": "That didn’t save. Please try again.",
    "slow": "That was a lot at once. Wait a moment, then try again.",
    "preview": "This is a preview. Nothing is saved.",
    "gone": "That person isn’t handed to you anymore.",
    "prayer_gone": "That request isn’t handed to you anymore.",
    "noemail": "They left no email, so a note can’t be sent.",
    "family_gone": "That family isn’t yours to shepherd anymore.",
    "task_gone": "That task isn’t handed to you anymore.",
}

LEAD_CSS = """
body:has(.ld-wide) .mb-top,body:has(.ld-wide) .mp-shell{max-width:1180px;}
/* From 1100px the tab bar is a 92px rail on the left: a wide page starts
   after it instead of under it (centred once there's room). */
@media (min-width:1100px){body:has(.ld-wide) .mp-shell.mb-has-nav,body:has(.mb-has-nav .ld-wide) .mb-top{margin-left:max(92px,calc((100vw - 1180px) / 2));margin-right:auto;}}
.ld-head{display:flex;align-items:flex-end;flex-wrap:wrap;gap:10px 14px;margin:6px 0 16px;}
.ld-hello{margin:0;font-size:34px;font-weight:750;letter-spacing:-.035em;line-height:1.05;}
.ld-hello em{font-family:var(--mb-serif);font-style:italic;font-weight:500;color:var(--acc);}
.ld-roles{display:flex;flex-wrap:wrap;gap:6px;}
.ld-role{display:inline-flex;align-items:center;min-height:30px;padding:0 12px;border-radius:999px;background:var(--mb-soft);
  border:.5px solid var(--mb-soft-line);color:var(--fg);font-size:12.5px;font-weight:600;}
.ld-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:18px;align-items:start;}
.ld-list,.ld-file{display:flex;flex-direction:column;gap:12px;min-width:0;}
.ld-grid.has-sel .ld-list,.ld-grid:not(.has-sel) .ld-file{display:none;}
@media (min-width:1000px){
  .ld-grid{grid-template-columns:340px minmax(0,1fr);}
  .ld-grid.has-sel .ld-list,.ld-grid:not(.has-sel) .ld-file{display:flex;}
  .ld-p[data-shown]{background:var(--s2);box-shadow:inset 0 0 0 1.5px var(--acc);}
}
.ld-card{background:var(--s1);border-radius:var(--r-lg);padding:16px 18px;display:flex;flex-direction:column;gap:12px;}
.ld-card h2,.ld-card h3{margin:0;font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--fg3);}
.ld-chief{background:var(--s1);border-radius:var(--r-md);padding:14px 16px;}
.ld-chief small{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--acc);}
.ld-chief p{margin:6px 0 0;font-size:15px;line-height:1.45;}
.ld-p{display:flex;align-items:center;gap:12px;padding:12px;border-radius:var(--r-md);background:var(--s1);min-height:66px;
  text-decoration:none;color:var(--fg);box-sizing:border-box;}
.ld-p[aria-current]{background:var(--s2);box-shadow:inset 0 0 0 1.5px var(--acc);}
.ld-av{width:44px;height:44px;border-radius:50%;display:grid;place-items:center;font-weight:700;font-size:14px;background:var(--s3);flex:none;}
.ld-av.new{background:var(--mb-fill);color:var(--mb-on-fill);}
.ld-p .t{display:flex;flex-direction:column;min-width:0;flex:1;}
.ld-p .t b{font-size:16px;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.ld-p .t small{font-size:13px;color:var(--fg2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.ld-due{font-size:12.5px;font-weight:650;color:var(--fg2);text-align:right;white-space:nowrap;}
.ld-due.late{color:#ff8a5c;}.ld-due.soon{color:var(--acc);}.ld-due.new{color:#5fd08a;}
.ld-quiet{margin:2px 2px 0;font-size:13px;color:var(--fg3);display:flex;gap:8px;align-items:flex-start;}
.ld-done{display:flex;align-items:center;gap:10px;padding:12px 14px;border-radius:var(--r-md);background:rgba(95,208,138,.1);font-size:14px;}
.ld-person{display:flex;align-items:center;gap:14px;flex-wrap:wrap;}
.ld-person .ld-av{width:60px;height:60px;font-size:19px;background:var(--mb-fill);color:var(--mb-on-fill);}
.ld-person h2{margin:0;font-size:30px;font-weight:750;letter-spacing:-.03em;line-height:1.05;}
.ld-person small{display:block;font-size:13px;color:var(--fg2);margin-top:3px;}
.ld-reach{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px;}
.ld-reach a{display:flex;flex-direction:column;align-items:center;gap:4px;padding:12px 0;border-radius:var(--r-md);background:var(--s1);
  font-size:13px;font-weight:600;color:var(--fg);text-decoration:none;}
.ld-why{margin:0;font-size:14px;color:var(--fg2);}
.ld-why b{color:var(--fg);font-weight:600;}
.ld-steps{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;}
.ld-steps li{display:flex;gap:12px;align-items:flex-start;padding:7px 0;}
.ld-dot{width:22px;height:22px;border-radius:50%;flex:none;display:grid;place-items:center;border:2px solid var(--s3);box-sizing:border-box;margin-top:1px;}
.ld-dot.done{background:#5fd08a;border-color:#5fd08a;color:#000;}
.ld-dot.now{border-color:var(--acc);}
.ld-steps b{display:block;font-size:15px;font-weight:650;}
.ld-steps small{display:block;font-size:13px;color:var(--fg2);}
.ld-btn{display:flex;align-items:center;justify-content:center;gap:8px;min-height:50px;border:0;border-radius:999px;background:var(--mb-fill);
  color:var(--mb-on-fill);font:inherit;font-weight:650;font-size:15.5px;width:100%;cursor:pointer;}
.ld-ghost{display:flex;align-items:center;justify-content:center;min-height:48px;border:0;border-radius:999px;background:var(--s2);
  color:var(--fg);font:inherit;font-weight:600;font-size:14.5px;width:100%;cursor:pointer;}
.ld-chips{display:flex;flex-wrap:wrap;gap:8px;border:0;padding:0;margin:0;}
.ld-chips legend{font-size:13px;color:var(--fg2);margin-bottom:8px;padding:0;}
.ld-chips label{position:relative;}
.ld-chips input{position:absolute;opacity:0;width:1px;height:1px;}
.ld-chips span{display:inline-flex;align-items:center;min-height:40px;padding:0 14px;border-radius:999px;background:var(--s2);
  font-size:14px;font-weight:600;color:var(--fg2);cursor:pointer;}
.ld-chips input:checked + span{background:var(--fg);color:var(--bg);}
.ld-chips input:focus-visible + span{outline:2px solid var(--acc);outline-offset:2px;}
.ld-ta{width:100%;min-height:104px;border-radius:var(--r-sm);border:.5px solid var(--line);background:var(--s2);color:var(--fg);
  padding:12px 14px;box-sizing:border-box;resize:vertical;font:inherit;font-size:16px;line-height:1.45;}
.ld-check{display:flex;align-items:center;gap:10px;min-height:44px;font-size:14.5px;color:var(--fg2);}
.ld-check input{width:20px;height:20px;accent-color:var(--mb-fill);}
.ld-ans{margin:0;display:grid;grid-template-columns:minmax(0,1fr);gap:10px;}
@media (min-width:1000px){.ld-ans{grid-template-columns:repeat(2,minmax(0,1fr));}}
.ld-ans div{display:flex;flex-direction:column;gap:1px;}
.ld-ans dt{font-size:12.5px;color:var(--fg3);}
.ld-ans dd{margin:0;font-size:15px;}
.ld-notes{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:10px;}
.ld-notes li{background:var(--s2);border-radius:var(--r-sm);padding:12px 14px;}
.ld-by{display:flex;align-items:center;flex-wrap:wrap;gap:8px;font-size:12.5px;color:var(--fg3);margin-bottom:4px;}
.ld-by b{color:var(--fg);font-weight:650;}
.ld-tag{font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;background:var(--s3);color:var(--fg2);}
.ld-notes p{margin:0;font-size:15px;line-height:1.5;white-space:pre-line;}
.ld-invite{background:var(--s1);border-radius:var(--r-lg);padding:18px;display:flex;flex-direction:column;gap:12px;margin-bottom:16px;}
.ld-invite h2{margin:0;font-size:24px;font-weight:750;letter-spacing:-.025em;line-height:1.15;}
.ld-invite h2 em{font-family:var(--mb-serif);font-style:italic;font-weight:500;color:var(--acc);}
.ld-invite p{margin:0;color:var(--fg2);font-size:15px;}
.ld-two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px;}
.ld-back summary{list-style:none;cursor:pointer;}
.ld-back summary::-webkit-details-marker{display:none;}
.ld-back[open] summary{margin-bottom:10px;}
.ld-seg{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);gap:4px;padding:4px;border-radius:14px;background:var(--s1);margin:0 0 16px;max-width:420px;}
.ld-seg a{display:flex;align-items:center;justify-content:center;min-height:42px;border-radius:10px;font-size:14.5px;font-weight:600;
  color:var(--fg2);text-decoration:none;}
.ld-seg a[aria-current]{background:var(--s3);color:var(--fg);}
.ld-prs{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;max-width:760px;}
@media (min-width:1000px){.ld-prs{grid-template-columns:repeat(2,minmax(0,1fr));max-width:none;}}
.ld-pr{background:var(--s1);border-radius:var(--r-lg);padding:16px;display:flex;flex-direction:column;gap:10px;}
.ld-pr-who{display:flex;align-items:center;gap:12px;}
.ld-pr-who .t{display:flex;flex-direction:column;min-width:0;flex:1;}
.ld-pr-who .t b{font-size:16px;font-weight:650;}
.ld-pr-who .t small{font-size:12.5px;color:var(--fg3);}
.ld-pr-text{margin:0;font-family:var(--mb-serif);font-size:19px;line-height:1.4;white-space:pre-line;}
.ld-pr-tags{display:flex;flex-wrap:wrap;gap:6px;}
.ld-pr-acts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}
.ld-pr-acts form{display:contents;}
.ld-pr-acts .ld-btn,.ld-pr-acts .ld-ghost{min-height:46px;font-size:14.5px;}
.ld-pr-acts .ld-said{display:flex;align-items:center;justify-content:center;gap:6px;min-height:46px;border-radius:999px;
  background:rgba(95,208,138,.12);color:#5fd08a;font-weight:650;font-size:14.5px;}
.ld-pr .ld-quiet{margin:0;}
.ld-pass{display:flex;gap:8px;flex-wrap:wrap;align-items:center;}
.ld-pass select{flex:1 1 180px;min-height:44px;border-radius:12px;border:.5px solid var(--line);background:var(--s2);color:var(--fg);
  padding:0 12px;font:inherit;font-size:15px;}
.ld-pass .ld-ghost{width:auto;padding:0 18px;}
"""


def _e(s: Any) -> str:
    from member_portal import _e as esc
    return esc(s)


def _tz(biz: Dict[str, Any]):
    from zoneinfo import ZoneInfo
    s = (biz.get("settings") or {}) if isinstance(biz.get("settings"), dict) else {}
    name = (s.get("timezone") or ((s.get("availability") or {}) if isinstance(s.get("availability"), dict) else {}).get("timezone")
            or "America/New_York")
    try:
        return ZoneInfo(str(name))
    except Exception:
        return ZoneInfo("America/New_York")


def _day(ts: Any, biz: Dict[str, Any]) -> str:
    dt = cfu._parse(ts)
    if not dt:
        return ""
    local = dt.astimezone(_tz(biz))
    return local.strftime("%a %b ") + str(local.day)


def due_label(item: Dict[str, Any], biz: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, str]:
    """{text, cls} for when the current step is due."""
    now = now or datetime.now(timezone.utc)
    due = cfu._parse(item.get("due_at"))
    if not due:
        return {"text": "", "cls": "ld-due"}
    tz = _tz(biz)
    days = (due.astimezone(tz).date() - now.astimezone(tz).date()).days
    if due < now:
        late = max(1, (now.astimezone(tz).date() - due.astimezone(tz).date()).days)
        return {"text": "Due today" if late == 0 else f"{late} day{'s' if late != 1 else ''} late", "cls": "ld-due late"}
    if days <= 0:
        return {"text": "Due today", "cls": "ld-due soon"}
    if days <= 6:
        return {"text": "Due " + due.astimezone(tz).strftime("%a"), "cls": "ld-due soon" if days <= 2 else "ld-due"}
    return {"text": "Due " + _day(item.get("due_at"), biz).split(" ", 1)[1], "cls": "ld-due"}


def _when(item: Dict[str, Any], biz: Dict[str, Any], now: datetime) -> str:
    """When the current step is due, as said in a sentence: "today",
    "Monday", "Nov 6"."""
    due = cfu._parse(item.get("due_at"))
    if not due:
        return "soon"
    tz = _tz(biz)
    days = (due.astimezone(tz).date() - now.astimezone(tz).date()).days
    if days <= 0:
        return "today"
    if days <= 6:
        return due.astimezone(tz).strftime("%A")
    return _day(item.get("due_at"), biz).split(" ", 1)[1]


def _is_new(item: Dict[str, Any], now: datetime) -> bool:
    a = cfu._parse(item.get("assigned_at"))
    return bool(a and (now - a).days < 3 and int(item.get("step") or 0) == 0 and not item.get("late"))


def chief_line(items: List[Dict[str, Any]], biz: Dict[str, Any], now: Optional[datetime] = None) -> str:
    """Chief's one line at the top of the list: who needs them first."""
    now = now or datetime.now(timezone.utc)
    if not items:
        return "Nobody is waiting on you. When Chief hands you someone, they show up here."
    late = [i for i in items if i.get("late")]
    if late:
        p = late[0]["person"]["name"]
        more = f" {len(late) - 1} more past due." if len(late) > 1 else ""
        return f"{cfu.first_name(p)} is past due. A quick call today?{more}"
    new = [i for i in items if _is_new(i, now)]
    if new:
        steps = new[0].get("steps") or []
        step = steps[0]["title"] if steps else "Reach out"
        return f"{new[0]['person']['name']} is new. {step} by {_when(new[0], biz, now)}."
    first = items[0]
    steps = first.get("steps") or []
    title = steps[first["step"]]["title"] if first["step"] < len(steps) else "Next step"
    return f"Next: {title} with {cfu.first_name(first['person']['name'])}, due {_when(first, biz, now)}."


def _role_text(r: Dict[str, Any]) -> str:
    label = r.get("label") or cfu.ROLE_LABELS.get(r.get("role"), "Leader")
    if (r.get("covers") == "team" or r.get("role") == "team_leader") and r.get("scope"):
        return f"{label} · {r['scope']}"
    return label


def _is_prayer(r: Dict[str, Any]) -> bool:
    return r.get("job") == "prayer" or any(h in (r.get("handles") or []) for h in ("prayer_shared", "prayer_passed"))


def _invite_card(r: Dict[str, Any], church: str) -> str:
    """The invitation (canvas board 8): what the role is, in the church's
    words, what they'd get and never see, and who they'd answer to."""
    import church_roles as cr
    team = r.get("covers") == "team" or (r.get("role") == "team_leader" and bool(r.get("scope")))
    what = cfu.role_name({**r, "def": {"title": r.get("label"), "covers": "team" if team else r.get("covers")}})
    job = cr.JOBS.get(r.get("job") or "") or {}
    rows = []
    if job:
        rows.append(f'<div><dt>You’ll get</dt><dd>{_e(job["gets"])}</dd></div>')
        rows.append(f'<div><dt>You’ll see</dt><dd>{_e(job["sees"])}</dd></div>')
        rows.append(f'<div><dt>You’ll never see</dt><dd>{_e(job["never"])}</dd></div>')
    if r.get("reports_to_title"):
        rows.append(f'<div><dt>You answer to</dt><dd>The {_e(r["reports_to_title"])}. If something waits a day, '
                    f'they hear about it.</dd></div>')
    ask = (f'Will you lead <em>{_e(what)}</em>?' if team else f'Will you be {_e(church)}’s <em>{_e(what)}</em>?')
    return (f'<section class="ld-invite" aria-label="An invitation">'
            f'<h2>{ask}</h2>'
            + (f'<p>{_e(r["definition"])}</p>' if r.get("definition") else
               f'<p>{_e(church)} asked. Say yes and the people Chief hands to you show up here.</p>')
            + (f'<dl class="ld-ans">{"".join(rows)}</dl>' if rows else "")
            + f'<form method="post" action="/my/lead/answer" class="ld-two">'
            f'<input type="hidden" name="role_id" value="{_e(r["id"])}">'
            f'<button class="ld-btn" type="submit" name="answer" value="yes">Yes, I’ll lead</button>'
            f'<button class="ld-ghost" type="submit" name="answer" value="no">Not right now</button></form>'
            f'<p class="ld-quiet">Saying no is fine. The church is told kindly, and nothing else changes for you.</p></section>')


def _prayer_card(p: Dict[str, Any], biz: Dict[str, Any], targets: List[Dict[str, Any]], now: datetime) -> str:
    from member_app_ui import icon
    church = (biz.get("name") or "Your church").strip()
    due = due_label({"due_at": p.get("due_at")}, biz, now)
    tags = ['<span class="ld-tag">Shared with the prayer team</span>']
    if p.get("wants_call"):
        tags.append('<span class="ld-tag">Wants a call</span>')
    acts = []
    rid = _e(p["id"])
    if p.get("prayed_at"):
        acts.append(f'<span class="ld-said">{icon("check", 15)}Prayed today</span>')
    else:
        acts.append(f'<form method="post" action="/my/lead/prayer/prayed"><input type="hidden" name="rid" value="{rid}">'
                    f'<button class="ld-btn" type="submit">I prayed</button></form>')
    if p.get("noted_at"):
        acts.append(f'<span class="ld-said">{icon("check", 15)}Note sent</span>')
    elif p.get("email_ok"):
        acts.append(f'<form method="post" action="/my/lead/prayer/note"><input type="hidden" name="rid" value="{rid}">'
                    f'<button class="ld-ghost" type="submit">Send a note</button></form>')
    phone = re.sub(r"[^\d+]", "", p.get("phone") or "")
    if phone:
        acts.append(f'<a class="ld-ghost" href="tel:{_e(phone)}">{icon("phone", 16)}Call {_e(p["first"])}</a>')
    passing = ""
    if targets and not p.get("prayed_at"):
        opts = "".join(f'<option value="{_e(t["contact_id"])}">{_e(t["name"])}</option>' for t in targets)
        passing = (f'<form method="post" action="/my/lead/prayer/pass" class="ld-pass"><input type="hidden" name="rid" value="{rid}">'
                   f'<label class="mp-sr" for="ld-pass-{rid}">Pass it to</label>'
                   f'<select id="ld-pass-{rid}" name="to">{opts}</select>'
                   f'<button class="ld-ghost" type="submit">Pass it on</button></form>')
    note_line = (f'<p class="ld-quiet">A note says: “We prayed for you today. {_e(church)} is with you.” Never their words.</p>'
                 if p.get("email_ok") and not p.get("noted_at") else "")
    return (f'<section class="ld-pr" aria-label="{_e(p["first"])}">'
            f'<div class="ld-pr-who"><span class="ld-av" aria-hidden="true">{_e((p["first"] or "?")[:1].upper())}</span>'
            f'<span class="t"><b>{_e(p["first"])}</b><small>{_e(_day(p.get("created_at"), biz))} · {_e(p.get("source") or "")}</small></span>'
            f'<span class="{due["cls"]}">{_e(due["text"]) if not p.get("prayed_at") else ""}</span></div>'
            f'<p class="ld-pr-text">{_e(p["text"])}</p>'
            f'<div class="ld-pr-tags">{"".join(tags)}</div>'
            f'<div class="ld-pr-acts">{"".join(acts)}</div>{passing}{note_line}</section>')


def _prayer_body(pv: Optional[Dict[str, Any]], biz: Dict[str, Any], targets: List[Dict[str, Any]], now: datetime) -> str:
    from member_app_ui import icon
    if pv is None:
        return '<p class="mp-err" role="alert">Your prayer requests couldn’t load just now. Please try again in a moment.</p>'
    reqs = pv.get("requests") or []
    waiting = sum(1 for p in reqs if not p.get("prayed_at"))
    head = (f'<div class="ld-chief"><small>{icon("star", 12)}From Chief</small><p>'
            + (_e(f"{waiting} {'request is' if waiting == 1 else 'requests are'} waiting for prayer.") if waiting else
               "Nothing is waiting. When someone shares a request with the prayer team, it shows up here.")
            + '</p></div>')
    cards = "".join(_prayer_card(p, biz, targets, now) for p in reqs)
    done = pv.get("prayed_30") or 0
    return (head + (f'<div class="ld-prs" style="margin-top:12px">{cards}</div>' if cards else "")
            + (f'<div class="ld-done" style="margin-top:12px">{icon("check", 16)}<span><b>{done} prayed over</b> this month.</span></div>' if done else "")
            + f'<p class="ld-quiet" style="margin-top:12px">{icon("lock", 14)}<span>Never here: requests kept for the pastors, '
              f'giving, or anyone’s whole record. Anything about someone in danger goes straight to the pastor.</span></p>')


def _person_link(i: Dict[str, Any], biz: Dict[str, Any], current: str, now: datetime, *, auto: bool = False) -> str:
    steps = i.get("steps") or []
    step = i["step"]
    label = f"Step {step + 1} of {len(steps)} · {steps[step]['title']}" if step < len(steps) else "Done"
    due = due_label(i, biz, now)
    new = _is_new(i, now)
    if new:
        due = {"text": "New", "cls": "ld-due new"}
    # The person a computer shows beside the list, before anyone is picked,
    # is marked only on a computer: on a phone the list stands alone.
    here = ((' data-shown="1"' if auto else ' aria-current="page"') if i["id"] == current else "")
    return (f'<a class="ld-p" href="/my/lead/{_e(i["id"])}"{here}>'
            f'<span class="ld-av{" new" if new else ""}" aria-hidden="true">{_e(i["person"]["initials"])}</span>'
            f'<span class="t"><b>{_e(i["person"]["name"])}</b><small>{_e(label)}</small></span>'
            f'<span class="{due["cls"]}">{_e(due["text"])}</span></a>')


def _note_who(n: Dict[str, Any], me_id: str, me_name: str) -> str:
    if n.get("author_kind") == "chief":
        return "Chief"
    if n.get("author_kind") == "leader" and n.get("author_name") == me_name:
        return "You"
    return n.get("author_name") or ("The office" if n.get("author_kind") == "office" else "A leader")


_NOTE_TAGS = {"talked": "Talked", "message": "Left a message", "noanswer": "No answer", "notnow": "Not right now",
              "note": "Note", "assigned": "Assigned", "reassigned": "Handed on", "step": "Step done",
              "nudged": "Reminder", "pastors_told": "Pastors told", "reassign_asked": "Late",
              "handed_back": "Handed back", "done": "Done"}


def _file(i: Dict[str, Any], biz: Dict[str, Any], me: Dict[str, Any]) -> str:
    """One person: reach them, why you, the path, log a conversation, what
    they wrote, the conversations so far, hand back."""
    p = i["person"]
    steps = i.get("steps") or []
    step = i["step"]
    reach = []
    phone = re.sub(r"[^\d+]", "", p.get("phone") or "")
    from member_app_ui import icon
    if phone:
        reach.append(f'<a href="tel:{_e(phone)}">{icon("phone", 20)}Call</a>')
        reach.append(f'<a href="sms:{_e(phone)}">{icon("chat", 20)}Text</a>')
    if p.get("email"):
        reach.append(f'<a href="mailto:{_e(p["email"])}">{icon("mail", 20)}Email</a>')
    rows = []
    for n, s in enumerate(steps):
        if n < step:
            dot, note = '<span class="ld-dot done" aria-hidden="true">✓</span>', "Done"
        elif n == step:
            dot, note = '<span class="ld-dot now" aria-hidden="true"></span>', due_label(i, biz)["text"] or "Now"
        else:
            dot, note = '<span class="ld-dot" aria-hidden="true"></span>', s.get("rule") or ""
        rows.append(f'<li>{dot}<span><b>{_e(s["title"])}</b><small>{_e(note)}</small></span></li>')
    advance = (f'<form method="post" action="/my/lead/step"><input type="hidden" name="fid" value="{_e(i["id"])}">'
               f'<button class="ld-btn" type="submit">{icon("check", 17)}Mark “{_e(steps[step]["title"])}” done</button></form>'
               if step < len(steps) else "")
    chips = "".join(
        f'<label><input type="radio" name="outcome" value="{k}"{" checked" if k == "talked" else ""}><span>{_e(v)}</span></label>'
        for k, v in cfu.OUTCOMES.items() if k != "note")
    answers = "".join(f'<div><dt>{_e(a["q"])}</dt><dd>{_e(a["a"])}</dd></div>' for a in i.get("answers") or []) or \
        '<div><dd>They left the rest of the card blank.</dd></div>'
    me_name = (me.get("name") or "").strip()
    notes = "".join(
        f'<li><div class="ld-by"><b>{_e(_note_who(n, str(me["id"]), " ".join(me_name.split())))}</b>'
        f'<span>{_e(_day(n.get("created_at"), biz))}</span><span class="ld-tag">{_e(_NOTE_TAGS.get(n.get("kind"), ""))}'
        f'{" · Pastors only" if n.get("pastors_only") else ""}</span></div>'
        f'{"<p>" + _e(n["body"]) + "</p>" if n.get("body") else ""}</li>' for n in i.get("notes") or [])
    return f"""<div class="ld-person"><span class="ld-av" aria-hidden="true">{_e(p['initials'])}</span>
<div><h2>{_e(p['name'])}</h2><small>{_e(i.get('card_name') or 'Card')} · {_e(_day(i.get('created_at'), biz))}</small></div></div>
{f'<div class="ld-reach">{"".join(reach)}</div>' if reach else ''}
<p class="ld-why"><b>Why you:</b> {_e(i.get('reason') or '')}</p>
<section class="ld-card" aria-label="The path"><h3>The path</h3><ol class="ld-steps">{''.join(rows)}</ol>{advance}</section>
<section class="ld-card" aria-label="Log a conversation"><h3>Log a conversation</h3>
<form method="post" action="/my/lead/note"><input type="hidden" name="fid" value="{_e(i['id'])}">
<fieldset class="ld-chips"><legend>How did it go?</legend>{chips}</fieldset>
<p><label class="mp-sr" for="ld-text-{_e(i['id'])}">What did you talk about?</label>
<textarea class="ld-ta" id="ld-text-{_e(i['id'])}" name="text" maxlength="2000" placeholder="What did you talk about? Anything the next person should know?"></textarea></p>
<label class="ld-check"><input type="checkbox" name="pastors_only" value="yes">Pastors only</label>
<button class="ld-btn" type="submit">Save the note</button></form></section>
<section class="ld-card" aria-label="On the card"><h3>On the card</h3><dl class="ld-ans">{answers}</dl></section>
<section class="ld-card" aria-label="Conversations"><h3>Conversations</h3><ul class="ld-notes">{notes}</ul></section>
<details class="ld-card ld-back"><summary class="ld-ghost">Hand back to the office</summary>
<form method="post" action="/my/lead/handback"><input type="hidden" name="fid" value="{_e(i['id'])}">
<p><label class="mp-sr" for="ld-why-{_e(i['id'])}">Why?</label>
<textarea class="ld-ta" id="ld-why-{_e(i['id'])}" name="text" maxlength="2000" placeholder="Why? (optional) The office will hand them to someone else."></textarea></p>
<button class="ld-btn" type="submit">Hand back</button></form></details>"""


def render(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], my_roles: List[Dict[str, Any]],
           view: Optional[Dict[str, Any]], selected: str = "", *, now: Optional[datetime] = None,
           prayer: Optional[Dict[str, Any]] = None, tab: str = "people",
           targets: Optional[List[Dict[str, Any]]] = None, fams: int = 0, safety: Optional[int] = None,
           room: bool = False, groups: int = 0) -> str:
    from member_portal import _shell
    import member_portal_safety as mps
    now = now or datetime.now(timezone.utc)
    church = (biz.get("name") or "Your church").strip()
    done = DONE.get(request.query_params.get("done") or "")
    err = ERRORS.get(request.query_params.get("err") or "")
    flash = (f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>' if err else
             f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>' if done else "")
    active = [r for r in my_roles if r.get("status") == "active"]
    invited = [r for r in my_roles if r.get("status") == "invited"]
    first = (me.get("name") or "").strip().split(" ")[0] or "friend"
    head = (f'<header class="ld-head"><h1 class="ld-hello">{_word()}, <em>{_e(first)}</em></h1>'
            f'<div class="ld-roles">{"".join(f"<span class=ld-role>{_e(_role_text(r))}</span>" for r in active)}</div></header>')
    invites = "".join(_invite_card(r, church) for r in invited)
    prays = any(_is_prayer(r) for r in active) or bool((prayer or {}).get("requests"))
    people = any(not _is_prayer(r) for r in active) or bool((view or {}).get("follow_ups"))
    if active and prays and (tab == "prayer" or not people):
        waiting = sum(1 for p in (prayer or {}).get("requests") or [] if not p.get("prayed_at"))
        seg = _seg("prayer", people, True, waiting, fams, groups)
        body = (f'{flash}{head}{invites}{mps.card(safety)}{_room_door(room)}{savvy_door(PARTS.get().get("team") or [])}'
                f'{PAID_BACK.get()}{seg}{_prayer_body(prayer, biz, targets or [], now)}')
        return _shell(biz, site, "Prayer", f'<style>{LEAD_CSS}{mps.SAFETY_CSS}</style><div class="ld-wide">{body}</div>',
                      tab="lead", who=me)
    seg = ""
    if active:
        waiting = sum(1 for p in (prayer or {}).get("requests") or [] if not p.get("prayed_at"))
        seg = _seg("people", True, prays, waiting, fams, groups)
    head = head + seg
    if not active:
        p = PARTS.get()
        kids = (f'<section class="ld-card"><h3>Kids room</h3><p>You serve in Kids. Your room and its Sundays live in '
                f'the Kids space.</p><p><a class="ld-btn" href="/my/space?to=kids">Open the Kids room</a></p></section>'
                if p.get("kids") else "")
        savvy = savvy_door(p.get("team") or []) + PAID_BACK.get()
        body = (f'{flash}{head}{invites}{savvy}{kids}' if invites or kids or savvy else
                f'{flash}{head}<section class="ld-card"><p>You don’t lead anything at {_e(church)} yet. When the church '
                f'asks you to, it shows up here.</p><p><a href="/my">Back to Home</a></p></section>')
        return _shell(biz, site, _word(), f'<style>{LEAD_CSS}{mps.SAFETY_CSS if savvy else ""}</style><div class="ld-wide">{body}</div>',
                      tab="lead", who=me)
    if view is None:
        body = (f'{flash}{head}<p class="mp-err" role="alert">Your people couldn’t load just now. '
                f'Please try again in a moment.</p>')
        return _shell(biz, site, "Lead", f'<style>{LEAD_CSS}</style><div class="ld-wide">{body}</div>', tab="lead", who=me)
    items = view["follow_ups"]
    order = sorted(items, key=lambda i: (not i.get("late"), not _is_new(i, now), i.get("due_at") or ""))
    sel = next((i for i in order if i["id"] == selected), None)
    shown = sel or (order[0] if order else None)
    links = "".join(_person_link(i, biz, (shown or {}).get("id", ""), now, auto=sel is None) for i in order)
    finished = view.get("done_30") or 0
    from member_app_ui import icon
    listing = (f'<section class="ld-list" aria-label="My people">'
               f'<div class="ld-chief"><small>{icon("star", 12)}From Chief</small><p>{_e(chief_line(order, biz, now))}</p></div>'
               f'<div class="mb-sh"><h2>My people</h2><span>{len(order)} handed to you</span></div>'
               f'{links}'
               + (f'<div class="ld-done">{icon("check", 16)}<span><b>{finished} finished</b> this month.</span></div>' if finished else "")
               + f'<p class="ld-quiet">{icon("lock", 14)}<span>You see only the people handed to you. Your notes are '
                 f'seen by you and the pastors.</span></p></section>')
    detail = (f'<section class="ld-file" aria-label="{_e(shown["person"]["name"])}">{_file(shown, biz, me)}</section>'
              if shown else '<section class="ld-file"></section>')
    grid = f'<div class="ld-grid{" has-sel" if sel else ""}">{listing}{detail}</div>'
    title = sel["person"]["name"] if sel else "Lead"
    door = "" if sel else mps.card(safety) + _room_door(room) + savvy_door(PARTS.get().get("team") or []) + PAID_BACK.get()
    return _shell(biz, site, title,
                  f'<style>{LEAD_CSS}{mps.SAFETY_CSS}</style><div class="ld-wide">{flash}{head}{invites}{door}{grid}</div>',
                  tab="lead", who=me, back=("/my/lead", _word()) if sel else None)


def _room_door(room: bool) -> str:
    """The All group leaders room's door (member_portal_groups), for the
    pastors and group leaders in it."""
    if not room:
        return ""
    from member_app_ui import icon
    return (f'<a class="sf-door" href="/my/groups/leaders">{icon("users", 20)}'
            f'<span><b>All group leaders</b><small>Every group leader and your pastors, in one chat</small></span>'
            f'{icon("chevron", 18)}</a>')


async def _context(request: Request, biz: Dict[str, Any], me: Dict[str, Any]) -> None:
    """What every Lead tab page's switcher and doors read, once per request:
    their Sunday team, their other parts, Get paid back, and their tasks."""
    import sunday_leading
    import member_app_ui
    import church_leader_tasks as clt
    SUNDAYS.set(await asyncio.to_thread(sunday_leading.leads_a_team, biz["id"], str(me["id"])))
    PARTS.set(await asyncio.to_thread(parts, biz, str(me["id"]), me.get("email")) if member_app_ui.serve_mode() else {})
    import member_portal_checks as mpck
    PAID_BACK.set(await mpck.door_async(request, biz))
    TASKS.set(await asyncio.to_thread(clt.section, biz, str(me["id"])))


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], sub: str):
    """GET /my/lead, /my/lead/prayer and /my/lead/<id>: (html, status)."""
    import church_prayer
    import church_shepherding as shep
    selected = sub[len("/my/lead/"):] if sub.startswith("/my/lead/") else ""
    await _context(request, biz, me)
    # The tasks the office handed them (church_leader_tasks).
    if selected == "tasks":
        return await serve_tasks(request, biz, site, me)
    # A Sunday team's leader: their team's Sundays (member_portal_leading).
    if selected == "sundays":
        import member_portal_leading
        return await member_portal_leading.serve(request, biz, site, me)
    if selected == "families" or selected.startswith("family/"):
        return await serve_families(request, biz, site, me, selected)
    # A group's leaders: their group (group_lead).
    if selected == "groups" or selected.startswith("groups/"):
        return await serve_groups(request, biz, site, me, selected[len("groups/"):] if "/" in selected else "")
    # The Safety room, for the church's safety officers (member_portal_safety).
    import member_portal_safety as mps
    if selected == "safety" or selected.startswith("safety/"):
        return await mps.serve(request, biz, site, me, sub)
    tab = "prayer" if selected == "prayer" else "people"
    if tab == "prayer":
        selected = ""
    if selected and not _FID.match(selected):
        return render(biz, site, request, me, [], None), 404
    my_roles = await asyncio.to_thread(cfu.roles_for, biz["id"], str(me["id"]))
    if my_roles is None:
        return render(biz, site, request, me, [{"status": "active", "role": "", "label": ""}], None), 503
    import group_lead
    led = await asyncio.to_thread(group_lead.led_groups, biz["id"], str(me["id"])) or []
    if led and not selected and tab == "people" and not any(r["status"] == "active" for r in my_roles):
        # Only a group to lead: the Lead tab opens on it.
        return await serve_groups(request, biz, site, me, "")
    if (PARTS.get().get("serving") and not selected and tab == "people"
            and not any(r["status"] in ("active", "invited") for r in my_roles)):
        # Only a place on a Sunday team: the Serve tab opens on their Sundays.
        import member_portal_serving as mps_serving
        import sunday_serving as ss
        m = await asyncio.to_thread(ss.mine, biz, str(me["id"]))
        if m is not None:
            m["hear"] = await asyncio.to_thread(ss.hearing, biz, str(me["id"]))
            m["hours"] = await mps_serving.hours_for(request, biz, me)
            return mps_serving.render_page(biz, site, request, me, m, None,
                                           door=savvy_door(PARTS.get().get("team") or []) + PAID_BACK.get()), 200
    if (TASKS.get() is not None and not selected and tab == "people"
            and not any(r["status"] in ("active", "invited") for r in my_roles)):
        # Only tasks the office handed them: the tab opens on them.
        return await serve_tasks(request, biz, site, me)
    view = prayer = None
    targets: List[Dict[str, Any]] = []
    fams = 0
    if any(r["status"] == "active" for r in my_roles):
        fv = await asyncio.to_thread(shep.my_families, biz["id"], str(me["id"]))
        fams = len((fv or {}).get("families") or [])
        view = await asyncio.to_thread(cfu.leader_view, biz["id"], str(me["id"]))
        prayer = await asyncio.to_thread(church_prayer.leader_prayers, biz["id"], str(me["id"]))
        if any(_is_prayer(r) for r in my_roles if r["status"] == "active"):
            targets = await asyncio.to_thread(church_prayer.pass_targets, biz["id"], me) or []
    safety = await asyncio.to_thread(mps.waiting, biz["id"], str(me["id"])) if any(
        r["status"] == "active" for r in my_roles) else None
    import member_portal_messaging as mpm
    room = (await asyncio.to_thread(mpm.in_leaders_room, biz["id"], str(me["id"]))
            if mpm.turned_on(biz) and any(r["status"] == "active" for r in my_roles) else False)
    html_out = render(biz, site, request, me, my_roles, view, selected, prayer=prayer, tab=tab, targets=targets,
                      fams=fams, safety=safety, room=bool(room), groups=len(led))
    ok = (prayer is not None) if tab == "prayer" else (view is not None)
    return html_out, 200 if ok or not my_roles else 503


async def serve_groups(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], group_id: str):
    """GET /my/lead/groups[/<group id>]: a group's leaders, their group
    (group_lead). (html, status)."""
    import group_lead
    import group_study
    import member_portal_church as mpc
    import member_portal_groups as mpg
    from member_portal import _shell
    if group_id and not _FID.match(group_id):
        group_id = ""
    v = await asyncio.to_thread(group_lead.view, biz, me, group_id)
    my_roles = await asyncio.to_thread(cfu.roles_for, biz["id"], str(me["id"])) or []
    active = [r for r in my_roles if r.get("status") == "active"]
    people = any(not _is_prayer(r) for r in active)
    prays = any(_is_prayer(r) for r in active)
    n = len((v or {}).get("groups") or [])
    seg = _seg("groups", people, prays, 0, 0, n)
    first = (me.get("name") or "").strip().split(" ")[0] or "friend"
    if v is None:
        body = (f'<header class="ld-head"><h1 class="ld-hello">Lead, <em>{_e(first)}</em></h1></header>{seg}'
                f'<p class="mp-err" role="alert">Your group couldn’t load just now. Please try again in a moment.</p>')
        return _shell(biz, site, "My group", f'<style>{LEAD_CSS}</style><div class="ld-wide">{body}</div>', tab="lead", who=me), 503
    if not v:
        body = (f'<header class="ld-head"><h1 class="ld-hello">Lead, <em>{_e(first)}</em></h1></header>{seg}'
                f'<section class="ld-card"><p>You don’t lead a group right now. When the church office makes you a group’s '
                f'leader, it shows up here.</p><p><a href="/my/lead">Back to Lead</a></p></section>')
        return _shell(biz, site, "My group", f'<style>{LEAD_CSS}</style><div class="ld-wide">{body}</div>', tab="lead", who=me), 200
    g = v["g"]
    mode = g.get("name_display") or "full"
    inner = group_lead.render_body(biz, me, v, ic=mpg._ic, esc=_e,
                                   face=lambda p: mpg._face(p, "gs-av", mode), name=lambda p: mpg.display_name(p, mode))
    import group_desk
    head = (f'<header class="ld-head" style="flex-direction:column;align-items:flex-start;gap:6px">'
            f'<p class="gl-eb">You lead {_e(g.get("name") or "a group")}</p>'
            f'<h1 class="ld-hello">{group_lead.hello(biz, me)}</h1></header>')
    # On a computer, the leader's desk (group_desk): the chats and the group's
    # chat beside My group; the phone keeps My group as it is.
    import chat_photos
    import chat_polls
    import group_chat_notify
    css = (f"{LEAD_CSS}{mpg.GROUP_CSS}{group_study.STUDY_CSS}{group_lead.GL_CSS}{mpg.CHAT_CSS}{chat_polls.POLL_CSS}"
           f"{chat_photos.PHOTO_CSS}{group_chat_notify.CONTROL_CSS}{group_desk.DESK_CSS}")
    rail = f'{mpc._flash(request)}{head}{seg}{PAID_BACK.get()}{group_desk.gathering(g, v, esc=_e, ic=mpg._ic)}{inner}'
    body = group_desk.shell(str(g["id"]), rail, esc=_e, ic=mpg._ic)
    return _shell(biz, site, g.get("name") or "My group", f'<style>{css}</style><div class="ld-wide gl">{body}</div>',
                  tab="lead", who=me, script=group_desk.script(str(g["id"]))), 200


# ─── Shepherding: the families a pastor or elder shepherds ────────────
#
# Canvas 31su6kdYmYecH5b2NxjBJN, boards 6-7. Only the family's current
# shepherd sees a family (church_shepherding checks every read and write);
# a child is a first name and an age; never giving, prayer kept for the
# pastors, or a child's care notes.

FAM_CSS = """
.ld-month{gap:8px;}
.ld-month b{font-family:var(--mb-serif);font-size:30px;font-weight:500;line-height:1;}
.ld-bar{height:8px;border-radius:999px;background:var(--s3);overflow:hidden;}
.ld-bar i{display:block;height:100%;background:var(--mb-fill);border-radius:999px;}
.ld-fams{display:flex;flex-direction:column;gap:10px;max-width:760px;}
.ld-kin{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:10px;}
.ld-kin li{display:flex;align-items:center;gap:12px;min-height:44px;}
.ld-kin .ld-av{width:40px;height:40px;font-size:13px;}
.ld-kin .t{display:flex;flex-direction:column;flex:1;min-width:0;}
.ld-kin .t b{font-size:15.5px;font-weight:650;}
.ld-kin .t small{font-size:12.5px;color:var(--fg3);}
.ld-kin .acts{display:flex;gap:6px;}
.ld-kin .acts a{display:grid;place-items:center;width:44px;height:44px;border-radius:50%;background:var(--s2);color:var(--fg);}
.ld-tags{display:flex;flex-wrap:wrap;gap:6px;}
.ld-tag.ld-late{color:#ff8a5c;}
.ld-news{align-items:flex-start;}
"""


def _and(names: List[str]) -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


def _ago(days: Optional[int]) -> str:
    if days is None:
        return "Not reached yet"
    if days <= 0:
        return "Reached today"
    if days == 1:
        return "Last reached yesterday"
    return f"Last reached {days} days ago"


def _seg(tab: str, people: bool, prays: bool, waiting: int, fams: int, groups: int = 0) -> str:
    """My group | Sundays | People | Prayer | Tasks | Families: only the ones
    this leader has, and only when there is more than one."""
    tabs = []
    if groups:
        tabs.append(("groups", "/my/lead/groups", "My groups" if groups > 1 else "My group"))
    if SUNDAYS.get():
        tabs.append(("sundays", "/my/lead/sundays", "Sundays"))
    if people:
        tabs.append(("people", "/my/lead", "People"))
    if prays:
        tabs.append(("prayer", "/my/lead/prayer", f"Prayer · {waiting}" if waiting else "Prayer"))
    tasks = TASKS.get()
    if tasks is not None:
        tabs.append(("tasks", "/my/lead/tasks", f"Tasks · {tasks['open']}" if tasks.get("open") else "Tasks"))
    if fams:
        tabs.append(("families", "/my/lead/families", f"Families · {fams}"))
    p = PARTS.get()
    if p.get("serving"):
        tabs.append(("serving", "/my/serving", "Serving"))
    if p.get("kids"):
        tabs.append(("kids", "/my/space?to=kids", "Kids room"))
    if len(tabs) < 2:
        return ""
    here = ' aria-current="page"'
    links = "".join(f'<a href="{href}"{here if key == tab else ""}>{_e(label)}</a>' for key, href, label in tabs)
    return f'<nav class="ld-seg" aria-label="{_word()}">{links}</nav>'


def _fam_link(f: Dict[str, Any], biz: Dict[str, Any]) -> str:
    import church_shepherding as shep
    import church_shepherd_signals as sig
    if f.get("drifting"):
        seen = sig._day(f.get("last_seen"))
        sub = "Missed three Sundays" + (f" · last here {sig.label(seen)}" if seen else "")
    elif f.get("reached") and f.get("last_touch_kind"):
        sub = f"{shep.KINDS.get(f['last_touch_kind'], 'Reached')} {_day(f.get('last_touch_at'), biz)}"
    else:
        sub = _ago(f.get("days"))
    size = int(f.get("size") or 0)
    return (f'<a class="ld-p" href="/my/lead/family/{_e(f["household_id"])}">'
            f'<span class="ld-av" aria-hidden="true">{_e(shep.family_initial(f["name"]))}</span>'
            f'<span class="t"><b>{_e(f["name"])}</b><small>{_e(sub)}</small></span>'
            f'<span class="ld-due">{size} {"person" if size == 1 else "people"}</span></a>')


def _notes_line(chain: List[str]) -> str:
    return f"{_and(chain)} can read your notes." if chain else "The church office can read your notes."


def _families_body(fv: Optional[Dict[str, Any]], biz: Dict[str, Any], church: str) -> str:
    from member_app_ui import icon
    if fv is None:
        return '<p class="mp-err" role="alert">Your families couldn’t load just now. Please try again in a moment.</p>'
    if not fv.get("shepherd"):
        return (f'<section class="ld-card"><p>You don’t shepherd any families at {_e(church)}. When the pastor gives '
                f'you some, they show up here.</p><p><a href="/my/lead">Back to Lead</a></p></section>')
    import church_shepherd_signals as sig
    fams = fv["families"]
    # Drifting families stay at the top until they're back at church.
    need = [f for f in fams if f.get("drifting") or not f["reached"]]
    done = sorted((f for f in fams if f["reached"] and not f.get("drifting")),
                  key=lambda f: f["days"] if f["days"] is not None else 0)
    n, x = len(fams), sum(1 for f in fams if f["reached"])
    days = int(fv.get("rhythm_days") or 30)
    if not fams:
        line = "No families are yours yet. When the pastor gives you some, they show up here."
    elif need and need[0].get("drifting"):
        f = need[0]
        seen = sig._day(f.get("last_seen"))
        line = (f"{f['name']} has missed three Sundays" + (f"; they were last here {sig.label(seen)}" if seen else "")
                + ". A call this week?" + (f" {len(need) - 1} more to reach." if len(need) > 1 else ""))
    elif need:
        f = need[0]
        when = "hasn’t been reached yet" if f["days"] is None else f"was last reached {f['days']} days ago"
        line = f"{f['name']} {when}. A call this week?" + (f" {len(need) - 1} more to reach." if len(need) > 1 else "")
    else:
        line = f"Every family heard from you in the last {days} days. Thank you."
    pct = round(100 * x / n) if n else 0
    out = (f'<div class="ld-fams"><div class="ld-chief"><small>{icon("star", 12)}From Chief</small><p>{_e(line)}</p></div>'
           + (f'<section class="ld-card ld-month" aria-label="Reached"><h2>Reached in the last {days} days</h2>'
              f'<b>{x} of {n}</b><div class="ld-bar" role="img" aria-label="{x} of {n} reached">'
              f'<i style="width:{pct}%"></i></div></section>' if fams else ""))
    if need:
        out += (f'<div class="mb-sh"><h2>They need you first</h2><span>{len(need)}</span></div>'
                + "".join(_fam_link(f, biz) for f in need))
    if done:
        out += (f'<div class="mb-sh"><h2>Reached lately</h2><span>{len(done)}</span></div>'
                + "".join(_fam_link(f, biz) for f in done))
    out += (f'<p class="ld-quiet">{icon("lock", 14)}<span>Never here: giving, prayer kept for the pastors, or a '
            f'child’s care notes. {_e(_notes_line(fv.get("chain") or []))}</span></p></div>')
    return out


def _family_body(fam: Dict[str, Any], biz: Dict[str, Any], me: Dict[str, Any]) -> str:
    import church_shepherding as shep
    from member_app_ui import icon
    hid = _e(fam["household_id"])
    kin = []
    for p in fam["people"]:
        acts = []
        phone = re.sub(r"[^\d+]", "", p.get("phone") or "")
        first = cfu.first_name(p["name"])
        if phone:
            acts.append(f'<a href="tel:{_e(phone)}" aria-label="Call {_e(first)}">{icon("phone", 18)}</a>')
            acts.append(f'<a href="sms:{_e(phone)}" aria-label="Text {_e(first)}">{icon("chat", 18)}</a>')
        if p.get("email"):
            acts.append(f'<a href="mailto:{_e(p["email"])}" aria-label="Email {_e(first)}">{icon("mail", 18)}</a>')
        kin.append(f'<li><span class="ld-av" aria-hidden="true">{_e(p["initials"])}</span>'
                   f'<span class="t"><b>{_e(p["name"])}</b><small>{_e(p["tag"])}</small></span>'
                   f'{"<span class=acts>" + "".join(acts) + "</span>" if acts else ""}</li>')
    touches = fam.get("touches") or []
    last = touches[0] if touches else None
    days = None
    if last:
        at = cfu._parse(last.get("at"))
        days = (datetime.now(timezone.utc) - at).days if at else None
    chips = "".join(
        f'<label><input type="radio" name="kind" value="{k}"{" checked" if k == "call" else ""}><span>{_e(v)}</span></label>'
        for k, v in shep.KINDS.items())
    lead = _and(fam.get("lead") or [])
    pastor = (f'<label class="ld-check"><input type="checkbox" name="needs_pastor" value="yes">'
              f'<span>Needs a pastor <small class="ld-quiet" style="display:inline">· goes to {_e(lead)} at once</small></span></label>'
              if lead else "")
    me_id = str(me["id"])
    before = "".join(
        f'<li><div class="ld-by"><b>{_e("You" if t.get("by_contact_id") == me_id else t.get("by") or "A shepherd")}</b>'
        f'<span>{_e(_day(t.get("at"), biz))}</span><span class="ld-tag">{_e(shep.KINDS.get(t.get("kind"), "Reached"))}'
        f'{" · Asked for a pastor" if t.get("needs_pastor") else ""}</span></div>'
        f'{"<p>" + _e(t["note"]) + "</p>" if t.get("note") else ""}</li>' for t in touches)
    since = _day(fam.get("since"), biz)
    import church_shepherd_signals as sig
    extras = fam.get("extras")
    sunday = sig.tag_for(extras)
    tags = (f'<span class="ld-tag{" ld-late" if (extras or {}).get("drifting") else ""}">{_e(sunday)}</span>' if sunday else "")
    tags += f'<span class="ld-tag">{_e(_ago(days))}</span>'
    if extras is None:
        news = '<p class="ld-quiet">Their Sundays and any care news couldn’t load just now. Try again in a moment.</p>'
    else:
        news = "".join(f'<p class="ld-quiet ld-news">{icon("heart", 14)}<span>{_e(x)}</span></p>' for x in extras["lines"])
    return f"""<div class="ld-fams"><div class="ld-person"><span class="ld-av" aria-hidden="true">{_e(shep.family_initial(fam['name']))}</span>
<div><h2>{_e(fam['name'])}</h2><small>{_e(f'Yours since {since}' if since else 'Yours to shepherd')}</small></div></div>
<div class="ld-tags">{tags}</div>
{news}
<section class="ld-card" aria-label="The family"><h3>The family</h3><ul class="ld-kin">{''.join(kin)}</ul></section>
<section class="ld-card" aria-label="Log a touch"><h3>Log a touch</h3>
<form method="post" action="/my/lead/family/{hid}/touch">
<fieldset class="ld-chips"><legend>How did you reach them?</legend>{chips}</fieldset>
<p><label class="mp-sr" for="ld-touch-{hid}">A note, for you and the pastors</label>
<textarea class="ld-ta" id="ld-touch-{hid}" name="note" maxlength="2000" placeholder="A note, for you and the pastors. How are they doing?"></textarea></p>
{pastor}
<button class="ld-btn" type="submit">Save</button></form></section>
{f'<section class="ld-card" aria-label="Before"><h3>Before</h3><ul class="ld-notes">{before}</ul></section>' if before else ''}
<p class="ld-quiet">{icon("lock", 14)}<span>Never here: their giving, prayer kept for the pastors, or the children’s care notes. {_e(_notes_line(fam.get('chain') or []))}</span></p></div>"""


def render_families(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], my_roles: List[Dict[str, Any]],
                    fv: Optional[Dict[str, Any]], fam: Optional[Dict[str, Any]] = None, *, gone: bool = False) -> str:
    """/my/lead/families and /my/lead/family/<id>."""
    from member_portal import _shell
    church = (biz.get("name") or "Your church").strip()
    done = DONE.get(request.query_params.get("done") or "")
    err = ERRORS.get(request.query_params.get("err") or "")
    flash = (f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>' if err else
             f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>' if done else "")
    active = [r for r in my_roles if r.get("status") == "active"]
    css = f"<style>{LEAD_CSS}{FAM_CSS}</style>"
    if fam is not None or gone:
        body = (_family_body(fam, biz, me) if fam is not None else
                f'<section class="ld-card"><p>{_e(ERRORS["family_gone"])}</p>'
                f'<p><a href="/my/lead/families">Back to your families</a></p></section>')
        return _shell(biz, site, fam["name"] if fam else "Your families", f'{css}<div class="ld-wide">{flash}{body}</div>',
                      tab="lead", who=me, back=("/my/lead/families", "Your families"))
    head = (f'<header class="ld-head"><h1 class="ld-hello">Your families, <em>this month</em></h1>'
            f'<div class="ld-roles">{"".join(f"<span class=ld-role>{_e(_role_text(r))}</span>" for r in active)}</div></header>')
    count = len((fv or {}).get("families") or [])
    seg = _seg("families", any(not _is_prayer(r) for r in active), any(_is_prayer(r) for r in active), 0, count)
    body = f'{flash}{head}{seg}{_families_body(fv, biz, church)}'
    return _shell(biz, site, "Your families", f'{css}<div class="ld-wide">{body}</div>', tab="lead", who=me)


async def serve_families(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], selected: str):
    """GET /my/lead/families and /my/lead/family/<id>: (html, status)."""
    import church_shepherding as shep
    my_roles = await asyncio.to_thread(cfu.roles_for, biz["id"], str(me["id"]))
    if my_roles is None:
        return render_families(biz, site, request, me, [], None), 503
    active = any(r["status"] == "active" for r in my_roles)
    fv = (await asyncio.to_thread(shep.my_families, biz["id"], str(me["id"])) if active
          else {"shepherd": False, "families": []})
    if selected == "families":
        return render_families(biz, site, request, me, my_roles, fv), 200 if fv is not None else 503
    hid = selected[len("family/"):]
    if not active or not _FID.match(hid):
        return render_families(biz, site, request, me, my_roles, fv, gone=True), 404
    try:
        fam = await asyncio.to_thread(shep.family_for, biz["id"], str(me["id"]), hid)
    except HTTPException:
        return render_families(biz, site, request, me, my_roles, fv, gone=True), 404
    if fam is None:
        return render_families(biz, site, request, me, my_roles, None), 503
    import church_shepherd_signals as sig
    fam["extras"] = await asyncio.to_thread(sig.family_extras, biz, fam)
    return render_families(biz, site, request, me, my_roles, fv, fam), 200


# ─── My tasks: what the office handed a leader ────────────────────────
#
# Kevin, 2026-10-27 ("yes build my tasks for leaders"; church_leader_tasks).
# Only the tasks handed to this member, at this church: every read and
# write is checked against both.

TASK_CSS = """
.ld-tks{display:flex;flex-direction:column;gap:12px;max-width:760px;}
.ld-tk-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;}
.ld-tk-top b{font-size:17px;font-weight:650;line-height:1.3;min-width:0;overflow-wrap:anywhere;}
.ld-tk-top .ld-due{flex:none;padding-top:2px;}
.ld-tk-top .ld-due.late{color:var(--error);}
.ld-tk-notes{margin:0;font-size:15px;line-height:1.5;color:var(--fg2);white-space:pre-line;overflow-wrap:anywhere;}
.ld-tk-from{margin:0;font-size:12.5px;color:var(--fg3);}
.ld-tk form{margin:0;}
.ld-tk-done .ld-notes li b{overflow-wrap:anywhere;}
"""


def tasks_line(items: List[Dict[str, Any]]) -> str:
    """Chief's one line at the top of a leader's tasks."""
    if not items:
        return "Nothing is waiting on you. When the church office hands you a task, it shows up here."
    late = [t for t in items if t.get("late")]
    if late:
        more = f" {len(late) - 1} more past due." if len(late) > 1 else ""
        return f"“{late[0]['title']}” is {late[0]['due_text']}. If it’s done, tap Done so the office knows.{more}"
    first = items[0]
    when = first["due_text"][:1].lower() + first["due_text"][1:]
    n = len(items)
    return f"{n} task{'s' if n != 1 else ''} handed to you. Next: “{first['title']}”, {when}."


def _task_card(t: Dict[str, Any]) -> str:
    from member_app_ui import icon
    cls = {"late": "ld-due late", "soon": "ld-due soon"}.get(t.get("state") or "", "ld-due")
    notes = f'<p class="ld-tk-notes">{_e(t["notes"])}</p>' if t.get("notes") else ""
    return (f'<section class="ld-pr ld-tk" aria-label="{_e(t["title"])}">'
            f'<div class="ld-tk-top"><b>{_e(t["title"])}</b><span class="{cls}">{_e(t["due_text"])}</span></div>'
            f'{notes}<p class="ld-tk-from">From {_e(t.get("from") or "the church office")}</p>'
            f'<form method="post" action="/my/lead/tasks/{_e(t["id"])}/done">'
            f'<button class="ld-btn" type="submit">{icon("check", 17)}Done</button></form></section>')


def _tasks_body(view: Optional[Dict[str, Any]]) -> str:
    from member_app_ui import icon
    if view is None:
        return '<p class="mp-err" role="alert">Your tasks couldn’t load just now. Please try again in a moment.</p>'
    items, done = view.get("open") or [], view.get("done") or []
    out = (f'<div class="ld-tks"><div class="ld-chief"><small>{icon("star", 12)}From Chief</small>'
           f'<p>{_e(tasks_line(items))}</p></div>')
    if items:
        out += (f'<div class="mb-sh"><h2>My tasks</h2><span>{len(items)} open</span></div>'
                + "".join(_task_card(t) for t in items))
    if done:
        lis = "".join(
            f'<li><div class="ld-by"><b>{_e(d["title"])}</b><span>{_e(d.get("done_on") or "")}</span>'
            f'<span class="ld-tag">{"Done by you" if d.get("by_me") else "Marked done"}</span></div></li>' for d in done)
        out += (f'<details class="ld-card ld-back ld-tk-done"><summary class="ld-ghost">Done lately · {len(done)}</summary>'
                f'<ul class="ld-notes">{lis}</ul></details>')
    return out + (f'<p class="ld-quiet">{icon("lock", 14)}<span>You see only the tasks handed to you. When you tap '
                  f'Done, the church office sees it.</span></p></div>')


def render_tasks(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], active: List[Dict[str, Any]],
                 view: Optional[Dict[str, Any]], seg: str, *, err: str = "") -> str:
    """/my/lead/tasks."""
    from member_portal import _shell
    done = DONE.get(request.query_params.get("done") or "")
    bad = ERRORS.get(err or request.query_params.get("err") or "")
    flash = (f'<p class="mp-err mp-flash" role="alert">{_e(bad)}</p>' if bad else
             f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>' if done else "")
    first = (me.get("name") or "").strip().split(" ")[0] or "friend"
    head = (f'<header class="ld-head"><h1 class="ld-hello">{_word()}, <em>{_e(first)}</em></h1>'
            f'<div class="ld-roles">{"".join(f"<span class=ld-role>{_e(_role_text(r))}</span>" for r in active)}</div></header>')
    return _shell(biz, site, "My tasks",
                  f'<style>{LEAD_CSS}{TASK_CSS}</style><div class="ld-wide">{flash}{head}{seg}{_tasks_body(view)}</div>',
                  tab="lead", who=me)


async def serve_tasks(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], *, err: str = ""):
    """GET /my/lead/tasks: (html, status). Not a page while the switch is
    closed for this church."""
    import church_leader_tasks as clt
    import church_shepherding as shep
    import group_lead
    if not await asyncio.to_thread(clt.church_open, biz.get("id")):
        return render(biz, site, request, me, [], None), 404
    my_roles = await asyncio.to_thread(cfu.roles_for, biz["id"], str(me["id"])) or []
    active = [r for r in my_roles if r.get("status") == "active"]
    led = await asyncio.to_thread(group_lead.led_groups, biz["id"], str(me["id"])) or []
    fams = 0
    if active:
        fv = await asyncio.to_thread(shep.my_families, biz["id"], str(me["id"]))
        fams = len((fv or {}).get("families") or [])
    view = await asyncio.to_thread(clt.mine, biz, str(me["id"]))
    if TASKS.get() is None and view is not None:
        # On the page itself the switcher always names it, even with nothing handed yet.
        TASKS.set({"open": len(view["open"])})
    seg = _seg("tasks", any(not _is_prayer(r) for r in active), any(_is_prayer(r) for r in active), 0, fams, len(led))
    return render_tasks(biz, site, request, me, active, view, seg, err=err), 200 if view is not None else 503


# ─── POST ─────────────────────────────────────────────────────────────

def _go(target: str, **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    if (target not in ("/my/lead", "/my/lead/prayer", "/my/lead/families", "/my/lead/groups", "/my/lead/tasks")
            and not re.fullmatch(r"/my/lead/(family/|groups/)?[0-9a-fA-F-]{36}", target)):
        target = "/my/lead"
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return RedirectResponse(f"{target}?{qs}" if qs else target, status_code=303, headers=_SECURE_HEADERS)


async def _leader(request: Request):
    """(church, me, err): me is a signed-in member of this church who holds
    an active role; err names why not ('preview', 'error', or '' with me
    None for no session)."""
    from member_portal_church import _signed_in
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return church, None, "preview" if unavailable == "preview" else "error"
    if not me:
        return church, None, ""
    if not cfu.is_church(church["business"]):
        raise HTTPException(404, "Not found")
    mine = await asyncio.to_thread(cfu.roles_for, church["business"]["id"], str(me["id"]))
    if mine is None:
        return church, None, "error"
    return church, (me if any(r["status"] == "active" for r in mine) else None), ""


def _allowed(church, me) -> bool:
    import rate_limit
    return rate_limit.allow_strict("member_action", f"{church['business']['id']}|{me['id']}")


@router.post("/my/lead/groups/notes", include_in_schema=False)
async def care_notes(request: Request):
    """Chief's note to each person who's missed the last three gatherings
    (group_care): a page of drafts, each sent by the leader from their own
    chat."""
    import group_care
    import group_gatherings as gg
    import group_lead
    import member_messaging_rules as rules
    import member_portal_groups as mpg
    import member_portal_messaging as mpm
    import rate_limit
    from member_portal import _shell
    from member_portal_church import _signed_in
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return _go("/my/lead", err="preview" if unavailable == "preview" else "error")
    if not me:
        return _go("/my")
    form = await request.form()
    gid = str(form.get("group_id") or "")
    if not _FID.match(gid):
        return _go("/my/lead")
    biz = church["business"]
    v = await asyncio.to_thread(group_lead.view, biz, me, gid)
    if v is None:
        return _go(f"/my/lead/groups/{gid}", err="error")
    if not v or str(v["g"]["id"]) != gid:
        return _go("/my/lead")
    if not mpm.turned_on(biz):
        return _go(f"/my/lead/groups/{gid}", err="notes_off")
    missing = v.get("missing") or []
    if not any(not rules.is_teen(p) for p in missing):          # nobody, or only teens: no note to send
        return _go(f"/my/lead/groups/{gid}", err="notes_none")
    if not rate_limit.allow_strict("care_notes", f"{biz['id']}|{me['id']}"):
        return _go(f"/my/lead/groups/{gid}", err="slow")
    g = v["g"]
    mode = g.get("name_display") or "full"
    rows = [{**p, "teen": rules.is_teen(p)} for p in missing[:group_care.PEOPLE_MAX]]
    nxt = (v.get("meet") or {}).get("next")
    when = gg.when_text(g, nxt) if nxt else ""
    first = (me.get("name") or "").strip().split(" ")[0]
    notes, by_chief = await asyncio.to_thread(
        group_care.draft, str(biz["id"]), g.get("name") or "the group", first, f"on {when}" if when else "",
        [{"id": p["id"], "first": mpg.display_name(p, "first")} for p in rows if not p["teen"]])
    body = group_care.render(g, rows, notes, by_chief, ic=mpg._ic, esc=_e,
                             face=lambda p: mpg._face(p, "gs-av m", mode), name=lambda p: mpg.display_name(p, mode))
    head = (f'<header class="ld-head" style="flex-direction:column;align-items:flex-start;gap:6px">'
            f'<p class="gl-eb">{_e(g.get("name") or "Your group")}</p><h1 class="ld-hello">A note to <em>each</em></h1></header>')
    css = f"{LEAD_CSS}{mpg.GROUP_CSS}{group_lead.GL_CSS}{group_care.CARE_CSS}"
    html = _shell(biz, church.get("site"), "A note to each", f'<style>{css}</style><div class="ld-wide gl">{head}{body}</div>',
                  tab="lead", who=me, back=(f"/my/lead/groups/{gid}", g.get("name") or "My group"))
    from fastapi.responses import HTMLResponse
    from member_portal import _SECURE_HEADERS
    return HTMLResponse(html, headers=_SECURE_HEADERS)


@router.get("/my/lead/groups/{group_id}/desk", include_in_schema=False)
async def desk(group_id: str, request: Request):
    """The leader's desk's left and middle columns (group_desk), as JSON,
    fetched only on a wide screen."""
    import group_desk
    import group_lead
    import member_portal_groups as mpg
    import member_portal_messaging as mpm
    from fastapi.responses import JSONResponse
    from member_portal_church import _signed_in
    no_store = {"Cache-Control": "no-store"}
    church, me, unavailable = await _signed_in(request)
    if unavailable or not me or not _FID.match(group_id):
        return JSONResponse({"error": "gone"}, status_code=404, headers=no_store)
    biz = church["business"]
    v = await asyncio.to_thread(group_lead.view, biz, me, group_id)
    if v is None:
        return JSONResponse({"error": "unavailable"}, status_code=503, headers=no_store)
    if not v or str(v["g"]["id"]) != group_id:
        return JSONResponse({"error": "gone"}, status_code=404, headers=no_store)
    rows = (await asyncio.to_thread(mpm.inbox_rows, str(biz["id"]), str(me["id"]))) if mpm.turned_on(biz) else ([], [])
    cv = await asyncio.to_thread(mpg.chat_view, biz, v["g"], me)
    side = group_desk.side(rows, group_id, [str(x["id"]) for x in v["groups"]], esc=_e, ic=mpg._ic)
    middle, script = await asyncio.to_thread(group_desk.middle, biz, request, me, v, cv)
    script = re.sub(r"^\s*<script>|</script>\s*$", "", script or "")
    return JSONResponse({"side": side, "middle": middle, "script": script}, headers=no_store)


@router.post("/my/lead/answer", include_in_schema=False)
async def answer(request: Request):
    from member_portal_church import _signed_in
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return _go("/my/lead", err="preview" if unavailable == "preview" else "error")
    if not me:
        return _go("/my")
    if not cfu.is_church(church["business"]):
        raise HTTPException(404, "Not found")
    form = await request.form()
    yes = str(form.get("answer") or "") == "yes"
    try:
        ok = await asyncio.to_thread(cfu.answer_invite, church["business"]["id"], str(me["id"]),
                                     str(form.get("role_id") or ""), yes)
    except HTTPException:
        ok = False
    return _go("/my/lead", **({"done": "yes" if yes else "no"} if ok else {"err": "error"}))


async def _act(request: Request, what: str):
    church, me, err = await _leader(request)
    form = await request.form()
    fid = str(form.get("fid") or "")
    here = f"/my/lead/{fid}" if _FID.match(fid) else "/my/lead"
    if err:
        return _go(here, err=err)
    if not me:
        return _go("/my") if not church else _go("/my/lead")
    if not _allowed(church, me):
        return _go(here, err="slow")
    biz_id = church["business"]["id"]
    try:
        if what == "note":
            await asyncio.to_thread(cfu.leader_note, biz_id, me, fid, str(form.get("outcome") or "talked"),
                                    str(form.get("text") or ""), str(form.get("pastors_only") or "") == "yes")
            return _go(here, done="saved")
        if what == "step":
            row = await asyncio.to_thread(cfu.leader_advance, biz_id, me, fid)
            return _go("/my/lead", done="finished") if row.get("status") == "done" else _go(here, done="step")
        await asyncio.to_thread(cfu.leader_hand_back, biz_id, me, fid, str(form.get("text") or ""))
        return _go("/my/lead", done="back")
    except HTTPException as e:
        return _go("/my/lead" if e.status_code in (400, 404) else here, err="gone" if e.status_code in (400, 404) else "error")


@router.post("/my/lead/note", include_in_schema=False)
async def note(request: Request):
    return await _act(request, "note")


@router.post("/my/lead/step", include_in_schema=False)
async def step(request: Request):
    return await _act(request, "step")


@router.post("/my/lead/handback", include_in_schema=False)
async def handback(request: Request):
    return await _act(request, "handback")


async def _pray(request: Request, what: str):
    """I prayed, send a note, pass it on: only for a request handed to
    this member (church_prayer checks every one against leader_contact_id)."""
    import church_prayer
    church, me, err = await _leader(request)
    here = "/my/lead/prayer"
    if err:
        return _go(here, err=err)
    if not me:
        return _go("/my") if not church else _go("/my/lead")
    if not _allowed(church, me):
        return _go(here, err="slow")
    form = await request.form()
    rid = str(form.get("rid") or "")
    biz = church["business"]
    try:
        if what == "prayed":
            await asyncio.to_thread(church_prayer.prayed, biz["id"], me, rid)
            return _go(here, done="prayed")
        if what == "note":
            await church_prayer.send_note(biz, me, rid)
            return _go(here, done="noted")
        await asyncio.to_thread(church_prayer.pass_on, biz["id"], me, rid, str(form.get("to") or ""))
        return _go(here, done="passed")
    except HTTPException as e:
        if e.status_code == 404:
            return _go(here, err="prayer_gone")
        if e.status_code == 400 and what == "note":
            return _go(here, err="noemail")
        return _go(here, err="error")


@router.post("/my/lead/prayer/prayed", include_in_schema=False)
async def prayer_prayed(request: Request):
    return await _pray(request, "prayed")


@router.post("/my/lead/prayer/note", include_in_schema=False)
async def prayer_note(request: Request):
    return await _pray(request, "note")


@router.post("/my/lead/prayer/pass", include_in_schema=False)
async def prayer_pass(request: Request):
    return await _pray(request, "pass")


@router.post("/my/lead/family/{household_id}/touch", include_in_schema=False)
async def family_touch(household_id: str, request: Request):
    """A call, a visit, a text or a talk at church, logged by the family's
    shepherd (church_shepherding checks it is theirs). "Needs a pastor"
    emails the Lead Pastor at once, never another member."""
    import church_shepherding as shep
    church, me, err = await _leader(request)
    hid = household_id if _FID.match(household_id or "") else ""
    here = f"/my/lead/family/{hid}" if hid else "/my/lead/families"
    if err:
        return _go(here, err=err)
    if not me:
        return _go("/my") if not church else _go("/my/lead")
    if not _allowed(church, me):
        return _go(here, err="slow")
    if not hid:
        return _go("/my/lead/families", err="family_gone")
    form = await request.form()
    biz = church["business"]
    try:
        logged = await asyncio.to_thread(shep.log_touch, biz["id"], me, hid, str(form.get("kind") or "call"),
                                         str(form.get("note") or ""), str(form.get("needs_pastor") or "") == "yes")
    except HTTPException as e:
        return _go("/my/lead/families", err="family_gone") if e.status_code == 404 else _go(here, err="error")
    if logged["needs_pastor"]:
        told = await shep.tell_pastor(biz, me, logged)
        return _go(here, done="pastor" if told else "pastor_unsent")
    return _go(here, done="touched")


@router.post("/my/lead/tasks/{task_id}/done", include_in_schema=False)
async def task_done(task_id: str, request: Request):
    """A leader marks a task the office handed them done (church_leader_tasks
    checks it is theirs, at this church, and records who). Anyone else's
    task is a 404: their own list, saying it isn't theirs."""
    import church_leader_tasks as clt
    from fastapi.responses import HTMLResponse
    from member_portal import _SECURE_HEADERS
    from member_portal_church import _signed_in
    church, me, unavailable = await _signed_in(request)
    here = "/my/lead/tasks"
    if unavailable:
        return _go(here, err="preview" if unavailable == "preview" else "error")
    if not me:
        return _go("/my")
    biz = church["business"]
    if not cfu.is_church(biz) or not await asyncio.to_thread(clt.church_open, biz.get("id")):
        raise HTTPException(404, "Not found")
    if not _allowed(church, me):
        return _go(here, err="slow")
    try:
        await asyncio.to_thread(clt.mark_done, biz["id"], str(me["id"]), task_id)
    except HTTPException as e:
        if e.status_code != 404:
            return _go(here, err="error")
        await _context(request, biz, me)
        html, _ = await serve_tasks(request, biz, church.get("site"), me, err="task_gone")
        return HTMLResponse(html, status_code=404, headers=_SECURE_HEADERS)
    return _go(here, done="task_done")
