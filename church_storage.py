"""
church_storage.py — a church plan's storage allowance: the meter, the
14-day rule for a recording made while full, and the warnings.

Kevin approved this on 2026-11-17 ("build"). A service recorded through the
stream relay is kept until someone deletes it, and a two-hour service is
about 6 GB (a real test ran at 7.1 Mbps, about 3 GB an hour). Instead of a
time rule, each church plan includes a fixed amount of storage for all of
its files (pricing_config.church_storage_gb: Small 100 GB, Growing 250 GB,
Established 500 GB, Large 1 TB; 1 GB = 1024^3 bytes). When it is full, the
church decides what to delete. We never choose for them, with one rule they
are warned about three times: a recording made while the church is already
over its allowance is kept 14 days, and deleted after that only if the
church is still over, the recording isn't a published sermon, and all three
warnings went out.

RECORDING IS NEVER STOPPED
--------------------------
Nothing here refuses a stream, a recording or going live. recording_ended
runs after the relay's end is fully saved (stream_relay_router.finalize)
and never raises.

WHAT IS COUNTED (used)
----------------------
  recordings  stream_sessions.bytes for the church's sessions not removed
              (the media bucket, private).
  classes     academy_live_sessions.recording_bytes for the church's
              courses (the class recordings' own bucket). Shown as 0 when
              it can't be read.
  files       every Supabase Storage object whose path starts with
              "<business_id>/" (the convention nearly every bucket follows;
              account_lifecycle deletes by the same prefix), summed by the
              database function church_storage_files_bytes, since PostgREST
              doesn't expose storage.objects. Before
              APPLY-2026-11-17-church-storage.sql it isn't there:
              files_counted is false and files show as 0.
Every read is paged (sb_get_all_as_service) past PostgREST's 1,000 rows.
A read that fails decides nothing: with the files or the class recordings
unread, the meter is incomplete (measure's `complete`), and that run
neither holds, warns, releases, removes nor re-arms anything for the church
(counted as 0 they would look like room, and a released hold is never held
again). A failed read of the recordings or the sermons skips the church.

A business not on a church plan (church_texts.church_plan_of: the comp tier,
or the Stripe PRICE id businesses.subscription_plan holds) has no allowance
(allowance_bytes None) and nothing here touches it.

MORE ROOM, BOUGHT (2026-11-17)
------------------------------
A church can buy blocks of 100 GB at $5 a month each (church_billing's
extra storage, an item on its subscription, the count kept in
businesses.settings.extra_storage as extra_logins is). extra_bytes adds
them to the allowance here and nowhere else. A count that can't be read
(church_billing.extra_storage_blocks None) is never 0: with a plan's
allowance in play it makes the meter incomplete, like unread files. The
page's extra_offer says what one block is and whether this login may buy
it; the warnings say "Make room or add storage" once the price is set
(add_storage_sold).

THE SWITCH
----------
CHURCH_STORAGE: off (the default) | owner (the platform owner's churches
only, member_asks.platform_church) | on. Off for a business: the storage
page answers {"enabled": false}, a delete is a 404, no warnings, no
removals, and the plan cards don't mention storage (those wait for "on").
Warnings and removals also wait for the key that may delete
(STREAM_R2_WRITE_ACCESS_KEY_ID / _SECRET_ACCESS_KEY): a warning that says
"make room" is only sent when the church can.

THE WARNINGS (chief_notifications, type storage_allowance, like the
texting heads-up in church_texts)
  1  when a recording ends and the church is over: kept until <date>.
  2  day 7, 3  day 13: still full, still kept until <date>.
     Then, at or after the date, still over, three warnings sent (the last
     one at least 12 hours ago) and not published: it is deleted the same
     way as the delete button, and the office hears once.
  If the church is back under its allowance, or the recording got
  published, the date is cleared and nothing more is said.
  The 80% heads-up: once per church per crossing (church_storage_notes
  holds that it went out; it re-arms below 75%, so a church sitting at the
  line hears once), with how many Sundays of room are left.
A warning counts only once its office notice is saved (_warn: claimed,
then marked delivered; a notice that didn't save is rolled back and sent
again next run), so a removal always follows three warnings that reached
the office. Every step is a conditional write (warnings_sent=eq.n,
last_warned_at=is.null, removed_at=is.null, near_noted_at=is.null), so two
replicas or a retry never send twice. Everything worth knowing in
production is print()ed with [church_storage] (Railway shows print only).
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

import sb_clients

GB = 1024 ** 3
NEAR_PERCENT = 80
REARM_PERCENT = 75
KEEP_DAYS = 14
SECOND_WARNING_DAY = 7
THIRD_WARNING_DAY = 13
DELETE_GAP = timedelta(hours=12)       # the last warning is at least this old before a removal
DEFAULT_SUNDAY_BYTES = 6 * GB          # a two-hour service, before the church has its own
SUNDAY_SAMPLE = 8
SUNDAY_MIN_S = 30 * 60
RECORDINGS_SHOWN = 50
NOTICE_TYPE = "storage_allowance"
NOTES = "church_storage_notes"
FILES_RPC = "church_storage_files_bytes"
COURSE_CHUNK = 50                      # course ids per in.() read: a short URL
DELETE_WORKERS = 16                    # a 2-hour service is ~1,800 four-second segments
LIST_PAGES_MAX = 100                   # 100,000 objects: far past any one service
R2_TIMEOUT_S = 15

SESSION_COLS = ("id,business_id,status,bytes,duration_s,started_at,ended_at,sermon_id,playlist_path,"
                "removed_at,keep_until,warnings_sent,last_warned_at")
_WATCH_RE = re.compile(r"/stream-relay/watch/([0-9a-fA-F-]{36})$")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now(now: Optional[datetime] = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _at(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _int(v: Any) -> int:
    try:
        return max(int(v or 0), 0)
    except (TypeError, ValueError):
        return 0


# ─── The switch ──────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_STORAGE") or "off").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switched_on(business_id: Any) -> bool:
    """Whether the allowance applies to this business: everyone's when on,
    the platform owner's churches when owner (a failed read is a no)."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(business_id)
    return False


