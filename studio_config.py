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

# COST_CAP_ENABLED lived here — the on/off switch for a hard daily
# Builder cap (50 runs/day, system-wide, process-local). Removed
# 2026-08-13 (site-builder audit) with studio_cost_cap itself.
#
# It was never wired: introduced in the SAME commit as the cap it was
# meant to gate (Pass 3.8g, a13b629), and read by nothing, ever. The
# cap it guarded was reachable only through /generate-multi-page,
# which has been 503 since 2026-05-08 and is 410 now — so the counter
# sat at zero for three months and the UI showed a gauge that could
# not move.
#
# Build spend is governed by CREDITS: pricing_config.build_base() +
# billing_limits.require_units, metered per build on the composer
# path. If a daily ceiling is ever wanted, it belongs there, not on
# a retired engine.

# Solutionist Quality rules block in Builder prompt + post-build validator.
# Set False to ship Builder output without the SQ ceiling (debugging path).
SOLUTIONIST_QUALITY_ENABLED: bool = True
