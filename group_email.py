"""
group_email.py — a church group's news by email.

Kevin, 2026-10-20 (decision 4): phone alerts and email for group news. The
approved canvas ("Church Groups, Together", boards Post and Notify) gives
email two jobs:

  * "Email the rest" — a leader posting to the Board can send the post to
    the group's people who haven't set the member app up on a phone
    (no member_push_subscriptions row), so they don't miss it.
  * "Email me if my phone misses it" — a member's own choice
    (member_push_prefs.email_missed, off unless turned on): a leader's post
    they haven't opened an hour after it went up comes by email.

Both send from the church's name with its branded layout and a one-click
unsubscribe (email_sender), only to adults (a known birthdate under 18 is
never emailed; the post is on their Board), only to a valid address, and
once per post per person (the Resend idempotency key). A post's own words
go out: they were checked before it went up (msg_screen), like every post.

  email_rest(business, group, post, author)  after create_post, off the request
  sweep_tick()                                every 15 minutes: the one-hour follow-up
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import sb_clients

logger = logging.getLogger(__name__)

MISSED_AFTER = timedelta(hours=1)     # "after an hour"
MISSED_WINDOW = timedelta(hours=6)    # older than this isn't caught up by email
_tasks: set = set()                   # background sends, kept alive until done


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def app_url(business_id: str) -> Optional[str]:
    """The church's member app, as its members open it (its own domain
    first, like the owner's link in Settings)."""
    from business_sites_helpers import PUBLIC_DOMAIN
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{_q(business_id)}&order=updated_at.desc&limit=1&select=slug,site_config")
    if not isinstance(rows, list) or not rows:
        return None
    site = rows[0]
    domain = (site.get("site_config") or {}).get("custom_domain")
    host = domain or (f"{site['slug']}.{PUBLIC_DOMAIN}" if site.get("slug") else "")
    return f"https://{host}" if host else None


def _adult(person: Dict[str, Any], today: Optional[date] = None) -> bool:
    """Only a known birthdate under 18 rules someone out."""
    raw = str(person.get("birthdate") or "")[:10]
    if not raw:
        return True
    try:
        born = date.fromisoformat(raw)
    except ValueError:
        return True
    t = today or date.today()
    return t.year - born.year - ((t.month, t.day) < (born.month, born.day)) >= 18


def _people(business_id: str, ids: List[str]) -> Optional[List[Dict[str, Any]]]:
    out: List[Dict[str, Any]] = []
    for i in range(0, len(ids), 150):
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(business_id)}&id=in.({','.join(ids[i:i + 150])})&select=id,name,email,birthdate")
        if not isinstance(rows, list):
            return None
        out += rows
    return out


def email_message(church: str, group: str, author_first: str, title: str, body: str) -> tuple:
    """(subject, message, preheader) — the post, said plainly."""
    subject = f"{group}: {title}" if title else f"{group}: a new post from {author_first}"
    lead = f"{author_first} posted to {group}:"
    message = "\n\n".join(x for x in (lead, title, body) if x)
    return subject[:150], message, (title or body)[:90]


async def _send(business: Dict[str, Any], group: Dict[str, Any], post: Dict[str, Any], author_first: str,
                person: Dict[str, Any], app: Optional[str], why: str) -> bool:
    import academy_join
    import email_layout
    import email_sender
    email = str(person.get("email") or "").strip()
    if not academy_join.valid_email(email) or not _adult(person):
        return False
    settings = business.get("settings") if isinstance(business.get("settings"), dict) else {}
    church = (business.get("name") or "").strip() or "Your church"
    gname = str(group.get("name") or "Your group")
    subject, message, preheader = email_message(church, gname, author_first, str(post.get("title") or ""),
                                                str(post.get("body") or ""))
    html = email_layout.render_html(
        message, business_name=church, brand=email_layout.brand_of(settings), sig=None,
        unsubscribe_url=email_sender._unsubscribe_url(email), preheader=preheader,
        cta=((f"Open {gname}", f"{app}/my/groups/{group['id']}/board") if app else None), disclaimer=why)
    await email_sender.send_via_resend(
        to_email=email, to_name=person.get("name") or None,
        from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
        from_name=church, subject=subject, body=html, reply_to=None, business_id=str(business["id"]),
        idempotency_key=f"group-post-{post['id']}-{person['id']}")
    return True


async def _send_all(business, group, post, author_first, people, app, why) -> int:
    sent = 0
    for p in people:
        try:
            if await _send(business, group, post, author_first, p, app, why):
                sent += 1
        except Exception as e:  # noqa: BLE001 — one address never stops the rest
            logger.warning(f"[group-email] one send failed: {type(e).__name__}")
    return sent


def _count(business_id: str, post_id: str, more: int) -> None:
    if not more:
        return
    rows = sb_clients.sb_get_as_service(
        f"/group_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(business_id)}&select=emailed&limit=1")
    have = int((rows[0].get("emailed") or 0) if isinstance(rows, list) and rows else 0)
    sb_clients.sb_patch_as_service(f"/group_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(business_id)}",
                                   {"emailed": have + more})


