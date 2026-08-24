"""
platform_addresses.py — the addresses the platform publishes and notifies.

There used to be two of these. `marketing_pages.CONTACT_EMAIL` and
`legal_content.CONTACT_EMAIL` were separate constants holding the same
literal, and the marketing site had already moved on to a derived
`hello@<inbound domain>` while the legal pages were still printing the
founder's personal Gmail. Same product, two addresses, and the one on
the Privacy Policy was the one that looked least like a company.

So both live here now, and both are derived the same way. Adding a
third caller means importing this, not copying a literal.

Two addresses, two jobs:

  public_contact_email()   the address the SITE PRINTS — "email us".
                           Goes on privacy, terms, help, SMS, the FAQ,
                           the data-deletion page and the in-app support
                           panel. Public, quotable, on a $79-399/mo
                           product's legal pages.

  operator_email()         where the system NOTIFIES THE OPERATOR — the
                           "a lead came in" mail the marketing site
                           sends. Internal. Never printed.

Both resolve to a local part that `email_sender` already claims in
PLATFORM_INBOX_DEFAULT_LOCALS, which is what makes them land in
`platform_emails` and show up in Mission Control's inbox rather than
falling through to the contact-reply pipeline. That coupling is not
decorative and it is not enforced by reading — it is a test
(`test_the_published_locals_are_ones_the_inbox_actually_claims`).

Kevin's ruling, 2026-08-20, is the reason any of this derives rather
than hardcodes: "contact should land in the system, not in a personal
mailbox." The Gmail fallback below is not a preference, it is a
bounce-guard: an address whose MX is not live is worse on an about page
than an unglamorous one that works, so the derived address only gets
published once INBOUND_EMAIL_DOMAIN says inbound mail is real.
"""

from __future__ import annotations

import os

# The local parts. Both are in email_sender.PLATFORM_INBOX_DEFAULT_LOCALS
# ("kevin,support,hello,admin,info,billing,contact") — a test proves it.
PUBLIC_CONTACT_LOCAL = "info"
OPERATOR_LOCAL = "admin"

# Where mail goes when inbound is NOT configured. A real mailbox that a
# human reads, on purpose — see the bounce-guard note above.
FOUNDER_FALLBACK_EMAIL = "kmjcreativesolution@gmail.com"


def _inbound_domain() -> str:
    """The MX-receiving domain, or "" when inbound mail isn't set up.
    Mirrors email_sender._inbound_domain without importing it — this
    module stays dependency-free so a page renderer can import it
    without dragging httpx and the send stack along."""
    return (os.environ.get("INBOUND_EMAIL_DOMAIN") or "").strip().lower()


def _derive(local: str, override_env: str) -> str:
    """override → local@<inbound domain> → founder mailbox."""
    override = (os.environ.get(override_env) or "").strip()
    if override:
        return override
    domain = _inbound_domain()
    if domain:
        return f"{local}@{domain}"
    return FOUNDER_FALLBACK_EMAIL


def public_contact_email() -> str:
    """The address the public site and the in-app support panel print.

    Resolution order:
      1. PUBLIC_CONTACT_EMAIL — explicit override, when the address to
         publish isn't the one derived below.
      2. info@INBOUND_EMAIL_DOMAIN — set only when inbound mail is
         actually configured, which is exactly when it is safe to print.
      3. The founder mailbox — bounce-guard, see module docstring.
    """
    return _derive(PUBLIC_CONTACT_LOCAL, "PUBLIC_CONTACT_EMAIL")


def operator_email() -> str:
    """Where the system mails the operator (lead alerts). Same ladder,
    its own override, and never printed on a page.

    Kevin, 2026-08-23: these land in the product now. Setting
    PLATFORM_OPERATOR_EMAIL to a personal mailbox puts them back on a
    phone in one env var if the Mission Control inbox isn't watched.
    """
    return _derive(OPERATOR_LOCAL, "PLATFORM_OPERATOR_EMAIL")
