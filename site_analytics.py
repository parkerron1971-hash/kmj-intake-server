"""
site_analytics.py — first-party, anonymous traffic analytics for the
marketing site.

    POST /api/track          public, anonymous, no auth
    GET  /admin/traffic      platform owner only

WHY FIRST-PARTY: Kevin wanted to "monitor the website traffic and flow"
without a third party and without the cookie-consent banner that GA4 and
friends require. Everything here is designed so the data cannot identify
a person, which is what makes the no-banner position honest:

  • no IP address is stored
  • no user-agent string is stored (it is read to drop bots, then dropped)
  • no cookie is ever set — session_id lives in sessionStorage and dies
    with the tab, so it cannot follow anyone across visits or sites
  • referrer is reduced to its HOST before storage, because full referrer
    URLs routinely carry search terms in their query strings

If any of those change, the privacy policy has to change with them.

See supabase/APPLY-2026-07-28-site-events.sql for the table + RLS.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("site_analytics")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] analytics: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
PLATFORM_OWNER_EMAIL = os.environ.get("PLATFORM_OWNER_EMAIL", "kmjcreativesolution@gmail.com").lower()
HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)

# The funnel we actually care about: did a visitor get from the front door
# to the application form, and did they finish it.
FUNNEL = [("/", "Landing"), ("/features", "Features"),
          ("/get-started", "Get Started"), ("submit", "Applied")]

ALLOWED_EVENTS = {"view", "cta", "submit"}
_BOT = re.compile(r"bot|crawl|spider|slurp|headless|preview|monitor|curl|wget|python-|axios|fetch\b|lighthouse|pingdom|uptime",
                  re.I)

# Cheap in-process flood guard. Not security — just stops one tab from
# writing thousands of rows if a script goes wrong.
_seen: Dict[str, List[float]] = defaultdict(list)
_MAX_PER_SESSION_PER_MIN = 30


def _rate_ok(session_id: str) -> bool:
    now = time.time()
    hits = [t for t in _seen[session_id] if now - t < 60]
    hits.append(now)
    _seen[session_id] = hits
    if len(_seen) > 5000:                      # bound the dict
        for k in [k for k, v in list(_seen.items()) if not v or now - v[-1] > 300]:
            _seen.pop(k, None)
    return len(hits) <= _MAX_PER_SESSION_PER_MIN


def _service_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(500, "Supabase service role not configured")
    h = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def require_owner(user: AuthedUser = Depends(require_user)) -> AuthedUser:
    """403 (not 401) so the client can tell 'signed in but not allowed'
    apart from 'not signed in'."""
    if (user.email or "").lower() != PLATFORM_OWNER_EMAIL:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Traffic data is restricted to the platform owner.")
    return user


# ── ingest ────────────────────────────────────────────────────────────

class TrackEvent(BaseModel):
    s: str = Field(..., max_length=64)     # session id (sessionStorage)
    p: str = Field(..., max_length=300)    # path
    r: Optional[str] = Field(None, max_length=500)   # referrer (reduced to host)
    d: Optional[str] = Field(None, max_length=16)    # device class
    e: str = Field("view", max_length=16)  # event


router = APIRouter(tags=["site-analytics"])


@router.post("/api/track", include_in_schema=False)
async def track(ev: TrackEvent, request: Request,
                user_agent: Optional[str] = Header(default=None),
                dnt: Optional[str] = Header(default=None)):
    """Record one anonymous event. Always returns 204 — a tracking
    endpoint must never surface an error to a visitor's browser or slow
    the page down, and a failure here is not worth a console message."""
    try:
        # Honour Do Not Track server-side as well as client-side.
        if (dnt or "").strip() == "1":
            return _no_content()
        if user_agent and _BOT.search(user_agent):
            return _no_content()

        path = (ev.p or "/").strip()[:300]
        if not path.startswith("/"):
            return _no_content()
        # Strip the query string: it can carry personal data and we never
        # need it for page-level traffic.
        path = path.split("?")[0].split("#")[0] or "/"

        event = ev.e if ev.e in ALLOWED_EVENTS else "view"
        session = (ev.s or "").strip()[:64]
        if not session or not _rate_ok(session):
            return _no_content()

        # HOST ONLY. Full referrer URLs leak search terms.
        ref_host = None
        if ev.r:
            try:
                h = urlparse(ev.r).hostname or ""
                if h and "mysolutionist.app" not in h:
                    ref_host = h[:120]
            except Exception:
                ref_host = None

        device = ev.d if ev.d in {"mobile", "tablet", "desktop"} else None

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(
                f"{SUPABASE_URL}/rest/v1/site_events",
                headers=_service_headers({"Prefer": "return=minimal"}),
                json={"session_id": session, "path": path, "referrer_host": ref_host,
                      "device": device, "event": event},
            )
            if r.status_code >= 400:
                logger.warning("track insert failed %s: %s", r.status_code, r.text[:200])
    except Exception as e:                                  # never bubble up
        logger.warning("track error: %s", e)
    return _no_content()


def _no_content():
    from fastapi import Response
    return Response(status_code=204)


# ── read-out ──────────────────────────────────────────────────────────

MAX_ROWS = 50000   # ceiling per query; see note in the summary docstring


@router.get("/admin/traffic", include_in_schema=False)
async def traffic_summary(days: int = Query(30, ge=1, le=365),
                          _: AuthedUser = Depends(require_owner)):
    """Aggregate the window in Python rather than SQL.

    That is a deliberate trade at this volume: it keeps the whole thing in
    one file with no database views to keep in sync. It does mean the read
    is bounded — MAX_ROWS caps the fetch, and `truncated` says so plainly
    rather than silently reporting a wrong number. If the site ever
    outgrows that, this becomes a materialised view.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/site_events",
            headers=_service_headers(),
            params={"select": "ts,session_id,path,referrer_host,device,event",
                    "ts": f"gte.{since}", "order": "ts.desc", "limit": str(MAX_ROWS)},
        )
    if r.status_code >= 400:
        raise HTTPException(502, f"traffic read failed: {r.text[:200]}")
    rows: List[Dict[str, Any]] = r.json() or []

    views = [x for x in rows if x.get("event") == "view"]
    sessions = {x.get("session_id") for x in rows if x.get("session_id")}

    by_day: Counter = Counter()
    for x in views:
        ts = (x.get("ts") or "")[:10]
        if ts:
            by_day[ts] += 1

    # funnel: how many distinct sessions reached each step
    reached: Dict[str, set] = {k: set() for k, _ in FUNNEL}
    for x in rows:
        sid, p, ev = x.get("session_id"), x.get("path") or "", x.get("event")
        if not sid:
            continue
        if ev == "submit":
            reached["submit"].add(sid)
        for key, _label in FUNNEL:
            if key != "submit" and p == key:
                reached[key].add(sid)

    funnel = []
    top = len(reached[FUNNEL[0][0]]) or 1
    for key, label in FUNNEL:
        n = len(reached[key])
        funnel.append({"step": label, "sessions": n, "pct": round(100.0 * n / top, 1)})

    return {
        "days": days,
        "views": len(views),
        "sessions": len(sessions),
        "truncated": len(rows) >= MAX_ROWS,
        "by_day": [{"date": d, "views": n} for d, n in sorted(by_day.items())],
        "top_paths": [{"path": p, "views": n} for p, n in Counter(
            x.get("path") for x in views).most_common(12)],
        "referrers": [{"host": h, "views": n} for h, n in Counter(
            x.get("referrer_host") for x in views if x.get("referrer_host")).most_common(12)],
        "devices": [{"device": d or "unknown", "views": n} for d, n in Counter(
            x.get("device") for x in views).most_common()],
        "funnel": funnel,
    }
