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
  • Mirrors business_profile_agent.py's sync REST-helper pattern (anon key).
  • Idempotent: never creates a module whose slug already exists for the business
    (custom_modules has UNIQUE(business_id, slug); we also pre-check to avoid 409s).
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
# Supabase REST helpers (mirrors business_profile_agent.py)
# ──────────────────────────────────────────────────────────────

def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_anon() -> str:
    return os.environ.get("SUPABASE_ANON", "")


def _sb_headers() -> Dict[str, str]:
    return {
        "apikey": _sb_anon(),
        "Authorization": f"Bearer {_sb_anon()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


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
    """All blueprint rows for a business type, ordered by sort_order."""
    if not business_type:
        return []
    rows = _sb_get(
        f"/business_type_module_blueprint"
        f"?business_type=eq.{business_type}&order=sort_order.asc"
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
    max_stage: str = PROVISION_MAX_STAGE,
) -> Dict[str, Any]:
    """
    Walk the blueprint and create the CORE module set for this business type
    (tier='core' and maturity_stage <= max_stage) that doesn't already exist.

    Idempotent and per-module non-fatal. Returns a small report:
        {"created": [...slugs], "skipped": [...slugs], "failed": [...slugs]}
    """
    report: Dict[str, Any] = {"created": [], "skipped": [], "failed": []}
    if not business_id:
        return report

    blueprint = get_blueprint(business_type or "custom")
    if not blueprint:
        logger.info(f"no blueprint for business_type={business_type!r}; nothing to provision")
        return report

    existing = _existing_slugs(business_id)

    for row in blueprint:
        if (row.get("tier") or "core") != "core":
            continue
        # Restricted modules (e.g. Giving) now provision normally: only their CONFIG
        # row lives here; ENTRIES are routed to the locked restricted store by the
        # frontend/backend (Access-Enforcement 25a). access_level travels via agent_config.
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
        f"created={report['created']} skipped={len(report['skipped'])} failed={report['failed']}"
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
    out: Dict[str, List[Dict[str, str]]] = {"core_missing": [], "suggested_available": []}
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
        if (row.get("tier") or "core") == "core":
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
    if not core and not suggested:
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
    return "\n".join(lines)
