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
import logging
import re
from collections import OrderedDict

logger = logging.getLogger("chief.cache_watch")

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


def note(kind: str, business_id, parts: dict) -> list:
    """Record `parts` (name -> text) for (kind, business); return and log
    the names that changed since the last note. The first call per
    business per process has nothing to compare and returns []."""
    if not business_id or not parts:
        return []
    key = (kind, str(business_id))
    now = {name: (_fingerprint(text), text) for name, text in parts.items()}
    before = _seen.pop(key, None)
    _seen[key] = now
    while len(_seen) > _MAX_BUSINESSES:
        _seen.popitem(last=False)
    if before is None:
        return []
    changed = [n for n in now if n not in before or before[n][0] != now[n][0]]
    gone = [n for n in before if n not in now]
    if changed or gone:
        first = changed[0] if changed else None
        detail = (_where(before[first][1], now[first][1]) if first and first in before else "new")
        logger.info("cache watch %s biz=%s: %d of %d parts changed since the last call "
                    "(first: %r, %s)%s: %s", kind, str(business_id)[:8], len(changed), len(now),
                    first, detail, f"; {len(gone)} gone" if gone else "",
                    ", ".join(repr(n) for n in changed[:10]))
    return changed + gone
