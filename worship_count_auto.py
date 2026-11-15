# worship_count_auto.py — the countdown that starts by itself (ChurchSavvy,
# 2026-11-14; Kevin: "countdown clock should be a clock that can be started
# either we start or a pre service clock starts it that a person can set").
#
# A church keeps up to six times a week in its look (worship_show.
# clean_count_look): "Sundays 10:15, 15 minutes, every screen". Every minute,
# on the scheduler's leader, sweep_tick puts each one up at its time on the
# church's own clock, even when nobody has opened the booth: it writes the live
# state (worship_live) the booth writes, so every screen has it within 15
# seconds (a waiting screen re-reads the row; the booth's poll checks it every
# few seconds), marked `auto` so the booth says "Started by itself at 10:15".
# The booth can hold it, add time, or move on, as with any countdown.
#
# WHAT GOES UP: an on-the-spot countdown (adhoc, kind countdown) counting to
# the time plus its minutes, shown where the time says (every screen, the room
# only, or online only). It wears the plan's countdown when the service nearest
# its end has one (its design, words, welcome line, what happens at zero, the
# call to the stage); otherwise the church's own countdown from its look.
#
# ONCE: a time goes up once a day. The day it went up is claimed in the look's
# row before anything is written (a compare-and-set on updated_at, so of two
# copies of the server only one claims it), and a look saved from a page keeps
# the claim (worship_show_router.save_look).
#
# NEVER OVER A BOOTH THAT IS RUNNING SOMETHING (busy): it goes up over nothing,
# off air, the logo, a welcome loop, or a countdown that ended. It leaves alone
# a countdown still counting or held, and anything else (a song, a passage, a
# sermon point, a picture, words cleared, black: pressed on purpose, to hide
# something) the booth pressed in the last QUIET_MINUTES. The live row is written only if nobody pressed between
# the check and the write (a compare-and-set on its rev).
#
# Times are tried for WINDOW_MINUTES after they come (a late tick, a deploy);
# a time skipped because the booth was busy is tried again inside that window
# and not after. Reads that fail skip the church this minute, never guess (a
# zone that can't be read never falls back to UTC here). A sample church's
# screens show nothing, so its times never go up. CHURCHSAVVY_SUNDAY_TOOLS=off
# or ChurchSavvy off (WORSHIP_SONGS=off) stops them all.
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote

import sb_clients
import worship_show as wsh

WINDOW_MINUTES = 3
QUIET_MINUTES = 30
# A countdown whose time passed this long ago has ended: the next one may replace it.
ENDED_MINUTES = 2
# A plan counts as the time's service when it starts within this of the countdown's end.
SERVICE_NEAR_MINUTES = 45
ZONE_SECONDS = 1800

_ZONES: Dict[str, Tuple[float, Any]] = {}


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat()


def _when(v: Any) -> Optional[datetime]:
    if not isinstance(v, str) or not v:
        return None
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def week_day(local: datetime) -> int:
    """The day of the week as the screens count it: 0 is Sunday."""
    return (local.weekday() + 1) % 7


def due(times: List[Dict[str, Any]], local_now: datetime) -> Iterator[Tuple[Dict[str, Any], datetime]]:
    """Each time switched on whose moment is now (or came in the last WINDOW_MINUTES),
    with that moment on the church's clock."""
    day = week_day(local_now)
    for t in times:
        if not t.get("on") or day not in (t.get("days") or []):
            continue
        h, m = (int(x) for x in t["at"].split(":"))
        start = local_now.replace(hour=h, minute=m, second=0, microsecond=0)
        if start <= local_now < start + timedelta(minutes=WINDOW_MINUTES):
            yield t, start


def busy(state: Any, now: datetime, items: Optional[Dict[str, Dict[str, Any]]] = None,
         starts_at: Optional[str] = None) -> Optional[str]:
    """Why the screens are the booth's right now, or None when the countdown may go
    up. `items` are the items of the service the state names (by id), when known,
    and `starts_at` its start (a planned countdown counts to it)."""
    if not isinstance(state, dict) or not state:
        return None
    mode = state.get("mode") or "show"
    if mode == "logo":
        return None  # the screens rest on the logo: waiting
    adhoc = state.get("adhoc") if isinstance(state.get("adhoc"), dict) and state["adhoc"].get("slides") else None
    if not adhoc and not state.get("item_id") and mode != "black":
        return None  # nothing of a plan named: off air, or a fresh church
    item = None if adhoc else (items or {}).get(state.get("item_id"))
    count = state.get("count") if isinstance(state.get("count"), dict) else None
    slide_to: Any = None
    countdown = False
    if adhoc and adhoc.get("kind") == "countdown":
        countdown, slide_to = True, (adhoc["slides"][0] or {}).get("to")
    elif item and item.get("kind") == "countdown":
        countdown, slide_to = True, item.get("to") or starts_at
    if countdown and mode != "black":
        if count and count.get("held") is not None:
            return "a countdown is up and held"
        to = _when((count or {}).get("to") or slide_to)
        if to is not None and to > now - timedelta(minutes=ENDED_MINUTES):
            return "a countdown is already counting"
        return None
    if item and item.get("kind") == "loop" and mode != "black":
        return None  # a welcome loop waits for the countdown
    pressed = _when(state.get("at") or state.get("since"))
    if pressed and now - pressed < timedelta(minutes=QUIET_MINUTES):
        return "the booth pressed something in the last %d minutes" % QUIET_MINUTES
    return None


