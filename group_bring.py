"""
group_bring.py — "Bring something": who's bringing what to a gathering.

From the approved canvas "Church Groups, Together" (boards Meet and Main:
"Bring a dish · 2 open"). On the group page's Meet tab:

  * a group's leaders list what a gathering needs (a main dish, greens,
    drinks, plates and cups), for the next gathering or one of the few
    after it; each thing is checked like a Board post before the group
    sees it
  * people in the group tap "I'll bring it" on one open thing, or Undo.
    One thing each, so the list spreads around (a partial unique index
    holds it if two taps race)
  * "2 still open" / "All covered", on the Meet tab and the group's Home
  * the 5 PM reminder tells each person what they said they'd bring

Someone who has left the group no longer holds a thing: it reads as open
and the next person can take it. The routes live in member_portal_groups
(/my/groups/meet/bring...).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import sb_clients

WHAT_MAX = 60
MAX_ITEMS = 30          # things on one gathering's list
AHEAD = 8               # gatherings ahead a leader can plan for


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def load(business_id: str, group_id: str, days: List[date]) -> Optional[List[Dict[str, Any]]]:
    """The lists for these gatherings, oldest thing first; None on a failed
    read."""
    if not days:
        return []
    rows = sb_clients.sb_get_as_service(
        f"/group_bring?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}"
        f"&met_on=in.({','.join(d.isoformat() for d in days)})"
        f"&select=id,met_on,what,contact_id,created_at&order=created_at.asc&limit=1000")
    return rows if isinstance(rows, list) else None


def holder(item: Dict[str, Any], members: set) -> Optional[str]:
    """Who is bringing it — only while they're still in the group."""
    c = str(item.get("contact_id") or "")
    return c if c and c in members else None


def still_open(items: List[Dict[str, Any]], members: set) -> int:
    return sum(1 for i in items if not holder(i, members))


def by_day(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for i in items:
        out.setdefault(str(i["met_on"])[:10], []).append(i)
    return out


def open_label(n: int) -> str:
    return "All covered" if n == 0 else f"{n} still open"


# ─── writing ─────────────────────────────────────────────────────────


def _roster(business_id: str, group_id: str) -> Optional[set]:
    rows = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}&select=contact_id&limit=5000")
    return {str(r["contact_id"]) for r in rows} if isinstance(rows, list) else None


def _item(business_id: str, group_id: str, item_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/group_bring?id=eq.{_q(item_id)}&business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}"
        f"&select=id,met_on,what,contact_id&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else {}


async def add(business: Dict[str, Any], me: Dict[str, Any], group_id: str, day: str, what: str) -> Tuple[bool, str]:
    """A leader adds one thing to a coming gathering's list."""
    import asyncio
    import group_gatherings as gg
    import msg_screen
    g, now_local, role = await asyncio.to_thread(gg._ready, business, me, group_id, leader=True)
    if not g:
        return False, role
    what = " ".join(str(what or "").split())[:WHAT_MAX]
    if not what:
        return False, "bring_empty"
    coming = gg.upcoming(g, now_local, AHEAD)
    try:
        d = date.fromisoformat(str(day or "")[:10]) if day else (coming[0] if coming else None)
    except ValueError:
        d = None
    if d is None or d not in coming:
        return False, "no_gathering"
    biz_id = str(business["id"])
    have = await asyncio.to_thread(load, biz_id, str(g["id"]), [d])
    if have is None:
        return False, "error"
    if len(have) >= MAX_ITEMS:
        return False, "bring_full"
    try:
        verdict = await msg_screen.screen(biz_id, what)
    except msg_screen.ScreenUnavailable:
        return False, "post_busy"
    if verdict != "ok":
        return False, "post_no"
    rows = await asyncio.to_thread(sb_clients.sb_post_as_service, "/group_bring", {
        "business_id": biz_id, "group_id": str(g["id"]), "met_on": d.isoformat(), "what": what,
        "added_by": str(me["id"])}, prefer="return=representation")
    return (True, "bring_added") if isinstance(rows, list) and rows else (False, "error")


def remove(business: Dict[str, Any], me: Dict[str, Any], group_id: str, item_id: str) -> Tuple[bool, str]:
    """A leader takes one thing off the list."""
    import group_gatherings as gg
    g, _, role = gg._ready(business, me, group_id, leader=True)
    if not g:
        return False, role
    ok = sb_clients.sb_delete_as_service(
        f"/group_bring?id=eq.{_q(item_id)}&business_id=eq.{_q(business['id'])}&group_id=eq.{_q(g['id'])}")
    return (True, "bring_removed") if ok else (False, "error")


