"""
scheduler_lock.py — Arc 29 — single-leader election for scheduled jobs.

The app runs scheduled jobs (morning brief, GL drain, recurring-invoice
ticks, etc.) inside the FastAPI process via AsyncIOScheduler. With 2+
Railway replicas every job would fire on every replica — duplicate
emails, double GL processing. There is no raw Postgres connection (the
app speaks PostgREST only), so pg_advisory_lock isn't available; instead
we lease leadership through a singleton row.

Mechanism:
  - One row in scheduler_lease (id='global') holds {holder, expires_at}.
  - try_acquire() does an ATOMIC claim: PATCH the row only WHERE it's
    expired or already mine. Postgres row-locks the UPDATE, so of two
    racing replicas exactly one matches the predicate and wins; the
    loser's filter no longer matches the now-future expires_at.
  - A renew tick (always runs, every RENEW_SEC) refreshes the cached
    is_leader() flag. Scheduled jobs call is_leader() and no-op if false.
  - If the leader dies, its lease expires after LEASE_TTL_SEC and another
    replica claims on its next renew tick.

Fail-safe: if the lease table is missing (migration not applied) or
Supabase is unreachable, default to LEADER (so a single-replica deploy
keeps working exactly as before). The lock only ever PREVENTS duplicate
work; it never blocks a lone instance.

Migration: __migrations__/2026_06_12_arc29_scheduler_lease.sql
Kill switch: SCHEDULER_LOCK=off forces leader (legacy single-instance).
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta

import sb_clients

logger = logging.getLogger("scheduler_lock")

INSTANCE_ID = str(uuid.uuid4())
LEASE_TTL_SEC = 90
RENEW_SEC = 30
_LEASE_ID = "global"

_is_leader = True            # optimistic default (single-replica safe)
_lease_table_present = True  # flips False on first 404 → permanent leader


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _disabled() -> bool:
    return (os.environ.get("SCHEDULER_LOCK") or "on").lower() == "off"


def try_acquire() -> bool:
    """Atomically claim/renew the global lease. Returns True if THIS
    instance holds leadership after the call."""
    global _is_leader, _lease_table_present
    if _disabled() or not _lease_table_present:
        _is_leader = True
        return True
    now = _now()
    expires = (now + timedelta(seconds=LEASE_TTL_SEC)).isoformat()
    now_iso = now.isoformat()
    try:
        # Claim only if expired OR already held by me. PostgREST 'or='
        # filter; the UPDATE is row-locked so the race resolves to one
        # winner. return=representation (service header default) tells us
        # whether our row write landed.
        rows = sb_clients.sb_patch_as_service(
            f"/scheduler_lease?id=eq.{_LEASE_ID}"
            f"&or=(expires_at.lt.{now_iso},holder.eq.{INSTANCE_ID})",
            {"holder": INSTANCE_ID, "expires_at": expires, "updated_at": now_iso},
        )
        if rows is None:
            # Distinguish "missing table" from "claim lost" by reading.
            existing = sb_clients.sb_get_as_service(
                f"/scheduler_lease?id=eq.{_LEASE_ID}&select=holder,expires_at&limit=1")
            if existing is None:
                _lease_table_present = False
                logger.warning("[scheduler_lock] lease table absent — defaulting to LEADER "
                               "(apply 2026_06_12_arc29_scheduler_lease.sql to enable HA).")
                _is_leader = True
                return True
            _is_leader = bool(existing) and str(existing[0].get("holder")) == INSTANCE_ID
            return _is_leader
        won = bool(rows) and str(rows[0].get("holder")) == INSTANCE_ID
        if not won:
            # Row exists but someone else holds a fresh lease, OR the row
            # doesn't exist yet (first boot) → try to seed it.
            seeded = _seed_if_absent(now_iso, expires)
            _is_leader = seeded
            return seeded
        _is_leader = True
        return True
    except Exception as e:
        logger.warning(f"[scheduler_lock] acquire error — defaulting to leader: {e}")
        _is_leader = True
        return True


def _seed_if_absent(now_iso: str, expires: str) -> bool:
    """First-boot: insert the singleton lease row if it doesn't exist.
    Returns True if we created it (and thus hold it)."""
    try:
        existing = sb_clients.sb_get_as_service(
            f"/scheduler_lease?id=eq.{_LEASE_ID}&select=id,holder,expires_at&limit=1")
        if existing:
            return str(existing[0].get("holder")) == INSTANCE_ID
        created = sb_clients.sb_post_as_service("/scheduler_lease", {
            "id": _LEASE_ID, "holder": INSTANCE_ID,
            "expires_at": expires, "updated_at": now_iso,
        })
        # Unique-violation (another replica seeded first) → not us.
        return bool(created) and str(created[0].get("holder")) == INSTANCE_ID \
            if isinstance(created, list) else False
    except Exception:
        return False


def is_leader() -> bool:
    """Cheap cached read for scheduled jobs to gate on."""
    return _is_leader


async def renew_tick() -> None:
    """Scheduled every RENEW_SEC on EVERY replica — the only always-run
    job. Refreshes leadership; everything else gates on is_leader()."""
    try_acquire()


def gate(job_name: str, fn):
    """Wrap a scheduled coroutine so it only runs on the leader. Logs a
    skip on followers (debug-level — not noise)."""
    async def _wrapped():
        if not is_leader():
            logger.debug(f"[scheduler_lock] not leader — skipping {job_name}")
            return
        return await fn()
    return _wrapped
