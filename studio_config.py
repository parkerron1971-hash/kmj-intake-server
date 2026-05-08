"""Pass 3.8g — runtime feature flags.

Module-level constants the rest of the system imports. Change a value,
redeploy, behavior changes. No env-var indirection (yet).
"""
from __future__ import annotations


# Multi-page architecture (Home / About / Services / Contact). Set False
# to fall back to single-page Builder for every site, regardless of the
# site_type stored on a business_sites row.
#
# Pass 3.8g hotfix — kept FALSE until the multi-page path is re-validated
# end-to-end. Single-page Builder + Solutionist Quality + cost cap are
# all still active; only the multi-page render Layer 0 + the
# /generate-multi-page endpoint go through this flag.
MULTI_PAGE_ENABLED: bool = False

# Hard daily Builder cap. Disabling this means Builder runs are unmetered;
# only useful for local dev or after a verified cost-control change.
COST_CAP_ENABLED: bool = True

# Solutionist Quality rules block in Builder prompt + post-build validator.
# Set False to ship Builder output without the SQ ceiling (debugging path).
SOLUTIONIST_QUALITY_ENABLED: bool = True
