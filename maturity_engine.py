"""
maturity_engine.py — Living Growth System Phase 2: business maturity model.

Computes a business's maturity stage (idea / launching / operating / scaling)
from observable signals, caches it, and exposes it to:
  • module_blueprint_agent.provision_modules  — gate which modules auto-assemble
  • the Chief context block                   — so Chief speaks to the right stage
  • the Growth Partner (Phase 4)               — objectives scale with maturity

Fork 8 (ruled): maturity is COMPUTED + CACHED, not practitioner-declared.
The cache lives on businesses.settings.maturity so it rides the existing
settings JSONB (no schema change) and is cheap to read on every provision/Chief
turn. Recompute on a TTL or on demand (force=True).

Reads are SERVICE-ROLE (sb_clients) because this runs server-side with no user
JWT in context — businesses + owner-scoped tables are RLS-protected, so the anon
key would see nothing. This mirrors the restricted_modules.py service-role pattern
and the sb_clients server-initiated contract.

Signals (all soft-fail to 0 so a missing table never crashes maturity):
  age_days          — businesses.created_at
  module_count      — active custom_modules
  entry_count       — module_entries rows (capped scan)
  contact_count     — contacts rows (capped scan)
  paid_invoice_count— invoices with status paid (capped scan)

Stage is the highest band whose ALL gating thresholds are met, walking down.
Conservative by design: a brand-new business is 'idea'/'launching', not
'operating', so downstream modules (Invoices, Staff) don't provision empty.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import sb_clients

logger = logging.getLogger("maturity_engine")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] maturity: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

STAGES = ["idea", "launching", "operating", "scaling"]
STAGE_ORDER = {s: i for i, s in enumerate(STAGES)}

# Cache TTL — maturity changes slowly; recompute at most a few times a day.
CACHE_TTL_SECONDS = 6 * 3600

# Cap on count scans — thresholds are small, so we never need exact counts past this.
_COUNT_CAP = 200

# Per-stage gating thresholds. A business is at stage S if it meets S's thresholds.
# Walk from highest to lowest; first all-met band wins. 'idea' is the floor.
_BANDS: List[Dict[str, Any]] = [
    {"stage": "scaling",   "age_days": 120, "module_count": 5, "entry_count": 80, "paid_invoice_count": 20},
    {"stage": "operating", "age_days": 30,  "module_count": 3, "entry_count": 15, "paid_invoice_count": 3},
    {"stage": "launching", "age_days": 0,   "module_count": 1, "entry_count": 1,  "paid_invoice_count": 0},
    # 'idea' is the implicit floor when nothing above is met.
]


# ──────────────────────────────────────────────────────────────
# Signal collection (service-role reads, all soft-fail to 0)
# ──────────────────────────────────────────────────────────────

def _count(path: str) -> int:
    """Capped count via a select=id scan. Good enough for threshold bands
    (we only care whether a count crosses a small threshold)."""
    rows = sb_clients.sb_get_as_service(f"{path}&select=id&limit={_COUNT_CAP}")
    return len(rows) if isinstance(rows, list) else 0


def _business_age_days(business_id: str) -> int:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=created_at&limit=1"
    ) or []
    if not rows:
        return 0
    created = rows[0].get("created_at")
    if not created:
        return 0
    try:
        # PostgREST returns ISO8601 with tz; normalize the trailing Z.
        dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        return max(0, delta.days)
    except (ValueError, TypeError):
        return 0


def collect_signals(business_id: str) -> Dict[str, int]:
    """Gather the maturity signals for a business. Every signal soft-fails to
    0 independently — a missing/empty table never blocks the computation."""
    return {
        "age_days": _business_age_days(business_id),
        "module_count": _count(f"/custom_modules?business_id=eq.{business_id}&is_active=eq.true"),
        "entry_count": _count(f"/module_entries?business_id=eq.{business_id}"),
        "contact_count": _count(f"/contacts?business_id=eq.{business_id}"),
        "paid_invoice_count": _count(
            f"/invoices?business_id=eq.{business_id}&status=eq.paid"
        ),
    }


# ──────────────────────────────────────────────────────────────
# Stage derivation
# ──────────────────────────────────────────────────────────────

def derive_stage(signals: Dict[str, int]) -> str:
    """Pure function: signals -> stage. Walk bands high→low; first band whose
    every threshold is met wins. Falls through to 'idea'."""
    for band in _BANDS:
        ok = all(
            signals.get(k, 0) >= v
            for k, v in band.items()
            if k != "stage"
        )
        if ok:
            return band["stage"]
    return "idea"


# ──────────────────────────────────────────────────────────────
# Compute + cache
# ──────────────────────────────────────────────────────────────

def _read_cache(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=settings&limit=1"
    ) or []
    if not rows:
        return None
    settings = rows[0].get("settings") or {}
    cached = settings.get("maturity")
    return cached if isinstance(cached, dict) else None


def _write_cache(business_id: str, payload: Dict[str, Any]) -> bool:
    """Surgical merge of settings.maturity, preserving all other settings keys."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=settings&limit=1"
    ) or []
    if not rows:
        return False
    settings = dict(rows[0].get("settings") or {})
    settings["maturity"] = payload
    res = sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{business_id}", {"settings": settings}
    )
    return res is not None


