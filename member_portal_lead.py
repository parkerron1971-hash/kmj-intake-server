"""member_portal_lead.py — the Lead tab: a leader's side of a member page.

Kevin, 2026-10-17: leaders "see assigned work that chief gives, make
comments from conversations they had with members". They are members first,
so it lives in the member page they already sign in to (a code, no
password), as a Lead tab; on a computer the list and the person sit side by
side (design canvas LG4Q97HqtEM4ByyXmmSrCP, boards 3-6).

    GET  /my/lead                 my people (and an invitation to answer)
    GET  /my/lead/<follow_up_id>  one person: the card, the path, the notes
    POST /my/lead/answer          yes or not now to a role
    POST /my/lead/note            log a conversation
    POST /my/lead/step            mark the current step done
    POST /my/lead/handback        hand them back to the office

A leader only ever sees the follow-ups handed to them (church_follow_up
checks every read and write against leader_contact_id), and never another
person's pastors-only note. The owner's preview reads and never writes.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

import church_follow_up as cfu

logger = logging.getLogger(__name__)
router = APIRouter()

_FID = re.compile(r"^[0-9a-fA-F-]{36}$")

DONE = {
    "saved": "Saved. The pastors can see it on their page.",
    "step": "Step done.",
    "finished": "That’s the whole path. Thank you.",
    "back": "Handed back to the office.",
    "yes": "You’re leading now. People Chief hands to you show up here.",
    "no": "Got it. Nothing changes for you.",
}
ERRORS = {
    "error": "That didn’t save. Please try again.",
    "slow": "That was a lot at once. Wait a moment, then try again.",
    "preview": "This is a preview. Nothing is saved.",
    "gone": "That person isn’t handed to you anymore.",
}

LEAD_CSS = """
body:has(.ld-wide) .mb-top,body:has(.ld-wide) .mp-shell{max-width:1180px;}
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
    if r.get("role") == "team_leader" and r.get("scope"):
        return f"Team leader · {r['scope']}"
    return r.get("label") or cfu.ROLE_LABELS.get(r.get("role"), "Leader")


def _invite_card(r: Dict[str, Any], church: str) -> str:
    what = cfu.role_name(r)
    return (f'<section class="ld-invite" aria-label="An invitation">'
            f'<h2>Will you lead <em>{_e(what)}</em>?</h2>'
            f'<p>{_e(church)} asked. Say yes and the people Chief hands to you show up here, with what they wrote '
            f'and the next step for each. You only see the people handed to you, never giving or prayer requests.</p>'
            f'<form method="post" action="/my/lead/answer" class="ld-two">'
            f'<input type="hidden" name="role_id" value="{_e(r["id"])}">'
            f'<button class="ld-btn" type="submit" name="answer" value="yes">Yes, I’ll lead</button>'
            f'<button class="ld-ghost" type="submit" name="answer" value="no">Not now</button></form></section>')


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
           view: Optional[Dict[str, Any]], selected: str = "", *, now: Optional[datetime] = None) -> str:
    from member_portal import _shell
    now = now or datetime.now(timezone.utc)
    church = (biz.get("name") or "Your church").strip()
    done = DONE.get(request.query_params.get("done") or "")
    err = ERRORS.get(request.query_params.get("err") or "")
    flash = (f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>' if err else
             f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>' if done else "")
    active = [r for r in my_roles if r.get("status") == "active"]
    invited = [r for r in my_roles if r.get("status") == "invited"]
    first = (me.get("name") or "").strip().split(" ")[0] or "friend"
    head = (f'<header class="ld-head"><h1 class="ld-hello">Lead, <em>{_e(first)}</em></h1>'
            f'<div class="ld-roles">{"".join(f"<span class=ld-role>{_e(_role_text(r))}</span>" for r in active)}</div></header>')
    invites = "".join(_invite_card(r, church) for r in invited)
    if not active:
        body = (f'{flash}{head}{invites}' if invites else
                f'{flash}{head}<section class="ld-card"><p>You don’t lead anything at {_e(church)} yet. When the church '
                f'asks you to, it shows up here.</p><p><a href="/my">Back to Home</a></p></section>')
        return _shell(biz, site, "Lead", f'<style>{LEAD_CSS}</style><div class="ld-wide">{body}</div>', tab="lead", who=me)
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
    return _shell(biz, site, title, f'<style>{LEAD_CSS}</style><div class="ld-wide">{flash}{head}{invites}{grid}</div>',
                  tab="lead", who=me, back=("/my/lead", "Lead") if sel else None)


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], sub: str):
    """GET /my/lead and /my/lead/<id>: (html, status)."""
    selected = sub[len("/my/lead/"):] if sub.startswith("/my/lead/") else ""
    if selected and not _FID.match(selected):
        return render(biz, site, request, me, [], None), 404
    my_roles = await asyncio.to_thread(cfu.roles_for, biz["id"], str(me["id"]))
    if my_roles is None:
        return render(biz, site, request, me, [{"status": "active", "role": "", "label": ""}], None), 503
    view = None
    if any(r["status"] == "active" for r in my_roles):
        view = await asyncio.to_thread(cfu.leader_view, biz["id"], str(me["id"]))
    return render(biz, site, request, me, my_roles, view, selected), 200 if view is not None or not my_roles else 503


# ─── POST ─────────────────────────────────────────────────────────────

def _go(target: str, **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    if target != "/my/lead" and not re.fullmatch(r"/my/lead/[0-9a-fA-F-]{36}", target):
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
