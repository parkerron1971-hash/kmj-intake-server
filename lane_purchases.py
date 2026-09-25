"""Private pilot purchases. Only the authenticated wallet UI can start checkout."""
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

import lane_mcp as mcp
import lane_store as store
import lane_merchant as merchant
from decimal import Decimal, InvalidOperation
from lane_wallet import router, owner, eligible, NO_STORE
import sb_clients
from auth_supabase import UserSession
from ledger_unlock import require_unlock, SCOPE_DANGER

OPAQUE = re.compile(r"[A-Za-z0-9_-]{1,160}")


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    prompt: str = Field(min_length=5, max_length=4000)
    merchant_url: str = Field(min_length=8, max_length=2048)
    max_amount_cents: int = Field(strict=True, ge=1, le=100000000)
    account: str = Field(min_length=1, max_length=200)
    merchant_name: str | None = Field(default=None, min_length=1, max_length=253)


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)


class Answer(Revision):
    answer: str = Field(min_length=1, max_length=2000)


def configured():
    if os.getenv("LANE_PURCHASES_ENABLED") != "true":
        return False
    try:
        store.cipher()
        return True
    except mcp.LaneError:
        return False


def checkout_enabled():
    return configured() and os.getenv("LANE_CHECKOUT_ENABLED") == "true"


def credentials(bid, uid):
    key = os.getenv("LANE_PILOT_API_KEY")
    if not eligible(bid, uid) or not configured() or not mcp.valid_key(key):
        raise mcp.LaneError("Lane purchases are not enabled for this account.")
    return key


def text(value, limit=4000):
    if not isinstance(value, str) or not 1 <= len(value) <= limit:
        raise mcp.LaneError("Lane returned incomplete purchase details. Open Lane to review.")
    return value


def identifier(value):
    value = text(value, 160)
    if not OPAQUE.fullmatch(value):
        raise mcp.LaneError("Lane returned an invalid purchase identifier.")
    return value


def safe_url(value, kind="approval"):
    value = text(value, 2048)
    u = urlsplit(value)
    path = r"/approve/[A-Za-z0-9_-]+" if kind == "approval" else r"/(?:asks/[A-Za-z0-9_-]+|home)"
    if (u.scheme != "https" or u.netloc != "wallet.getonlane.com" or u.fragment
            or re.search(r"[\\\s\x00-\x1f]", value) or not re.fullmatch(path, u.path)
            or (kind == "approval" and u.query)):
        raise mcp.LaneError("Lane returned an unexpected verification address.")
    return value


def snapshot(state):
    # No raw provider responses, tokens, card fields, logs, or stored key fingerprint.
    allowed = ("id", "revision", "phase", "request", "approval_url", "questions",
               "mandates", "ask_url", "ask_prompt", "order_number", "amount_charged",
               "message", "checkout_claimed", "purchase_details", "merchant_evidence")
    return {k: state[k] for k in allowed if k in state}


def view(p):
    return snapshot(dict(p.state, id=p.args["p_id"], revision=p.revision, checkout_claimed=p.claimed))


def expect(p, revision):
    if p.revision != revision:
        raise mcp.LaneError("This purchase changed. Refresh it before taking action.")


def accept_draft(p, data):
    # Journal known identifiers before parsing optional provider fields. A schema
    # mismatch must not lose the only safe way to reconcile an existing draft.
    for field in ("session_id", "draft_session_id"):
        if data.get(field):
            p.state[field] = identifier(data[field])
    payload = data.get("draft")
    intent = payload.get("intent_id") if isinstance(payload, dict) else None
    if intent:
        intent = identifier(intent)
        if p.state.get("intent_id") not in (None, intent):
            raise mcp.LaneError("Lane changed the purchase identity. Review it in Lane.")
        p.state["intent_id"] = intent
    p.save()
    try:
        _accept_draft(p, data)
    except (mcp.LaneError, AttributeError, TypeError, ValueError) as exc:
        message = str(exc) if isinstance(exc, mcp.LaneError) else "Lane returned unsupported purchase details. Review or decline the request in Lane."
        p.state.update(phase="attention", message=message)
        p.state.pop("approval_url", None)
        p.save()