def count_slide(service: Optional[Dict[str, Any]], church: Dict[str, Any], to: str) -> Dict[str, Any]:
    """The countdown's one slide: the plan's countdown when the service has one,
    else the church's own (its look), counting to `to`."""
    items = [i for i in ((service or {}).get("items") or []) if isinstance(i, dict)]
    planned = next((i for i in items if i.get("kind") == "countdown"), None)
    if planned:
        try:
            return wsh.clean_count_slide({**planned, "to": to})
        except ValueError:
            pass  # a planned countdown that no longer passes: the church's own
    # With no plan to move into, zero shows the logo rather than sitting at 0:00.
    plan = any(i.get("kind") != "section" for i in items)
    return wsh.clean_count_slide({"to": to, "title": church.get("title"), "design": church.get("design"),
                                  "welcome": church.get("welcome"), "big_last": church.get("big_last"),
                                  "zero": "next" if plan else "logo"})


def zone_for(biz: str):
    """The church's clock, the lobby's and the announcements' (business_marketing.
    business_tz), kept for half an hour. None when it can't be read: no guessing."""
    hit = _ZONES.get(biz)
    if hit and time.monotonic() - hit[0] < ZONE_SECONDS:
        return hit[1]
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{_q(biz)}&select=id,owner_id,availability:settings->availability&limit=1")
    if not isinstance(rows, list) or not rows:
        return None
    try:
        import business_marketing
        zone = business_marketing.business_tz(rows[0])
    except Exception as e:  # noqa: BLE001 — the owner's profile couldn't be read: try next minute
        print(f"[worship_count_auto] {biz[:8]}: no time zone this minute ({e})", flush=True)
        return None
    _ZONES[biz] = (time.monotonic(), zone)
    return zone


def _service_near(biz: str, to: datetime) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """(read, the service starting nearest the countdown's end, within SERVICE_NEAR_MINUTES)."""
    lo, hi = to - timedelta(minutes=SERVICE_NEAR_MINUTES), to + timedelta(minutes=SERVICE_NEAR_MINUTES)
    rows = sb_clients.sb_get_as_service(
        f"/worship_services?business_id=eq.{_q(biz)}&archived_at=is.null&is_template=eq.false"
        f"&starts_at=gte.{_q(_iso(lo))}&starts_at=lte.{_q(_iso(hi))}&select=id,title,starts_at,items"
        f"&order=starts_at.asc&limit=5")
    if rows is None:
        return False, None
    near = sorted((r for r in rows if _when(r.get("starts_at"))), key=lambda r: abs((_when(r["starts_at"]) - to).total_seconds()))
    return True, (near[0] if near else None)


def _items_of(biz: str, sid: Any) -> Tuple[bool, Dict[str, Dict[str, Any]], Optional[str]]:
    rows = sb_clients.sb_get_as_service(
        f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&select=items,starts_at&limit=1")
    if rows is None:
        return False, {}, None
    row = rows[0] if rows else {}
    return True, {i.get("id"): i for i in (row.get("items") or []) if isinstance(i, dict)}, row.get("starts_at")


def _claim(biz: str, tid: str, day: str, times: List[Dict[str, Any]], now: datetime) -> bool:
    """Mark the time as up today in the look's row, only if the row hasn't changed since
    it was read (so of two copies of the server, one claims it). False: claimed already,
    or moved under us (the next minute looks again)."""
    rows = sb_clients.sb_get_as_service(f"/worship_settings?business_id=eq.{_q(biz)}&select=look,updated_at&limit=1")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0].get("look"), dict):
        return False
    look, stamp = rows[0]["look"], rows[0].get("updated_at")
    fired = look.get(wsh.FIRED_KEY) if isinstance(look.get(wsh.FIRED_KEY), dict) else {}
    if fired.get(tid) == day or not stamp:
        return False
    keep = {t["id"] for t in times}
    fired = {k: v for k, v in fired.items() if k in keep}
    fired[tid] = day
    got = sb_clients.sb_patch_as_service(
        f"/worship_settings?business_id=eq.{_q(biz)}&updated_at=eq.{_q(stamp)}&select=business_id",
        {"look": {**look, wsh.FIRED_KEY: fired}, "updated_at": _iso(now)})
    return isinstance(got, list) and bool(got)


