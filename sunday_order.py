# sunday_order.py — ChurchSavvy Planning, step 4: one order of service for
# every team (design canvas Ct88v7pxpq5a4PGYX3MuQQ, board 3 "Order of
# service"). The items are ChurchSavvy's plan (worship_services.items, the
# one plan the slides read); Planning adds when each starts and a note for
# each team (serve_notes), kept beside the plan so a save in ChurchSavvy
# never overwrites a team's note.
#
#   GET /planning/order?business_id=&service_id=   one service's order (the next one without an id)
#   PUT /planning/order/notes                      {business_id, service_id, item_id, team, note}
#                                                  team is a Sunday team's group id or "all";
#                                                  an empty note takes it off
#
# Everyone on the team and every seat reads; a note is written by whoever
# schedules (worship_team CAN["serve"]). Behind the same SUNDAY_PLANNING
# switch as the rest of Planning.
#
# When each item starts: from the service's start, each item's minutes
# after the one before. Items under a section called "Before" count back
# from the start instead (the call time, prayer with the team, the welcome
# loop), so they end as the service begins; items under "After" (the
# goodbye loop) follow the end without moving it.
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
import sunday_planning as sp
from auth_supabase import AuthedUser, require_user
from sunday_planning import _gate, _ids, _q, _read, _staff, _uuid
from worship_team import can

router = APIRouter(prefix="/planning", tags=["planning"])

NOTE_MAX = 300
UPCOMING = 8
_ITEM = re.compile(r"^[a-z0-9-]{1,24}$")
BEFORE = ("before", "before the service", "before service")
AFTER = ("after", "after the service", "after service")


def _service(biz: str, sid: Optional[str], zone) -> Dict[str, Any]:
    if sid:
        rows = _read(f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&archived_at=is.null"
                     f"&select=id,title,starts_at,items,is_template&limit=1")
    else:
        now = sp._now() - timedelta(hours=3)
        rows = _read(f"/worship_services?business_id=eq.{_q(biz)}&archived_at=is.null&is_template=eq.false"
                     f"&starts_at=gte.{_q(now.isoformat())}&select=id,title,starts_at,items,is_template"
                     f"&order=starts_at.asc&limit=1")
    if not rows or rows[0].get("is_template"):
        raise HTTPException(404, "That service isn't here")
    return rows[0]


def _upcoming(biz: str, zone) -> List[Dict[str, Any]]:
    now = sp._now() - timedelta(hours=3)
    rows = _read(f"/worship_services?business_id=eq.{_q(biz)}&archived_at=is.null&is_template=eq.false"
                 f"&starts_at=gte.{_q(now.isoformat())}&select=id,title,starts_at&order=starts_at.asc&limit={UPCOMING}")
    out = []
    for r in rows:
        at = _at(r.get("starts_at"), zone)
        if at:
            out.append({"id": str(r["id"]), "title": r.get("title") or "Sunday service",
                        "day": at.date().isoformat(), "time": at.strftime("%H:%M")})
    return out


def _at(v: Any, zone) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(zone)
    except (TypeError, ValueError):
        return None