def _accept_draft(p, data):
    kind = data.get("kind")
    if kind == "needs_info":
        questions = data.get("questions")
        if not isinstance(questions, list) or not 1 <= len(questions) <= 10:
            raise mcp.LaneError("Lane needs more information. Review the request in Lane.")
        normalized = []
        for q in questions:
            if not isinstance(q, dict):
                raise mcp.LaneError("Lane returned an unsupported question.")
            suggestions = q.get("suggestions", [])
            if not isinstance(suggestions, list) or len(suggestions) > 20:
                raise mcp.LaneError("Lane returned unsupported choices.")
            normalized.append({"prompt": text(q.get("prompt") or q.get("question")),
                               "suggestions": [text(s, 500) for s in suggestions]})
        p.state.update(phase="needs_info", session_id=identifier(data.get("session_id")), questions=normalized)
        p.state.pop("approval_url", None)
    elif kind == "draft_ready":
        draft = data.get("draft") or {}
        if not isinstance(draft, dict) or draft.get("currency", "USD") != "USD":
            raise mcp.LaneError("Lane returned an unsupported purchase currency or draft. Checkout is blocked.")
        mandates = draft.get("mandates")
        if not isinstance(mandates, list) or not 1 <= len(mandates) <= 10:
            raise mcp.LaneError("Lane returned an incomplete merchant list.")
        normalized = []
        for m in mandates:
            if not isinstance(m, dict) or m.get("currency", "USD") != "USD":
                raise mcp.LaneError("Lane returned an unsupported merchant or currency. Checkout is blocked.")
            amount = m.get("max_amount_cents")
            if type(amount) is not int or not 0 < amount <= 100000000:
                raise mcp.LaneError("Lane did not return a valid purchase ceiling.")
            normalized.append({"mandate_id": identifier(m.get("mandate_id")),
                               "merchant": text(m.get("merchant"), 253),
                               "summary": text(m.get("summary")),
                               "max_amount_cents": amount})
        details = p.state.get("purchase_details")
        if not details or sum(m["max_amount_cents"] for m in normalized) > details["max_amount_cents"]:
            raise mcp.LaneError("Lane's proposed ceiling exceeds your maximum total. Do not approve it. Review or decline it in Lane.")
        if len(normalized) != 1 or not merchant.matches_merchant(normalized[0]["merchant"], details):
            raise mcp.LaneError("Lane's merchant does not match the saved merchant page. Review or decline the request in Lane.")
        intent = identifier(draft.get("intent_id"))
        if p.state.get("intent_id") not in (None, intent):
            raise mcp.LaneError("Lane changed the purchase identity. Review it in Lane.")
        p.state.update(phase="review", session_id=identifier(data.get("session_id")),
                       intent_id=intent, approval_url=safe_url(data.get("approval_url")),
                       mandates=normalized)
        p.state.pop("questions", None)
    else:
        # A surprising 'complete' is not a substitute for this application's review.
        raise mcp.LaneError("Lane could not prepare a new request for review. Check your Lane wallet.")
    p.save()


def draft(bid, uid, request_id, prompt, merchant_url=None, max_amount_cents=None, account=None, merchant_name=None):
    key = credentials(bid, uid)
    details = merchant.details(merchant_url, max_amount_cents, account, merchant_name)
    p = store.Purchase(bid, uid, key, str(request_id))
    p.create(prompt, details)
    with p:
        if p.state.get("merchant_evidence") or p.state["phase"] != "new":
            return view(p)
        p.state["merchant_evidence"] = merchant.inspect(details["merchant_url"])
        p.state["message"] = "Review the merchant page, intended account and maximum total. No request has been sent to Lane."
        p.save()
        return view(p)


def prepare(bid, uid, purchase_id, revision):
    key = credentials(bid, uid)
    with store.Purchase(bid, uid, key, purchase_id) as p:
        expect(p, revision)
        if p.state["phase"] != "new" or not p.state.get("purchase_details"):
            raise mcp.LaneError("This request was already submitted or needs a new merchant review.")
        details = p.state["purchase_details"]
        p.state.update(phase="submitting", merchant_reviewed_at=datetime.now(timezone.utc).isoformat(),
                       message="Preparing the reviewed request in Lane.")
        p.save()
        # Preserve the user's words. Structured constraints are separate context.
        context = ("Owner-reviewed purchase constraints: merchant " + details["merchant_name"] + "; merchant page " + details["merchant_url"]
                   + "; maximum total including all taxes and fees USD " + format(Decimal(details["max_amount_cents"]) / 100, ".2f")
                   + "; intended account: " + details["account"]
                   + ". One-time purchase only. No auto-reload or subscription. Stop if the final total exceeds this limit.")
        accept_draft(p, mcp.call(key, "intent_submit", {"prompt": p.state["request"],
                     "conversation_context": context, "external_ref": p.args["p_id"]}))
        return view(p)


def close_proposal(bid, uid, purchase_id, revision):
    key = credentials(bid, uid)
    with store.Purchase(bid, uid, key, purchase_id) as p:
        expect(p, revision)
        if p.state["phase"] != "new" or p.claimed:
            raise mcp.LaneError("Only an unsent proposal can be dismissed here. Review submitted requests in Lane.")
        p.state.update(phase="closed", message="Proposal dismissed before submission to Lane.")
        p.save()
        return view(p)


