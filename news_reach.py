"""
news_reach.py — an important post reaches the people without the app.

Kevin, 2026-10-28: "texting only people without app alerts", important posts
only, "with email as you shared". A post a pastor marks Important rings the
phones of the people who set the member app up (news_alerts). This reaches
the rest of the people it's for, once:

  * a TEXT, from the church's own number under its own registered name
    (sms_routing.own_registration, and that number active), to those who
    said yes to its texts (sms_alerts.said_yes_to_texts, the mixed rule) and
    haven't turned "Text me important news" off (member_push_prefs.news_texts).
    Never from the shared number: words a church wrote don't go out on the
    platform's campaign. One plain 160-character part: the post's title (or
    first words) and its link. send_sms_core leads it with the church's name,
    checks STOP and the mixed rule again, and keeps the thread. A text that
    doesn't go becomes that person's email;
  * an EMAIL to everyone else it's for with an address, in the church's
    branded layout with a one-click unsubscribe, the way a group's "Email the
    rest" goes (group_email).

Who it's for: the post's ministry or groups, or the whole church's members
(contacts not marked lead or inactive: guests aren't sent the church's news).
Never whoever posted it, never a known minor (group_email._adult), never
someone with a phone set up for the app (their phone rang), never someone who
chose Off for News or muted it.

Limits: nothing between 9 PM and 7 AM at the church (member_push.quiet_hour);
the sweep sends it after 7. At most REACH_DAILY posts a day. At most
texts_cap() texts a month per church (NEWS_TEXTS_MONTH, default 500); past it
the rest get the email. A church can switch it off: settings.news.reach_rest
= false (News & celebrations, Settings).

Records: church_posts.reached_at (claimed once) and church_posts.reach
({texts, emails, phones, at}, or {why}); member_push_prefs.news_texts
(supabase/APPLY-2026-10-28-news-reach.sql).

  plan(business, post)     who'd get a text and who an email (the composer's line)
  reach(business, post)    send it, once
  sweep_tick()             every 15 minutes: important posts still waiting
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger("news_reach")

REACH_DAILY = 3                       # posts a day that reach past the app
WINDOW_HOURS = 36                     # older than this isn't news any more
NOT_MEMBERS = ("lead", "inactive")    # contacts.status: guests and people who left
TEXT_MAX = 160                        # one part, plain letters
TEXT_PACE = 0.25                      # seconds between texts, like the bulletin
PAGE = 1000                           # rows per read


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def texts_cap() -> int:
    try:
        return max(0, int(os.environ.get("NEWS_TEXTS_MONTH", "500")))
    except ValueError:
        return 500


def church_on(business: Dict[str, Any]) -> bool:
    news = ((business or {}).get("settings") or {}).get("news") or {}
    return not (isinstance(news, dict) and news.get("reach_rest") is False)


def _all(path: str) -> Optional[List[Dict[str, Any]]]:
    """Every row, a page at a time (a read past the server's page size would
    otherwise stop quietly at the first page)."""
    out: List[Dict[str, Any]] = []
    for off in range(0, 200 * PAGE, PAGE):
        rows = sb_clients.sb_get_as_service(f"{path}&limit={PAGE}&offset={off}")
        if rows is None:
            return None
        out += rows
        if len(rows) < PAGE:
            return out
    return out


# ─── who it's for ────────────────────────────────────────────────────


def audience(business: Dict[str, Any], post: Dict[str, Any]) -> Optional[Set[str]]:
    """The people the post is for: its ministry's or groups' members, or the
    church's members. Never whoever posted it."""
    import church_news as cn
    b = _q(business["id"])
    if cn.scoped(post):
        gids = ([str(post["group_id"])] if post.get("group_id")
                else [str(g) for g in (post.get("attach") or {}).get("groups") or []])
        rows = _all(f"/group_members?business_id=eq.{b}&group_id=in.({cn._ids(gids)})&select=contact_id&order=contact_id.asc")
        ids = None if rows is None else {str(r["contact_id"]) for r in rows}
    else:
        rows = _all(f"/contacts?business_id=eq.{b}&or=(status.is.null,status.not.in.({','.join(NOT_MEMBERS)}))"
                    f"&select=id&order=id.asc")
        ids = None if rows is None else {str(r["id"]) for r in rows}
    if ids is not None:
        ids.discard(str(post.get("posted_by") or ""))
    return ids


def _people(business_id: str, ids: List[str]) -> Optional[List[Dict[str, Any]]]:
    out: List[Dict[str, Any]] = []
    for i in range(0, len(ids), 150):
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(business_id)}&id=in.({','.join(_q(x) for x in ids[i:i + 150])})"
            f"&select=id,name,email,phone,birthdate&limit=500")
        if rows is None:
            return None
        out += rows
    return out


