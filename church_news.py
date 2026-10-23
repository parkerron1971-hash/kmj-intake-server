"""
church_news.py — the church's news in the member app, and the office's side of it.

Kevin, 2026-10-23: "a news feed area in the app that flows news and
announcements from the church. kinda how facebook has a news feed allow
people to comment but not make a post themselves only admins and certain
leaders can make a post." The approved canvas "Church News & Celebrations"
(Hfrz3Y174kbDmJv1G4puVq), and his calls the same day:

  * News lives on Home ("From the church") with a News page behind it,
    no new tab (member_portal_news).
  * Who posts: the office, the church's pastoral leaders (an active senior
    or pastoral role), and the people the church picks
    (church_news_posters) post to the WHOLE church. Any group leader posts
    to their own ministry or group (group_id), which only its people see.
  * Members never post. They react (Love, Praying, Amen, Celebrate) and
    comment; teenagers comment too, because every comment is checked first
    (msg_screen): 'ok' shows, 'harm' is held for the safety officers,
    'self_harm' is held and the pastor is told (the writer sees 988).
    Comments open once the church has its two safety officers, like group
    chat (messaging_router.MIN_OFFICERS).

Records (supabase/APPLY-2026-10-23-church-news.sql): church_posts,
church_post_reactions, church_post_seen, church_post_comments,
church_post_comment_loves, church_post_reports, church_news_posters. Only
this file writes them.

Office API (any seat reads; a seat that can edit writes):
  GET  /church/news                 posts with how each did, the safety
                                    picture, who may post, held comments
  POST /church/news                 a new post (now or later)
  POST /church/news/{id}/pin        pin to the top for a week, or unpin
  POST /church/news/{id}/remove     take a post down
  GET  /church/news/held            a safety officer's seat: the held comments' words
  POST /church/news/held/{id}       a safety officer's seat: show or keep hidden
  POST /church/news/posters         pick who posts to the whole church
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("church_news")
router = APIRouter(tags=["church-news"])

KINDS = ("announcement", "event", "photos", "celebration", "praise", "message", "milestone", "good_news")
REACTIONS = ("love", "pray", "amen", "cheer")
COMMENT_MODES = ("on", "prayers", "off")
TITLE_MAX, BODY_MAX, COMMENT_MAX, LABEL_MAX = 120, 4000, 1000, 80
PIN_DAYS = 7
FEED_READ = 80
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# The News page's filters: which kinds each one shows. A post that carries
# an event counts as an event; one that carries photos, as photos.
FILTERS = (("", "All"), ("announcements", "Announcements"), ("celebrations", "Celebrations"),
           ("photos", "Photos"), ("events", "Events"))
FILTER_KINDS = {"announcements": {"announcement", "message", "praise"},
                "celebrations": {"celebration", "milestone", "good_news"},
                "photos": {"photos"}, "events": {"event"}}
_RANK = {"viewer": 1, "member": 2, "manager": 3, "admin": 4, "owner": 5}
POST_SELECT = ("id,kind,title,body,group_id,posted_by,office_user,author_label,source,status,pinned_until,important,"
               "comments,publish_at,attach,person_id,created_at")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(v: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None


def _ids(xs) -> str:
    return ",".join(_q(x) for x in sorted({str(x) for x in xs if x}))


# ─── who ─────────────────────────────────────────────────────────────


def my_groups(business_id: str, contact_id: str) -> Optional[List[str]]:
    rows = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}&select=group_id&limit=500")
    return None if rows is None else [str(r["group_id"]) for r in rows]


def led_groups(business_id: str, contact_id: str) -> Optional[List[Dict[str, Any]]]:
    """The running groups and ministries this person leads: where they post."""
    rows = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}&role=eq.leader"
        f"&select=group_id&limit=100")
    if rows is None:
        return None
    if not rows:
        return []
    groups = sb_clients.sb_get_as_service(
        f"/groups?business_id=eq.{_q(business_id)}&id=in.({_ids(r['group_id'] for r in rows)})&active=eq.true"
        f"&select=id,name,kind&order=name.asc")
    return None if groups is None else [{"id": str(g["id"]), "name": g.get("name") or "Your group", "kind": g.get("kind")}
                                        for g in groups]


def is_pastoral(business_id: str, contact_id: str) -> Optional[bool]:
    """An active senior or pastoral role (Pastors, Elders, Ministers…)."""
    import church_roles as cr
    import messaging_router as mr
    roles = sb_clients.sb_get_as_service(
        f"/church_leader_roles?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}"
        f"&status=eq.active&select=role&limit=50")
    if roles is None:
        return None
    if not roles:
        return False
    defs = cr.defs(str(business_id))
    if defs is None:
        return None
    by = cr.by_key(defs)
    return any((by.get(r["role"]) or cr.LEGACY.get(r["role"]) or {}).get("job") in mr.PASTORAL_JOBS for r in roles)


def picked(business_id: str, contact_id: str) -> Optional[bool]:
    rows = sb_clients.sb_get_as_service(
        f"/church_news_posters?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}&select=contact_id&limit=1")
    return None if rows is None else bool(rows)


def can_post(business_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    """{'church': posts to everyone, 'groups': [the ministries they lead]}.
    None when a read failed."""
    pastoral, chosen, led = is_pastoral(business_id, contact_id), picked(business_id, contact_id), \
        led_groups(business_id, contact_id)
    if pastoral is None or chosen is None or led is None:
        return None
    return {"church": bool(pastoral or chosen), "pastoral": bool(pastoral), "groups": led}


def comments_open(business: Dict[str, Any]) -> bool:
    """Comments need the church's two safety officers (like group chat), and
    the church can turn them off (settings.news.comments = false)."""
    import messaging_router as mr
    news = ((business or {}).get("settings") or {}).get("news") or {}
    if isinstance(news, dict) and news.get("comments") is False:
        return False
    try:
        return mr.officer_count(str(business["id"])) >= mr.MIN_OFFICERS
    except Exception:  # noqa: BLE001 — a failed read never opens comments
        return False


# ─── reading ─────────────────────────────────────────────────────────


def _people(business_id: str, ids) -> Optional[Dict[str, Dict[str, Any]]]:
    out: Dict[str, Dict[str, Any]] = {}
    ids = sorted({str(i) for i in ids if i})
    for i in range(0, len(ids), 150):
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(business_id)}&id=in.({_ids(ids[i:i + 150])})&select=id,name,birthdate,metadata")
        if rows is None:
            return None
        out.update({str(r["id"]): r for r in rows})
    return out


def is_live(p: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """Posted, not taken down, and its time has come."""
    if p.get("status") != "posted" or p.get("removed_at"):
        return False
    at = _ts(p.get("publish_at"))
    return at is None or at <= (now or _now())


def pinned_now(p: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    until = _ts(p.get("pinned_until"))
    return bool(until and until > (now or _now()))


def when_of(p: Dict[str, Any]) -> str:
    return str(p.get("publish_at") or p.get("created_at") or "")


def matches(p: Dict[str, Any], filt: str) -> bool:
    if not filt:
        return True
    att = p.get("attach") if isinstance(p.get("attach"), dict) else {}
    if filt == "events" and att.get("event"):
        return True
    if filt == "photos" and att.get("photos"):
        return True
    return p.get("kind") in FILTER_KINDS.get(filt, set())


def _decorate(business_id: str, rows: List[Dict[str, Any]], me_id: str) -> Optional[List[Dict[str, Any]]]:
    """Authors, ministry names, reaction counts and mine, comment counts,
    and what each post carries (an event, a sermon)."""
    if not rows:
        return []
    ids = _ids(r["id"] for r in rows)
    b = _q(business_id)
    rx = sb_clients.sb_get_as_service(f"/church_post_reactions?business_id=eq.{b}&post_id=in.({ids})"
                                      f"&select=post_id,contact_id,kind&limit=50000")
    cm = sb_clients.sb_get_as_service(f"/church_post_comments?business_id=eq.{b}&post_id=in.({ids})&status=eq.shown"
                                      f"&select=post_id&limit=50000")
    authors = _people(business_id, [r.get("posted_by") for r in rows] + [r.get("person_id") for r in rows])
    gids = {str(r["group_id"]) for r in rows if r.get("group_id")}
    groups = (sb_clients.sb_get_as_service(f"/groups?business_id=eq.{b}&id=in.({_ids(gids)})&select=id,name")
              if gids else [])
    if rx is None or cm is None or authors is None or groups is None:
        return None
    gname = {str(g["id"]): g.get("name") or "" for g in groups}
    pastoral: Dict[str, bool] = {}
    for r in rows:
        pid = str(r["id"])
        mine = [x for x in rx if str(x["post_id"]) == pid]
        r["rx"] = {k: sum(1 for x in mine if x["kind"] == k) for k in REACTIONS}
        r["my_rx"] = sorted({x["kind"] for x in mine if str(x["contact_id"]) == str(me_id)})
        r["comment_n"] = sum(1 for x in cm if str(x["post_id"]) == pid)
        r["author"] = authors.get(str(r.get("posted_by") or "")) or {}
        r["person"] = authors.get(str(r.get("person_id") or "")) or {}
        r["group_name"] = gname.get(str(r.get("group_id") or ""), "")
        r["pinned"] = pinned_now(r)
        a = str(r.get("posted_by") or "")
        if a and a not in pastoral:
            pastoral[a] = bool(is_pastoral(business_id, a))
        r["pastor"] = pastoral.get(a, False)
        if not isinstance(r.get("attach"), dict):
            r["attach"] = {}
    _attachments(business_id, rows)
    return rows


def _attachments(business_id: str, rows: List[Dict[str, Any]]) -> None:
    """The sermon a post carries (title, series). Events are matched by the
    page against the member's own upcoming list. Best effort: a post shows
    without its card rather than not at all."""
    sids = {str(r["attach"].get("sermon")) for r in rows if UUID.match(str(r["attach"].get("sermon") or ""))}
    if not sids:
        return
    got = sb_clients.sb_get_as_service(
        f"/sermons?business_id=eq.{_q(business_id)}&id=in.({_ids(sids)})&published=eq.true"
        f"&select=id,title,speaker,scripture,series_id")
    by = {str(s["id"]): s for s in (got or [])}
    for r in rows:
        s = by.get(str(r["attach"].get("sermon") or ""))
        if s:
            r["sermon"] = s


def feed(business_id: str, me_id: str, filt: str = "") -> Optional[List[Dict[str, Any]]]:
    """What the News page shows this member, pinned first, then newest. None
    when a read failed (the page says try again, never "no news")."""
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?business_id=eq.{_q(business_id)}&status=eq.posted&removed_at=is.null"
        f"&select={POST_SELECT}&order=created_at.desc&limit={FEED_READ}")
    groups = my_groups(business_id, me_id)
    if rows is None or groups is None:
        return None
    now = _now()
    mine = set(groups)
    rows = [r for r in rows if is_live(r, now) and (not r.get("group_id") or str(r["group_id"]) in mine)]
    rows.sort(key=when_of, reverse=True)
    rows.sort(key=lambda r: not pinned_now(r, now))
    rows = [r for r in rows if matches(r, filt)]
    return _decorate(business_id, rows[:40], me_id)


def home_view(business_id: str, me_id: str) -> Tuple[Optional[List[Dict[str, Any]]], int]:
    """Home's "From the church" (the first four posts, decorated) and the
    bell's count of posts from the last two weeks this member hasn't opened.
    Read in one go, beside Home's other reads. (None, 0) when a read failed:
    Home leaves the section out rather than wait or say "nothing"."""
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?business_id=eq.{_q(business_id)}&status=eq.posted&removed_at=is.null"
        f"&select={POST_SELECT}&order=created_at.desc&limit=40")
    groups = my_groups(business_id, me_id)
    if rows is None or groups is None:
        return None, 0
    now = _now()
    mine = set(groups)
    rows = [r for r in rows if is_live(r, now) and (not r.get("group_id") or str(r["group_id"]) in mine)]
    if not rows:
        return [], 0
    since = (now - timedelta(days=14)).isoformat()
    recent = [str(r["id"]) for r in rows if str(r.get("created_at") or "") >= since]
    unseen_n = 0
    if recent:
        seen = sb_clients.sb_get_as_service(
            f"/church_post_seen?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(me_id)}"
            f"&post_id=in.({_ids(recent)})&select=post_id&limit=200")
        if seen is not None:
            have = {str(s["post_id"]) for s in seen}
            unseen_n = sum(1 for r in recent if r not in have)
    rows.sort(key=when_of, reverse=True)
    rows.sort(key=lambda r: not pinned_now(r, now))
    return _decorate(business_id, rows[:4], me_id), unseen_n


def one(business_id: str, me_id: str, post_id: str) -> Optional[Dict[str, Any]]:
    """One post with its comments; {} when it isn't there for this member."""
    if not UUID.match(str(post_id or "")):
        return {}
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(business_id)}&select={POST_SELECT},removed_at&limit=1")
    if rows is None:
        return None
    if not rows or not is_live(rows[0]):
        return {}
    p = rows[0]
    if p.get("group_id"):
        groups = my_groups(business_id, me_id)
        if groups is None:
            return None
        if str(p["group_id"]) not in groups:
            return {}
    done = _decorate(business_id, [p], me_id)
    if done is None:
        return None
    talk = comments_of(business_id, me_id, str(p["id"]))
    if talk is None:
        return None
    p["thread"] = talk
    # Who reacted: how many people, and the two most recent by name (the
    # canvas's "Dana, Monique and 89 others reacted"). Best effort.
    rx = sb_clients.sb_get_as_service(
        f"/church_post_reactions?business_id=eq.{_q(business_id)}&post_id=eq.{_q(p['id'])}"
        f"&select=contact_id,created_at&order=created_at.desc&limit=5000") or []
    order: List[str] = []
    for r in rx:
        c = str(r.get("contact_id") or "")
        if c and c not in order:
            order.append(c)
    p["reactors_n"] = len(order)
    names = _people(business_id, order[:2]) or {}
    p["reactors"] = [names[c] for c in order[:2] if c in names]
    return p


