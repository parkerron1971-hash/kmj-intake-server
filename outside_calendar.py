"""
outside_calendar.py — the practitioner's OTHER calendar, read as busy times.

WHY. For a barber, a therapist or a coach the calendar IS the business,
and until now there was no way in: the only Google scope is
gmail.readonly, there was no ICS import, and a practitioner who kept
Calendly, Acuity, Square or their phone's calendar got double-booked.
The pricing FAQ promises "you can keep Calendly ... and Solutionist
will work around it". This is the thing that makes that true.

HOW. A private calendar feed (iCal / ICS link), not OAuth. Google's
"secret address in iCal format", Outlook's published calendar, an
iCloud public calendar link and Acuity's sync feed are all the same
thing: an https URL that returns a VCALENDAR. Calendly and Square users
come in through the Google or Outlook calendar those tools already
write into. No OAuth means no new scope on the pending Google app
verification.

WHAT IS STORED. Busy times only: start, end, all-day, and a hash of the
event's UID (so a re-sync updates rather than duplicates). No titles,
attendees, descriptions or locations are ever read into storage: those
belong to other people.

THE FEED URL IS A SECRET, like a password. Anyone holding a Google
secret address can read the whole calendar. So it is never returned
whole to the client (mask_url), never put in a log line, and never
echoed in an error. Database error bodies for calendar_feeds are not
logged either, because a Postgres constraint error quotes the failing
row. Only this module and the database ever see it.

SSRF. Fetching a URL a user typed is a server-side request forgery
risk, so fetch_feed() is strict: https only (webcal:// becomes
https://), port 443, no credentials in the URL, no IP-literal hosts,
DNS resolved by us and EVERY address checked (private, loopback,
link-local, multicast, reserved, CGNAT and cloud-metadata ranges,
IPv4 and IPv6, including IPv4 embedded in IPv6), and the connection is
PINNED to the address that was checked, so a second DNS answer cannot
swap in an internal host (DNS rebinding). Redirects are followed by
hand, at most 3, each hop re-checked and still https. 10 seconds and
5 MB, streamed, compressed bodies decompressed with the same cap. The
body must start with BEGIN:VCALENDAR.

MULTIPLE REPLICAS. The scheduled sync is leader-gated
(scheduler_lock.gate), and every sync of one feed first CLAIMS it with
an atomic PATCH on sync_lock_until, so a "sync now" on one replica and
the tick on another cannot interleave. Within a claim the sync is
idempotent: upsert on (feed_id, uid_hash, starts_at), stamp the run id,
then delete that feed's rows from any other run. Stale rows are only
deleted when every upsert landed, so a half-failed write never erases
good busy times.

FAILS SOFT. Until supabase/APPLY-2026-09-26-calendar-feeds.sql is
applied, reads return nothing (slots behave exactly as before) and the
endpoints say "not set up yet". A failing feed records last_error in
plain words, backs off, keeps its last good busy times, and never
throws out of the scheduler. Nothing here costs money, so nothing is
metered.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import socket
import threading
import time as _time
import uuid
import zlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeout
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

import httpx

import sb_clients

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

logger = logging.getLogger("outside_calendar")

# ─── Limits ──────────────────────────────────────────────────────────

FETCH_TIMEOUT_S = 10.0
MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
DNS_TIMEOUT_S = 5.0
HORIZON_DAYS = 60
MAX_BLOCKS_PER_FEED = 2000
# Occurrences looked at (busy or not) before giving up on a feed. Bounds
# a hostile RRULE (FREQ=SECONDLY) that would otherwise expand forever.
MAX_OCCURRENCES_SCANNED = 20000
MAX_FEEDS_PER_BUSINESS = 5
SYNC_EVERY_MIN = 15
MAX_BACKOFF_MIN = 360
CLAIM_SECONDS = 120
SYNC_NOW_COOLDOWN_S = 30
TICK_BATCH = 25
TICK_BUDGET_S = 240
_UPSERT_CHUNK = 500
_ABSENT_TTL_S = 300
_USER_AGENT = "SolutionistCalendarSync/1.0 (+https://mysolutionist.app)"

FEEDS = "calendar_feeds"
BLOCKS = "calendar_busy_blocks"

# What the client may see about a feed. Never `url`.
_FEED_PUBLIC_COLS = ("id,label,provider,status,last_synced_at,last_error,"
                     "busy_count,created_at,updated_at")


# ─── Plain-language errors ───────────────────────────────────────────

class FeedError(Exception):
    """A feed problem the practitioner can read. The message is shown
    in the app and stored as last_error, so it is plain words and
    NEVER contains the URL."""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.message = message
        self.retryable = retryable


MSG_BAD_URL = ("That doesn't look like a calendar link. Copy the full link "
               "from your calendar's sharing settings.")
MSG_NOT_HTTPS = ("Calendar links need to start with https:// or webcal://. "
                 "Copy the link again from your calendar's sharing settings.")
MSG_PRIVATE = ("That link points to a private network address, so we can't "
               "read it. Use the secret or public link your calendar gives you.")
MSG_DNS = "We couldn't find that web address. Check the link and try again."
MSG_TIMEOUT = ("Your calendar took too long to answer. We'll try again in a "
               "few minutes.")
MSG_CONNECT = "We couldn't reach your calendar. We'll try again in a few minutes."
MSG_TOO_BIG = ("That calendar is too large to read (over 5 MB). Try sharing a "
               "calendar with fewer events.")
MSG_NOT_ICS = ("That link didn't return a calendar. Make sure you copied the "
               "iCal (.ics) link, not the address of the calendar page.")
MSG_UNREADABLE = ("We couldn't read that calendar file. Make sure you copied "
                  "the iCal (.ics) link.")
MSG_AUTH = ("Your calendar asked for a sign-in. Use the secret or public iCal "
            "link, which works without one.")
MSG_GONE = ("That calendar link no longer works. It may have been reset: copy "
            "a fresh link and connect it again.")
MSG_REDIRECTS = ("That link bounced through too many addresses. Copy the "
                 "calendar's direct iCal link.")
MSG_SAVE = ("Your calendar was read, but we couldn't save its busy times. "
            "We'll try again in a few minutes.")


def _http_error_message(status: int) -> str:
    if status in (401, 403):
        return MSG_AUTH
    if status in (404, 410):
        return MSG_GONE
    return (f"Your calendar service had a problem (error {status}). "
            "We'll try again in a few minutes.")


# ─── URL handling ────────────────────────────────────────────────────

_BLOCKED_HOST_SUFFIXES = (".local", ".localhost", ".internal", ".lan",
                          ".home.arpa", ".intranet", ".corp")


def normalize_feed_url(raw: str) -> str:
    """Canonical https URL for a pasted calendar link, or FeedError.

    webcal:// and webcals:// are the same feed over https. http:// is
    refused rather than upgraded: a feed that only answers on plain http
    would send its secret in the clear on every sync."""
    value = str(raw or "").strip()
    if not value or len(value) > 2048:
        raise FeedError(MSG_BAD_URL, retryable=False)
    if any(ord(c) < 33 or c == "\\" for c in value):
        raise FeedError(MSG_BAD_URL, retryable=False)
    lower = value.lower()
    if lower.startswith("webcals://"):
        value = "https://" + value[len("webcals://"):]
    elif lower.startswith("webcal://"):
        value = "https://" + value[len("webcal://"):]
    try:
        p = urlsplit(value)
        port = p.port
    except ValueError:
        raise FeedError(MSG_BAD_URL, retryable=False) from None
    if p.scheme.lower() != "https":
        raise FeedError(MSG_NOT_HTTPS, retryable=False)
    if p.username or p.password or "@" in (p.netloc or ""):
        raise FeedError(MSG_BAD_URL, retryable=False)
    host = (p.hostname or "").strip().rstrip(".")
    if not host:
        raise FeedError(MSG_BAD_URL, retryable=False)
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise FeedError(MSG_BAD_URL, retryable=False) from None
    if port not in (None, 443):
        raise FeedError(MSG_BAD_URL, retryable=False)
    try:
        ipaddress.ip_address(host)
        # An IP literal. No calendar service hands these out, and a
        # hostname is what lets TLS prove who answered.
        raise FeedError(MSG_PRIVATE, retryable=False)
    except ValueError:
        pass
    if "." not in host or host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise FeedError(MSG_PRIVATE, retryable=False)
    return urlunsplit(("https", host, p.path or "/", p.query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def mask_url(url: str) -> str:
    """Host plus the last 4 characters of the link's secret part, e.g.
    ``calendar.google.com ····a1b2``. The secret part is the longest
    path segment or query value, which for every provider we know is
    the token."""
    try:
        p = urlsplit(url)
    except ValueError:
        return "calendar link"
    host = p.hostname or "calendar link"
    parts = [s for s in (p.path or "").split("/") if s]
    parts += [v for _, v in parse_qsl(p.query or "", keep_blank_values=False)]
    token = max(parts, key=len) if parts else ""
    tail = token[-4:] if len(token) >= 8 else ""
    return f"{host} ····{tail}" if tail else host


def detect_provider(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()

    def on(*domains: str) -> bool:
        return any(host == d or host.endswith("." + d) for d in domains)

    if on("google.com"):
        return "google"
    if on("outlook.com", "office365.com", "office.com", "live.com"):
        return "outlook"
    if on("icloud.com"):
        return "icloud"
    if on("acuityscheduling.com", "as.me"):
        return "acuity"
    if on("calendly.com"):
        return "calendly"
    if on("squareup.com", "square.site"):
        return "square"
    return "other"


_PROVIDER_LABEL = {
    "google": "Google Calendar", "outlook": "Outlook", "icloud": "iCloud",
    "acuity": "Acuity", "calendly": "Calendly", "square": "Square",
    "other": "My calendar",
}


# ─── SSRF guard ──────────────────────────────────────────────────────

def address_blocked(addr: str) -> bool:
    """True when a server-side fetch must never connect to `addr`.

    Only globally routable unicast addresses pass. That excludes RFC1918,
    loopback, link-local (169.254.169.254, the cloud metadata address),
    CGNAT (100.64/10, Alibaba's metadata at 100.100.100.200), ULA
    (fd00:ec2::254, AWS's IPv6 metadata), multicast, reserved and
    unspecified. IPv4 carried inside IPv6 (mapped, 6to4, Teredo, NAT64)
    is unwrapped and judged as the IPv4 it is."""
    try:
        ip = ipaddress.ip_address(str(addr).split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour
        if embedded is None and ip.teredo:
            embedded = ip.teredo[1]
        if embedded is None and ip in ipaddress.ip_network("64:ff9b::/96"):
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if embedded is not None and address_blocked(str(embedded)):
            return True
    return bool(
        not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


_dns_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="calfeed-dns")


def _resolve_host(host: str) -> List[str]:
    """Every address `host` resolves to (tests replace this)."""
    fut = _dns_pool.submit(socket.getaddrinfo, host, 443, 0, socket.SOCK_STREAM)
    infos = fut.result(timeout=DNS_TIMEOUT_S)
    return list(dict.fromkeys(info[4][0] for info in infos))


def _public_address(host: str) -> str:
    """The address to connect to, after checking ALL of them. One bad
    answer refuses the host: a name that resolves to a public and a
    private address is exactly what a rebinding attack looks like."""
    try:
        addrs = _resolve_host(host)
    except (_FutureTimeout, TimeoutError):
        raise FeedError(MSG_TIMEOUT) from None
    except (socket.gaierror, OSError, UnicodeError):
        raise FeedError(MSG_DNS) from None
    if not addrs:
        raise FeedError(MSG_DNS)
    if any(address_blocked(a) for a in addrs):
        raise FeedError(MSG_PRIVATE, retryable=False)
    return addrs[0]


# httpx writes "HTTP Request: GET <url>" at INFO. The pinned URL carries
# the feed's secret path, so while a feed fetch is running on this
# thread those records are dropped. Scoped by thread, so every other
# request in the process logs exactly as before.
_quiet = threading.local()


class _QuietFeedFetch(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(_quiet, "on", False)


for _name in ("httpx", "httpcore"):
    _lg = logging.getLogger(_name)
    if not any(isinstance(f, _QuietFeedFetch) for f in _lg.filters):
        _lg.addFilter(_QuietFeedFetch())


def _make_client() -> httpx.Client:
    """One client per hop (tests replace this). No env proxies, no
    redirects, no connection reuse across hostnames."""
    return httpx.Client(timeout=httpx.Timeout(FETCH_TIMEOUT_S),
                        follow_redirects=False, trust_env=False)


def _read_capped(resp: httpx.Response, deadline: float) -> bytes:
    enc = (resp.headers.get("content-encoding") or "").strip().lower()
    if enc in ("", "identity"):
        decoder = None
    elif enc in ("gzip", "x-gzip"):
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif enc == "deflate":
        decoder = zlib.decompressobj()
    else:
        raise FeedError(MSG_UNREADABLE)
    try:
        declared = int(resp.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > MAX_BYTES:
        raise FeedError(MSG_TOO_BIG, retryable=False)
    out = bytearray()
    raw_total = 0
    for chunk in resp.iter_raw():
        if _time.monotonic() > deadline:
            raise FeedError(MSG_TIMEOUT)
        raw_total += len(chunk)
        if raw_total > MAX_BYTES:
            raise FeedError(MSG_TOO_BIG, retryable=False)
        if decoder is None:
            out.extend(chunk)
        else:
            try:
                piece = decoder.decompress(chunk, MAX_BYTES + 1 - len(out))
            except zlib.error:
                raise FeedError(MSG_UNREADABLE) from None
            out.extend(piece)
            if decoder.unconsumed_tail:
                raise FeedError(MSG_TOO_BIG, retryable=False)
        if len(out) > MAX_BYTES:
            raise FeedError(MSG_TOO_BIG, retryable=False)
    return bytes(out)


def _looks_like_ics(body: bytes) -> bool:
    head = body[:2048].lstrip(b"\xef\xbb\xbf \t\r\n")
    return head[:15].upper() == b"BEGIN:VCALENDAR"


def fetch_feed(url: str) -> bytes:
    """GET a calendar feed under every SSRF guard (module docstring).
    Returns the VCALENDAR bytes or raises FeedError."""
    current = normalize_feed_url(url)
    deadline = _time.monotonic() + FETCH_TIMEOUT_S
    _quiet.on = True
    try:
        for _hop in range(MAX_REDIRECTS + 1):
            p = urlsplit(current)
            host = p.hostname or ""
            address = _public_address(host)
            authority = f"[{address}]" if ":" in address else address
            pinned = urlunsplit(("https", authority, p.path or "/", p.query, ""))
            try:
                with _make_client() as client:
                    with client.stream(
                        "GET", pinned,
                        headers={
                            "Host": host,
                            "User-Agent": _USER_AGENT,
                            "Accept": "text/calendar, text/plain;q=0.8, */*;q=0.5",
                            "Accept-Encoding": "gzip, deflate",
                            "Connection": "close",
                        },
                        # TLS: SNI and certificate verification use the
                        # hostname, not the pinned address.
                        extensions={"sni_hostname": host},
                    ) as resp:
                        status = resp.status_code
                        if status in (301, 302, 303, 307, 308):
                            loc = resp.headers.get("location") or ""
                            if not loc:
                                raise FeedError(MSG_CONNECT)
                            try:
                                current = normalize_feed_url(urljoin(current, loc))
                            except FeedError as e:
                                # A redirect off https or into a private
                                # name reads to the user as the link's
                                # own fault; say which.
                                raise FeedError(
                                    MSG_PRIVATE if e.message == MSG_PRIVATE else MSG_NOT_HTTPS,
                                    retryable=False) from None
                            continue
                        if status >= 400:
                            raise FeedError(_http_error_message(status),
                                            retryable=status not in (401, 403, 404, 410))
                        if status != 200:
                            raise FeedError(MSG_NOT_ICS)
                        body = _read_capped(resp, deadline)
            except FeedError:
                raise
            except httpx.TimeoutException:
                raise FeedError(MSG_TIMEOUT) from None
            except (httpx.HTTPError, OSError, ValueError):
                raise FeedError(MSG_CONNECT) from None
            if not _looks_like_ics(body):
                raise FeedError(MSG_NOT_ICS, retryable=False)
            return body
        raise FeedError(MSG_REDIRECTS, retryable=False)
    finally:
        _quiet.on = False


# ─── ICS → busy blocks ───────────────────────────────────────────────

def _zone(tz_name: Optional[str]):
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo((tz_name or "UTC").strip() or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _iso_z(dt: datetime) -> str:
    """UTC, Z form. '+00:00' reads as a space in a PostgREST query string
    and silently kills the filter (the 2026-07-21 bug class)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_utc(value: Any, tz) -> Optional[datetime]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)       # floating time → business tz
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time(0), tzinfo=tz).astimezone(timezone.utc)
    return None


