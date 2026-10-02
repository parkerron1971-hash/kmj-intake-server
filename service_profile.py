"""Describe business access and AI delivery separately for the edition rollout.

This is an additive, read-only projection of existing billing facts. It does
not authorize a tool, select a provider, create a subscription, or migrate an
account. Existing subscriptions remain `legacy` until an explicit commercial
migration exists. See docs/TWO_EDITION_ROLLOUT.md for the release gates.
"""
from __future__ import annotations

from typing import Any, Dict

import feature_gates


def describe(business: Dict[str, Any], entitlements: Dict[str, Any]) -> Dict[str, Any]:
    """Return plan inclusions, not runtime availability or remaining credit.

An included connector still needs a scoped credential, an active subscription,
the MCP switch and the policy engine. Grandfathering and enforcement bypasses
remain in the existing entitlement fields; they do not change plan inclusions.
Ignore customer-editable settings: they cannot select an edition or AI payer.
"""
    features = entitlements["features"]
    return {
        "schema_version": 1,
        "edition": "legacy",
        "business_plan": {
            "tier": entitlements["plan"],
            "limits": {
                key: feature_gates.limit_for(business, key)
                for key in ("max_seats", "max_businesses", "plaid_connections",
                            "open_assignments")
            },
        },
        "ai_service": {
            "delivery": "solutionist_provided",
            # The recurring plan grant, NOT the trial grant, remaining units,
            # purchased credits, or a promise of unlimited grandfather usage.
            "monthly_plan_credits": feature_gates.monthly_credits(business),
        },
        "external_agent": {
            "transport": "mcp",
            "read_included_in_plan": features["agent_connector"]["included_in_plan"],
            "write_included_in_plan": features["agent_connector_write"]["included_in_plan"],
            # An outside client calling MCP is not Chief running that client.
            "in_app_delegation_supported": False,
        },
    }