def claim(business: Dict[str, Any], me: Dict[str, Any], group_id: str, item_id: str) -> Tuple[bool, str]:
    """"I'll bring it": one open thing, for a gathering still coming, one
    thing each."""
    import group_gatherings as gg
    g, now_local, role = gg._ready(business, me, group_id)
    if not g:
        return False, role
    biz_id, gid, mine = str(business["id"]), str(g["id"]), str(me["id"])
    it = _item(biz_id, gid, item_id)
    if it is None:
        return False, "error"
    if not it:
        return False, "bring_gone"
    d = date.fromisoformat(str(it["met_on"])[:10])
    if d not in gg.upcoming(g, now_local, AHEAD):
        return False, "bring_gone"
    if str(it.get("contact_id") or "") == mine:
        return True, "bring_claimed"
    members = _roster(biz_id, gid)
    same_day = load(biz_id, gid, [d])
    if members is None or same_day is None:
        return False, "error"
    if holder(it, members):
        return False, "bring_taken"
    if any(str(i.get("contact_id") or "") == mine for i in same_day):
        return False, "bring_one_each"
    # Only if nobody took it in the meantime (or the one who had it left).
    was = str(it.get("contact_id") or "")
    cond = f"&contact_id=eq.{_q(was)}" if was else "&contact_id=is.null"
    rows = sb_clients.sb_patch_as_service(
        f"/group_bring?id=eq.{_q(it['id'])}&business_id=eq.{_q(biz_id)}{cond}",
        {"contact_id": mine, "claimed_at": datetime.now(timezone.utc).isoformat()})
    if not isinstance(rows, list):
        return False, "error"
    return (True, "bring_claimed") if rows else (False, "bring_taken")


def unclaim(business: Dict[str, Any], me: Dict[str, Any], group_id: str, item_id: str) -> Tuple[bool, str]:
    """Undo: only your own."""
    import group_gatherings as gg
    g, _, role = gg._ready(business, me, group_id)
    if not g:
        return False, role
    rows = sb_clients.sb_patch_as_service(
        f"/group_bring?id=eq.{_q(item_id)}&business_id=eq.{_q(business['id'])}&group_id=eq.{_q(g['id'])}"
        f"&contact_id=eq.{_q(me['id'])}", {"contact_id": None, "claimed_at": None})
    return (True, "bring_undone") if isinstance(rows, list) else (False, "error")


def bringing(business_id: str, group_id: str, day: date) -> Dict[str, str]:
    """{contact_id: what they said they'd bring} for one gathering (the 5 PM
    reminder); empty when the read fails, so the reminder still goes."""
    rows = load(business_id, group_id, [day]) or []
    return {str(r["contact_id"]): str(r["what"]) for r in rows if r.get("contact_id")}


# ─── the Meet tab ────────────────────────────────────────────────────

BRING_CSS = """
.gb-list{border-radius:var(--r-lg);background:var(--s1);overflow:hidden;margin:0 0 12px;padding:0;list-style:none;}
.gb-slot{display:flex;align-items:center;gap:12px;padding:12px 16px;position:relative;}
.gb-slot+.gb-slot::before{content:"";position:absolute;top:0;left:70px;right:0;height:.5px;background:var(--line);}
.gb-slot .gs-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px;}
.gb-slot .gs-t b{font-size:15px;font-weight:620;overflow-wrap:anywhere;}
.gb-slot .gs-t small{font-size:13px;color:var(--fg2);}
.gb-slot form{margin:0;flex:none;}
.gb-open{width:42px;height:42px;border-radius:50%;flex:none;display:grid;place-items:center;border:1.5px dashed var(--fg3);color:var(--fg3);}
.gb-x{width:40px;height:40px;flex:none;display:grid;place-items:center;border:0;border-radius:50%;background:none;color:var(--fg3);cursor:pointer;}
.gb-x:hover{background:var(--s2);color:var(--fg);}
.gb-add{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;padding:12px 16px 16px;}
.gb-add label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--fg2);flex:1;min-width:150px;}
.gb-add input,.gb-add select{min-height:44px;border:0;outline:none;border-radius:var(--r-md);background:var(--s2);color:var(--fg);
  padding:0 12px;font:inherit;font-size:15px;box-shadow:inset 0 0 0 1px var(--line);}
.gb-add label.gb-day{flex:0 0 auto;min-width:0;}
.gb-for{margin:-6px 0 10px;font-size:13px;color:var(--fg2);}
.gb-plan summary{list-style:none;cursor:pointer;}
.gb-plan summary::-webkit-details-marker{display:none;}
.gb-plan .gb-add{padding:12px 0 0;}
.gb-sh .gb-n{font-size:15px;font-weight:500;color:var(--fg3);}
"""


