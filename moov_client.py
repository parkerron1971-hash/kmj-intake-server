"""moov_client.py — the one door to Moov (test mode only in this build).

Kevin, 2026-11-27: a church may pay its 1099 people (guest speakers,
musicians, contractors, reimbursements) through Moov, FROM THE CHURCH'S OWN
BANK, so the church is the payer and Solutionist never is. Off by default,
each church opts in (moov_payouts.py holds the routes and the rules).

    THE MODEL ...... Solutionist's Moov account is the PARTNER (facilitator).
                     Each church is its own Moov business account, onboarded
                     by Moov's hosted form (KYB, the church's bank). Each
                     payee is their own Moov account, onboarded the same way.
                     A transfer is created on the partner's path, but its
                     SOURCE is a payment method of the church's account and
                     its DESTINATION one of the payee's
    TEST MODE ONLY . LIVE_ALLOWED is False. MOOV_MODE=live is refused here,
                     not just unset: real money moves only after a reviewed
                     change flips the constant (docs/MOOV_PAYOUTS.md, "Go
                     live")
    AUTH ........... HTTP Basic with the API key's public and private keys on
                     every call, the server-side form Moov documents (no
                     browser token, so no Origin/Referer domain rule)
    NEVER LOGGED ... the keys, the Authorization header, request bodies, and
                     Moov's error bodies (an error can echo account details).
                     A failure logs the method, the path's shape and the
                     status, nothing more
    THE WEBHOOK .... Moov signs `{X-Timestamp}|{X-Nonce}|{X-Webhook-ID}` with
                     HMAC-SHA512 (hex). The BODY IS NOT SIGNED, so a caller
                     treats a verified delivery only as "go and look": every
                     state change is read back from Moov's API

Docs checked 2026-11-27 (docs.moov.io, API version v2026.10.00). The
transfer amount: the schema names `amount.valueDecimal` (a decimal string)
while the page's own examples send `amount.value` (integer cents);
MOOV_AMOUNT_SHAPE picks one ("decimal", the default, or "cents") so a first
sandbox call settles it without a deploy of code.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException

logger = logging.getLogger("moov_client")

# Real money is a reviewed code change, never an env var someone sets.
LIVE_ALLOWED = False

API_BASE = "https://api.moov.io"
DEFAULT_VERSION = "v2026.10.00"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)
# Moov's own limit for X-Wait-For is 15 s; give the read a little more.
TRANSFER_TIMEOUT = httpx.Timeout(connect=10.0, read=25.0, write=15.0, pool=10.0)
# A webhook whose timestamp is further than this from now is refused (Moov
# publishes no window; ten minutes allows for its retries' clock, not more).
WEBHOOK_TOLERANCE_SECONDS = 600

NOT_CONFIGURED = "Sending with Moov isn't set up yet."
LIVE_REFUSED = "Sending with Moov runs in test mode only for now."
MOOV_502 = "Moov didn't answer as expected. Nothing was sent."

# What each speed costs on Moov's standard pricing (moov.io/pricing, read
# 2026-11-27). Shown to the church before it sends; who carries the fee is
# a pricing decision (docs/MOOV_PAYOUTS.md), not charged by this code.
SPEEDS = ("next_day", "same_day", "instant")
DEFAULT_SPEED = "next_day"
# The destination payment-method types each speed may use, best first.
DEST_TYPES = {
    "next_day": ("ach-credit-standard",),
    "same_day": ("ach-credit-same-day",),
    "instant": ("rtp-credit", "instant-bank-credit", "push-to-card"),
}


def fee_for(speed: str, amount: float) -> float:
    """Moov's fee for one payout at this speed, in dollars."""
    if speed == "same_day":
        return 0.40
    if speed == "instant":
        return round(min(5.00, max(0.50, amount * 0.0095)), 2)
    return 0.25


# ─── Settings ──────────────────────────────────────────────────────────

def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def mode() -> str:
    """'test' unless MOOV_MODE says live (which this build refuses)."""
    return "live" if _env("MOOV_MODE").lower() == "live" else "test"


def partner_account_id() -> str:
    return _env("MOOV_PARTNER_ACCOUNT_ID")


def configured() -> bool:
    """Keys and the partner id are set, and the mode is one this build runs."""
    if mode() == "live" and not LIVE_ALLOWED:
        return False
    return bool(_env("MOOV_PUBLIC_KEY") and _env("MOOV_PRIVATE_KEY") and partner_account_id())


def why_not() -> Optional[str]:
    if mode() == "live" and not LIVE_ALLOWED:
        return LIVE_REFUSED
    if not configured():
        return NOT_CONFIGURED
    return None