def cards_on() -> bool:
    """The plan cards and the plan list say each plan's storage only once
    it is everyone's (not while it is the owner's alone)."""
    return mode() == "on"


def can_delete() -> bool:
    """The key that may delete from the media bucket is set."""
    import stream_relay_router as sr
    return sr.r2_write_config() is not None


def add_storage_sold() -> bool:
    """More storage can be bought (church_billing's price for it is set):
    the warnings' "Make room" becomes "Make room or add storage"."""
    import church_billing
    return bool(church_billing.extra_storage_prices())


# ─── The plan's allowance ────────────────────────────────────────────

# The blocks bought, read out of settings by PostgREST (a JSON path, so the
# whole settings object isn't sent for one number): "extra_storage" on the row.
EXTRA_SELECT = "extra_storage:settings->extra_storage"


def business_row(business_id: str) -> Optional[Dict[str, Any]]:
    """The fields the plan and the storage bought are read from; {} when
    there is no such business, None when the read failed."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{_q(business_id)}&select=id,comp_tier,subscription_plan,subscription_status,"
        f"stripe_subscription_id,{EXTRA_SELECT}&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else {}


def allowance_bytes(row: Optional[Dict[str, Any]]) -> Optional[int]:
    """The church plan's storage in bytes; None for anything that isn't a
    church plan (no limit)."""
    import church_texts
    import feature_gates
    plan = church_texts.church_plan_of(row)
    if plan is None:
        return None
    gb = feature_gates.plan_limits().get(plan, {}).get("storage_gb")
    return _int(gb) * GB if gb is not None else None


def block_bytes() -> int:
    """One block of storage bought (pricing_config.extra_storage_offer: 100 GB)."""
    import pricing_config
    return _int(pricing_config.extra_storage_offer()["gb"]) * GB


def _blocks_on(row: Any) -> Tuple[bool, Optional[int]]:
    """(the row carries the count, the count): settings.extra_storage from
    a row read with its settings (church_texts._church_rows), or the
    extra_storage column business_row asks for."""
    import church_billing
    if not isinstance(row, dict):
        return False, None
    if "settings" in row:
        return True, church_billing.extra_storage_blocks(row)
    if church_billing.EXTRA_STORAGE in row:
        return True, church_billing.storage_blocks_value(row.get(church_billing.EXTRA_STORAGE))
    return False, None


def extra_blocks(business_id: str, row: Optional[Dict[str, Any]] = None) -> Optional[int]:
    """The blocks of storage the church bought, from `row` when it carries
    them, else read. None when they can't be told: never 0 on a guess."""
    carried, blocks = _blocks_on(row)
    if carried:
        return blocks
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(business_id)}&select={EXTRA_SELECT}&limit=1")
    if not isinstance(rows, list) or not rows:
        return None
    return _blocks_on(rows[0])[1]


def extra_bytes(business_id: str, row: Optional[Dict[str, Any]] = None) -> Optional[int]:
    """Storage the church bought on top of its plan (church_billing's extra
    storage: blocks times block_bytes). It joins the allowance here and
    nowhere else. None when the count can't be read: the meter is then
    incomplete, and nothing is held, released or removed from it."""
    blocks = extra_blocks(business_id, row)
    return None if blocks is None else blocks * block_bytes()


