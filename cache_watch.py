"""cache_watch.py — which cached prompt parts changed since this business's last call.

A cached prompt segment that differs from one turn to the next is written
again, at 1.25x-2x the input price, instead of read at 0.1x. After the
2026-09-24 fixes the usage log still showed Chief's ~22k-token state
segment and the answer check's records re-written on every message, and
nothing could say which part had moved: a rebuild of the same inputs
offline was byte-identical. This keeps a fingerprint of each part per
business (in memory, bounded) and logs the parts that changed since the
previous call, so the cause is one log line.

The log names parts by their static heading and says where a part
changed and whether only digits moved (a clock, a count). It never logs
the business's data itself.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import OrderedDict

logger = logging.getLogger("chief.cache_watch")
if not logger.handlers:
    # The root logger stays at WARNING; like chief.truth, this one carries
    # its own handler or its INFO lines never reach Railway (the first
    # deploy of this watch logged nothing for exactly that reason).
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] chief.cache_watch: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
    logger.propagate = False

_MAX_BUSINESSES = 300
_seen: "OrderedDict[tuple, dict]" = OrderedDict()
_DIGITS = re.compile(r"\d")


def paragraphs(text: str) -> dict:
    """A segment split at blank lines, keyed by position and first line."""
    out = {}
    for i, part in enumerate((text or "").split("\n\n")):
        head = next((ln.strip() for ln in part.splitlines() if ln.strip()), "")
        out[f"{i:02d} {head[:40]}"] = part
    return out


def _fingerprint(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8", "ignore")).hexdigest()[:12]


def _where(old: str, new: str) -> str:
    a, b = (old or "").splitlines(), (new or "").splitlines()
    for n, (x, y) in enumerate(zip(a, b), 1):
        if x != y:
            kind = "digits only" if _DIGITS.sub("#", x) == _DIGITS.sub("#", y) else "text"
            return f"line {n} ({kind})"
    return f"length {len(a)} -> {len(b)} lines"


def note(kind: str, business_id, parts: dict, quiet_unchanged: bool = False) -> list:
    """Record `parts` (name -> text) for (kind, business); return and log
    the names that changed since the last note. The first call per
    business per process has nothing to compare and returns []."""
    if not business_id or not parts:
        return []
    key = (kind, str(business_id))
    # The order is a part too: the same records in a different order are a
    # different prefix, and a cache miss, to the API.
    parts = {**parts, "(order)": "\n".join(parts)}
    now = {name: (_fingerprint(text), text) for name, text in parts.items()}
    before = _seen.pop(key, None)
    _seen[key] = now
    while len(_seen) > _MAX_BUSINESSES:
        _seen.popitem(last=False)
    if before is None:
        return []
    changed = [n for n in now if n not in before or before[n][0] != now[n][0]]
    gone = [n for n in before if n not in now]
    if not (changed or gone):
        if not quiet_unchanged:
            logger.info("cache watch %s biz=%s: nothing changed (%d parts)",
                        kind, str(business_id)[:8], len(now))
    else:
        first = changed[0] if changed else None
        detail = (_where(before[first][1], now[first][1]) if first and first in before else "new")
        logger.info("cache watch %s biz=%s: %d of %d parts changed since the last call "
                    "(first: %r, %s)%s: %s", kind, str(business_id)[:8], len(changed), len(now),
                    first, detail, f"; {len(gone)} gone" if gone else "",
                    ", ".join(repr(n) for n in changed[:10]))
    return changed + gone


# ─── The whole request, not just the system prompt (2026-10-07) ──────────
#
# 30 days of usage showed 48 calls that re-wrote Chief's entire ~106k-token
# brief less than an hour after the business's previous call, almost all of
# them reading NOTHING back. A read of zero means the very start of the
# prefix changed, and the start is not the system prompt: the API renders
# the tool definitions first, keys every cache to the model, and (model-
# specifically) to the thinking/effort settings. The system-part watch
# above could never see any of those. This one fingerprints everything the
# cache is keyed on, and when a call really does re-write the brief, one
# log line says which part moved, or that nothing did and the stored copy
# had simply expired.

_last_call: "OrderedDict[str, tuple]" = OrderedDict()   # business -> (time, role)
REWRITE_LOG_TOKENS = 20000


def request_parts(payload: dict, *, ttl: str = "") -> dict:
    """What the prompt cache is keyed on, part by part, in render order:
    the model, the thinking/effort settings, the cache lifetime asked for,
    every tool definition, then each cached system block. The uncached
    per-message tail is left out: it is meant to change."""
    p = payload or {}
    parts = {
        "model": str(p.get("model") or ""),
        "effort": json.dumps({k: p[k] for k in ("thinking", "output_config") if k in p},
                             sort_keys=True),
        "ttl": ttl or "",
    }
    for t in p.get("tools") or []:
        name = (t.get("name") or t.get("type") or "?") if isinstance(t, dict) else "?"
        parts[f"tool {name}"] = json.dumps(t)
    system = p.get("system")
    if isinstance(system, list):
        for i, block in enumerate(system):
            if isinstance(block, dict) and "cache_control" in block:
                parts[f"system {i}"] = (str(block.get("text") or "")
                                        + json.dumps(block["cache_control"], sort_keys=True))
    elif system:
        parts["system"] = str(system)
    return parts


def note_request(business_id, payload: dict, *, ttl: str = "", role: str = ""):
    """Fingerprint one model request for this business. Returns a summary
    for report_write(); logs only when something changed."""
    if not business_id:
        return None
    b = str(business_id)
    now = time.time()
    prev = _last_call.pop(b, None)
    _last_call[b] = (now, role)
    while len(_last_call) > _MAX_BUSINESSES:
        _last_call.popitem(last=False)
    changed = note("chief_request", b, request_parts(payload, ttl=ttl), quiet_unchanged=True)
    return {"first": prev is None, "changed": changed, "role": role,
            "prev_role": prev[1] if prev else None,
            "gap_s": (now - prev[0]) if prev else None}


def report_write(business_id, summary, read_tokens, write_tokens) -> None:
    """One line for a call that wrote a large part of the brief to the
    cache: how much, how much it read back, and why."""
    try:
        written = int(write_tokens or 0)
    except (TypeError, ValueError):
        return
    if not business_id or not summary or written < REWRITE_LOG_TOKENS:
        return
    if summary.get("first"):
        why = "first call for this business since this server started"
    elif summary.get("changed"):
        why = "changed: " + ", ".join(repr(n) for n in summary["changed"][:12])
    else:
        why = "nothing in the request changed: the stored copy had expired or been dropped"
    gap = summary.get("gap_s")
    since = "" if gap is None else f", {gap / 60:.1f} min after a {summary.get('prev_role') or '?'} call"
    logger.info("cache rewrite biz=%s role=%s%s: wrote %d, read %d. %s",
                str(business_id)[:8], summary.get("role") or "?", since, written,
                int(read_tokens or 0), why)