def render(g: Dict[str, Any], v: Dict[str, Any], *, me_id: str, leader: bool, people: List[Dict[str, Any]],
           ic, face, esc, name) -> str:
    """Each coming gathering that has a list; for a leader, the way to start
    one. Nothing at all for a member when no list is out."""
    import group_gatherings as gg
    coming: List[date] = v.get("coming") or []
    lists = v.get("bring") or {}
    if not coming:
        return ""
    gid = esc(g["id"])
    hidden = f'<input type="hidden" name="group_id" value="{gid}">'
    members = {p["id"]: p for p in people}
    out: List[str] = []
    i_have = {d: any(str(i.get("contact_id") or "") == me_id for i in lists.get(d.isoformat(), [])) for d in coming}
    add_form = ""
    if leader:
        days = ""
        if len(coming) > 1:
            opts = "".join(f'<option value="{d.isoformat()}">{d.strftime("%a, %b")} {d.day}</option>' for d in coming)
            days = f'<label class="gb-day">For<select name="day">{opts}</select></label>'
        add_form = (f'<form class="gb-add" method="post" action="/my/groups/meet/bring/add">{hidden}'
                    f'<label>Add something to bring<input type="text" name="what" maxlength="{WHAT_MAX}" required '
                    f'placeholder="Like dessert or drinks" autocomplete="off"></label>{days}'
                    f'<button class="gs-btn soft sm" type="submit">{ic("plus", 15)}Add</button></form>')
    shown = [d for d in coming if lists.get(d.isoformat())]
    for n, d in enumerate(shown):
        items = lists[d.isoformat()]
        left = still_open(items, set(members))
        title_id = f"gb-{d.isoformat()}"
        when = "" if d == coming[0] else f'<p class="gb-for">For {esc(gg.when_text(g, d).split(" · ")[0])}</p>'
        rows = []
        for it in items:
            who = holder(it, set(members))
            mine = who == me_id
            if who:
                disc = face(members[who])
                sub = "You" if mine else esc(name(members[who]))
            else:
                disc = f'<span class="gb-open" aria-hidden="true">{ic("plus", 16)}</span>'
                sub = "Nobody yet"
            act = ""
            if mine:
                act = (f'<form method="post" action="/my/groups/meet/bring/undo">{hidden}<input type="hidden" name="item" value="{esc(it["id"])}">'
                       f'<button class="gs-btn soft sm" type="submit" aria-label="Undo: I won’t bring {esc(it["what"])}">Undo</button></form>')
            elif not who and not i_have[d]:
                act = (f'<form method="post" action="/my/groups/meet/bring/claim">{hidden}<input type="hidden" name="item" value="{esc(it["id"])}">'
                       f'<button class="gs-btn tint sm" type="submit" aria-label="I’ll bring {esc(it["what"])}">I’ll bring it</button></form>')
            if leader:
                act += (f'<form method="post" action="/my/groups/meet/bring/remove">{hidden}<input type="hidden" name="item" value="{esc(it["id"])}">'
                        f'<button class="gb-x" type="submit" aria-label="Take {esc(it["what"])} off the list">{ic("x", 16)}</button></form>')
            rows.append(f'<li class="gb-slot">{disc}<span class="gs-t"><b>{esc(it["what"])}</b><small>{sub}</small></span>{act}</li>')
        out.append(f'<section aria-labelledby="{title_id}"><div class="mb-sh gb-sh"><h2 id="{title_id}">Bring something</h2>'
                   f'<span class="gb-n">{open_label(left)}</span></div>{when}<ul class="gb-list">{"".join(rows)}'
                   f'{f"<li>{add_form}</li>" if leader and n == 0 else ""}</ul></section>')
    if leader and not shown:
        out.append(f'<details class="gs-card gb-plan"><summary class="gs-ph"><span class="gs-t"><b>Bring something</b>'
                   f'<small>Sharing a meal? List what’s needed, and people tap I’ll bring it.</small></span>{ic("chevron", 18)}</summary>'
                   f'{add_form}</details>')
    return "".join(out)
