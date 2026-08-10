"""oauth_connect_ticket.py — proof that whoever started an OAuth connect
actually owns the business it will be bound to.

The problem this exists for:

    GET /connect/meta?business_id=<any uuid>
    GET /connect/quickbooks?business_id=<any uuid>

Both were unauthenticated, and both signed that business_id into the
OAuth `state` parameter. A signed state proves the state came from our
server. It does not prove the person holding it owns the business — so
anyone could open the connect URL with someone else's business_id,
authorise with their OWN Facebook or Intuit account, and have their
Pages or their QuickBooks realm bound to a stranger's tenant.

These endpoints are browser redirects, opened with window.open, so they
cannot carry a bearer token — which is why the check was missing rather
than merely forgotten. The fix is a two-step handshake: an authenticated
call the frontend CAN make mints a short-lived ticket, and the redirect
accepts the ticket instead of a bare business_id.

A ticket is deliberately boring: HMAC over (business_id, user_id, ts),
five-minute life, no storage. It is not a session and grants nothing on
its own — it only says "at this moment, this signed-in user owned this
business."
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional, Tuple

TICKET_TTL_SECONDS = 300


def _secret() -> str:
    """Shared with nothing else on purpose — a ticket must not be
    forgeable by anyone who learns an unrelated secret. Falls back so a
    partially-configured environment still boots, but the fallback is
    the service role key, which is never public."""
    return (os.environ.get("OAUTH_CONNECT_TICKET_SECRET")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or "solutionist-connect-ticket")


def mint(business_id: str, user_id: str) -> str:
    payload = {"b": str(business_id), "u": str(user_id), "ts": int(time.time())}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    sig = hmac.new(_secret().encode(), body.encode("ascii"),
                   hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify(ticket: str, max_age_s: int = TICKET_TTL_SECONDS
           ) -> Tuple[Optional[str], Optional[str]]:
    """Returns (business_id, user_id), or (None, None) on any failure.

    Never raises and never explains which check failed — a caller
    probing this endpoint learns only that the ticket was not good.
    """
    try:
        body, sig = (ticket or "").split(".", 1)
    except ValueError:
        return None, None
    try:
        expected = hmac.new(_secret().encode(), body.encode("ascii"),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None, None
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
        if int(time.time()) - int(payload.get("ts") or 0) > max_age_s:
            return None, None
        biz = payload.get("b") or None
        usr = payload.get("u") or None
        if not biz:
            return None, None
        return biz, usr
    except Exception:
        return None, None