def comments_of(business_id: str, me_id: str, post_id: str) -> Optional[List[Dict[str, Any]]]:
    """Shown comments, oldest first, each reply after the comment it answers;
    a member also sees their own held comment (marked)."""
    b = _q(business_id)
    rows = sb_clients.sb_get_as_service(
        f"/church_post_comments?business_id=eq.{b}&post_id=eq.{_q(post_id)}&status=in.(shown,held)"
        f"&select=id,contact_id,reply_to,body,status,created_at&order=created_at.asc&limit=500")
    if rows is None:
        return None
    rows = [r for r in rows if r.get("status") == "shown" or str(r.get("contact_id")) == str(me_id)]
    if not rows:
        return []
    loves = sb_clients.sb_get_as_service(
        f"/church_post_comment_loves?business_id=eq.{b}&comment_id=in.({_ids(r['id'] for r in rows)})"
        f"&select=comment_id,contact_id&limit=50000")
    reported = sb_clients.sb_get_as_service(
        f"/church_post_reports?business_id=eq.{b}&reported_by=eq.{_q(me_id)}"
        f"&comment_id=in.({_ids(r['id'] for r in rows)})&select=comment_id&limit=500")
    people = _people(business_id, [r["contact_id"] for r in rows])
    if loves is None or reported is None or people is None:
        return None
    pastor_of = {c: bool(is_pastoral(business_id, c)) for c in {str(r["contact_id"]) for r in rows}}
    mine_reported = {str(x["comment_id"]) for x in reported}
    for r in rows:
        cid = str(r["id"])
        r["person"] = people.get(str(r["contact_id"])) or {}
        r["loves"] = sum(1 for x in loves if str(x["comment_id"]) == cid)
        r["i_loved"] = any(str(x["comment_id"]) == cid and str(x["contact_id"]) == str(me_id) for x in loves)
        r["i_reported"] = cid in mine_reported
        r["mine"] = str(r["contact_id"]) == str(me_id)
        r["pastor"] = pastor_of.get(str(r["contact_id"]), False)
    # Replies sit under the comment they answer (one level, like the canvas).
    top = [r for r in rows if not r.get("reply_to")]
    ids = {str(r["id"]) for r in rows}
    out: List[Dict[str, Any]] = []
    for t in top:
        out.append(t)
        out.extend({**r, "is_reply": True} for r in rows if str(r.get("reply_to") or "") == str(t["id"]))
    # A reply whose comment is gone (or held) still shows, on its own.
    out.extend(r for r in rows if r.get("reply_to") and str(r["reply_to"]) not in ids)
    return out


