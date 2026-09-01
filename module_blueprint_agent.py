"""
module_blueprint_agent.py — Business-type → module auto-assembly (Phase 1).

The keystone of the Living Growth System: when onboarding finishes, walk the
business_type_module_blueprint table and provision the CORE module set for that
business type into custom_modules. The Chief then notices any gaps via the
gap-scan block injected into its context.

Reads:
  business_type_module_blueprint  — global, KMJ-curated (one row per type+slug)
  custom_modules                  — to detect what already exists (idempotency)
Writes:
  custom_modules                  — one row per provisioned module

Design notes:
  • Reads and writes with the SERVICE ROLE. custom_modules RLS is scoped to
    the `authenticated` role with no anon policy, and this agent runs
    server-side with no user JWT — the anon key this file used to use could
    neither read nor write it. See the helpers section for the evidence.
  • Idempotent: never creates a module whose slug already exists for the business
    (custom_modules has UNIQUE(business_id, slug); we also pre-check to avoid 409s).
    That pre-check only became REAL with the service role — under the anon key
    _existing_slugs returned an empty set every time and the constraint was
    doing all the deduplication.
  • Maturity-gated: only provisions core modules at/under PROVISION_MAX_STAGE so a
    brand-new business doesn't get empty downstream modules (e.g. Invoices) on day 1.
    Full maturity computation lands in Phase 2; this is the conservative default.
  • Failure is per-module and non-fatal — callers wrap in try/except and never let a
    provisioning hiccup block onboarding or strategy-track completion.
"""

from __future__ import annotations

import os
import json
import logging
from typing import Any, Dict, List, Optional, Set

import httpx

import sb_clients

