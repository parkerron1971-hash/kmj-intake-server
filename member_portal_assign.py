"""member_portal_assign.py — a leader's assignments on the member app's Lead
tab (docs/CHURCH_ASSIGNMENTS.md, PR C2).

Kevin, 2026-11-12, on the phone mock: "phone view idea is good. we can move
forward with that." Leaders don't get office logins; they use the member
app. So the Lead tab's assignments page carries the same things the office's
board does, for one of the church's people (church_over: `me` is a person):

    Your people ........ for a leader over others: each person under them,
                         their first assignment n of m, what's stuck (Send up
                         to whoever is over me) and what's next; Give an
                         assignment; Start their first assignment
    Your assignments ... what was handed to them: their first assignment n of
                         m, each with when it's due, what done means, what the
                         check counts and who it's from; Done, Stuck (with a
                         note), Not stuck (until it's sent up: #1801's rules)
    Sent up to you ..... what's stuck and was sent up to them; No longer stuck
    From the office .... what the office sent them for their area
                         (church_handovers); Got it

    GET  /my/lead/tasks                          the page (while CHURCH_ASSIGNMENTS
                                                 is open for the church; closed,
                                                 the tasks page as before)
    POST /my/lead/assignments/<id>/done          done
    POST /my/lead/assignments/<id>/stuck         {note}
    POST /my/lead/assignments/<id>/unstuck       not stuck (theirs, or sent up to them)
    POST /my/lead/assignments/<id>/raise         send one of their people's up
    POST /my/lead/assignments/give               {for, title, due_date?, done_when?}
    POST /my/lead/assignments/start              {for}
    POST /my/lead/handovers/<id>/seen            Got it

Every write is church_assignments' or church_handovers' own (each checks the
church, the person and who is over whom); here: a live session at this
church (member_portal_church._signed_in, which refuses a cross-site POST and
reads Origin: null by the browser's Sec-Fetch-Site), never the owner's
preview, the per-person rate limit, and a redirect back with a short code.
No office words and no ids on the page: ids ride in form addresses only.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)
router = APIRouter()

HERE = "/my/lead/tasks"
_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
NEXT_SHOWN = 3

DONE = {
    "as_done": "Done. Whoever is over you can see it.",
    "as_stuck": "Marked stuck. Whoever is over you can see why.",
    "as_unstuck": "No longer stuck.",
    "as_raised": "Sent up. They’ll hear about it within the hour.",
    "as_given": "Given. It’s on their list now.",
    "as_started": "Their first assignment is ready.",
    "as_seen": "Got it.",
}
ERRORS = {
    "error": "That didn’t save. Please try again.",
    "slow": "That was a lot at once. Wait a moment, then try again.",
    "preview": "This is a preview. Nothing is saved.",
    "as_gone": "That isn’t yours to change anymore.",
    "as_sent_up": "It was sent up, so whoever it went to says when it’s no longer stuck. Done still works.",
    "as_changed": "That changed just now. Here it is as it stands.",
    "as_said": "That didn’t come through. Check it and try again.",
    "as_nobody": "Nobody is over you here, so there’s no one to send it up to.",
    "as_done_already": "That one is done, so there’s nothing to send up.",
}

ASSIGN_CSS = """
.ld-tks.as-page{max-width:none;}
.as-sec{display:flex;flex-direction:column;gap:12px;}
.as-sec + .as-sec{margin-top:22px;}
.as-it{background:var(--s2);border-radius:var(--r-sm);padding:10px 12px;display:flex;flex-direction:column;gap:4px;font-size:14.5px;line-height:1.4;}
.as-it b{font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--fg2);}
.as-it.stuck{box-shadow:inset 0 0 0 1.5px #ff8a5c;}
.as-it.stuck b{color:#ff8a5c;}
.as-it.next b{color:var(--acc);}
.as-it p{margin:0;overflow-wrap:anywhere;}
.as-it form{margin:4px 0 0;}
.as-who{display:flex;flex-direction:column;gap:2px;}
.as-who b{font-size:17px;font-weight:650;}
.as-who small{font-size:13px;color:var(--fg2);}
.as-prog{height:6px;border-radius:99px;background:var(--s3);overflow:hidden;}
.as-prog i{display:block;height:100%;border-radius:99px;background:#5fd08a;}
.as-cnt{font-size:12.5px;color:var(--fg2);}
.as-meta{margin:0;font-size:13.5px;color:var(--fg2);line-height:1.45;overflow-wrap:anywhere;}
.as-meta b{color:var(--fg);font-weight:600;}
.as-acts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}
.as-acts form{display:contents;}
.as-acts .ld-btn,.as-acts .ld-ghost{min-height:46px;font-size:14.5px;}
.as-more summary{list-style:none;cursor:pointer;}
.as-more summary::-webkit-details-marker{display:none;}
.as-more[open] summary{margin-bottom:10px;}
.as-form{display:flex;flex-direction:column;gap:10px;}
.as-form label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--fg2);}
.as-form input{min-height:46px;border-radius:12px;border:.5px solid var(--line);background:var(--s2);color:var(--fg);
  padding:0 12px;font:inherit;font-size:16px;box-sizing:border-box;width:100%;}