def mark_seen(business_id: str, contact_id: str, post_ids: List[str]) -> None:
    if not post_ids:
        return
    try:
        sb_clients.sb_post_as_service(
            "/church_post_seen?on_conflict=post_id,contact_id",
            [{"post_id": p, "contact_id": str(contact_id), "business_id": str(business_id)} for p in post_ids],
            prefer="resolution=ignore-duplicates,return=minimal")
    except Exception:
        logger.warning("news seen write failed", exc_info=True)


def unseen(business_id: str, me_id: str) -> int:
    """How many live posts from the last two weeks this member hasn't opened
    (the bell on Home). 0 when it can't be told."""
    since = _q((_now() - timedelta(days=14)).isoformat())
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?business_id=eq.{_q(business_id)}&status=eq.posted&removed_at=is.null&created_at=gte.{since}"
        f"&select=id,group_id,status,publish_at,removed_at&limit=200")
    seen = sb_clients.sb_get_as_service(
        f"/church_post_seen?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(me_id)}&seen_at=gte.{since}&select=post_id&limit=500")
    groups = my_groups(business_id, me_id)
    if rows is None or seen is None or groups is None:
        return 0
    have = {str(s["post_id"]) for s in seen}
    return sum(1 for r in rows if is_live(r) and str(r["id"]) not in have
               and (not r.get("group_id") or str(r["group_id"]) in groups))


