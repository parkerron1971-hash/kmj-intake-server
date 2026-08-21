"""
suppliers_router.py — THE SOURCING DESK, stage 0 (2026-08-21).

A vendor as an entity instead of two free-text columns on a product.

THE CACHE CONTRACT — read this before changing anything here
    offerings.supplier_name / supplier_email are NOT a second source of
    truth. They are a denormalized cache of whichever supplier is primary
    for that product, and this module is the only thing that maintains
    them. Five live readers still use those columns — the hourly reorder
    sweep, compose_purchase_order(), the notification action payload, the
    Chief inventory verbs, and the frontend's reorder dialog — so every
    write in here that could change "who supplies this product" ends by
    calling _sync_offering_cache() for each affected offering:

        link created / deleted        → sync that offering
        is_primary moved              → sync that offering
        supplier's name/email edited  → sync every offering it is primary for
        supplier deleted              → sync every offering it was primary for

    Miss one of those and a practitioner's purchase order goes to the
    wrong address, silently, an hour later. That is the whole reason the
    sync is one function called from one place per write.

Owner writes, seat/accountant reads — the bills_router split, because a
vendor list is operational and the people who can see the stock should be
able to see who it comes from.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("suppliers_router")

router = APIRouter(prefix="/suppliers", tags=["suppliers"])

_SOURCES = ("manual", "sourcing", "import")
_STATUSES = ("candidate", "contacted", "active", "passed")
_LIST_CAP = 1000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(v: Optional[str]) -> Optional[str]:
    s = (v or "").strip()
    return s or None


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _reader(biz: str, user: AuthedUser) -> Dict[str, Any]:
    """Owner, active accountant, or any seat with at least viewer — the
    same tier that can already see the stock these vendors supply."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    row = rows[0]
    if str(row.get("owner_id")) == str(user.id):
        return row
    from business_collaborators_router import is_active_accountant
    if is_active_accountant(biz, str(user.id)):
        return row
    from business_users_router import require_role
    require_role(biz, str(user.id), "viewer")
    return row


def _supplier_or_404(supplier_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/suppliers?id=eq.{supplier_id}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "vendor not found")
    return rows[0]


def _link_or_404(link_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/offering_suppliers?id=eq.{link_id}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "link not found")
    return rows[0]


# ─── The cache contract ──────────────────────────────────────────────

def _sync_offering_cache(offering_id: str) -> None:
    """Point offerings.supplier_name/email at whoever is primary now.

    No primary link → both cleared, which is the honest answer: nobody
    supplies this product, so the reorder sweep should say so rather than
    keep addressing a vendor the practitioner unlinked.

    Deliberately swallows its own failure. Losing the cache write is bad;
    failing the practitioner's save because of it is worse, and the next
    write through this path repairs it.
    """
    try:
        links = sb_clients.sb_get_as_service(
            f"/offering_suppliers?offering_id=eq.{offering_id}"
            f"&is_primary=is.true&select=supplier_id&limit=1") or []
        name: Optional[str] = None
        email: Optional[str] = None
        if links:
            sup = sb_clients.sb_get_as_service(
                f"/suppliers?id=eq.{links[0]['supplier_id']}"
                f"&select=name,email&limit=1") or []
            if sup:
                name = _clean(sup[0].get("name"))
                email = _clean(sup[0].get("email"))
        sb_clients.sb_patch_as_service(
            f"/offerings?id=eq.{offering_id}",
            {"supplier_name": name, "supplier_email": email})
    except Exception as e:
        logger.warning(f"[suppliers] cache sync failed for {offering_id}: {e}")


def _sync_all_for_supplier(supplier_id: str) -> None:
    """Every product this vendor is primary for. Used after an edit to the
    vendor's own name or address, and before a delete."""
    links = sb_clients.sb_get_as_service(
        f"/offering_suppliers?supplier_id=eq.{supplier_id}"
        f"&is_primary=is.true&select=offering_id&limit={_LIST_CAP}") or []
    for l in links:
        _sync_offering_cache(str(l["offering_id"]))


def _clear_other_primaries(offering_id: str, keep_link_id: str) -> None:
    """The partial unique index allows exactly one primary per offering,
    so the old one is demoted before the new one is promoted."""
    sb_clients.sb_patch_as_service(
        f"/offering_suppliers?offering_id=eq.{offering_id}"
        f"&is_primary=is.true&id=neq.{keep_link_id}",
        {"is_primary": False, "updated_at": _now_iso()})


