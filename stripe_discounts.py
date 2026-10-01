"""Stripe-backed coupon management. Stripe is the catalog and redemption ledger.

Platform promotions and each business's Connect promotions are separate catalogs.
No caller-supplied Stripe account or subscription ID is ever trusted.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import Literal, Optional
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

import sb_clients
from business_access import business_access
from financial_policy import require_stripe_write
from lead_admin import require_owner
from stripe_billing import HTTP_TIMEOUT, STRIPE_API_BASE, _flatten, _stripe_headers, _stripe_key

router = APIRouter(tags=["discounts"])


class StripeDiscountError(HTTPException):
    def __init__(self, status, error):
        self.param = error.get("param")
        self.code = error.get("code")
        super().__init__(status, error.get("message") or "Stripe could not complete this request.")


async def stripe_request(method, path, *, account=None, form=None, params=None, key=None):
    headers = _stripe_headers()
    if account:
        headers["Stripe-Account"] = account
        if method != "GET":
            require_stripe_write(account)
    if key:
        headers["Idempotency-Key"] = key
    flat = {}
    for k, v in (form or {}).items():
        _flatten(flat, k, v)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.request(
                method, STRIPE_API_BASE + path, auth=(_stripe_key(), ""),
                headers=headers, params=params, data=flat if method != "GET" else None,
            )
    except httpx.RequestError as exc:
        raise HTTPException(503, "Stripe is unavailable. Retry the same request.") from exc
    if response.status_code >= 400:
        try:
            error = response.json().get("error") or {}
        except ValueError:
            error = {}
        raise StripeDiscountError(400 if response.status_code < 500 else 502, error)
    return response.json()


def normalized_code(code):
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,63}", code):
        raise ValueError("Use 1–64 letters, numbers, or dashes for the code.")
    return code


class CreateDiscount(BaseModel):
    request_id: UUID
    code: str
    percent_off: Optional[float] = Field(default=None, gt=0, le=100, allow_inf_nan=False)
    amount_off: Optional[int] = Field(default=None, gt=0, le=99999999)
    currency: str = Field(default="usd", pattern=r"^[a-z]{3}$")
    duration: Literal["once", "forever", "repeating"] = "once"
    duration_in_months: Optional[int] = Field(default=None, ge=1, le=36)
    max_redemptions: Optional[int] = Field(default=None, ge=1, le=1000000)
    expires_at: Optional[int] = None

    @model_validator(mode="after")
    def validate_discount(self):
        self.code = normalized_code(self.code)
        if (self.percent_off is None) == (self.amount_off is None):
            raise ValueError("Choose a percentage or a fixed amount, not both.")
        if self.duration == "repeating" and not self.duration_in_months:
            raise ValueError("Set the number of months for a repeating discount.")
        if self.duration != "repeating" and self.duration_in_months is not None:
            raise ValueError("Months are only used for repeating discounts.")
        if self.expires_at is not None and self.expires_at <= int(time.time()):
            raise ValueError("Choose an expiration in the future.")
        return self


def _account(biz):
    import payments_core
    if payments_core.provider_for(biz).id != "stripe":
        raise HTTPException(409, "Coupons require Stripe as this business's payment provider.")
    account = biz.get("stripe_account_id")
    if not account:
        raise HTTPException(409, "Connect Stripe in Payments before creating coupons.")
    return account


async def _coupon(promo, account=None):
    coupon = (promo.get("promotion") or {}).get("coupon") or promo.get("coupon")
    if isinstance(coupon, str):
        try:
            coupon = await stripe_request("GET", "/coupons/" + quote(coupon, safe=""), account=account)
        except StripeDiscountError as exc:
            if exc.code != "resource_missing":
                raise
            # Deleted coupons must not prevent the rest of the catalog loading.
            coupon = {"id": coupon, "valid": False}
    return coupon or {}


async def _summary(promo, account=None):
    coupon = await _coupon(promo, account)
    return {**{k: promo.get(k) for k in (
        "id", "code", "active", "livemode", "times_redeemed", "max_redemptions", "expires_at")},
        "coupon": {k: coupon.get(k) for k in (
            "id", "valid", "percent_off", "amount_off", "currency", "duration", "duration_in_months")}}


async def list_discounts(account=None, after=None):
    params = {"limit": 50}
    if after:
        params["starting_after"] = after
    page = await stripe_request("GET", "/promotion_codes", account=account, params=params)
    semaphore = asyncio.Semaphore(8)
    async def summarize(promo):
        async with semaphore:
            return await _summary(promo, account)
    items = await asyncio.gather(*(summarize(p) for p in page.get("data", [])))
    return {"items": items, "has_more": bool(page.get("has_more")),
            "next_cursor": items[-1]["id"] if items and page.get("has_more") else None}


async def create_discount(body, account=None):
    if account and body.duration != "once":
        raise HTTPException(422, "Business checkout coupons apply once per purchase.")
    fingerprint = hashlib.sha256(json.dumps(body.model_dump(mode="json", exclude={"request_id"}),
                                           sort_keys=True).encode()).hexdigest()
    existing = await stripe_request("GET", "/promotion_codes", account=account,
                                    params={"code": body.code, "active": "true", "limit": 100})
    for promo in existing.get("data", []):
        md = promo.get("metadata") or {}
        if md.get("request_id") == str(body.request_id) and md.get("fingerprint") == fingerprint:
            return await _summary(promo, account)
        raise HTTPException(409, "An active code with that name already exists. Use it or choose another name.")
    key = "discount:" + str(body.request_id)
    coupon_form = {"name": body.code, "duration": body.duration,
                   "metadata": {"request_id": str(body.request_id), "fingerprint": fingerprint}}
    if body.percent_off is not None:
        coupon_form["percent_off"] = body.percent_off
    else:
        coupon_form.update(amount_off=body.amount_off, currency=body.currency)
    if body.duration == "repeating":
        coupon_form["duration_in_months"] = body.duration_in_months
    coupon = await stripe_request("POST", "/coupons", account=account,
                                  form=coupon_form, key=key + ":coupon")
    form = {"code": body.code, "promotion": {"type": "coupon", "coupon": coupon["id"]},
            "max_redemptions": body.max_redemptions, "expires_at": body.expires_at,
            "metadata": coupon_form["metadata"]}
    try:
        promo = await stripe_request("POST", "/promotion_codes", account=account, form=form, key=key + ":promo")
    except StripeDiscountError as exc:
        # Compatibility only for pre-Clover accounts. Never retry validation or auth failures.
        if exc.code != "parameter_unknown" or exc.param != "promotion":
            raise
        form.pop("promotion")
        form["coupon"] = coupon["id"]
        promo = await stripe_request("POST", "/promotion_codes", account=account, form=form, key=key + ":legacy")
    return await _summary(promo, account)


async def resolve_code(code, account=None):
    try:
        code = normalized_code(code)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    page = await stripe_request("GET", "/promotion_codes", account=account,
                                params={"code": code, "active": "true", "limit": 100})
    promos = page.get("data") or []
    if len(promos) != 1:
        raise HTTPException(409, "That code is unavailable or customer-specific. Use a unique unrestricted code.")
    promo = promos[0]
    if (promo.get("expires_at") and promo["expires_at"] <= time.time()) or (
        promo.get("max_redemptions") and promo.get("times_redeemed", 0) >= promo["max_redemptions"]):
        raise HTTPException(409, "That code has expired or reached its usage limit.")
    if not (await _coupon(promo, account)).get("valid", False):
        raise HTTPException(409, "That coupon is no longer valid.")
    return promo


@router.get("/billing/discounts", dependencies=[Depends(require_owner)])
async def platform_discounts(after: Optional[str] = Query(default=None, max_length=100)):
    return await list_discounts(after=after)


@router.post("/billing/discounts", dependencies=[Depends(require_owner)])
async def platform_create_discount(body: CreateDiscount):
    return await create_discount(body)


@router.post("/billing/discounts/{promo_id}/deactivate", dependencies=[Depends(require_owner)])
async def platform_deactivate(promo_id: str):
    promo = await stripe_request("POST", "/promotion_codes/" + quote(promo_id, safe=""), form={"active": False})
    return await _summary(promo)


@router.get("/payments/{business_id}/discounts")
async def business_discounts(after: Optional[str] = Query(default=None, max_length=100),
                             biz: dict = Depends(business_access("owner"))):
    return await list_discounts(_account(biz), after)


@router.post("/payments/{business_id}/discounts")
async def business_create_discount(body: CreateDiscount, biz: dict = Depends(business_access("owner"))):
    return await create_discount(body, _account(biz))


@router.post("/payments/{business_id}/discounts/{promo_id}/deactivate")
async def business_deactivate(promo_id: str, biz: dict = Depends(business_access("owner"))):
    account = _account(biz)
    promo = await stripe_request("POST", "/promotion_codes/" + quote(promo_id, safe=""),
                                 account=account, form={"active": False})
    return await _summary(promo, account)


@router.get("/billing/discount-targets", dependencies=[Depends(require_owner)])
async def discount_targets():
    rows = sb_clients.sb_get_as_service(
        "/businesses?stripe_subscription_id=not.is.null&select=id,name,subscription_status&order=name&limit=1000")
    if not isinstance(rows, list):
        raise HTTPException(503, "Could not load subscriptions.")
    return {"items": [r for r in rows if r.get("subscription_status") in ("active", "trialing", "past_due")]}


class ApplyDiscount(BaseModel):
    business_id: UUID
    code: str = Field(min_length=1, max_length=64)
    request_id: UUID


@router.post("/billing/apply-discount")
async def apply_discount(body: ApplyDiscount, _owner=Depends(require_owner)):
    from stripe_billing import _load_business
    biz = await _load_business(str(body.business_id))
    sub_id = biz.get("stripe_subscription_id")
    if not sub_id:
        raise HTTPException(409, "This business has no subscription. Enter the code at signup checkout instead.")
    sub = await stripe_request("GET", "/subscriptions/" + quote(sub_id, safe=""))
    customer = sub.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    if not customer or customer != biz.get("stripe_customer_id"):
        raise HTTPException(409, "The subscription and business customer do not match.")
    if sub.get("status") not in ("active", "trialing", "past_due"):
        raise HTTPException(409, "This subscription cannot receive a discount.")
    # An application retry is safe even after a once-only coupon has been redeemed.
    if (sub.get("metadata") or {}).get("discount_request_id") == str(body.request_id):
        if (sub.get("metadata") or {}).get("discount_code") != normalized_code(body.code):
            raise HTTPException(409, "This request was already used for another code.")
        return {"ok": True, "subscription_id": sub_id, "code": (sub.get("metadata") or {}).get("discount_code")}
    if sub.get("discounts") or sub.get("discount"):
        raise HTTPException(409, "This subscription already has a discount. Manage that discount in Stripe before applying another.")
    promo = await resolve_code(body.code)
    if promo.get("customer") and promo["customer"] != customer:
        raise HTTPException(409, "That code belongs to another customer.")
    await stripe_request("POST", "/subscriptions/" + quote(sub_id, safe=""), key="apply-discount:" + str(body.request_id),
                         form={"discounts": [{"promotion_code": promo["id"]}], "proration_behavior": "none",
                               "metadata": {"discount_request_id": str(body.request_id), "discount_code": promo["code"]}})
    return {"ok": True, "subscription_id": sub_id, "code": promo["code"]}
