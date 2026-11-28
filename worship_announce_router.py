# worship_announce_router.py — the announcements board over HTTP (ChurchSavvy
# round 5, canvas UZu4VsoY9KemkUGorz234j boards 18-21).
#
# Signed in, behind the same switch as the rest of Sunday's screens
# (worship_router.mode()). Anyone on the church's team reads; the plan's
# part (planner, worship leader, admin) makes and changes them.
#   GET     /worship/announcements                 the board, each with its tab on `day`
#   POST    /worship/announcements                 a new one
#   PUT     /worship/announcements/{id}            change one
#   POST    /worship/announcements/{id}/decide     a ministry's request: put it on, or not (its leader hears)
#   DELETE  /worship/announcements/{id}            take it off the board (archived)
#
# board_for() hands worship_show_router the board for a service's day, so the
# announcement spot and the welcome loop fill themselves.
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
import worship_announce as wa
from auth_supabase import AuthedUser, require_user
from worship_show_router import _q, _read, _seat, _staff, _uuid
from worship_team import can

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/worship", tags=["worship"])

_FIELDS = ("id,title,when_text,where_text,body,image_url,design,event_on,qr,show_from,show_until,shows,"
           "status,source,source_ref,sent_by,sort,archived_at,created_at,updated_at")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def church_zone(biz: str) -> ZoneInfo:
    """The church's clock (business_marketing.business_tz), or UTC when it can't be read."""
    try:
        import business_marketing
        rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz)}&select=id,owner_id,settings&limit=1") or []
        if rows:
            return business_marketing.business_tz(rows[0])
    except Exception:  # noqa: BLE001 — a day off at midnight beats no board at all
        logger.warning("announcements: no time zone for %s", biz, exc_info=True)
    return ZoneInfo("UTC")


def church_today(biz: str) -> date:
    return datetime.now(church_zone(biz)).date()


def day_of_service(biz: str, starts_at: Optional[str]) -> date:
    """The service's own day on the church's clock (an evening service isn't tomorrow in UTC)."""
    if starts_at:
        try:
            return datetime.fromisoformat(starts_at.replace("Z", "+00:00")).astimezone(church_zone(biz)).date()
        except ValueError:
            pass
    return church_today(biz)


def _rows(biz: str) -> List[Dict[str, Any]]:
    return _read(f"/worship_announcements?business_id=eq.{_q(biz)}&archived_at=is.null&select={_FIELDS}"
                 f"&order=event_on.asc.nullslast,sort.asc,created_at.asc&limit={wa.MAX_PER_CHURCH}", "The announcements")


def board_for(biz: str, starts_at: Optional[str], where: str = "room") -> List[Dict[str, Any]]:
    """What shows on the service's day on one kind of screen, nearest first, as slides."""
    day = day_of_service(biz, starts_at)
    rows = wa.showing(_rows(biz), day, where)
    return [wa.slide(r, day, rows) for r in rows]


def _one(biz: str, aid: str) -> Dict[str, Any]:
    _uuid(aid, "announcement")
    rows = _read(f"/worship_announcements?id=eq.{_q(aid)}&business_id=eq.{_q(biz)}&archived_at=is.null&select={_FIELDS}",
                 "The announcement")
    if not rows:
        raise HTTPException(404, "announcement not found")
    return rows[0]


def _day(raw: Optional[str], biz: str) -> date:
    if raw:
        try:
            d = wa.day_of(raw, "The day")
            if d:
                return d
        except ValueError as e:
            raise HTTPException(400, str(e))
    return church_today(biz)


# ─── announcements once, two places (the one Sunday hub, M-7) ────────
# With SUNDAY_HUB on, an announcement made or changed here can also be posted
# to News ("Also post to News"), and a News post can also go on the screens
# (church_news.create's also_screens). Each side keeps its own permission:
# posting to News is News's own rule (church_news.create, an editing seat),
# the screens are the Plan part's. A login missing the other side's
# permission gets its own side saved and a plain refusal for the other.
# Editing or taking out one side never changes the other by itself.
NEWS_REFUSED = "You can't post to News here."
NEWS_UNAVAILABLE = "It didn't post to News just now. Try again from News."


