"""
chief_prewarm.py — hold the message-independent half of a Chief turn's
context so it can be fetched while the practitioner is still talking.

Kevin's question, 2026-08-14: "would it be better if we have it
positioned so as I talk it starts thinking, so when I am done it
processed some of what I said already?"

Half of that is right, and it is the cheap half. Guessing at a reply
from a half-finished sentence is the expensive half — people change
direction mid-thought ("no, you don't have to do that right now, just
put a note for me"), so speculative generation buys tokens you throw
away and risks acting on half a request. But the CONTEXT a turn needs is
a different story: the revenue forecast, relationship insights, habit
patterns, bookkeeping, voice samples and mentor cooldown depend only on
WHO is asking, never on WHAT they say. That work can start the moment
the mic opens and be finished before the sentence is.

So: pre-warm the data, never pre-guess the answer.

WHAT THIS IS NOT: a general response cache. Only sources that are
provably message-independent belong here — chief_of_staff._context_sources
is the single list, used by both the prewarm endpoint and the turn, so
the two can't drift into disagreeing about what is safe to reuse.

ISOLATION: the key is (user_id, business_id), never business_id alone.
Entries are built under one practitioner's JWT and must never be served
to another — a Chief turn reading someone else's forecast would be a
data leak, not a slow page.

STALENESS: entries expire after TTL_SECONDS. The numbers in here move on
the order of hours (forecasts, habit patterns, relationship health), so
a ~minute-old copy is the same answer. Past the TTL the turn just
fetches normally — a miss is today's behaviour, never an error.

PROCESS-LOCAL by design: an in-process dict, so a prewarm that lands on
one web instance and a turn that lands on another simply misses. That
degrades to the current path. Correctness never depends on the hit.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple

# How long a warmed entry stays usable. Long enough to cover a slow
# sentence and the round trip after it; short enough that nothing here
# is meaningfully staler than what the turn would have fetched itself.
TTL_SECONDS = 90.0

# Re-warming inside this window is a no-op. A practitioner tapping the
# mic four times must not fan out four sweeps of Supabase.
MIN_REWARM_SECONDS = 10.0

# Hard ceiling so a long-lived process can't grow this without bound.
# Far above any plausible concurrent-practitioner count; the pruning
# pass below keeps it honest.
MAX_ENTRIES = 500

_lock = threading.Lock()
# key -> (stored_at, payload)
_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}


def _key(user_id: Any, business_id: Any) -> Tuple[str, str]:
    return (str(user_id or ""), str(business_id or ""))


def _prune_locked(now: float) -> None:
    dead = [k for k, (at, _) in _cache.items() if now - at > TTL_SECONDS]
    for k in dead:
        _cache.pop(k, None)
    if len(_cache) > MAX_ENTRIES:
        # Oldest first — the ones closest to expiry anyway.
        for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[
                :len(_cache) - MAX_ENTRIES]:
            _cache.pop(k, None)


def store(user_id: Any, business_id: Any, payload: Dict[str, Any]) -> None:
    """Park a warmed context payload for this practitioner + business."""
    if not user_id or not business_id or not isinstance(payload, dict):
        return
    now = time.monotonic()
    with _lock:
        _prune_locked(now)
        _cache[_key(user_id, business_id)] = (now, dict(payload))


def take(user_id: Any, business_id: Any) -> Dict[str, Any]:
    """Return the warmed payload, or {} if there isn't a fresh one.

    Deliberately a read, not a pop: a practitioner who opens the mic and
    then sends two quick turns should get the benefit on both, and every
    value in here is equally valid for either.
    """
    if not user_id or not business_id:
        return {}
    now = time.monotonic()
    with _lock:
        hit = _cache.get(_key(user_id, business_id))
        if not hit:
            return {}
        stored_at, payload = hit
        if now - stored_at > TTL_SECONDS:
            _cache.pop(_key(user_id, business_id), None)
            return {}
        return dict(payload)


def age(user_id: Any, business_id: Any) -> Optional[float]:
    """Seconds since this pair was last warmed, or None if never/expired."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(_key(user_id, business_id))
        if not hit:
            return None
        stored_at, _ = hit
        if now - stored_at > TTL_SECONDS:
            return None
        return now - stored_at


def should_rewarm(user_id: Any, business_id: Any) -> bool:
    """False when a warm entry is recent enough that re-fetching would be
    pure waste — the mic-tap throttle."""
    a = age(user_id, business_id)
    return a is None or a >= MIN_REWARM_SECONDS


def clear() -> None:
    """Tests only."""
    with _lock:
        _cache.clear()
