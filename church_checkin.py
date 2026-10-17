"""
church_checkin.py — Sunday check-in: members count themselves.

Kevin, 2026-10-17, after the research on how churches take attendance:
"the app checkin and online checkin for online view are all good. kiosk
is for children." So adults never use a kiosk. A code on the welcome slide
(or a sign at the door) opens the church's /here, which is the member's
own page; one tap checks in their family ("At church" or "Watching
online"). The same card waits at the top of their Home while check-in is
open, so it works whether they scan or just open the app. The Kids self
kiosk stays for children, but the parent who checks children in counts as
there (method 'kids_parent').

Shepherding (canvas 31su6kdYmYecH5b2NxjBJN) reads these Sundays to see who
has stopped coming; this module only records them.

  settings(biz)              the church's Sunday service (defaults until saved)
  save_settings(biz, body)   the office sets it once
  window(st, now)            this week's service: when check-in opens/closes
  ensure_occasion(biz, st, day)  that day's occasion in Services & Events,
                             made once (a unique index keeps it once)
  family_of(biz, me)         the member and the other adults of their family
  card(biz, me)              what the member sees: off / closed / open + marks
  check_in(...)              write the member's choice; idempotent
  count_kids_parent(...)     the self kiosk's parent; never fails the kiosk
  counts(biz, entry)         this Sunday by how people were counted
  sweep(now)                 hourly: make the coming Sunday's occasion early

Rows are written as the service role (the member page and the kiosk have
no seat); attendance's own trigger keeps every row inside its church.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import HTTPException

import sb_clients

logger = logging.getLogger("church_checkin")

DEFAULTS: Dict[str, Any] = {
    "enabled": False, "weekday": 6, "start_time": "11:00", "timezone": "",
    "opens_before_min": 30, "closes_after_min": 180, "title": "",
}
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# Who a member's phone may write, and what it leaves alone: a check-in at
# the door, by a station, the kiosk's parent or an RSVP stays as it is.
MINE = ("self", "online")
FAMILY_CAP = 12
_TIME = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _zone(name: str) -> Optional[ZoneInfo]:
    try:
        return ZoneInfo(str(name)) if name else None
    except Exception:
        return None


def church_zone_name(biz: Dict[str, Any]) -> str:
    """The church's own clock, as the Lead tab reads it; New York if none."""
    s = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    avail = s.get("availability") if isinstance(s.get("availability"), dict) else {}
    name = str(s.get("timezone") or avail.get("timezone") or "")
    return name if _zone(name) else "America/New_York"


# ─── settings ─────────────────────────────────────────────────────────