def verify_approved_limits(p, key):
    details = p.state.get("purchase_details")
    if not details or not p.state.get("merchant_reviewed_at"):
        raise mcp.LaneError("This request needs a merchant and budget review before checkout.")
    data = mcp.call(key, "intent_list", {"status": "all", "limit": 100})
    rows = data.get("intents")
    if not isinstance(rows, list):
        raise mcp.LaneError("Lane did not provide verifiable approved spending limits.")
    matches = [r for r in rows if isinstance(r, dict) and r.get("id", r.get("intent_id")) == p.state["intent_id"]]
    if len(matches) != 1:
        raise mcp.LaneError("Lane's approved purchase could not be matched. Checkout remains blocked.")
    row = matches[0]
    try:
        amount = Decimal(str(row["amount"])) * 100 if "amount" in row else Decimal(str(row["amount_cents"]))
        if not amount.is_finite() or amount != amount.to_integral_value() or not 0 < amount <= details["max_amount_cents"]:
            raise ValueError()
        if row.get("currency") != details["currency"]:
            raise ValueError()
        names = row.get("merchants")
        if not isinstance(names, list) or len(names) != 1 or not isinstance(names[0], str):
            raise ValueError()
        if not merchant.matches_merchant(names[0], details):
            raise ValueError()
    except (KeyError, InvalidOperation, ValueError, mcp.LaneError):
        raise mcp.LaneError("Lane's current merchant, currency or ceiling does not match your reviewed request. Checkout is blocked.") from None


def approval(p, key):
    data = mcp.call(key, "intent_get_status", {"session_id": p.state["session_id"]})
    if data.get("kind") == "complete":
        if identifier(data.get("lane_intent_id")) != p.state["intent_id"]:
            raise mcp.LaneError("Lane approval did not match this purchase.")
        p.state["phase"] = "approved"
        p.state["message"] = "Approved in Lane. No order has been placed."
    elif data.get("kind") == "rejected":
        p.state["phase"] = "rejected"
    elif data.get("kind") == "draft_ready":
        accept_draft(p, data)
        return
    else:
        raise mcp.LaneError("Lane approval is not ready. Review the request in Lane.")
    p.save()


def order_status(p, key):
    data = mcp.call(key, "get_session_status", {"intent_id": p.state["intent_id"], "wait_seconds": 0})
    if data.get("intent_id") not in (None, p.state["intent_id"]):
        raise mcp.LaneError("Lane returned a different purchase.")
    outcome = data.get("outcome")
    p.state.pop("ask_url", None)
    p.state.pop("ask_prompt", None)
    if outcome == "ok":
        receipt = data.get("data") or {}
        # 'ok' alone is insufficient for the UI's placed claim.
        p.state.update(phase="placed", order_number=text(receipt.get("order_number"), 200),
                       amount_charged=text(receipt.get("amount_charged"), 80),
                       message="Lane confirmed the order was placed.")
    elif outcome == "running":
        p.state.update(phase="running", message="Lane is working on the checkout.")
    elif outcome == "needs_human":
        ask = data.get("suspend") or {}
        p.state.update(phase="needs_human", ask_url=safe_url(ask.get("ask_url"), "ask"),
                       ask_prompt=text(ask.get("prompt")),
                       message="Answer securely in Lane, then check the purchase status.")
    else:
        # Never reset the execution claim, even for busy/not-found/failed/crashed.
        p.state.update(phase="checkout_unknown",
                       message="Checkout needs review. Check Lane and the merchant before any new purchase; a charge may have occurred.")
    p.save()


def refresh(bid, uid, purchase_id):
    key = credentials(bid, uid)
    with store.Purchase(bid, uid, key, purchase_id) as p:
        if p.claimed:
            if p.state["phase"] != "placed":
                order_status(p, key)
        elif p.state["phase"] in {"review", "approved", "resolving", "products_needed"}:
            approval(p, key)
        elif p.state["phase"] in {"submitting", "attention"}:
            # No known provider response: resubmission could create duplicate approvals.
            if p.state.get("session_id"):
                data = mcp.call(key, "intent_get_status", {"session_id": p.state["session_id"]})
                if data.get("kind") == "rejected":
                    p.state.update(phase="rejected", message="Declined in Lane.")
                    p.save()
                elif data.get("kind") in {"draft_ready", "needs_info"}:
                    accept_draft(p, data)
                else:
                    p.state["message"] = "This draft needs review in Lane. Checkout remains blocked."
                    p.save()
            else:
                p.state["message"] = "Draft outcome unknown. Inspect your Lane wallet before making another request."
        return view(p)