def _product_counts(business_id: str) -> Dict[str, int]:
    rows = sb_clients.sb_get_as_service(
        f"/offering_suppliers?business_id=eq.{business_id}"
        f"&select=supplier_id&limit={_LIST_CAP}") or []
    out: Dict[str, int] = {}
    for r in rows:
        k = str(r.get("supplier_id"))
        out[k] = out.get(k, 0) + 1
    return out


# ─── Endpoints: the vendor list ──────────────────────────────────────

@router.get("")
def list_suppliers(biz: str, status: Optional[str] = None,
                   user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _reader(biz, user)
    parts = [f"business_id=eq.{biz}"]
    if status:
        if status not in _STATUSES:
            raise HTTPException(400, "unknown status")
        parts.append(f"status=eq.{status}")
    parts.append(f"order=name.asc&select=*&limit={_LIST_CAP}")
    rows = sb_clients.sb_get_as_service(f"/suppliers?{'&'.join(parts)}") or []
    counts = _product_counts(biz)
    for r in rows:
        r["product_count"] = counts.get(str(r.get("id")), 0)
    return {"ok": True, "suppliers": rows}


class SupplierBody(BaseModel):
    business_id: str
    name: str
    website: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    contact_name: Optional[str] = None
    categories: Optional[List[str]] = None
    min_order: Optional[str] = None
    lead_time_days: Optional[int] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    source: str = "manual"
    source_url: Optional[str] = None
    status: str = "active"


def _validated(body: Dict[str, Any]) -> Dict[str, Any]:
    email = _clean(body.get("email"))
    if email and not _EMAIL_RE.match(email):
        raise HTTPException(400, "that email doesn't look like an address")
    src = body.get("source") or "manual"
    if src not in _SOURCES:
        raise HTTPException(400, "unknown source")
    st = body.get("status") or "active"
    if st not in _STATUSES:
        raise HTTPException(400, "unknown status")
    # A vendor we cannot point back at a real page is a vendor we invented.
    if src == "sourcing" and not _clean(body.get("source_url")):
        raise HTTPException(400, "a sourced vendor must carry its source_url")
    ltd = body.get("lead_time_days")
    if ltd is not None and (not isinstance(ltd, int) or ltd < 0 or ltd > 3650):
        raise HTTPException(400, "lead time should be a number of days")
    return body


@router.post("")
def create_supplier(body: SupplierBody,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(body.business_id, user)
    name = _clean(body.name)
    if not name:
        raise HTTPException(400, "a vendor needs a name")
    payload = _validated(body.model_dump())
    row = {
        "business_id": body.business_id,
        "name": name,
        "website": _clean(body.website),
        "email": _clean(body.email),
        "phone": _clean(body.phone),
        "contact_name": _clean(body.contact_name),
        "categories": [c.strip() for c in (body.categories or []) if c and c.strip()],
        "min_order": _clean(body.min_order),
        "lead_time_days": body.lead_time_days,
        "payment_terms": _clean(body.payment_terms),
        "notes": _clean(body.notes),
        "source": payload["source"],
        "source_url": _clean(body.source_url),
        "status": payload["status"],
        "updated_at": _now_iso(),
    }
    if row["source"] == "sourcing":
        row["found_at"] = _now_iso()
    created = sb_clients.sb_post_as_service("/suppliers", row) or []
    if not created:
        raise HTTPException(500, "could not save that vendor")
    out = created[0] if isinstance(created, list) else created
    out["product_count"] = 0
    return {"ok": True, "supplier": out}


@router.get("/{supplier_id}")
def get_supplier(supplier_id: str,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    sup = _supplier_or_404(supplier_id)
    _reader(str(sup["business_id"]), user)
    links = sb_clients.sb_get_as_service(
        f"/offering_suppliers?supplier_id=eq.{supplier_id}"
        f"&select=*&order=created_at.asc&limit={_LIST_CAP}") or []
    if links:
        ids = ",".join(str(l["offering_id"]) for l in links)
        offs = sb_clients.sb_get_as_service(
            f"/offerings?id=in.({ids})&select=id,name,inventory_qty,reorder_at"
            f"&limit={_LIST_CAP}") or []
        by_id = {str(o["id"]): o for o in offs}
        for l in links:
            l["offering"] = by_id.get(str(l["offering_id"]))
    sup["products"] = links
    sup["product_count"] = len(links)
    return {"ok": True, "supplier": sup}


class SupplierPatch(BaseModel):
    name: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    contact_name: Optional[str] = None
    categories: Optional[List[str]] = None
    min_order: Optional[str] = None
    lead_time_days: Optional[int] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    # Fields the practitioner may blank out. PATCH bodies cannot tell
    # "unset" from "clear", so clearing is explicit.
    clear: Optional[List[str]] = None


_PATCHABLE = ("name", "website", "email", "phone", "contact_name", "categories",
              "min_order", "lead_time_days", "payment_terms", "notes", "status")
_CLEARABLE = ("website", "email", "phone", "contact_name", "min_order",
              "lead_time_days", "payment_terms", "notes")


@router.patch("/{supplier_id}")
def update_supplier(supplier_id: str, body: SupplierPatch,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    sup = _supplier_or_404(supplier_id)
    _owner(str(sup["business_id"]), user)

    given = body.model_dump(exclude_none=True)
    patch: Dict[str, Any] = {}
    for k in _PATCHABLE:
        if k not in given:
            continue
        if k == "categories":
            patch[k] = [c.strip() for c in (given[k] or []) if c and c.strip()]
        elif k == "lead_time_days":
            patch[k] = given[k]
        else:
            v = _clean(given[k])
            if k == "name" and not v:
                raise HTTPException(400, "a vendor needs a name")
            patch[k] = v
    for k in (body.clear or []):
        if k in _CLEARABLE:
            patch[k] = None
    if not patch:
        return {"ok": True, "supplier": sup}

    _validated({
        "email": patch.get("email", sup.get("email")),
        "source": sup.get("source"),
        # An existing sourced row keeps the url it was created with, so
        # re-validating against the stored value is the honest check.
        "source_url": sup.get("source_url"),
        "status": patch.get("status", sup.get("status")),
        "lead_time_days": patch.get("lead_time_days", sup.get("lead_time_days")),
    })

    patch["updated_at"] = _now_iso()
    sb_clients.sb_patch_as_service(f"/suppliers?id=eq.{supplier_id}", patch)

    # The name or the address may just have moved. Every product this
    # vendor is primary for now addresses its purchase order differently.
    if "name" in patch or "email" in patch:
        _sync_all_for_supplier(supplier_id)

    return {"ok": True, "supplier": _supplier_or_404(supplier_id)}


@router.delete("/{supplier_id}")
def delete_supplier(supplier_id: str, force: bool = False,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Deleting a vendor that supplies products is allowed but never
    silent: those products lose their reorder address, so the count comes
    back as a 409 the first time and the caller has to mean it."""
    sup = _supplier_or_404(supplier_id)
    _owner(str(sup["business_id"]), user)

    links = sb_clients.sb_get_as_service(
        f"/offering_suppliers?supplier_id=eq.{supplier_id}"
        f"&select=offering_id,is_primary&limit={_LIST_CAP}") or []
    if links and not force:
        raise HTTPException(409, {
            "error": "vendor_has_products",
            "product_count": len(links),
            "message": (f"{sup.get('name')} supplies {len(links)} "
                        f"product{'' if len(links) == 1 else 's'}. "
                        f"Deleting clears their reorder address."),
        })

    affected = [str(l["offering_id"]) for l in links if l.get("is_primary")]
    # The links go with the row (ON DELETE CASCADE); the cache does not,
    # so it is repaired after the row is gone and the primaries with it.
    sb_clients.sb_delete_as_service(f"/suppliers?id=eq.{supplier_id}")
    for oid in affected:
        _sync_offering_cache(oid)
    return {"ok": True, "deleted": supplier_id, "products_unlinked": len(links)}


# ─── Endpoints: the link ─────────────────────────────────────────────
#
# These sit at two path segments (/links/{id}), so they cannot collide
# with the one-segment /{supplier_id} routes above regardless of order.

class LinkPatch(BaseModel):
    unit_cost: Optional[float] = None
    moq: Optional[int] = None
    sku_at_supplier: Optional[str] = None
    notes: Optional[str] = None
    is_primary: Optional[bool] = None
    clear: Optional[List[str]] = None


_LINK_CLEARABLE = ("unit_cost", "moq", "sku_at_supplier", "notes")


@router.patch("/links/{link_id}")
def update_link(link_id: str, body: LinkPatch,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    link = _link_or_404(link_id)
    _owner(str(link["business_id"]), user)

    given = body.model_dump(exclude_none=True)
    patch: Dict[str, Any] = {}
    for k in ("unit_cost", "moq", "is_primary"):
        if k in given:
            patch[k] = given[k]
    for k in ("sku_at_supplier", "notes"):
        if k in given:
            patch[k] = _clean(given[k])
    for k in (body.clear or []):
        if k in _LINK_CLEARABLE:
            patch[k] = None
    if not patch:
        return {"ok": True, "link": link}

    if patch.get("is_primary") is True:
        _clear_other_primaries(str(link["offering_id"]), link_id)

    patch["updated_at"] = _now_iso()
    sb_clients.sb_patch_as_service(f"/offering_suppliers?id=eq.{link_id}", patch)
    if "is_primary" in patch:
        _sync_offering_cache(str(link["offering_id"]))
    return {"ok": True, "link": _link_or_404(link_id)}


@router.delete("/links/{link_id}")
def delete_link(link_id: str,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    link = _link_or_404(link_id)
    _owner(str(link["business_id"]), user)
    sb_clients.sb_delete_as_service(f"/offering_suppliers?id=eq.{link_id}")
    _sync_offering_cache(str(link["offering_id"]))
    return {"ok": True, "deleted": link_id}


class LinkBody(BaseModel):
    offering_id: str
    unit_cost: Optional[float] = None
    moq: Optional[int] = None
    sku_at_supplier: Optional[str] = None
    notes: Optional[str] = None
    is_primary: bool = True


@router.post("/{supplier_id}/products")
def link_product(supplier_id: str, body: LinkBody,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Link a product to this vendor, or update the link if it exists.
    Primary by default: the common case is 'this is who I buy it from'."""
    sup = _supplier_or_404(supplier_id)
    biz = str(sup["business_id"])
    _owner(biz, user)

    offs = sb_clients.sb_get_as_service(
        f"/offerings?id=eq.{body.offering_id}&business_id=eq.{biz}"
        f"&select=id&limit=1") or []
    if not offs:
        raise HTTPException(404, "product not found")

    existing = sb_clients.sb_get_as_service(
        f"/offering_suppliers?offering_id=eq.{body.offering_id}"
        f"&supplier_id=eq.{supplier_id}&select=id&limit=1") or []

    fields = {
        "unit_cost": body.unit_cost,
        "moq": body.moq,
        "sku_at_supplier": _clean(body.sku_at_supplier),
        "notes": _clean(body.notes),
        "is_primary": bool(body.is_primary),
        "updated_at": _now_iso(),
    }

    if existing:
        link_id = str(existing[0]["id"])
        if fields["is_primary"]:
            _clear_other_primaries(body.offering_id, link_id)
        sb_clients.sb_patch_as_service(
            f"/offering_suppliers?id=eq.{link_id}", fields)
    else:
        # Demote the incumbent BEFORE inserting, or the partial unique
        # index rejects the insert instead of the practitioner's intent
        # winning.
        if fields["is_primary"]:
            sb_clients.sb_patch_as_service(
                f"/offering_suppliers?offering_id=eq.{body.offering_id}"
                f"&is_primary=is.true",
                {"is_primary": False, "updated_at": _now_iso()})
        created = sb_clients.sb_post_as_service("/offering_suppliers", {
            "business_id": biz,
            "offering_id": body.offering_id,
            "supplier_id": supplier_id,
            **fields,
        }) or []
        if not created:
            raise HTTPException(500, "could not link that product")
        link_id = str((created[0] if isinstance(created, list) else created)["id"])

    _sync_offering_cache(body.offering_id)
    return {"ok": True, "link": _link_or_404(link_id)}


@router.get("/for-offering/{offering_id}")
def suppliers_for_offering(offering_id: str,
                           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Everyone who quotes this product. The Stage-3 comparison reads
    this; the Stage-0 product row reads it to show who is primary."""
    links = sb_clients.sb_get_as_service(
        f"/offering_suppliers?offering_id=eq.{offering_id}"
        f"&select=*&order=is_primary.desc,unit_cost.asc.nullslast"
        f"&limit={_LIST_CAP}") or []
    if not links:
        return {"ok": True, "links": []}
    _reader(str(links[0]["business_id"]), user)
    ids = ",".join(str(l["supplier_id"]) for l in links)
    sups = sb_clients.sb_get_as_service(
        f"/suppliers?id=in.({ids})&select=*&limit={_LIST_CAP}") or []
    by_id = {str(s["id"]): s for s in sups}
    for l in links:
        l["supplier"] = by_id.get(str(l["supplier_id"]))
    return {"ok": True, "links": links}