def settings(biz: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The church's Sunday service: its saved row, else the defaults (off,
    Sunday 11:00 on the church's clock). None when the read failed."""
    rows = _rows(f"/church_checkin_settings?business_id=eq.{_q(biz['id'])}&select=*&limit=1")
    if rows is None:
        return None
    out = dict(DEFAULTS, timezone=church_zone_name(biz), saved=False)
    if rows:
        r = rows[0]
        out.update({k: r[k] for k in DEFAULTS if r.get(k) is not None}, saved=True)
    if not _zone(out["timezone"]):
        out["timezone"] = church_zone_name(biz)
    return out


def _clean_settings(body: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "enabled" in body:
        out["enabled"] = bool(body["enabled"])
    if "weekday" in body:
        try:
            wd = int(body["weekday"])
        except (TypeError, ValueError):
            raise HTTPException(400, "Pick the day of your service")
        if not 0 <= wd <= 6:
            raise HTTPException(400, "Pick the day of your service")
        out["weekday"] = wd
    if "start_time" in body:
        t = str(body["start_time"] or "").strip()[:5]
        if not _TIME.match(t):
            raise HTTPException(400, "Give the service's start time, like 11:00")
        out["start_time"] = t
    if "timezone" in body:
        tz = str(body["timezone"] or "").strip()
        if not _zone(tz):
            raise HTTPException(400, "That time zone isn't one we know")
        out["timezone"] = tz
    for key, lo, hi, what in (("opens_before_min", 0, 240, "opens"), ("closes_after_min", 30, 720, "closes")):
        if key in body:
            try:
                n = int(body[key])
            except (TypeError, ValueError):
                raise HTTPException(400, f"Say when check-in {what}")
            out[key] = max(lo, min(hi, n))
    if "title" in body:
        out["title"] = " ".join(str(body["title"] or "").split())[:80]
    return out


def save_settings(biz: Dict[str, Any], body: Dict[str, Any], by_user: Optional[str]) -> Dict[str, Any]:
    cur = settings(biz)
    if cur is None:
        raise HTTPException(503, "Check-in couldn’t be read. Nothing was changed — try again.")
    patch = _clean_settings(body)
    row = {k: cur[k] for k in DEFAULTS}
    row.update(patch)
    row.update({"business_id": str(biz["id"]), "updated_by": by_user, "updated_at": _iso(_now())})
    saved = sb_clients.sb_post_as_service("/church_checkin_settings?on_conflict=business_id", row,
                                          prefer="return=representation,resolution=merge-duplicates")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn’t save. Nothing was changed — try again.")
    return settings(biz) or dict(row, saved=True)


# ─── this week's service ──────────────────────────────────────────────

def window(st: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """This week's service on the church's clock: the next service day
    whose check-in hasn't closed yet (today's, until it closes)."""
    tz = _zone(st.get("timezone") or "") or ZoneInfo("America/New_York")
    now = (now or _now()).astimezone(tz)
    hh, mm = (int(x) for x in str(st.get("start_time") or "11:00").split(":"))
    before = timedelta(minutes=int(st.get("opens_before_min") or 0))
    after = timedelta(minutes=int(st.get("closes_after_min") or 180))
    day = now.date() + timedelta(days=(int(st.get("weekday", 6)) - now.weekday()) % 7)
    start = datetime.combine(day, time(hh, mm), tzinfo=tz)
    if now > start + after:
        day += timedelta(days=7)
        start = datetime.combine(day, time(hh, mm), tzinfo=tz)
    opens, closes = start - before, start + after
    return {"day": day, "start": start, "opens": opens, "closes": closes, "open": opens <= now <= closes,
            "weekday": DAYS[day.weekday()]}


def clock(dt: datetime) -> str:
    """'11:00 AM', '6:30 PM' (no leading zero on any system)."""
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


# ─── the occasion ─────────────────────────────────────────────────────

def _roster(biz_id: str) -> Optional[List[Dict[str, Any]]]:
    rows = _rows(f"/custom_modules?business_id=eq.{_q(biz_id)}&archetype=eq.event_roster&is_active=eq.true"
                 "&select=id,name,archetype_params&order=created_at.asc&limit=50")
    return rows


def _entries(biz_id: str, module_ids: List[str]) -> Optional[List[Dict[str, Any]]]:
    if not module_ids:
        return []
    return _rows(f"/module_entries?business_id=eq.{_q(biz_id)}&module_id=in.({','.join(_q(m) for m in module_ids)})"
                 "&status=eq.active&select=id,module_id,data&order=created_at.desc&limit=400")


def _shape(e: Dict[str, Any], fields: Dict[str, Any]) -> Dict[str, Any]:
    data = e.get("data") or {}
    return {"id": str(e["id"]), "title": str(data.get(fields["title_field"]) or "").strip() or "Service",
            "date": str(data.get(fields["date_field"]) or "")}


def find_occasion(biz_id: str, day: date, *, made: bool = True) -> Optional[Dict[str, Any]]:
    """That day's occasion: the one check-in made, else a service the church
    already dated for that day. {} when there is none, None when unread."""
    from events_rsvp_router import _parse_day, resolve_fields
    mods = _roster(biz_id)
    if mods is None:
        return None
    fields = {str(m["id"]): resolve_fields(m.get("archetype_params")) for m in mods}
    entries = _entries(biz_id, list(fields))
    if entries is None:
        return None
    ours, theirs = None, None
    for e in entries:
        f = fields.get(str(e.get("module_id")))
        data = e.get("data") or {}
        if not f:
            continue
        if made and str(data.get("_checkin_day") or "") == day.isoformat():
            ours = _shape(e, f)
            break
        if _parse_day(data.get(f["date_field"])) == day and str(data.get("type") or "service") == "service":
            theirs = theirs or _shape(e, f)
    return ours or theirs or {}


def ensure_occasion(biz_id: str, st: Dict[str, Any], day: date) -> Optional[Dict[str, Any]]:
    """That day's occasion, made in Services & Events if it isn't there.
    None when it can't be read or made (the church has no Services & Events
    room, or a write failed)."""
    found = find_occasion(biz_id, day)
    if found is None or found:
        return found or None
    from events_rsvp_router import resolve_fields
    mods = _roster(biz_id)
    if not mods:
        return None
    mod = next((m for m in mods if "service" in str(m.get("name") or "").lower()), mods[0])
    f = resolve_fields(mod.get("archetype_params"))
    # Named after the church's own undated service ("Sunday Worship"), else
    # what the office typed, else plainly.
    entries = _entries(biz_id, [str(mod["id"])]) or []
    template = next((e.get("data") or {} for e in entries
                     if str((e.get("data") or {}).get("type") or "") == "service"
                     and not str((e.get("data") or {}).get(f["date_field"]) or "")), {})
    title = st.get("title") or str(template.get(f["title_field"]) or "").strip() or f"{DAYS[day.weekday()]} service"
    data = {
        f["title_field"]: title[:120],
        f["date_field"]: f"{day.isoformat()}T{st.get('start_time') or '11:00'}",
        "type": "service",
        f["location_field"]: str(template.get(f["location_field"]) or ""),
        f["signups_field"]: [],
        # Church only: one of these a week never crowds the public events page.
        "_visibility": "private",
        "notes": "Made for Sunday check-in.",
        "_checkin_day": day.isoformat(),
    }
    made = sb_clients.sb_post_as_service("/module_entries", {
        "business_id": biz_id, "module_id": str(mod["id"]), "data": data,
        "status": "active", "created_by": "sunday_checkin"})
    if isinstance(made, list) and made:
        return _shape(made[0], f)
    # Another phone made it first (the unique index): read it back.
    again = find_occasion(biz_id, day)
    return again or None


# ─── the member's family ──────────────────────────────────────────────

def family_of(biz_id: str, me: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """The member first, then the other adults of their family (Families,
    household_adults). Just them when they have no family on record."""
    mine = {"id": str(me["id"]), "name": str(me.get("name") or "").strip() or "You", "me": True}
    links = _rows(f"/household_adults?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(me['id'])}"
                  "&select=household_id&limit=10")
    if links is None:
        return None
    if not links:
        return [mine]
    homes = ",".join(sorted({_q(l["household_id"]) for l in links}))
    adults = _rows(f"/household_adults?business_id=eq.{_q(biz_id)}&household_id=in.({homes})"
                   "&select=contact_id&limit=60")
    if adults is None:
        return None
    others = sorted({str(a["contact_id"]) for a in adults} - {mine["id"]})
    if not others:
        return [mine]
    people = _rows(f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({','.join(_q(o) for o in others)})"
                   "&select=id,name&limit=60")
    if people is None:
        return None
    rest = sorted(({"id": str(p["id"]), "name": str(p.get("name") or "").strip() or "Someone", "me": False}
                   for p in people), key=lambda p: p["name"].lower())
    return ([mine] + rest)[:FAMILY_CAP]


def marks(biz_id: str, entry_id: str, ids: List[str]) -> Optional[Dict[str, Dict[str, Any]]]:
    """{contact_id: their attendance row on this occasion}."""
    if not ids:
        return {}
    rows = _rows(f"/attendance?business_id=eq.{_q(biz_id)}&entry_id=eq.{_q(entry_id)}"
                 f"&contact_id=in.({','.join(_q(i) for i in ids)})&select=id,contact_id,method&limit=100")
    if rows is None:
        return None
    return {str(r["contact_id"]): r for r in rows}


def card(biz: Dict[str, Any], me: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """What the member sees.
        {"state": "off"}                  check-in isn't on at this church
        {"state": "closed", "w": …}       not open yet (or the room is missing)
        {"state": "open", "w", "occasion", "family", "marks"}
        {"state": "error"}                something couldn't be read"""
    st = settings(biz)
    if st is None:
        return {"state": "error"}
    if not st["enabled"]:
        return {"state": "off"}
    w = window(st, now)
    if not w["open"]:
        return {"state": "closed", "w": w}
    occ = ensure_occasion(str(biz["id"]), st, w["day"])
    if not occ:
        return {"state": "error"}
    fam = family_of(str(biz["id"]), me)
    if fam is None:
        return {"state": "error"}
    got = marks(str(biz["id"]), occ["id"], [p["id"] for p in fam])
    if got is None:
        return {"state": "error"}
    return {"state": "open", "w": w, "occasion": occ, "family": fam, "marks": got, "settings": st}


# ─── writing ──────────────────────────────────────────────────────────

def _insert(biz_id: str, entry_id: str, person: Dict[str, Any], method: str) -> bool:
    made = sb_clients.sb_post_as_service("/attendance", {
        "business_id": biz_id, "entry_id": entry_id, "contact_id": person["id"],
        "name": (person.get("name") or "A member").strip()[:160] or "A member", "method": method})
    if isinstance(made, list) and made:
        return True
    # Lost a race with another check-in of the same person: that counts.
    again = _rows(f"/attendance?business_id=eq.{_q(biz_id)}&entry_id=eq.{_q(entry_id)}"
                  f"&contact_id=eq.{_q(person['id'])}&select=id&limit=1")
    return bool(again)


def check_in(biz_id: str, entry_id: str, family: List[Dict[str, Any]], chosen: List[str],
             where: str) -> Dict[str, List[str]]:
    """Make the record say what the member chose for their family: the
    ticked people counted ("self" at church, "online" watching), the
    unticked ones not, by the member's own phone. A check-in someone else
    made (the door, the kiosk's parent, a station) is left alone either way.
    Raises 503 when a write fails, so the page says try again."""
    method = "online" if where == "online" else "self"
    want = {str(c) for c in chosen} & {p["id"] for p in family}
    if not want:
        raise HTTPException(400, "Tick at least one person")
    got = marks(biz_id, entry_id, [p["id"] for p in family])
    if got is None:
        raise HTTPException(503, "Check-in couldn’t be read. Try again in a moment.")
    out: Dict[str, List[str]] = {"counted": [], "kept": [], "removed": []}
    for p in family:
        row = got.get(p["id"])
        if p["id"] in want:
            if row is None:
                if not _insert(biz_id, entry_id, p, method):
                    raise HTTPException(503, "That didn’t save. Try again in a moment.")
                out["counted"].append(p["name"])
            elif row.get("method") in MINE and row.get("method") != method:
                ok = sb_clients.sb_patch_as_service(
                    f"/attendance?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz_id)}", {"method": method})
                if not ok and ok != []:
                    raise HTTPException(503, "That didn’t save. Try again in a moment.")
                out["counted"].append(p["name"])
            elif row.get("method") in MINE:
                out["counted"].append(p["name"])
            else:
                out["kept"].append(p["name"])
        elif row is not None and row.get("method") in MINE:
            if not sb_clients.sb_delete_as_service(
                    f"/attendance?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz_id)}"):
                raise HTTPException(503, "That didn’t save. Try again in a moment.")
            out["removed"].append(p["name"])
    if method == "self":
        # They were here today (the record shows when someone was last in,
        # as a check-in at the door does).
        ids = [p["id"] for p in family if p["id"] in want]
        try:
            sb_clients.sb_patch_as_service(
                f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({','.join(_q(i) for i in ids)})",
                {"last_interaction": _iso(_now())})
        except Exception:
            logger.info("check-in: last_interaction stamp skipped", exc_info=True)
    return out


def count_kids_parent(biz_id: str, entry_id: str, adult: Dict[str, Any]) -> bool:
    """The parent who checked children in at the self kiosk was here too.
    Best-effort: a failure here never touches the children's check-in."""
    try:
        if not adult or not adult.get("id") or not _UUID.match(str(entry_id or "")):
            return False
        got = marks(biz_id, entry_id, [str(adult["id"])])
        if got is None or got:
            return bool(got)
        return _insert(biz_id, entry_id, {"id": str(adult["id"]), "name": adult.get("name")}, "kids_parent")
    except Exception:
        logger.warning("kids kiosk: counting the parent failed", exc_info=True)
        return False


# ─── the office ───────────────────────────────────────────────────────

def counts(biz_id: str, entry_id: str) -> Optional[Dict[str, int]]:
    rows = _rows(f"/attendance?business_id=eq.{_q(biz_id)}&entry_id=eq.{_q(entry_id)}&select=method&limit=5000")
    if rows is None:
        return None
    out = {"phone": 0, "kids_parents": 0, "online": 0, "office": 0}
    for r in rows:
        m = r.get("method")
        key = {"self": "phone", "kids_parent": "kids_parents", "online": "online"}.get(m, "office")
        out[key] += 1
    out["total"] = sum(out.values())
    return out


def overview(biz: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """GET /church/checkin: the settings, the member link, this week's
    service and (when it has an occasion) how it has been counted."""
    st = settings(biz)
    if st is None:
        raise HTTPException(503, "Check-in couldn’t be read. Try again in a moment.")
    w = window(st, now)
    occ = (ensure_occasion(str(biz["id"]), st, w["day"]) if st["enabled"]
           else find_occasion(str(biz["id"]), w["day"]) or None)
    import church_follow_up as cfu
    origin = cfu.site_origin(str(biz["id"]))
    rooms = _roster(str(biz["id"]))
    return {
        "settings": {k: st[k] for k in DEFAULTS} | {"saved": st["saved"]},
        "member_url": f"{origin}/here" if origin else "",
        "has_room": bool(rooms),
        "next": {"day": w["day"].isoformat(), "weekday": w["weekday"], "start": clock(w["start"]),
                 "opens": clock(w["opens"]), "closes": clock(w["closes"]), "open": w["open"]},
        "occasion": occ or None,
        "counts": counts(str(biz["id"]), occ["id"]) if occ else None,
    }


async def sweep(now: Optional[datetime] = None) -> Dict[str, int]:
    """Hourly: from two days before, each church's coming service has its
    occasion, so the Kids kiosk and Attendance find it on Sunday morning."""
    import asyncio
    now = now or _now()
    rows = await asyncio.to_thread(_rows, "/church_checkin_settings?enabled=is.true&select=*&limit=1000")
    made = 0
    for r in rows or []:
        try:
            st = dict(DEFAULTS, **{k: r[k] for k in DEFAULTS if r.get(k) is not None})
            w = window(st, now)
            if now >= w["start"] - timedelta(days=2):
                if await asyncio.to_thread(ensure_occasion, str(r["business_id"]), st, w["day"]):
                    made += 1
        except Exception:
            logger.warning("check-in sweep failed for a church", exc_info=True)
    return {"ready": made}
