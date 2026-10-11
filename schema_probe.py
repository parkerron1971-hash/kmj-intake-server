"""schema_probe.py — does a table carry these columns yet?

Migrations here are applied by hand, so code that writes a new column can
reach production before the column does. PostgREST rejects an insert that
names an unknown column (PGRST204), and most writers fail soft — the row is
simply lost. This is the guard: send the new keys only once the probe has
seen the columns.

Same shape as proposal_life.columns_supported: one `select=<cols>&limit=1`
per (table, columns) at most every PROBE_TTL_S seconds, never probed at all
without a Supabase URL (tests and scripts answer False). A migration applied
after boot is picked up within the TTL. Per-process cache only; a wrong
answer costs at most one TTL of missing optional columns, never a write.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Dict, Iterable, Tuple

import sb_clients

logger = logging.getLogger("schema_probe")

PROBE_TTL_S = 600.0

_cache: Dict[Tuple[str, Tuple[str, ...]], Tuple[bool, float]] = {}


def _key(table: str, cols: Iterable[str]) -> Tuple[str, Tuple[str, ...]]:
    return table.strip("/"), tuple(sorted(str(c) for c in cols))


def cached(table: str, cols: Iterable[str]) -> "bool | None":
    """The cached answer if it is fresh, else None. Never touches the network."""
    hit = _cache.get(_key(table, cols))
    if hit is not None and time.monotonic() - hit[1] < PROBE_TTL_S:
        return hit[0]
    return None


def has_columns(table: str, cols: Iterable[str]) -> bool:
    """True once `table` has every column in `cols`. Sync; never raises."""
    if not os.environ.get("SUPABASE_URL"):
        return False
    key = _key(table, cols)
    fresh = cached(*key)
    if fresh is not None:
        return fresh
    try:
        rows = sb_clients.sb_get_as_service(f"/{key[0]}?select={','.join(key[1])}&limit=1")
        ok = isinstance(rows, list)
    except Exception:
        ok = False
    if not ok:
        logger.info(f"[schema_probe] {key[0]} has no {','.join(key[1])} yet")
    _cache[key] = (ok, time.monotonic())
    return ok


async def has_columns_async(table: str, cols: Iterable[str]) -> bool:
    """has_columns for async callers: a fresh cached answer costs nothing,
    a probe runs off the event loop."""
    fresh = cached(table, cols)
    if fresh is not None:
        return fresh
    return await asyncio.to_thread(has_columns, table, tuple(cols))


def reset() -> None:
    """Tests only."""
    _cache.clear()