def _prop(component: Any, name: str) -> str:
    try:
        v = component.get(name)
    except Exception:
        return ""
    return str(v or "").strip().upper()


def _is_free(component: Any) -> bool:
    """Events that do not make the practitioner busy: marked free
    (TRANSP:TRANSPARENT, or Outlook's busy-status FREE) or cancelled."""
    return (_prop(component, "TRANSP") == "TRANSPARENT"
            or _prop(component, "STATUS") == "CANCELLED"
            or _prop(component, "X-MICROSOFT-CDO-BUSYSTATUS") == "FREE")


def _span(component: Any, tz) -> Optional[Tuple[datetime, datetime, bool]]:
    try:
        raw_start = component.decoded("DTSTART")
    except Exception:
        return None
    all_day = isinstance(raw_start, date) and not isinstance(raw_start, datetime)
    raw_end: Any = None
    try:
        if component.get("DTEND") is not None:
            raw_end = component.decoded("DTEND")
        elif component.get("DURATION") is not None:
            raw_end = raw_start + component.decoded("DURATION")
    except Exception:
        raw_end = None
    if raw_end is None:
        # RFC 5545: a date event with no end lasts the day; a timed one
        # with no end is an instant, which blocks nothing.
        raw_end = raw_start + timedelta(days=1) if all_day else raw_start
    start = _as_utc(raw_start, tz)
    end = _as_utc(raw_end, tz)
    if start is None or end is None:
        return None
    if all_day and end <= start:
        end = start + timedelta(days=1)
    if end <= start:
        return None
    return start, end, all_day


