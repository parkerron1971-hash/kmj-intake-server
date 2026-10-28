"""
church_groups_office.py — the office's Groups page: how each group is doing,
a word to every group, and a nudge to a leader.

From the approved canvas "Church Groups, Together" (board Office: "Every
group, alive. … Here you see how each one is doing, help its leaders, and
speak to every group at once. You never see their private chat.").

  GET  /church/groups/health   per group: how many messages its chat had
                               this week and how many Board posts and
                               prayers this month — counts only, never a
                               word of the chat; and the safety picture
                               (held by the check this week, open reports,
                               safety officers, prayers that went straight
                               to a pastor this week)
  POST /church/groups/word     a word from the pastors to every group (or
                               to the group leaders only): it lands on each
                               group's Board, a note goes to every phone that
                               allows group news, and an email to the rest.
                               A word to every group can go on News too
                               (news), for the people who aren't in a group
  POST /church/groups/remind   someone has been waiting to join: a note to
                               the group's leaders (once a day per group)

Any seat sees the page; a seat that can edit sends. Attendance, rosters
and join requests the office already reads itself (groupsData.ts).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["church-groups"])

TITLE_MAX, BODY_MAX = 120, 4000
_RANK = {"viewer": 1, "member": 2, "manager": 3, "admin": 4, "owner": 5}


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _unavailable() -> HTTPException:
    return HTTPException(503, "Groups are temporarily unavailable. Nothing was changed — try again.")


def _need(business_id: str, user: AuthedUser, minimum: str) -> str:
    import kids_router
    role = kids_router.role_for(business_id, user)
    if _RANK.get(role or "", 0) < _RANK[minimum]:
        raise HTTPException(403, "Your seat can see groups. Someone who can edit sends to them."
                            if minimum != "viewer" else "This seat can't see groups.")
    return role or ""


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise _unavailable()
    return rows


def _count_by(rows: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        k = str(r.get(key) or "")
        if k:
            out[k] = out.get(k, 0) + 1
    return out


# ─── how each group is doing ─────────────────────────────────────────


def health_of(business_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Counts only. Raises 503 when a read fails (the page says try again;
    a broken read never reads as a quiet group)."""
    import messaging_router as mr
    now = now or _now()
    b = _q(business_id)
    week = _q((now - timedelta(days=7)).isoformat())
    month = _q((now - timedelta(days=30)).isoformat())
    threads = _get(f"/msg_threads?business_id=eq.{b}&kind=eq.group&select=id,group_id&limit=2000")
    group_of = {str(t["id"]): str(t["group_id"]) for t in threads if t.get("group_id")}
    talk: Dict[str, int] = {}
    if group_of:
        said = _get(f"/msg_messages?business_id=eq.{b}&thread_id=in.({','.join(group_of)})&status=eq.delivered"
                    f"&created_at=gte.{week}&select=thread_id&limit=50000")
        for tid, n in _count_by(said, "thread_id").items():
            gid = group_of.get(tid)
            if gid:
                talk[gid] = talk.get(gid, 0) + n
    posts = _count_by(_get(f"/group_posts?business_id=eq.{b}&group_id=not.is.null&removed_at=is.null"
                           f"&created_at=gte.{month}&select=group_id&limit=50000"), "group_id")
    prayers_rows = _get(f"/group_prayers?business_id=eq.{b}&created_at=gte.{month}&select=group_id,to_pastor,created_at"
                        f"&limit=50000")
    prayers = _count_by([p for p in prayers_rows if not p.get("to_pastor")], "group_id")
    week_iso = (now - timedelta(days=7)).isoformat()
    to_pastor = sum(1 for p in prayers_rows if p.get("to_pastor") and str(p.get("created_at") or "") >= week_iso)
    held = _get(f"/msg_messages?business_id=eq.{b}&status=eq.held&created_at=gte.{week}&select=id&limit=5000")
    reports = _get(f"/msg_reports?business_id=eq.{b}&status=eq.open&select=id&limit=5000")
    biz = _get(f"/businesses?id=eq.{b}&select=settings&limit=1")
    on = bool((((biz[0].get("settings") if biz else None) or {}).get("messaging") or {}).get("enabled"))
    gids = set(talk) | set(posts) | set(prayers)
    return {
        "groups": {g: {"talk_week": talk.get(g, 0), "posts_month": posts.get(g, 0), "prayers_month": prayers.get(g, 0)}
                   for g in sorted(gids)},
        "safety": {"messaging_on": on, "officers": mr.officer_count(business_id), "min_officers": mr.MIN_OFFICERS,
                   "held_week": len(held), "reports_open": len(reports), "to_pastor_week": to_pastor},
    }


