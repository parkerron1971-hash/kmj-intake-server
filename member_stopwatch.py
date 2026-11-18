"""member_stopwatch.py — how long the member app (/my) takes, on the server and on the phone.

Kevin, 2026-11-18: "the members app move slow when send messages in chat,
switching from one tab to another… what is the problem and how can that be
sped up?" Nothing timed member pages, so there was no number to start from
and none to prove a fix with. This is the stopwatch; the fixes come after it.

THE SERVER'S PART. MemberStopwatch (pure ASGI, kmj_intake_automation.py) times
every request under /my, pages and POSTs alike:
  - a Server-Timing header on the response: total, church (the host → church
    read, member_portal._church_for_request), session (the signed-in member,
    member_portal._session_for) and rest (the page's own reads and the HTML);
  - one print() line: "[member] GET /my/messages/:id 200 412ms church=85
    session=90". The path is a pattern: any part with a digit, or anything
    but lower-case letters and dashes, prints as ":id"; the query string
    never prints. The phone's beacon, the app's icons and service worker, and
    the chat's 6-second polls print only when slow (>= 1 s) or failing;
  - a sample in this process's rolling numbers, for a signed-in member's page
    (200) or save (under 400) only: sign-in pages and the owner's preview
    never count.
`timed()` wraps the two lookups; outside a /my request it costs nothing.

THE PHONE'S PART. PHONE_JS, inline at the foot of every signed-in page
(member_portal._shell), sends the page's own navigation timing once it can
be used: time to first byte and time until the page can be used
(DOMContentLoaded), both from the tap, as {p, f, r, t} via
navigator.sendBeacon to POST /my/timing. p is the page's path with every
part that has a digit replaced by ":id"; no query, no name, no cookie read
by the script. A back/forward page from the browser's cache sends nothing.
POST /my/timing takes it only:
  - on a church's own address (never the API host), from its own page (the
    Origin or Referer names this host; Origin: null only with the browser's
    Sec-Fetch-Site: same-origin, as in member_portal._same_origin; a request
    with none of the three is refused);
  - from a signed-in member of that church (the session cookie's signature
    is checked first, with no database read, so a made-up cookie costs
    nothing; then the address must be that church's: what this process saw
    serve a member page in the last 10 minutes, else one lookup);
  - never from the owner's preview, at most RL_MEMBER_TIMING_PER_MIN a minute
    from one network (a church's wifi is one network), with plausible numbers
    (0-60 s, first byte before ready). Anything else is dropped.

THE NUMBERS. Per page kind (Home, Watch, Bible, Give, Connect, Messages, a
conversation, Me, other pages, sending a message, other saves), per side
(server, phone first byte, phone ready): the last KEEP samples with their
time, in memory. Each server copy (Railway runs several) keeps only its own.

WHERE KEVIN SEES THEM. db_health.take_reading saves for_reading() into the
reading's metrics jsonb as metrics.member_app (no new table, no migration):
Sunday every 15 minutes, Wednesday, and Check now. A scheduled reading takes
what this process timed since its last saved scheduled reading (at most an
hour; the mark moves only once the reading is saved, so a failed save leaves
its numbers for the next); Check now takes the last hour without moving that
mark, so it never steals Sunday's numbers. The reading is taken by the scheduler's leader, so each
reading holds the numbers of the one server copy that took it: a sample,
fair while visits are shared out evenly between copies. card() turns the
week's readings into the words on Mission Control → Systems → Database.

MEMBER_STOPWATCH=off turns all of it off (no header, no line, no script, no
numbers). Every piece fails soft: a stopwatch fault never touches a page.
"""
from __future__ import annotations

import contextvars
import functools
import json
import math
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter(tags=["member-portal"])

# ─── The switch ─────────────────────────────────────────────────────────

ENV = "MEMBER_STOPWATCH"


def enabled() -> bool:
    return (os.environ.get(ENV) or "on").strip().lower() not in ("off", "0", "false", "no")


# ─── Paths: a pattern and a kind ────────────────────────────────────────

KEEP = 1000                    # samples per (side, kind) in memory
WINDOW_SECONDS = 3600          # a reading never reaches further back than this
SLOW_MS = 1000.0               # an uncounted request (poll, icon, beacon) prints when slower than this
MAX_MS = 60000.0               # a phone number over a minute isn't a page load
KNOWN_HOST_SECONDS = 600.0
KNOWN_HOST_MAX = 2000

SIDES = ("server", "first_byte", "ready")

