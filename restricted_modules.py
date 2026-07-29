"""
restricted_modules.py — backend-mediated access to access_level:"restricted"
module entries (Access-Enforcement 25a, Fork 25).

Restricted entries (e.g. ministry Giving) live in restricted_module_entries,
which is LOCKED: the anon key is REVOKEd and it is not in the realtime
publication, so the frontend CANNOT read it directly. All access goes through
these endpoints, which:
  • require an authenticated Supabase user (auth_supabase.require_user),
  • authorize BUSINESS-OWNER-ONLY (business.owner_id == auth.uid) — this owner
    check is the exact seam where the 25b role-check slots in later,
  • use the SERVICE-ROLE Supabase client (which bypasses RLS) — mirrors
    lead_admin.py's pattern,
  • audit EVERY access (list/read/create/update/delete/denied) to
    restricted_module_access_log (Fork 37 — financial-data access trail).

The restricted module's CONFIG row stays in custom_modules; only its ENTRIES
live in the locked table.
"""

from __future__ import annotations

import os
import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("restricted_modules")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] restricted: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

router = APIRouter(prefix="/restricted-modules", tags=["restricted-modules"])

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=15.0, pool=10.0)


def _service_headers(prefer: Optional[str] = None) -> Dict[str, str]:
    """Service-role headers — bypass RLS to reach the locked table.
    The service-role key is the ONLY credential that can touch
    restricted_module_entries (anon is REVOKEd)."""
    h = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def _sb(method: str, path: str, body: Any = None, prefer: Optional[str] = None) -> Any:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=503, detail="service-role storage not configured")
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as c:
            r = c.request(
                method, f"{SUPABASE_URL}/rest/v1{path}",
                headers=_service_headers(prefer),
                content=json.dumps(body) if body is not None else None,
            )
        if r.status_code >= 400:
            logger.warning(f"sb {method} {path}: {r.status_code} {r.text[:200]}")
            raise HTTPException(status_code=502, detail="storage error")
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"sb {method} {path} failed: {e}")
        raise HTTPException(status_code=502, detail="storage unreachable")


def _audit(business_id: str, module_id: Optional[str], entry_id: Optional[str],
           user: AuthedUser, action: str, detail: Optional[Dict] = None) -> None:
    """Append to the financial-data access trail. Never fatal."""
    try:
        _sb("POST", "/restricted_module_access_log", {
            "business_id": business_id,
            "module_id": module_id,
            "entry_id": entry_id,
            "actor_user_id": user.id,
            "actor_email": user.email,
            "action": action,
            "detail": detail or {},
        }, prefer="return=minimal")
    except Exception as e:
        logger.warning(f"audit write failed ({action}): {e}")


def _authorize(business_id: str, module_id: str, user: AuthedUser) -> Dict[str, Any]:
    """Owner-check + restricted-check. Returns the module row, or raises.

    25b SEAM: replace the `owner_id == user.id` check below with a
    role-permission lookup (business_members) when multi-staff lands.
    """
    if not business_id or not module_id:
        raise HTTPException(status_code=400, detail="business_id and module_id required")

    biz = _sb("GET", f"/businesses?id=eq.{business_id}&select=id,owner_id&limit=1") or []
    if not biz:
        _audit(business_id, module_id, None, user, "denied", {"reason": "business not found"})
        raise HTTPException(status_code=404, detail="business not found")

    is_owner = str(biz[0].get("owner_id")) == str(user.id)

    mod = _sb("GET",
              f"/custom_modules?id=eq.{module_id}&business_id=eq.{business_id}"
              f"&select=id,name,agent_config,restricted_min_role&limit=1") or []
    if not mod:
        _audit(business_id, module_id, None, user, "denied", {"reason": "module not found"})
        raise HTTPException(status_code=404, detail="module not found")
    access = ((mod[0].get("agent_config") or {}).get("access_level"))
    if access != "restricted":
        # Non-restricted modules must NOT use this path (they live in module_entries).
        _audit(business_id, module_id, None, user, "denied", {"reason": "not a restricted module"})
        raise HTTPException(status_code=400, detail="module is not access-restricted")

    # 25b seam, closed. The owner always passes; anyone else needs the module
    # to have opted in to delegation AND to hold a sufficient role.
    #
    # restricted_min_role is NULL by default, which means owner-only — the
    # exact behaviour that existed before this. Nothing widened by adding the
    # column; a business opts in per module. That default matters: giving is
    # the most confidential data a church holds, and many deliberately keep
    # it from their own staff.
    if not is_owner:
        min_role = (mod[0].get("restricted_min_role") or "").strip()
        if not min_role:
            _audit(business_id, module_id, None, user, "denied",
                   {"reason": "not owner; module is owner-only"})
            raise HTTPException(status_code=403,
                                detail="not authorized for this business")
        role = _role_for(business_id, user)
        if not _role_at_least(role, min_role):
            _audit(business_id, module_id, None, user, "denied",
                   {"reason": "role below module minimum",
                    "role": role or "none", "required": min_role})
            raise HTTPException(
                status_code=403,
                detail=f"this module requires the '{min_role}' role or higher")
        # NOT audited as a separate "granted" row on purpose. The access log
        # constrains `action` to list/read/create/update/delete/denied, and
        # the operation the caller went on to perform is audited with its own
        # real action a moment later — so a grant already leaves a trail.
        # Inventing a seventh action value here would have violated the CHECK
        # and, because _audit is best-effort, failed silently: a role-granted
        # access to financial data that logged nothing at all.

    return mod[0]


