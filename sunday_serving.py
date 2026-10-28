# sunday_serving.py — ChurchSavvy Planning, the member's side: what a member
# is asked to serve, their coming Sundays, a sub when they can't, away dates
# and how often they'd like to serve (design canvas Ct88v7pxpq5a4PGYX3MuQQ,
# boards 7 "The ask" and 8 "My serving"). The pages are
# member_portal_serving.py; the office is sunday_planning.py.
#
# A member only ever reads and changes their own: an ask made to them, a
# Sunday they said yes to, a place offered to their team that they're trained
# for, their own away days and their own wish for how often. Nothing here
# reaches a business_users seat.
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import HTTPException

import sb_clients
import sunday_planning as sp
from sunday_planning import _ids, _q, _read

logger = logging.getLogger(__name__)

AHEAD_DAYS = 90
MAX_AWAY = 20
OFTEN = ("one", "two", "every")
# The reminders before a Sunday (sunday_serving_alerts) and "I'm here" on
# the day (the pack): a place that moves to someone new starts fresh.
REMINDERS_UNSENT = {"week_sent_at": None, "day_sent_at": None, "morning_sent_at": None, "here_at": None}
WHY = ("Away", "Working", "Not feeling well", "Rather not say")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _when(row: Dict[str, Any], zone) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(row["starts_at"]).replace("Z", "+00:00")).astimezone(zone)
    except (KeyError, TypeError, ValueError):
        return None


def on() -> bool:
    """The member's side follows the office's switch: nobody can be asked
    to serve where the office can't schedule."""
    return sp.mode() != "off"


# ─── reading what's mine ─────────────────────────────────────────────


