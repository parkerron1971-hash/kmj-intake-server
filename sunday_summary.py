# sunday_summary.py — the one Sunday hub's summary (mission M-7): one
# Sunday, read once, for the This Sunday page's six steps.
#
#   GET /worship/services/{service_id}/sunday?business_id=
#
# Readers only (the wall in worship_team.roles_of: a Sunday role, duty or
# part); 404 while SUNDAY_HUB is off. Nothing is written. Each part is read
# on its own: one that can't be read just now comes back null and is named in
# `unavailable`, and the rest still answers. The offering is in the answer
# only for a login the giving gate already lets see it (giving_services._gate,
# what Giving > by service keeps): for anyone else the key is left out, never
# set to null. Shapes: kai/reviews/M-7-api-contract.md section 2.
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
import sunday_hub as hub
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/worship", tags=["worship"])


def _q(v: Any) -> str:
    from urllib.parse import quote
    return quote(str(v), safe="")


def _need(path: str, what: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise HTTPException(503, f"{what} couldn't be read. Try again.")
    return rows


def _at(raw: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")) if raw else None
    except ValueError:
        return None


# ─── each step's part ─────────────────────────────────────────────────


def _service(row: Dict[str, Any], biz: str) -> Dict[str, Any]:
    import worship_show_router as wsr
    out = wsr._service_out(row)
    start = _at(row.get("starts_at"))
    ends = (start + timedelta(minutes=float(out["minutes"] or 0))).isoformat() if start else None
    return {"id": out["id"], "title": out["title"], "starts_at": out["starts_at"], "ends_at": ends,
            "minutes": out["minutes"], "item_count": out["item_count"], "live_ok": hub.live_ok(biz, str(row["id"]))}


def _plan(biz: str, row: Dict[str, Any], teams: List[Dict[str, Any]]) -> Dict[str, Any]:
    items = row.get("items") or []
    texts = [i for i in items if i.get("kind") == "text"]
    sermon = max(texts, key=lambda i: float(i.get("minutes") or 0)) if texts else None
    passage = next((i for i in items if i.get("kind") == "scripture" and i.get("ref")), None)
    notes = _need(f"/serve_notes?business_id=eq.{_q(biz)}&service_id=eq.{_q(row['id'])}&select=item_id,team,note"
                  "&limit=2000", "The team notes")
    written = [n for n in notes if (n.get("note") or "").strip()]
    shown = sum(1 for i in items if i.get("kind") != "section")
    return {
        "items": shown, "minutes": round(sum(float(i.get("minutes") or 0) for i in items), 1),
        "sermon": ({"title": sermon.get("title") or "", "ref": (passage or {}).get("ref") or "",
                    "who": sermon.get("who") or "", "points": len(sermon.get("slides") or [])} if sermon else None),
        "notes": {"written": len(written),
                  "teams": [{"group_id": t["group_id"], "name": t["name"],
                             "written": sum(1 for n in written if str(n.get("team")) == t["group_id"]),
                             "items": shown} for t in teams]},
    }


def _songs(biz: str, row: Dict[str, Any], areas: Dict[str, Optional[str]]) -> Dict[str, Any]:
    import worship_lyrics as wl
    import worship_show_router as wsr
    items = [i for i in row.get("items") or [] if i.get("kind") == "song"]
    songs = wsr._songs_for(biz, items)
    out = []
    for i in items:
        song = songs.get(i.get("song_id") or "") or {}
        out.append({"item_id": i.get("id"), "song_id": i.get("song_id"),
                    "title": song.get("title") or ("Pick a song" if not i.get("song_id") else "A song"),
                    "key": song.get("song_key") or "", "words_ready": bool(song) and wl.has_words(song),
                    "team": hub.item_team(i, areas)})
    return {"count": len(out), "ready": sum(1 for s in out if s["words_ready"]), "items": out}


def _screens(biz: str, row: Dict[str, Any]) -> Dict[str, Any]:
    import worship_announce as wa
    import worship_announce_router as war
    items = row.get("items") or []
    day = war.day_of_service(biz, row.get("starts_at"))
    showing = wa.showing(war._rows(biz), day, "room")
    missing = [{"id": str(r["id"]), "title": r.get("title") or "An announcement"} for r in showing
               if not r.get("image_url") and not r.get("design")]
    missing += [{"id": str(i.get("id")), "title": i.get("title") or "An announcement"} for i in items
                if i.get("kind") == "announcement" and not i.get("from_board") and not i.get("image_url")]
    screens = _need(f"/worship_screens?business_id=eq.{_q(biz)}&archived_at=is.null&select=id&limit=100", "The screens")
    count = next((i for i in items if i.get("kind") == "countdown"), None)
    return {"announcements_showing": len(showing), "missing_pictures": missing, "screens": len(screens),
            "loop": any(i.get("kind") == "loop" for i in items),
            "countdown_minutes": (count or {}).get("minutes") if count else None}


_STATUS = {"yes": "yes", "asked": "asked", "offered": "asked"}


def _serving(biz: str, row: Dict[str, Any], leads: List[str]) -> Dict[str, Any]:
    import serve_dates as sd
    import sunday_planning as sp
    teams, _ = sp._teams(biz)
    opened = hub.open_to_ops(biz)
    rows = _need(f"/serve_assignments?business_id=eq.{_q(biz)}&service_id=eq.{_q(row['id'])}"
                 "&select=position_id,slot,contact_id,status&limit=2000", "Who's serving")
    who = sp._people(biz, [r.get("contact_id") for r in rows])
    out = []
    for t in teams:
        if not sp.serves(row, t):
            continue
        spots, filled, asked, open_ = [], 0, 0, 0
        for p in t["places"]:
            for slot in range(1, int(sd.needed(row, p) or 0) + 1):
                hit = next((r for r in rows if str(r["position_id"]) == str(p["id"]) and int(r.get("slot") or 1) == slot
                            and r.get("status") in _STATUS), None)
                status = _STATUS[hit["status"]] if hit else "open"
                person = (who.get(str(hit.get("contact_id"))) or {}).get("name") if hit and hit.get("contact_id") else None
                spots.append({"position_id": str(p["id"]), "place": p["name"], "person": person, "status": status})
                filled += status == "yes"
                asked += status == "asked"
                open_ += status == "open"
        out.append({"group_id": t["group_id"], "name": t["name"], "owner": t.get("owner"),
                    "open_to_ops": t["group_id"] in opened, "filled": filled, "open": open_, "asked": asked,
                    "mine": t["group_id"] in leads, "spots": spots})
    return {"filled": sum(t["filled"] for t in out), "open": sum(t["open"] for t in out),
            "asked": sum(t["asked"] for t in out), "teams": out}


def _stream(biz: str) -> Optional[Dict[str, Any]]:
    import stream_relay_router as srr
    if not srr.is_ready():
        return None
    got = srr.stream_row(biz)
    if got is None:
        raise HTTPException(503, "The stream couldn't be read. Try again.")
    if not got:
        return None
    return {"ready": bool(got.get("key_hash")),
            "destinations": [d for d in srr.DESTINATIONS if got.get(f"{d}_on")]}


def _day_of(biz: str, row: Dict[str, Any]) -> Optional[date]:
    import worship_announce_router as war
    return war.day_of_service(biz, row.get("starts_at")) if row.get("starts_at") else None


def _count_recorded(church: Dict[str, Any], day: Optional[date], now: datetime) -> Optional[bool]:
    """Whether that service's count is in: None before its day (or when it
    can't be said), never "missed" on a read that failed."""
    import business_marketing
    import church_work_checks as cw
    if not day:
        return None
    tz = business_marketing.business_tz(church)
    if day > now.astimezone(tz).date():
        return None
    try:
        return bool(cw.sunday_counted(cw.Ctx(church, now, tz), day, now))
    except Exception:  # noqa: BLE001 — Unread or a blip: can't say
        return None


def _sermon_draft(biz: str, day: Optional[date]) -> Optional[Dict[str, Any]]:
    """The unpublished sermon the stream saved for that day, if any."""
    import stream_relay_router as srr
    if not day:
        return None
    for r in _need(f"/sermons?business_id=eq.{_q(biz)}&published=eq.false&preached_on=eq.{day.isoformat()}"
                   "&select=id,title,video_url&order=created_at.desc&limit=10", "The sermon"):
        if srr.watch_session(str(r.get("video_url") or "")):
            return {"id": str(r["id"]), "title": r.get("title") or ""}
    return None


def _offering(biz: str, day: Optional[date]) -> Optional[Dict[str, Any]]:
    """That day's offering by service (giving_counts and their gifts)."""
    import giving_services as gs
    if not day:
        return None
    counts = _need(f"/giving_counts?business_id=eq.{_q(biz)}&service_date=eq.{day.isoformat()}&select=id&limit=20",
                   "The offering")
    if not counts:
        return None
    total = gs.totals(gs._gifts_of(biz, [c["id"] for c in counts]))
    return {"total_cents": total["all"], "gifts": total["gifts"]}


# ─── the route ────────────────────────────────────────────────────────


@router.get("/services/{service_id}/sunday")
def sunday_summary(service_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    import worship_show_router as wsr
    from worship_team import roles_of
    if not hub.open_to(user):
        raise HTTPException(404, "Not Found")
    wsr._gate(user)
    biz = wsr._uuid(business_id)
    roles_of(biz, user, part=None)                      # a stranger 404s; the wall 403s
    st = hub.standing(biz, user)
    row = wsr._service(biz, wsr._uuid(service_id, "service"))
    church = (sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz)}&select=id,type,owner_id,settings&limit=1")
              or [{"id": biz}])[0]
    now = datetime.now(timezone.utc)
    unavailable: List[str] = []

    def part(name: str, read: Callable[[], Any]) -> Any:
        try:
            return read()
        except HTTPException as e:
            if e.status_code < 500:
                raise
        except Exception as e:  # noqa: BLE001 — one step's blip never blanks the page
            logger.warning("[sunday-summary] %s unreadable for %s: %s", name, biz, e)
        unavailable.append(name)
        return None

    teams = part("teams", lambda: hub.sunday_teams(biz)) or []
    areas = part("areas", lambda: hub.team_areas(biz, teams)) or {}
    day = _day_of(biz, row)
    after: Dict[str, Any] = {
        "count_recorded": _count_recorded(church, day, now),
        "sermon_draft": part("after.sermon_draft", lambda: _sermon_draft(biz, day)),
    }
    # The giving gate decides for everyone, the owner and the admins too (a
    # giving keeper, and giving by service's own switch).
    if hub.sees_giving(biz, user) is True:
        after["offering"] = part("after.offering", lambda: _offering(biz, day))
    out = {
        "service": _service(row, biz),
        "plan": part("plan", lambda: _plan(biz, row, teams)),
        "songs": part("songs", lambda: _songs(biz, row, areas)),
        "screens": part("screens", lambda: _screens(biz, row)),
        "serving": part("serving", lambda: _serving(biz, row, [t["group_id"] for t in st["leads"]])),
        "live": {"stream": part("live.stream", lambda: _stream(biz))},
        "after": after,
    }
    out["unavailable"] = unavailable
    return out