# Ascending. 'viewer' is deliberately absent from the ALLOWED minimums (see
# the migration) but present here, because a viewer can still be the CALLER
# and must be compared and refused rather than crashing the lookup.
_ROLE_ORDER = ("viewer", "member", "manager", "admin")


def _role_at_least(role: Optional[str], minimum: str) -> bool:
    """True when `role` ranks at or above `minimum`. Unknown or missing role
    answers False — the refusing answer, matching the posture everywhere
    else in this file."""
    if not role:
        return False
    try:
        return _ROLE_ORDER.index(role) >= _ROLE_ORDER.index(minimum)
    except ValueError:
        return False


def _role_for(business_id: str, user: AuthedUser) -> Optional[str]:
    """The caller's ACTIVE role on this business, or None.

    status must be 'active' — an invited-but-not-accepted or revoked
    collaborator holds a role row and must not be let in on it. That is the
    difference between a row existing and a person having access.
    """
    try:
        rows = _sb("GET",
                   f"/business_users?business_id=eq.{business_id}"
                   f"&user_id=eq.{user.id}&status=eq.active"
                   f"&select=role&limit=1") or []
        return (rows[0].get("role") if rows else None)
    except Exception as e:
        logger.warning(f"[restricted] role lookup failed, denying: {e}")
        return None


# ──────────────────────────────────────────────────────────────
# Request models
# ──────────────────────────────────────────────────────────────

class EntryCreate(BaseModel):
    business_id: str
    data: Dict[str, Any] = {}
    status: str = "active"
    source: Optional[str] = None


class EntryUpdate(BaseModel):
    business_id: str
    module_id: str
    data: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


class EntryDelete(BaseModel):
    business_id: str
    module_id: str


# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────

@router.get("/{module_id}/entries")
def list_entries(module_id: str, business_id: str,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _authorize(business_id, module_id, user)
    rows = _sb("GET",
               f"/restricted_module_entries?module_id=eq.{module_id}"
               f"&business_id=eq.{business_id}&status=eq.active"
               f"&order=updated_at.desc&select=*") or []
    _audit(business_id, module_id, None, user, "list", {"count": len(rows)})
    return {"ok": True, "entries": rows}


@router.post("/{module_id}/entries")
def create_entry(module_id: str, body: EntryCreate,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _authorize(body.business_id, module_id, user)
    inserted = _sb("POST", "/restricted_module_entries", {
        "module_id": module_id,
        "business_id": body.business_id,
        "data": body.data or {},
        "status": body.status or "active",
        "created_by": user.email or user.id,
        "source": body.source,
    }, prefer="return=representation")
    row = inserted[0] if isinstance(inserted, list) and inserted else inserted
    _audit(body.business_id, module_id, (row or {}).get("id"), user, "create")
    return {"ok": True, "entry": row}


@router.patch("/entries/{entry_id}")
def update_entry(entry_id: str, body: EntryUpdate,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _authorize(body.business_id, body.module_id, user)
    # IDOR guard: the entry must belong to this business + module.
    existing = _sb("GET",
                   f"/restricted_module_entries?id=eq.{entry_id}"
                   f"&business_id=eq.{body.business_id}&module_id=eq.{body.module_id}"
                   f"&select=id&limit=1") or []
    if not existing:
        _audit(body.business_id, body.module_id, entry_id, user, "denied", {"reason": "entry mismatch"})
        raise HTTPException(status_code=404, detail="entry not found")
    patch: Dict[str, Any] = {}
    if body.data is not None:
        patch["data"] = body.data
    if body.status is not None:
        patch["status"] = body.status
    if not patch:
        raise HTTPException(status_code=400, detail="nothing to update")
    updated = _sb("PATCH", f"/restricted_module_entries?id=eq.{entry_id}", patch,
                  prefer="return=representation")
    _audit(body.business_id, body.module_id, entry_id, user, "update", {"fields": list(patch.keys())})
    row = updated[0] if isinstance(updated, list) and updated else updated
    return {"ok": True, "entry": row}


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, body: EntryDelete,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _authorize(body.business_id, body.module_id, user)
    existing = _sb("GET",
                   f"/restricted_module_entries?id=eq.{entry_id}"
                   f"&business_id=eq.{body.business_id}&module_id=eq.{body.module_id}"
                   f"&select=id&limit=1") or []
    if not existing:
        _audit(body.business_id, body.module_id, entry_id, user, "denied", {"reason": "entry mismatch"})
        raise HTTPException(status_code=404, detail="entry not found")
    _sb("DELETE", f"/restricted_module_entries?id=eq.{entry_id}", prefer="return=minimal")
    _audit(body.business_id, body.module_id, entry_id, user, "delete")
    return {"ok": True}
