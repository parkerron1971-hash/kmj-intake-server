"""
module_spec_router.py — Phase B dock-facing surface.

Owner-checked endpoints for the Chief dock's spec card stack:
  POST /module-specs/propose                  generate (1+ specs) for an intake
  POST /module-specs/{spec_id}/accept         materialize → custom_modules + workflows
  POST /module-specs/{spec_id}/reject         mark rejected
  GET  /module-specs?business_id=…&status=…   list (debug + reload)

Owner check mirrors workflow_router / restricted_modules / growth_objective_router.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException

from auth_supabase import AuthedUser, require_user
import module_spec_generator as msg
import module_vocabulary

logger = logging.getLogger("module_spec_router")
router = APIRouter(prefix="/module-specs", tags=["module-specs"])
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


def _service_headers() -> Dict[str, str]:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _sb_get(path: str) -> Any:
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    try:
        with httpx.Client(timeout=_TIMEOUT) as c:
            r = c.get(f"{url}/rest/v1{path}", headers=_service_headers())
        return r.json() if r.text and r.status_code < 400 else None
    except httpx.HTTPError as e:
        logger.warning(f"sb GET {path} failed: {e}")
        return None


def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    """Owner check. Returns the business row (owner_id + type) so callers
    that also need the vertical for the scope guard don't re-fetch."""
    rows = _sb_get(f"/businesses?id=eq.{business_id}&select=owner_id,type&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")
    return rows[0]


def _spec_context(spec_id: str) -> Optional[Dict[str, Any]]:
    """Get the business owner_id + type + draft_json for a spec — used by
    accept/reject endpoints where the caller passes spec_id without
    business_id. Returns None when the spec or its business is missing."""
    rows = _sb_get(
        f"/module_specs?id=eq.{spec_id}&select=business_id,draft_json&limit=1") or []
    if not rows:
        return None
    biz_id = rows[0].get("business_id")
    biz_rows = _sb_get(f"/businesses?id=eq.{biz_id}&select=owner_id,type&limit=1") or []
    if not biz_rows:
        return None
    return {
        "owner_id": biz_rows[0].get("owner_id"),
        "business_type": biz_rows[0].get("type"),
        "draft_json": rows[0].get("draft_json") or {},
    }


# ─── R1 — HIPAA scope guard at the REST seam ─────────────────────────
# vertical_scope.check_module_scope was only wired into the two Chief
# handlers; this router — the endpoints ModuleSpecProposalCard actually
# calls — had no guard, so a therapist could propose + materialize a
# "Progress Notes" module through the UI with no refusal. The guard now
# runs here too. 422 with a STRING detail on refusal: the card's
# _structuredErrorMessage helper parses `detail` from the JSON body and
# renders it inline + as a toast, so the practitioner sees the actual
# refusal ("…out of scope… HIPAA…") rather than "HTTP 4xx".

_SCOPE_UNAVAILABLE = (
    "The safety check for this vertical couldn't run, so nothing was "
    "created. Please try again."
)


def _scope_guard(business_type: Optional[str], *parts: Optional[str]) -> None:
    """Raise 422 if the described module is out of scope for this vertical.

    Fails CLOSED: if the check itself can't run, refuse rather than let a
    potentially-clinical module through — a false refusal here is an
    inconvenience; a false allow is a HIPAA exposure."""
    try:
        import vertical_scope
        ok, refusal = vertical_scope.check_module_scope(business_type, *parts)
    except Exception as e:
        logger.error(f"[scope] guard could not run (refusing): {e}")
        raise HTTPException(status_code=422, detail=_SCOPE_UNAVAILABLE)
    if not ok:
        raise HTTPException(status_code=422, detail=refusal)


def _module_scope_parts(draft: Dict[str, Any]) -> list:
    """name/slug/description + field labels — the same shape the Chief
    accept handler checks, so 'Sessions' with a 'diagnosis' field is caught
    exactly like a module named 'Clinical Notes'."""
    fields = (draft.get("schema") or {}).get("fields") or []
    labels = " ".join(
        str(f.get("label") or f.get("name") or "")
        for f in fields if isinstance(f, dict))
    return [draft.get("name"), draft.get("slug"), draft.get("description"), labels]