def _put_live(biz: str, state: Dict[str, Any], prev: Optional[Tuple[int, Dict[str, Any]]], now: datetime) -> Optional[int]:
    """Write the live row only if nobody pressed since it was read (its rev)."""
    rev = max(int(time.time() * 1000), (prev[0] + 1) if prev else 0)
    row = {"service_id": state.get("service_id"), "state": state, "rev": rev, "updated_at": _iso(now)}
    if prev:
        got = sb_clients.sb_patch_as_service(f"/worship_live?business_id=eq.{_q(biz)}&rev=eq.{prev[0]}&select=rev", row)
    else:
        # No row yet: an insert, which a row made in between refuses.
        got = sb_clients.sb_post_as_service("/worship_live?select=rev", {"business_id": biz, **row})
    if not isinstance(got, list) or not got:
        return None
    try:
        # This copy's own screens hear it at once; every other copy reads the row.
        import worship_show_router
        worship_show_router.HUB.publish(biz, rev, state)
    except Exception:  # noqa: BLE001 — the row is what counts
        pass
    return rev


def _live(biz: str) -> Tuple[bool, Optional[Tuple[int, Dict[str, Any]]]]:
    rows = sb_clients.sb_get_as_service(f"/worship_live?business_id=eq.{_q(biz)}&select=rev,state&limit=1")
    if rows is None:
        return False, None
    if not rows:
        return True, None
    return True, (int(rows[0].get("rev") or 0), rows[0].get("state") if isinstance(rows[0].get("state"), dict) else {})


def start_one(biz: str, t: Dict[str, Any], start: datetime, church: Dict[str, Any],
              times: List[Dict[str, Any]], now: datetime) -> str:
    """Put one time's countdown up for one church: 'up', or why not."""
    ends = start + timedelta(minutes=t["minutes"])
    ok, live = _live(biz)
    if not ok:
        return "unread"
    state = (live or (0, {}))[1]
    items: Dict[str, Dict[str, Any]] = {}
    starts_at = None
    if state.get("service_id") and state.get("item_id") and not state.get("adhoc"):
        ok, items, starts_at = _items_of(biz, state["service_id"])
        if not ok:
            return "unread"
    why = busy(state, now, items, starts_at)
    if why:
        return "busy"
    ok, service = _service_near(biz, ends.astimezone(timezone.utc))
    if not ok:
        return "unread"
    try:
        slide = count_slide(service, church, _iso(ends))
        at = _iso(now)
        new = wsh.clean_live({
            "service_id": (service or {}).get("id"), "item_id": None, "slide": 0, "mode": "show", "show_key": "",
            "adhoc": {"kind": "countdown", "title": slide["title"], "show": t["where"], "slides": [slide]},
            "auto": {"id": t["id"], "at": t["at"]}, "since": at})
    except ValueError as e:
        print(f"[worship_count_auto] {biz[:8]}: the countdown for {t['at']} doesn't pass ({e})", flush=True)
        return "bad"
    new["at"] = at
    wsh.carry_log(state, new, at)
    # A lower third the booth left up stays over the countdown (2026-11-15).
    wsh.carry_third(state, new)
    if not _claim(biz, t["id"], start.date().isoformat(), times, now):
        return "claimed"
    rev = _put_live(biz, new, live, now)
    if rev is None:
        # The booth pressed in between (or the write failed): it's the booth's now. The day
        # stays claimed, so this time doesn't come back over whatever the booth put up.
        print(f"[worship_count_auto] {biz[:8]}: {t['at']} claimed but the screens moved first; left to the booth", flush=True)
        return "moved"
    print(f"[worship_count_auto] {biz[:8]}: up by itself at {t['at']} for {t['minutes']} min ({t['where']}), rev {rev}", flush=True)
    return "up"


def _enabled() -> bool:
    import worship_router
    if worship_router.mode() == "off":
        return False
    return worship_router.sunday_tools_mode() != "off"


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every minute: each church's countdown times that have come, put up once."""
    stats: Dict[str, int] = {"churches": 0, "up": 0, "busy": 0, "claimed": 0, "moved": 0, "unread": 0, "bad": 0}
    if not _enabled():
        stats["off"] = 1
        return stats
    now = now or datetime.now(timezone.utc)
    rows = sb_clients.sb_get_as_service(
        "/worship_settings?select=business_id,church:look->countdown&look->countdown->times=not.is.null&limit=2000")
    if not isinstance(rows, list):
        print("[worship_count_auto] the churches' countdown times couldn't be read this minute", flush=True)
        stats["unread"] += 1
        return stats
    import sample_church
    for row in rows:
        biz = str(row.get("business_id") or "")
        if not biz or not isinstance(row.get("church"), dict) or not row["church"].get("times"):
            continue
        if sample_church.skip_id(biz):
            continue
        try:
            church = wsh.clean_count_look(row.get("church"))
        except ValueError:
            continue  # an older shape that no longer passes: nothing goes up by itself
        times = church["times"]
        if not any(t["on"] for t in times):
            continue
        stats["churches"] += 1
        zone = zone_for(biz)
        if zone is None:
            stats["unread"] += 1
            continue
        local = now.astimezone(zone)
        for t, start in due(times, local):
            try:
                got = start_one(biz, t, start, church, times, now)
            except Exception as e:  # noqa: BLE001 — one church never stops the rest
                print(f"[worship_count_auto] {biz[:8]}: {t.get('at')} failed: {e}", flush=True)
                got = "unread"
            stats[got] = stats.get(got, 0) + 1
            if got == "up":
                break  # one countdown up at a time
    return stats
