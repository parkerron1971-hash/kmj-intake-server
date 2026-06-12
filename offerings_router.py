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


def _refresh_composed_site(business_id: Optional[str]) -> None:
    """Arc 28b — keep module-composer sites' offerings/store sections
    live: any catalog mutation re-renders the page from its stored spec
    in the background (no LLM; no-op for legacy/Smart Sites pages).
    Never blocks or fails the catalog write."""
    if not business_id:
        return
    try:
        from site_composer import refresh_if_composed_async
        refresh_if_composed_async(str(business_id))
    except Exception as e:
        logger.warning(f"[offerings] composed-site refresh hook failed: {e}")


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
    # 500 chars cap — a generous one-paragraph description; longer copy
    # belongs in a separate marketing surface, not the offerings catalog.
    description: Optional[str] = Field(default=None, max_length=500)
    current_price: Optional[float] = Field(default=None, ge=0)
    currency: str = "usd"
    duration_min: Optional[int] = Field(default=None, gt=0)
    show_price_to_customer: bool = True
    # Arc 27 — product fields (store MVP)
    image_url: Optional[str] = Field(default=None, max_length=600)
    sku: Optional[str] = Field(default=None, max_length=80)
    inventory_qty: Optional[int] = Field(default=None, ge=0)
    requires_shipping: Optional[bool] = None
    fulfillment_note: Optional[str] = Field(default=None, max_length=600)

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
    # 500 chars cap — see OfferingCreateBody.description.
    description: Optional[str] = Field(default=None, max_length=500)
    category: Optional[str] = None
    current_price: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = None
    duration_min: Optional[int] = Field(default=None, gt=0)
    show_price_to_customer: Optional[bool] = None
    is_active: Optional[bool] = None
    # Arc 27 — product fields (store MVP)
    image_url: Optional[str] = Field(default=None, max_length=600)
    sku: Optional[str] = Field(default=None, max_length=80)
    inventory_qty: Optional[int] = Field(default=None, ge=0)
    requires_shipping: Optional[bool] = None
    fulfillment_note: Optional[str] = Field(default=None, max_length=600)

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
        # Arc 27 — product fields pass through when provided (columns
        # exist after the arc27_store migration; PostgREST rejects
        # unknown columns, so only include set fields).
        **({"image_url": body.image_url} if body.image_url is not None else {}),
        **({"sku": body.sku} if body.sku is not None else {}),
        **({"inventory_qty": body.inventory_qty} if body.inventory_qty is not None else {}),
        **({"requires_shipping": body.requires_shipping} if body.requires_shipping is not None else {}),
        **({"fulfillment_note": body.fulfillment_note} if body.fulfillment_note is not None else {}),
    })
    if not (isinstance(created, list) and created):
        logger.warning(
            f"offering create failed for biz={body.business_id} slug={slug!r} — "
            f"see preceding sb_clients log line for detail"
        )
        raise HTTPException(status_code=500, detail="Something went wrong on our end — please try again.")
    _refresh_composed_site(body.business_id)
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
    # Arc 27 — product fields
    if body.image_url is not None:             update["image_url"] = body.image_url or None
    if body.sku is not None:                   update["sku"] = body.sku or None
    if body.inventory_qty is not None:         update["inventory_qty"] = body.inventory_qty
    if body.requires_shipping is not None:     update["requires_shipping"] = body.requires_shipping
    if body.fulfillment_note is not None:      update["fulfillment_note"] = body.fulfillment_note or None
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
    _refresh_composed_site(rows[0].get("business_id") if rows else None)
    return {"ok": True, "offering": rows[0] if rows else None}


@router.post("/{offering_id}/archive")
def archive_offering(offering_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    owner = _owner_for_offering(offering_id)
    if not owner:
        raise HTTPException(status_code=404, detail="offering not found")
    if str(owner) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")
    rows = sb_clients.sb_get_as_service(
        f"/offerings?id=eq.{offering_id}&select=business_id&limit=1") or []
    sb_clients.sb_patch_as_service(
        f"/offerings?id=eq.{offering_id}",
        {
            "is_active": False,
            "archived_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )
    _refresh_composed_site(rows[0].get("business_id") if rows else None)
    return {"ok": True, "offering_id": offering_id, "archived": True}


# ─── Arc 28 — category behavior readiness ────────────────────────────


@router.get("/readiness")
def offerings_readiness(
    business_id: str = Query(...),
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Per-offering functional readiness (Arc 28 behavior profiles):
    bookable offerings check duration + booking page + site; sellable
    ones check price + site + Stripe + stock. Computed live from
    business state — see offering_profiles.py."""
    _require_owner(business_id, user)
    import offering_profiles
    return {"ok": True, **offering_profiles.business_readiness(business_id)}
