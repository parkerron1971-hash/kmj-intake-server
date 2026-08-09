"""webhook_guard.py — one policy for what happens when a webhook signing
secret is missing.

Every inbound webhook on this platform used to fail OPEN when its secret
was unset: Resend (email_sender), Telnyx (sms_service) and Twilio
(twilio_sms) each logged a warning and processed the payload anyway. Each
was a reasonable local decision — don't break inbound while the operator
is still wiring up the provider — and together they were a hole, because
inbound email and SMS bodies are interpolated verbatim into Chief's
system prompt and Chief can send.

So the default flips: an unverifiable payload is dropped.

The escape hatch exists because flipping to fail-closed on a deploy where
a secret was never set would silently kill inbound mail, and a change
that quietly destroys a working path is its own kind of outage. Setting
WEBHOOK_ALLOW_UNSIGNED names the providers you are knowingly running
unverified — it is loud, per-provider, and shows up in every log line, so
it reads as a decision rather than an accident.

    WEBHOOK_ALLOW_UNSIGNED=resend          # one provider
    WEBHOOK_ALLOW_UNSIGNED=resend,telnyx   # several
    WEBHOOK_ALLOW_UNSIGNED=all             # everything (don't)

Unset — the default — means every provider verifies or is dropped.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_ENV = "WEBHOOK_ALLOW_UNSIGNED"


def _allowlist() -> set[str]:
    raw = (os.environ.get(_ENV) or "").strip().lower()
    if not raw:
        return set()
    return {p.strip() for p in raw.split(",") if p.strip()}


def unsigned_allowed(provider: str) -> bool:
    """True when `provider` is explicitly permitted to skip verification.

    Logs at CRITICAL every time it returns True. That is deliberate: an
    unverified inbound webhook is a standing incident, not a config
    detail, and it should be impossible to leave on without noticing.
    """
    allow = _allowlist()
    permitted = bool(allow) and (provider.lower() in allow or "all" in allow)
    if permitted:
        logger.critical(
            "[WEBHOOK] %s payload accepted WITHOUT signature verification — "
            "%s permits it. Untrusted content from this endpoint can reach "
            "Chief's prompt. Set the provider's signing secret and remove it "
            "from %s.", provider, _ENV, _ENV,
        )
    return permitted


def reject_unsigned(provider: str, reason: str) -> None:
    """Log a dropped payload. Call sites return 200 so a real-but-broken
    sender doesn't hammer retries; the payload is simply not processed."""
    logger.warning(
        "[WEBHOOK] %s payload DROPPED — %s. If this provider is not yet "
        "configured, set its signing secret; to accept unverified payloads "
        "deliberately, add '%s' to %s.", provider, reason, provider, _ENV,
    )
