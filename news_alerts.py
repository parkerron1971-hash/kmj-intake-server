"""
news_alerts.py — phone alerts and the week's email for the church's news.

Part 5 of the approved canvas "Church News & Celebrations"
(Hfrz3Y174kbDmJv1G4puVq): board 6's "What you hear about" (Important,
Everything or Off; birthdays in my groups; replies to my comments; the
week's news by email) and board 9's Phone alerts (up to three a day, shared
with the church's other alerts; celebrations as one 9 AM note about people
in your own groups, or none; quiet hours 9 PM to 7 AM). On the Write board,
"Important: ring their phones".

Every note is member_push kind "news", so the church's own switch
(Settings → Member page, or News & celebrations → Settings) and the
member's own boxes still decide first, and quiet hours hold it for the
morning (member_push.QUIET_KINDS).

  * a post rings once, when it goes up (church_posts.alerted_at; a
    scheduled post when its time comes): to members who keep Important or
    Everything when a pastor marked it important, to members who chose
    Everything otherwise; only the people it's for (a ministry's, a
    group's), never whoever posted it
  * no more than DAILY_MAX a day from the church, counting its
    announcements (member_push.DAILY_ANNOUNCEMENTS); a post past that
    doesn't ring and is still on News
  * a reply to your comment: "Dana replied to your comment" (what was said
    never goes on a lock screen)
  * birthdays and anniversaries: one note after 9 AM, to the people in the
    celebrated person's own groups, naming everyone of theirs celebrated
    that day, unless the church chose no celebration alerts
    (settings.news.celebration_alerts = 'none')
  * the week's email: Saturdays after 9 AM, to members who asked for it, with
    the week's posts they haven't seen (none unseen, no email); once a week
    (church_news_digests). Grown-ups only, like the groups' email
  * the sweep runs every 15 minutes (kmj_intake_automation "news_alerts")

Records: member_push_prefs.news_level / news_birthdays / news_replies /
news_email, church_posts.alerted_at, church_news_digests
(supabase/APPLY-2026-10-23-news-alerts.sql).
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import sb_clients

logger = logging.getLogger("news_alerts")

KIND = "news"
LEVELS = ("important", "everything", "off")
BIRTHDAY_HOUR = 9
DIGEST_WEEKDAY, DIGEST_HOUR = 5, 9      # Saturday, 9 AM on the church's clock
ALERT_WINDOW_HOURS = 36                  # a post older than this isn't news any more


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def daily_max() -> int:
    import member_push
    return member_push.DAILY_ANNOUNCEMENTS


def church_on(business: Dict[str, Any]) -> bool:
    import member_push
    return KIND in member_push.church_kinds(business.get("settings"))


def celebration_alerts(business: Dict[str, Any]) -> bool:
    news = ((business or {}).get("settings") or {}).get("news") or {}
    return not (isinstance(news, dict) and news.get("celebration_alerts") == "none")


# ─── what each member chose ─────────────────────────────────────────


def _pref(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    r = row or {}
    level = r.get("news_level") if r.get("news_level") in LEVELS else "important"
    return {"level": level, "birthdays": r.get("news_birthdays") is not False,
            "replies": r.get("news_replies") is not False, "email": r.get("news_email") is True,
            "muted": KIND in (r.get("off") or [])}


def prefs(business_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/member_push_prefs?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}"
        f"&select=off,news_level,news_birthdays,news_replies,news_email&limit=1")
    if rows is None:
        return None
    return _pref(rows[0] if rows else None)


def _prefs_of(business_id: str, ids: List[str]) -> Optional[Dict[str, Dict[str, Any]]]:
    out: Dict[str, Dict[str, Any]] = {}
    ids = sorted({str(i) for i in ids if i})
    for i in range(0, len(ids), 150):
        rows = sb_clients.sb_get_as_service(
            f"/member_push_prefs?business_id=eq.{_q(business_id)}&contact_id=in.({','.join(_q(x) for x in ids[i:i + 150])})"
            f"&select=contact_id,off,news_level,news_birthdays,news_replies,news_email&limit=5000")
        if rows is None:
            return None
        out.update({str(r["contact_id"]): _pref(r) for r in rows})
    return {c: out.get(c) or _pref(None) for c in ids}


def save_prefs(business_id: str, contact_id: str, level: str, birthdays: bool, replies: bool, email: bool) -> bool:
    rows = sb_clients.sb_post_as_service(
        "/member_push_prefs?on_conflict=business_id,contact_id",
        {"business_id": str(business_id), "contact_id": str(contact_id),
         "news_level": level if level in LEVELS else "important", "news_birthdays": bool(birthdays),
         "news_replies": bool(replies), "news_email": bool(email), "updated_at": _now().isoformat()},
        prefer="resolution=merge-duplicates,return=representation")
    return bool(rows)


# ─── a post going up ────────────────────────────────────────────────


def _day_start(business: Dict[str, Any], now: Optional[datetime] = None) -> datetime:
    import celebrations as cel
    here = cel.local_now(business, now)
    return datetime.combine(here.date(), time(0, 0), tzinfo=here.tzinfo).astimezone(timezone.utc)


def sent_today(business: Dict[str, Any], now: Optional[datetime] = None) -> Optional[int]:
    """Alerts the church sent today on its own clock: News posts that rang,
    and its announcements. None when the count can't be read."""
    b = _q(business["id"])
    since = _q(_day_start(business, now).isoformat())
    posts = sb_clients.sb_get_as_service(
        f"/member_push_sends?business_id=eq.{b}&kind=eq.{KIND}&ref_id=like.news-post:*&created_at=gte.{since}&select=id&limit=50")
    notes = sb_clients.sb_get_as_service(
        f"/member_push_sends?business_id=eq.{b}&kind=eq.announcements&created_at=gte.{since}&select=id&limit=50")
    if posts is None or notes is None:
        return None
    return len(posts) + len(notes)