def percent_of(used: int, total: int) -> int:
    """Whole percent, rounded down, so 99.6% reads 99 while it is still 'near'."""
    if total <= 0:
        return 100 if used > 0 else 0
    return int(used * 100 // total)


def state_of(used: int, total: int) -> str:
    if used >= total:
        return "full"
    if used * 100 >= NEAR_PERCENT * total:
        return "near"
    return "ok"


# ─── Reads ───────────────────────────────────────────────────────────

def sessions_of(business_id: str) -> Optional[List[Dict[str, Any]]]:
    """Every stream session of the church, removed ones too (their size
    still says what a Sunday takes). None when any page failed."""
    try:
        return sb_clients.sb_get_all_as_service(
            f"/stream_sessions?business_id=eq.{_q(business_id)}&select={SESSION_COLS}", key="id", strict=True)
    except Exception as e:  # noqa: BLE001  (PartialRead included)
        print(f"[church_storage] sessions read failed: {type(e).__name__}", flush=True)
        return None


def class_bytes(business_id: str) -> Optional[int]:
    """The church's class recordings. None when they can't be read: the page
    shows 0 for them, and the rules decide nothing from that church's meter
    on that run."""
    try:
        courses = sb_clients.sb_get_all_as_service(
            f"/academy_courses?business_id=eq.{_q(business_id)}&select=id", key="id", strict=True) or []
        ids = [str(c["id"]) for c in courses if c.get("id")]
        total = 0
        for i in range(0, len(ids), COURSE_CHUNK):
            part = ",".join(_q(x) for x in ids[i:i + COURSE_CHUNK])
            rows = sb_clients.sb_get_all_as_service(
                f"/academy_live_sessions?course_id=in.({part})&recording_bytes=not.is.null"
                f"&select=id,recording_bytes", key="id", strict=True) or []
            total += sum(_int(r.get("recording_bytes")) for r in rows)
        return total
    except Exception as e:  # noqa: BLE001
        print(f"[church_storage] class recordings not counted: {type(e).__name__}", flush=True)
        return None


def files_bytes(business_id: str) -> Optional[int]:
    """Supabase Storage under "<business_id>/", in every bucket. None when
    the database function isn't there (the migration) or the call failed."""
    out = sb_clients.sb_post_as_service(f"/rpc/{FILES_RPC}", {"p_business": business_id})
    if isinstance(out, bool):
        return None
    if isinstance(out, int):
        return max(out, 0)
    if isinstance(out, str) and out.isdigit():
        return int(out)
    return None


def sunday_bytes(sessions: List[Dict[str, Any]]) -> int:
    """What one service takes: the church's own average over its last
    SUNDAY_SAMPLE ended services of at least 30 minutes, else 6 GB."""
    done = [s for s in sessions if s.get("status") == "ended"
            and _int(s.get("duration_s")) >= SUNDAY_MIN_S and _int(s.get("bytes")) > 0]
    done.sort(key=lambda s: str(s.get("started_at") or ""), reverse=True)
    last = done[:SUNDAY_SAMPLE]
    if not last:
        return DEFAULT_SUNDAY_BYTES
    return max(1, sum(_int(s.get("bytes")) for s in last) // len(last))


def measure(business_id: str, sessions: List[Dict[str, Any]], row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The meter, from a whole read of the church's sessions and its row.
    `complete` (not on the page) is false when the files, the class
    recordings or the storage bought couldn't be read: the meter then counts
    them as 0 for the page, and nothing is held, released or removed from
    it. (The storage bought only matters with a plan's allowance: a church
    that left its plan is let go of its dates whatever it bought.)"""
    allowance = allowance_bytes(row)
    recordings = sum(_int(s.get("bytes")) for s in sessions if not s.get("removed_at"))
    classes = class_bytes(business_id)
    files = files_bytes(business_id)
    used_now = recordings + (classes or 0) + (files or 0)
    per_sunday = sunday_bytes(sessions)
    out: Dict[str, Any] = {
        "allowance_bytes": allowance, "extra_bytes": 0, "used_bytes": used_now,
        "parts": {"recordings": recordings, "classes": classes or 0, "files": files or 0},
        "files_counted": files is not None, "percent": None, "state": "ok",
        "bytes_per_sunday": per_sunday, "sundays_left": None,
        "complete": files is not None and classes is not None,
    }
    if allowance is not None:
        extra = extra_bytes(business_id, row)
        if extra is None:
            print(f"[church_storage] {str(business_id)[:8]}: the storage bought couldn't be read", flush=True)
            out["complete"] = False
        total = allowance + (extra or 0)
        out.update(extra_bytes=extra or 0, percent=percent_of(used_now, total), state=state_of(used_now, total),
                   sundays_left=max(0, total - used_now) // per_sunday)
    return out


def extra_offer(row: Optional[Dict[str, Any]], *, owner: bool) -> Dict[str, Any]:
    """What the page needs to sell more room: {gb, cents, every, blocks,
    can_buy, trial}. `cents` is one block's price each time the church's
    plan bills (`every`: month, quarter or year, read from its plan's price,
    no call to the payment side). `blocks` is what it bought, None when that
    can't be read (then nothing can be bought from the page: a save sends
    the whole count). `can_buy`: the owner (it spends money), a price for
    the plan's term is set, and the church pays for a church plan. `trial`:
    its card's trial is still running, so nothing is charged today (the
    page says so before Save)."""
    import church_billing
    import feature_gates
    import pricing_config
    _carried, blocks = _blocks_on(row)
    term = church_billing.row_term(row)
    paid = (feature_gates.plan_of(row) in feature_gates.CHURCH_PLANS
            and bool(str((row or {}).get("stripe_subscription_id") or "").strip()))
    return {"gb": _int(pricing_config.extra_storage_offer()["gb"]),
            "cents": church_billing.extra_storage_cents(term),
            "every": church_billing.every_word(term),
            "blocks": blocks,
            "can_buy": bool(owner and paid and blocks is not None and church_billing.extra_storage_price(term)),
            "trial": str((row or {}).get("subscription_status") or "") == "trialing"}


def total_of(meter: Dict[str, Any]) -> Optional[int]:
    """Allowance plus what was bought; None when there is no limit."""
    if meter.get("allowance_bytes") is None:
        return None
    return int(meter["allowance_bytes"]) + int(meter.get("extra_bytes") or 0)


def used(business_id: str) -> Optional[Dict[str, Any]]:
    """The church's meter (see the module's WHAT IS COUNTED). None when its
    plan or its recordings can't be read."""
    row = business_row(business_id)
    sessions = sessions_of(business_id)
    if row is None or sessions is None:
        return None
    return measure(business_id, sessions, row)


