"""
contacts_router.py — practitioner-facing endpoints scoped to a single
contact.

Phase C.1 endpoints:
  GET /contacts/{contact_id}/related-entries?business_id=...
      Returns all module_entries with data.contact_id = contact_id grouped
      by module slug, so ContactDetail.tsx can render one collapsible
      section per module (C7 / C8 rulings).

  GET /contacts/{contact_id}/timeline?business_id=...&limit=&kinds=
      One dated record for the client — bookings, forms, invoices and
      payments, contracts, email and SMS, notes, time, balances, records —
      merged from every table that knows them (client_timeline.assemble;
      the same function Chief's contact_deep_dive reads). Owner-only: it
      carries message subjects and invoice totals.

Owner check mirrors the workflow_router / module_spec_router pattern:
  business.owner_id == auth.uid().
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from auth_supabase import AuthedUser, require_user
import sb_clients

logger = logging.getLogger("contacts_router")
router = APIRouter(prefix="/contacts", tags=["contacts"])


def _require_owner(business_id: str, user: AuthedUser) -> None:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1"
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")


@router.get("/{contact_id}/related-entries")
async def related_entries(
    contact_id: str,
    business_id: str = Query(..., description="scopes the lookup"),
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Group module_entries with data.contact_id == contact_id by their
    parent module. Used by ContactDetail to render per-module collapsible
    sections.

    Shape: { ok, modules: [
      { module: {id, slug, name, icon, archetype}, entries: [...] },
      ...
    ] }

    Sort: modules in custom_modules.sort_order, entries by created_at desc.
    Empty sections are omitted (no point showing 'Bookings (0)' if there
    are no bookings)."""
    _require_owner(business_id, user)

    # Active modules for the business — list once, dispatch by module_id.
    modules = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{business_id}"
        f"&is_active=eq.true&order=sort_order.asc,created_at.asc"
        f"&select=id,slug,name,icon,archetype,archetype_params"
    ) or []
    if not modules:
        return {"ok": True, "modules": []}

    # PostgREST: filter on data->>'contact_id'. Using cs (contains) over
    # data jsonb is the simplest reliable form.
    # Note: data is jsonb; PostgREST's `cs` operator does containment.
    # Filter: data=cs.{"contact_id":"<uuid>"}
    contains_filter = f'data=cs.{{"contact_id":"{contact_id}"}}'
    entries = sb_clients.sb_get_as_service(
        f"/module_entries?business_id=eq.{business_id}"
        f"&{contains_filter}&order=created_at.desc"
        f"&select=id,module_id,data,status,created_at,updated_at"
    ) or []

    # Bucket entries by module_id.
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for e in entries:
        buckets.setdefault(e["module_id"], []).append(e)

    out_modules: List[Dict[str, Any]] = []
    for m in modules:
        bucket = buckets.get(m["id"]) or []
        if not bucket:
            continue
        out_modules.append({
            "module": {
                "id": m["id"],
                "slug": m["slug"],
                "name": m["name"],
                "icon": m.get("icon") or "📋",
                "archetype": m.get("archetype") or "fallback_generic",
                "archetype_params": m.get("archetype_params") or {},
            },
            "entries": bucket,
        })

    return {"ok": True, "modules": out_modules}


@router.get("/{contact_id}/timeline")
async def timeline(
    contact_id: str,
    business_id: str = Query(..., description="scopes the lookup"),
    limit: int = Query(200, ge=1, le=500, description="entries, newest first"),
    kinds: Optional[str] = Query(None, description="comma-separated kinds to keep"),
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """The client's one record, newest first. See client_timeline for the
    entry shape and which tables feed it.

    Shape: { ok, contact, entries: [...], summary, sources: {table: count
    or null when that read was refused}, partial }.

    A refused read is reported in `sources` and `partial`, never rendered
    as an empty history — a quiet client and a broken read are different
    things and the practitioner must be able to tell them apart."""
    _require_owner(business_id, user)
    import client_timeline
    record = await client_timeline.assemble(
        business_id, contact_id, limit=limit,
        kinds=[k for k in (kinds or "").split(",") if k.strip()] or None,
    )
    if not record:
        raise HTTPException(status_code=404, detail="contact not found")
    return {
        "ok": True,
        "contact": record["contact"],
        "entries": record["entries"],
        "summary": record["summary"],
        "sources": record["sources"],
        "partial": record["partial"],
    }
