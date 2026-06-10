"""
contractors_router.py — Phase F.1 v1 — Stripe outbound contractor payments.

Contractors are standalone (ruled — not contacts). Each contractor gets a
Stripe EXPRESS account (Stripe owns identity + W-9 + 1099-NEC delivery via
Tax Reporting). v1 funding model: transfers are sent from the PLATFORM
Stripe balance to the contractor's Express account — correct for current
production (LLC-consolidation ruling: the platform account is the money
home). The multi-practitioner funding model (destination charges / account
debits) is a surfaced fork for a future ruling.

Every paid transfer auto-creates a PAID AP bill (is_1099_eligible=true,
contractor linked, paid_via='stripe_transfer'), so the GL books
Dr Expense / Cr AP + Dr AP / Cr Cash through the existing bills→GL pipeline
(the bills INSERT enqueue-trigger picks it up live), and the 1099 Summary
aggregates from bills as the single source of truth.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("contractors_router")

router = APIRouter(prefix="/contractors", tags=["contractors"])

STRIPE_API_BASE = "https://api.stripe.com/v1"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)
_APP_BASE = "https://app.solutionist.studio"

_BUCKETS = ("tax", "owner_pay", "operating", "savings", "other")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _secret_key() -> str:
    key = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
    if not key:
        raise HTTPException(503, "Stripe is not configured (STRIPE_SECRET_KEY missing).")
    return key


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _owner_for_contractor(contractor_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/contractors?id=eq.{contractor_id}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "contractor not found")
    _owner(str(rows[0]["business_id"]), user)
    return rows[0]


async def _stripe_post(path: str, data: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(f"{STRIPE_API_BASE}{path}", auth=(_secret_key(), ""), data=data)
    body = r.json() if r.content else {}
    if r.status_code >= 400:
        msg = ((body.get("error") or {}).get("message")) or f"stripe {path} failed ({r.status_code})"
        logger.warning(f"[f1] stripe POST {path} -> {r.status_code}: {msg}")
        raise HTTPException(502, msg)
    return body


async def _stripe_get(path: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(f"{STRIPE_API_BASE}{path}", auth=(_secret_key(), ""))
    body = r.json() if r.content else {}
    if r.status_code >= 400:
        msg = ((body.get("error") or {}).get("message")) or f"stripe {path} failed ({r.status_code})"
        raise HTTPException(502, msg)
    return body


# ─── CRUD + onboarding ───────────────────────────────────────────────

@router.get("")
def list_contractors(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/contractors?business_id=eq.{biz}&order=created_at.desc&select=*&limit=500") or []
    return {"ok": True, "contractors": rows}


class ContractorBody(BaseModel):
    business_id: str
    name: str
    email: Optional[str] = None
    default_category: str = "operating"
    is_1099_eligible: bool = True
    notes: Optional[str] = None


@router.post("")
def create_contractor(body: ContractorBody,
                      user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(body.business_id, user)
    if not (body.name or "").strip():
        raise HTTPException(400, "name is required")
    if body.default_category not in _BUCKETS:
        raise HTTPException(400, f"default_category must be one of {_BUCKETS}")
    res = sb_clients.sb_post_as_service("/contractors", {
        "business_id": body.business_id, "name": body.name.strip(),
        "email": (body.email or "").strip().lower() or None,
        "default_category": body.default_category,
        "is_1099_eligible": body.is_1099_eligible, "notes": body.notes,
        "onboarding_status": "invited",
    })
    row = (res or [None])[0] if isinstance(res, list) else res
    return {"ok": True, "contractor": row}


class ContractorPatchBody(BaseModel):
    business_id: str
    name: Optional[str] = None
    email: Optional[str] = None
    default_category: Optional[str] = None
    is_1099_eligible: Optional[bool] = None
    notes: Optional[str] = None


@router.patch("/{contractor_id}")
def update_contractor(contractor_id: str, body: ContractorPatchBody,
                      user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner_for_contractor(contractor_id, user)
    patch: Dict[str, Any] = {"updated_at": _now_iso()}
    for f in ("name", "email", "is_1099_eligible", "notes"):
        v = getattr(body, f)
        if v is not None:
            patch[f] = v
    if body.default_category is not None:
        if body.default_category not in _BUCKETS:
            raise HTTPException(400, f"default_category must be one of {_BUCKETS}")
        patch["default_category"] = body.default_category
    sb_clients.sb_patch_as_service(
        f"/contractors?id=eq.{contractor_id}&business_id=eq.{body.business_id}", patch)
    return {"ok": True}


@router.post("/{contractor_id}/onboarding-link")
async def onboarding_link(contractor_id: str,
                          user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Create the Express account (once) + a fresh onboarding link. Emails
    the link when possible; always returns it so the practitioner can share
    it manually (collaborators pattern)."""
    c = _owner_for_contractor(contractor_id, user)
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{c['business_id']}&select=name&limit=1") or [{}]
    biz_name = biz_rows[0].get("name") or "the business"

    acct_id = c.get("stripe_account_id")
    if not acct_id:
        acct = await _stripe_post("/accounts", {
            "type": "express",
            "email": c.get("email") or "",
            "capabilities[transfers][requested]": "true",
            "metadata[business_id]": str(c["business_id"]),
            "metadata[contractor_id]": str(contractor_id),
            "metadata[source]": "solutionist_f1",
        })
        acct_id = acct["id"]
        sb_clients.sb_patch_as_service(
            f"/contractors?id=eq.{contractor_id}",
            {"stripe_account_id": acct_id, "onboarding_status": "pending",
             "updated_at": _now_iso()})

    link = await _stripe_post("/account_links", {
        "account": acct_id,
        "refresh_url": f"{_APP_BASE}?contractor_onboarding=refresh",
        "return_url": f"{_APP_BASE}?contractor_onboarding=done",
        "type": "account_onboarding",
    })
    url = link.get("url")

    email_sent = False
    if c.get("email"):
        try:
            from email_sender import send_via_resend
            await send_via_resend(
                to_email=c["email"], to_name=c.get("name"),
                from_email="payments@solutionist.studio", from_name="Solutionist System",
                reply_to=None,
                subject=f"{biz_name} wants to pay you — set up your payout account",
                body=(f"{biz_name} uses Solutionist System to send contractor payments.\n\n"
                      f"Set up your secure payout account with Stripe (takes ~5 minutes):\n"
                      f"{url}\n\nStripe handles your identity, W-9, and 1099 delivery. "
                      f"This link expires after a few days — ask {biz_name} for a fresh "
                      f"one if needed."))
            email_sent = True
        except Exception as e:
            logger.warning(f"[f1] onboarding email not sent: {e}")

    return {"ok": True, "onboarding_url": url, "stripe_account_id": acct_id,
            "email_sent": email_sent}