def _uid_hash(component: Any, start: datetime, end: datetime) -> str:
    uid = str(component.get("UID") or "").strip()
    basis = uid or f"no-uid|{_iso_z(start)}|{_iso_z(end)}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:40]


def parse_busy_blocks(ics: bytes, *, tz_name: Optional[str] = None,
                      now: Optional[datetime] = None,
                      horizon_days: int = HORIZON_DAYS,
                      max_blocks: int = MAX_BLOCKS_PER_FEED) -> List[Dict[str, Any]]:
    """Busy blocks from a VCALENDAR over [now - 1 day, now + horizon).

    Recurrences are expanded (RRULE, RDATE, EXDATE, RECURRENCE-ID
    overrides) by recurring_ical_events; X-WR-TIMEZONE is honoured.
    Floating times and all-day dates are read in `tz_name` (the
    business's zone). Free and cancelled events are skipped. Returns
    [{uid_hash, starts_at, ends_at, all_day}] sorted by start, capped at
    max_blocks. Only times leave this function."""
    try:
        import icalendar
        import recurring_ical_events
    except Exception:  # pragma: no cover — requirements.txt pins both
        raise FeedError(MSG_UNREADABLE)

    tz = _zone(tz_name)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    window_start = now - timedelta(days=1)
    window_end = now + timedelta(days=horizon_days)

    try:
        cal = icalendar.Calendar.from_ical(ics)
        query = recurring_ical_events.of(cal, skip_bad_series=True)
        occurrences = query.after(window_start.astimezone(tz))
    except Exception:
        raise FeedError(MSG_UNREADABLE) from None

    blocks: Dict[Tuple[str, str], Dict[str, Any]] = {}
    scanned = 0
    try:
        for component in occurrences:
            scanned += 1
            if scanned > MAX_OCCURRENCES_SCANNED:
                break
            span = _span(component, tz)
            if span is None:
                continue
            start, end, all_day = span
            if start >= window_end:
                break              # after() yields in start order
            if end <= window_start or _is_free(component):
                continue
            key = (_uid_hash(component, start, end), _iso_z(start))
            prior = blocks.get(key)
            if prior is not None:
                if _iso_z(end) > prior["ends_at"]:
                    prior["ends_at"] = _iso_z(end)
                continue
            blocks[key] = {"uid_hash": key[0], "starts_at": key[1],
                           "ends_at": _iso_z(end), "all_day": all_day}
            if len(blocks) >= max_blocks:
                break
    except FeedError:
        raise
    except Exception:
        # A series that breaks mid-expansion: keep what was read if any,
        # otherwise the file is unreadable.
        if not blocks:
            raise FeedError(MSG_UNREADABLE) from None
    return sorted(blocks.values(), key=lambda b: (b["starts_at"], b["uid_hash"]))


