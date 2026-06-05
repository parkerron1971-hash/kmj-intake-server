"""
invoices_router.py — Phase D.4 PR 3.

Practitioner-facing invoice CRUD. Architecture choice: invoices live
as first-class rows in the `invoices` table (not module_entries
extension) because they're a different shape than appointment-style
entries (their own lifecycle, line items, Stripe-side ids, send/void/
mark-uncollectible actions).

Endpoints (all owner-gated):
  GET   /payments/invoices?biz=...&status=...     list with optional filter
  POST  /payments/invoices                        create (draft)
  GET   /payments/invoices/{id}                   single
  POST  /payments/invoices/{id}/send              create on Stripe + email
  POST  /payments/invoices/{id}/void              void
  POST  /payments/invoices/{id}/uncollectible     mark uncollectible

The Stripe Invoice creation flow:
  1. Create Stripe Customer if needed (cached on invoices.stripe_customer_id)
  2. For each line item: POST /v1/invoiceitems  (attaches to customer)
  3. POST /v1/invoices (collects all pending items + sets metadata)
  4. POST /v1/invoices/{id}/send  (emails the hosted-pay link)

USD only for v1. Multi-currency surfaced as a future arc.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("invoices_router")

router = APIRouter(prefix="/payments", tags=["payments"])

STRIPE_API_BASE = "https://api.stripe.com/v1"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)


def _secret_key() -> str:
    k = os.environ.get("STRIPE_SECRET_KEY") or ""
    if not k:
        raise HTTPException(503, "payments not configured")
    return k


def _require_owner_with_acct(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,owner_id,stripe_account_id,name&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    if not rows[0].get("stripe_account_id"):
        raise HTTPException(409, "stripe account not connected")
    return rows[0]


def _require_invoice_owner(invoice_id: str, user: AuthedUser) -> tuple:
    """Returns (invoice_row, business_row)."""
    inv_rows = sb_clients.sb_get_as_service(
        f"/invoices?id=eq.{invoice_id}&select=*&limit=1"
    ) or []
    if not inv_rows:
        raise HTTPException(404, "invoice not found")
    inv = inv_rows[0]
    biz = _require_owner_with_acct(inv["business_id"], user)
    return inv, biz


async def _stripe(method: str, path: str, *, acct: str, data: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.request(
            method, f"{STRIPE_API_BASE}{path}",
            auth=(_secret_key(), ""),
            headers={"Stripe-Account": acct},
            data=data,
        )
    if resp.status_code >= 400:
        logger.warning(f"stripe {method} {path} failed: {resp.status_code} {resp.text[:300]}")
        try:
            err = resp.json().get("error") or {}
            msg = err.get("message") or "stripe error"
        except Exception:
            msg = "stripe error"
        raise HTTPException(resp.status_code, msg)
    return resp.json()


# ─── Pydantic bodies ─────────────────────────────────────────────────


class InvoiceLineItem(BaseModel):
    description: str = Field(..., max_length=500)
    quantity: int = Field(1, ge=1)
    unit_amount_cents: int = Field(..., gt=0)


class InvoiceCreateBody(BaseModel):
    business_id: str
    customer_name: str
    customer_email: str
    line_items: List[InvoiceLineItem]
    description: Optional[str] = None
    due_date: Optional[str] = None   # YYYY-MM-DD


# ─── Endpoints ───────────────────────────────────────────────────────


@router.get("/invoices")
def list_invoices(
    biz: str,
    status: Optional[str] = None,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _require_owner_with_acct(biz, user)
    qs = f"/invoices?business_id=eq.{biz}&order=created_at.desc&select=*"
    if status:
        qs += f"&status=eq.{status}"
    rows = sb_clients.sb_get_as_service(qs) or []
    return {"ok": True, "data": rows}


@router.get("/invoices/{invoice_id}")
def get_invoice(
    invoice_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    inv, _ = _require_invoice_owner(invoice_id, user)
    return {"ok": True, "invoice": inv}


@router.post("/invoices")
def create_invoice(
    body: InvoiceCreateBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Create a draft invoice in Solutionist (Stripe-side creation
    happens on /send). Returns the new row."""
    _require_owner_with_acct(body.business_id, user)

    if not body.line_items:
        raise HTTPException(400, "at least one line item required")

    subtotal = sum(li.quantity * li.unit_amount_cents for li in body.line_items)

    created = sb_clients.sb_post_as_service("/invoices", {
        "business_id": body.business_id,
        "customer_name": body.customer_name.strip(),
        "customer_email": body.customer_email.strip().lower(),
        "description": (body.description or "").strip() or None,
        "line_items": [li.model_dump() for li in body.line_items],
        "currency": "usd",
        "subtotal_cents": subtotal,
        "total_cents": subtotal,
        "amount_due_cents": subtotal,
        "status": "draft",
        "due_date": body.due_date,
    })
    if not (isinstance(created, list) and created):
        raise HTTPException(500, "could not create invoice")
    return {"ok": True, "invoice": created[0]}


