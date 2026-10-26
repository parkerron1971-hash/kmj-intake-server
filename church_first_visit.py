"""church_first_visit.py — a first-time check-in starts a welcome follow-up.

Kevin, 2026-10-26, on the "who sees what" plan for churches: "yes, a
first-time check-in starts a welcome follow-up." Until now a church's
follow-ups (church_follow_up) started only from cards and forms, so
someone who walked in and was checked in for the first time never reached
the welcome lead's Lead tab. They sat on the First-time guests list
(church_reads.first_time_guests) until somebody noticed.

Two places write a first check-in, and each is handed on here:

    the kids desk ............... kids_checkin.do_checkin (a team seat, a
      after_kids_checkin          station, the self kiosk): one family's
                                  children into one occasion. The server
                                  writes it, so the hook runs right there,
                                  in the background.
    the office's First time ..... Attendance writes attendance with
      sweep                       first_time straight from the app, so the
                                  server never sees the write; the
                                  follow-up sweep (every 10 minutes) picks
                                  up the last day's.

A member's own phone check-in (church_checkin) and online "I'm here" are
members the church already has (the member page makes no one), never a
first visit, so neither starts one.

When a family is new
    the office's First time ..... the office said so. Still skipped when
                                  any of the family was checked in at an
                                  earlier occasion.
    the kids desk ............... nobody says so, so it is read: the
                                  family and the adult who brought them
                                  were both added in the last 7 days, no
                                  child of theirs was checked in before,
                                  and none of its adults was at another
                                  occasion. A family the office typed in
                                  from its old records is not new on its
                                  first Sunday in the app.

One follow-up per family per first visit, for the adult (whoever dropped
the children off, else the family's parent), never one per child:
church_follow_up.on_first_check_in, with the family's own receipt
(first-visit:h:<family> or first-visit:c:<person>) that the unique source
index keeps once however often a check-in is sent. Anyone in the family
already in follow-up keeps that one. It is routed like a connect card:
the welcome role, else the senior role, else the office.

Switched by CHURCH_AREAS: only when church_areas.mode() is "on" (a
Thursday switch-on). Best effort: nothing here blocks, slows or fails a
check-in, and a failure is printed (only print() reaches Railway's logs).
Reads and writes go through the service role, pinned to one business.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import church_areas
import church_follow_up
import sb_clients

# A family the kids desk checks in counts as new when it, and the adult
# who brought them, were added this recently.
NEW_FAMILY_DAYS = 7
# How far back the sweep looks for the office's First time check-ins, and
# how many it reads at once.
SWEEP_HOURS = 24
SWEEP_LIMIT = 1000

_RELATION_RANK = {"parent": 0, "guardian": 0, "grandparent": 1, "other": 2}


def _q(value: Any) -> str:
    return quote(str(value), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    # No "+00:00": a raw "+" in a PostgREST query string reads as a space.
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _say(what: str, business_id: Any = "", err: Optional[BaseException] = None) -> None:
    # Ids cut short and the error's type only: no names or bodies in the log.
    tail = f" ({type(err).__name__})" if err else ""
    print(f"[church_first_visit] {what} business={str(business_id)[:8]}{tail}", flush=True)


def on() -> bool:
    """Only when the church areas are switched on for everyone."""
    try:
        return church_areas.mode() == "on"
    except Exception:
        return False


def _church(biz: str) -> bool:
    rows = _rows(f"/businesses?id=eq.{_q(biz)}&select=id,type&limit=1")
    return bool(rows) and church_follow_up.is_church(rows[0])


def line_for(occasion: str, kids: int) -> str:
    """The line the leader reads under First check-in."""
    where = f"First time at {occasion}" if occasion else "First time"
    if kids:
        return f"{where} · {kids} {'kid' if kids == 1 else 'kids'} checked in"
    return where


def _guardian(adults: List[Dict[str, Any]], adult_id: Optional[str]) -> str:
    """The adult who brought them, else the family's parent or guardian
    (the first one added), else whoever the family has."""
    ids = {str(a["contact_id"]) for a in adults}
    if adult_id and str(adult_id) in ids:
        return str(adult_id)
    best = sorted(adults, key=lambda a: (_RELATION_RANK.get(a.get("relationship") or "", 3),
                                         str(a.get("created_at") or ""), str(a["contact_id"])))
    return str(best[0]["contact_id"])


def _kids_here_if_first(biz: str, entry_id: str, household_id: Optional[str],
                        family: List[str]) -> Optional[int]:
    """How many of the family's children are checked in at this occasion,
    or None when the family has been before (a child of theirs checked in,
    or one of its adults at, any other occasion) or a read failed. A read
    that failed never reads as "new"."""
    kids: List[Dict[str, Any]] = []
    if household_id:
        got = _rows(f"/child_checkins?business_id=eq.{_q(biz)}&household_id=eq.{_q(household_id)}"
                    "&select=entry_id&limit=500")
        if got is None or any(str(k.get("entry_id")) != str(entry_id) for k in got):
            return None
        kids = got
    if family:
        seen = _rows(f"/attendance?business_id=eq.{_q(biz)}&contact_id=in.({','.join(_q(i) for i in family)})"
                     f"&entry_id=neq.{_q(entry_id)}&select=id&limit=1")
        if seen is None or seen:
            return None
    return len(kids)


# ─── The kids desk ────────────────────────────────────────────────────

def _spawn(fn, *args) -> None:
    """In the background: the check-in has already answered."""
    def run() -> None:
        try:
            fn(*args)
        except Exception as e:  # never reaches the check-in
            _say("welcome failed", args[0] if args else "", e)

    threading.Thread(target=run, daemon=True, name="church-first-visit").start()


def after_kids_checkin(business_id: str, entry_id: str, occasion: str, household_id: str,
                       adult_id: Optional[str]) -> None:
    """kids_checkin.do_checkin's hook, once new children are saved (every
    way in: a team seat, a station, the self kiosk). Returns at once and
    never raises; the reading happens in the background."""
    try:
        if not on():
            return
        _spawn(welcome_kids, str(business_id), str(entry_id), str(occasion or ""), str(household_id),
               str(adult_id) if adult_id else None)
    except Exception as e:
        _say("welcome not started", business_id, e)


def welcome_kids(business_id: str, entry_id: str, occasion: str, household_id: str,
                 adult_id: Optional[str], now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """A family's children were checked in: a welcome follow-up for their
    adult when the family is new. The follow-up row, or None."""
    biz = str(business_id)
    if not on():
        return None
    # Most families have been before: the family's age stops those first.
    since = (now or _now()) - timedelta(days=NEW_FAMILY_DAYS)
    homes = _rows(f"/households?id=eq.{_q(household_id)}&business_id=eq.{_q(biz)}&select=id,created_at&limit=1")
    if not homes or not _recent(homes[0].get("created_at"), since) or not _church(biz):
        return None
    adults = _rows(f"/household_adults?household_id=eq.{_q(household_id)}&business_id=eq.{_q(biz)}"
                   "&select=contact_id,relationship,created_at&limit=20")
    if not adults:
        return None  # no adult on the family: nobody to follow up with
    guardian = _guardian(adults, adult_id)
    person = _rows(f"/contacts?id=eq.{_q(guardian)}&business_id=eq.{_q(biz)}&select=id,created_at&limit=1")
    if not person or not _recent(person[0].get("created_at"), since):
        return None
    family = sorted({str(a["contact_id"]) for a in adults})
    kids = _kids_here_if_first(biz, entry_id, household_id, family)
    if kids is None:
        return None
    row = church_follow_up.on_first_check_in(biz, guardian, family_key=f"h:{household_id}",
                                             said=line_for(occasion, kids), family_ids=family)
    if row:
        _say("welcome follow-up started (kids desk)", biz)
    return row


def _recent(ts: Any, since: datetime) -> bool:
    at = _parse(ts)
    return bool(at and at >= since)


# ─── The office's First time ──────────────────────────────────────────

async def sweep(now: Optional[datetime] = None) -> int:
    """The last day's First time check-ins (attendance.first_time, written
    from the app): a welcome follow-up for each new family. Run by the
    follow-up sweep. How many were started."""
    import asyncio
    if not on():
        return 0
    try:
        return await asyncio.to_thread(_sweep, now or _now())
    except Exception as e:
        _say("sweep failed", "", e)
        return 0


def _sweep(now: datetime) -> int:
    since = now - timedelta(hours=SWEEP_HOURS)
    rows = _rows(f"/attendance?first_time=is.true&contact_id=not.is.null&checked_in_at=gte.{_q(_iso(since))}"
                 f"&select=id,business_id,entry_id,contact_id,checked_in_at&order=checked_in_at.asc&limit={SWEEP_LIMIT}")
    if not rows:
        return 0
    bizs = sorted({str(r["business_id"]) for r in rows})
    kinds = _rows(f"/businesses?id=in.({','.join(_q(b) for b in bizs)})&select=id,type")
    if kinds is None:
        return 0
    churches = sorted(str(b["id"]) for b in kinds if church_follow_up.is_church(b))
    rows = [r for r in rows if str(r["business_id"]) in churches]
    if not rows:
        return 0
    # Each person's family, and the first visits already handed on, in one
    # read each, so a quiet sweep costs three reads whatever the window holds.
    people = sorted({str(r["contact_id"]) for r in rows})
    links = _rows(f"/household_adults?business_id=in.({','.join(_q(b) for b in churches)})"
                  f"&contact_id=in.({','.join(_q(p) for p in people)})"
                  "&select=household_id,contact_id,business_id&limit=1000")
    done = _rows(f"/church_follow_ups?business_id=in.({','.join(_q(b) for b in churches)})"
                 f"&source_event=like.first-visit:*&created_at=gte.{_q(_iso(since - timedelta(days=1)))}"
                 "&select=business_id,source_event&limit=2000")
    if links is None or done is None:
        return 0
    home_of: Dict[tuple, str] = {}
    for link in sorted(links, key=lambda l: str(l["household_id"])):
        home_of.setdefault((str(link["business_id"]), str(link["contact_id"])), str(link["household_id"]))
    handed = {(str(d["business_id"]), str(d.get("source_event") or "")) for d in done}
    started = 0
    for r in rows:
        biz, cid = str(r["business_id"]), str(r["contact_id"])
        home = home_of.get((biz, cid))
        key = f"h:{home}" if home else f"c:{cid}"
        if (biz, f"first-visit:{key}") in handed:
            continue
        handed.add((biz, f"first-visit:{key}"))  # a second adult of the same family, same sweep
        try:
            if _welcome_checked_in(biz, str(r["entry_id"]), cid, home, key):
                started += 1
        except Exception as e:
            _say("welcome failed (first time)", biz, e)
    if started:
        _say(f"{started} welcome follow-up(s) started (first time)", "")
    return started


def _welcome_checked_in(biz: str, entry_id: str, contact_id: str, household_id: Optional[str],
                        key: str) -> Optional[Dict[str, Any]]:
    family = [contact_id]
    if household_id:
        adults = _rows(f"/household_adults?household_id=eq.{_q(household_id)}&business_id=eq.{_q(biz)}"
                       "&select=contact_id&limit=20")
        if adults is None:
            return None
        family = sorted({contact_id} | {str(a["contact_id"]) for a in adults})
    kids = _kids_here_if_first(biz, entry_id, household_id, family)
    if kids is None:
        return None
    return church_follow_up.on_first_check_in(biz, contact_id, family_key=key,
                                             said=line_for(_occasion(biz, entry_id), kids), family_ids=family)


def _occasion(biz: str, entry_id: str) -> str:
    rows = _rows(f"/module_entries?id=eq.{_q(entry_id)}&business_id=eq.{_q(biz)}&select=data&limit=1")
    data = (rows[0].get("data") or {}) if rows else {}
    return " ".join(str(data.get("title") or data.get("name") or "").split())[:80]