# ─── Database (service role, secret-safe) ────────────────────────────

_absent_until = 0.0


def _mark_absent() -> None:
    global _absent_until
    _absent_until = _time.monotonic() + _ABSENT_TTL_S


def tables_known_absent() -> bool:
    return _time.monotonic() < _absent_until


def _table_of(path: str) -> str:
    return path.lstrip("/").split("?", 1)[0]


def _rest(method: str, path: str, body: Any = None,
          prefer: Optional[str] = "return=representation") -> Tuple[int, Any]:
    """(status, json) for one PostgREST call with the SERVICE ROLE.

    Logs the method, table and status only. Never the body (it can hold
    the feed URL) and never PostgREST's error text (a constraint error
    quotes the failing row, which can hold the feed URL). Status 0 means
    not configured or not reachable. A 404 for a missing table flips the
    module to "not set up" for a few minutes."""
    base = sb_clients.sb_url()
    if not base or not sb_clients.sb_service_role():
        return 0, None
    try:
        headers = sb_clients.sb_headers_service(prefer=prefer)
    except RuntimeError:
        return 0, None
    try:
        with httpx.Client(timeout=sb_clients.HTTP_TIMEOUT) as client:
            resp = client.request(
                method, f"{base}/rest/v1{path}", headers=headers,
                content=json.dumps(body) if body is not None else None)
    except httpx.HTTPError as e:
        logger.warning("[calendar] %s %s transport error: %s",
                       method, _table_of(path), type(e).__name__)
        return 0, None
    data: Any = None
    if resp.text:
        try:
            data = resp.json()
        except ValueError:
            data = None
    if resp.status_code >= 400:
        code = data.get("code") if isinstance(data, dict) else None
        if resp.status_code == 404 and code in ("PGRST205", "42P01", None):
            _mark_absent()
        logger.warning("[calendar] %s %s -> %s %s", method, _table_of(path),
                       resp.status_code, code or "")
        return resp.status_code, None
    return resp.status_code, data


