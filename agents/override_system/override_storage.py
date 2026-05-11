"""Pass 4.0d PART 1 — Override persistence (Supabase REST).

Wraps the site_content_overrides table. Reuses brand_engine._sb_get for
reads; defines _sb_post / _sb_delete locally because brand_engine only
exposes GET + PATCH today.

Functions:
  list_overrides(business_id, override_type=None) -> List[dict]
  get_override(business_id, override_type, target_path) -> Optional[dict]
  upsert_override(business_id, override_type, target_path, override_value,
                  target_selector=None, original_value=None,
                  created_via='manual_edit') -> Optional[dict]
  delete_override_by_id(business_id, override_id) -> bool
  delete_override_by_path(business_id, override_type, target_path) -> bool

Upsert uses PostgREST's resolution=merge-duplicates with
on_conflict=business_id,override_type,target_path (the UNIQUE
constraint from the migration).

Owner gating: NONE at this layer.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# httpx + HTTP_TIMEOUT shared with brand_engine. Imported lazily inside
# functions to keep this module importable in test contexts without
# the network deps.


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_anon() -> str:
    return os.environ.get("SUPABASE_ANON", "")


def _sb_headers(prefer: Optional[str] = None) -> Dict[str, str]:
    """Standard Supabase REST headers. `prefer` lets callers attach
    return=representation, resolution=merge-duplicates, etc."""
    h = {
        "apikey": _sb_anon(),
        "Authorization": f"Bearer {_sb_anon()}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    else:
        h["Prefer"] = "return=representation"
    return h


def _sb_post(path: str, body: Any, prefer: Optional[str] = None) -> Optional[Any]:
    """POST to Supabase REST. `body` is JSON-serialized. Returns parsed
    response JSON on success, None on any failure (logged at WARN)."""
    try:
        import httpx
        from brand_engine import HTTP_TIMEOUT  # reuse the canonical timeout
    except Exception as e:
        logger.warning(f"[override_storage] dep import failed: {e}")
        return None
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.post(
                f"{_sb_url()}/rest/v1{path}",
                headers=_sb_headers(prefer=prefer),
                content=json.dumps(body),
            )
        if r.status_code >= 400:
            logger.warning(f"sb POST {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"sb POST {path} failed: {e}")
        return None


def _sb_delete(path: str) -> bool:
    """DELETE on Supabase REST. Returns True on 2xx, False otherwise."""
    try:
        import httpx
        from brand_engine import HTTP_TIMEOUT
    except Exception as e:
        logger.warning(f"[override_storage] dep import failed: {e}")
        return False
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.delete(
                f"{_sb_url()}/rest/v1{path}",
                headers=_sb_headers(),
            )
        if r.status_code >= 400:
            logger.warning(f"sb DELETE {path}: {r.status_code} {r.text[:200]}")
            return False
        return True
    except httpx.HTTPError as e:
        logger.warning(f"sb DELETE {path} failed: {e}")
        return False


# ─── Read ──────────────────────────────────────────────────────────

def list_overrides(
    business_id: str,
    override_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """All overrides for a business, optionally filtered by type. Empty
    list when none exist or the GET fails. Ordered by override_type
    then target_path so callers can stably iterate."""
    try:
        from brand_engine import _sb_get as be_get
    except Exception as e:
        logger.warning(f"[override_storage] brand_engine import failed: {e}")
        return []
    qs = f"business_id=eq.{business_id}"
    if override_type:
        qs += f"&override_type=eq.{override_type}"
    qs += "&order=override_type.asc,target_path.asc"
    rows = be_get(f"/site_content_overrides?{qs}") or []
    return rows if isinstance(rows, list) else []


def get_override(
    business_id: str,
    override_type: str,
    target_path: str,
) -> Optional[Dict[str, Any]]:
    """Single override matching (business_id, override_type, target_path),
    or None if not present."""
    try:
        from brand_engine import _sb_get as be_get
    except Exception as e:
        logger.warning(f"[override_storage] brand_engine import failed: {e}")
        return None
    rows = be_get(
        f"/site_content_overrides?business_id=eq.{business_id}"
        f"&override_type=eq.{override_type}"
        f"&target_path=eq.{target_path}&limit=1"
    ) or []
    return rows[0] if rows else None


def overrides_as_lookup(
    business_id: str,
    override_type: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Convenience: returns a flat dict keyed by target_path for fast
    resolver lookup. When `override_type` is None, the resolver expects
    the caller to filter per-type so this typically passes a specific
    override_type."""
    return {
        row["target_path"]: row
        for row in list_overrides(business_id, override_type)
        if row.get("target_path")
    }