async def _texting(business_id: str, people: List[Dict[str, Any]]) -> Optional[Tuple[bool, Set[str]]]:
    """(the church texts under its own name from its own active number, the
    phones that said yes to its texts). None when the yes couldn't be read."""
    import httpx
    import sms_alerts
    import sms_routing
    import sms_service
    async with httpx.AsyncClient() as client:
        own = await sms_routing.own_registration(client, business_id)
        if not own:
            return False, set()
        active = await sms_service.active_number_for(client, business_id)
        if not active or sms_service.normalize_phone(active) != sms_service.normalize_phone(own.get("number")):
            return False, set()      # suspended: its texts would leave from the shared number
        yes = await sms_alerts.said_yes_to_texts(client, business_id, [p.get("phone") for p in people])
    return None if yes is None else (True, yes)


def _month_start(business: Dict[str, Any], now: datetime) -> datetime:
    import celebrations as cel
    here = cel.local_now(business, now)
    return here.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _reached_since(business: Dict[str, Any], since: datetime) -> Optional[List[Dict[str, Any]]]:
    rows = _all(f"/church_posts?business_id=eq.{_q(business['id'])}&reached_at=gte.{_q(since.isoformat())}"
                f"&select=id,reach&order=id.asc")
    return None if rows is None else [r for r in rows if isinstance(r.get("reach"), dict) and not r["reach"].get("why")]


def texts_used(business: Dict[str, Any], now: Optional[datetime] = None) -> Optional[int]:
    """Texts this church's news sent this month (its own clock)."""
    rows = _reached_since(business, _month_start(business, now or _now()))
    return None if rows is None else sum(int(r["reach"].get("texts") or 0) for r in rows)


def reached_today(business: Dict[str, Any], now: Optional[datetime] = None) -> Optional[int]:
    import news_alerts as na
    rows = _reached_since(business, na._day_start(business, now))
    return None if rows is None else len(rows)


