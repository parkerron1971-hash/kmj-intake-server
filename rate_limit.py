"""
rate_limit.py — tiny in-process sliding-window limiter.

Beta-readiness audit (AI-spend + adversarial): the paid AI endpoints had
no per-caller throttle, so one tester (or a leaked URL) could fire
thousands of requests. This is the same fixed-window pattern already
used by the intake + booking endpoints, factored out so chat, voice,
and the proxy can share it.

Keyed by caller identity — user id when the endpoint is authenticated,
else the client IP (from X-Forwarded-For behind Railway's proxy). Fully
in-process (single Railway instance); fail-OPEN by design — a limiter
glitch must never block a legitimate call.

Defaults are generous (meant to stop abuse/runaways, not normal use) and
env-overridable per bucket.
"""

import os
import time
from typing import Dict, Tuple

# bucket name → (max_requests, window_seconds), env-overridable.
_LIMITS: Dict[str, Tuple[int, int]] = {
    "chief":  (int(os.environ.get("RL_CHIEF_PER_MIN", "30")), 60),
    "voice":  (int(os.environ.get("RL_VOICE_PER_MIN", "40")), 60),
    "proxy":  (int(os.environ.get("RL_PROXY_PER_MIN", "60")), 60),
    # Interview v3 (B3) — the follow-up probe's per-business hourly budget.
    "interview_probe": (int(os.environ.get("RL_INTERVIEW_PROBE_PER_HOUR", "6")), 3600),
    # The agent-facing MCP surface. Tighter than the practitioner buckets
    # and checked with allow_strict() — an external agent that loops is a
    # different problem from a person clicking twice.
    "mcp": (int(os.environ.get("RL_MCP_PER_MIN", "20")), 60),
    # Digital-delivery downloads — anon, token-gated; generous enough
    # for a buyer grabbing a multi-item order, tight enough to stop a
    # scripted token search.
    "store_download": (int(os.environ.get("RL_STORE_DOWNLOAD_PER_MIN", "30")), 60),
}
_DEFAULT = (60, 60)

# (bucket, key) → {"start": epoch, "count": n}
_buckets: Dict[Tuple[str, str], Dict[str, float]] = {}


def client_ip(request) -> str:
    """Best-effort caller IP. Railway sits behind a proxy, so prefer the
    first X-Forwarded-For hop; fall back to the socket peer."""
    try:
        xff = request.headers.get("x-forwarded-for") or ""
        if xff:
            return xff.split(",")[0].strip()
        return (request.client.host if request.client else "unknown")
    except Exception:
        return "unknown"


def _check(bucket: str, key: str) -> bool:
    """The window arithmetic, with no error handling. RAISES on trouble —
    the two public wrappers below decide what a failure means, and they
    disagree on purpose."""
    max_req, window = _LIMITS.get(bucket, _DEFAULT)
    now = time.time()
    bkey = (bucket, key or "unknown")
    b = _buckets.get(bkey)
    if not b or now - b["start"] > window:
        _buckets[bkey] = {"start": now, "count": 1}
        return True
    if b["count"] >= max_req:
        return False
    b["count"] += 1
    return True


def allow(bucket: str, key: str) -> bool:
    """True if this (bucket, key) is under its limit for the current
    window. Fail-OPEN on any error."""
    try:
        return _check(bucket, key)
    except Exception:
        return True


def allow_strict(bucket: str, key: str) -> bool:
    """`allow`, but FAIL-CLOSED.

    Every bucket above fails open, which is right for a practitioner: a
    limiter glitch must never stop someone running their own business.
    It is wrong for an external agent. On that surface the caller is not
    a person waiting on a screen, the credential may be stolen, and
    "the limiter broke so everything was permitted" is the failure you
    least want. Same window arithmetic, opposite answer when it breaks.

    Kept separate from `allow` rather than adding a flag, so that no
    existing caller can acquire this behaviour by accident.
    """
    try:
        return _check(bucket, key)
    except Exception:
        return False


def retry_after(bucket: str) -> int:
    """Seconds a caller should wait — the window length."""
    return int(_LIMITS.get(bucket, _DEFAULT)[1])
