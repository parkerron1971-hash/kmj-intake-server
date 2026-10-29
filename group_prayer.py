"""
group_prayer.py — a church group's prayer wall (the group page's Prayer tab).

Part 3 of the approved canvas "Church Groups, Together" (boards Prayer and
Settings; Kevin, 2026-10-20: "anything that I could be missing"). Requests
the group prays over together:

  * a member asks "This group" (on the wall, by first name) or "Only the
    pastors" (private: Prayer & care, as /my/prayer does; the group never
    sees it — member_portal_church.save_prayer)
  * words about harm, abuse or a death (church_prayer.needs_pastor, or the
    message check's crisis verdict) never reach the wall: they go to a
    pastor, and the wall shows only that a pastor has one
  * "I'm praying" on a request (the asker hears, once a day); the asker can
    mark it answered with a word of praise, and the group can say "Praise God"
  * the asker can take their request down; so can the group's leaders

Every request is checked first (msg_screen), like every message and post.
The routes live in member_portal_groups (/my/groups/prayer...). Records:
group_prayers, group_prayer_marks (supabase/APPLY-2026-10-20-group-prayer.sql),
written only here.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger(__name__)

BODY_MAX = 1000
PRAISE_MAX = 500
PASTOR_CARD_DAYS = 7        # "a pastor has it" stays on the wall a week
ANSWERED_DAYS = 120         # the Answered view looks back this far
MARKS = ("praying", "praise")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def first(name: Any) -> str:
    return (str(name or "").strip().split(" ") or [""])[0] or "Someone"


# ─── reading ─────────────────────────────────────────────────────────


def wall(business_id: str, group_id: str, me_id: str, *, answered: bool = False) -> Optional[Dict[str, Any]]:
    """{'items', 'answered_n', 'prayed_month'} for the Prayer tab, or None
    on a failed read. Each item: the request, its asker (by first name; a
    pastor card has none), counts and this person's own marks."""
    now = _now()
    rows = sb_clients.sb_get_as_service(
        f"/group_prayers?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}&removed_at=is.null"
        f"&created_at=gte.{_q((now - timedelta(days=ANSWERED_DAYS)).isoformat())}"
        f"&select=id,contact_id,body,to_pastor,answered_at,praise,created_at&order=created_at.desc&limit=300")
    if not isinstance(rows, list):
        return None
    cut = (now - timedelta(days=PASTOR_CARD_DAYS)).isoformat()
    rows = [r for r in rows if not (r.get("to_pastor") and str(r.get("created_at") or "") < cut)]
    answered_n = sum(1 for r in rows if r.get("answered_at"))
    shown = [r for r in rows if bool(r.get("answered_at")) == answered]
    ids = [str(r["id"]) for r in rows]
    marks: List[Dict[str, Any]] = []
    for i in range(0, len(ids), 150):
        got = sb_clients.sb_get_as_service(
            f"/group_prayer_marks?business_id=eq.{_q(business_id)}&prayer_id=in.({','.join(ids[i:i + 150])})"
            f"&select=prayer_id,contact_id,kind,created_at&limit=20000")
        if not isinstance(got, list):
            return None
        marks += got
    people_ids = sorted({str(r["contact_id"]) for r in shown if r.get("contact_id")} |
                        {str(m["contact_id"]) for m in marks})
    folks: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(people_ids), 150):
        got = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(business_id)}&id=in.({','.join(people_ids[i:i + 150])})"
            f"&select=id,name,birthdate,metadata&limit=500")
        if not isinstance(got, list):
            return None
        folks.update({str(c["id"]): c for c in got})
    month = (now - timedelta(days=30)).isoformat()
    items = []
    for r in shown:
        mine = [m for m in marks if str(m["prayer_id"]) == str(r["id"])]
        praying = [m for m in mine if m["kind"] == "praying"]
        items.append({
            **r, "asker": folks.get(str(r.get("contact_id") or "")) if not r.get("to_pastor") else None,
            "mine": str(r.get("contact_id") or "") == str(me_id),
            "praying_n": len(praying), "praise_n": sum(1 for m in mine if m["kind"] == "praise"),
            "i_pray": any(str(m["contact_id"]) == str(me_id) for m in praying),
            "i_praise": any(str(m["contact_id"]) == str(me_id) and m["kind"] == "praise" for m in mine),
            "who_prays": [folks[str(m["contact_id"])] for m in praying if str(m["contact_id"]) in folks][:3],
        })
    prayed = sum(1 for m in marks if m["kind"] == "praying" and str(m.get("created_at") or "") >= month)
    return {"items": items, "answered_n": answered_n, "prayed_month": prayed}