.as-seen{font-size:12.5px;font-weight:650;color:#5fd08a;}
.as-link{color:var(--acc);font-weight:600;overflow-wrap:anywhere;}
"""


def _e(s: Any) -> str:
    import html
    return html.escape(str(s if s is not None else ""), quote=True)


def _first(name: Any) -> str:
    return (str(name or "").strip().split(" ") or [""])[0] or "someone"


def _days_since(ts: Any, now: datetime) -> Optional[int]:
    try:
        at = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return max(0, (now - at).days)


def _stuck_for(ts: Any, now: datetime) -> str:
    n = _days_since(ts, now)
    if n is None:
        return "Stuck"
    return "Stuck · today" if n == 0 else f"Stuck · {n} day{'s' if n != 1 else ''}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── What the page shows ──────────────────────────────────────────────

def view(biz: Dict[str, Any], contact_id: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Everything the page shows, for one of the church's people. A read
    that fails raises a 503 for the whole page, but for what the office sent
    (`from_office` None: that part says so, and the rest stands)."""
    import church_assignments as cas
    import church_handovers as cho
    import church_map
    import church_over as co
    now = now or _now()
    ch = co.Church(biz)
    me = co.who(co.PERSON, contact_id)
    with church_map.once():
        mine = cas.theirs(ch, me, me, False, now)
        people = cas.board(ch, me, now)["people"]
        up = co.above(ch, me) if any(p["stuck"] for p in people) else []
    try:
        office: Optional[List[Dict[str, Any]]] = cho.for_people(biz, [str(contact_id)], now)
    except HTTPException:
        print(f"[member_portal_assign] {str(biz.get('id'))[:8]}: what the office sent wasn't read", flush=True)
        office = None
    return {"mine": mine, "people": people, "up_to": up[0]["name"] if up else "", "from_office": office,
            "now": now}


def chief_line(v: Dict[str, Any]) -> str:
    """Chief's one line at the top: what's stuck under them first, then
    what's sent up to them, then their own next, then what the office sent."""
    now = v["now"]
    for p in v["people"]:
        for s in p.get("stuck_items") or []:
            if not s.get("raised"):
                n = _days_since(s.get("since"), now)
                since = f" {n} day{'s' if n != 1 else ''}" if n else ""
                return (f"{_first(p['name'])}’s “{s['title']}” has been stuck{since}. Help clear it, or send it up"
                        f"{' to ' + v['up_to'] if v.get('up_to') else ''}.")
    waiting = [r for r in v["mine"].get("raised_to_you") or [] if not r.get("resolved")]
    if waiting:
        r = waiting[0]
        return f"“{r['title']}” was sent up to you. When it’s cleared, tap No longer stuck."
    mine = v["mine"].get("open") or []
    late = [i for i in mine if i.get("late")]
    if late:
        return f"“{late[0]['title']}” is {late[0]['due_text'].lower()}. If it’s done, tap Done so they know."
    if mine:
        first = mine[0]
        when = first["due_text"][:1].lower() + first["due_text"][1:]
        n = len(mine)
        return f"{n} assignment{'s' if n != 1 else ''} handed to you. Next: “{first['title']}”, {when}."
    unseen = [h for h in v.get("from_office") or [] if not h.get("seen")]
    if unseen:
        return f"{unseen[0]['from']} sent you “{unseen[0]['title']}”. Tap Got it once you have it."
    if v["people"]:
        return "Nobody under you is stuck. Give someone an assignment, or start their first one."
    return "Nothing is waiting on you. When something is handed to you, it shows up here."


def _progress(first: Dict[str, int]) -> str:
    of = int(first.get("of") or 0)
    if not of:
        return ""
    done = int(first.get("done") or 0)
    pct = round(100 * done / of)
    return (f'<div class="as-prog" role="img" aria-label="First assignment {done} of {of}">'
            f'<i style="width:{pct}%"></i></div><span class="as-cnt">First assignment {done} of {of}</span>')


def _person_card(p: Dict[str, Any], up_to: str, now: datetime) -> str:
    """One person under them, as on the phone mock."""
    pid = p["id"]
    stuck = ""
    for s in p.get("stuck_items") or []:
        note = f"<p>{_e(s['note'])}</p>" if s.get("note") else ""
        if s.get("raised"):
            act = '<p class="as-meta">Sent up</p>'
        else:
            act = (f'<form method="post" action="/my/lead/assignments/{_e(s["id"])}/raise">'
                   f'<button class="ld-ghost" type="submit">Send up{" to " + _e(up_to) if up_to else ""}</button></form>')
        stuck += (f'<div class="as-it stuck"><b>{_e(_stuck_for(s.get("since"), now))}</b>'
                  f'<p>{_e(s["title"])}</p>{note}{act}</div>')
    nxt = "".join(f'<div class="as-it next"><b>{_e(i["due_text"])}</b><p>{_e(i["title"])}</p></div>'
                  for i in (p.get("next") or [])[:NEXT_SHOWN])
    first = p.get("first") or {}
    progress = _progress(first) or '<span class="as-cnt">No first assignment yet</span>'
    start = ""
    if first.get("to_make"):
        n = int(first["to_make"])
        label = "Start their first assignment" if not first.get("of") else f"Add {n} more to their first assignment"
        start = (f'<form method="post" action="/my/lead/assignments/start"><input type="hidden" name="for" value="{_e(pid)}">'
                 f'<button class="ld-ghost" type="submit">{_e(label)}</button></form>')
    give = (f'<details class="as-more"><summary class="ld-ghost">Give an assignment</summary>'
            f'<form class="as-form" method="post" action="/my/lead/assignments/give">'
            f'<input type="hidden" name="for" value="{_e(pid)}">'
            f'<label>What<input name="title" maxlength="200" required></label>'
            f'<label>By when<input name="due_date" type="date"></label>'
            f'<label>Done when<input name="done_when" maxlength="300"></label>'
            f'<button class="ld-btn" type="submit">Give it</button></form></details>')
    return (f'<section class="ld-pr" aria-label="{_e(p["name"])}">'
            f'<div class="as-who"><b>{_e(p["name"])}</b><small>{_e(p.get("why") or "")}</small></div>'
            f'{progress}{stuck}{nxt}{give}{start}</section>')


def _mine_card(i: Dict[str, Any], now: datetime) -> str:
    """One of their own assignments: Done, Stuck, Not stuck."""
    from member_app_ui import icon
    tid = i["id"]
    cls = "ld-due late" if i.get("late") else "ld-due"
    meta = []
    if i.get("done_when"):
        meta.append(f'<p class="as-meta"><b>Done when</b> {_e(i["done_when"])}</p>')
    if i.get("check") and i["check"].get("text"):
        meta.append(f'<p class="as-meta"><b>So far</b> {_e(i["check"]["text"])}</p>')
    if i.get("notes"):
        meta.append(f'<p class="ld-tk-notes">{_e(i["notes"])}</p>')
    meta.append(f'<p class="ld-tk-from">From {_e(i.get("from") or "the church office")}</p>')
    stuck = ""
    acts = [f'<form method="post" action="/my/lead/assignments/{_e(tid)}/done">'
            f'<button class="ld-btn" type="submit">{icon("check", 17)}Done</button></form>']
    if i.get("stuck"):
        note = f" {_e(i['stuck']['note'])}" if i["stuck"].get("note") else ""
        if i.get("raised"):
            to = i["raised"].get("to") or ""
            stuck = (f'<div class="as-it stuck"><b>{_e(_stuck_for(i["stuck"].get("since"), now))}</b>'
                     f'<p>{note.strip() or "Stuck"}</p><p class="as-meta">Sent up{" to " + _e(to) if to else ""}. '
                     f'They’ll say when it’s no longer stuck.</p></div>')
        else:
            stuck = (f'<div class="as-it stuck"><b>{_e(_stuck_for(i["stuck"].get("since"), now))}</b>'
                     f'<p>{note.strip() or "Stuck"}</p></div>')
            acts.append(f'<form method="post" action="/my/lead/assignments/{_e(tid)}/unstuck">'
                        f'<button class="ld-ghost" type="submit">Not stuck</button></form>')
    else:
        acts.append(f'<details class="as-more"><summary class="ld-ghost">Stuck</summary>'
                    f'<form class="as-form" method="post" action="/my/lead/assignments/{_e(tid)}/stuck">'
                    f'<label>What’s in the way<textarea class="ld-ta" name="note" maxlength="500"></textarea></label>'
                    f'<button class="ld-btn" type="submit">Mark it stuck</button></form></details>')
    return (f'<section class="ld-pr ld-tk" aria-label="{_e(i["title"])}">'
            f'<div class="ld-tk-top"><b>{_e(i["title"])}</b><span class="{cls}">{_e(i["due_text"])}</span></div>'
            f'{"".join(meta)}{stuck}<div class="as-acts">{"".join(acts)}</div></section>')


def _raised_card(r: Dict[str, Any], now: datetime) -> str:
    whose = f"{_first(r['whose'])}’s · " if r.get("whose") else ""
    note = (r.get("stuck") or {}).get("note") or ""
    if r.get("resolved"):
        return (f'<div class="as-it"><b>{_e(whose)}Done now</b><p>{_e(r["title"])}</p></div>')
    by = f'<p class="as-meta">Sent up by {_e(r["sent_up_by"])}</p>' if r.get("sent_up_by") else ""
    return (f'<div class="as-it stuck"><b>{_e(whose)}{_e(_stuck_for((r.get("stuck") or {}).get("since"), now))}</b>'
            f'<p>{_e(r["title"])}</p>{"<p>" + _e(note) + "</p>" if note else ""}{by}'
            f'<form method="post" action="/my/lead/assignments/{_e(r["id"])}/unstuck">'
            f'<button class="ld-ghost" type="submit">No longer stuck</button></form></div>')


def _office_card(h: Dict[str, Any]) -> str:
    bits = [b for b in (h.get("from"), h.get("department"),
                        f"for {h['for_date_text']}" if h.get("for_date_text") else "") if b]
    note = f'<p class="ld-tk-notes">{_e(h["note"])}</p>' if h.get("note") else ""
    link = (f'<a class="as-link" href="{_e(h["link"])}" target="_blank" rel="noopener noreferrer">Open the link</a>'
            if str(h.get("link") or "").startswith("https://") else "")
    act = ('<span class="as-seen">Seen</span>' if h.get("seen") else
           f'<form method="post" action="/my/lead/handovers/{_e(h["id"])}/seen">'
           f'<button class="ld-btn" type="submit">Got it</button></form>')
    return (f'<section class="ld-pr ld-tk" aria-label="{_e(h["title"])}">'
            f'<div class="ld-tk-top"><b>{_e(h["title"])}</b></div>'
            f'<p class="ld-tk-from">{_e(" · ".join(bits))}</p>{note}{link}{act}</section>')


def body(v: Optional[Dict[str, Any]]) -> str:
    """The page's own part (inside the header and the switcher)."""
    from member_app_ui import icon
    from member_portal import band
    if v is None:
        return '<p class="mp-err" role="alert">Your assignments couldn’t load just now. Please try again in a moment.</p>'
    now = v["now"]
    chief = (f'<div class="ld-chief"><small>{icon("star", 12)}From Chief</small><p>{_e(chief_line(v))}</p></div>')
    left = ""
    if v["people"]:
        n = len(v["people"])
        left += (f'<div class="as-sec"><div class="mb-sh"><h2>Your people</h2><span>{n} '
                 f'{"person" if n == 1 else "people"}</span></div>'
                 + "".join(_person_card(p, v.get("up_to") or "", now) for p in v["people"]) + '</div>')
    mine = v["mine"]
    items = sorted((mine.get("open") or []) + (mine.get("stuck") or []),
                   key=lambda i: (not i.get("stuck"), not i.get("late"), i.get("due") or "9999-12-31"))
    mine_html = f'<div class="as-sec"><div class="mb-sh"><h2>Your assignments</h2><span>{len(items)} open</span></div>'
    mine_html += _progress(mine.get("first") or {})
    mine_html += "".join(_mine_card(i, now) for i in items) if items else (
        '<p class="ld-quiet">Nothing is handed to you right now.</p>')
    done = mine.get("done") or []
    if done:
        lis = "".join(f'<li><div class="ld-by"><b>{_e(d["title"])}</b>'
                      f'<span class="ld-tag">{"Counted" if d.get("checked") else "Done"}</span></div></li>' for d in done)
        mine_html += (f'<details class="ld-card ld-back ld-tk-done"><summary class="ld-ghost">Done lately · {len(done)}'
                      f'</summary><ul class="ld-notes">{lis}</ul></details>')
    left += mine_html + '</div>'
    right = ""
    raised = mine.get("raised_to_you") or []
    if raised:
        right += ('<div class="as-sec"><div class="mb-sh"><h2>Sent up to you</h2>'
                  f'<span>{sum(1 for r in raised if not r.get("resolved"))} waiting</span></div>'
                  + "".join(_raised_card(r, now) for r in raised) + '</div>')
    office = v.get("from_office")
    if office is None:
        right += ('<div class="as-sec"><div class="mb-sh"><h2>From the office</h2></div>'
                  '<p class="mp-err" role="alert">What the office sent couldn’t load just now.</p></div>')
    elif office:
        right += ('<div class="as-sec"><div class="mb-sh"><h2>From the office</h2>'
                  f'<span>{sum(1 for h in office if not h.get("seen"))} new</span></div>'
                  + "".join(_office_card(h) for h in office) + '</div>')
    quiet = (f'<p class="ld-quiet">{icon("lock", 14)}<span>You see only what’s handed to you and the people under '
             f'you. When you tap Done, whoever is over you sees it.</span></p>')
    return f'<div class="ld-tks as-page">{chief}{band(left, right)}{quiet}</div>'


def render(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], active: List[Dict[str, Any]],
           v: Optional[Dict[str, Any]], seg: str, *, err: str = "") -> str:
    """/my/lead/tasks, while assignments are open for the church."""
    import member_portal_lead as mpl
    from member_portal import _shell
    done = DONE.get(request.query_params.get("done") or "") or mpl.DONE.get(request.query_params.get("done") or "")
    code = err or request.query_params.get("err") or ""
    bad = ERRORS.get(code) or mpl.ERRORS.get(code)
    flash = (f'<p class="mp-err mp-flash" role="alert">{_e(bad)}</p>' if bad else
             f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>' if done else "")
    first = (me.get("name") or "").strip().split(" ")[0] or "friend"
    head = (f'<header class="ld-head"><h1 class="ld-hello">{mpl._word()}, <em>{_e(first)}</em></h1>'
            f'<div class="ld-roles">{"".join(f"<span class=ld-role>{_e(mpl._role_text(r))}</span>" for r in active)}'
            f'</div></header>')
    return _shell(biz, site, "Assignments",
                  f'<style>{mpl.LEAD_CSS}{mpl.TASK_CSS}{ASSIGN_CSS}</style><div class="ld-wide">{flash}{head}{seg}'
                  f'{body(v)}</div>', tab="lead", who=me, wide=True)


def section(biz: Dict[str, Any], contact_id: Any) -> Optional[Dict[str, int]]:
    """The switcher's count for Assignments: what's open and handed to them,
    what was sent up to them and is still stuck, and what the office sent
    that they haven't seen. {"open": 0} when it can't be read: the entry
    still shows. None while the switch is closed for the church."""
    import church_over as co
    import sb_clients
    from urllib.parse import quote
    if not co.church_open(biz):
        return None
    b, c = quote(str(biz["id"]), safe=""), quote(str(contact_id), safe="")
    n = 0
    rows = sb_clients.sb_get_as_service(
        f"/tasks?business_id=eq.{b}&or=(assigned_contact_id.eq.{c},raised_to_contact_id.eq.{c})&status=neq.done"
        "&select=id,assigned_contact_id,raised_to_contact_id,stuck_at&limit=200")
    if isinstance(rows, list):
        n += sum(1 for r in rows if str(r.get("assigned_contact_id") or "") == str(contact_id)
                 or (str(r.get("raised_to_contact_id") or "") == str(contact_id) and r.get("stuck_at")))
    seen = sb_clients.sb_get_as_service(f"/church_handovers?business_id=eq.{b}&contact_id=eq.{c}&seen_at=is.null"
                                        "&select=id&limit=100")
    if isinstance(seen, list):
        n += len(seen)
    return {"open": n}


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], *, err: str = ""):
    """GET /my/lead/tasks while assignments are open: (html, status)."""
    import church_follow_up as cfu
    import church_shepherding as shep
    import group_lead
    import member_portal_lead as mpl
    cid = str(me["id"])
    my_roles = await asyncio.to_thread(cfu.roles_for, biz["id"], cid) or []
    active = [r for r in my_roles if r.get("status") == "active"]
    led = await asyncio.to_thread(group_lead.led_groups, biz["id"], cid) or []
    fams = 0
    if active:
        fv = await asyncio.to_thread(shep.my_families, biz["id"], cid)
        fams = len((fv or {}).get("families") or [])
    try:
        v = await asyncio.to_thread(view, biz, cid)
    except HTTPException as e:
        logger.warning("lead assignments read failed: %s", e.detail)
        v = None
    if mpl.TASKS.get() is None:
        mpl.TASKS.set({"open": 0})
    seg = mpl._seg("tasks", any(not mpl._is_prayer(r) for r in active), any(mpl._is_prayer(r) for r in active),
                   0, fams, len(led))
    return render(biz, site, request, me, active, v, seg, err=err), 200 if v is not None else 503


