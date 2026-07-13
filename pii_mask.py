"""
pii_mask.py — tiny helpers to keep customer PII out of logs.

Beta-readiness audit (privacy): inbound SMS bodies, email payloads, and
raw contact emails/phones were being logged — some at WARNING level,
which the platform watchdog's ring buffer captures and renders in
Mission Control, i.e. a tester's CUSTOMER's message content showing up
in the owner's admin UI. These helpers give logs enough to debug
(domain, last-4, lengths) without the sensitive value itself.
"""


def mask_email(email: str) -> str:
    e = (email or "").strip()
    if "@" not in e:
        return "***" if e else ""
    local, _, domain = e.partition("@")
    return f"{local[:1]}***@{domain}" if local else f"***@{domain}"


def mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return f"***{digits[-4:]}" if len(digits) >= 4 else "***"