def fee_plan_codes() -> List[str]:
    return [c.strip() for c in _env("MOOV_FEE_PLAN_CODES").split(",") if c.strip()]


def church_capabilities() -> List[str]:
    """What a church's account asks for: to send by ACH from its bank."""
    raw = _env("MOOV_CHURCH_CAPABILITIES") or "transfers,send-funds.ach,wallet.balance"
    return [c.strip() for c in raw.split(",") if c.strip()]


def payee_capabilities() -> List[str]:
    """A payee only receives: Moov's payout guide asks `transfers` alone."""
    raw = _env("MOOV_PAYEE_CAPABILITIES") or "transfers"
    return [c.strip() for c in raw.split(",") if c.strip()]


def invite_scopes() -> List[str]:
    """What the partner may do on an account that redeems an invite."""
    raw = _env("MOOV_INVITE_SCOPES") or (
        "accounts.read,bank-accounts.read,payment-methods.read,transfers.read,transfers.write,capabilities.read")
    return [c.strip() for c in raw.split(",") if c.strip()]


def amount_shape() -> str:
    return "cents" if _env("MOOV_AMOUNT_SHAPE").lower() == "cents" else "decimal"


# ─── HTTP ─────────────────────────────────────────────────────────────

_ID = re.compile(r"[0-9a-fA-F-]{20,}")


def _shape(path: str) -> str:
    """The path with its ids hidden, for a log line."""
    return _ID.sub(":id", path.split("?")[0])


class MoovError(Exception):
    def __init__(self, status: int, path: str, body: Any = None) -> None:
        super().__init__(f"moov {status} {_shape(path)}")
        self.status = status
        self.body = body


def _auth() -> tuple:
    return (_env("MOOV_PUBLIC_KEY"), _env("MOOV_PRIVATE_KEY"))


def _headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    h = {"X-Moov-Version": _env("MOOV_VERSION") or DEFAULT_VERSION, "Accept": "application/json"}
    if extra:
        h.update(extra)
    return h


# Tests swap this for a fake (`transport=httpx.MockTransport(...)`).
_transport: Optional[httpx.BaseTransport] = None


def request(method: str, path: str, *, json: Any = None, headers: Optional[Dict[str, str]] = None,
            timeout: httpx.Timeout = HTTP_TIMEOUT) -> Any:
    """One call to Moov. Raises MoovError on 4xx/5xx (body kept for the caller,
    never logged) and HTTPException(503) when the integration can't run."""
    reason = why_not()
    if reason:
        raise HTTPException(503, reason)
    url = f"{_env('MOOV_API_BASE') or API_BASE}{path}"
    try:
        with httpx.Client(timeout=timeout, transport=_transport) as client:
            r = client.request(method, url, json=json, headers=_headers(headers), auth=_auth())
    except httpx.HTTPError as e:
        logger.warning("[moov] %s %s transport error: %s", method, _shape(path), type(e).__name__)
        raise HTTPException(502, MOOV_502)
    try:
        body = r.json() if r.content else None
    except ValueError:
        body = None
    if r.status_code >= 400:
        logger.warning("[moov] %s %s -> %s", method, _shape(path), r.status_code)
        raise MoovError(r.status_code, path, body)
    return {"_status": r.status_code, **body} if isinstance(body, dict) else body


# ─── Accounts and onboarding ──────────────────────────────────────────

def create_onboarding_invite(*, account_type: str, prefill_profile: Dict[str, Any], foreign_id: str,
                             capabilities: List[str], return_url: Optional[str] = None) -> Dict[str, Any]:
    """Moov's hosted onboarding: the church (KYB and its bank) or a payee
    (their bank or card) fills Moov's own form. Returns {code, link, ...}."""
    body: Dict[str, Any] = {
        "capabilities": capabilities,
        "feePlanCodes": fee_plan_codes(),
        "scopes": invite_scopes(),
        "prefill": {"accountType": account_type, "profile": prefill_profile, "foreignID": foreign_id[:64]},
    }
    if return_url:
        body["returnURL"] = return_url
    return request("POST", "/onboarding-invites", json=body)


def get_onboarding_invite(code: str) -> Dict[str, Any]:
    """`redeemedAccountID` is set once the form is finished."""
    return request("GET", f"/onboarding-invites/{_seg(code)}")


def get_account(account_id: str) -> Dict[str, Any]:
    return request("GET", f"/accounts/{_seg(account_id)}")


