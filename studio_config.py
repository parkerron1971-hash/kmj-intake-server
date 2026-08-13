"""Pass 3.8g — runtime feature flags.

Module-level constants the rest of the system imports. Change a value,
redeploy, behavior changes. No env-var indirection (yet).
"""
from __future__ import annotations


# MULTI_PAGE_ENABLED lived here. Removed 2026-08-13 (site-builder audit)
# with both things it gated: the /generate-multi-page endpoint, now 410,
# and Smart Sites' multi-page render Layer 0. It had been False since
# 2026-05-08, so neither had run in three months.
#
# Multi-page is not gone — it moved. compose_site renders About /
# Services / Contact through site_multipage whenever a site's site_type
# is "multi-page", and public_site serves them at /about, /services and
# /contact. There is no flag on that path, because it is the live one.

# Hard daily Builder cap. Disabling this means Builder runs are unmetered;
# only useful for local dev or after a verified cost-control change.
#
# NOTE (2026-08-13): nothing reads this. studio_cost_cap enforces the cap
# unconditionally. Left in place rather than removed with its neighbour
# because it reads as a cost-control switch someone may have meant to
# wire, and that is a money decision, not a cleanup one.
COST_CAP_ENABLED: bool = True

# Solutionist Quality rules block in Builder prompt + post-build validator.
# Set False to ship Builder output without the SQ ceiling (debugging path).
SOLUTIONIST_QUALITY_ENABLED: bool = True