# ─── a member's reactions and comments ──────────────────────────────


def _live_post(business_id: str, me_id: str, post_id: str) -> Optional[Dict[str, Any]]:
    if not UUID.match(str(post_id or "")):
        return {}
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(business_id)}"
        f"&select=id,group_id,posted_by,status,publish_at,removed_at,comments&limit=1")
    if rows is None:
        return None
    if not rows or not is_live(rows[0]):
        return {}
    p = rows[0]
    if p.get("group_id"):
        groups = my_groups(business_id, me_id)
        if groups is None:
            return None
        if str(p["group_id"]) not in groups:
            return {}
    return p


def react(business_id: str, me_id: str, post_id: str, kind: str) -> Tuple[bool, str, str]:
    """Toggle one reaction. (ok, code, post_id)."""
    if kind not in REACTIONS:
        return False, "error", ""
    p = _live_post(business_id, me_id, post_id)
    if p is None:
        return False, "error", ""
    if not p:
        return False, "news_gone", ""
    pid = str(p["id"])
    have = sb_clients.sb_get_as_service(
        f"/church_post_reactions?post_id=eq.{_q(pid)}&contact_id=eq.{_q(me_id)}&kind=eq.{kind}&select=kind&limit=1")
    if have is None:
        return False, "error", pid
    if have:
        ok = sb_clients.sb_delete_as_service(
            f"/church_post_reactions?post_id=eq.{_q(pid)}&contact_id=eq.{_q(me_id)}&kind=eq.{kind}&business_id=eq.{_q(business_id)}")
        return (True, "", pid) if ok else (False, "error", pid)
    # return=representation: a minimal write hands back None even when it worked.
    ok = sb_clients.sb_post_as_service(
        "/church_post_reactions?on_conflict=post_id,contact_id,kind",
        {"post_id": pid, "contact_id": str(me_id), "business_id": str(business_id), "kind": kind},
        prefer="resolution=ignore-duplicates,return=representation")
    return (True, "", pid) if ok is not None else (False, "error", pid)


async def comment(business: Dict[str, Any], me: Dict[str, Any], post_id: str, text: str,
                  reply_to: str = "") -> Tuple[bool, str, str]:
    """A comment, checked first. (ok, code, post_id). Codes: 'commented',
    'comment_held' (the safety officers look first), 'care' (crisis words:
    held, the pastor told, the writer shown 988)."""
    import msg_screen
    business_id = str(business["id"])
    text = re.sub(r"[ \t]+\n", "\n", str(text or "")).strip()[:COMMENT_MAX]
    if not text:
        return False, "comment_empty", str(post_id or "")
    if not await asyncio.to_thread(comments_open, business):
        return False, "comments_closed", str(post_id or "")
    p = await asyncio.to_thread(_live_post, business_id, str(me["id"]), post_id)
    if p is None:
        return False, "error", str(post_id or "")
    if not p:
        return False, "news_gone", ""
    pid = str(p["id"])
    if p.get("comments") != "on":
        return False, "comments_off", pid
    reply = ""
    if reply_to and UUID.match(str(reply_to)):
        parent = await asyncio.to_thread(
            sb_clients.sb_get_as_service,
            f"/church_post_comments?id=eq.{_q(reply_to)}&post_id=eq.{_q(pid)}&status=eq.shown&select=id,reply_to&limit=1")
        if parent is None:
            return False, "error", pid
        # One level of replies: answering a reply answers its comment.
        reply = str(parent[0].get("reply_to") or parent[0]["id"]) if parent else ""
    try:
        verdict = await msg_screen.screen(business_id, text)
    except msg_screen.ScreenUnavailable:
        return False, "comment_busy", pid
    status = "shown" if verdict == "ok" else "held"
    row = await asyncio.to_thread(sb_clients.sb_post_as_service, "/church_post_comments", {
        "business_id": business_id, "post_id": pid, "contact_id": str(me["id"]), "body": text, "status": status,
        **({"reply_to": reply} if reply else {})})
    if not isinstance(row, list) or not row:
        return False, "error", pid
    if verdict == "self_harm":
        import member_portal_messaging as mpm
        await asyncio.to_thread(mpm.care_alert, business_id, me)
        return True, "care", pid
    return True, "commented" if status == "shown" else "comment_held", pid