def recordings_of(sessions: List[Dict[str, Any]], limit: int = RECORDINGS_SHOWN) -> List[Dict[str, Any]]:
    """Ended and not removed, newest first."""
    out = [s for s in sessions if s.get("status") == "ended" and not s.get("removed_at")]
    out.sort(key=lambda s: str(s.get("started_at") or ""), reverse=True)
    return out[:limit]


def published_sessions(business_id: str) -> Optional[Set[str]]:
    """The recordings a PUBLISHED sermon of this church carries (the same
    test as stream_relay_router._published), in one paged read. None when
    it failed."""
    try:
        rows = sb_clients.sb_get_all_as_service(
            f"/sermons?business_id=eq.{_q(business_id)}&published=eq.true"
            f"&video_url=like.{_q('*/stream-relay/watch/*')}&select=id,video_url", key="id", strict=True)
    except Exception as e:  # noqa: BLE001
        print(f"[church_storage] sermons read failed: {type(e).__name__}", flush=True)
        return None
    out: Set[str] = set()
    for r in rows or []:
        m = _WATCH_RE.search(str(r.get("video_url") or "").strip())
        if m:
            out.add(m.group(1).lower())
    return out


# ─── Removing a recording ────────────────────────────────────────────

def recording_prefix(business_id: str, s: Dict[str, Any]) -> Optional[str]:
    """The recording's folder in the media bucket: its playlist's path
    without index.m3u8. The relay writes every session at
    live/<business>/<session>/ (stream_relay_router.playlist_path), and
    nothing else is ever deleted: a stored path anywhere else is None."""
    import stream_relay_router as sr
    sid = str(s.get("id") or "").lower()
    if not sr.UUID_RE.match(sid) or not sr.UUID_RE.match(str(business_id).lower()):
        return None
    expected = sr.playlist_path(str(business_id).lower(), sid)
    stored = str(s.get("playlist_path") or "").strip() or expected
    if stored != expected:
        print(f"[church_storage] recording {sid[:8]} has an unexpected path; not deleting it", flush=True)
        return None
    return expected[: -len("index.m3u8")]


def _client():
    import httpx
    return httpx.Client(timeout=R2_TIMEOUT_S, limits=httpx.Limits(max_connections=DELETE_WORKERS))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_listing(text: str) -> Optional[Tuple[List[Tuple[str, int]], Optional[str], bool]]:
    """One ListObjectsV2 page: ([(key, size)], next continuation token,
    truncated?). None when it isn't one."""
    try:
        root = ET.fromstring(text or "")
    except ET.ParseError:
        return None
    if _local(root.tag) != "ListBucketResult":
        return None
    items: List[Tuple[str, int]] = []
    token: Optional[str] = None
    truncated = False
    for el in root:
        name = _local(el.tag)
        if name == "Contents":
            key, size = "", 0
            for f in el:
                if _local(f.tag) == "Key":
                    key = f.text or ""
                elif _local(f.tag) == "Size":
                    size = _int(f.text)
            if key:
                items.append((key, size))
        elif name == "NextContinuationToken":
            token = (el.text or "").strip() or None
        elif name == "IsTruncated":
            truncated = (el.text or "").strip().lower() == "true"
    return items, token, truncated


def _list(client: Any, prefix: str) -> Optional[List[str]]:
    """Every object key under `prefix`. None when any page failed."""
    import stream_relay_router as sr
    keys: List[str] = []
    token: Optional[str] = None
    for _ in range(LIST_PAGES_MAX):
        query = {"list-type": "2", "prefix": prefix}
        if token:
            query["continuation-token"] = token
        url = sr.r2_write_link("GET", None, query)
        if url is None:
            return None
        try:
            r = client.request("GET", url)
        except Exception as e:  # noqa: BLE001
            print(f"[church_storage] listing failed: {type(e).__name__}", flush=True)
            return None
        if r.status_code != 200:
            print(f"[church_storage] listing answered {r.status_code}", flush=True)
            return None
        page = parse_listing(r.text)
        if page is None:
            return None
        items, token, truncated = page
        keys.extend(k for k, _size in items if k.startswith(prefix))
        if not truncated:
            return keys
        if not token:
            return None
    return None