# The kinds, in the order the card lists them, with their plain names.
KINDS: List[Tuple[str, str]] = [
    ("home", "Home"), ("watch", "Watch"), ("bible", "Bible"), ("give", "Give"),
    ("connect", "Connect"), ("messages", "Messages"), ("conversation", "A conversation"),
    ("me", "Me"), ("page", "Other pages"), ("send", "Sending a message"), ("save", "Other saves"),
]
LABEL = dict(KINDS)
PAGE_KINDS = tuple(k for k, _ in KINDS if k not in ("send", "save"))

_SAFE_PART = re.compile(r"^[a-z][a-z-]{0,23}$")
_ASSET = re.compile(r"^/my/(manifest\.webmanifest|sw\.js|icon-[^/]*\.png|offline)$")


def is_member_path(path: str) -> bool:
    return path == "/my" or path.startswith("/my/")


def pattern(path: str) -> str:
    """'/my/messages/2f1c…/send' → '/my/messages/:id/send'. Only parts made
    of lower-case letters and dashes (up to 24) are kept as they are, so no
    id, number, token or name can reach a log line."""
    parts = [p for p in str(path or "").split("?")[0].split("/") if p]
    out = []
    for p in parts:
        out.append(p if _SAFE_PART.match(p) else ":id")
    return "/" + "/".join(out)


def _asset(path: str) -> bool:
    if _ASSET.match(path):
        return True
    return path.startswith("/my/photo/") or bool(re.match(r"^/my/messages/[^/]+/photo/", path))


def kind_of(method: str, path: str) -> Optional[str]:
    """The page kind a request counts under, 'poll' or 'asset' for the ones
    that never count, or None (the beacon itself, the preview link)."""
    pat = pattern(path)
    if pat == "/my/timing":
        return None
    if str(method or "").upper() == "POST":
        if pat in ("/my/messages/:id/send", "/my/inbox/church/send"):
            return "send"
        return "save"
    if _asset(path) or _asset(pat):
        return "asset"
    if "/feed" in pat:
        return "poll"
    if pat in ("/my/preview", "/my/space"):
        return None
    if pat == "/my":
        return "home"
    head = pat.split("/")[2] if pat.count("/") >= 2 else ""
    rest = pat[len("/my/" + head):]
    if head in ("sermons", "live"):
        return "watch"
    if head == "bible":
        return "bible"
    if head == "give" and not rest:
        return "give"
    if head == "me" and not rest:
        return "me"
    if head in ("groups", "classes", "directory") and not rest:
        return "connect"
    if head == "groups" and rest.endswith("/chat"):
        return "conversation"
    if head in ("messages", "inbox"):
        return "messages" if not rest else "conversation"
    return "page"


# ─── The rolling numbers (this process only) ────────────────────────────

_lock = threading.Lock()
_store: Dict[Tuple[str, str], Deque[Tuple[float, float]]] = {}
_state: Dict[str, float] = {"mark": 0.0}
_known: Dict[str, Tuple[float, str, int]] = {}


def forget() -> None:
    """For the tests: every number, the reading mark and the known hosts."""
    with _lock:
        _store.clear()
        _known.clear()
        _state["mark"] = 0.0


def record(side: str, kind: str, ms: float, at: Optional[float] = None) -> None:
    if side not in SIDES or kind not in LABEL:
        return
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return
    if not math.isfinite(ms) or ms < 0 or ms > MAX_MS:
        return
    with _lock:
        q = _store.get((side, kind))
        if q is None:
            q = _store[(side, kind)] = deque(maxlen=KEEP)
        q.append((time.time() if at is None else at, ms))


def _values(since: float, until: float) -> Dict[str, Dict[str, List[float]]]:
    out: Dict[str, Dict[str, List[float]]] = {}
    with _lock:
        for (side, kind), q in _store.items():
            vals = [ms for at, ms in q if since < at <= until]
            if vals:
                out.setdefault(side, {})[kind] = vals
    return out


def _exact(vals: List[float], q: float) -> float:
    s = sorted(vals)
    return s[max(0, min(len(s) - 1, math.ceil(q * len(s)) - 1))]


def numbers(seconds: float = WINDOW_SECONDS) -> Dict[str, Dict[str, Dict[str, float]]]:
    """This process's live numbers for the last `seconds`: {side: {kind:
    {n, p50, p90}}} in milliseconds."""
    now = time.time()
    return {side: {kind: {"n": len(v), "p50": round(_exact(v, 0.5)), "p90": round(_exact(v, 0.9))}
                   for kind, v in kinds.items()}
            for side, kinds in _values(now - seconds, now).items()}


