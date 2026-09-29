"""app_base — the one place that knows where the practitioner app lives.

Every outbound link into the app (seat invites, collaborator invites,
contractor onboarding, fresh booking links, Stripe Connect returns) must
come through here. History: `https://app.solutionist.studio` was
hardcoded in five routers and that domain never resolved — every invite
email shipped a dead link. The canonical app is system.mysolutionist.app.
APP_BASE_URL supports explicit alternate environments; the retired Vercel
alias is normalized to the branded production origin.
"""

from __future__ import annotations

import os

_DEFAULT_APP_BASE = "https://system.mysolutionist.app"


def app_base_url() -> str:
    """Base URL of the practitioner app, no trailing slash."""
    configured = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
    # Retire the old deployment alias even if an environment still sets it.
    if configured == "https://solutionist-studio.vercel.app":
        return _DEFAULT_APP_BASE
    return configured or _DEFAULT_APP_BASE