def _delete_all(client: Any, keys: List[str]) -> bool:
    """Delete each object (a signed DELETE apiece, several at a time).
    True only when every one is gone (204, or 404: already gone)."""
    import stream_relay_router as sr

    def one(key: str) -> bool:
        url = sr.r2_write_link("DELETE", key)
        if url is None:
            return False
        try:
            r = client.request("DELETE", url)
        except Exception as e:  # noqa: BLE001
            print(f"[church_storage] delete of {key[-40:]} failed: {type(e).__name__}", flush=True)
            return False
        if r.status_code in (200, 204, 404):
            return True
        print(f"[church_storage] delete of {key[-40:]} answered {r.status_code}", flush=True)
        return False

    if not keys:
        return True
    with ThreadPoolExecutor(max_workers=min(DELETE_WORKERS, len(keys))) as pool:
        return all(list(pool.map(one, keys)))


def _forget(sid: str) -> None:
    """The player's short caches of this recording."""
    import stream_relay_router as sr
    with sr._cache.lock:
        sr._cache.access.pop(sid, None)
        sr._cache.lists.pop(sid, None)
        sr._cache.links.pop(sid, None)


def _clear_drafts(business_id: str, sid: str, now: datetime) -> None:
    """An UNPUBLISHED sermon that carried this recording keeps its words
    and loses the player that would only say the video isn't available.
    Best effort."""
    got = sb_clients.sb_patch_as_service(
        f"/sermons?business_id=eq.{_q(business_id)}&published=eq.false"
        f"&video_url=like.{_q('*/stream-relay/watch/' + sid)}",
        {"video_url": "", "updated_at": _iso(now)})
    if got is None:
        print(f"[church_storage] draft for {sid[:8]} kept its link", flush=True)


def remove_recording(business_id: str, s: Dict[str, Any], *, now: Optional[datetime] = None
                     ) -> Optional[Dict[str, Any]]:
    """Delete one recording's files from the media bucket, then mark it
    removed (removed_at, keep_until cleared). {"marked": this call marked
    it, "freed_bytes": what the meter counted for it}; None when anything
    failed, and then nothing is marked, so it can be tried again (a retry
    finds fewer files, or none, and finishes). The caller has already
    checked it is the church's, ended and not a published sermon."""
    sid = str(s.get("id") or "").lower()
    if s.get("removed_at"):
        return {"marked": False, "freed_bytes": 0}
    prefix = recording_prefix(business_id, s)
    if prefix is None or not can_delete():
        return None
    with _client() as client:
        keys = _list(client, prefix)
        if keys is None or not _delete_all(client, keys):
            return None
    stamp = _now(now)
    got = sb_clients.sb_patch_as_service(
        f"/stream_sessions?id=eq.{_q(sid)}&business_id=eq.{_q(business_id)}&removed_at=is.null",
        {"removed_at": _iso(stamp), "keep_until": None})
    if not isinstance(got, list):
        return None
    _forget(sid)
    _clear_drafts(business_id, sid, stamp)
    print(f"[church_storage] removed recording {sid[:8]} of {str(business_id)[:8]}: "
          f"{len(keys)} files, {_int(s.get('bytes'))} bytes", flush=True)
    return {"marked": bool(got), "freed_bytes": _int(s.get("bytes")) if got else 0}


# ─── Telling the office ──────────────────────────────────────────────

def _church_clock(business_id: str):
    import stream_relay_router as sr
    try:
        return sr._church_tz(business_id)
    except Exception:  # noqa: BLE001  (a 503 there: words on UTC rather than none)
        return timezone.utc


def _day_words(dt: datetime) -> str:
    return f"{dt:%A}, {dt:%B} {dt.day}"


def _date_words(dt: datetime) -> str:
    return f"{dt:%B} {dt.day}"


def _make_room() -> str:
    return "Make room or add storage to keep it." if add_storage_sold() else "Make room to keep it."


def fewer_blocks_words(over: Optional[bool]) -> Optional[str]:
    """What the answer to taking storage off says: over (True), maybe over
    (None: it couldn't be measured), or nothing to say (False)."""
    rule = (f"kept {KEEP_DAYS} days, then deleted unless you make room or add storage again. "
            "Published sermons are never deleted.")
    if over is True:
        return f"Your church now uses more storage than it has. Nothing is deleted now. A service recorded while it's over is {rule}"
    if over is None:
        return f"If your church now uses more storage than it has, a service recorded while it's over is {rule}"
    return None