# ─── POST ─────────────────────────────────────────────────────────────

def _go(**q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return RedirectResponse(f"{HERE}?{qs}" if qs else HERE, status_code=303, headers=_SECURE_HEADERS)


def _code(e: HTTPException) -> str:
    """A refusal as a short code for the page (never its words in the URL)."""
    import church_assignments as cas
    said = str(e.detail or "")
    if e.status_code == 403 and said in (cas.SENT_UP,):
        return "as_sent_up"
    if e.status_code == 409 and said == cas.JUST_SENT_UP:
        return "as_sent_up"
    if e.status_code == 409 and said.startswith("Nobody is over you"):
        return "as_nobody"
    if e.status_code == 409 and said.startswith("That one is done"):
        return "as_done_already"
    if e.status_code in (403, 404):
        return "as_gone"
    if e.status_code == 409:
        return "as_changed"
    if e.status_code == 400:
        return "as_said"
    return "error"


async def _act(request: Request, fn, ok: str):
    """A live session at this church, never the preview, the switch open,
    not too fast; then fn(biz, me, form) in a thread; back to the page."""
    import church_follow_up as cfu
    import church_over as co
    import rate_limit
    from member_portal_church import _signed_in
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return _go(err="preview" if unavailable == "preview" else "error")
    if not me:
        return RedirectResponse("/my", status_code=303)
    biz = church["business"]
    if not cfu.is_church(biz) or not await asyncio.to_thread(co.church_open, biz):
        raise HTTPException(404, "Not found")
    if not rate_limit.allow_strict("member_action", f"{biz['id']}|{me['id']}"):
        return _go(err="slow")
    form = await request.form()
    try:
        await asyncio.to_thread(fn, biz, me, form)
    except HTTPException as e:
        if e.status_code >= 500:
            logger.warning("lead assignments write failed: %s", e.detail)
        return _go(err=_code(e))
    return _go(done=ok)


def _ch_me(biz: Dict[str, Any], me: Dict[str, Any]):
    import church_over as co
    return co.Church(biz), co.who(co.PERSON, me["id"])


def _task_of(ch, task_id: str):
    import church_assignments as cas
    if not _ID.match(task_id or ""):
        raise HTTPException(404, "Not found")
    return cas._task(ch, task_id)


def _for(form) -> Dict[str, str]:
    import church_over as co
    pid = str(form.get("for") or "")
    if not _ID.match(pid):
        raise HTTPException(400, "That person isn't valid")
    return co.who(co.PERSON, pid.lower())


@router.post("/my/lead/assignments/{task_id}/done", include_in_schema=False)
async def done(task_id: str, request: Request):
    def go(biz, me, form):
        import church_assignments as cas
        ch, who = _ch_me(biz, me)
        t = _task_of(ch, task_id)
        cas._ready(ch)
        cas.change(ch, who, t, {"done": True})
    return await _act(request, go, "as_done")


@router.post("/my/lead/assignments/{task_id}/stuck", include_in_schema=False)
async def stuck(task_id: str, request: Request):
    def go(biz, me, form):
        import church_assignments as cas
        ch, who = _ch_me(biz, me)
        t = _task_of(ch, task_id)
        cas._ready(ch)
        cas.change(ch, who, t, {"stuck": str(form.get("note") or "")})
    return await _act(request, go, "as_stuck")


@router.post("/my/lead/assignments/{task_id}/unstuck", include_in_schema=False)
async def unstuck(task_id: str, request: Request):
    def go(biz, me, form):
        import church_assignments as cas
        ch, who = _ch_me(biz, me)
        t = _task_of(ch, task_id)
        cas._ready(ch)
        cas.change(ch, who, t, {"stuck": None})
    return await _act(request, go, "as_unstuck")


@router.post("/my/lead/assignments/{task_id}/raise", include_in_schema=False)
async def raise_up(task_id: str, request: Request):
    def go(biz, me, form):
        import church_assignments as cas
        ch, who = _ch_me(biz, me)
        t = _task_of(ch, task_id)
        cas._ready(ch)
        note = form.get("note")
        cas.raise_up(ch, who, t, str(note) if note else None)
    return await _act(request, go, "as_raised")


@router.post("/my/lead/assignments/give", include_in_schema=False)
async def give(request: Request):
    def go(biz, me, form):
        import church_assignments as cas
        ch, who = _ch_me(biz, me)
        target = _for(form)
        cas._allowed(ch, who, target, self_ok=False)
        cas._ready(ch)
        cas.give(ch, who, target, {"title": form.get("title"), "due_date": form.get("due_date") or None,
                                   "done_when": form.get("done_when")})
    return await _act(request, go, "as_given")


@router.post("/my/lead/assignments/start", include_in_schema=False)
async def start(request: Request):
    def go(biz, me, form):
        import church_assignments as cas
        import church_startup as cs
        import church_work_checks as cw
        ch, who = _ch_me(biz, me)
        target = _for(form)
        cas._allowed(ch, who, target, self_ok=False)
        cas._ready(ch)
        cs.start(ch, who, target, cw.Ctx(ch.business, cas._now(), ch.tz).today)
    return await _act(request, go, "as_started")


@router.post("/my/lead/handovers/{handover_id}/seen", include_in_schema=False)
async def seen(handover_id: str, request: Request):
    def go(biz, me, form):
        import church_handovers as cho
        cho.mark_seen(biz["id"], [str(me["id"])], handover_id)
    return await _act(request, go, "as_seen")