def _services(biz: str, zone, lo: datetime, hi: datetime, ids: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    path = (f"/worship_services?business_id=eq.{_q(biz)}&archived_at=is.null&is_template=eq.false"
            + (f"&id=in.({_ids(ids)})" if ids is not None else
               f"&starts_at=gte.{_q(_iso(lo))}&starts_at=lt.{_q(_iso(hi))}")
            + "&select=id,title,starts_at&order=starts_at.asc")
    out = {}
    for r in (_read(path) if ids is None or ids else []):
        at = _when(r, zone)
        if at:
            out[str(r["id"])] = {"id": str(r["id"]), "title": r.get("title") or "Sunday service", "at": at,
                                 "day": at.date().isoformat()}
    return out


def mine(biz: Dict[str, Any], cid: str) -> Optional[Dict[str, Any]]:
    """Everything My serving shows, or None when this member isn't on a
    Sunday team and nobody has asked them anything."""
    biz_id = str(biz["id"])
    zone = sp._zone(biz_id)
    now = sp._now().astimezone(zone)
    teams = _read(f"/serve_teams?business_id=eq.{_q(biz_id)}&select=group_id,call_time,max_month")
    gids = [str(t["group_id"]) for t in teams]
    member_of = [str(m["group_id"]) for m in (_read(
        f"/group_members?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&group_id=in.({_ids(gids)})&select=group_id")
        if gids else [])]
    soon = _services(biz_id, zone, now - timedelta(hours=3), now + timedelta(days=AHEAD_DAYS))
    sids = list(soon)
    rows = (_read(f"/serve_assignments?business_id=eq.{_q(biz_id)}&service_id=in.({_ids(sids)})"
                  f"&or=(contact_id.eq.{_q(cid)},swap_to.eq.{_q(cid)},status.eq.offered)"
                  f"&select=id,service_id,position_id,slot,contact_id,status,note,asked_by,asked_at,swap_to,swap_asked_at")
            if sids else [])
    if not member_of and not any(str(r.get("contact_id")) == cid or str(r.get("swap_to")) == cid for r in rows):
        return None
    trained = {str(t["position_id"]): t.get("level") or "trained" for t in _read(
        f"/serve_trained?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&select=position_id,level")}
    pids = {str(r["position_id"]) for r in rows} | set(trained)
    places = {str(p["id"]): p for p in (_read(
        f"/serve_positions?business_id=eq.{_q(biz_id)}&id=in.({_ids(pids)})&select=id,group_id,name,active,sort")
        if pids else [])}
    names = {str(g["id"]): g["name"] for g in (_read(
        f"/groups?business_id=eq.{_q(biz_id)}&id=in.({_ids(gids)})&select=id,name") if gids else [])}
    turns = {str(t["group_id"]): t for t in teams}
    away = _read(f"/serve_away?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}"
                 f"&ends_on=gte.{now.date().isoformat()}&select=id,starts_on,ends_on,note&order=starts_on.asc")
    pref = _read(f"/serve_prefs?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&select=often&limit=1")

    def is_away(day: str) -> bool:
        return any(str(a["starts_on"]) <= day <= str(a["ends_on"]) for a in away)

    def busy(sid: str) -> bool:
        return any(str(r.get("contact_id")) == cid and str(r["service_id"]) == sid and r["status"] in ("asked", "yes")
                   for r in rows)

    def item(r: Dict[str, Any]) -> Dict[str, Any]:
        s = soon[str(r["service_id"])]
        p = places.get(str(r["position_id"])) or {}
        gid = str(p.get("group_id") or "")
        return {"id": str(r["id"]), "service": s, "place": p.get("name") or "A place", "team": names.get(gid, "Your team"),
                "group_id": gid, "call_time": sp._hhmm((turns.get(gid) or {}).get("call_time")), "status": r["status"],
                "asked_by": r.get("asked_by") or "", "asked_at": r.get("asked_at"), "note": r.get("note") or "",
                "swap_to": str(r["swap_to"]) if r.get("swap_to") else None}

    mine_rows = [r for r in rows if str(r.get("contact_id")) == cid]
    asks = [item(r) for r in mine_rows if r["status"] == "asked"]
    covers = [item(r) | {"from_id": str(r["contact_id"])} for r in rows
              if str(r.get("swap_to")) == cid and r["status"] == "yes"]
    coming = [item(r) for r in mine_rows if r["status"] == "yes"]
    open_ = [item(r) for r in rows if r["status"] == "offered" and trained.get(str(r["position_id"])) == "trained"
             and not busy(str(r["service_id"])) and not is_away(soon[str(r["service_id"])]["day"])]
    who = sp._people(biz_id, [c["from_id"] for c in covers] + [c["swap_to"] for c in coming if c["swap_to"]])
    for c in covers:
        c["from"] = (who.get(c["from_id"]) or {}).get("name") or "Someone"
    for c in coming:
        c["swap_name"] = (who.get(c["swap_to"]) or {}).get("name") if c["swap_to"] else None
    # Who else on the team serves those Sundays: "Be there 10:15 · with Luis and Marcus".
    if coming:
        team_places = {pid for pid, p in (places.items())}
        at_mine = _read(f"/serve_assignments?business_id=eq.{_q(biz_id)}&service_id=in.({_ids(c['service']['id'] for c in coming)})"
                        f"&status=in.(asked,yes)&select=service_id,position_id,contact_id")
        other_pids = {str(r["position_id"]) for r in at_mine} - team_places
        if other_pids:
            places.update({str(p["id"]): p for p in _read(
                f"/serve_positions?business_id=eq.{_q(biz_id)}&id=in.({_ids(other_pids)})&select=id,group_id,name,active")})
        names_ = sp._people(biz_id, [r["contact_id"] for r in at_mine if str(r["contact_id"]) != cid])
        for c in coming:
            c["with"] = [names_[str(r["contact_id"])]["name"] for r in at_mine
                         if str(r["service_id"]) == c["service"]["id"] and str(r["contact_id"]) != cid
                         and str((places.get(str(r["position_id"])) or {}).get("group_id")) == c["group_id"]
                         and str(r["contact_id"]) in names_]
    by_time = lambda x: x["service"]["at"]
    teams_out = []
    for gid in member_of:
        # In the team's own order of places, as the office set it.
        mine_places = sorted((p for pid, p in places.items() if str(p.get("group_id")) == gid and p.get("active") is not False
                              and trained.get(pid) == "trained"), key=lambda p: (p.get("sort") or 0, p["name"].lower()))
        teams_out.append({"group_id": gid, "name": names.get(gid, "A team"), "places": [p["name"] for p in mine_places]})
    return {
        "teams": sorted(teams_out, key=lambda t: t["name"].lower()),
        "asks": sorted(asks + covers, key=by_time), "coming": sorted(coming, key=by_time), "open": sorted(open_, key=by_time),
        "this_year": _served_this_year(biz_id, cid, zone, now),
        "away": [{"id": str(a["id"]), "starts_on": str(a["starts_on"]), "ends_on": str(a["ends_on"]),
                  "note": a.get("note") or ""} for a in away],
        "often": (pref[0].get("often") if pref else None),
        # The church's next service: "this Sunday" means that one, not
        # whichever Sunday this member serves next.
        "next_day": min((s["day"] for s in soon.values()), default=None),
    }


def _served_this_year(biz_id: str, cid: str, zone, now: datetime) -> int:
    said = _read(f"/serve_assignments?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&status=eq.yes&select=service_id")
    ids = sorted({str(r["service_id"]) for r in said})
    if not ids:
        return 0
    n = 0
    for i in range(0, len(ids), 150):
        for s in _services(biz_id, zone, now, now, ids[i:i + 150]).values():
            if s["at"].year == now.year and s["at"] <= now:
                n += 1
    return n


def serves(biz: Dict[str, Any], cid: str) -> bool:
    """Me shows My serving to someone on a Sunday team, or anyone asked."""
    if not on():
        return False
    biz_id = str(biz["id"])
    try:
        gids = [str(t["group_id"]) for t in _read(f"/serve_teams?business_id=eq.{_q(biz_id)}&select=group_id")]
        if gids and _read(f"/group_members?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}"
                          f"&group_id=in.({_ids(gids)})&select=group_id&limit=1"):
            return True
        return bool(_read(f"/serve_assignments?business_id=eq.{_q(biz_id)}&or=(contact_id.eq.{_q(cid)},swap_to.eq.{_q(cid)})"
                          f"&select=id&limit=1"))
    except HTTPException:
        return False


def waiting(biz: Dict[str, Any], cid: str) -> List[Dict[str, Any]]:
    """Home's card: asks and cover requests waiting on this member."""
    if not on():
        return []
    try:
        m = mine(biz, cid)
    except HTTPException:
        return []
    return (m or {}).get("asks") or []


# ─── one ask ─────────────────────────────────────────────────────────


def _row(biz_id: str, aid: str) -> Dict[str, Any]:
    rows = _read(f"/serve_assignments?id=eq.{_q(aid)}&business_id=eq.{_q(biz_id)}&select=*&limit=1")
    if not rows:
        raise HTTPException(404, "That isn't on the schedule anymore.")
    return rows[0]


def _future(biz_id: str, row: Dict[str, Any]) -> Tuple[Any, datetime]:
    zone = sp._zone(biz_id)
    s = _services(biz_id, zone, sp._now(), sp._now(), [str(row["service_id"])]).get(str(row["service_id"]))
    if not s or s["at"] <= sp._now().astimezone(zone):
        raise HTTPException(409, "That Sunday has already passed.")
    return zone, s["at"]


def ask_view(biz: Dict[str, Any], cid: str, aid: str) -> Dict[str, Any]:
    """The ask (board 7): the place, the Sunday, who's on with them, and the
    next Sunday they're free, for "I can't, but I can do …"."""
    biz_id = str(biz["id"])
    row = _row(biz_id, aid)
    mine_ = str(row.get("contact_id")) == cid
    cover = str(row.get("swap_to")) == cid and row["status"] == "yes"
    if not mine_ and not cover and row["status"] != "offered":
        raise HTTPException(404, "That isn't on the schedule anymore.")
    board = sp._service_board(biz_id, str(row["service_id"]))
    sid, pid = str(row["service_id"]), str(row["position_id"])
    team = board.place_team.get(pid)
    if not team:
        raise HTTPException(404, "That place isn't on a Sunday team anymore.")
    if row["status"] == "offered":
        me = next((c for c in board.candidates(sid, pid) if c["contact_id"] == cid), None)
        if not me or me["trained"] != "trained":
            raise HTTPException(404, "That isn't on the schedule anymore.")
    svc = board.service[sid]
    at = datetime.fromisoformat(str(svc["starts_at"]).replace("Z", "+00:00")).astimezone(board.zone)
    others = sp._people(biz_id, [r.get("contact_id") for r in board.rows])
    with_ = []
    for p in team["places"]:
        for slot in range(1, (p["needed"] or 1) + 1):
            if p["id"] == pid and slot == int(row.get("slot") or 1):
                continue
            h = board.holder(sid, p["id"], slot)
            if h and h["status"] in ("asked", "yes") and h.get("contact_id"):
                with_.append({"name": (others.get(str(h["contact_id"])) or {}).get("name") or "Someone", "place": p["name"],
                              "status": h["status"]})
            else:
                learning = [x["name"] for x in p["people"] if x["level"] == "learning"]
                with_.append({"name": None, "place": p["name"], "status": "open", "learning": learning[:1]})
    leaders = [x["name"] for x in team["people"] if x["leader"]]
    asker = row.get("asked_by") or ""
    if not asker or asker == sp.FILLED_BY:
        asker = leaders[0].split(" ")[0] if leaders else ""
    return {
        "id": str(row["id"]), "status": row["status"], "cover": cover,
        "cover_from": (others.get(str(row["contact_id"])) or {}).get("name") if cover else None,
        "place": next(p["name"] for p in team["places"] if p["id"] == pid), "team": team["name"], "group_id": team["group_id"],
        "call_time": team.get("call_time"), "at": at, "title": svc["title"], "asked_by": asker,
        "leader": leaders[0] if leaders else None, "note": row.get("note") or "", "past": at <= sp._now().astimezone(board.zone),
        "with": with_, "can_do": _next_free(biz_id, cid, board.zone, at) if mine_ and row["status"] in ("asked", "no") else None,
    }


def free_sundays(biz_id: str, cid: str, zone, after: datetime, n: int = 2, days: int = 29) -> List[Dict[str, Any]]:
    """The next services (up to n, within `days`) that this member isn't
    away for and isn't already serving at: "I can't, but I can do …"."""
    later = _services(biz_id, zone, after + timedelta(hours=12), after + timedelta(days=days))
    if not later:
        return []
    rows = _read(f"/serve_assignments?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&service_id=in.({_ids(later)})"
                 f"&status=in.(asked,yes)&select=service_id")
    taken = {str(r["service_id"]) for r in rows}
    away = _read(f"/serve_away?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&select=starts_on,ends_on")
    out: List[Dict[str, Any]] = []
    for s in later.values():
        if s["id"] in taken or any(str(a["starts_on"]) <= s["day"] <= str(a["ends_on"]) for a in away):
            continue
        out.append({"id": s["id"], "at": s["at"], "title": s["title"]})
        if len(out) >= n:
            break
    return out


def _next_free(biz_id: str, cid: str, zone, after: datetime) -> Optional[Dict[str, Any]]:
    """The next service within two weeks that this member isn't away for
    and isn't already serving at."""
    free = free_sundays(biz_id, cid, zone, after, n=1, days=15)
    return free[0] if free else None


# ─── answering ───────────────────────────────────────────────────────


def _patch(biz_id: str, aid: str, guard: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    saved = sb_clients.sb_patch_as_service(
        f"/serve_assignments?id=eq.{_q(aid)}&business_id=eq.{_q(biz_id)}&{guard}&select=*", fields)
    if saved is None:
        raise HTTPException(503, "That didn't save. Try again.")
    if not saved:
        raise HTTPException(409, "That changed while you were looking. Open it again.")
    return saved[0]


def answer(biz: Dict[str, Any], cid: str, aid: str, ans: str, why: str = "",
           offer: Optional[str] = None) -> Dict[str, Any]:
    """yes, no, or other (can't, but free the next Sunday, or the one they
    picked: `offer`, a service from free_sundays). An answer to a cover
    request moves the place to this member, or leaves it with the one who
    asked."""
    biz_id = str(biz["id"])
    if ans not in ("yes", "no", "other"):
        raise HTTPException(400, "The answer is yes or no.")
    why = why if why in WHY else ""
    row = _row(biz_id, aid)
    zone, at = _future(biz_id, row)
    now = sp._now().isoformat()
    if str(row.get("swap_to")) == cid and row["status"] == "yes":
        if ans != "yes":
            return _patch(biz_id, aid, f"swap_to=eq.{_q(cid)}", {"swap_to": None, "swap_asked_at": None, "swap_told_at": None})
        board = sp._service_board(biz_id, str(row["service_id"]))
        me = next((c for c in board.candidates(str(row["service_id"]), str(row["position_id"])) if c["contact_id"] == cid), None)
        if not me or me["away"] or me["clash"]:
            raise HTTPException(409, "You're away or already serving that hour, so you can't cover it.")
        was = (sp._people(biz_id, [row["contact_id"]]).get(str(row["contact_id"])) or {}).get("name") or "someone"
        return _patch(biz_id, aid, f"swap_to=eq.{_q(cid)}",
                      {"contact_id": cid, "status": "yes", "answered_at": now, "swap_to": None, "swap_asked_at": None, "swap_told_at": None,
                       "note": f"Covering for {was.split(' ')[0]}"[:300], **REMINDERS_UNSENT})
    if str(row.get("contact_id")) != cid or row["status"] not in ("asked", "yes", "no"):
        raise HTTPException(404, "That isn't on the schedule anymore.")
    if ans == "yes":
        return _patch(biz_id, aid, f"contact_id=eq.{_q(cid)}", {"status": "yes", "answered_at": now, "note": ""})
    note = why
    if ans == "other":
        if offer:
            nxt = next((f for f in free_sundays(biz_id, cid, zone, at) if f["id"] == offer), None)
            if not nxt:
                raise HTTPException(409, "That Sunday isn't free for you anymore. Pick another.")
        else:
            nxt = _next_free(biz_id, cid, zone, at)
        if nxt:
            note = f"Can do {_day(nxt['at'])}" + (f" · {why}" if why else "")
    return _patch(biz_id, aid, f"contact_id=eq.{_q(cid)}",
                  {"status": "no", "answered_at": now, "note": note[:300], "swap_to": None, "swap_asked_at": None, "swap_told_at": None})


def _day(at: datetime) -> str:
    return f"{at.strftime('%b')} {at.day}"


def set_why(biz: Dict[str, Any], cid: str, aid: str, why: str) -> Dict[str, Any]:
    """Why they can't, if they want to say; only the office and the team's
    leaders see it. A "can do" date they offered stays in front."""
    biz_id = str(biz["id"])
    row = _row(biz_id, aid)
    if str(row.get("contact_id")) != cid or row["status"] != "no":
        raise HTTPException(404, "That isn't on the schedule anymore.")
    why = why if why in WHY else ""
    keep = (row.get("note") or "").split(" · ")[0]
    note = (f"{keep} · {why}" if keep.startswith("Can do ") and why else keep if keep.startswith("Can do ") else why)
    return _patch(biz_id, aid, f"contact_id=eq.{_q(cid)}", {"note": note[:300]})


def take(biz: Dict[str, Any], cid: str, aid: str) -> Dict[str, Any]:
    """Take a place offered to the whole team: the first yes takes it."""
    biz_id = str(biz["id"])
    row = _row(biz_id, aid)
    if row["status"] != "offered":
        raise HTTPException(409, "Someone already took it. Thank you for offering.")
    _future(biz_id, row)
    board = sp._service_board(biz_id, str(row["service_id"]))
    me = next((c for c in board.candidates(str(row["service_id"]), str(row["position_id"])) if c["contact_id"] == cid), None)
    if not me or me["trained"] != "trained":
        raise HTTPException(404, "That isn't on the schedule anymore.")
    if me["away"] or me["clash"]:
        raise HTTPException(409, "You're away or already serving that hour.")
    try:
        return _patch(biz_id, aid, "status=eq.offered", {"contact_id": cid, "status": "yes", "answered_at": sp._now().isoformat()})
    except HTTPException as e:
        if e.status_code == 409:
            raise HTTPException(409, "Someone already took it. Thank you for offering.")
        raise


# ─── a Sunday they can't make ────────────────────────────────────────


def subs(biz: Dict[str, Any], cid: str, aid: str) -> List[Dict[str, Any]]:
    """Who could cover a Sunday this member said yes to: the team's people
    who are trained on the place or learning it, the free first."""
    biz_id = str(biz["id"])
    row = _row(biz_id, aid)
    if str(row.get("contact_id")) != cid or row["status"] != "yes":
        raise HTTPException(404, "That isn't on the schedule anymore.")
    board = sp._service_board(biz_id, str(row["service_id"]))
    return [c for c in board.candidates(str(row["service_id"]), str(row["position_id"]))
            if c["contact_id"] != cid and c["trained"] in ("trained", "learning")]


def ask_sub(biz: Dict[str, Any], cid: str, aid: str, sub: str) -> Dict[str, Any]:
    biz_id = str(biz["id"])
    row = _row(biz_id, aid)
    _future(biz_id, row)
    pick = next((c for c in subs(biz, cid, aid) if c["contact_id"] == sub), None)
    if not pick:
        raise HTTPException(404, "They aren't on the team for that place.")
    if not pick["ok"]:
        raise HTTPException(409, f"{pick['name'].split(' ')[0]} isn't free that day.")
    return _patch(biz_id, aid, f"contact_id=eq.{_q(cid)}&status=eq.yes",
                  {"swap_to": sub, "swap_asked_at": sp._now().isoformat(), "swap_told_at": None})


def stop_sub(biz: Dict[str, Any], cid: str, aid: str) -> Dict[str, Any]:
    return _patch(str(biz["id"]), aid, f"contact_id=eq.{_q(cid)}&status=eq.yes", {"swap_to": None, "swap_asked_at": None, "swap_told_at": None})


def cant_make_it(biz: Dict[str, Any], cid: str, aid: str, why: str = "") -> Dict[str, Any]:
    """Just tell the leader: the place opens and the office sees why."""
    biz_id = str(biz["id"])
    row = _row(biz_id, aid)
    _future(biz_id, row)
    why = why if why in WHY else ""
    if str(row.get("contact_id")) != cid or row["status"] not in ("asked", "yes"):
        raise HTTPException(404, "That isn't on the schedule anymore.")
    return _patch(biz_id, aid, f"contact_id=eq.{_q(cid)}",
                  {"status": "no", "answered_at": sp._now().isoformat(), "note": ("Can't make it" + (f" · {why}" if why else ""))[:300],
                   "swap_to": None, "swap_asked_at": None, "swap_told_at": None})


# ─── away days and how often ─────────────────────────────────────────


def add_away(biz: Dict[str, Any], cid: str, start: str, end: str, note: str = "") -> Dict[str, Any]:
    biz_id = str(biz["id"])
    try:
        a, b = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end or start)[:10])
    except ValueError:
        raise HTTPException(400, "Pick the days you're away.")
    today = sp._now().astimezone(sp._zone(biz_id)).date()
    if b < a or b < today or (b - a).days > 366:
        raise HTTPException(400, "Pick the days you're away, a year at most, not in the past.")
    have = _read(f"/serve_away?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&ends_on=gte.{today.isoformat()}&select=id")
    if len(have) >= MAX_AWAY:
        raise HTTPException(400, "That's a lot of away dates. Take some off first.")
    saved = sb_clients.sb_post_as_service("/serve_away?select=id", {
        "business_id": biz_id, "contact_id": cid, "starts_on": a.isoformat(), "ends_on": b.isoformat(),
        "note": " ".join(str(note or "").split())[:100]})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    return saved[0]