def notice(kind: str, *, day: str = "", started: str = "", keep: str = "", percent: int = 0,
           sundays: int = 0, has_draft: bool = False) -> Tuple[str, str]:
    """The office's title and body. `day` is the service's weekday
    ("Sunday"), `started` its date ("November 15"), `keep` the day it is
    kept until ("Tuesday, December 1")."""
    never = "Published sermons are never deleted."
    if kind == "held":
        return ("Your storage is full",
                f"{day}'s recording is kept until {keep}. {_make_room()} Delete recordings or files you "
                f"no longer need. {never}")
    if kind == "second":
        return (f"{day}'s recording: one week left",
                f"Your storage is still full. {day}'s recording from {started} is kept until {keep}. "
                f"{_make_room()}")
    if kind == "last":
        return (f"Last day to keep {day}'s recording",
                f"Your storage is still full, so {day}'s recording from {started} will be deleted after "
                f"{keep}. {_make_room()} {never}")
    if kind == "removed":
        draft = " Its sermon draft is still there, without the video." if has_draft else ""
        return (f"{day}'s recording was deleted",
                f"Your storage was still full after {KEEP_DAYS} days, so {day}'s recording from {started} "
                f"was deleted to make room.{draft} {never}")
    # the heads-up
    if percent >= 100:
        title = "Your storage is full"
        room = "There's no room left for another Sunday's recording."
    else:
        title = f"Your storage is {percent}% full"
        room = ("There's room for less than one more Sunday's recording." if sundays < 1 else
                f"There's room for about {sundays:,} more Sunday{'' if sundays == 1 else 's'} of recordings.")
    return (title, f"{room} To make room, delete the oldest recordings you haven't published as sermons. "
                   f"Recording never stops.")


def _post(business_id: str, kind: str, title: str, body: str, now: datetime, data: Dict[str, Any]) -> bool:
    """The office notice, saved. False when the insert failed (nothing
    reached the office): a warning is then not counted, and is sent again."""
    out = sb_clients.sb_post_as_service("/chief_notifications", {
        "business_id": business_id,
        "type": NOTICE_TYPE,
        "title": title,
        "body": body,
        "priority": "high" if kind in ("held", "last", "removed") else "normal",
        "status": "unread",
        "created_at": _iso(now),
        "data": {"kind": kind, **data},
    })
    saved = isinstance(out, list) and bool(out)
    if not saved:
        print(f"[church_storage] {kind} notice for {str(business_id)[:8]} didn't save", flush=True)
    return saved


def _tell_about(business_id: str, kind: str, s: Dict[str, Any], now: datetime,
                keep_until: Optional[datetime] = None) -> bool:
    tz = _church_clock(business_id)
    start = (_at(s.get("started_at")) or now).astimezone(tz)
    keep = keep_until or _at(s.get("keep_until"))
    title, body = notice(kind, day=f"{start:%A}", started=_date_words(start),
                         keep=_day_words(keep.astimezone(tz)) if keep else "",
                         has_draft=bool(s.get("sermon_id")))
    return _post(business_id, kind, title, body, now, {"session_id": str(s.get("id")),
                                                        "keep_until": _iso(keep) if keep else None})


def _tell_near(business_id: str, used_now: int, total: int, per_sunday: int, now: datetime) -> bool:
    pct = percent_of(used_now, total)
    sundays = max(0, total - used_now) // max(per_sunday, 1)
    title, body = notice("near", percent=pct, sundays=sundays)
    return _post(business_id, "near", title, body, now, {"percent": pct, "sundays_left": sundays,
                                                         "used_bytes": used_now, "allowance_bytes": total})


# ─── The 14-day rule ─────────────────────────────────────────────────

def _hold(business_id: str, sid: str, now: datetime) -> Optional[datetime]:
    """Keep a recording made while full for KEEP_DAYS, once: only a session
    never held or warned before. The date when this call set it. The first
    warning is sent (and counted) separately, by _warn."""
    keep = now + timedelta(days=KEEP_DAYS)
    got = sb_clients.sb_patch_as_service(
        f"{_session_path(business_id, sid)}&removed_at=is.null&keep_until=is.null&warnings_sent=eq.0",
        {"keep_until": _iso(keep)})
    return keep if isinstance(got, list) and got else None


def _session_path(business_id: str, sid: str) -> str:
    return f"/stream_sessions?id=eq.{_q(sid)}&business_id=eq.{_q(business_id)}"


WARNING_KINDS = {1: "held", 2: "second", 3: "last"}


