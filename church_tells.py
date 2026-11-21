"""church_tells.py — the office's missing tells: the next person hears it's
their turn.

Love City's connection map (2026-11-21) checked every hand-off between the
office's people. Several worked on paper but never told the next person:
a count closed and the treasurer wasn't told, a sermon draft waited with
nobody told, a room request from an office login reached no one, a leader's
yes never reached whoever runs background checks. The pastor asked for those
tells to be fixed.

One sweep on the worker (every 30 minutes) asks each FINDER what just
happened at each church, and tells whoever does that job:

    finder(church, now) -> [Item]       church: the businesses row
                                         (id, name, type, settings, owner_id)

An Item names a duty (church_duties.CATALOG) or explicit logins, a key that
makes it one tell for good (claimed in businesses.settings.church_tells),
and the words. Who hears a duty's item (recipients): the Manager logins that
hold it; else the church's Admin logins; else the owner. Never the login who
did the thing (Item.actor). Several items for one login in one sweep become
one notice. The tell is church_schedule_tell.to_login: a push to the office
app and an email.

Rules every finder keeps:
  * read as the server, only this church's rows, only what just happened
    (a short look back, so switching it on never floods anyone);
  * a lock screen line never carries an amount or a private note;
  * a read that fails returns [] (the next sweep tries again), never raises.

Switch CHURCH_TELLS = off | owner | on (default owner: only the platform's
own church). Quiet hours hold a church's tells until they're over. A sample
church is never told anything.

Known limit: church_tells is not one of business_settings.SERVER_KEYS (that
list is pinned to a SQL list the owner applies by hand), so a whole-settings
write from an old copy could drop the stamps; the worst case is one tell
sent twice.
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

import sb_clients

SWITCH = "CHURCH_TELLS"
KEY = "church_tells"            # businesses.settings[KEY] = {item key: when it was told}
KEEP_DAYS = 45                  # stamps older than this are dropped when the next one is written
MAX_PER_LOGIN = 6               # lines in one notice's email; the push says how many
BIZ_FIELDS = "id,name,type,settings,owner_id"

# Each finder lives in its own module, so the tells can be built side by side.
# A module that isn't there yet is skipped.
FINDERS: Sequence[str] = (
    "church_tells_money:count_closed",       # a count closed -> the treasurer (deposit)
    "church_tells_money:payback_asked",      # a new pay-back request -> the treasurer (pay)
    "church_tells_rooms:room_asked",         # a room request -> the rooms holder
    "church_tells_rooms:room_answered",      # the answer -> whoever asked
    "church_tells_rooms:leader_said_yes",    # a leader's yes -> background checks
    "church_tells_sunday:sermon_draft",      # a sermon draft is waiting -> sermons
    "church_tells_sunday:count_missing",     # Sunday's count isn't in -> attendance
    "church_tells_sunday:flyer_needed",      # an event has no flyer -> flyers
)


@dataclass
class Item:
    """One thing a person should hear about."""
    key: str                            # unique for good, e.g. "count:<id>"
    title: str                          # the push title, <= 80 characters
    line: str                           # the push body and the email's line, <= 160
    duty: Optional[str] = None          # who hears: this duty's recipients ...
    to: List[str] = field(default_factory=list)   # ... or these logins
    actor: Optional[str] = None         # the login who did it: never told


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


def mode() -> str:
    m = (os.environ.get(SWITCH) or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_for(church: Dict[str, Any]) -> bool:
    """The switch, a church, and never a sample church."""
    m = mode()
    if m == "off" or not church or not church.get("id"):
        return False
    try:
        import church_follow_up as cfu
        import member_asks
        import sample_church
        return (cfu.is_church(church) and member_asks._switch_open(m, church["id"])
                and not sample_church.skip(church))
    except Exception:  # noqa: BLE001 — a switch that can't be read is closed
        return False


def churches() -> List[Dict[str, Any]]:
    """The churches the sweep works for. [] when they can't be read."""
    if mode() == "off":
        return []
    if mode() == "owner":
        import church_assignments as cas
        rows = sb_clients.sb_get_as_service(f"/businesses?owner_id=eq.{_q(cas._platform_owner_id())}"
                                            f"&select={BIZ_FIELDS}&limit=50")
    else:
        try:
            rows = sb_clients.sb_get_all_as_service(f"/businesses?select={BIZ_FIELDS}")
        except Exception:  # noqa: BLE001 — a page that failed: the next sweep
            rows = None
    if not isinstance(rows, list):
        print("[church_tells] the churches weren't read; next sweep", flush=True)
        return []
    return [b for b in rows if open_for(b)]


def _q(v: Any) -> str:
    from urllib.parse import quote
    return quote(str(v), safe="")


# ─── Who hears ────────────────────────────────────────────────────────

def recipients(church: Dict[str, Any], duty: str) -> Optional[List[str]]:
    """The Manager logins that hold this duty; else the Admin logins; else
    the owner. None when it can't be read (the item waits for the next sweep)."""
    import church_duties as cd
    biz = str(church["id"])
    try:
        managers = cd.manager_holders(biz, duty)
        if managers:
            return managers
        everyone = cd.holders_of(biz, duty)        # the owner first, then each Admin
    except Exception:  # noqa: BLE001 — a 503 or a duty this trunk doesn't know
        return None
    owner = str(church.get("owner_id") or "")
    admins = [u for u in everyone if u != owner]
    return admins or ([owner] if owner else [])


# ─── Told once ────────────────────────────────────────────────────────

def _stamps(church: Dict[str, Any]) -> Dict[str, str]:
    s = church.get("settings") if isinstance(church.get("settings"), dict) else {}
    got = s.get(KEY)
    return dict(got) if isinstance(got, dict) else {}