def _missing(status: int) -> bool:
    return status == 404


# ─── Business time zone ──────────────────────────────────────────────

def business_timezone(business_id: str) -> str:
    """The engine's one chain: availability.timezone → the owner's
    practitioner_profiles.timezone → PLATFORM_DEFAULT_TZ → UTC. The
    businesses table has no timezone column of its own."""
    try:
        from availability import BusinessAvailability
        from availability_engine import resolved_tz_name
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}&select=owner_id,settings&limit=1") or []
        biz = rows[0] if rows else {}
        av = BusinessAvailability.from_settings_dict(
            (biz.get("settings") or {}).get("availability"))
        practitioner_tz = None
        if biz.get("owner_id"):
            prof = sb_clients.sb_get_as_service(
                f"/practitioner_profiles?owner_id=eq.{biz['owner_id']}"
                "&select=timezone&limit=1") or []
            practitioner_tz = ((prof[0].get("timezone") or "").strip() or None) if prof else None
        return resolved_tz_name(av, practitioner_tz)
    except Exception:
        return (os.environ.get("PLATFORM_DEFAULT_TZ") or "UTC").strip() or "UTC"


# ─── Busy reads (the booking paths) ──────────────────────────────────

def busy_blocks_between(business_id: str, lo: datetime,
                        hi: datetime) -> List[Dict[str, Any]]:
    """Every outside busy block overlapping [lo, hi). Fails soft to []
    (not set up, not configured, database blip), so the booking paths
    behave exactly as they did before this feature existed."""
    if not business_id or tables_known_absent():
        return []
    status, rows = _rest(
        "GET",
        f"/{BLOCKS}?business_id=eq.{business_id}"
        f"&starts_at=lt.{_iso_z(hi)}&ends_at=gt.{_iso_z(lo)}"
        "&select=starts_at,ends_at,all_day&order=starts_at.asc&limit=5000",
        prefer=None)
    return rows if isinstance(rows, list) else []