async def email_rest(business: Dict[str, Any], group: Dict[str, Any], post: Dict[str, Any],
                     author: Dict[str, Any]) -> int:
    """"Email the rest": the group's people with no phone set up for the
    member app. Returns how many emails went."""
    biz_id = str(business["id"])
    members = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/group_members?group_id=eq.{_q(group['id'])}&business_id=eq.{_q(biz_id)}&select=contact_id&limit=5000")
    phones = await asyncio.to_thread(
        sb_clients.sb_get_as_service, f"/member_push_subscriptions?business_id=eq.{_q(biz_id)}&select=contact_id&limit=5000")
    if not isinstance(members, list) or not isinstance(phones, list):
        return 0
    have_phone = {str(r["contact_id"]) for r in phones}
    ids = sorted({str(r["contact_id"]) for r in members} - have_phone - {str(author.get("id") or "")})
    if not ids:
        return 0
    people = await asyncio.to_thread(_people, biz_id, ids)
    if people is None:
        return 0
    app = await asyncio.to_thread(app_url, biz_id)
    first = str(author.get("name") or "").split(" ")[0] or "A leader"
    church = (business.get("name") or "").strip() or "your church"
    sent = await _send_all(business, group, post, first, people, app,
                           f"You’re getting this because you’re in {group.get('name') or 'this group'} at {church}.")
    await asyncio.to_thread(_count, biz_id, str(post["id"]), sent)
    return sent


def spawn(coro) -> None:
    """Off the request: the leader's post is up before any email goes."""
    try:
        task = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        coro.close()
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# ─── the one-hour follow-up ──────────────────────────────────────────


async def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every 15 minutes (kmj_intake_automation, leader only): each leader's
    post an hour old, once (missed_checked_at is claimed first), to the
    members who asked and haven't opened it."""
    now = now or datetime.now(timezone.utc)
    out = {"posts": 0, "emails": 0}
    due = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/group_posts?missed_checked_at=is.null&removed_at=is.null&group_id=not.is.null"
        f"&created_at=lte.{_q((now - MISSED_AFTER).isoformat())}&created_at=gte.{_q((now - MISSED_WINDOW).isoformat())}"
        f"&select=id,business_id,group_id,title,body,posted_by,created_at&order=created_at.asc&limit=200")
    if not isinstance(due, list):
        return out
    for post in due:
        claimed = await asyncio.to_thread(
            sb_clients.sb_patch_as_service,
            f"/group_posts?id=eq.{_q(post['id'])}&missed_checked_at=is.null", {"missed_checked_at": now.isoformat()})
        if not isinstance(claimed, list) or not claimed:
            continue   # someone else took it
        out["posts"] += 1
        try:
            out["emails"] += await _follow_up(post)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[group-email] follow-up failed: {type(e).__name__}")
    if out["posts"]:
        logger.info(f"[group-email] {out}")
    return out


async def _follow_up(post: Dict[str, Any]) -> int:
    biz_id, gid = str(post["business_id"]), str(post["group_id"])
    rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service, f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,settings&limit=1")
    group = await asyncio.to_thread(
        sb_clients.sb_get_as_service, f"/groups?id=eq.{_q(gid)}&business_id=eq.{_q(biz_id)}&active=eq.true&select=id,name&limit=1")
    members = await asyncio.to_thread(
        sb_clients.sb_get_as_service, f"/group_members?group_id=eq.{_q(gid)}&business_id=eq.{_q(biz_id)}&select=contact_id&limit=5000")
    wants = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/member_push_prefs?business_id=eq.{_q(biz_id)}&email_missed=is.true&select=contact_id&limit=5000")
    seen = await asyncio.to_thread(
        sb_clients.sb_get_as_service, f"/group_post_seen?post_id=eq.{_q(post['id'])}&business_id=eq.{_q(biz_id)}&select=contact_id&limit=5000")
    if not all(isinstance(x, list) for x in (rows, group, members, wants, seen)) or not rows or not group:
        return 0
    ids = sorted(({str(r["contact_id"]) for r in members} & {str(r["contact_id"]) for r in wants})
                 - {str(r["contact_id"]) for r in seen} - {str(post.get("posted_by") or "")})
    if not ids:
        return 0
    people = await asyncio.to_thread(_people, biz_id, ids)
    author = await asyncio.to_thread(
        sb_clients.sb_get_as_service, f"/contacts?id=eq.{_q(post.get('posted_by'))}&business_id=eq.{_q(biz_id)}&select=name&limit=1")
    if people is None:
        return 0
    first = str(((author or [{}])[0] if isinstance(author, list) and author else {}).get("name") or "").split(" ")[0] or "A leader"
    app = await asyncio.to_thread(app_url, biz_id)
    sent = await _send_all(rows[0], group[0], post, first, people, app,
                           "You’re getting this because you asked for an email when your phone misses a leader’s post. "
                           "Change it in the member app, under Me, Notifications.")
    await asyncio.to_thread(_count, biz_id, str(post["id"]), sent)
    return sent