def told(church: Dict[str, Any], key: str) -> bool:
    return key in _stamps(church)


def _stamp(church: Dict[str, Any], keys: List[str], now: datetime) -> None:
    """Keep these keys as told (and drop stamps older than KEEP_DAYS)."""
    import business_settings
    stamps = _stamps(church)
    cutoff = _iso(now - timedelta(days=KEEP_DAYS))
    stamps = {k: v for k, v in stamps.items() if isinstance(v, str) and v >= cutoff}
    for k in keys:
        stamps[k] = _iso(now)
    got = business_settings.merge(church["id"], set={KEY: stamps})
    if got is None:
        print(f"[church_tells] {str(church['id'])[:8]}: the told stamps weren't kept", flush=True)
        return
    church["settings"] = got


# ─── The sweep ────────────────────────────────────────────────────────

def _finder(spec: str) -> Optional[Callable[[Dict[str, Any], datetime], List[Item]]]:
    mod, _, fn = spec.partition(":")
    try:
        return getattr(importlib.import_module(mod), fn)
    except (ImportError, AttributeError):
        return None


def _quiet(church: Dict[str, Any], now: datetime) -> bool:
    try:
        import member_push
        return bool(member_push.quiet_hour(church, now))
    except Exception:  # noqa: BLE001 — a clock nobody could read never holds a tell back
        return False


def _words(church: Dict[str, Any], items: List[Item]) -> Dict[str, str]:
    name = str(church.get("name") or "Your church").strip()
    if len(items) == 1:
        it = items[0]
        return {"title": it.title[:80], "body": it.line[:160], "subject": f"{name}: {it.title}"[:120],
                "text": it.line}
    shown = items[:MAX_PER_LOGIN]
    more = len(items) - len(shown)
    text = "\n".join(f"• {it.line}" for it in shown) + (f"\n…and {more} more in the app." if more else "")
    return {"title": f"{len(items)} things for you at {name}"[:80], "body": shown[0].line[:160],
            "subject": f"{name}: {len(items)} things for you"[:120], "text": text}


def _tell(church: Dict[str, Any], uid: str, items: List[Item], now: datetime) -> bool:
    import church_over as co
    import church_schedule_tell as cst
    w = _words(church, items)
    ref = f"tells-{items[0].key}-{uid}"[:200]
    try:
        got = cst.to_login(co.Church(church), uid, title=w["title"], body=w["body"], ref=ref,
                           subject=w["subject"], text=w["text"])
    except Exception:  # noqa: BLE001 — one login that fails never stops the next
        return False
    return bool(got.get("rang") or got.get("mailed"))


def run_church(church: Dict[str, Any], now: datetime, stats: Dict[str, int]) -> None:
    """One church's sweep: every finder, the new items, one notice a login."""
    items: List[Item] = []
    seen = set()
    for spec in FINDERS:
        fn = _finder(spec)
        if fn is None:
            continue
        try:
            found = fn(church, now) or []
        except Exception as e:  # noqa: BLE001 — one finder that fails never stops the others
            print(f"[church_tells] {str(church['id'])[:8]}: {spec} failed: {type(e).__name__}", flush=True)
            stats["failed"] = stats.get("failed", 0) + 1
            continue
        for it in found:
            if it.key in seen or told(church, it.key):
                continue
            seen.add(it.key)
            items.append(it)
    if not items:
        return
    by_login: Dict[str, List[Item]] = {}
    unread = set()
    for it in items:
        to = list(it.to) if it.to else (recipients(church, it.duty) if it.duty else [])
        if to is None:
            unread.add(it.key)
            continue
        for uid in dict.fromkeys(str(u) for u in to if u):
            if it.actor and uid == str(it.actor):
                continue
            by_login.setdefault(uid, []).append(it)
    done: Dict[str, bool] = {it.key: False for it in items}
    for uid, its in by_login.items():
        if _tell(church, uid, its, now):
            stats["told"] = stats.get("told", 0) + 1
            for it in its:
                done[it.key] = True
        else:
            stats["unsent"] = stats.get("unsent", 0) + 1
    # An item nobody needs to hear (the doer is the only holder) is kept as
    # told too, so it isn't looked at again.
    reached = {it.key for v in by_login.values() for it in v}
    nobody = {it.key for it in items if it.key not in reached and it.key not in unread}
    keep = [k for k, ok in done.items() if ok or k in nobody]
    if keep:
        _stamp(church, keep, now)
    stats["items"] = stats.get("items", 0) + len(items)


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every 30 minutes on the worker (kmj_intake_automation). A church that
    fails never stops the others. Quiet with the switch off."""
    stats: Dict[str, int] = {"churches": 0, "items": 0, "told": 0, "unsent": 0, "failed": 0, "quiet": 0}
    now = now or _now()
    for church in churches():
        if _quiet(church, now):
            stats["quiet"] += 1
            continue
        stats["churches"] += 1
        try:
            run_church(church, now, stats)
        except Exception as e:  # noqa: BLE001
            print(f"[church_tells] {str(church.get('id'))[:8]}: the sweep failed: {type(e).__name__}", flush=True)
            stats["failed"] += 1
    if stats["items"] or stats["failed"]:
        print(f"[church_tells] {stats}", flush=True)
    return stats


# ─── Shared bits for the finders ──────────────────────────────────────

def since(now: datetime, days: float) -> str:
    """A PostgREST-safe ISO stamp `days` back."""
    return _q(_iso(now - timedelta(days=days)))


def rows(path: str) -> List[Dict[str, Any]]:
    """A service read that is [] on any failure (the next sweep tries again)."""
    try:
        got = sb_clients.sb_get_as_service(path)
    except Exception:  # noqa: BLE001
        return []
    return got if isinstance(got, list) else []


def q(v: Any) -> str:
    return _q(v)