@router.post("/{contractor_id}/refresh-status")
async def refresh_status(contractor_id: str,
                         user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    c = _owner_for_contractor(contractor_id, user)
    acct_id = c.get("stripe_account_id")
    if not acct_id:
        return {"ok": True, "onboarding_status": c.get("onboarding_status")}
    acct = await _stripe_get(f"/accounts/{acct_id}")
    if acct.get("payouts_enabled"):
        status = "active"
    elif acct.get("details_submitted"):
        status = "restricted" if (acct.get("requirements") or {}).get("currently_due") else "active"
    else:
        status = "pending"
    patch: Dict[str, Any] = {"onboarding_status": status, "updated_at": _now_iso()}
    if status == "active" and not c.get("onboarded_at"):
        patch["onboarded_at"] = _now_iso()
    sb_clients.sb_patch_as_service(f"/contractors?id=eq.{contractor_id}", patch)
    return {"ok": True, "onboarding_status": status,
            "payouts_enabled": bool(acct.get("payouts_enabled"))}


# ─── Pay ─────────────────────────────────────────────────────────────

class PayBody(BaseModel):
    business_id: str
    amount: float
    description: Optional[str] = None
    category: Optional[str] = None      # defaults to the contractor's default


@router.post("/{contractor_id}/pay")
async def pay(contractor_id: str, body: PayBody,
              user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Send a Stripe Transfer (platform balance → contractor Express) and
    record it: outbound_transfers row + auto-created PAID AP bill
    (is_1099_eligible per contractor) → GL books it via the bills pipeline."""
    c = _owner_for_contractor(contractor_id, user)
    if str(c["business_id"]) != body.business_id:
        raise HTTPException(403, "contractor belongs to a different business")
    if body.amount <= 0:
        raise HTTPException(400, "amount must be positive")
    if c.get("onboarding_status") != "active" or not c.get("stripe_account_id"):
        raise HTTPException(409, "contractor hasn't finished payout onboarding yet")
    category = body.category or c.get("default_category") or "operating"
    if category not in _BUCKETS:
        raise HTTPException(400, f"category must be one of {_BUCKETS}")

    # Record first (status 'created') so a Stripe success is never lost.
    res = sb_clients.sb_post_as_service("/outbound_transfers", {
        "business_id": body.business_id, "contractor_id": contractor_id,
        "amount": round(body.amount, 2), "currency": "USD", "status": "created",
        "description": body.description,
    })
    ot = (res or [None])[0] if isinstance(res, list) else res
    if not ot:
        raise HTTPException(500, "failed to record transfer")

    try:
        transfer = await _stripe_post("/transfers", {
            "amount": int(round(body.amount * 100)),
            "currency": "usd",
            "destination": c["stripe_account_id"],
            "description": (body.description or f"Payment to {c.get('name')}")[:200],
            "metadata[business_id]": body.business_id,
            "metadata[contractor_id]": contractor_id,
            "metadata[source_type]": "contractor_payment",
            "metadata[source_id]": ot["id"],
        })
    except HTTPException as e:
        sb_clients.sb_patch_as_service(
            f"/outbound_transfers?id=eq.{ot['id']}",
            {"status": "failed", "failed_at": _now_iso(),
             "failure_message": str(e.detail)[:500]})
        raise

    # Auto-create the PAID AP bill (F15/F5) — the bills INSERT trigger
    # enqueues it and the GL converges (Dr Expense/Cr AP + Dr AP/Cr Cash).
    bill_res = sb_clients.sb_post_as_service("/bills", {
        "business_id": body.business_id, "vendor_name": c.get("name"),
        "description": body.description or f"Contractor payment ({transfer.get('id')})",
        "amount": round(body.amount, 2), "category": category,
        "subcategory": "contractor", "status": "paid",
        "due_date": _now_iso()[:10], "paid_at": _now_iso(),
        "paid_amount": round(body.amount, 2), "paid_via": "stripe_transfer",
        "is_1099_eligible": bool(c.get("is_1099_eligible", True)),
        "contractor_id": contractor_id, "recurrence_index": 0,
    })
    bill = (bill_res or [None])[0] if isinstance(bill_res, list) else bill_res

    sb_clients.sb_patch_as_service(
        f"/outbound_transfers?id=eq.{ot['id']}",
        {"status": "paid", "paid_at": _now_iso(),
         "stripe_transfer_id": transfer.get("id"),
         "bill_id": (bill or {}).get("id")})

    return {"ok": True, "transfer_id": transfer.get("id"),
            "outbound_transfer_id": ot["id"], "bill_id": (bill or {}).get("id"),
            "amount": round(body.amount, 2)}


@router.get("/transfers")
def list_transfers(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/outbound_transfers?business_id=eq.{biz}"
        f"&order=created_at.desc&select=*,contractors(name)&limit=500") or []
    return {"ok": True, "transfers": rows}