# ─── Write ─────────────────────────────────────────────────────────

_VALID_TYPES = {"text", "color_role", "slot_image"}
_VALID_CREATED_VIA = {"manual_edit", "chief_command", "director_refine"}


def upsert_override(
    business_id: str,
    override_type: str,
    target_path: str,
    override_value: str,
    target_selector: Optional[str] = None,
    original_value: Optional[str] = None,
    created_via: str = "manual_edit",
) -> Optional[Dict[str, Any]]:
    """Insert or update an override on the (business_id, override_type,
    target_path) UNIQUE constraint. Returns the persisted row, or None
    on validation failure / DB error.

    Validates override_type and created_via against the migration's
    CHECK enums before hitting the DB so callers get a clear None back
    instead of a Postgres 400 buried in logs.
    """
    if override_type not in _VALID_TYPES:
        logger.warning(
            f"[override_storage] invalid override_type={override_type!r}, "
            f"expected one of {sorted(_VALID_TYPES)}"
        )
        return None
    if created_via not in _VALID_CREATED_VIA:
        logger.warning(
            f"[override_storage] invalid created_via={created_via!r}, "
            f"expected one of {sorted(_VALID_CREATED_VIA)}"
        )
        return None
    if not business_id or not target_path or override_value is None:
        logger.warning("[override_storage] upsert missing required fields")
        return None

    body: Dict[str, Any] = {
        "business_id": business_id,
        "override_type": override_type,
        "target_path": target_path,
        "override_value": override_value,
        "created_via": created_via,
    }
    if target_selector is not None:
        body["target_selector"] = target_selector
    if original_value is not None:
        body["original_value"] = original_value

    # PostgREST upsert: POST with resolution=merge-duplicates and the
    # conflict columns named via on_conflict query param. The UNIQUE
    # constraint from the migration matches business_id+override_type
    # +target_path.
    result = _sb_post(
        "/site_content_overrides?on_conflict=business_id,override_type,target_path",
        body,
        prefer="resolution=merge-duplicates,return=representation",
    )
    if not result:
        return None
    # PostgREST returns a list on insert/upsert with return=representation.
    if isinstance(result, list) and result:
        return result[0]
    if isinstance(result, dict):
        return result
    return None


def delete_override_by_id(business_id: str, override_id: str) -> bool:
    """Delete a single override by its UUID. business_id is required as
    a scoping safety check — the DELETE only fires when both match.
    Returns True when the request returned 2xx (note: PostgREST returns
    204 No Content even when 0 rows match, so True doesn't strictly
    confirm a row was deleted)."""
    if not business_id or not override_id:
        return False
    return _sb_delete(
        f"/site_content_overrides?id=eq.{override_id}"
        f"&business_id=eq.{business_id}"
    )


def delete_override_by_path(
    business_id: str,
    override_type: str,
    target_path: str,
) -> bool:
    """Delete the override matching (business_id, override_type,
    target_path). Used as the canonical 'revert this edit' path so the
    caller doesn't need the UUID."""
    if not (business_id and override_type and target_path):
        return False
    return _sb_delete(
        f"/site_content_overrides?business_id=eq.{business_id}"
        f"&override_type=eq.{override_type}"
        f"&target_path=eq.{target_path}"
    )