def answer(bid, uid, purchase_id, body):
    key = credentials(bid, uid)
    with store.Purchase(bid, uid, key, purchase_id) as p:
        expect(p, body.revision)
        if p.claimed or p.state["phase"] != "needs_info":
            raise mcp.LaneError("This purchase is not waiting for a draft answer.")
        session_id = p.state["session_id"]
        p.state["phase"] = "submitting"
        p.save()
        accept_draft(p, mcp.call(key, "intent_submit", {"session_id": session_id, "prompt": body.answer}))
        return view(p)


def checkout(bid, uid, purchase_id, revision):
    key = credentials(bid, uid)
    if not checkout_enabled():
        raise mcp.LaneError("Live checkout is disabled until the private pilot is activated.")
    with store.Purchase(bid, uid, key, purchase_id) as p:
        expect(p, revision)
        if p.claimed:
            return view(p)  # Permanently prohibits another start_session for this purchase.
        if p.state["phase"] not in {"approved", "products_needed", "resolving"}:
            raise mcp.LaneError("Review and approve this purchase in Lane first.")
        approval(p, key)  # Revalidate with provider immediately before checkout.
        if p.state["phase"] != "approved":
            raise mcp.LaneError("The Lane approval is no longer active.")
        verify_approved_limits(p, key)
        p.state["phase"] = "resolving"
        p.save()
        for mandate in p.state["mandates"]:
            result = mcp.call(key, "find_products", {"mandate_id": mandate["mandate_id"]})
            if result.get("outcome") != "ok" or not result.get("products") or result.get("unresolved"):
                p.state.update(phase="products_needed",
                               message="Lane could not resolve every product. Review product links in Lane before continuing.")
                p.save()
                return view(p)
            products = result.get("products")
            target = p.state["purchase_details"]["merchant_url"]
            if not isinstance(products, list) or any(
                    not isinstance(item, dict) or merchant.merchant_url(item.get("url")) != target
                    for item in products):
                p.state.update(phase="products_needed",
                               message="Lane resolved a different product page. Checkout is blocked; review the product in Lane.")
                p.save()
                return view(p)
            p.save()  # Renew the lease between separately bounded product resolutions.
        p.state.update(phase="checkout_unknown", consent={"user_id": uid,
                       "at": datetime.now(timezone.utc).isoformat(), "revision": revision})
        p.save(claim=True)  # Permanent, atomic, cross-worker claim BEFORE the spending call.
        try:
            mcp.call(key, "start_session", {"intent_id": p.state["intent_id"],
                                          "dry_run": False, "success_on_place_order": False})
            order_status(p, key)  # Poll immediately; no 'approved == bought' confusion.
        except mcp.LaneError:
            p.state["message"] = "Checkout outcome unknown. Check status; do not repeat this purchase."
            p.save()
        return view(p)


@contextmanager
def guarded(response):
    response.headers.update(NO_STORE)
    try:
        yield
    except mcp.LaneError as exc:
        raise HTTPException(409, str(exc), headers=NO_STORE) from None
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), **NO_STORE}
        raise
    except Exception:
        raise HTTPException(503, "Lane purchase storage is unavailable. Refresh before trying again.",
                            headers=NO_STORE) from None


@router.get("/{business_id}/purchases")
def purchases(business_id: str, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    with guarded(response):
        bid, uid = owner(business_id, session)
        key = credentials(bid, uid)
        return {"purchases": [snapshot(r) for r in store.listing(bid, uid, key)],
                "checkout_enabled": checkout_enabled()}


@router.post("/{business_id}/purchases")
def create(business_id: str, body: Draft, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    with guarded(response):
        bid, uid = owner(business_id, session)
        return draft(bid, uid, body.request_id, body.prompt, body.merchant_url, body.max_amount_cents, body.account, body.merchant_name)


@router.post("/{business_id}/purchases/{purchase_id}/{operation}")
def operate(business_id: str, purchase_id: UUID, operation: str, body: Answer | Revision,
            request: Request, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    with guarded(response):
        bid, uid = owner(business_id, session)
        pid = str(purchase_id)
        if operation == "prepare":
            return prepare(bid, uid, pid, body.revision)
        if operation == "dismiss":
            return close_proposal(bid, uid, pid, body.revision)
        if operation == "refresh":
            return refresh(bid, uid, pid)
        if operation == "answer" and isinstance(body, Answer):
            return answer(bid, uid, pid, body)
        if operation == "checkout":
            require_unlock(request, uid, SCOPE_DANGER)
            return checkout(bid, uid, pid, body.revision)
        raise HTTPException(404, "Unknown purchase action.", headers=NO_STORE)