def busy_blocks_for_dates(business_id: str, from_date: date,
                          to_date: date) -> List[Dict[str, Any]]:
    """Blocks for a slot window of business-tz days, padded a day each
    side so no time zone can push an overlap out of the read."""
    lo = datetime.combine(from_date - timedelta(days=1), time(0), tzinfo=timezone.utc)
    hi = datetime.combine(to_date + timedelta(days=2), time(0), tzinfo=timezone.utc)
    return busy_blocks_between(business_id, lo, hi)


def _parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        s = str(value or "")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def busy_intervals(rows: Iterable[Dict[str, Any]]) -> List[Tuple[datetime, datetime]]:
    out = []
    for r in rows or []:
        s, e = _parse_ts(r.get("starts_at")), _parse_ts(r.get("ends_at"))
        if s and e and e > s:
            out.append((s, e))
    return out


def conflicts_with_outside_calendar(business_id: str, start: datetime,
                                    end: datetime) -> bool:
    """True when [start, end) overlaps any outside busy block. The
    booking-time re-check."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        return False
    for s, e in busy_intervals(busy_blocks_between(business_id, start, end)):
        if s < end and start < e:
            return True
    return False


# ─── Feeds: list / connect / remove ──────────────────────────────────

class NotSetUp(Exception):
    """The migration has not been applied yet."""


class FeedConflict(ValueError):
    """A business rule refused the connection (already connected, too
    many calendars). The message is plain words for the practitioner."""


def _public_feed(row: Dict[str, Any], upcoming: int) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "label": row.get("label") or _PROVIDER_LABEL.get(row.get("provider") or "other"),
        "provider": row.get("provider") or "other",
        "status": row.get("status") or "pending",
        "masked_url": row.get("masked_url") or "",
        "last_synced_at": row.get("last_synced_at"),
        "last_error": row.get("last_error"),
        "busy_count": int(row.get("busy_count") or 0),
        "busy_next_14_days": upcoming,
        "created_at": row.get("created_at"),
    }


def list_feeds(business_id: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The practitioner's feeds, masked. {available: False} before the
    migration is applied."""
    now = now or datetime.now(timezone.utc)
    if tables_known_absent():
        return {"ok": True, "available": False, "feeds": []}
    status, rows = _rest(
        "GET", f"/{FEEDS}?business_id=eq.{business_id}"
        f"&select={_FEED_PUBLIC_COLS},url&order=created_at.asc&limit=20", prefer=None)
    if _missing(status):
        return {"ok": True, "available": False, "feeds": []}
    if not isinstance(rows, list):
        raise RuntimeError("calendar feeds unavailable")
    counts: Counter = Counter()
    if rows:
        _, upcoming = _rest(
            "GET", f"/{BLOCKS}?business_id=eq.{business_id}"
            f"&starts_at=lt.{_iso_z(now + timedelta(days=14))}&ends_at=gt.{_iso_z(now)}"
            "&select=feed_id&limit=10000", prefer=None)
        for r in upcoming if isinstance(upcoming, list) else []:
            counts[str(r.get("feed_id"))] += 1
    feeds = []
    for r in rows:
        r = dict(r)
        r["masked_url"] = mask_url(str(r.pop("url", "") or ""))
        feeds.append(_public_feed(r, counts.get(str(r.get("id")), 0)))
    return {"ok": True, "available": True, "feeds": feeds,
            "max_feeds": MAX_FEEDS_PER_BUSINESS}


def _get_feed(business_id: str, feed_id: str) -> Optional[Dict[str, Any]]:
    status, rows = _rest(
        "GET", f"/{FEEDS}?id=eq.{feed_id}&business_id=eq.{business_id}"
        "&select=*&limit=1", prefer=None)
    if _missing(status):
        raise NotSetUp()
    return rows[0] if isinstance(rows, list) and rows else None


