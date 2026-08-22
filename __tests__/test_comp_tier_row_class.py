"""The comp_tier-starved-select class (flip test, 2026-08-22).

plan_of() reads comp_tier FIRST — it is how a comped account gets its
tier without a subscription. Any /businesses select that feeds plan_of
but omits comp_tier silently disables comp accounts for whatever that
row gates. The live flip test caught it: a comped Solutionist business
answered "limit 1" on the multi-business cap. A sweep found the same
starvation on the seat cap (invite + fallback), the Plaid cap, the
usage allotment, the concierge tier check, and — worst — mcp_oauth,
whose select also dropped subscription_status, denying agent_connector
to PAYING subscribers too.

THE FAKE PROJECTS THE SELECT. FakeSB.get() returns whole rows no
matter what columns the query asked for, which would make every test
here pass against the broken selects. _ProjectingSB narrows each row
to the selected columns exactly like PostgREST — that is what lets
these tests fail against the bug they exist to catch (each was proven
red against the pre-fix selects).
"""
from __future__ import annotations

import re
import sys
import pathlib
from urllib.parse import parse_qs, urlparse

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from test_i2_gl_sync import FakeSB  # noqa: E402

import billing_limits as bl  # noqa: E402
import feature_gates  # noqa: E402


class _ProjectingSB(FakeSB):
    """FakeSB that honors select= column lists, like PostgREST does."""

    def get(self, path):
        rows = super().get(path)
        q = parse_qs(urlparse(path).query)
        select = (q.get("select") or ["*"])[0]
        if select == "*":
            return rows
        cols = [c.strip() for c in select.split(",") if c.strip()]
        return [{c: r.get(c) for c in cols if c in r} for r in rows]


@pytest.fixture
def fake(monkeypatch):
    fb = _ProjectingSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    for k in ("BILLING_ENFORCE", "STRIPE_PRICE_ID_STARTER",
              "STRIPE_PRICE_ID_PROFESSIONAL", "STRIPE_PRICE_ID_PRACTICE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_professional")
    monkeypatch.setenv("STRIPE_PRICE_ID_PRACTICE", "price_practice")
    return fb


def _comp_biz(fb, bid, comp, owner="owner1"):
    fb.rows("businesses").append({
        "id": bid, "owner_id": owner, "is_active": True, "name": bid,
        "subscription_status": None, "subscription_plan": None,
        "comp_tier": comp, "settings": {}})


def test_comped_solutionist_gets_three_businesses(fake):
    """THE flip-test catch: owner_best_plan_row's select dropped
    comp_tier, so a comped top-tier owner was capped at 1 business."""
    _comp_biz(fake, "b1", "practice")
    out = bl.can_create_business("owner1")
    assert out["plan"] == "practice"
    assert out["limit"] == 3
    assert out["allowed"] is True


def test_comped_solutionist_seat_cap_is_five(fake):
    """can_add_seat's fallback fetch — the row business_users_router
    trusts at invite time comes through the same starved shape."""
    _comp_biz(fake, "b1", "practice")
    out = bl.can_add_seat("b1")
    assert out["limit"] == 5
    assert out["allowed"] is True


def test_comped_professional_plaid_cap_is_five(fake):
    _comp_biz(fake, "b1", "professional")
    out = bl.can_connect_account("b1")
    assert out["limit"] == 5


def test_comped_solutionist_allotment_is_practice_sized(fake):
    _comp_biz(fake, "b1", "practice")
    out = bl.chief_usage("b1")
    assert out["plan"] == "practice"
    import pricing_config
    assert out["limit"] == pricing_config.practice_credits()


def test_concierge_tier_check_sees_comp(fake):
    _comp_biz(fake, "b1", "professional")
    import site_concierge
    row = site_concierge._biz_row("b1")
    assert feature_gates.has_feature(row, "site_concierge") is True


def test_mcp_oauth_row_carries_status_and_comp():
    """mcp_oauth's select dropped subscription_status entirely — a
    PAYING subscriber resolved to no plan. Pin the select itself: it
    must carry every column plan_of() consumes."""
    src = pathlib.Path(bl.__file__).parent.joinpath("mcp_oauth.py").read_text(encoding="utf-8")
    m = re.search(r'businesses\?id=eq\.\{business_id\}"?\s*f?"&select=([^&"]+)', src)
    assert m, "mcp_oauth business select not found"
    cols = m.group(1)
    for needed in ("subscription_status", "subscription_plan", "comp_tier"):
        assert needed in cols, f"mcp_oauth select missing {needed}"


def test_the_402_names_the_tier_by_its_display_name(fake, monkeypatch):
    """'practice' is the key; 'Solutionist' is the name (8/19 rename).
    The flip test caught the 402 copy still saying 'Practice-plan'."""
    import usage_metering
    _comp_biz(fake, "b1", "starter")
    monkeypatch.setattr(usage_metering, "is_grandfathered_business",
                        lambda bid, row=None: False)
    with pytest.raises(HTTPException) as e:
        bl.require_feature("b1", "audit_trail")
    d = e.value.detail
    assert d["required_plan"] == "practice", "the KEY must not change — the FE maps it"
    assert "Solutionist-plan feature" in d["message"]
    assert "Practice-plan" not in d["message"]


def test_no_plan_still_resolves_to_no_plan(fake):
    """The fix adds a column, not a default — a business with neither a
    subscription nor a comp still has no plan and starter-sized caps."""
    _comp_biz(fake, "b1", None)
    out = bl.can_create_business("owner1")
    assert out["plan"] is None
    assert out["limit"] == 1
