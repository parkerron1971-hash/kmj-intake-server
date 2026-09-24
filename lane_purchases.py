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
from lane_wallet import router, owner, eligible, NO_STORE
import sb_clients
from auth_supabase import UserSession
from ledger_unlock import require_unlock, SCOPE_DANGER

OPAQUE = re.compile(r"[A-Za-z0-9_-]{1,160}")


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    prompt: str = Field(min_length=5, max_length=4000)


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
               "message", "checkout_claimed")
    return {k: state[k] for k in allowed if k in state}


def view(p):
    return snapshot(dict(p.state, id=p.args["p_id"], revision=p.revision, checkout_claimed=p.claimed))


def expect(p, revision):
    if p.revision != revision:
        raise mcp.LaneError("This purchase changed. Refresh it before taking action.")


def accept_draft(p, data):
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
        mandates = draft.get("mandates")
        if not isinstance(mandates, list) or not 1 <= len(mandates) <= 10:
            raise mcp.LaneError("Lane returned an incomplete merchant list.")
        normalized = []
        for m in mandates:
            amount = m.get("max_amount_cents")
            if type(amount) is not int or not 0 < amount <= 100000000:
                raise mcp.LaneError("Lane did not return a valid purchase ceiling.")
            normalized.append({"mandate_id": identifier(m.get("mandate_id")),
                               "merchant": text(m.get("merchant"), 253),
                               "summary": text(m.get("summary")),
                               "max_amount_cents": amount})
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


def draft(bid, uid, request_id, prompt):
    key = credentials(bid, uid)
    p = store.Purchase(bid, uid, key, str(request_id))
    p.create(prompt)
    with p:
        if p.state["phase"] != "new":
            return view(p)  # Stable idempotency key; never blindly re-submit.
        p.state["phase"] = "submitting"
        p.save()  # Crash/timeout thereafter leaves a durable ambiguous draft.
        accept_draft(p, mcp.call(key, "intent_submit", {"prompt": prompt, "external_ref": p.args["p_id"]}))
        return view(p)


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
        p.state["phase"] = "review"
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
        elif p.state["phase"] == "submitting":
            # No known provider response: resubmission could create duplicate approvals.
            if p.state.get("session_id") and p.state.get("intent_id"):
                approval(p, key)
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
        p.state["phase"] = "resolving"
        p.save()
        for mandate in p.state["mandates"]:
            result = mcp.call(key, "find_products", {"mandate_id": mandate["mandate_id"]})
            if result.get("outcome") != "ok" or not result.get("products") or result.get("unresolved"):
                p.state.update(phase="products_needed",
                               message="Lane could not resolve every product. Review product links in Lane before continuing.")
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
        return draft(bid, uid, body.request_id, body.prompt)


@router.post("/{business_id}/purchases/{purchase_id}/{operation}")
def operate(business_id: str, purchase_id: UUID, operation: str, body: Answer | Revision,
            request: Request, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    with guarded(response):
        bid, uid = owner(business_id, session)
        pid = str(purchase_id)
        if operation == "refresh":
            return refresh(bid, uid, pid)
        if operation == "answer" and isinstance(body, Answer):
            return answer(bid, uid, pid, body)
        if operation == "checkout":
            require_unlock(request, uid, SCOPE_DANGER)
            return checkout(bid, uid, pid, body.revision)
        raise HTTPException(404, "Unknown purchase action.", headers=NO_STORE)