def connect_feed(business_id: str, raw_url: str, *, label: Optional[str] = None,
                 created_by: Optional[str] = None,
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    """Validate by fetching once, then save the feed and its busy times.

    Raises FeedError (plain words, nothing saved) when the link cannot
    be read, NotSetUp before the migration, ValueError for the business
    rules (FeedConflict: too many feeds, already connected)."""
    now = now or datetime.now(timezone.utc)
    if tables_known_absent():
        raise NotSetUp()
    url = normalize_feed_url(raw_url)
    h = url_hash(url)

    status, existing = _rest(
        "GET", f"/{FEEDS}?business_id=eq.{business_id}&select=id,url_hash&limit=50",
        prefer=None)
    if _missing(status):
        raise NotSetUp()
    if not isinstance(existing, list):
        raise RuntimeError("calendar feeds unavailable")
    if any(r.get("url_hash") == h for r in existing):
        raise FeedConflict("That calendar is already connected.")
    if len(existing) >= MAX_FEEDS_PER_BUSINESS:
        raise FeedConflict(f"You can connect up to {MAX_FEEDS_PER_BUSINESS} calendars. "
                         "Remove one to add another.")

    tz_name = business_timezone(business_id)
    blocks = parse_busy_blocks(fetch_feed(url), tz_name=tz_name, now=now)

    provider = detect_provider(url)
    clean_label = " ".join(str(label or "").split())[:80] or _PROVIDER_LABEL[provider]
    status, created = _rest("POST", f"/{FEEDS}", {
        "business_id": business_id,
        "label": clean_label,
        "url": url,
        "url_hash": h,
        "provider": provider,
        "status": "pending",
        "created_by": created_by,
    })
    if _missing(status):
        raise NotSetUp()
    if status == 409:
        raise FeedConflict("That calendar is already connected.")
    if not isinstance(created, list) or not created:
        raise RuntimeError("could not save the calendar")
    feed = created[0]
    result = sync_feed(feed, now=now, prefetched=blocks)
    feed = _get_feed(business_id, str(feed["id"])) or feed
    out = dict(feed)
    out["masked_url"] = mask_url(url)
    out.pop("url", None)
    return {"feed": _public_feed(out, _upcoming_count(business_id, str(feed["id"]), now)),
            "sync": result}


def _upcoming_count(business_id: str, feed_id: str, now: datetime) -> int:
    _, rows = _rest(
        "GET", f"/{BLOCKS}?business_id=eq.{business_id}&feed_id=eq.{feed_id}"
        f"&starts_at=lt.{_iso_z(now + timedelta(days=14))}&ends_at=gt.{_iso_z(now)}"
        "&select=id&limit=10000", prefer=None)
    return len(rows) if isinstance(rows, list) else 0


def remove_feed(business_id: str, feed_id: str) -> bool:
    """Delete the feed and every busy block it produced. True when the
    feed existed. Blocks go first so a half-finished removal never
    leaves busy times with no feed to explain them."""
    feed = _get_feed(business_id, feed_id)
    if not feed:
        return False
    _rest("DELETE", f"/{BLOCKS}?feed_id=eq.{feed_id}&business_id=eq.{business_id}",
          prefer="return=minimal")
    status, _ = _rest("DELETE", f"/{FEEDS}?id=eq.{feed_id}&business_id=eq.{business_id}",
                      prefer="return=minimal")
    return 200 <= status < 300


def sync_now(business_id: str, feed_id: str, *,
             now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    feed = _get_feed(business_id, feed_id)
    if not feed:
        raise LookupError("feed not found")
    last = _parse_ts(feed.get("last_synced_at"))
    if (last and feed.get("status") == "ok"
            and (now - last).total_seconds() < SYNC_NOW_COOLDOWN_S):
        result = {"ok": True, "skipped": "just synced", "busy_count": feed.get("busy_count")}
    else:
        result = sync_feed(feed, now=now, force=True)
    fresh = _get_feed(business_id, feed_id) or feed
    fresh = dict(fresh)
    fresh["masked_url"] = mask_url(str(fresh.pop("url", "") or ""))
    return {"feed": _public_feed(fresh, _upcoming_count(business_id, feed_id, now)),
            "sync": result}


# ─── Sync ────────────────────────────────────────────────────────────

def backoff_minutes(failure_count: int) -> int:
    """15, 30, 60, 120, 240, then every 6 hours."""
    n = max(int(failure_count or 1), 1)
    return min(SYNC_EVERY_MIN * (2 ** (n - 1)), MAX_BACKOFF_MIN)


def _claim(feed_id: str, now: datetime) -> bool:
    """Atomically take this feed for one sync. The UPDATE is row-locked,
    so of two replicas racing the same feed exactly one matches."""
    status, rows = _rest(
        "PATCH",
        f"/{FEEDS}?id=eq.{feed_id}"
        f"&or=(sync_lock_until.is.null,sync_lock_until.lt.{_iso_z(now)})",
        {"sync_lock_until": _iso_z(now + timedelta(seconds=CLAIM_SECONDS))})
    return isinstance(rows, list) and len(rows) > 0


def _finish(feed_id: str, now: datetime, fields: Dict[str, Any]) -> None:
    body = dict(fields)
    body["sync_lock_until"] = None
    body["updated_at"] = _iso_z(now)
    _rest("PATCH", f"/{FEEDS}?id=eq.{feed_id}", body, prefer="return=minimal")


def _store_blocks(feed: Dict[str, Any], blocks: List[Dict[str, Any]]) -> bool:
    """Upsert this run's blocks, then delete the feed's blocks from any
    other run. Returns False (and deletes nothing) if any write failed."""
    run = str(uuid.uuid4())
    rows = [{
        "business_id": feed["business_id"],
        "feed_id": feed["id"],
        "starts_at": b["starts_at"],
        "ends_at": b["ends_at"],
        "all_day": bool(b.get("all_day")),
        "uid_hash": b["uid_hash"],
        "sync_run": run,
    } for b in blocks]
    for i in range(0, len(rows), _UPSERT_CHUNK):
        status, _ = _rest(
            "POST", f"/{BLOCKS}?on_conflict=feed_id,uid_hash,starts_at",
            rows[i:i + _UPSERT_CHUNK],
            prefer="resolution=merge-duplicates,return=minimal")
        if not (200 <= status < 300):
            return False
    status, _ = _rest(
        "DELETE",
        f"/{BLOCKS}?feed_id=eq.{feed['id']}&or=(sync_run.is.null,sync_run.neq.{run})",
        prefer="return=minimal")
    return 200 <= status < 300


def sync_feed(feed: Dict[str, Any], *, now: Optional[datetime] = None,
              prefetched: Optional[List[Dict[str, Any]]] = None,
              force: bool = False) -> Dict[str, Any]:
    """Fetch, parse and store one feed. Never raises for a feed problem:
    the outcome is written to the feed row and returned."""
    now = now or datetime.now(timezone.utc)
    feed_id = str(feed.get("id") or "")
    if not feed_id:
        return {"ok": False, "error": "unknown feed"}
    if not _claim(feed_id, now):
        return {"ok": False, "skipped": "already syncing"}
    try:
        if prefetched is not None:
            blocks = prefetched
        else:
            tz_name = business_timezone(str(feed.get("business_id")))
            blocks = parse_busy_blocks(fetch_feed(str(feed.get("url") or "")),
                                       tz_name=tz_name, now=now)
        if not _store_blocks(feed, blocks):
            raise FeedError(MSG_SAVE)
    except FeedError as e:
        failures = int(feed.get("failure_count") or 0) + 1
        _finish(feed_id, now, {
            "status": "error",
            "last_error": e.message,
            "failure_count": failures,
            "next_sync_at": _iso_z(now + timedelta(minutes=backoff_minutes(failures))),
        })
        return {"ok": False, "error": e.message}
    except Exception as e:  # never out of the scheduler; never the URL
        logger.warning("[calendar] sync failed for feed %s: %s", feed_id, type(e).__name__)
        failures = int(feed.get("failure_count") or 0) + 1
        _finish(feed_id, now, {
            "status": "error",
            "last_error": MSG_CONNECT,
            "failure_count": failures,
            "next_sync_at": _iso_z(now + timedelta(minutes=backoff_minutes(failures))),
        })
        return {"ok": False, "error": MSG_CONNECT}
    _finish(feed_id, now, {
        "status": "ok",
        "last_error": None,
        "last_synced_at": _iso_z(now),
        "busy_count": len(blocks),
        "failure_count": 0,
        "next_sync_at": _iso_z(now + timedelta(minutes=SYNC_EVERY_MIN)),
    })
    return {"ok": True, "busy_count": len(blocks)}


def sync_due(now: Optional[datetime] = None) -> int:
    """Sync every feed whose next_sync_at has come. Returns how many
    were attempted. Bounded per tick in count and wall time."""
    if (os.environ.get("CALENDAR_FEEDS_SYNC") or "on").strip().lower() == "off":
        return 0
    if tables_known_absent():
        return 0
    now = now or datetime.now(timezone.utc)
    status, rows = _rest(
        "GET",
        f"/{FEEDS}?or=(next_sync_at.is.null,next_sync_at.lte.{_iso_z(now)})"
        f"&select=*&order=next_sync_at.asc.nullsfirst&limit={TICK_BATCH}",
        prefer=None)
    if not isinstance(rows, list):
        return 0
    started = _time.monotonic()
    attempted = 0
    for feed in rows:
        if _time.monotonic() - started > TICK_BUDGET_S:
            break
        attempted += 1
        try:
            sync_feed(feed, now=datetime.now(timezone.utc))
        except Exception as e:
            logger.warning("[calendar] tick: feed %s: %s", feed.get("id"), type(e).__name__)
    return attempted


async def sync_due_tick() -> None:
    """Scheduler entry (leader-gated in kmj_intake_automation). Runs the
    blocking fetches off the event loop and never raises."""
    try:
        import asyncio
        n = await asyncio.to_thread(sync_due)
        if n:
            logger.info("[calendar] synced %s feed(s)", n)
    except Exception as e:
        logger.warning("[calendar] tick failed: %s", type(e).__name__)