def _comment_row(business_id: str, comment_id: str) -> Optional[Dict[str, Any]]:
    if not UUID.match(str(comment_id or "")):
        return {}
    rows = sb_clients.sb_get_as_service(
        f"/church_post_comments?id=eq.{_q(comment_id)}&business_id=eq.{_q(business_id)}"
        f"&select=id,post_id,contact_id,status&limit=1")
    if rows is None:
        return None
    return rows[0] if rows else {}


def love(business_id: str, me_id: str, comment_id: str) -> Tuple[bool, str, str]:
    c = _comment_row(business_id, comment_id)
    if c is None:
        return False, "error", ""
    if not c or c.get("status") != "shown":
        return False, "comment_gone", str((c or {}).get("post_id") or "")
    pid = str(c["post_id"])
    if not _live_post(business_id, me_id, pid):
        return False, "news_gone", ""
    have = sb_clients.sb_get_as_service(
        f"/church_post_comment_loves?comment_id=eq.{_q(c['id'])}&contact_id=eq.{_q(me_id)}&select=comment_id&limit=1")
    if have is None:
        return False, "error", pid
    if have:
        ok = sb_clients.sb_delete_as_service(
            f"/church_post_comment_loves?comment_id=eq.{_q(c['id'])}&contact_id=eq.{_q(me_id)}&business_id=eq.{_q(business_id)}")
        return (True, "", pid) if ok else (False, "error", pid)
    ok = sb_clients.sb_post_as_service(
        "/church_post_comment_loves?on_conflict=comment_id,contact_id",
        {"comment_id": str(c["id"]), "contact_id": str(me_id), "business_id": str(business_id)},
        prefer="resolution=ignore-duplicates,return=representation")
    return (True, "", pid) if ok is not None else (False, "error", pid)


def report(business_id: str, me_id: str, comment_id: str) -> Tuple[bool, str, str]:
    """A member reports a comment: it goes to the safety officers, who never
    learn from the app who told them."""
    c = _comment_row(business_id, comment_id)
    if c is None:
        return False, "error", ""
    if not c or c.get("status") != "shown":
        return False, "comment_gone", str((c or {}).get("post_id") or "")
    pid = str(c["post_id"])
    if str(c["contact_id"]) == str(me_id):
        return False, "error", pid
    ok = sb_clients.sb_post_as_service(
        "/church_post_reports?on_conflict=comment_id,reported_by",
        {"business_id": str(business_id), "comment_id": str(c["id"]), "reported_by": str(me_id)},
        prefer="resolution=ignore-duplicates,return=representation")
    return (True, "reported", pid) if ok is not None else (False, "error", pid)


def remove_comment(business_id: str, me_id: str, comment_id: str) -> Tuple[bool, str, str]:
    """Its writer, or whoever posted the post, takes a comment down."""
    c = _comment_row(business_id, comment_id)
    if c is None:
        return False, "error", ""
    if not c or c.get("status") == "removed":
        return False, "comment_gone", str((c or {}).get("post_id") or "")
    pid = str(c["post_id"])
    by = "writer" if str(c["contact_id"]) == str(me_id) else ""
    if not by:
        p = sb_clients.sb_get_as_service(
            f"/church_posts?id=eq.{_q(pid)}&business_id=eq.{_q(business_id)}&select=posted_by&limit=1")
        if p is None:
            return False, "error", pid
        if not p or str(p[0].get("posted_by") or "") != str(me_id):
            return False, "not_yours", pid
        by = "poster"
    ok = sb_clients.sb_patch_as_service(
        f"/church_post_comments?id=eq.{_q(c['id'])}&business_id=eq.{_q(business_id)}",
        {"status": "removed", "removed_by": by, "removed_at": _now().isoformat()})
    return (True, "comment_down", pid) if ok is not None else (False, "error", pid)


# ─── posting ─────────────────────────────────────────────────────────


def clean(title: str, body: str) -> Tuple[str, str]:
    title = " ".join(str(title or "").split())[:TITLE_MAX]
    body = re.sub(r"[ \t]+\n", "\n", str(body or "")).strip()[:BODY_MAX]
    return title, body


