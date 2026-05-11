"""Pass 4.0d PART 1 — Override FastAPI router.

Mounts under `/chief`. The /chief prefix is shared with PART 2's
forthcoming /chief/message intent-classifier endpoint; this router
provides the override sub-surface that the classifier (and the future
inline-edit UI) will route content-edit intents to.

Endpoints:
  GET    /chief/overrides/{business_id}                — list overrides
  GET    /chief/overrides/{business_id}/{type}/{path}  — get one (404 if missing)
  POST   /chief/override                               — upsert one override
  DELETE /chief/override/{business_id}/{override_id}   — revert by id
  DELETE /chief/overrides/{business_id}/{type}/{path}  — revert by path

  GET    /chief/override/_diag/targets/{business_id}/preview
                                                       — enumerate
    every data-override-target found in the currently-rendered preview
    HTML. Used by the inline-edit UI to discover what's editable.

Owner gating: NONE (matches single-tenant-anon pattern across
slot_system, voice_depth, public_site).

Registration: BEFORE public_site_router in kmj_intake_automation.py
(public_site_router defines the catch-all `/{path:path}` and must
remain last).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.override_system import override_storage
from agents.override_system.override_resolver import find_override_targets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chief", tags=["overrides"])


# ─── Request models ────────────────────────────────────────────────

class UpsertOverrideRequest(BaseModel):
    business_id: str
    override_type: str  # 'text' | 'color_role' | 'slot_image'
    target_path: str
    override_value: str
    target_selector: Optional[str] = None
    original_value: Optional[str] = None
    created_via: str = "manual_edit"  # 'manual_edit' | 'chief_command' | 'director_refine'


# ─── List / get ────────────────────────────────────────────────────

@router.get("/overrides/{business_id}")
def list_overrides_for_business(
    business_id: str,
    override_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Return every override for `business_id`, optionally filtered by
    type via ?override_type=text. Ordered by override_type, target_path.

    Empty list when none exist or the DB is unreachable; callers should
    treat 'no overrides' and 'lookup failed' the same way — both render
    Builder's original output."""
    rows = override_storage.list_overrides(business_id, override_type)
    return {
        "business_id": business_id,
        "override_type_filter": override_type,
        "count": len(rows),
        "overrides": rows,
    }


@router.get("/overrides/{business_id}/{override_type}/{target_path:path}")
def get_one_override(
    business_id: str,
    override_type: str,
    target_path: str,
) -> Dict[str, Any]:
    """Return a single override by (business_id, type, path). 404 if
    no such row. `target_path` uses `:path` so dotted/slashed paths
    like `section[3]/cta_label` survive URL routing."""
    row = override_storage.get_override(business_id, override_type, target_path)
    if not row:
        raise HTTPException(
            404,
            {
                "error": "override_not_found",
                "business_id": business_id,
                "override_type": override_type,
                "target_path": target_path,
            },
        )
    return row


# ─── Create / update (upsert) ──────────────────────────────────────

@router.post("/override")
def upsert_override(req: UpsertOverrideRequest) -> Dict[str, Any]:
    """Insert or update an override on the (business_id, override_type,
    target_path) UNIQUE constraint.

    Validation lives in override_storage.upsert_override and returns
    None for invalid enums or missing required fields; we surface that
    as 400 here so the caller knows it's a bad request rather than a
    transient DB failure.

    color_role and slot_image upserts persist but are NO-OPs at render
    in PART 1 (see override_resolver.py). They land in the table so
    PART 3 / future passes can read them once the resolvers are wired."""
    persisted = override_storage.upsert_override(
        business_id=req.business_id,
        override_type=req.override_type,
        target_path=req.target_path,
        override_value=req.override_value,
        target_selector=req.target_selector,
        original_value=req.original_value,
        created_via=req.created_via,
    )
    if not persisted:
        # Could be: invalid override_type/created_via enum, missing
        # required field, or DB write failure. The storage layer logs
        # the exact reason at WARN; here we return a generic 400/502
        # split based on whether the inputs look syntactically valid.
        looks_valid = (
            req.business_id
            and req.target_path
            and req.override_value is not None
            and req.override_type in {"text", "color_role", "slot_image"}
            and req.created_via in {"manual_edit", "chief_command", "director_refine"}
        )
        if not looks_valid:
            raise HTTPException(
                400,
                {
                    "error": "invalid_override_request",
                    "advice": (
                        "Check override_type is one of "
                        "['text','color_role','slot_image'] and "
                        "created_via is one of "
                        "['manual_edit','chief_command','director_refine']. "
                        "business_id, target_path, override_value all required."
                    ),
                },
            )
        raise HTTPException(
            502,
            {"error": "override_persist_failed"},
        )
    return persisted


# ─── Delete (revert) ───────────────────────────────────────────────

@router.delete("/override/{business_id}/{override_id}")
def delete_one_override(business_id: str, override_id: str) -> Dict[str, Any]:
    """Revert by deleting an override row. business_id is scoped into
    the DELETE WHERE clause so callers can't accidentally delete an
    override that belongs to a different business by passing the wrong
    UUID."""
    ok = override_storage.delete_override_by_id(business_id, override_id)
    if not ok:
        raise HTTPException(
            502,
            {"error": "override_delete_failed"},
        )
    return {"success": True, "business_id": business_id, "override_id": override_id}


@router.delete("/overrides/{business_id}/{override_type}/{target_path:path}")
def delete_override_by_path(
    business_id: str,
    override_type: str,
    target_path: str,
) -> Dict[str, Any]:
    """Revert by (business_id, override_type, target_path). Canonical
    'revert this edit' path for the inline-edit UI — no need to look up
    the override UUID first."""
    ok = override_storage.delete_override_by_path(
        business_id, override_type, target_path
    )
    if not ok:
        raise HTTPException(
            502,
            {"error": "override_delete_failed"},
        )
    return {
        "success": True,
        "business_id": business_id,
        "override_type": override_type,
        "target_path": target_path,
    }


# ─── Diagnostic ────────────────────────────────────────────────────

@router.get("/override/_diag/targets/{business_id}/preview")
def diag_list_targets_in_preview(business_id: str) -> Dict[str, Any]:
    """Enumerate every data-override-target element currently present
    in the persisted preview HTML for `business_id`. Returns the tag
    name, target_path, and the current inner content of each — handy
    for the inline-edit UI to discover what's editable without
    re-parsing on the frontend.

    Soft-fails to an empty list when the site row / HTML isn't present
    so callers don't need to special-case never-built sites."""
    try:
        from brand_engine import _sb_get as be_get
        rows = be_get(
            f"/business_sites?business_id=eq.{business_id}"
            "&select=site_config&limit=1"
        ) or []
        if not rows:
            return {
                "business_id": business_id,
                "count": 0,
                "targets": [],
                "note": "no business_sites row",
            }
        site_config = rows[0].get("site_config") or {}
        html = site_config.get("generated_html") or ""
        targets = find_override_targets(html)
        return {
            "business_id": business_id,
            "count": len(targets),
            "targets": targets,
        }
    except Exception as e:
        logger.warning(
            f"[override_router] diag targets failed for {business_id}: {e}"
        )
        return {
            "business_id": business_id,
            "count": 0,
            "targets": [],
            "error": str(e),
        }