def _hub_on(user: AuthedUser) -> bool:
    import sunday_hub
    return sunday_hub.open_to(user)


def _news_of(biz: str, ann_id: str) -> Optional[str]:
    """The News post this announcement was posted with, if any."""
    rows = sb_clients.sb_get_as_service(f"/church_posts?business_id=eq.{_q(biz)}&screen_announcement_id=eq.{_q(ann_id)}"
                                        "&select=id&limit=1")
    return str(rows[0]["id"]) if isinstance(rows, list) and rows else None


def also_news(biz: str, user: AuthedUser, row: Dict[str, Any]) -> Dict[str, Any]:
    """Post this announcement to News too: {post_id}, {refused} or
    {unavailable}. Never fails the announcement's own answer: it is saved
    already, so whatever News says comes back as words, never an error."""
    try:
        return _also_news(biz, user, row)
    except HTTPException as e:
        if e.status_code < 500:
            return {"refused": e.detail if isinstance(e.detail, str) and e.detail else NEWS_REFUSED}
        logger.warning("announcements: News didn't take %s: %s", row.get("id"), e.detail)
    except Exception:  # noqa: BLE001 — the announcement is saved; News is the second side
        logger.warning("announcements: News didn't take %s", row.get("id"), exc_info=True)
    return {"unavailable": NEWS_UNAVAILABLE}


def _also_news(biz: str, user: AuthedUser, row: Dict[str, Any]) -> Dict[str, Any]:
    """By News's own create route and its rules. Posted once: an
    announcement already on News (or one that came from News) answers with
    that post."""
    import church_news
    if row.get("source") == "news" and row.get("source_ref"):
        return {"post_id": str(row["source_ref"])}
    have = _news_of(biz, str(row["id"]))
    if have:
        return {"post_id": have}
    try:
        church_news._need(biz, user, "member")
    except HTTPException:
        return {"refused": NEWS_REFUSED}
    line = " · ".join(x for x in (row.get("when_text"), row.get("where_text")) if x)
    text = "\n".join(x for x in (line, row.get("body")) if x)
    made = church_news.create(church_news.PostIn(business_id=biz, kind="announcement",
                                                 title=(row.get("title") or "")[:church_news.TITLE_MAX],
                                                 body=text[:church_news.BODY_MAX]), user)
    pid = str(made["post_id"])
    linked = sb_clients.sb_patch_as_service(f"/church_posts?id=eq.{_q(pid)}&business_id=eq.{_q(biz)}&select=id",
                                            {"screen_announcement_id": str(row["id"])})
    if not isinstance(linked, list) or not linked:
        logger.warning("announcements: post %s isn't linked to its announcement %s", pid, row["id"])
    return {"post_id": pid}


def _with_news_links(biz: str, user: AuthedUser, out: List[Dict[str, Any]], board: List[Dict[str, Any]]) -> None:
    """With the hub on, each announcement says the News post it's paired with
    (`board`: the rows the list was made from, read once)."""
    if not _hub_on(user) or not out:
        return
    rows = {str(r["id"]): r for r in board}
    ids = [str(a["id"]) for a in out]
    posts = sb_clients.sb_get_as_service(f"/church_posts?business_id=eq.{_q(biz)}&screen_announcement_id=in.({','.join(_q(i) for i in ids)})"
                                         "&select=id,screen_announcement_id&limit=500") or []
    by_ann = {str(p["screen_announcement_id"]): str(p["id"]) for p in posts if isinstance(p, dict)}
    for a in out:
        r = rows.get(str(a["id"])) or {}
        a["news_post_id"] = (str(r["source_ref"]) if r.get("source") == "news" and r.get("source_ref")
                             else by_ann.get(str(a["id"])))