def _attach(business_id: str, raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Only what can be shown: an event and a sermon by id, photos by an
    https address on this church's own storage."""
    raw = raw if isinstance(raw, dict) else {}
    out: Dict[str, Any] = {}
    if UUID.match(str(raw.get("event") or "")):
        out["event"] = str(raw["event"])
    if UUID.match(str(raw.get("sermon") or "")):
        out["sermon"] = str(raw["sermon"])
    photos = [str(u) for u in (raw.get("photos") or []) if isinstance(u, str) and u.startswith("https://")][:12]
    if photos:
        out["photos"] = photos
    return out


def insert(business_id: str, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Writes one post. When it's pinned, it takes the top from any other
    pin with the same reach (one pin for the church, one per ministry)."""
    if row.get("pinned_until") and not row.get("publish_at"):
        scope = f"group_id=eq.{_q(row['group_id'])}" if row.get("group_id") else "group_id=is.null"
        sb_clients.sb_patch_as_service(
            f"/church_posts?business_id=eq.{_q(business_id)}&{scope}&pinned_until=gt.{_q(_now().isoformat())}",
            {"pinned_until": None})
    rows = sb_clients.sb_post_as_service("/church_posts", {"business_id": business_id, **row})
    return rows[0] if isinstance(rows, list) and rows else None


# ─── the office ──────────────────────────────────────────────────────


def _unavailable() -> HTTPException:
    return HTTPException(503, "News is temporarily unavailable. Nothing was changed — try again.")


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise _unavailable()
    return rows


def _need(business_id: str, user: AuthedUser, minimum: str) -> str:
    import kids_router
    role = kids_router.role_for(business_id, user)
    if _RANK.get(role or "", 0) < _RANK[minimum]:
        raise HTTPException(403, "Your seat can see the news. Someone who can edit posts it."
                            if minimum != "viewer" else "This seat can't see the news.")
    return role or ""


def _business(biz_id: str) -> Dict[str, Any]:
    rows = _get(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,settings,owner_id&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def office_view(business: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the office page shows. Counts only for comments; the words
    of a comment only for one the check held (the officers decide it)."""
    import messaging_router as mr
    biz_id = str(business["id"])
    b = _q(biz_id)
    rows = _get(f"/church_posts?business_id=eq.{b}&status=in.(posted,waiting)&removed_at=is.null"
                f"&select={POST_SELECT}&order=created_at.desc&limit=60")
    ids = _ids(r["id"] for r in rows)
    seen = _get(f"/church_post_seen?business_id=eq.{b}&post_id=in.({ids})&select=post_id&limit=100000") if rows else []
    rx = _get(f"/church_post_reactions?business_id=eq.{b}&post_id=in.({ids})&select=post_id&limit=100000") if rows else []
    cm = _get(f"/church_post_comments?business_id=eq.{b}&post_id=in.({ids})&status=eq.shown&select=post_id&limit=100000") if rows else []
    gids = {str(r["group_id"]) for r in rows if r.get("group_id")}
    groups = _get(f"/groups?business_id=eq.{b}&id=in.({_ids(gids)})&select=id,name") if gids else []
    authors = _people(biz_id, [r.get("posted_by") for r in rows]) or {}
    # The app's people: every address that has signed in to the member app.
    signed = _get(f"/member_login_codes?business_id=eq.{b}&succeeded=is.true&select=email&limit=100000")
    app_people = len({str(s.get("email") or "") for s in signed if s.get("email")})
    gname = {str(g["id"]): g.get("name") or "" for g in groups}
    now = _now()

    def n(items, pid):
        return sum(1 for x in items if str(x["post_id"]) == pid)
    posts = []
    for r in rows:
        pid = str(r["id"])
        a = authors.get(str(r.get("posted_by") or "")) or {}
        posts.append({
            "id": pid, "kind": r.get("kind"), "title": r.get("title") or "", "body": r.get("body") or "",
            "from": a.get("name") or r.get("author_label") or business.get("name") or "",
            "from_sub": {"office": "Office", "leader": "Leader", "member": "Shared by a member", "chief": "Chief",
                         "sermon": "With the sermon"}.get(r.get("source") or "", ""),
            "for": gname.get(str(r.get("group_id") or ""), "") or "Whole church",
            "group_id": r.get("group_id"), "status": r.get("status"),
            "scheduled": bool(_ts(r.get("publish_at")) and _ts(r.get("publish_at")) > now),
            "publish_at": r.get("publish_at"), "created_at": r.get("created_at"),
            "pinned": pinned_now(r, now), "comments": r.get("comments"),
            "seen": n(seen, pid), "reactions": n(rx, pid), "comment_n": n(cm, pid),
        })
    held = _get(f"/church_post_comments?business_id=eq.{b}&status=eq.held&select=id,post_id,contact_id,body,created_at"
                f"&order=created_at.desc&limit=50")
    reports = _get(f"/church_post_reports?business_id=eq.{b}&status=eq.open&select=comment_id&limit=500")
    titles = {p["id"]: p["title"] for p in posts}
    posters = _get(f"/church_news_posters?business_id=eq.{b}&select=contact_id,added_at&limit=200")
    poster_people = _people(biz_id, [p["contact_id"] for p in posters]) or {}
    week = (now - timedelta(days=7)).isoformat()
    saw = _get(f"/church_post_seen?business_id=eq.{b}&seen_at=gte.{_q(week)}&select=contact_id&limit=100000")
    # What a new post can be for and carry: the running ministries and
    # groups, what's coming up, the latest sermons.
    ministries = _get(f"/groups?business_id=eq.{b}&active=eq.true&select=id,name,kind&order=name.asc&limit=500")
    sermons = _get(f"/sermons?business_id=eq.{b}&published=eq.true&select=id,title,preached_on"
                   f"&order=preached_on.desc&limit=12")
    import member_portal_church as mpc
    occ = mpc.upcoming_for(biz_id, {"id": "", "name": "", "email": ""}) or []
    events = [{"id": o.get("entry_id"), "title": o.get("title") or "", "when": o.get("date_label") or "", "date": o.get("date")}
              for o in occ if o.get("entry_id")][:25]
    # Who the church can pick to post to everyone: its leaders (an active
    # role) and the people who lead a group.
    led = _get(f"/group_members?business_id=eq.{b}&role=eq.leader&select=contact_id&limit=2000")
    roles = _get(f"/church_leader_roles?business_id=eq.{b}&status=eq.active&select=contact_id&limit=2000")
    chosen = {str(p["contact_id"]) for p in posters}
    pool = sorted({str(r["contact_id"]) for r in led + roles} - chosen)
    pool_people = _people(biz_id, pool) or {}
    return {
        "posts": posts,
        "app_people": app_people,
        "seen_week": len({str(s["contact_id"]) for s in saw}),
        "posts_month": sum(1 for p in posts if p["status"] == "posted" and str(p.get("created_at") or "") >= (now - timedelta(days=30)).isoformat()),
        "held": [{"id": h["id"], "post_id": h["post_id"], "post_title": titles.get(str(h["post_id"]), ""),
                  "created_at": h["created_at"]} for h in held],
        "safety": {"comments_open": comments_open(business), "officers": mr.officer_count(biz_id),
                   "min_officers": mr.MIN_OFFICERS, "held_week": sum(1 for h in held if str(h["created_at"]) >= week),
                   "reports_open": len(reports)},
        "posters": [{"contact_id": str(p["contact_id"]), "name": (poster_people.get(str(p["contact_id"])) or {}).get("name") or ""}
                    for p in posters],
        "settings": {"comments": (((business.get("settings") or {}).get("news") or {}).get("comments")) is not False},
        "ministries": [{"id": str(g["id"]), "name": g.get("name") or "", "kind": g.get("kind") or ""} for g in ministries],
        "events": events,
        "sermons": [{"id": str(s["id"]), "title": s.get("title") or "", "date": s.get("preached_on")} for s in sermons],
        "candidates": sorted(({"contact_id": c, "name": (pool_people.get(c) or {}).get("name") or ""} for c in pool
                              if (pool_people.get(c) or {}).get("name")), key=lambda x: x["name"].lower()),
    }


@router.get("/church/news")
def office(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    import kids_router
    biz = kids_router._uuid(business_id, "business_id")
    _need(biz, user, "viewer")
    return office_view(_business(biz))


class PostIn(BaseModel):
    business_id: str
    kind: Literal["announcement", "event", "photos", "praise", "message"] = "announcement"
    title: str = Field("", max_length=TITLE_MAX)
    body: str = Field("", max_length=BODY_MAX)
    group_id: Optional[str] = None
    author_label: str = Field("", max_length=LABEL_MAX)
    pin: bool = False
    comments: Literal["on", "prayers", "off"] = "on"
    publish_at: Optional[str] = None
    attach: Dict[str, Any] = Field(default_factory=dict)


@router.post("/church/news")
def create(body: PostIn, user: AuthedUser = Depends(require_user)):
    import kids_router
    biz_id = kids_router._uuid(body.business_id, "business_id")
    # A direct call, so the ownership sweep (ownership_sweep.py) sees the gate.
    _need(biz_id, user, "member")
    title, text = clean(body.title, body.body)
    att = _attach(biz_id, body.attach)
    if not text and not title and not att:
        raise HTTPException(422, "Write something first.")
    gid = None
    if body.group_id:
        gid = kids_router._uuid(body.group_id, "group")
        if not _get(f"/groups?id=eq.{_q(gid)}&business_id=eq.{_q(biz_id)}&active=eq.true&select=id&limit=1"):
            raise HTTPException(404, "That ministry isn't running any more.")
    when = None
    if body.publish_at:
        when = _ts(body.publish_at)
        if not when or when.tzinfo is None:
            raise HTTPException(422, "Pick a time to post it.")
        if when <= _now():
            when = None
        elif when > _now() + timedelta(days=90):
            raise HTTPException(422, "Schedule it within the next 90 days.")
    business = _business(biz_id)
    row = insert(biz_id, {
        "kind": body.kind, "title": title, "body": text, "group_id": gid, "office_user": user.id,
        "author_label": " ".join(body.author_label.split())[:LABEL_MAX], "source": "office", "status": "posted",
        "pinned_until": (_now() + timedelta(days=PIN_DAYS)).isoformat() if body.pin else None,
        "comments": body.comments, "publish_at": when.astimezone(timezone.utc).isoformat() if when else None,
        "attach": att})
    if not row:
        raise HTTPException(503, "That didn't post. Nothing went out — try again.")
    return {"ok": True, "post_id": row["id"], "scheduled": bool(when), "comments_open": comments_open(business)}


class PinIn(BaseModel):
    business_id: str
    on: bool = True


def _post_or_404(biz_id: str, post_id: str) -> Dict[str, Any]:
    import kids_router
    pid = kids_router._uuid(post_id, "post")
    rows = _get(f"/church_posts?id=eq.{_q(pid)}&business_id=eq.{_q(biz_id)}&removed_at=is.null"
                f"&select=id,group_id,status,publish_at&limit=1")
    if not rows:
        raise HTTPException(404, "That post isn't there any more.")
    return rows[0]


@router.post("/church/news/{post_id}/pin")
def pin(post_id: str, body: PinIn, user: AuthedUser = Depends(require_user)):
    import kids_router
    biz_id = kids_router._uuid(body.business_id, "business_id")
    _need(biz_id, user, "member")
    p = _post_or_404(biz_id, post_id)
    if body.on:
        scope = f"group_id=eq.{_q(p['group_id'])}" if p.get("group_id") else "group_id=is.null"
        sb_clients.sb_patch_as_service(f"/church_posts?business_id=eq.{_q(biz_id)}&{scope}&pinned_until=not.is.null",
                                       {"pinned_until": None})
    ok = sb_clients.sb_patch_as_service(
        f"/church_posts?id=eq.{_q(p['id'])}&business_id=eq.{_q(biz_id)}",
        {"pinned_until": (_now() + timedelta(days=PIN_DAYS)).isoformat() if body.on else None})
    if ok is None:
        raise _unavailable()
    return {"ok": True}


class BizIn(BaseModel):
    business_id: str


@router.post("/church/news/{post_id}/remove")
def remove(post_id: str, body: BizIn, user: AuthedUser = Depends(require_user)):
    import kids_router
    biz_id = kids_router._uuid(body.business_id, "business_id")
    _need(biz_id, user, "member")
    p = _post_or_404(biz_id, post_id)
    ok = sb_clients.sb_patch_as_service(
        f"/church_posts?id=eq.{_q(p['id'])}&business_id=eq.{_q(biz_id)}",
        {"status": "removed", "removed_at": _now().isoformat(), "pinned_until": None})
    if ok is None:
        raise _unavailable()
    return {"ok": True}


@router.get("/church/news/held")
def held_words(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    """The words of each held comment, for the church's safety officers only
    (everyone else sees that one is waiting, never what it says)."""
    import kids_router
    import messaging_router as mr
    biz = kids_router._uuid(business_id, "business_id")
    # A direct call, so the ownership sweep sees the gate; then the officer check.
    _need(biz, user, "viewer")
    mr.require_officer(biz, user)
    rows = _get(f"/church_post_comments?business_id=eq.{_q(biz)}&status=eq.held"
                f"&select=id,post_id,contact_id,body,created_at&order=created_at.desc&limit=50")
    people = _people(biz, [r["contact_id"] for r in rows]) or {}
    return {"held": [{"id": r["id"], "post_id": r["post_id"], "body": r.get("body") or "", "created_at": r["created_at"],
                      "name": (people.get(str(r["contact_id"])) or {}).get("name") or "Someone"} for r in rows]}


class HeldIn(BaseModel):
    business_id: str
    show: bool


@router.post("/church/news/held/{comment_id}")
def decide_held(comment_id: str, body: HeldIn, user: AuthedUser = Depends(require_user)):
    """A held comment, decided by a safety officer's seat (or the owner)."""
    import kids_router
    import messaging_router as mr
    biz_id = kids_router._uuid(body.business_id, "business_id")
    cid = kids_router._uuid(comment_id, "comment")
    _need(biz_id, user, "viewer")
    mr.require_officer(biz_id, user)
    rows = _get(f"/church_post_comments?id=eq.{_q(cid)}&business_id=eq.{_q(biz_id)}&status=eq.held&select=id&limit=1")
    if not rows:
        raise HTTPException(404, "That comment was already decided.")
    patch = {"status": "shown"} if body.show else {"status": "removed", "removed_by": "officer",
                                                    "removed_at": _now().isoformat()}
    if sb_clients.sb_patch_as_service(f"/church_post_comments?id=eq.{_q(cid)}&business_id=eq.{_q(biz_id)}", patch) is None:
        raise _unavailable()
    return {"ok": True}


class PostersIn(BaseModel):
    business_id: str
    add: List[str] = Field(default_factory=list)
    remove: List[str] = Field(default_factory=list)


@router.post("/church/news/posters")
def posters(body: PostersIn, user: AuthedUser = Depends(require_user)):
    """The people who post to the whole church. The owner and admins pick."""
    import kids_router
    biz_id = kids_router._uuid(body.business_id, "business_id")
    _need(biz_id, user, "admin")
    add = [kids_router._uuid(c, "person") for c in body.add[:50]]
    drop = [kids_router._uuid(c, "person") for c in body.remove[:50]]
    if add:
        found = _get(f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({_ids(add)})&select=id")
        if len(found) != len(set(add)):
            raise HTTPException(404, "Someone on that list isn't one of your people.")
        ok = sb_clients.sb_post_as_service(
            "/church_news_posters?on_conflict=business_id,contact_id",
            [{"business_id": biz_id, "contact_id": c, "added_by": user.id} for c in sorted(set(add))],
            prefer="resolution=ignore-duplicates,return=representation")
        if ok is None:
            raise _unavailable()
    if drop:
        if not sb_clients.sb_delete_as_service(
                f"/church_news_posters?business_id=eq.{_q(biz_id)}&contact_id=in.({_ids(drop)})"):
            raise _unavailable()
    return {"ok": True}


class NewsSettingsIn(BaseModel):
    business_id: str
    comments: bool


@router.post("/church/news/settings")
def news_settings(body: NewsSettingsIn, user: AuthedUser = Depends(require_user)):
    """Comments on News, on or off (settings.news.comments)."""
    import kids_router
    biz_id = kids_router._uuid(body.business_id, "business_id")
    _need(biz_id, user, "admin")
    business = _business(biz_id)
    settings = business.get("settings") if isinstance(business.get("settings"), dict) else {}
    news = settings.get("news") if isinstance(settings.get("news"), dict) else {}
    ok = sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(biz_id)}",
                                        {"settings": {**settings, "news": {**news, "comments": bool(body.comments)}}})
    if ok is None:
        raise _unavailable()
    return {"ok": True}
