"""
group_post_later.py — a leader's Board post that goes out later.

From the approved canvas "Church Groups, Together" (board Post: "Send later
· Thursday at 9:00 AM … It goes out Thursday at 9:00 AM. You can change it
on the Board until then.").

  * on the Board's compose, a leader picks a day and time on the church's
    own clock (from 5 minutes to 30 days ahead); the post is checked like
    any other when it's written
  * until then only the group's leaders see it, marked Scheduled, with
    Send now and Take it down; members see nothing
  * at its time it shows on the Board, and the scheduled job
    (group_post_later, every 5 minutes) sends the group's note and the
    email to the rest, once (told_at); a pin waits until then too

group_posts.publish_at (null = it went out when written) and told_at.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger(__name__)

EARLIEST = timedelta(minutes=5)
LATEST = timedelta(days=30)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def when_from(business: Dict[str, Any], raw: str, now: Optional[datetime] = None) -> Tuple[Optional[datetime], str]:
    """(when, '') for a datetime-local value on the church's clock, or
    (None, code): '' when nothing was picked."""
    import group_gatherings as gg
    raw = str(raw or "").strip()
    if not raw:
        return None, ""
    tz = gg.zone(business)
    if tz is None:
        return None, "error"
    try:
        local = datetime.fromisoformat(raw[:16]).replace(tzinfo=tz)
    except ValueError:
        return None, "later_bad"
    now = now or _now()
    if local < now + EARLIEST or local > now + LATEST:
        return None, "later_bad"
    return local, ""


def is_waiting(p: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """Scheduled and not yet out."""
    at = p.get("publish_at")
    if not at:
        return False
    try:
        return datetime.fromisoformat(str(at).replace("Z", "+00:00")) > (now or _now())
    except ValueError:
        return False


def label(business: Dict[str, Any], at: Any) -> str:
    """'Thursday, October 22 · 9:00 AM' on the church's clock."""
    import group_gatherings as gg
    tz = gg.zone(business)
    t = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    if tz is not None:
        t = t.astimezone(tz)
    return f"{gg.DAYS[t.weekday()]}, {t.strftime('%B')} {t.day} · {t.strftime('%I:%M %p').lstrip('0')}"


# ─── going out ───────────────────────────────────────────────────────


def _go_out(post: Dict[str, Any], now: datetime) -> bool:
    """Claim the post (told_at, once), then its pin, note and emails."""
    import member_push
    biz_id, gid = str(post["business_id"]), str(post["group_id"])
    claimed = sb_clients.sb_patch_as_service(
        f"/group_posts?id=eq.{_q(post['id'])}&business_id=eq.{_q(biz_id)}&told_at=is.null&removed_at=is.null",
        {"told_at": now.isoformat()})
    if not isinstance(claimed, list) or not claimed:
        return False
    bizs = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,settings,owner_id&limit=1")
    gs = sb_clients.sb_get_as_service(f"/groups?id=eq.{_q(gid)}&business_id=eq.{_q(biz_id)}&select=id,name&limit=1")
    who = sb_clients.sb_get_as_service(
        f"/contacts?id=eq.{_q(post.get('posted_by') or '')}&business_id=eq.{_q(biz_id)}&select=id,name&limit=1")
    if not bizs or not gs:
        return True
    business, g, author = bizs[0], gs[0], (who or [{}])[0] if isinstance(who, list) else {}
    if post.get("pinned"):
        # One pin per group: it takes the top now, not when it was written.
        sb_clients.sb_patch_as_service(
            f"/group_posts?business_id=eq.{_q(biz_id)}&group_id=eq.{_q(gid)}&pinned=eq.true&id=neq.{_q(post['id'])}",
            {"pinned": False})
    member_push.tell_group_post(business, g, str(post["id"]), author, str(post.get("title") or ""))
    if post.get("email_rest"):
        import group_email
        try:
            asyncio.run(group_email.email_rest(business, g, post, author))
        except RuntimeError:
            group_email.spawn(group_email.email_rest(business, g, post, author))
    return True


def sweep_tick(now: Optional[datetime] = None) -> int:
    """Every 5 minutes: scheduled posts whose time has come."""
    now = now or _now()
    rows = sb_clients.sb_get_as_service(
        f"/group_posts?publish_at=lte.{_q(now.isoformat())}&told_at=is.null&removed_at=is.null&group_id=not.is.null"
        f"&select=id,business_id,group_id,title,body,pinned,posted_by,email_rest,publish_at&order=publish_at.asc&limit=200")
    if not isinstance(rows, list):
        return 0
    sent = 0
    for p in rows:
        try:
            sent += 1 if _go_out(p, now) else 0
        except Exception:
            logger.warning("a scheduled group post failed to go out", exc_info=True)
    return sent


def send_now(business: Dict[str, Any], me: Dict[str, Any], post_id: str) -> Tuple[bool, str, str]:
    """A leader of its group (or whoever wrote it) sends a scheduled post now.
    (ok, code, group_id)."""
    import member_portal_groups as mpg
    biz_id = str(business["id"])
    rows = sb_clients.sb_get_as_service(
        f"/group_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(biz_id)}&removed_at=is.null&group_id=not.is.null"
        f"&select=id,business_id,group_id,title,body,pinned,posted_by,email_rest,publish_at,told_at&limit=1")
    if not isinstance(rows, list):
        return False, "error", ""
    if not rows:
        return False, "post_gone", ""
    p = rows[0]
    gid = str(p["group_id"])
    leader = mpg._is_leader(biz_id, gid, me["id"])
    if leader is None:
        return False, "error", gid
    if not leader and str(p.get("posted_by") or "") != str(me["id"]):
        return False, "not_group_leader", gid
    if p.get("told_at"):
        return True, "post_up", gid
    now = _now()
    sb_clients.sb_patch_as_service(f"/group_posts?id=eq.{_q(p['id'])}&business_id=eq.{_q(biz_id)}", {"publish_at": now.isoformat()})
    _go_out(p, now)
    return True, "post_up", gid


COMPOSE_LATER = """<details class="gs-later"><summary class="gs-mini">{icon}Send later</summary>
<label class="gs-l" for="gs-at">When it goes out</label>
<input type="datetime-local" id="gs-at" name="send_at" min="{min}" max="{max}">
<p class="gs-fine">Your church’s time. Until then only the group’s leaders see it. Leave it empty to post now.</p></details>"""

LATER_CSS = """
.gs-later summary{list-style:none;}
.gs-later summary::-webkit-details-marker{display:none;}
.gs-later input[type=datetime-local]{width:100%;min-height:46px;border:0;outline:none;background:var(--bg);color:var(--fg);border-radius:12px;
  padding:0 14px;font:inherit;font-size:16px;box-sizing:border-box;}
.gs-card.later{box-shadow:inset 0 0 0 1.5px var(--line);background:transparent;}
.gs-tag.later{background:var(--s2);color:var(--fg2);}
"""


def compose_later(business: Dict[str, Any], ic) -> str:
    """The Send later fold on a leader's compose (church clock bounds)."""
    import group_gatherings as gg
    tz = gg.zone(business)
    now = _now().astimezone(tz) if tz is not None else _now()
    lo, hi = now + EARLIEST, now + LATEST
    return COMPOSE_LATER.format(icon=ic("clock", 15), min=lo.strftime("%Y-%m-%dT%H:%M"), max=hi.strftime("%Y-%m-%dT%H:%M"))