def list_payment_methods(account_id: str, payment_method_type: Optional[str] = None) -> List[Dict[str, Any]]:
    q = f"?paymentMethodType={_seg(payment_method_type)}" if payment_method_type else ""
    out = request("GET", f"/accounts/{_seg(account_id)}/payment-methods{q}")
    return out if isinstance(out, list) else []


def list_bank_accounts(account_id: str) -> List[Dict[str, Any]]:
    out = request("GET", f"/accounts/{_seg(account_id)}/bank-accounts")
    return out if isinstance(out, list) else []


def capabilities_of(account: Dict[str, Any]) -> Dict[str, str]:
    """{capability: status} from an account read."""
    out: Dict[str, str] = {}
    for c in (account or {}).get("capabilities") or []:
        if isinstance(c, dict) and c.get("capability"):
            out[str(c["capability"])] = str(c.get("status") or "")
        elif isinstance(c, str):
            out[c] = "enabled"
    return out


# ─── Money ────────────────────────────────────────────────────────────

def _amount(amount_cents: int) -> Dict[str, Any]:
    if amount_shape() == "cents":
        return {"currency": "USD", "value": int(amount_cents)}
    return {"currency": "USD", "valueDecimal": f"{amount_cents // 100}.{amount_cents % 100:02d}"}


def transfer_options(*, source_account_id: str, destination_account_id: str, amount_cents: int) -> Dict[str, Any]:
    """Moov's own answer to "which ways can this money go?"."""
    return request("POST", f"/accounts/{_seg(partner_account_id())}/transfer-options", json={
        "amount": {"currency": "USD", "valueDecimal": f"{amount_cents // 100}.{amount_cents % 100:02d}"},
        "source": {"accountID": source_account_id},
        "destination": {"accountID": destination_account_id},
    })


def create_transfer(*, source_account_id: str, source_payment_method_id: str,
                    destination_payment_method_id: str, amount_cents: int, idempotency_key: str,
                    description: str, metadata: Dict[str, str], foreign_id: str) -> Dict[str, Any]:
    """Send one payout. THE LAST CHECK: the source payment method must belong
    to `source_account_id`, as Moov itself says, and that account may never
    be the partner's: Solutionist never funds a transfer."""
    partner = partner_account_id()
    if not source_account_id or source_account_id == partner:
        raise HTTPException(403, "A payout must come from the church's own account.")
    owned = {str(m.get("paymentMethodID")) for m in list_payment_methods(source_account_id)}
    if source_payment_method_id not in owned:
        raise HTTPException(403, "A payout must come from the church's own account.")
    return request("POST", f"/accounts/{_seg(partner)}/transfers", json={
        "source": {"paymentMethodID": source_payment_method_id},
        "destination": {"paymentMethodID": destination_payment_method_id},
        "amount": _amount(amount_cents),
        "description": description[:256],
        "metadata": {k: str(v)[:256] for k, v in metadata.items()},
        "foreignID": foreign_id[:64],
    }, headers={"X-Idempotency-Key": idempotency_key, "X-Wait-For": "rail-response"},
        timeout=TRANSFER_TIMEOUT)


def get_transfer(transfer_id: str) -> Dict[str, Any]:
    return request("GET", f"/accounts/{_seg(partner_account_id())}/transfers/{_seg(transfer_id)}")


# ─── Webhook ──────────────────────────────────────────────────────────

def webhook_secret() -> str:
    return _env("MOOV_WEBHOOK_SECRET")


def signature_ok(headers: Any, *, secret: Optional[str] = None, now: Optional[float] = None) -> bool:
    """Moov's signature: hex HMAC-SHA512 of `timestamp|nonce|webhookID`.
    False for anything missing, stale or wrong. Constant-time compare."""
    key = secret if secret is not None else webhook_secret()
    if not key:
        return False
    ts = (headers.get("x-timestamp") or "").strip()
    nonce = (headers.get("x-nonce") or "").strip()
    wid = (headers.get("x-webhook-id") or "").strip()
    sig = (headers.get("x-signature") or "").strip().lower()
    if not (ts and nonce and wid and sig):
        return False
    try:
        when = float(ts)
    except ValueError:
        from datetime import datetime
        try:
            when = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return False
    if when > 1e11:  # milliseconds
        when /= 1000.0
    if abs((now if now is not None else time.time()) - when) > WEBHOOK_TOLERANCE_SECONDS:
        return False
    want = hmac.new(key.encode(), f"{ts}|{nonce}|{wid}".encode(), hashlib.sha512).hexdigest()
    return hmac.compare_digest(want, sig)


def _seg(v: Any) -> str:
    from urllib.parse import quote
    return quote(str(v), safe="")
