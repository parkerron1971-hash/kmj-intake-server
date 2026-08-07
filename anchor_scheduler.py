"""Anchoring on a clock — the thing that makes redundancy mean anything.

Two independent providers protect against one network failing. They do
nothing at all about the failure that was actually most likely: nobody
anchoring. Until this module, anchoring was owner-triggered from the
ledger surface, which meant a practice's records stayed unprovable until
someone remembered to click — and a gap cannot be repaired afterwards,
because you cannot anchor last month at last month's timestamp.

THE SWEEP WRITES NO LEDGER ENTRY, AND THAT IS THE LOAD-BEARING DECISION.
The owner-triggered route records `ledger:anchored` in audit_log, which
is right for a human deliberately asserting "this is our record as of
now" — it is rare, and it is a real act. On a six-hourly schedule the
same write becomes a perpetual motion machine: every sweep would create
a new row, that row is new unanchored activity, so the next sweep has
work, which creates another row, forever. A ledger that is otherwise
quiet would fill with nothing but records of its own anchoring.

Writing nothing keeps the sweep a genuine no-op for a quiet tenant, and
loses no information: the receipt in ledger_anchors IS the record of the
anchor, and it is the one an auditor reads.

Leader-gated like every other job here (see scheduler_lock) — with two
replicas an ungated sweep would have both anchoring the same window, and
the per-provider unique index would turn that into a constraint error
rather than a duplicate.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import ledger_anchor
import sb_clients

logger = logging.getLogger("anchor_scheduler")

# Bounded so one tick cannot spend an unbounded amount of time, or lean
# on the free OpenTimestamps calendars harder than is polite. A backlog
# drains over several ticks instead of in one long stall.
DEFAULT_MAX_PER_TICK = 25

# What the last sweep did, for the health surface. In-process only —
# it resets on redeploy, and the anchors themselves are the durable
# record, so this never needs a table.
LAST_SWEEP: Optional[Dict[str, Any]] = None


def max_per_tick() -> int:
    try:
        v = int(os.environ.get("LEDGER_ANCHOR_MAX_PER_TICK") or DEFAULT_MAX_PER_TICK)
    except (TypeError, ValueError):
        return DEFAULT_MAX_PER_TICK
    return v if v > 0 else DEFAULT_MAX_PER_TICK


def _work_list() -> List[Tuple[str, int]]:
    """Which tenants are behind, and by how much — in TWO queries.

    The obvious implementation asks each tenant in turn whether it has
    anything to anchor, which is one round trip per tenant per tick and
    gets worse forever. ledger_chain_state already holds one row per
    tenant with its ledger head, so the whole work list is that table
    joined against the anchor high-water marks in memory.

    A tenant is behind if ANY configured provider's newest anchor is
    below the head — per provider, because the whole point of running
    two is that one can be behind while the other is current.
    """
    heads = sb_clients.sb_get_as_service(
        "/ledger_chain_state?select=business_id,last_sequence&limit=5000") or []
    anchors = sb_clients.sb_get_as_service(
        "/ledger_anchors?select=business_id,provider,last_sequence"
        "&order=last_sequence.desc&limit=20000") or []

    providers = ledger_anchor.configured_providers()
    high: Dict[Tuple[str, str], int] = {}
    for a in anchors:
        key = (str(a.get("business_id")), str(a.get("provider")))
        try:
            seq = int(a.get("last_sequence") or 0)
        except (TypeError, ValueError):
            continue
        if seq > high.get(key, 0):
            high[key] = seq

    behind: List[Tuple[str, int]] = []
    for h in heads:
        biz = str(h.get("business_id") or "")
        try:
            head = int(h.get("last_sequence") or 0)
        except (TypeError, ValueError):
            continue
        if not biz or head <= 0:
            continue
        lags = [head - high.get((biz, p), 0) for p in providers]
        if any(lag > 0 for lag in lags):
            # Ranked by the WORST provider's lag, so the most exposed
            # tenant is served first when a backlog exceeds the cap.
            behind.append((biz, max(lags)))

    behind.sort(key=lambda t: t[1], reverse=True)
    return behind


async def sweep_tick() -> Dict[str, Any]:
    """Anchor every tenant that has unanchored rows. Leader-gated.

    Blocking work is pushed to a thread deliberately. anchor_business()
    talks to Hedera and to the OpenTimestamps calendars over synchronous
    HTTP — a single Hedera submit measured 5.8s — so calling it directly
    from this coroutine would park the API's event loop for minutes at a
    time, once every interval. Every request the server was serving
    would hang behind an anchoring job nobody asked about.
    """
    global LAST_SWEEP
    started = time.time()

    if not ledger_anchor.schedule_enabled():
        LAST_SWEEP = {"skipped": "LEDGER_ANCHOR_SCHEDULE=off", "at": _now_z()}
        return LAST_SWEEP

    try:
        behind = await asyncio.to_thread(_work_list)
    except Exception as e:
        logger.warning("[anchor-sweep] could not build the work list: %s", e)
        LAST_SWEEP = {"error": f"{type(e).__name__}: {str(e)[:160]}", "at": _now_z()}
        return LAST_SWEEP

    cap = max_per_tick()
    todo = behind[:cap]
    deferred = len(behind) - len(todo)
    if deferred > 0:
        # Never a silent cap: a truncated sweep that reported success
        # would read as "everything is anchored" when it is not.
        logger.warning("[anchor-sweep] %d tenants behind, taking %d this tick "
                       "(%d deferred to the next run)", len(behind), len(todo), deferred)

    anchored = 0
    failed = 0
    per_provider: Dict[str, Dict[str, int]] = {}
    for biz, _lag in todo:
        try:
            out = await asyncio.to_thread(ledger_anchor.anchor_business, biz)
        except Exception as e:
            # anchor_business already swallows per-provider errors, so
            # reaching here means something structural. One tenant must
            # not end the sweep for the rest.
            failed += 1
            logger.warning("[anchor-sweep] %s raised: %s", biz, e)
            continue
        if out.get("anchored"):
            anchored += 1
        for r in out.get("providers") or []:
            slot = per_provider.setdefault(str(r.get("provider")),
                                           {"anchored": 0, "failed": 0})
            if r.get("anchored"):
                slot["anchored"] += 1
            elif r.get("error"):
                slot["failed"] += 1
                failed += 1

    LAST_SWEEP = {
        "at": _now_z(),
        "took_s": round(time.time() - started, 1),
        "behind": len(behind),
        "attempted": len(todo),
        "deferred": deferred,
        "anchored": anchored,
        "provider_failures": failed,
        "per_provider": per_provider,
        "providers": ledger_anchor.configured_providers(),
    }
    if todo:
        logger.info("[anchor-sweep] %s", LAST_SWEEP)
    return LAST_SWEEP


def _now_z() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── The Bitcoin upgrade tick ────────────────────────────────────────
#
# A stored .ots is written at submission time and never learns about its
# own Bitcoin confirmation — the upgrade lives at the calendar server.
# Without something asking, every OpenTimestamps proof reports
# `submitted` forever, which throws away the distinction that is the
# entire reason there are two states.

LAST_UPGRADE: Optional[Dict[str, Any]] = None

DEFAULT_UPGRADE_BATCH = 25


def upgrade_batch() -> int:
    try:
        v = int(os.environ.get("LEDGER_ANCHOR_UPGRADE_BATCH")
                or DEFAULT_UPGRADE_BATCH)
    except (TypeError, ValueError):
        return DEFAULT_UPGRADE_BATCH
    return v if v > 0 else DEFAULT_UPGRADE_BATCH


async def upgrade_tick() -> Dict[str, Any]:
    """Ask the calendars for Bitcoin attestations we do not have yet.

    A SEPARATE JOB ON A DIFFERENT CLOCK, because the two answer to
    different things. The anchoring sweep is driven by new ledger
    activity; this one is driven by Bitcoin block times, and it has work
    to do even on a platform where nothing whatsoever is happening.
    Folding it into the sweep would tie confirmation to activity, so a
    quiet practice's proofs would stay `submitted` indefinitely — which
    is the exact bug this fixes, reintroduced by the back door.

    Off the event loop for the same reason the sweep is: this talks to
    three calendar servers per proof over synchronous http.
    """
    global LAST_UPGRADE
    started = time.time()

    if not ledger_anchor.schedule_enabled():
        LAST_UPGRADE = {"skipped": "LEDGER_ANCHOR_SCHEDULE=off", "at": _now_z()}
        return LAST_UPGRADE

    try:
        out = await asyncio.to_thread(ledger_anchor.upgrade_pending,
                                      upgrade_batch())
    except Exception as e:
        logger.warning("[anchor-upgrade] tick failed: %s", e)
        LAST_UPGRADE = {"error": f"{type(e).__name__}: {str(e)[:160]}",
                        "at": _now_z()}
        return LAST_UPGRADE

    LAST_UPGRADE = {**out, "at": _now_z(),
                    "took_s": round(time.time() - started, 1)}
    return LAST_UPGRADE