def plan(business: Dict[str, Any], post: Dict[str, Any], now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Who this post would reach past the app, without sending anything:
    {'phones': rang in the app, 'texts': [person], 'emails': [person],
    'texting': the church texts under its own name, 'used', 'cap'}. None
    when something couldn't be read."""
    import academy_join
    import group_email
    import news_alerts as na
    from sms_service import normalize_phone
    biz = str(business["id"])
    aud = audience(business, post)
    devices = _all(f"/member_push_subscriptions?business_id=eq.{_q(biz)}&select=contact_id&order=id.asc")
    if aud is None or devices is None:
        return None
    have = {str(r["contact_id"]) for r in devices}
    rest = sorted(aud - have)
    chose = na._prefs_of(biz, rest) if rest else {}
    if chose is None:
        return None
    rest = [c for c in rest if not chose[c]["muted"] and chose[c]["level"] != "off"]
    people = _people(biz, rest) if rest else []
    if people is None:
        return None
    people = sorted((p for p in people if group_email._adult(p)), key=lambda p: str(p["id"]))
    texting = asyncio.run(_texting(biz, people)) if people else (False, set())
    used = texts_used(business, now)
    if texting is None or used is None:
        return None
    on, yes = texting
    room = max(0, texts_cap() - used)
    texts: List[Dict[str, Any]] = []
    emails: List[Dict[str, Any]] = []
    phones_done: Set[str] = set()
    emails_done: Set[str] = set()
    for p in people:
        phone = normalize_phone(p.get("phone"))
        email = str(p.get("email") or "").strip().lower()
        if (on and phone and phone in yes and phone not in phones_done and chose[str(p["id"])]["texts"]
                and len(texts) < room):
            texts.append({**p, "phone": phone})
            phones_done.add(phone)
        elif academy_join.valid_email(email) and email not in emails_done:
            emails.append(p)
            emails_done.add(email)
    return {"phones": len(aud & have), "texts": texts, "emails": emails, "texting": on,
            "used": used, "cap": texts_cap()}


# ─── what goes ───────────────────────────────────────────────────────


def _plain(text: str) -> str:
    """Plain letters only: typography swapped for its stand-in, anything else
    outside GSM-7 (an emoji) dropped, so the text stays one cheap part."""
    import twilio_sms
    s = twilio_sms.gsm_safe(" ".join(str(text or "").split()))
    return "".join(c for c in s if c in twilio_sms._GSM_BASIC).strip()


def text_for(business: Dict[str, Any], post: Dict[str, Any], app: Optional[str]) -> str:
    """The words before send_sms_core leads them with "<church>: " (and, the
    first time, the STOP line): the post's title or first words, and its
    link. Room is kept for both, so the whole text is one part."""
    import sms_service
    name = (business.get("name") or "").strip()
    lead = (min(len(name), sms_service.MAX_BRAND_PREFIX) + 2) if name else 0
    link = f"{app}/my/news/{post['id']}" if app else "Open the church app to read it."
    words = _plain(post.get("title") or post.get("body") or "") or "News from the church"
    join = " " if app or words[-1] in ".!?" else ". "
    room = TEXT_MAX - lead - len(sms_service.OPTOUT_TAIL) - len(join) - len(link)
    if len(words) > room:
        words = words[:max(0, room - 3)].rstrip() + "..."
    return f"{words}{join}{link}"


async def _send_texts(business: Dict[str, Any], post: Dict[str, Any], people: List[Dict[str, Any]],
                      app: Optional[str]) -> Tuple[int, List[Dict[str, Any]]]:
    """(texts sent, the people whose text didn't go: they get the email)."""
    import httpx
    import sms_service
    body = text_for(business, post, app)
    sent, missed = 0, []
    async with httpx.AsyncClient() as client:
        for p in people:
            try:
                await sms_service.send_sms_core(client, business_id=str(business["id"]), to=p["phone"], message=body,
                                                contact_id=str(p["id"]), sent_by="system")
                sent += 1
            except Exception as e:  # noqa: BLE001 — one number never stops the rest
                logger.warning(f"[news-reach] one text failed: {type(e).__name__}")
                missed.append(p)
            await asyncio.sleep(TEXT_PACE)
    return sent, missed


def email_message(church: str, post: Dict[str, Any]) -> Tuple[str, str, str]:
    """(subject, message, preheader)."""
    title = " ".join(str(post.get("title") or "").split())
    body = str(post.get("body") or "").strip()
    subject = f"{church}: {title}" if title else f"Important news from {church}"
    message = "\n\n".join(x for x in (title, body) if x) or f"{church} shared something important."
    return subject[:150], message, (title or " ".join(body.split()))[:90]


async def _send_emails(business: Dict[str, Any], post: Dict[str, Any], people: List[Dict[str, Any]],
                       app: Optional[str]) -> int:
    import email_layout
    import email_sender
    church = (business.get("name") or "").strip() or "Your church"
    settings = business.get("settings") if isinstance(business.get("settings"), dict) else {}
    subject, message, preheader = email_message(church, post)
    why = (f"{church} marked this important. It came by email because the {church} app isn't set up on your "
           f"phone yet. Turn on alerts in the app and news comes there instead.")
    sent = 0
    for p in people:
        email = str(p.get("email") or "").strip()
        try:
            html = email_layout.render_html(
                message, business_name=church, brand=email_layout.brand_of(settings), sig=None,
                unsubscribe_url=email_sender._unsubscribe_url(email), preheader=preheader,
                cta=(("Read it in the app", f"{app}/my/news/{post['id']}") if app else None), disclaimer=why)
            await email_sender.send_via_resend(
                to_email=email, to_name=p.get("name") or None,
                from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
                from_name=church, subject=subject, body=html, reply_to=None, business_id=str(business["id"]),
                idempotency_key=f"church-news-reach-{post['id']}-{p['id']}")
            sent += 1
        except Exception as e:  # noqa: BLE001 — one address never stops the rest
            logger.warning(f"[news-reach] one email failed: {type(e).__name__}")
    return sent


# ─── once per post ───────────────────────────────────────────────────


def _claim(business_id: str, post_id: str, now: datetime) -> Optional[list]:
    """The rows claimed; [] when it was already; None on failure."""
    return sb_clients.sb_patch_as_service(
        f"/church_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(business_id)}&reached_at=is.null",
        {"reached_at": now.isoformat()})


def _record(business_id: str, post_id: str, reach: Optional[Dict[str, Any]], *, reached: bool = True) -> None:
    sb_clients.sb_patch_as_service(f"/church_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(business_id)}",
                                   {"reach": reach} if reached else {"reached_at": None, "reach": None})


def _let_go(business_id: str, post_id: str, now: datetime, why: str) -> Dict[str, Any]:
    """Claim it and say why it won't reach anyone, so the sweep stops looking."""
    if _claim(business_id, post_id, now):
        _record(business_id, post_id, {"why": why})
    return {"texts": 0, "emails": 0, "why": why}


def reach(business: Dict[str, Any], post: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Text and email the rest of the people an important post is for, once.
    {'texts', 'emails', 'why': ''|'not'|'later'|'old'|'off'|'full'|'busy'}.
    Runs off the request (a thread) or in the sweep, never in a running loop."""
    import academy_join
    import church_news as cn
    import group_email
    import member_push
    now = now or _now()
    none = {"texts": 0, "emails": 0}
    biz_id, post_id = str(business["id"]), str(post["id"])
    if not post.get("important") or post.get("reached_at") or cn.is_person_celebration(post):
        return {**none, "why": "not"}
    if post.get("status") != "posted" or post.get("removed_at"):
        return {**none, "why": "not"}
    if not cn.is_live(post, now):
        return {**none, "why": "later"}
    at = cn._ts(post.get("publish_at")) or cn._ts(post.get("created_at")) or now
    if at < now - timedelta(hours=WINDOW_HOURS):
        return _let_go(biz_id, post_id, now, "old")
    if not church_on(business):
        return _let_go(biz_id, post_id, now, "off")
    if member_push.quiet_hour(business, now):
        return {**none, "why": "later"}
    today = reached_today(business, now)
    if today is None:
        return {**none, "why": "busy"}
    if today >= REACH_DAILY:
        return _let_go(biz_id, post_id, now, "full")
    claimed = _claim(biz_id, post_id, now)
    if not claimed:
        return {**none, "why": "not" if claimed == [] else "busy"}
    who = plan(business, post, now)
    if who is None:
        _record(biz_id, post_id, None, reached=False)      # the sweep tries again
        return {**none, "why": "busy"}
    app = group_email.app_url(biz_id)
    texts, missed = asyncio.run(_send_texts(business, post, who["texts"], app)) if who["texts"] else (0, [])
    to_email = list(who["emails"])
    have = {str(p.get("email") or "").strip().lower() for p in to_email}
    for p in missed:                                     # a text that didn't go: the email instead
        email = str(p.get("email") or "").strip().lower()
        if academy_join.valid_email(email) and email not in have:
            to_email.append(p)
            have.add(email)
    emails = asyncio.run(_send_emails(business, post, to_email, app)) if to_email else 0
    _record(biz_id, post_id, {"texts": texts, "emails": emails, "phones": who["phones"], "at": now.isoformat()})
    logger.info(f"[news-reach] {biz_id[:8]} post {post_id[:8]}: {texts} texts, {emails} emails")
    return {"texts": texts, "emails": emails, "why": ""}


def reach_later(business: Dict[str, Any], post: Dict[str, Any]) -> None:
    """After an important post goes up now, off the request's path."""
    import member_push
    member_push._later(reach, business, post)


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every 15 minutes: important posts that haven't reached the rest yet
    (a scheduled one whose time came, one held through quiet hours, one a
    failed read put back)."""
    import church_news as cn
    now = now or _now()
    out = {"posts": 0, "texts": 0, "emails": 0}
    since = _q((now - timedelta(hours=WINDOW_HOURS + 12)).isoformat())
    due = sb_clients.sb_get_as_service(
        f"/church_posts?important=is.true&status=eq.posted&removed_at=is.null&reached_at=is.null"
        f"&or=(created_at.gte.{since},publish_at.gte.{since})"
        f"&select={cn.POST_SELECT},business_id,reached_at,removed_at&order=created_at.asc&limit=100")
    if not due:
        return out
    ids = sorted({str(p["business_id"]) for p in due})
    bizs = sb_clients.sb_get_as_service(f"/businesses?id=in.({','.join(_q(i) for i in ids)})"
                                        f"&select=id,name,settings,owner_id&limit=500")
    if not isinstance(bizs, list):
        return out
    by_id = {str(b["id"]): b for b in bizs}
    for p in due:
        biz = by_id.get(str(p["business_id"]))
        if not biz:
            continue
        try:
            got = reach(biz, p, now)
        except Exception:  # noqa: BLE001 — one church never stops the rest
            logger.warning("news reach: one post failed", exc_info=True)
            continue
        if not got["why"]:
            out["posts"] += 1
            out["texts"] += got["texts"]
            out["emails"] += got["emails"]
    return out


# ─── a member's own yes ──────────────────────────────────────────────


def record_yes(business_id: str, me: Dict[str, Any], ip: str = "", user_agent: str = "") -> bool:
    """A member ticked "Text me important news" in the app: their yes to the
    church's texts, kept like every other (sms_consents, source member_app)."""
    from sms_service import normalize_phone
    phone = normalize_phone(me.get("phone"))
    if not phone:
        return False
    rows = sb_clients.sb_post_as_service("/sms_consents", {
        "phone": phone, "name": (me.get("name") or "")[:120], "source": "member_app", "business_id": str(business_id),
        "consented_at": _now().isoformat(), "ip": (ip or "")[:64], "user_agent": (user_agent or "")[:300]},
        prefer="return=representation")
    return bool(rows)