# ─── Histograms: what a reading keeps, so readings can be added up ─────

# Upper bounds in ms; the first bucket starts at 0, the last ends at MAX_MS.
# 50 ms wide under half a second, 100 ms to 1.6 s, so a number read back from
# them is within about a tenth of what it was.
BOUNDS = (25, 50, 75, 100, 125, 150, 175, 200, 250, 300, 350, 400, 450, 500, 600, 700, 800, 900,
          1000, 1100, 1200, 1300, 1400, 1500, 1600, 1800, 2000, 2250, 2500, 2750, 3000, 3500, 4000,
          5000, 6000, 8000, 10000, 15000, 20000, 30000, int(MAX_MS))


def hist(vals: Iterable[float]) -> List[int]:
    counts = [0] * len(BOUNDS)
    for v in vals:
        for i, top in enumerate(BOUNDS):
            if v < top or i == len(BOUNDS) - 1:
                counts[i] += 1
                break
    while counts and counts[-1] == 0:
        counts.pop()
    return counts


def merge(hists: Iterable[Any]) -> List[int]:
    out = [0] * len(BOUNDS)
    for h in hists:
        if not isinstance(h, list):
            continue
        for i, c in enumerate(h[:len(BOUNDS)]):
            if isinstance(c, (int, float)) and not isinstance(c, bool) and c > 0:
                out[i] += int(c)
    while out and out[-1] == 0:
        out.pop()
    return out


def from_hist(h: List[int], q: float) -> Optional[float]:
    """The q-th share (0.5 typical, 0.9 the slowest 1 in 10) read from a
    histogram, straight-line inside the bucket it falls in."""
    n = sum(h)
    if n <= 0:
        return None
    target, seen = q * n, 0
    for i, c in enumerate(h):
        if c and seen + c >= target:
            lo = BOUNDS[i - 1] if i else 0
            return lo + (target - seen) / c * (BOUNDS[i] - lo)
        seen += c
    return float(BOUNDS[len(h) - 1])


# ─── What a db_health reading saves ─────────────────────────────────────

def _replica() -> str:
    raw = os.environ.get("RAILWAY_REPLICA_ID") or os.environ.get("HOSTNAME") or ""
    return re.sub(r"[^A-Za-z0-9-]", "", raw)[:12]