def _warn(business_id: str, s: Dict[str, Any], n: int, now: datetime) -> bool:
    """Send warning n (1 kept, 2 a week left, 3 the last day), counted only
    once its office notice is saved. True when it reached the office.

    Two conditional steps, so replicas and retries never send twice: the
    claim (warnings_sent n-1 -> n with last_warned_at null: claimed, not
    yet delivered), then, once the notice is saved, last_warned_at = now
    (delivered). A notice that didn't save rolls the claim back to what it
    was claimed from, so the next run sends it again. If even that write
    fails, the warning stays claimed-not-delivered (last_warned_at null):
    it never counts toward the next warning or a removal, and the next run
    sends it again. Warning 1 starts the 14 days from now, so a church
    always gets them in full once it is told."""
    sid = str(s.get("id") or "").lower()
    path = _session_path(business_id, sid)
    resend = _int(s.get("warnings_sent")) == n and not s.get("last_warned_at")
    keep = _at(s.get("keep_until"))
    if not resend:
        claim: Dict[str, Any] = {"warnings_sent": n, "last_warned_at": None}
        if n == 1:
            keep = now + timedelta(days=KEEP_DAYS)
            claim["keep_until"] = _iso(keep)
        before = "&last_warned_at=not.is.null" if n > 1 else ""
        got = sb_clients.sb_patch_as_service(
            f"{path}&removed_at=is.null&keep_until=not.is.null&warnings_sent=eq.{n - 1}{before}", claim)
        if not (isinstance(got, list) and got):
            return False
    if _tell_about(business_id, WARNING_KINDS[n], s, now, keep_until=keep):
        done = sb_clients.sb_patch_as_service(f"{path}&warnings_sent=eq.{n}&last_warned_at=is.null",
                                              {"last_warned_at": _iso(now)})
        if not (isinstance(done, list) and done):
            print(f"[church_storage] warning {n} for {sid[:8]} reached the office but wasn't marked; "
                  f"it will be sent again", flush=True)
        return True
    if not resend:
        back = sb_clients.sb_patch_as_service(
            f"{path}&warnings_sent=eq.{n}&last_warned_at=is.null",
            {"warnings_sent": n - 1, "last_warned_at": s.get("last_warned_at")})
        if not (isinstance(back, list) and back):
            print(f"[church_storage] warning {n} for {sid[:8]} couldn't be undone; it stays unsent "
                  f"and is sent again next run", flush=True)
    return False


def _release(business_id: str, sid: str) -> bool:
    """It is kept after all: the date goes, nothing is said. The warnings
    count stays, so the same recording is never held a second time."""
    got = sb_clients.sb_patch_as_service(
        f"/stream_sessions?id=eq.{_q(sid)}&business_id=eq.{_q(business_id)}&keep_until=not.is.null",
        {"keep_until": None})
    return isinstance(got, list) and bool(got)


def _claim_near(business_id: str, now: datetime) -> bool:
    """The 80% heads-up for this crossing is this call's to send."""
    stamp = _iso(now)
    got = sb_clients.sb_patch_as_service(
        f"/{NOTES}?business_id=eq.{_q(business_id)}&near_noted_at=is.null",
        {"near_noted_at": stamp, "updated_at": stamp})
    if not isinstance(got, list):
        return False
    if got:
        return True
    made = sb_clients.sb_post_as_service(
        f"/{NOTES}?on_conflict=business_id", {"business_id": business_id, "near_noted_at": stamp,
                                              "updated_at": stamp},
        prefer="resolution=ignore-duplicates,return=representation")
    return isinstance(made, list) and bool(made)


def _rearm(business_id: str, now: datetime) -> None:
    sb_clients.sb_patch_as_service(f"/{NOTES}?business_id=eq.{_q(business_id)}&near_noted_at=not.is.null",
                                   {"near_noted_at": None, "updated_at": _iso(now)})


def recording_ended(business_id: str, session_id: str, *, now: Optional[datetime] = None) -> Optional[str]:
    """Called once a recording's end is saved. Over the allowance with it:
    keep it KEEP_DAYS and send the first warning ("held"). Past 80%: the
    heads-up, once per crossing ("near"). Otherwise, or while switched off,
    or without the key that may delete: nothing (None). Never raises and
    never stops anything."""
    try:
        biz, sid = str(business_id), str(session_id).lower()
        if not switched_on(biz) or not can_delete():
            return None
        stamp = _now(now)
        row, sessions = business_row(biz), sessions_of(biz)
        if row is None or sessions is None:
            return None
        meter = measure(biz, sessions, row)
        total = total_of(meter)
        s = next((x for x in sessions if str(x.get("id") or "").lower() == sid), None)
        if total is None or s is None or s.get("removed_at"):
            return None
        if not meter["complete"]:
            # Files or class recordings unreadable: can't tell whether it is
            # over, so neither hold it nor say anything on a guess.
            print(f"[church_storage] recording {sid[:8]} ended; storage couldn't be fully read, "
                  f"nothing decided", flush=True)
            return None
        if meter["used_bytes"] > total:
            keep = _hold(biz, sid, stamp)
            if keep is None:
                return None
            held = {**s, "keep_until": _iso(keep), "warnings_sent": 0, "last_warned_at": None}
            if _warn(biz, held, 1, stamp):
                _claim_near(biz, stamp)      # the warning says more than the heads-up would
            return "held"
        if meter["state"] != "ok" and _claim_near(biz, stamp):
            if _tell_near(biz, meter["used_bytes"], total, meter["bytes_per_sunday"], stamp):
                return "near"
            _rearm(biz, stamp)               # not told: the next run tries again
        return None
    except Exception as e:  # noqa: BLE001
        print(f"[church_storage] after a recording: {type(e).__name__}: {e}", flush=True)
        return None


def _published_one(business_id: str, sid: str) -> Optional[bool]:
    import stream_relay_router as sr
    return sr._published(business_id, sid)