def _devices(business_id: str) -> Optional[set]:
    rows = sb_clients.sb_get_as_service(
        f"/member_push_subscriptions?business_id=eq.{_q(business_id)}&select=contact_id&limit=50000")
    return None if rows is None else {str(r["contact_id"]) for r in rows}


def recipients(business: Dict[str, Any], post: Dict[str, Any]) -> Optional[List[str]]:
    """Who this post rings: the people it's for with a phone set up, by what
    they chose. Never whoever posted it."""
    import church_news as cn
    biz_id = str(business["id"])
    have = _devices(biz_id)
    if have is None:
        return None
    if cn.scoped(post):
        gids = [str(post["group_id"])] if post.get("group_id") else [str(g) for g in (post.get("attach") or {}).get("groups") or []]
        rows = sb_clients.sb_get_as_service(
            f"/group_members?business_id=eq.{_q(biz_id)}&group_id=in.({cn._ids(gids)})&select=contact_id&limit=50000")
        if rows is None:
            return None
        have &= {str(r["contact_id"]) for r in rows}
    have.discard(str(post.get("posted_by") or ""))
    chose = _prefs_of(biz_id, sorted(have))
    if chose is None:
        return None
    want = ("important", "everything") if post.get("important") else ("everything",)
    return sorted(c for c, p in chose.items() if not p["muted"] and p["level"] in want)


def _mark(business_id: str, post_id: str) -> Optional[list]:
    """Claim the post (once): the rows claimed, [] when it was already, None on failure."""
    return sb_clients.sb_patch_as_service(
        f"/church_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(business_id)}&alerted_at=is.null",
        {"alerted_at": _now().isoformat()})


