"""Short-lived, user-scoped receipts for a completed stream's plain POST retry.

This process-local cache recovers lost final events; it is not a durable job
queue or a guarantee across server restarts. A new UI turn has a new request ID.
"""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import time

TTL_SECONDS = 300
MAX_ENTRIES = 64
MAX_PAYLOAD_BYTES = 512_000
_receipts = OrderedDict()


def _key(request, user_id):
    if not request.request_id or not user_id:
        return None
    body = json.dumps(request.model_dump(), sort_keys=True, default=str)
    return (str(user_id), request.business_id, hashlib.sha256(body.encode()).hexdigest())


def _expire():
    now = time.monotonic()
    for key, (expires, _) in list(_receipts.items()):
        if expires <= now:
            _receipts.pop(key, None)


def remember(request, user_id, payload):
    key = _key(request, user_id)
    if key is None or not isinstance(payload, dict):
        return
    if len(json.dumps(payload, default=str).encode()) > MAX_PAYLOAD_BYTES:
        return
    _expire()
    _receipts[key] = (time.monotonic() + TTL_SECONDS, deepcopy(payload))
    _receipts.move_to_end(key)
    while len(_receipts) > MAX_ENTRIES:
        _receipts.popitem(last=False)


def recover(request, user_id):
    _expire()
    entry = _receipts.get(_key(request, user_id))
    return deepcopy(entry[1]) if entry else None


# ── In-flight turns ──────────────────────────────────────────────────
# The stream endpoint used to CANCEL the turn when the client went away,
# so a proxy cut mid-actions left nothing to remember, and the client's
# plain re-POST ran the whole turn again — any action that had already
# completed ran twice (the 2026-09-06 double build, still open on
# 2026-09-19). Now the turn is left to finish and registered here; the
# re-POST finds it and WAITS for its result instead of starting over.
_inflight = {}
INFLIGHT_WAIT_SECONDS = 150


def register(request, user_id, task):
    key = _key(request, user_id)
    if key is None:
        return
    _inflight[key] = task

    def _done(_t):
        _inflight.pop(key, None)
    try:
        task.add_done_callback(_done)
    except Exception:
        _inflight.pop(key, None)


async def recover_async(request, user_id):
    """A remembered result, or the result of the same turn still running
    (waited for), or None."""
    found = recover(request, user_id)
    if found is not None:
        return found
    task = _inflight.get(_key(request, user_id))
    if task is None:
        return None
    import asyncio
    try:
        payload = await asyncio.wait_for(asyncio.shield(task), timeout=INFLIGHT_WAIT_SECONDS)
    except Exception:
        return None
    return deepcopy(payload) if isinstance(payload, dict) else None