def tick_church(business_id: str, row: Optional[Dict[str, Any]], noted: bool,
                now: datetime) -> Dict[str, int]:
    """One church's day: its held recordings, then the heads-up."""
    out = {"cleared": 0, "warned": 0, "removed": 0, "notices": 0, "errors": 0}
    row = row if row is not None else business_row(business_id)
    sessions = sessions_of(business_id)
    if row is None or sessions is None:
        out["errors"] += 1
        return out
    meter = measure(business_id, sessions, row)
    if not meter["complete"]:
        # Files or class recordings unreadable: counted as 0 they would look
        # like room, and a hold released on that is never held again. Nothing
        # is released, warned, removed or re-armed for this church today.
        print(f"[church_storage] {business_id[:8]}: storage couldn't be fully read (files "
              f"{'counted' if meter['files_counted'] else 'unread'}); nothing decided today", flush=True)
        out["errors"] += 1
        return out
    total = total_of(meter)
    used_now = int(meter["used_bytes"])
    held = sorted((s for s in sessions if s.get("keep_until") and not s.get("removed_at")),
                  key=lambda s: str(s.get("keep_until")))
    pub = published_sessions(business_id) if held else set()
    if held and pub is None:
        out["errors"] += 1
        held = []
    for s in held:
        sid = str(s.get("id") or "").lower()
        keep = _at(s.get("keep_until"))
        if total is None or used_now <= total or sid in (pub or set()) or keep is None:
            out["cleared"] += int(_release(business_id, sid))
            continue
        sent = _int(s.get("warnings_sent"))
        last = _at(s.get("last_warned_at"))
        if sent == 0 or last is None:
            # Never told, or a warning claimed whose notice never landed: (re)send it.
            if _warn(business_id, s, min(max(sent, 1), 3), now):
                out["warned"] += 1
        elif now >= keep and sent >= 3 and last <= now - DELETE_GAP:
            fresh = _published_one(business_id, sid)        # once more, at the last moment
            if fresh is None:
                out["errors"] += 1
                continue
            if fresh:
                out["cleared"] += int(_release(business_id, sid))
                continue
            done = remove_recording(business_id, s, now=now)
            if done is None:
                out["errors"] += 1
                continue
            if done["marked"]:
                used_now -= int(done["freed_bytes"])
                out["removed"] += 1
                _tell_about(business_id, "removed", s, now)
        elif sent == 2 and now >= keep - timedelta(days=KEEP_DAYS - THIRD_WARNING_DAY):
            if _warn(business_id, s, 3, now):
                out["warned"] += 1
        elif sent == 1 and now >= keep - timedelta(days=KEEP_DAYS - SECOND_WARNING_DAY):
            if _warn(business_id, s, 2, now):
                out["warned"] += 1
    if total is not None:
        if used_now * 100 >= NEAR_PERCENT * total:
            if not noted and _claim_near(business_id, now):
                if _tell_near(business_id, used_now, total, int(meter["bytes_per_sunday"]), now):
                    out["notices"] += 1
                else:
                    _rearm(business_id, now)          # not told: tomorrow tries again
        elif noted and used_now * 100 < REARM_PERCENT * total:
            _rearm(business_id, now)
    return out


def storage_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Once a day, where the switch is on and the key that may delete is
    set: every church on a church plan, and every church holding a
    recording (a church that left its plan is let go of its dates). One
    church's failure never stops the rest."""
    out = {"churches": 0, "cleared": 0, "warned": 0, "removed": 0, "notices": 0, "errors": 0}
    m = mode()
    if m == "off" or not can_delete():
        return out
    stamp = _now(now)
    import church_texts
    import sample_church
    try:
        rows = church_texts._church_rows()
        held = sb_clients.sb_get_all_as_service(
            "/stream_sessions?keep_until=not.is.null&removed_at=is.null&select=id,business_id",
            key="id", strict=True)
        notes = sb_clients.sb_get_all_as_service(f"/{NOTES}?select=business_id,near_noted_at",
                                                 key="business_id", strict=True)
    except Exception as e:  # noqa: BLE001
        print(f"[church_storage] tick read failed: {type(e).__name__}", flush=True)
        out["errors"] += 1
        return out
    by_id = {str(r.get("id")): r for r in rows or [] if r.get("id")}
    ids = list(by_id) + sorted({str(h.get("business_id")) for h in held or []
                                if h.get("business_id") and str(h.get("business_id")) not in by_id})
    ids = sample_church.drop_samples(ids)
    noted = {str(n.get("business_id")): bool(n.get("near_noted_at")) for n in notes or []}
    for biz in ids:
        try:
            if m == "owner" and not switched_on(biz):
                continue
            got = tick_church(biz, by_id.get(biz), noted.get(biz, False), stamp)
            out["churches"] += 1
            for k, v in got.items():
                out[k] += v
        except Exception as e:  # noqa: BLE001
            out["errors"] += 1
            print(f"[church_storage] tick failed for {biz[:8]}: {type(e).__name__}: {e}", flush=True)
    if out["removed"] or out["warned"]:
        print(f"[church_storage] tick: {out}", flush=True)
    return out
