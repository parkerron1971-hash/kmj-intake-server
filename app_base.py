"""app_base — the one place that knows where the practitioner app lives.

Every outbound link into the app (seat invites, collaborator invites,
contractor onboarding, fresh booking links, Stripe Connect returns) must
come through here. History: `https://app.solutionist.studio` was
hardcoded in five routers and that domain never resolved — every invite
email shipped a dead link. The app's live home is the Vercel deployment;
when a branded app domain is bound, change APP_BASE_URL and nothing else.
"""

from __future__ import annotations

import os

_DEFAULT_APP_BASE = "https://solutionist-studio.vercel.app"


def app_base_url() -> str:
    """Base URL of the practitioner app, no trailing slash."""
    return (os.environ.get("APP_BASE_URL") or _DEFAULT_APP_BASE).rstrip("/")