logger = logging.getLogger("module_blueprint_agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] blueprint: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

HTTP_TIMEOUT = 15.0

# Maturity ladder. Core modules above this stage wait until the business grows
# into them (surfaced by the Chief gap scan, auto-provisioned in a later phase).
STAGE_ORDER = {"idea": 0, "launching": 1, "operating": 2, "scaling": 3}
PROVISION_MAX_STAGE = "launching"


# ──────────────────────────────────────────────────────────────
# Supabase REST helpers
# ──────────────────────────────────────────────────────────────
#
# THE SERVICE ROLE, NOT THE ANON KEY — and this is the second half of a
# bug that had two halves.
#
# This file used to say it "mirrors business_profile_agent.py's sync
# REST-helper pattern (anon key)", and it did. That pattern predates the
# RLS tightening on custom_modules: every policy on that table is now
# scoped to the `authenticated` role and there is NO anon policy. This
# agent runs server-side with no user JWT, so the anon key is neither
# authenticated nor the owner, and Postgres refuses it. Verified against
# production rather than inferred:
#
#   POST /custom_modules -> 401
#   {"code":"42501","message":"new row violates row-level security
#    policy for table \"custom_modules\""}
#
# Two consequences, both silent:
#   1. provision_modules could not create ANY module. _sb_post returned
#      None, the slug went into report["failed"], and the caller's
#      non-fatal wrapper swallowed it.
#   2. _existing_slugs returned an empty set for every business, because
#      the anon key cannot SELECT either — so the idempotency pre-check
#      this module's docstring promises was blind. It never deduplicated
#      anything; the UNIQUE(business_id, slug) constraint was doing that
#      work alone.
#
# The service role is the right credential here: this is system-initiated
# provisioning on a business's behalf, with the business_id supplied by
# the caller rather than chosen by a request. Same choice sb_clients
# already makes for every other server-side agent.
#
# NOTE: business_profile_agent.py still uses the anon key for the pattern
# this file copied. Whether its tables are anon-writable was NOT checked
# here — worth a look, separately.

def _sb_url() -> str:
    return sb_clients.sb_url()


def _sb_headers() -> Dict[str, str]:
    return sb_clients.sb_headers_service()


def _sb_get(path: str) -> Optional[Any]:
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.get(f"{_sb_url()}/rest/v1{path}", headers=_sb_headers())
        if r.status_code >= 400:
            logger.warning(f"sb GET {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"sb GET {path} failed: {e}")
        return None


def _sb_post(path: str, body: Any) -> Optional[Any]:
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.post(
                f"{_sb_url()}/rest/v1{path}",
                headers=_sb_headers(),
                content=json.dumps(body),
            )
        if r.status_code >= 400:
            logger.warning(f"sb POST {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"sb POST {path} failed: {e}")
        return None


# ──────────────────────────────────────────────────────────────
# Blueprint reads
# ──────────────────────────────────────────────────────────────

def get_blueprint(business_type: str) -> List[Dict[str, Any]]:
    """All blueprint rows for a business type, ordered by sort_order.

    Resolves ALIASES first. The table is keyed canonically, so the raw
    lookup this replaces returned zero rows for every alias — and zero
    rows is indistinguishable from "this vertical has no blueprint":
    `provision_modules` creates nothing and reports success, so a business
    stamped 'agency', 'church' or 'coaching' got an empty workspace with
    no error raised anywhere. 'agency' was the most common type in the
    live businesses table.

    Fixed here rather than by adding duplicate rows per alias: the alias
    set grows, and a data copy per synonym drifts the moment one side is
    edited."""
    if not business_type:
        return []
    try:
        import vertical_registry
        key = vertical_registry.resolve(business_type)
    except Exception:
        # Registry unavailable — fall back to the raw string rather than
        # returning nothing. A canonical type still provisions correctly.
        key = (business_type or "").strip().lower()
    rows = _sb_get(
        f"/business_type_module_blueprint"
        f"?business_type=eq.{key}&order=sort_order.asc"
    )
    return rows if isinstance(rows, list) else []


def _existing_slugs(business_id: str) -> Set[str]:
    """Active custom_modules slugs already present for this business."""
    rows = _sb_get(
        f"/custom_modules?business_id=eq.{business_id}&select=slug"
    ) or []
    return {r.get("slug") for r in rows if isinstance(r, dict) and r.get("slug")}


def _stage_le(stage: Optional[str], ceiling: str) -> bool:
    return STAGE_ORDER.get((stage or "launching"), 1) <= STAGE_ORDER.get(ceiling, 1)


# ──────────────────────────────────────────────────────────────
# Provisioning (the auto-assembly walk)
# ──────────────────────────────────────────────────────────────

def provision_modules(
    business_id: str,
    business_type: str,
    max_stage: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Walk the blueprint and create the CORE module set for this business type
    (tier='core' and maturity_stage <= max_stage) that doesn't already exist.

    Phase 2: when max_stage is None (the normal call), the ceiling is the
    business's COMPUTED maturity stage (maturity_engine) rather than a flat
    'launching' — so a business that has grown into operating/scaling gets its
    operating-stage core modules too. Callers may still pass an explicit
    max_stage to override.

    THE CEILING IS FLOORED AT PROVISION_MAX_STAGE, and that is not a
    belt-and-braces nicety — without it this function could never provision
    anything at signup:

        a new business has 0 modules and 0 entries
        -> maturity_engine's 'launching' band needs module_count >= 1 AND
           entry_count >= 1, so derive_stage returns 'idea'
        -> every one of the 66 core blueprint rows is maturity_stage
           'launching'
        -> _stage_le('launching', 'idea') is False for all of them
        -> nothing is created, an empty report is returned, and NOTHING
           ERRORS

    A brand-new business needed at least one module to reach the stage that
    permits it to be given its first module. Eleven of the twelve most
    recently created businesses had zero modules because of it — across
    creative, personal_services, service_provider, ministry, lawyer and
    coach, every one of which had blueprint rows waiting.

    The giveaway that this was a bug and not a design: the except branch
    below already fell back to PROVISION_MAX_STAGE, so a maturity lookup
    that FAILED provisioned more than one that succeeded.

    The gate keeps its real purpose — the 11 'operating' and 'scaling' rows
    still wait for a business to grow into them. It just no longer holds
    back the launching set it was never meant to block.

    Idempotent and per-module non-fatal. Returns a small report:
        {"created": [...slugs], "skipped": [...slugs], "failed": [...slugs]}
    """
    report: Dict[str, Any] = {"created": [], "skipped": [], "failed": [], "skipped_restricted": []}
    if not business_id:
        return report

    if max_stage is None:
        try:
            import maturity_engine
            max_stage = maturity_engine.get_maturity_stage(business_id)
        except Exception as e:
            logger.warning(f"maturity lookup failed, falling back to {PROVISION_MAX_STAGE}: {e}")
            max_stage = PROVISION_MAX_STAGE
        # Floor it. A computed stage BELOW the provisioning floor means the
        # business has not done anything yet — which is exactly when it needs
        # its starting modules, not when it should be denied them.
        if not _stage_le(PROVISION_MAX_STAGE, max_stage):
            logger.info(
                f"maturity stage {max_stage!r} is below the provisioning floor; "
                f"using {PROVISION_MAX_STAGE!r} so the core set can land")
            max_stage = PROVISION_MAX_STAGE

    blueprint = get_blueprint(business_type or "custom")
    if not blueprint:
        logger.info(f"no blueprint for business_type={business_type!r}; nothing to provision")
        return report

    existing = _existing_slugs(business_id)

    for row in blueprint:
        if (row.get("tier") or "core") != "core":
            continue
        # RE-GATED (Fork 25): do NOT auto-provision an access-restricted module
        # (e.g. ministry Giving) until the FRONTEND 25a (locked-endpoint routing) ships.
        # Backend lock + un-gate alone would let the CURRENT frontend write giving through
        # the open module_entries path. Giving stays dormant until BOTH backend+frontend deploy.
        if ((row.get("agent_config") or {}).get("access_level")) == "restricted":
            report["skipped_restricted"].append(row.get("module_slug"))
            continue
        if not _stage_le(row.get("maturity_stage"), max_stage):
            continue
        slug = row.get("module_slug")
        if not slug:
            continue
        if slug in existing:
            report["skipped"].append(slug)
            continue

        payload = {
            "business_id": business_id,
            "name": row.get("module_name") or slug,
            "slug": slug,
            "description": row.get("description"),
            "icon": row.get("icon") or "📋",
            "schema": row.get("schema") or {"fields": []},
            "agent_config": row.get("agent_config") or {"enabled": True, "triggers": []},
            "is_active": True,
            "sort_order": row.get("sort_order") or 0,
        }
        # The blueprint now names the module ARCHETYPE. Without it every
        # provisioned module landed on fallback_generic — so a lawyer's
        # auto-created Matters was a plain list, and the vertical desk,
        # which reads custom_modules where archetype='work_pipeline',
        # never saw it. The lawyer got "No open matters" forever while a
        # Matters module sat right there.
        arch = row.get("archetype")
        if arch:
            payload["archetype"] = arch
        # ...and the archetype's CONFIGURATION, which is not optional in
        # practice. work_pipeline resolves its field names from
        # archetype_params and otherwise falls back to DEFAULT_FIELDS —
        # title / due_date / value. A blueprint whose schema uses different
        # names (nonprofit/grants uses funder / deadline / amount) renders
        # every card with no title, no date and no value unless the params
        # ride along. Naming the archetype without configuring it ships a
        # board that looks broken, which is a worse failure than the plain
        # list it replaced.
        arch_params = row.get("archetype_params")
        if arch_params:
            payload["archetype_params"] = arch_params
        pub = row.get("public_display")
        if pub:
            payload["public_display"] = pub

        created = _sb_post("/custom_modules", payload)
        if created and isinstance(created, list):
            report["created"].append(slug)
            existing.add(slug)
        else:
            report["failed"].append(slug)

    logger.info(
        f"provision biz={business_id} type={business_type}: "
        f"created={report['created']} skipped={len(report['skipped'])} "
        f"restricted={report['skipped_restricted']} failed={report['failed']}"
    )
    return report


# ──────────────────────────────────────────────────────────────
# Gap scan (Chief context)
# ──────────────────────────────────────────────────────────────

def missing_modules(
    business_id: str,
    business_type: str,
    max_stage: str = "scaling",
) -> Dict[str, List[Dict[str, str]]]:
    """
    Diff the blueprint against what the business actually has.
    Returns {"core_missing": [...], "suggested_available": [...]} where each
    entry is {slug, name, reason}. max_stage caps how far ahead we look.
    """
    out: Dict[str, List[Dict[str, str]]] = {"core_missing": [], "suggested_available": [], "access_pending": []}
    if not business_id:
        return out

    blueprint = get_blueprint(business_type or "custom")
    if not blueprint:
        return out
    existing = _existing_slugs(business_id)

    for row in blueprint:
        slug = row.get("module_slug")
        if not slug or slug in existing:
            continue
        if not _stage_le(row.get("maturity_stage"), max_stage):
            continue
        entry = {
            "slug": slug,
            "name": row.get("module_name") or slug,
            "reason": (row.get("reason") or "").strip(),
        }
        # RE-GATED (Fork 25): restricted modules are not offered for creation until
        # the frontend 25a ships — surfaced separately so the Chief does NOT offer them.
        if ((row.get("agent_config") or {}).get("access_level")) == "restricted":
            out["access_pending"].append(entry)
        elif (row.get("tier") or "core") == "core":
            out["core_missing"].append(entry)
        else:
            out["suggested_available"].append(entry)
    return out


def blueprint_gap_block(business_id: str, business_type: str) -> str:
    """
    Markdown block appended to the Chief's Business Profile context so it can
    proactively notice missing modules and offer to create them via the
    existing `ensure_module` action. Returns "" when there's nothing to say.
    """
    try:
        gap = missing_modules(business_id, business_type)
    except Exception as e:
        logger.warning(f"blueprint_gap_block failed: {e}")
        return ""

    core = gap.get("core_missing") or []
    suggested = gap.get("suggested_available") or []
    pending = gap.get("access_pending") or []
    if not core and not suggested and not pending:
        return ""

    lines: List[str] = ["## Module Coverage"]
    if core:
        names = ", ".join(e["name"] for e in core)
        lines.append(
            f"Core modules MISSING for this business type: {names}. "
            f"Offer to set them up (use ensure_module with the blueprint slug)."
        )
    if suggested:
        names = ", ".join(e["name"] for e in suggested)
        lines.append(
            f"Suggested next modules (recommend when relevant, don't auto-create): {names}."
        )
    if pending:
        names = ", ".join(e["name"] for e in pending)
        lines.append(
            f"Access-restricted modules NOT yet available: {names}. Secure routing ships with the "
            f"frontend 25a — do NOT offer to create them yet."
        )
    return "\n".join(lines)