def _z(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def for_reading(kind: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """This process's numbers for a db_health reading, or None when it has
    none (or the stopwatch is off). A scheduled reading takes what was timed
    since this process's last saved one (at most an hour); Check now
    ('manual') takes the last hour. Neither moves the mark: saved() does,
    once the reading is in the database, so a reading that fails to save
    leaves its numbers for the next one."""
    if not enabled():
        return None
    try:
        now = time.time() if now is None else now
        with _lock:
            since = now - WINDOW_SECONDS
            if kind != "manual":
                since = max(since, _state["mark"])
        vals = _values(since, now)
        if not vals:
            return None
        out: Dict[str, Any] = {"v": 1, "since": _z(since), "until": _z(now), "replica": _replica()}
        for side, kinds in vals.items():
            out[side] = {k: {"n": len(v), "p50": round(_exact(v, 0.5)), "p90": round(_exact(v, 0.9)),
                             "h": hist(v)} for k, v in kinds.items()}
        return out
    except Exception as e:  # noqa: BLE001 — a reading never fails for the stopwatch
        print(f"[member] reading numbers failed: {type(e).__name__}", flush=True)
        return None


def saved(reading: Optional[Dict[str, Any]], kind: str) -> None:
    """A scheduled reading made it into the database: the next one starts
    where it ended. Check now never moves the mark."""
    if not reading or kind == "manual":
        return
    until = _parse(reading.get("until"))
    if until is None:
        return
    with _lock:
        _state["mark"] = max(_state["mark"], until.timestamp())


# ─── The card (pure): the week's readings in plain words ────────────────

def _secs(ms: Optional[float]) -> str:
    if ms is None:
        return "—"
    if ms < 50:
        return "under 0.1 s"
    return f"{ms / 1000:.1f} s"


def _parse(raw: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _member(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    m = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    got = m.get("member_app")
    return got if isinstance(got, dict) else None


def _sum(blocks: List[Dict[str, Any]], side: str, kinds: Iterable[str]) -> List[int]:
    kinds = list(kinds)
    hs = []
    for b in blocks:
        by_kind = b.get(side)
        if not isinstance(by_kind, dict):
            continue
        for k in kinds:
            if isinstance(by_kind.get(k), dict):
                hs.append(by_kind[k].get("h"))
    return merge(hs)


def _stat(h: List[int]) -> Optional[Dict[str, Any]]:
    n = sum(h)
    if not n:
        return None
    return {"n": n, "typical_ms": round(from_hist(h, 0.5) or 0), "slow_ms": round(from_hist(h, 0.9) or 0)}


def _words(stat: Optional[Dict[str, Any]]) -> str:
    return f"{_secs(stat['typical_ms'])} typical, {_secs(stat['slow_ms'])} for the slowest 1 in 10"


def block(rows: List[Dict[str, Any]], label: str) -> Optional[Dict[str, Any]]:
    """Several readings' member numbers added up, in words. None when none
    of them has any."""
    blocks = [b for b in (_member(r) for r in rows) if b]
    if not blocks:
        return None
    ready = _stat(_sum(blocks, "ready", PAGE_KINDS))
    first = _stat(_sum(blocks, "first_byte", PAGE_KINDS))
    server = _stat(_sum(blocks, "server", PAGE_KINDS))
    pages = []
    for kind, name in KINDS:
        row = {"kind": kind, "label": name, "ready": _stat(_sum(blocks, "ready", [kind])),
               "server": _stat(_sum(blocks, "server", [kind]))}
        if row["ready"] or row["server"]:
            pages.append(row)
    if ready:
        line = f"Tabs open in {_words(ready)} ({label})."
    elif server:
        line = (f"The server answers member pages in {_words(server)} ({label}). "
                "No timings from phones came in.")
    else:
        send = _stat(_sum(blocks, "server", ["send", "save"]))
        if not send:
            return None
        line = f"Saves took {_words(send)} on the server ({label})."
    server_line = f"The server's share of a page: {_words(server)}." if ready and server else None
    first_line = f"The first of the page reaches the phone in {_words(first)}." if ready and first else None
    return {"label": label, "readings": len(blocks), "ready": ready, "first_byte": first, "server": server,
            "pages": pages, "line": line, "server_line": server_line, "first_line": first_line}


NOTE = ("Timed on members' phones, from the tap until the page can be used, and on the server. The "
        "server runs as several copies; each reading keeps the numbers of the copy that took it, a fair "
        "sample while visits are shared out evenly. Sign-in pages and your previews don't count.")
OFF = "The member app's stopwatch is switched off on the server, so no timings are saved."
EMPTY = ("No member app timings yet. They're saved with every reading from now on: Sunday morning, "
         "Wednesday, and whenever you press Check now.")


def card(in_week: List[Dict[str, Any]], rows: List[Dict[str, Any]], *, so_far: bool,
         when_words: Callable[[datetime], str]) -> Dict[str, Any]:
    """The card's member app section: last Sunday's readings added up, and
    the newest reading that has member numbers when it isn't one of those."""
    sunday_rows = [r for r in in_week if r.get("kind") == "sunday" and _member(r)]
    sunday = block(sunday_rows, "this morning so far" if so_far else "last Sunday")
    newest = None
    have = sorted((r for r in rows if _member(r) and _parse(r.get("taken_at"))),
                  key=lambda r: _parse(r["taken_at"]))
    if have and have[-1] not in sunday_rows:
        last = have[-1]
        at = _parse(last["taken_at"])
        if last.get("kind") in ("sunday", "weekday"):
            # A scheduled reading holds its last 15 minutes: the day's add up.
            same = [r for r in have if r.get("kind") == last.get("kind")
                    and _parse(r["taken_at"]).date() == at.date()]
            newest = block(same, f"{when_words(at).split(' at ')[0]} morning")
        else:
            newest = block([last], f"the hour before {when_words(at)}")
        if newest:
            newest["at"] = last.get("taken_at")
    main = sunday or newest
    headline = main["line"] if main else (EMPTY if enabled() else OFF)
    return {"headline": headline, "sunday": sunday, "latest": newest, "note": NOTE, "has_numbers": bool(main)}


# ─── Timing one request ─────────────────────────────────────────────────

class _Watch:
    __slots__ = ("t0", "total", "parts", "results")

    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.total: Optional[float] = None
        self.parts: Dict[str, float] = {}
        self.results: Dict[str, Any] = {}

    def add(self, part: str, ms: float, result: Any) -> None:
        self.parts[part] = self.parts.get(part, 0.0) + ms
        self.results[part] = result

    def stop(self) -> float:
        if self.total is None:
            self.total = (time.perf_counter() - self.t0) * 1000
        return self.total

    def header(self) -> str:
        total = self.stop()
        bits = [f"total;dur={total:.1f}"]
        for part, desc in (("church", "church lookup"), ("session", "signed-in member")):
            if part in self.parts:
                bits.append(f'{part};desc="{desc}";dur={self.parts[part]:.1f}')
        rest = max(total - sum(self.parts.values()), 0.0)
        bits.append(f'rest;desc="the page itself";dur={rest:.1f}')
        return ", ".join(bits)


_current: contextvars.ContextVar[Optional[_Watch]] = contextvars.ContextVar("member_stopwatch", default=None)


def timed(part: str):
    """Add the wrapped (sync) call's time to this request's `part`. Outside
    a timed request it's a plain call."""
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*a, **k):
            w = _current.get()
            if w is None:
                return fn(*a, **k)
            t0 = time.perf_counter()
            result = None
            try:
                result = fn(*a, **k)
                return result
            finally:
                try:
                    w.add(part, (time.perf_counter() - t0) * 1000, result)
                except Exception:  # noqa: BLE001
                    pass
        return inner
    return wrap


def _host(scope) -> str:
    from starlette.requests import Request as _Req
    import public_site
    return public_site.public_host(_Req(scope))


def _signed_in(w: _Watch) -> bool:
    s = w.results.get("session")
    return isinstance(s, dict) and bool(s.get("me")) and not s.get("unavailable") and not s.get("preview")


def _remember_host(host: str, church: Any) -> None:
    if not host or not isinstance(church, dict) or not isinstance(church.get("business"), dict):
        return
    import member_portal
    biz = church["business"]
    entry = (time.monotonic() + KNOWN_HOST_SECONDS, str(biz.get("id") or ""), member_portal._epoch(biz))
    with _lock:
        if len(_known) >= KNOWN_HOST_MAX:
            _known.clear()
        _known[host] = entry


def finish(method: str, path: str, status: int, w: _Watch, host: str = "") -> Optional[str]:
    """After a timed request: the log line (returned too, for the tests),
    the sample, and the host it was served on."""
    total = w.stop()
    kind = kind_of(method, path)
    line = None
    if kind in LABEL or status >= 500 or total >= SLOW_MS:
        parts = " ".join(f"{p}={round(ms)}" for p, ms in w.parts.items())
        line = f"[member] {method} {pattern(path)} {status} {round(total)}ms{' ' + parts if parts else ''}"
        print(line, flush=True)
    if kind in LABEL and _signed_in(w):
        ok = status == 200 if kind in PAGE_KINDS else 200 <= status < 400
        if ok:
            record("server", kind, total)
        if host:
            _remember_host(host, w.results.get("church"))
    return line


class MemberStopwatch:
    """Times every /my request (pure ASGI: it only adds a header to the
    response start, never touches a body). Add it outside GZipMiddleware so
    the total includes compressing the page."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = str(scope.get("path") or "")
        if scope.get("type") != "http" or not is_member_path(path):
            await self.app(scope, receive, send)
            return
        try:
            on = enabled()
        except Exception:  # noqa: BLE001
            on = False
        if not on:
            await self.app(scope, receive, send)
            return
        w = _Watch()
        token = _current.set(w)
        seen = {"status": 500}

        async def timed_send(message):
            if message.get("type") == "http.response.start":
                seen["status"] = int(message.get("status") or 0)
                try:
                    headers = list(message.get("headers") or [])
                    headers.append((b"server-timing", w.header().encode("latin-1")))
                    message = {**message, "headers": headers}
                except Exception:  # noqa: BLE001 — the page goes out without the header
                    pass
            await send(message)

        try:
            await self.app(scope, receive, timed_send)
        finally:
            _current.reset(token)
            try:
                finish(str(scope.get("method") or "GET"), path, seen["status"], w, _host(scope))
            except Exception as e:  # noqa: BLE001
                print(f"[member] stopwatch failed: {type(e).__name__}", flush=True)


# ─── The phone's part ───────────────────────────────────────────────────

# Runs once the page can be used; a page restored from the back/forward
# cache, or one the browser can't time, sends nothing. A prerendered page is
# timed from when it was shown (activationStart).
_JS = ("<script>(function(){try{var P=window.performance,N=navigator;"
       "if(!N.sendBeacon||!P||!P.getEntriesByType)return;"
       "function go(){var n=P.getEntriesByType('navigation')[0];"
       "if(!n||!(n.domContentLoadedEventEnd>0)||(n.type!=='navigate'&&n.type!=='reload'))return;"
       "var a=n.activationStart||0;"
       "N.sendBeacon('/my/timing',JSON.stringify({p:location.pathname.replace(/[^\\/]*\\d[^\\/]*/g,':id'),"
       "f:Math.max(0,Math.round(n.responseStart-a)),r:Math.max(0,Math.round(n.domContentLoadedEventEnd-a)),"
       "t:n.type==='reload'?1:0}))}"
       "if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',function(){setTimeout(go,0)});"
       "else setTimeout(go,0)}catch(e){}})();</script>")


def phone_js() -> str:
    """The inline script for a signed-in page, or nothing when off."""
    try:
        return _JS if enabled() else ""
    except Exception:  # noqa: BLE001
        return ""


def _from_own_page(request: Request) -> bool:
    import member_portal
    h = request.headers
    if not (h.get("origin") or h.get("referer") or h.get("sec-fetch-site")):
        return False
    return member_portal._same_origin(request)


async def _church_for(request: Request, host: str) -> Optional[Tuple[str, int]]:
    """(business id, sign-out epoch) of the church on this address: what this
    process saw serve a member page in the last 10 minutes, else one read."""
    with _lock:
        hit = _known.get(host)
    if hit and hit[0] > time.monotonic():
        return hit[1], hit[2]
    import asyncio
    import member_portal
    church = await asyncio.to_thread(member_portal._church_for_request, request)
    if not church or not member_portal.portal_active(church["business"]):
        return None
    _remember_host(host, church)
    biz = church["business"]
    return str(biz["id"]), member_portal._epoch(biz)


def _signed_session(cookie: str) -> Optional[Dict[str, Any]]:
    """A member session cookie whose signature holds, for the church it
    names, checked before anything is read: a made-up cookie never costs a
    database read. The address is matched to that church after."""
    import member_portal
    try:
        payload = cookie.split(".", 1)[0]
        biz = str(json.loads(member_portal._unb64(payload)).get("biz") or "")
    except Exception:  # noqa: BLE001
        return None
    if not biz:
        return None
    return member_portal.read_session(cookie, biz)


def _clean(body: bytes) -> Optional[Tuple[str, float, float]]:
    """(kind, first byte ms, ready ms) from the beacon, or None."""
    if not body or len(body) > 512:
        return None
    try:
        got = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(got, dict):
        return None
    p, f, r = got.get("p"), got.get("f"), got.get("r")
    if not isinstance(p, str) or len(p) > 200 or not is_member_path(p):
        return None
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in (f, r)):
        return None
    f, r = float(f), float(r)
    if not (math.isfinite(f) and math.isfinite(r)) or f < 0 or r <= 0 or r > MAX_MS or f > r:
        return None
    kind = kind_of("GET", p)
    if kind not in PAGE_KINDS:
        return None
    return kind, f, r


@router.post("/my/timing", include_in_schema=False)
async def phone_timing(request: Request):
    """The phone's beacon (PHONE_JS). Nothing reads the answer; refusals
    still say what they are, for anyone debugging."""
    done = Response(status_code=204, headers={"Cache-Control": "no-store"})
    if not enabled():
        return done
    import member_portal
    import member_portal_preview as pv
    import public_site
    import rate_limit
    host = public_site.public_host(request)
    if public_site._is_api_host(host):
        return Response(status_code=404)
    if not _from_own_page(request):
        return Response(status_code=403)
    if not rate_limit.allow("member_timing", rate_limit.trusted_client_ip(request)):
        return Response(status_code=429)
    if request.cookies.get(pv.PREVIEW_COOKIE):
        return done
    claims = _signed_session(request.cookies.get(member_portal.SESSION_COOKIE) or "")
    if not claims:
        return done
    got = _clean(await request.body())
    if not got:
        return Response(status_code=400)
    church = await _church_for(request, host)
    if not church:
        return Response(status_code=404)
    if church[0] != str(claims["biz"]) or int(claims.get("iat") or 0) < int(church[1] or 0):
        return done
    kind, first, ready = got
    record("first_byte", kind, first)
    record("ready", kind, ready)
    return done