def _prayer(business_id: str, prayer_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/group_prayers?id=eq.{_q(prayer_id)}&business_id=eq.{_q(business_id)}&removed_at=is.null"
        f"&select=id,group_id,contact_id,body,to_pastor,answered_at&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else {}


# ─── writing ─────────────────────────────────────────────────────────


async def ask(business: Dict[str, Any], me: Dict[str, Any], group: Dict[str, Any], body: str,
              to_pastors: bool) -> Tuple[bool, str]:
    """A member's request: on the wall, or to the pastors. (ok, code)."""
    import asyncio
    import church_prayer
    import msg_screen
    import member_portal_church as mpc
    biz_id = str(business["id"])
    text = re.sub(r"[ \t]+\n", "\n", str(body or "")).strip()[:BODY_MAX]
    if not text:
        return False, "empty"
    source = f"Group: {group.get('name') or 'a group'}"
    full = await asyncio.to_thread(mpc.load_me, biz_id, me["id"]) or me
    if to_pastors:
        ok = await asyncio.to_thread(mpc.save_prayer, biz_id, full, text, True, False, False, source)
        return (True, "prayer_pastors") if ok else (False, "error")
    danger = church_prayer.needs_pastor(text)
    if not danger:
        try:
            verdict = await msg_screen.screen(biz_id, text)
        except msg_screen.ScreenUnavailable:
            return False, "post_busy"
        if verdict == "harm":
            return False, "prayer_no"
        danger = verdict == "self_harm"
    if danger:
        # A pastor hears first; the wall shows only that a pastor has one.
        ok = await asyncio.to_thread(mpc.save_prayer, biz_id, full, text, True, False, False, source)
        if not ok:
            return False, "error"
        await asyncio.to_thread(sb_clients.sb_post_as_service, "/group_prayers", {
            "business_id": biz_id, "group_id": str(group["id"]), "contact_id": str(me["id"]), "to_pastor": True})
        return True, "prayer_pastor_first"
    rows = await asyncio.to_thread(sb_clients.sb_post_as_service, "/group_prayers", {
        "business_id": biz_id, "group_id": str(group["id"]), "contact_id": str(me["id"]), "body": text})
    if not isinstance(rows, list) or not rows:
        return False, "error"
    import member_push
    member_push.tell_group_prayer(business, group, str(rows[0]["id"]), me)
    return True, "prayer_up"


def mark(business: Dict[str, Any], me: Dict[str, Any], prayer_id: str, kind: str,
         member_of) -> Tuple[bool, str, str]:
    """Toggle "I'm praying" or "Praise God". (ok, code, group_id).
    `member_of(group_id)` says whether this person is in the group."""
    biz_id = str(business["id"])
    if kind not in MARKS:
        return False, "error", ""
    p = _prayer(biz_id, prayer_id)
    if p is None:
        return False, "error", ""
    if not p or p.get("to_pastor"):
        return False, "prayer_gone", str((p or {}).get("group_id") or "")
    gid = str(p["group_id"])
    inside = member_of(gid)
    if inside is None:
        return False, "error", gid
    if not inside:
        return False, "not_in_group", gid
    if kind == "praise" and not p.get("answered_at"):
        return False, "error", gid
    where = (f"/group_prayer_marks?prayer_id=eq.{_q(p['id'])}&contact_id=eq.{_q(me['id'])}"
             f"&kind=eq.{kind}&business_id=eq.{_q(biz_id)}")
    had = sb_clients.sb_get_as_service(where + "&select=kind&limit=1")
    if not isinstance(had, list):
        return False, "error", gid
    if had:
        return (True, "unmarked", gid) if sb_clients.sb_delete_as_service(where) else (False, "error", gid)
    rows = sb_clients.sb_post_as_service(
        "/group_prayer_marks?on_conflict=prayer_id,contact_id,kind",
        {"prayer_id": str(p["id"]), "contact_id": str(me["id"]), "business_id": biz_id, "kind": kind},
        prefer="return=representation,resolution=ignore-duplicates")
    if not isinstance(rows, list):
        return False, "error", gid
    if kind == "praying" and str(p.get("contact_id") or "") != str(me["id"]):
        import member_push
        member_push.tell_group_praying(business, gid, str(p["id"]), str(p.get("contact_id") or ""))
    return True, "praying" if kind == "praying" else "praised", gid


def answer(business_id: str, me: Dict[str, Any], prayer_id: str, praise: str) -> Tuple[bool, str, str]:
    """The asker marks their request answered, with a word of praise."""
    p = _prayer(business_id, prayer_id)
    if p is None:
        return False, "error", ""
    if not p or p.get("to_pastor"):
        return False, "prayer_gone", str((p or {}).get("group_id") or "")
    gid = str(p["group_id"])
    if str(p.get("contact_id") or "") != str(me["id"]):
        return False, "not_yours", gid
    saved = sb_clients.sb_patch_as_service(
        f"/group_prayers?id=eq.{_q(p['id'])}&business_id=eq.{_q(business_id)}&removed_at=is.null",
        {"answered_at": _now().isoformat(), "praise": " ".join(str(praise or "").split())[:PRAISE_MAX]})
    return (True, "answered", gid) if isinstance(saved, list) and saved else (False, "error", gid)


def remove(business_id: str, me: Dict[str, Any], prayer_id: str, is_leader) -> Tuple[bool, str, str]:
    """The asker, or one of the group's leaders, takes a request down."""
    p = _prayer(business_id, prayer_id)
    if p is None:
        return False, "error", ""
    if not p:
        return False, "prayer_gone", ""
    gid = str(p["group_id"])
    if str(p.get("contact_id") or "") != str(me["id"]):
        lead = is_leader(gid)
        if lead is None:
            return False, "error", gid
        if not lead:
            return False, "not_yours", gid
    saved = sb_clients.sb_patch_as_service(
        f"/group_prayers?id=eq.{_q(p['id'])}&business_id=eq.{_q(business_id)}&removed_at=is.null",
        {"removed_at": _now().isoformat(), "removed_by": str(me["id"])})
    return (True, "prayer_down", gid) if isinstance(saved, list) and saved else (False, "error", gid)


# ─── the Prayer tab ──────────────────────────────────────────────────

PRAYER_CSS = """
.gp-stat{display:flex;align-items:baseline;gap:8px;margin:2px 0 14px;color:var(--fg2);font-size:14px;}
.gp-stat b{font-family:var(--mb-serif);font-size:30px;font-weight:500;color:var(--fg);line-height:1;}
.gp-ask{display:flex;flex-direction:column;gap:10px;}
.gp-ask textarea{min-height:92px;border:0;outline:none;border-radius:var(--r-md);background:var(--s2);color:var(--fg);padding:12px 14px;
  font:inherit;font-size:16px;line-height:1.4;resize:vertical;box-shadow:inset 0 0 0 1px var(--line);}
.gp-to{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.gp-to label{display:flex;gap:10px;align-items:flex-start;padding:12px;border-radius:var(--r-md);background:var(--s2);cursor:pointer;
  box-shadow:inset 0 0 0 1px var(--line);}
.gp-to label:has(input:checked){box-shadow:inset 0 0 0 1.5px var(--teal-ink,var(--acc));background:var(--teal-deep,var(--s2));}
.gp-to input{width:18px;height:18px;margin:2px 0 0;flex:none;accent-color:var(--teal);}
.gp-to span{display:flex;flex-direction:column;gap:2px;min-width:0;}
.gp-to b{font-size:14.5px;}
.gp-to small{font-size:12.5px;color:var(--fg3);line-height:1.3;}
@media (max-width:360px){.gp-to{grid-template-columns:1fr;}}
.gp-filter{display:flex;gap:6px;margin:18px 0 12px;}
.gp-filter a{display:inline-flex;align-items:center;min-height:36px;padding:0 14px;border-radius:999px;background:var(--s1);color:var(--fg2);
  text-decoration:none;font-size:13.5px;font-weight:650;}
.gp-filter a[aria-current]{background:var(--teal-deep,var(--s2));color:var(--teal-ink,var(--fg));}
.gp-list{display:flex;flex-direction:column;gap:12px;}
.gp-card{display:flex;flex-direction:column;gap:10px;}
.gp-who{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--fg3);}
.gp-who b{color:var(--fg);font-size:15px;font-weight:650;}
.gp-body{margin:0;font-size:15.5px;line-height:1.45;white-space:pre-line;overflow-wrap:anywhere;}
.gp-praise{margin:0;padding:10px 12px;border-radius:var(--r-md);background:var(--s2);font-size:14.5px;line-height:1.4;}
.gp-tag{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:700;color:var(--gold,var(--acc));}
.gp-acts{display:flex;align-items:center;flex-wrap:wrap;gap:8px;}
.gp-acts form{margin:0;}
.gp-btn{display:inline-flex;align-items:center;gap:6px;min-height:40px;padding:0 14px;border-radius:999px;border:0;background:var(--s2);
  color:var(--fg);font:inherit;font-size:14px;font-weight:650;cursor:pointer;}
.gp-btn.on{background:var(--teal-deep);color:var(--teal-ink);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--teal-ink) 40%,transparent);}
.gp-btn .mb-ic{width:16px;height:16px;}
.gp-n{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--fg2);}
.gp-n .gs-faces .gs-av{width:22px;height:22px;font-size:9px;}
.gp-more{margin-left:auto;display:flex;gap:2px;}
.gp-link{display:inline-flex;align-items:center;min-height:36px;padding:0 10px;border:0;background:none;color:var(--fg3);font:inherit;
  font-size:13px;font-weight:600;cursor:pointer;border-radius:999px;}
.gp-link.warn{color:var(--error);}
.gp-ans summary{list-style:none;cursor:pointer;}
.gp-ans summary::-webkit-details-marker{display:none;}
.gp-ans[open]{flex-basis:100%;}
.gp-ans form{display:flex;flex-direction:column;gap:8px;margin-top:8px;}
.gp-ans textarea{min-height:64px;border:0;outline:none;border-radius:var(--r-md);background:var(--s2);color:var(--fg);padding:10px 12px;
  font:inherit;font-size:15px;box-shadow:inset 0 0 0 1px var(--line);}
.gp-pastor{display:flex;gap:10px;align-items:flex-start;color:var(--fg2);font-size:14px;line-height:1.4;}
"""


def render_tab(biz: Dict[str, Any], g: Dict[str, Any], w: Optional[Dict[str, Any]], *, me_id: str, leader: bool,
               size: int, answered: bool, ic, face, when, esc) -> str:
    """The Prayer tab's html. `ic`, `face`, `when`, `esc` are the group
    page's own helpers (icons, avatars, "2 hours ago", escaping)."""
    gid = esc(g["id"])
    church = esc(biz.get("name") or "the church")
    base = f"/my/groups/{gid}/prayer"
    if w is None:
        return '<p class="mp-err" role="alert">The prayer wall couldn’t load just now. Please try again in a moment.</p>'
    others = max(size - 1, 0)
    ask = (f'<form class="gs-card gp-ask" method="post" action="/my/groups/prayer"><input type="hidden" name="group_id" value="{gid}">'
           f'<label class="gs-l" for="gp-b">Carry each other in prayer</label>'
           f'<textarea id="gp-b" name="body" maxlength="{BODY_MAX}" required placeholder="What can we pray about?"></textarea>'
           f'<div class="gp-to" role="radiogroup" aria-label="Who sees it">'
           f'<label><input type="radio" name="to" value="group" checked><span><b>This group</b>'
           f'<small>{"Your " + str(others) + (" person prays" if others == 1 else " people pray") + " with you" if others else "Everyone who joins prays with you"}</small></span></label>'
           f'<label><input type="radio" name="to" value="pastors"><span><b>Only the pastors</b>'
           f'<small>Private. The group never sees it</small></span></label></div>'
           f'<button class="gs-btn" type="submit">{ic("hand-heart", 16)}Send</button>'
           f'<p class="gs-fine">The group sees your first name. If someone may be in danger, or it’s about abuse or a death, '
           f'it goes straight to a pastor at {church}, not the wall.</p></form>')
    stat = (f'<p class="gp-stat"><b>{int(w["prayed_month"])}</b>'
            f'{"prayer" if w["prayed_month"] == 1 else "prayers"} prayed this month</p>')
    tabs = (f'<nav class="gp-filter" aria-label="Prayer wall"><a href="{base}"{"" if answered else " aria-current=page"}>Praying for</a>'
            f'<a href="{base}?view=answered"{" aria-current=page" if answered else ""}>Answered · {int(w["answered_n"])}</a></nav>')
    cards = []
    for p in w["items"]:
        pid = esc(p["id"])
        hidden = f'<input type="hidden" name="id" value="{pid}">'
        if p.get("to_pastor"):
            note = ("You shared something a pastor needs to hear first. It went to them, not the wall."
                    if p.get("mine") else "A pastor has a request from this group. They’ll reach out.")
            cards.append(f'<article class="gs-card gp-card"><p class="gp-pastor">{ic("shield", 18)}<span>{esc(note)}</span></p>'
                         f'<span class="gp-who">{esc(when(p.get("created_at")))}</span></article>')
            continue
        asker = p.get("asker") or {}
        who = "You" if p.get("mine") else esc(first(asker.get("name")))
        meta = esc(when(p.get("created_at")))
        tag = ""
        if p.get("answered_at"):
            said = when(p.get("answered_at"))
            meta += f' · answered {esc(said[:1].lower() + said[1:])}'
            tag = f'<span class="gp-tag">{ic("star", 13)}Answered</span>'
        praise = f'<p class="gp-praise">{esc(p["praise"])}</p>' if p.get("praise") else ""
        acts = []
        if p.get("answered_at"):
            acts.append(f'<form method="post" action="/my/groups/prayer/mark">{hidden}<input type="hidden" name="kind" value="praise">'
                        f'<button class="gp-btn{" on" if p.get("i_praise") else ""}" type="submit" aria-pressed="{"true" if p.get("i_praise") else "false"}">'
                        f'{ic("star", 16)}Praise God</button></form>')
            n = " · ".join(x for x in ((f'{p["praying_n"]} prayed' if p["praying_n"] else ""),
                                       (f'{p["praise_n"]} said praise God' if p["praise_n"] else "")) if x)
            if n:
                acts.append(f'<span class="gp-n">{esc(n)}</span>')
        else:
            if not p.get("mine"):
                acts.append(f'<form method="post" action="/my/groups/prayer/mark">{hidden}<input type="hidden" name="kind" value="praying">'
                            f'<button class="gp-btn{" on" if p.get("i_pray") else ""}" type="submit" aria-pressed="{"true" if p.get("i_pray") else "false"}">'
                            f'{ic("hand-heart", 16)}{"Praying" if p.get("i_pray") else "I’m praying"}</button></form>')
            if p["praying_n"]:
                faces = "".join(face(x) for x in p.get("who_prays") or [])
                acts.append(f'<span class="gp-n"><span class="gs-faces" aria-hidden="true">{faces}</span>{p["praying_n"]} praying</span>')
        more = []
        if p.get("mine") and not p.get("answered_at"):
            more.append(f'<details class="gp-ans"><summary class="gp-link">Answered?</summary>'
                        f'<form method="post" action="/my/groups/prayer/answer">{hidden}'
                        f'<label class="mp-sr" for="gp-pr-{pid}">What happened</label>'
                        f'<textarea id="gp-pr-{pid}" name="praise" maxlength="{PRAISE_MAX}" placeholder="Tell the group what God did (optional)"></textarea>'
                        f'<button class="gs-btn soft sm" type="submit">Mark it answered</button></form></details>')
        if p.get("mine") or leader:
            more.append(f'<form method="post" action="/my/groups/prayer/remove">{hidden}'
                        f'<button class="gp-link{"" if p.get("mine") else " warn"}" type="submit">{"Remove" if p.get("mine") else "Take down"}</button></form>')
        if more:
            acts.append(f'<span class="gp-more">{"".join(more)}</span>')
        cards.append(f'<article class="gs-card gp-card"><div class="gp-who">{face(asker) if asker else ""}<b>{who}</b>'
                     f'<span>{meta}</span>{tag}</div><p class="gp-body">{esc(p["body"])}</p>{praise}'
                     f'<div class="gp-acts">{"".join(acts)}</div></article>')
    empty = ('<p class="gs-empty">No answered prayers yet. When a request is answered, it shows here.</p>' if answered else
             '<p class="gs-empty">Nothing on the wall yet. Be the first to ask the group to pray.</p>')
    listing = f'<div class="gp-list">{"".join(cards)}</div>' if cards else empty
    return f'{stat}{"" if answered else ask}{tabs}{listing}'