@router.post("/propose")
async def propose(body: Dict[str, Any], user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    business_id = (body or {}).get("business_id")
    intake = (body or {}).get("intake_excerpt", "")
    revise = (body or {}).get("revise_feedback")
    if not business_id or not intake:
        raise HTTPException(status_code=400, detail="business_id and intake_excerpt required")
    biz = _require_owner(business_id, user)
    # R1 — refuse a clinical ask before any LLM generation or draft rows.
    # The generated specs are re-checked at accept + materialize, so an
    # innocuous intake that the LLM turns clinical is still caught.
    _scope_guard(biz.get("type"), intake, revise)
    import asyncio
    res = await asyncio.to_thread(msg.propose_module_from_intake, business_id, intake, revise)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "propose failed"))
    return res


@router.post("/{spec_id}/accept")
async def accept(spec_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    ctx = _spec_context(spec_id)
    if not ctx or not ctx.get("owner_id"):
        raise HTTPException(status_code=404, detail="spec not found")
    if str(ctx["owner_id"]) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")
    # R1 — scope-check the draft about to be materialized. Module drafts
    # only: offerings are billing items ("Psychotherapy — 50 min" is a
    # price, not a clinical record) and blocking those would break the
    # vertical's core purpose. materialize_spec re-checks (defense in
    # depth for future callers); this is the seam that shapes the 422.
    draft = ctx["draft_json"]
    if (draft.get("__kind") or "module") == "module":
        _scope_guard(ctx.get("business_type"), *_module_scope_parts(draft))
    import asyncio
    res = await asyncio.to_thread(msg.materialize_spec, spec_id)
    if not res.get("ok"):
        # C.1.5.5 Finding D backend — forward the rich `detail` field
        # from materialize_spec (e.g. M3-δ's multi_module_not_supported
        # full prose) so the frontend can show practitioner-readable
        # text instead of just the machine token. Fall back to the
        # `error` token if no detail is set (matches pre-fix behavior).
        raise HTTPException(
            status_code=400,
            detail=res.get("detail") or res.get("error") or "materialize failed",
        )
    return res


@router.post("/{spec_id}/reject")
async def reject(spec_id: str, body: Optional[Dict[str, Any]] = None,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    # NO scope guard here on purpose — rejecting an out-of-scope draft is
    # exactly what a practitioner should be able to do.
    ctx = _spec_context(spec_id)
    if not ctx or not ctx.get("owner_id"):
        raise HTTPException(status_code=404, detail="spec not found")
    if str(ctx["owner_id"]) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")
    import asyncio
    res = await asyncio.to_thread(msg.reject_spec, spec_id, (body or {}).get("reason"))
    return res


@router.get("")
async def list_specs(business_id: str, status: Optional[str] = None,
                     user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _require_owner(business_id, user)
    import asyncio
    rows = await asyncio.to_thread(msg.list_specs, business_id, status)
    return {"ok": True, "specs": rows}


@router.get("/vocabulary")
async def vocabulary(user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The module vocabulary as data — field types, view kinds, trigger
    kinds, offering categories.

    WHY THIS EXISTS. The vocabulary is declared once per repo
    (module_vocabulary.py here, moduleVocabulary.ts in the studio) and a
    TS union has to exist at compile time, so the frontend copy cannot
    simply be deleted. What it CAN stop doing is guessing: the builder
    now asks the server what the server allows, and reports the
    difference instead of silently offering a type Chief will never
    produce — or hiding one it will.

    Authenticated but not business-scoped: this is a platform constant,
    identical for every tenant, and contains no tenant data. It is behind
    auth because every read in this service is.

    Route lives under /module-specs because that is the router that owns
    the spec surface; nothing here is spec-specific.
    """
    return {"ok": True, "vocabulary": module_vocabulary.as_dict()}