def alert_post(business: Dict[str, Any], post: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Ring for one post, once, when it's up. {'rang': phones, 'why': ''|'off'|'later'|'old'|'full'|'nobody'|'busy'}."""
    import church_news as cn
    import member_push
    now = now or _now()
    biz_id = str(business["id"])
    if post.get("alerted_at") or post.get("status") != "posted" or post.get("removed_at"):
        return {"rang": 0, "why": "old"}
    at = cn._ts(post.get("publish_at")) or cn._ts(post.get("created_at")) or now
    if at > now:
        return {"rang": 0, "why": "later"}
    if not church_on(business):
        return {"rang": 0, "why": "off"}
    if at < now - timedelta(hours=ALERT_WINDOW_HOURS):
        _mark(biz_id, str(post["id"]))
        return {"rang": 0, "why": "old"}
    n = sent_today(business, now)
    people = recipients(business, post)
    if n is None or people is None:
        return {"rang": 0, "why": "busy"}
    claimed = _mark(biz_id, str(post["id"]))
    if not claimed:
        return {"rang": 0, "why": "old" if claimed == [] else "busy"}
    if n >= daily_max():
        return {"rang": 0, "why": "full"}
    if not people:
        return {"rang": 0, "why": "nobody"}
    words = (post.get("title") or post.get("body") or "").strip()
    rang = member_push.send(business, KIND, title=business.get("name") or "Your church",
                            body=(("Important: " if post.get("important") else "") + words)[:member_push.BODY_MAX],
                            url=f"/my/news/{post['id']}", contact_ids=people, ref_id=f"news-post:{post['id']}",
                            tag=f"news-{post['id']}")
    return {"rang": rang, "why": ""}


def alert_later(business: Dict[str, Any], post: Dict[str, Any]) -> None:
    """After a post goes up now, off the request's path."""
    import member_push
    member_push._later(alert_post, business, post)


# ─── a reply ────────────────────────────────────────────────────────


def tell_reply(business: Dict[str, Any], post_id: str, comment_id: str, to_id: str, by: Dict[str, Any]) -> int:
    """"Dana replied to your comment", to the person answered."""
    import member_push
    if not church_on(business) or str(to_id) == str(by.get("id")):
        return 0
    p = prefs(str(business["id"]), str(to_id))
    if not p or not p["replies"] or p["muted"]:
        return 0
    first = (by.get("name") or "").strip().split(" ")[0] or "Someone"
    return member_push.send(business, KIND, title=business.get("name") or "Your church",
                            body=f"{first} replied to your comment", url=f"/my/news/{post_id}#c-{comment_id}",
                            contact_ids=[str(to_id)], ref_id=f"news-reply:{comment_id}", tag=f"news-reply-{post_id}")


# ─── birthdays in my groups ─────────────────────────────────────────


def _named(post: Dict[str, Any], names: Dict[str, Dict[str, Any]]) -> str:
    first = lambda c: ((names.get(str(c)) or {}).get("name") or "").strip().split(" ")[0] or "Someone"  # noqa: E731
    sub = (post.get("attach") or {}).get("sub")
    if sub == "anniversary" and post.get("partner_id"):
        return f"{first(post['person_id'])} & {first(post['partner_id'])}'s anniversary"
    return f"{first(post['person_id'])}'s birthday"


def birthday_notes(business: Dict[str, Any], now: Optional[datetime] = None) -> int:
    """After 9 AM: one note to each person in a celebrated person's own
    groups (not the celebrated themselves)."""
    import celebrations as cel
    import church_news as cn
    import member_push
    if not church_on(business) or not celebration_alerts(business):
        return 0
    here = cel.local_now(business, now)
    if not (BIRTHDAY_HOUR <= here.hour < member_push.QUIET_FROM):
        return 0
    biz_id, today = str(business["id"]), here.date().isoformat()
    posts = sb_clients.sb_get_as_service(
        f"/church_posts?business_id=eq.{_q(biz_id)}&kind=eq.celebration&celebrate_on=eq.{today}&status=eq.posted"
        f"&removed_at=is.null&select=id,person_id,partner_id,attach&limit=100")
    if not posts:
        return 0
    people = [str(c) for p in posts for c in (p.get("person_id"), p.get("partner_id")) if c]
    theirs = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{_q(biz_id)}&contact_id=in.({cn._ids(people)})&select=group_id,contact_id&limit=5000")
    names = cn._people(biz_id, people)
    have = _devices(biz_id)
    if theirs is None or names is None or have is None:
        return 0
    groups_of: Dict[str, set] = {}
    for r in theirs:
        groups_of.setdefault(str(r["contact_id"]), set()).add(str(r["group_id"]))
    gids = sorted({g for gs in groups_of.values() for g in gs})
    if not gids:
        return 0
    members = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{_q(biz_id)}&group_id=in.({cn._ids(gids)})&select=group_id,contact_id&limit=50000")
    if members is None:
        return 0
    told: Dict[str, List[str]] = {}
    for p in posts:
        mine = groups_of.get(str(p["person_id"]), set()) | groups_of.get(str(p.get("partner_id") or ""), set())
        them = {str(p["person_id"]), str(p.get("partner_id") or "")}
        for m in members:
            c = str(m["contact_id"])
            if str(m["group_id"]) in mine and c not in them and c in have:
                line = _named(p, names)
                if line not in told.setdefault(c, []):
                    told[c].append(line)
    chose = _prefs_of(biz_id, sorted(told))
    if chose is None:
        return 0
    sent = 0
    for c, lines in sorted(told.items()):
        if not chose[c]["birthdays"] or chose[c]["muted"]:
            continue
        body = (f"It's {lines[0]} today." if len(lines) == 1
                else "Today: " + ", ".join(lines[:-1]) + " and " + lines[-1] + ".")
        sent += member_push.send(business, KIND, title=business.get("name") or "Your church", body=body, url="/my",
                                 contact_ids=[c], ref_id=f"news-bday:{today}:{c}", tag=f"news-bday-{today}")
    return sent


# ─── the week's news by email ───────────────────────────────────────


def digest(business: Dict[str, Any], now: Optional[datetime] = None) -> int:
    """Saturdays after 9 AM: the week's posts each member who asked hasn't
    seen. Grown-ups only; once a week."""
    import asyncio
    import celebrations as cel
    import church_news as cn
    import group_email
    here = cel.local_now(business, now)
    if here.weekday() != DIGEST_WEEKDAY or here.hour < DIGEST_HOUR:
        return 0
    biz_id = str(business["id"])
    b = _q(biz_id)
    asked = sb_clients.sb_get_as_service(
        f"/member_push_prefs?business_id=eq.{b}&news_email=is.true&select=contact_id&limit=50000")
    if not asked:
        return 0
    week_of = (here.date() - timedelta(days=here.weekday())).isoformat()
    done = sb_clients.sb_get_as_service(f"/church_news_digests?business_id=eq.{b}&week_of=eq.{week_of}&select=contact_id&limit=50000")
    if done is None:
        return 0
    ids = sorted({str(r["contact_id"]) for r in asked} - {str(r["contact_id"]) for r in done})
    if not ids:
        return 0
    since = _q(((now or _now()) - timedelta(days=7)).isoformat())
    posts = sb_clients.sb_get_as_service(
        f"/church_posts?business_id=eq.{b}&status=eq.posted&removed_at=is.null&created_at=gte.{since}"
        f"&select={cn.POST_SELECT}&order=created_at.desc&limit=60")
    people = group_email._people(biz_id, ids)
    if posts is None or people is None:
        return 0
    posts = [p for p in posts if cn.is_live(p, now or _now()) and not cn.is_person_celebration(p)]
    if not posts:
        return 0
    app = group_email.app_url(biz_id)
    sent = 0
    for person in people:
        if not group_email._adult(person):
            continue
        cid = str(person["id"])
        groups = cn.my_groups(biz_id, cid)
        seen = sb_clients.sb_get_as_service(
            f"/church_post_seen?business_id=eq.{b}&contact_id=eq.{_q(cid)}&post_id=in.({cn._ids(p['id'] for p in posts)})"
            f"&select=post_id&limit=500")
        if groups is None or seen is None:
            continue
        had = {str(s["post_id"]) for s in seen}
        theirs = [p for p in posts if cn.reaches(p, set(groups), cid) and str(p["id"]) not in had]
        if not theirs:
            continue
        claimed = sb_clients.sb_post_as_service(
            "/church_news_digests?on_conflict=business_id,contact_id,week_of",
            {"business_id": biz_id, "contact_id": cid, "week_of": week_of, "posts": len(theirs)},
            prefer="resolution=ignore-duplicates,return=representation")
        if not claimed:
            continue
        try:
            asyncio.run(_email(business, person, theirs, app))
            sent += 1
        except Exception:  # noqa: BLE001 — one address never stops the rest
            logger.warning("news digest: one email failed", exc_info=True)
    return sent


async def _email(business: Dict[str, Any], person: Dict[str, Any], posts: List[Dict[str, Any]], app: Optional[str]) -> None:
    import os
    import academy_join
    import email_layout
    import email_sender
    email = str(person.get("email") or "").strip()
    if not academy_join.valid_email(email):
        return
    church = (business.get("name") or "").strip() or "Your church"
    settings = business.get("settings") if isinstance(business.get("settings"), dict) else {}
    lines = []
    for p in posts[:8]:
        head = (p.get("title") or "").strip()
        body = " ".join(str(p.get("body") or "").split())
        lines.append(f"{head}\n{body[:200]}" if head else body[:240])
    more = len(posts) - len(lines)
    message = "\n\n".join([f"Here's what {church} shared this week that you haven't seen yet."] + lines
                          + ([f"And {more} more on News."] if more > 0 else []))
    html = email_layout.render_html(
        message, business_name=church, brand=email_layout.brand_of(settings), sig=None,
        unsubscribe_url=email_sender._unsubscribe_url(email), preheader=(posts[0].get("title") or "")[:90],
        cta=(("Open News", f"{app}/my/news") if app else None),
        disclaimer=f"You asked for the week's news from {church} by email. Turn it off in the app: Me, Celebrations.")
    await email_sender.send_via_resend(
        to_email=email, to_name=person.get("name") or None,
        from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
        from_name=church, subject=f"This week at {church}"[:150], body=html, reply_to=None,
        business_id=str(business["id"]), idempotency_key=f"church-news-digest-{business['id']}-{person['id']}-{posts[0]['id']}")


# ─── the sweep ──────────────────────────────────────────────────────


def _churches() -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        "/businesses?settings->member_portal->notifications->>news=eq.true&select=id,name,settings,owner_id&limit=5000")
    return rows or []


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every 15 minutes: posts whose time came, the morning's birthday notes,
    Saturday's email."""
    import church_news as cn
    out = {"posts": 0, "birthdays": 0, "digests": 0}
    now = now or _now()
    since = _q((now - timedelta(hours=ALERT_WINDOW_HOURS + 12)).isoformat())
    for biz in _churches():
        try:
            due = sb_clients.sb_get_as_service(
                f"/church_posts?business_id=eq.{_q(biz['id'])}&status=eq.posted&removed_at=is.null&alerted_at=is.null"
                f"&created_at=gte.{since}&select={cn.POST_SELECT},alerted_at,removed_at&order=created_at.asc&limit=40") or []
            for p in due:
                if p.get("kind") == "celebration" and p.get("person_id"):
                    _mark(str(biz["id"]), str(p["id"]))     # a birthday rings as the 9 AM note, not as a post
                    continue
                if alert_post(biz, p, now)["rang"]:
                    out["posts"] += 1
            out["birthdays"] += birthday_notes(biz, now)
            out["digests"] += digest(biz, now)
        except Exception:
            logger.warning("news alerts: one church failed", exc_info=True)
    return out