def _songs(biz: str, items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    ids = [i.get("song_id") for i in items if i.get("kind") == "song" and i.get("song_id")]
    if not ids:
        return {}
    return {str(s["id"]): s for s in _read(f"/worship_songs?business_id=eq.{_q(biz)}&id=in.({_ids(ids)})"
                                            f"&select=id,title,song_key,sections,arrangements")}


def _parts(item: Dict[str, Any], song: Dict[str, Any]) -> List[str]:
    """The band's order: the parts' names in the arrangement the plan picked
    ("V1 C V2 C B C"). Labels only; the words never leave the library."""
    arrs = song.get("arrangements") or []
    arr = next((a for a in arrs if a.get("id") == item.get("arrangement_id")), None) or (arrs[0] if arrs else None)
    secs = [s for s in song.get("sections") or [] if isinstance(s, dict)]
    order = arr.get("order") if arr else [s.get("id") for s in secs]
    label = {s.get("id"): (s.get("label") or s.get("id")) for s in secs}
    return [str(label.get(x, x))[:20] for x in (order or [])][:40]


def _name(item: Dict[str, Any], songs: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """What the order calls an item, and the line under it. Never a song's
    words: the title and key from the library, nothing more."""
    kind = item.get("kind")
    if kind == "song":
        s = songs.get(str(item.get("song_id") or ""))
        if not s:
            return {"title": "A song to pick", "sub": "Song"}
        return {"title": s.get("title") or "A song", "sub": "Song" + (f" · key of {s['song_key']}" if s.get("song_key") else ""),
                "key": s.get("song_key") or "", "parts": _parts(item, s)}
    if kind == "scripture":
        ref = item.get("ref") or ""
        return {"title": ref or "A passage to pick", "sub": f"Scripture · {item.get('translation') or ''}".rstrip(" ·")}
    if kind == "announcement":
        return {"title": item.get("title") or "Announcement", "sub": item.get("when") or "Announcement"}
    if kind == "media":
        return {"title": item.get("title") or ("Video" if item.get("media_kind") == "video" else "Picture"),
                "sub": "Video" if item.get("media_kind") == "video" else "Picture"}
    if kind == "loop":
        return {"title": item.get("title") or "Welcome loop", "sub": "Loop"}
    if kind == "countdown":
        return {"title": item.get("title") or "Countdown", "sub": "Countdown"}
    return {"title": item.get("title") or "Words on screen", "sub": "Words"}


def _hm(at: datetime) -> str:
    return at.strftime("%H:%M")


def order_of(biz: str, svc: Dict[str, Any], zone) -> Dict[str, Any]:
    items = [i for i in (svc.get("items") or []) if isinstance(i, dict) and _ITEM.match(str(i.get("id") or ""))]
    start = _at(svc.get("starts_at"), zone)
    songs = _songs(biz, items)
    teams, _ = sp._teams(biz)
    team_ids = {t["group_id"] for t in teams}
    notes: Dict[str, Dict[str, str]] = {}
    for n in _read(f"/serve_notes?business_id=eq.{_q(biz)}&service_id=eq.{_q(svc['id'])}&select=item_id,team,note"):
        if n["team"] == "all" or n["team"] in team_ids:
            notes.setdefault(str(n["item_id"]), {})[n["team"]] = n["note"]
    # Before items count back from the start; the rest forward.
    before, section = [], None
    for i in items:
        if i.get("kind") == "section":
            section = str(i.get("title") or "").strip().lower()
        elif section in BEFORE:
            before.append(i["id"])
    mins = lambda i: float(i.get("minutes") or 0)
    back = sum(mins(i) for i in items if i["id"] in before)
    at_before = start - timedelta(minutes=back) if start else None
    at_after = start
    ends = None
    rows = []
    for i in items:
        if i.get("kind") == "section":
            first_next = next((x for x in items[items.index(i) + 1:] if x.get("kind") != "section"), None)
            is_before = str(i.get("title") or "").strip().lower() in BEFORE
            if str(i.get("title") or "").strip().lower() in AFTER and ends is None:
                ends = at_after
            when = at_before if is_before else at_after
            rows.append({"id": i["id"], "section": True, "title": i.get("title") or "Section",
                         "time": _hm(when) if when and first_next else None})
            continue
        is_before = i["id"] in before
        when = at_before if is_before else at_after
        named = _name(i, songs)
        rows.append({"id": i["id"], "section": False, "kind": i.get("kind"), **named,
                     "part": "before" if is_before else ("after" if ends is not None else "service"),
                     "minutes": i.get("minutes"), "who": i.get("who") or "",
                     "time": _hm(when) if when else None, "notes": notes.get(i["id"], {})})
        if when:
            if is_before:
                at_before = when + timedelta(minutes=mins(i))
            else:
                at_after = when + timedelta(minutes=mins(i))
    return {
        "service": {"id": str(svc["id"]), "title": svc.get("title") or "Sunday service",
                    "day": start.date().isoformat() if start else None, "time": _hm(start) if start else None},
        "starts": _hm(start) if start else None,
        "ends": _hm(ends or at_after) if (ends or at_after) else None,
        "items": rows,
        "teams": [{"group_id": t["group_id"], "name": t["name"]} for t in teams],
    }


@router.get("/order")
def get_order(business_id: str, service_id: Optional[str] = None, user: AuthedUser = Depends(require_user)):
    _gate(user)
    biz = _uuid(business_id)
    roles = _staff(biz, user, write=False)
    zone = sp._zone(biz)
    svc = _service(biz, _uuid(service_id, "service") if service_id else None, zone)
    return {**order_of(biz, svc, zone), "upcoming": _upcoming(biz, zone), "can_write": can(roles, "serve")}


@router.put("/order/notes")
def put_note(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user, write=True)
    sid = _uuid(body.get("service_id"), "service")
    item_id = str(body.get("item_id") or "")
    team = str(body.get("team") or "")
    note = body.get("note")
    if not _ITEM.match(item_id):
        raise HTTPException(400, "Which item is the note for?")
    if note is None or not isinstance(note, str):
        raise HTTPException(400, "The note is text")
    note = " ".join(note.split())
    if len(note) > NOTE_MAX:
        raise HTTPException(400, f"A note is at most {NOTE_MAX} characters")
    svc = _service(biz, sid, sp._zone(biz))
    if not any(isinstance(i, dict) and i.get("id") == item_id and i.get("kind") != "section" for i in svc.get("items") or []):
        raise HTTPException(404, "That item isn't in this service anymore")
    if team != "all":
        team = _uuid(team, "team")
        if not _read(f"/serve_teams?business_id=eq.{_q(biz)}&group_id=eq.{_q(team)}&select=group_id&limit=1"):
            raise HTTPException(404, "That Sunday team isn't here")
    key = f"business_id=eq.{_q(biz)}&service_id=eq.{_q(sid)}&item_id=eq.{_q(item_id)}&team=eq.{_q(team)}"
    if not note:
        if not sb_clients.sb_delete_as_service(f"/serve_notes?{key}"):
            raise HTTPException(503, "That didn't save. Try again.")
        return {"ok": True, "note": None}
    saved = sb_clients.sb_post_as_service(
        "/serve_notes?on_conflict=service_id,item_id,team",
        {"business_id": biz, "service_id": sid, "item_id": item_id, "team": team, "note": note,
         "updated_by": sp._asker(biz, user), "updated_at": sp._now().isoformat()},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"ok": True, "note": note}


# ??? the booth's Today (board 11) ????????????????????????????????????

SERMON_MIN = 15          # the plan's clock names the longest item this long or longer


@router.get("/today")
def today(business_id: str, service_id: Optional[str] = None, user: AuthedUser = Depends(require_user)):
    """Who's on that Sunday, team by team and place by place: here (they
    tapped I'm here, and when), said yes and not here yet, asked and
    waiting, or open; and the plan's clock: when it starts, its longest
    item (the sermon), when it ends. For the booth (ChurchSavvy's Today)."""
    _gate(user)
    biz = _uuid(business_id)
    _staff(biz, user, write=False)
    zone = sp._zone(biz)
    svc = _service(biz, _uuid(service_id, "service") if service_id else None, zone)
    order = order_of(biz, svc, zone)
    teams, _ = sp._teams(biz)
    rows = _read(f"/serve_assignments?business_id=eq.{_q(biz)}&service_id=eq.{_q(svc['id'])}"
                 f"&select=position_id,slot,contact_id,status,here_at")
    who = sp._people(biz, [r.get("contact_id") for r in rows])
    held = {(str(r["position_id"]), int(r.get("slot") or 1)): r for r in rows}
    out = []
    for t in teams:
        spots = []
        for p in t["places"]:
            for slot in range(1, int(p.get("needed") or 1) + 1):
                r = held.get((p["id"], slot))
                person = (who.get(str(r["contact_id"])) or {}) if r and r.get("contact_id") else {}
                here = _at(r.get("here_at"), zone) if r else None
                state = ("open" if not r or r["status"] in ("offered", "no") or not person
                         else "here" if r["status"] == "yes" and here
                         else "yes" if r["status"] == "yes" else "asked")
                spots.append({"place": p["name"], "slot": slot, "state": state,
                              "name": person.get("name") if state != "open" else None,
                              "here": _hm(here) if state == "here" else None})
        out.append({"group_id": t["group_id"], "name": t["name"], "call_time": sp._hhmm(t.get("call_time")), "spots": spots})
    service = [i for i in order["items"] if not i["section"] and i.get("part") == "service"]
    long = max(service, key=lambda i: float(i.get("minutes") or 0), default=None)
    return {
        "service": order["service"], "teams": out,
        "clock": {"starts": order["starts"], "ends": order["ends"],
                  "longest": ({"title": long["title"], "time": long["time"], "minutes": long["minutes"]}
                              if long and float(long.get("minutes") or 0) >= SERMON_MIN else None)},
    }