@router.get("/church/groups/health")
def health(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    import kids_router
    biz = kids_router._uuid(business_id, "business_id")
    _need(biz, user, "viewer")
    return health_of(biz)


# ─── a word to every group ───────────────────────────────────────────


class WordIn(BaseModel):
    business_id: str
    audience: Literal["groups", "leaders"] = "groups"
    title: str = Field("", max_length=TITLE_MAX)
    body: str = Field(..., min_length=1, max_length=BODY_MAX)
    # Also on News, for the whole church (Kevin, 2026-10-23: "if I want to
    # post to news feed i can choose so or not because not everyone possibly
    # is in a group"). A word to every group only; never a leaders-only one.
    news: bool = False


def _audience(business_id: str, audience: str) -> Tuple[List[str], int]:
    """(everyone in an active group, or only their leaders; how many groups)."""
    b = _q(business_id)
    active = {str(g["id"]) for g in _get(f"/groups?business_id=eq.{b}&active=eq.true&select=id&limit=2000")}
    rows = _get(f"/group_members?business_id=eq.{b}&select=group_id,contact_id,role&limit=50000")
    who = sorted({str(r["contact_id"]) for r in rows if str(r["group_id"]) in active
                  and (audience == "groups" or r.get("role") == "leader")})
    return who, len(active)


async def _email(business: Dict[str, Any], post: Dict[str, Any], people: List[Dict[str, Any]], app: Optional[str],
                 audience: str) -> int:
    """The people with no phone set up for the member app."""
    import academy_join
    import email_layout
    import email_sender
    import group_email
    church = (business.get("name") or "").strip() or "Your church"
    settings = business.get("settings") if isinstance(business.get("settings"), dict) else {}
    title, body = str(post.get("title") or ""), str(post.get("body") or "")
    subject = (f"{church}: {title}" if title else f"A word from {church}'s pastors")[:150]
    message = "\n\n".join(x for x in (f"From your pastors, to every {'group leader' if audience == 'leaders' else 'group'}:",
                                      title, body) if x)
    why = (f"You’re getting this because you lead a group at {church}." if audience == "leaders"
           else f"You’re getting this because you’re in a group at {church}.")
    sent = 0
    for p in people:
        email = str(p.get("email") or "").strip()
        if not academy_join.valid_email(email) or not group_email._adult(p):
            continue
        try:
            html = email_layout.render_html(
                message, business_name=church, brand=email_layout.brand_of(settings), sig=None,
                unsubscribe_url=email_sender._unsubscribe_url(email), preheader=(title or body)[:90],
                cta=(("Open your groups", f"{app}/my/groups") if app else None), disclaimer=why)
            await email_sender.send_via_resend(
                to_email=email, to_name=p.get("name") or None,
                from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
                from_name=church, subject=subject, body=html, reply_to=None, business_id=str(business["id"]),
                idempotency_key=f"church-word-{post['id']}-{p['id']}")
            sent += 1
        except Exception as e:  # noqa: BLE001 — one address never stops the rest
            logger.warning(f"[church-word] one email failed: {type(e).__name__}")
    return sent


@router.post("/church/groups/word")
async def word(body: WordIn, user: AuthedUser = Depends(require_user)):
    import group_email
    import kids_router
    import member_push
    biz_id = kids_router._uuid(body.business_id, "business_id")
    # A direct call, so the ownership sweep (ownership_sweep.py) sees the gate.
    _need(biz_id, user, "member")
    text = "\n".join(line.rstrip() for line in body.body.strip().splitlines()).strip()
    title = " ".join(body.title.split())
    if not text:
        raise HTTPException(422, "Write your message first.")
    news_too = bool(body.news) and body.audience == "groups"
    who, n_groups = await asyncio.to_thread(_audience, biz_id, body.audience)
    if not who and not news_too:
        raise HTTPException(409, "Nobody is in a group yet." if body.audience == "groups" else "No group has a leader yet.")
    biz = (await asyncio.to_thread(_get, f"/businesses?id=eq.{_q(biz_id)}&select=id,name,settings&limit=1"))
    if not biz:
        raise HTTPException(404, "business not found")
    business = biz[0]
    news_post = None
    if news_too:
        # The same words on News, for everyone in the app, groups or not
        # (church_news); it rings like any office post (news_alerts).
        import church_news as cn
        import news_alerts
        news_post = await asyncio.to_thread(cn.insert, biz_id, {
            "kind": "announcement", "title": title, "body": text, "office_user": user.id, "author_label": "",
            "source": "office", "status": "posted", "comments": "on", "attach": {}})
        if not news_post:
            raise HTTPException(503, "That didn't post. Nothing went out — try again.")
        news_alerts.alert_later(business, news_post)
    if not who:
        return {"ok": True, "post_id": None, "people": 0, "phones": 0, "emailed": 0, "groups": n_groups,
                "news_post_id": news_post["id"]}
    rows = await asyncio.to_thread(sb_clients.sb_post_as_service, "/group_posts", {
        "business_id": biz_id, "group_id": None, "title": title, "body": text, "pinned": False, "ask_ack": True,
        "posted_by": None, "audience": "leaders" if body.audience == "leaders" else "all"})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't post. Nothing went out — try again.")
    post = rows[0]
    phones = await asyncio.to_thread(member_push.send, business, "groups",
                                     title=(business.get("name") or "Your church"),
                                     body=(f"From your pastors: {title}" if title else "A word from your pastors to every group"),
                                     url="/my/groups", contact_ids=who, ref_id=f"church-word:{post['id']}",
                                     tag=f"church-word-{post['id']}")
    subs = await asyncio.to_thread(_get, f"/member_push_subscriptions?business_id=eq.{_q(biz_id)}&select=contact_id&limit=50000")
    no_phone = sorted(set(who) - {str(s["contact_id"]) for s in subs})
    emailed = 0
    if no_phone:
        people = await asyncio.to_thread(group_email._people, biz_id, no_phone) or []
        app = await asyncio.to_thread(group_email.app_url, biz_id)
        emailed = await _email(business, post, people, app, body.audience)
        if emailed:
            await asyncio.to_thread(sb_clients.sb_patch_as_service,
                                    f"/group_posts?id=eq.{_q(post['id'])}&business_id=eq.{_q(biz_id)}", {"emailed": emailed})
    return {"ok": True, "post_id": post["id"], "people": len(who), "phones": phones, "emailed": emailed, "groups": n_groups,
            "news_post_id": news_post["id"] if news_post else None}


# ─── a nudge to a group's leaders ────────────────────────────────────


class RemindIn(BaseModel):
    business_id: str
    group_id: str


@router.post("/church/groups/remind")
def remind(body: RemindIn, user: AuthedUser = Depends(require_user)):
    """People waiting to join: a note to the group's leaders, once a day per
    group. Says how many phones it reached, so the office knows to call."""
    import kids_router
    import member_push
    biz_id = kids_router._uuid(body.business_id, "business_id")
    gid = kids_router._uuid(body.group_id, "group")
    _need(biz_id, user, "member")
    b = _q(biz_id)
    g = _get(f"/groups?id=eq.{_q(gid)}&business_id=eq.{b}&active=eq.true&select=id,name&limit=1")
    if not g:
        raise HTTPException(404, "That group isn't running any more.")
    waiting = _get(f"/group_join_requests?business_id=eq.{b}&group_id=eq.{_q(gid)}&status=eq.waiting&select=id&limit=500")
    if not waiting:
        raise HTTPException(409, "Nobody is waiting to join that group now.")
    leads = [str(r["contact_id"]) for r in
             _get(f"/group_members?business_id=eq.{b}&group_id=eq.{_q(gid)}&role=eq.leader&select=contact_id&limit=50")]
    if not leads:
        raise HTTPException(409, "That group has no leader yet. Answer them in the group, under Asking to join.")
    biz = _get(f"/businesses?id=eq.{b}&select=id,name,settings&limit=1")
    n = len(waiting)
    if "groups" not in member_push.church_kinds((biz[0] if biz else {}).get("settings")):
        return {"ok": True, "phones": 0, "why": "off"}
    phones = member_push.send(
        biz[0], "groups", title=str(g[0].get("name") or "Your group"),
        body=f"{n} {'person is' if n == 1 else 'people are'} waiting to join. Open the group to say yes.",
        url=f"/my/groups/{gid}", contact_ids=leads,
        ref_id=f"join-remind:{gid}:{_now().date().isoformat()}", tag=f"group-{gid}")
    return {"ok": True, "phones": phones, "why": "" if phones else "no_phone"}