@router.get("/announcements")
def list_announcements(business_id: str, day: Optional[str] = None, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    roles = _seat(biz, user)
    today = _day(day, biz)
    board = _rows(biz)
    out = [wa.as_out(r, today) for r in board]
    cutoff = wa.past_cutoff(today)
    out = [a for a in out if a["tab"] != "declined" and not (a["tab"] == "past" and (a["show_until"] or "") < cutoff)]
    _with_news_links(biz, user, out, board)
    counts = {t: sum(1 for a in out if a["tab"] == t) for t in wa.TABS}
    # can_write: the plan's part (planner, worship leader, admin) makes and changes them.
    return {"announcements": out, "counts": counts, "day": today.isoformat(), "can_write": can(roles, "plan")}


@router.post("/announcements")
def create_announcement(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.get("business_id"))
    _staff(biz, user, "plan")
    try:
        row = wa.clean(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not row.get("show_until"):
        row["show_until"] = wa.until_default(row.get("event_on"))
        if row["show_until"] and row.get("show_from") and row["show_from"] > row["show_until"]:
            row["show_until"] = row["show_from"]
    have = _read(f"/worship_announcements?business_id=eq.{_q(biz)}&archived_at=is.null&select=id&limit={wa.MAX_PER_CHURCH}",
                 "The announcements")
    if len(have) >= wa.MAX_PER_CHURCH:
        raise HTTPException(400, f"A church keeps up to {wa.MAX_PER_CHURCH} announcements. Take a few old ones off first.")
    now = _now()
    saved = sb_clients.sb_post_as_service(f"/worship_announcements?select={_FIELDS}", {
        "business_id": biz, **row, "status": "on", "source": "typed", "created_at": now, "updated_at": now,
    }, prefer="return=representation")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "The announcement wasn't saved. Try again.")
    out = {"announcement": wa.as_out(saved[0], church_today(biz))}
    if body.get("also_news") is True and _hub_on(user):
        out["news"] = also_news(biz, user, saved[0])
    return out


@router.put("/announcements/{announcement_id}")
def save_announcement(announcement_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.get("business_id"))
    _staff(biz, user, "plan")
    cur = _one(biz, announcement_id)
    try:
        change = wa.clean({k: v for k, v in body.items() if k != "business_id"}, partial=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    f = change.get("show_from", cur.get("show_from"))
    u = change.get("show_until", cur.get("show_until"))
    if f and u and f > u:
        raise HTTPException(400, "It can't stop showing before it starts")
    change["updated_at"] = _now()
    saved = sb_clients.sb_patch_as_service(
        f"/worship_announcements?id=eq.{_q(cur['id'])}&business_id=eq.{_q(biz)}&select={_FIELDS}", change)
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "The change wasn't saved. Try again.")
    out = {"announcement": wa.as_out(saved[0], church_today(biz))}
    if body.get("also_news") is True and _hub_on(user):
        out["news"] = also_news(biz, user, saved[0])
    return out


@router.post("/announcements/{announcement_id}/decide")
def decide_announcement(announcement_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """A ministry's request: on the board (`on`), or not this time (`declined`).
    Its leader hears by email, with the office's note when there is one."""
    biz = _uuid(body.get("business_id"))
    _staff(biz, user, "plan")
    decision = body.get("decision")
    if decision not in ("on", "declined"):
        raise HTTPException(400, "Put it on, or not this time")
    note = body.get("note") or ""
    if not isinstance(note, str) or len(note.strip()) > 300:
        raise HTTPException(400, "A note is at most 300 letters")
    cur = _one(biz, announcement_id)
    saved = sb_clients.sb_patch_as_service(
        f"/worship_announcements?id=eq.{_q(cur['id'])}&business_id=eq.{_q(biz)}&select={_FIELDS}", {"status": decision, "updated_at": _now()})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That wasn't saved. Try again.")
    told = False
    if cur.get("status") == "waiting" and cur.get("source") == "ministry":
        import worship_ministries
        told = worship_ministries.tell_leader(biz, saved[0], decision, " ".join(note.split()))
    return {"announcement": wa.as_out(saved[0], church_today(biz)), "told": told}


@router.delete("/announcements/{announcement_id}")
def remove_announcement(announcement_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _staff(biz, user, "plan")
    cur = _one(biz, announcement_id)
    saved = sb_clients.sb_patch_as_service(
        f"/worship_announcements?id=eq.{_q(cur['id'])}&business_id=eq.{_q(biz)}&select=id", {"archived_at": _now(), "updated_at": _now()})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "It wasn't taken off. Try again.")
    return {"ok": True}