def _is_fresh(cached: Optional[Dict[str, Any]]) -> bool:
    if not cached or not cached.get("computed_at"):
        return False
    try:
        ts = datetime.fromisoformat(str(cached["computed_at"]).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts).total_seconds() < CACHE_TTL_SECONDS
    except (ValueError, TypeError):
        return False


def compute_maturity(business_id: str, force: bool = False) -> Dict[str, Any]:
    """Return {stage, score_signals, computed_at, cached}. Uses the cached value
    when fresh (< CACHE_TTL_SECONDS) unless force=True. Recompute writes the
    cache back to businesses.settings.maturity (best-effort, non-fatal)."""
    if not business_id:
        return {"stage": "idea", "signals": {}, "computed_at": None, "cached": False}

    if not force:
        cached = _read_cache(business_id)
        if _is_fresh(cached):
            cached["cached"] = True
            return cached

    signals = collect_signals(business_id)
    stage = derive_stage(signals)
    payload = {
        "stage": stage,
        "signals": signals,
        "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        _write_cache(business_id, payload)
    except Exception as e:
        logger.warning(f"maturity cache write failed for {business_id}: {e}")
    payload["cached"] = False
    logger.info(f"maturity biz={business_id} stage={stage} signals={signals}")
    return payload


def get_maturity_stage(business_id: str, force: bool = False) -> str:
    """Convenience: just the stage string. Used by provision gating."""
    return compute_maturity(business_id, force=force).get("stage", "idea")


def stage_at_least(stage: Optional[str], floor: str) -> bool:
    return STAGE_ORDER.get(stage or "idea", 0) >= STAGE_ORDER.get(floor, 0)


# ──────────────────────────────────────────────────────────────
# Chief context block
# ──────────────────────────────────────────────────────────────

def maturity_context_block(business_id: str) -> str:
    """Markdown appended to the Chief context so it speaks to the business's
    actual stage (idea-stage gets setup nudges; scaling-stage gets leverage
    moves). Returns "" on any failure."""
    try:
        m = compute_maturity(business_id)
    except Exception as e:
        logger.warning(f"maturity_context_block failed: {e}")
        return ""
    stage = m.get("stage", "idea")
    guidance = {
        "idea": "Brand-new. Focus on foundation: identity, first offer, first contacts. Don't push operational modules yet.",
        "launching": "Getting off the ground. Core modules are appropriate; encourage first paying clients + consistent intake.",
        "operating": "Running steadily. Suggest operational leverage: recurring revenue, nurture, reporting. Operating-stage modules now fit.",
        "scaling": "Scaling. Surface growth-objective moves: new programs, team/staff, automation, higher-tier offers.",
    }.get(stage, "")
    return f"## Business Maturity\nStage: **{stage}**. {guidance}"