@router.post("/invoices/{invoice_id}/send")
async def send_invoice(
    invoice_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Create the invoice on Stripe + send. Idempotent on
    invoices.stripe_invoice_id — if already created, re-send only."""
    inv, biz = _require_invoice_owner(invoice_id, user)
    acct = biz["stripe_account_id"]

    if inv.get("status") not in ("draft", "open"):
        raise HTTPException(409, f"cannot send invoice in status {inv.get('status')}")

    # Step 1 — Stripe customer (cached on invoice).
    stripe_customer_id = inv.get("stripe_customer_id")
    if not stripe_customer_id:
        cust_resp = await _stripe("POST", "/customers", acct=acct, data={
            "email": inv.get("customer_email") or "",
            "name": inv.get("customer_name") or "",
        })
        stripe_customer_id = cust_resp.get("id")
        sb_clients.sb_patch_as_service(
            f"/invoices?id=eq.{invoice_id}",
            {"stripe_customer_id": stripe_customer_id},
        )

    # Step 2 — Stripe invoice (only if we haven't created one yet).
    stripe_invoice_id = inv.get("stripe_invoice_id")
    if not stripe_invoice_id:
        # 2a — attach invoiceitems
        for li in (inv.get("line_items") or []):
            await _stripe("POST", "/invoiceitems", acct=acct, data={
                "customer": stripe_customer_id,
                "amount": int(li["quantity"]) * int(li["unit_amount_cents"]),
                "currency": "usd",
                "description": li.get("description") or "",
            })
        # 2b — create the invoice
        inv_data: Dict[str, Any] = {
            "customer": stripe_customer_id,
            "collection_method": "send_invoice",
            "days_until_due": 14,    # honored when due_date isn't set
            "metadata[source_type]": "invoice",
            "metadata[source_id]": invoice_id,
        }
        if inv.get("description"):
            inv_data["description"] = inv["description"]
        if inv.get("due_date"):
            # Convert YYYY-MM-DD to unix seconds end-of-day UTC.
            from datetime import datetime, timezone
            try:
                dt = datetime.strptime(inv["due_date"], "%Y-%m-%d")
                dt = dt.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
                inv_data["due_date"] = int(dt.timestamp())
            except Exception:
                pass
        created = await _stripe("POST", "/invoices", acct=acct, data=inv_data)
        stripe_invoice_id = created.get("id")
        sb_clients.sb_patch_as_service(
            f"/invoices?id=eq.{invoice_id}",
            {
                "stripe_invoice_id": stripe_invoice_id,
                "hosted_invoice_url": created.get("hosted_invoice_url"),
                "pdf_url": created.get("invoice_pdf"),
            },
        )

    # Step 3 — send (emails the practitioner-facing customer the link)
    sent = await _stripe("POST", f"/invoices/{stripe_invoice_id}/send", acct=acct, data={})

    from datetime import datetime, timezone
    sb_clients.sb_patch_as_service(
        f"/invoices?id=eq.{invoice_id}",
        {
            "status": "open",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "hosted_invoice_url": sent.get("hosted_invoice_url"),
            "pdf_url": sent.get("invoice_pdf"),
        },
    )

    return {
        "ok": True,
        "stripe_invoice_id": stripe_invoice_id,
        "hosted_invoice_url": sent.get("hosted_invoice_url"),
    }


@router.post("/invoices/{invoice_id}/void")
async def void_invoice(
    invoice_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    inv, biz = _require_invoice_owner(invoice_id, user)
    if not inv.get("stripe_invoice_id"):
        # Draft-only — mark void locally; no Stripe round-trip.
        sb_clients.sb_patch_as_service(
            f"/invoices?id=eq.{invoice_id}",
            {"status": "void", "voided_at": _now_iso()},
        )
        return {"ok": True, "voided": True}
    await _stripe(
        "POST", f"/invoices/{inv['stripe_invoice_id']}/void",
        acct=biz["stripe_account_id"], data={},
    )
    sb_clients.sb_patch_as_service(
        f"/invoices?id=eq.{invoice_id}",
        {"status": "void", "voided_at": _now_iso()},
    )
    return {"ok": True, "voided": True}


@router.post("/invoices/{invoice_id}/uncollectible")
async def mark_uncollectible(
    invoice_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    inv, biz = _require_invoice_owner(invoice_id, user)
    if not inv.get("stripe_invoice_id"):
        raise HTTPException(409, "invoice not yet sent")
    await _stripe(
        "POST", f"/invoices/{inv['stripe_invoice_id']}/mark_uncollectible",
        acct=biz["stripe_account_id"], data={},
    )
    sb_clients.sb_patch_as_service(
        f"/invoices?id=eq.{invoice_id}",
        {"status": "uncollectible"},
    )
    return {"ok": True}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
