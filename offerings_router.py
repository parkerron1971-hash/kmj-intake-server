"""
offerings_router.py — Phase C.1.2 — CRUD for the canonical pricing layer.

Per-business offerings (services, sessions, events, courses, products,
packages, custom). Practitioner-facing endpoints with JWT auth + owner
check. Customer-facing reads go through the widget routes
(/widgets/booking/.../config-anon) which use service-role internally
and scope by token claims.

Endpoints:
  GET    /offerings?business_id=…[&category=…&active=true|false]
         List offerings for a business. Optionally filter by category
         (single value) and active state (default true).

  POST   /offerings
         Body: {business_id, name, slug, category, current_price?, currency?,
                duration_min?, description?, show_price_to_customer?}
         Create a new offering.

  PATCH  /offerings/{offering_id}
         Body: any subset of {name, slug, description, category,
                current_price, currency, duration_min,
                show_price_to_customer, is_active}
         Update. Note: changes do NOT propagate to historical
         module_entries — those captured price_at_booking etc. at
         create-time per P5 ruling. The widget config endpoint always
         serves current_price.

  POST   /offerings/{offering_id}/archive
         Soft-delete: sets is_active=false + archived_at=now().
         Existing references to this offering id still resolve for
         display (denormalized fields preserve historical data).

Cross-tenant isolation: every endpoint uses owner-check mirroring the
module_spec_router / workflow_router pattern.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from auth_supabase import AuthedUser, require_user
import sb_clients

logger = logging.getLogger("offerings_router")
router = APIRouter(prefix="/offerings", tags=["offerings"])


# ─── Helpers ─────────────────────────────────────────────────────────


def _require_owner(business_id: str, user: AuthedUser) -> None:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1"
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")


def _owner_for_offering(offering_id: str) -> Optional[str]:
    """Lookup owner_id for a given offering via its business_id."""
    rows = sb_clients.sb_get_as_service(
        f"/offerings?id=eq.{offering_id}&select=business_id&limit=1"
    ) or []
    if not rows:
        return None
    biz_id = rows[0].get("business_id")
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz_id}&select=owner_id&limit=1"
    ) or []
    return biz_rows[0].get("owner_id") if biz_rows else None


_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_VALID_CATEGORIES = {"service", "session", "event", "course", "product", "package", "custom"}


def _validate_slug(slug: str) -> str:
    s = (slug or "").strip().lower()
    if not _SLUG_RE.match(s):
        raise HTTPException(
            status_code=400,
            detail="slug must be kebab-case (lowercase letters, digits, hyphens — e.g. 'haircut' or 'beard-trim')",
        )
    return s


# ─── Pydantic bodies ─────────────────────────────────────────────────


class OfferingCreateBody(BaseModel):
    business_id: str
    name: str = Field(..., min_length=1, max_length=200)
    slug: str
    category: str
    description: Optional[str] = None
    current_price: Optional[float] = Field(default=None, ge=0)
    currency: str = "usd"
    duration_min: Optional[int] = Field(default=None, gt=0)
    show_price_to_customer: bool = True

    @field_validator("category")
    @classmethod
    def _cat_ok(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in _VALID_CATEGORIES:
            raise ValueError(
                f"category must be one of {sorted(_VALID_CATEGORIES)} — "
                f"'donation' is intentionally excluded (Fork 25 Giving guard)"
            )
        return v


class OfferingPatchBody(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    slug: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    current_price: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = None
    duration_min: Optional[int] = Field(default=None, gt=0)
    show_price_to_customer: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("category")
    @classmethod
    def _cat_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip().lower()
        if v not in _VALID_CATEGORIES:
            raise ValueError(
                f"category must be one of {sorted(_VALID_CATEGORIES)}"
            )
        return v


# ─── Endpoints ───────────────────────────────────────────────────────


@router.get("")
def list_offerings(
    business_id: str = Query(...),
    category: Optional[str] = Query(default=None),
    active: bool = Query(default=True),
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _require_owner(business_id, user)
    q = f"/offerings?business_id=eq.{business_id}&order=name.asc&select=*"
    if active:
        q += "&is_active=eq.true"
    if category:
        if category not in _VALID_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"unknown category '{category}'")
        q += f"&category=eq.{category}"
    rows = sb_clients.sb_get_as_service(q) or []
    return {"ok": True, "offerings": rows}


@router.post("")
def create_offering(body: OfferingCreateBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _require_owner(body.business_id, user)
    slug = _validate_slug(body.slug)

    # Idempotent on (business_id, lower(slug)) — DB has the UNIQUE index.
    existing = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{body.business_id}&slug=eq.{slug}&select=id,name&limit=1"
    ) or []
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"offering with slug '{slug}' already exists for this business "
                   f"(currently named '{existing[0].get('name')}')",
        )

    created = sb_clients.sb_post_as_service("/offerings", {
        "business_id": body.business_id,
        "name": body.name,
        "slug": slug,
        "description": body.description,
        "category": body.category,
        "current_price": body.current_price,
        "currency": body.currency or "usd",
        "duration_min": body.duration_min,
        "show_price_to_customer": body.show_price_to_customer,
        "is_active": True,
    })
    if not (isinstance(created, list) and created):
        logger.warning(
            f"offering create failed for biz={body.business_id} slug={slug!r} — "
            f"see preceding sb_clients log line for detail"
        )
        raise HTTPException(status_code=500, detail="Something went wrong on our end — please try again.")
    return {"ok": True, "offering": created[0]}


@router.patch("/{offering_id}")
def patch_offering(
    offering_id: str,
    body: OfferingPatchBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    owner = _owner_for_offering(offering_id)
    if not owner:
        raise HTTPException(status_code=404, detail="offering not found")
    if str(owner) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")

    update: Dict[str, Any] = {}
    if body.name is not None:                  update["name"] = body.name
    if body.slug is not None:                  update["slug"] = _validate_slug(body.slug)
    if body.description is not None:           update["description"] = body.description
    if body.category is not None:              update["category"] = body.category
    if body.current_price is not None:         update["current_price"] = body.current_price
    if body.currency is not None:              update["currency"] = body.currency
    if body.duration_min is not None:          update["duration_min"] = body.duration_min
    if body.show_price_to_customer is not None: update["show_price_to_customer"] = body.show_price_to_customer
    if body.is_active is not None:             update["is_active"] = body.is_active
    if not update:
        raise HTTPException(status_code=400, detail="no fields to update")

    # P5 — price updates do NOT propagate to historical module_entries.
    # The denormalized price_at_booking / service_name_at_booking /
    # duration_min_at_booking on existing entries preserve the captured
    # state. The widget config endpoint always serves the new current_price
    # for future bookings.
    update["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    res = sb_clients.sb_patch_as_service(
        f"/offerings?id=eq.{offering_id}", update,
    )
    if not res:
        logger.warning(
            f"offering patch failed offering_id={offering_id} — "
            f"see preceding sb_clients log line for detail"
        )
        raise HTTPException(status_code=500, detail="Something went wrong on our end — please try again.")
    rows = sb_clients.sb_get_as_service(
        f"/offerings?id=eq.{offering_id}&select=*&limit=1"
    ) or []
    return {"ok": True, "offering": rows[0] if rows else None}


@router.post("/{offering_id}/archive")
def archive_offering(offering_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    owner = _owner_for_offering(offering_id)
    if not owner:
        raise HTTPException(status_code=404, detail="offering not found")
    if str(owner) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")
    sb_clients.sb_patch_as_service(
        f"/offerings?id=eq.{offering_id}",
        {
            "is_active": False,
            "archived_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )
    return {"ok": True, "offering_id": offering_id, "archived": True}
