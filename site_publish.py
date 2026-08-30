"""site_publish.py — the autonomy dial, and what it is allowed to govern.

Publishing splits into two kinds of destination, and they do not deserve
the same rule.

A post to a Facebook Page lands on somebody else's platform. It notifies
followers, it cannot be unsent, and taking it down does not take back
who saw it. Approval there is not a preference — it is the whole reason
post_approval.py exists, and there is no setting here that turns it off.

A post to the practitioner's own news feed lands on their own domain, on
our server, with no third party's terms in play and no audience pushed
at. Removing it removes the page. That difference is what makes an
automatic setting defensible for one and not the other.

So the dial has exactly two values and reaches exactly one verb. It is
written this way — an allow-list of one — rather than as a boolean the
social path could later be taught to read.
"""
from __future__ import annotations

from typing import Any, Dict

SETTING_KEY = "content_autonomy"

# Approve everything before it goes out unattended. The default, and the
# value any unrecognised setting collapses to.
APPROVE_ALL = "approve_all"

# The site feed may publish on a schedule without a per-post approval.
# Social is untouched by this value — see GOVERNS below.
AUTO_SITE = "auto_site"

VALUES = (APPROVE_ALL, AUTO_SITE)

# The verbs the dial can speak for. `publish_post` is deliberately absent
# and must stay absent: adding it here would silently convert "approve
# everything" into a preference on a surface where a mistake is public,
# permanent, and on a platform we do not control.
GOVERNS = frozenset({"publish_to_site"})


def setting(settings: Dict[str, Any]) -> str:
    """The business's dial, defaulting closed.

    Anything unrecognised — a typo, a value from a future version, a
    hand-edited row — reads as APPROVE_ALL. A dial that fails open is a
    dial that publishes on the day someone fat-fingers it.
    """
    raw = (settings or {}).get(SETTING_KEY)
    return raw if raw in VALUES else APPROVE_ALL


def exempt_from_approval(verb: str, settings: Dict[str, Any]) -> bool:
    """May this verb publish unattended without a per-post approval?

    Two conditions, both required: the dial is on, AND the verb is one
    the dial is allowed to speak for. The second check is what stops a
    future caller from passing `publish_post` and inheriting an
    exemption the owner set for their own website.
    """
    if verb not in GOVERNS:
        return False
    return setting(settings) == AUTO_SITE