def drop_away(biz: Dict[str, Any], cid: str, away_id: str) -> None:
    if not sb_clients.sb_delete_as_service(
            f"/serve_away?id=eq.{_q(away_id)}&business_id=eq.{_q(str(biz['id']))}&contact_id=eq.{_q(cid)}"):
        raise HTTPException(503, "That didn't save. Try again.")


def set_often(biz: Dict[str, Any], cid: str, often: str) -> None:
    if often not in OFTEN:
        raise HTTPException(400, "Pick how often.")
    saved = sb_clients.sb_post_as_service(
        "/serve_prefs?on_conflict=business_id,contact_id&select=often",
        {"business_id": str(biz["id"]), "contact_id": cid, "often": often, "updated_at": sp._now().isoformat()},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")


# ─── how I hear (board 8) ────────────────────────────────────────────


def hearing(biz: Dict[str, Any], cid: str) -> Optional[Dict[str, Any]]:
    """How I hear, or None where nothing would reach anyone yet: the
    church hasn't switched Serving on. Phone alerts are member_push's own
    box for kind "serving"; the email copy is serve_prefs.email."""
    import member_push
    if "serving" not in member_push.church_kinds(biz.get("settings")):
        return None
    biz_id = str(biz["id"])
    off = member_push.turned_off(biz_id, cid)
    pref = _read(f"/serve_prefs?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&select=email&limit=1")
    return {"phone_shown": member_push.ready(), "phone": "serving" not in (off or set()),
            "devices": member_push.device_count(biz_id, cid) if member_push.ready() else 0,
            "email": not pref or pref[0].get("email") is not False}


def set_hearing(biz: Dict[str, Any], cid: str, what: str, on_: bool) -> None:
    import member_push
    biz_id = str(biz["id"])
    if what == "phone":
        off = member_push.turned_off(biz_id, cid)
        if off is None or not member_push.save_turned_off(biz_id, cid, (off - {"serving"}) if on_ else (off | {"serving"})):
            raise HTTPException(503, "That didn't save. Try again.")
        return
    if what != "email":
        raise HTTPException(400, "Pick phone alerts or email.")
    # Turning the email copy back on also undoes "Stop these emails".
    _save_prefs(biz_id, cid, {"email": on_, **({"email_stopped_at": None} if on_ else {})})


def _save_prefs(biz_id: str, cid: str, fields: Dict[str, Any]) -> None:
    saved = sb_clients.sb_post_as_service(
        "/serve_prefs?on_conflict=business_id,contact_id&select=email",
        {"business_id": biz_id, "contact_id": cid, **fields, "updated_at": sp._now().isoformat()},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")


def stop_emails(biz: Dict[str, Any], cid: str) -> None:
    """"Stop these emails" (the link in every serving email): no serving
    email from this church reaches them again, not even an ask their phone
    missed, until they turn the email copy back on. Only this church, and
    only serving: their sign-in codes and other mail still go."""
    _save_prefs(str(biz["id"]), cid, {"email": False, "email_stopped_at": sp._now().isoformat()})


def emails_on(biz_id: str, cid: str) -> bool:
    """False once they've said "Stop these emails"."""
    rows = _read(f"/serve_prefs?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&select=email_stopped_at&limit=1")
    return not (rows and rows[0].get("email_stopped_at"))


# ─── the Sunday pack (board 9) ───────────────────────────────────────

HERE_FROM_HOURS = 3        # "I'm here" opens this long before the call time


def pack(biz: Dict[str, Any], cid: str, aid: str) -> Dict[str, Any]:
    """Everything a member needs for one Sunday they said yes to: when to be
    there and "I'm here", each team they're on that day, the songs (when
    their team has notes on them), their team's moments, and today's order.
    Only their own yes; a song is its title, key and parts, never words."""
    import sunday_order as so
    biz_id = str(biz["id"])
    row = _row(biz_id, aid)
    if str(row.get("contact_id")) != cid or row["status"] != "yes":
        raise HTTPException(404, "That isn't on the schedule anymore.")
    zone = sp._zone(biz_id)
    svc = so._service(biz_id, str(row["service_id"]), zone)
    at = _when(svc, zone)
    if not at:
        raise HTTPException(404, "That isn't on the schedule anymore.")
    now = sp._now().astimezone(zone)
    order = so.order_of(biz_id, svc, zone)
    teams = {t["group_id"]: t for t in sp._teams(biz_id)[0]}
    place_team = {p["id"]: t for t in teams.values() for p in t["places"]}
    mine = _read(f"/serve_assignments?business_id=eq.{_q(biz_id)}&service_id=eq.{_q(row['service_id'])}"
                 f"&contact_id=eq.{_q(cid)}&status=eq.yes&select=id,position_id,here_at")
    roles = []
    for r in mine:
        t = place_team.get(str(r["position_id"]))
        if not t:
            continue
        place = next(p["name"] for p in t["places"] if p["id"] == str(r["position_id"]))
        call = sp._hhmm(t.get("call_time"))
        leaders = [p["name"] for p in t["people"] if p.get("leader")]
        roles.append({"id": str(r["id"]), "team": t["name"], "group_id": t["group_id"], "place": place,
                      "call": call, "here": bool(r.get("here_at")), "leader": leaders[0] if leaders else None})
    roles.sort(key=lambda x: x["team"].lower())
    role = next((x for x in roles if x["id"] == aid), roles[0] if roles else None)
    if not role:
        raise HTTPException(404, "That isn't on the schedule anymore.")
    gid = role["group_id"]
    items = [i for i in order["items"] if not i["section"]]
    note = lambda i: (i.get("notes") or {}).get(gid) or ""
    songs = [i for i in items if i.get("kind") == "song"]
    # The songs are their own card for a team with notes on most of them (the
    # band, board 9); another team's note on a song is one of its moments
    # ("New slides for Firm Foundation").
    noted = sum(1 for i in songs if note(i))
    with_songs = noted * 2 > len(songs)
    n = 0
    song_rows = []
    for i in songs if with_songs else []:
        n += 1
        song_rows.append({"n": n, "title": i["title"], "key": i.get("key") or "", "parts": i.get("parts") or [],
                          "who": i.get("who") or "", "note": note(i)})
    moments = [{"time": i["time"], "title": i["title"], "note": note(i) or (i.get("notes") or {}).get("all", "")}
               for i in items if (note(i) or (i.get("notes") or {}).get("all")) and not (with_songs and i.get("kind") == "song")]
    call_at = (datetime.combine(at.date(), datetime.strptime(role["call"], "%H:%M").time(), tzinfo=zone)
               if role["call"] else at)
    ends = (datetime.combine(at.date(), datetime.strptime(order["ends"], "%H:%M").time(), tzinfo=zone)
            if order.get("ends") else at + timedelta(hours=2))
    return {
        "id": aid, "title": svc.get("title") or "Sunday service", "at": at, "role": role, "roles": roles,
        "songs": song_rows, "moments": moments,
        "order": [{"time": i["time"], "title": i["title"], "who": i.get("who") or ""} for i in items if i.get("part") == "service"],
        "here_open": now.date() == at.date() and call_at - timedelta(hours=HERE_FROM_HOURS) <= now <= ends,
        "past": now > ends,
    }


def here(biz: Dict[str, Any], cid: str, aid: str) -> Dict[str, Any]:
    """"I'm here": only on the day, from a few hours before the call time
    until the service ends; once."""
    p = pack(biz, cid, aid)
    if not p["here_open"]:
        raise HTTPException(409, "\"I'm here\" opens on the day, a few hours before you're due.")
    rows = sb_clients.sb_patch_as_service(
        f"/serve_assignments?id=eq.{_q(p['role']['id'])}&business_id=eq.{_q(str(biz['id']))}&contact_id=eq.{_q(cid)}"
        f"&status=eq.yes&here_at=is.null&select=id", {"here_at": sp._now().isoformat()})
    if rows is None:
        raise HTTPException(503, "That didn't save. Try again.")
    return p
