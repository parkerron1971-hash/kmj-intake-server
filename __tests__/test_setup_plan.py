# __tests__/test_setup_plan.py
#
# The session exit ramp. Pins: price parsing, plan tier logic
# (inserts only offered when they'd do work; connects state-aware),
# and the route+auth surface.

from unittest import mock

import setup_plan


def test_parse_price():
    p = setup_plan.parse_price
    assert p("$1,200/mo") == 1200.0
    assert p("450") == 450.0
    assert p(89.5) == 89.5
    assert p("call for pricing") is None
    assert p(None) is None


def test_slugify():
    assert setup_plan._slugify("Deep Clean (Weekly!)") == "deep-clean-weekly"
    assert setup_plan._slugify("") == "offering"


_BIZ = {"id": "biz-1", "name": "Clean Quick", "owner_id": "o1",
        "stripe_account_id": None, "settings": {}}


def _sb_router(overrides):
    """Route sb_get_as_service by path prefix; default empty."""
    def fake(path):
        for prefix, value in overrides.items():
            if path.startswith(prefix):
                return value
        return []
    return fake


def test_plan_offers_inserts_only_when_they_do_work():
    overrides = {
        "/strategy_tracks": [{"service_packages": [
            {"name": "Deep Clean", "price": "$200", "delivery_format": "one_on_one"}],
            "pricing_strategy": {"tiers": [1]}}],
        "/offerings": [],                       # none yet -> offer creation
        "/business_profiles": [{"service_models": [], "pricing_models": [],
                                "governing_state": "MI"}],
        "/plaid_items": [],
        "/quickbooks_connections": [],
    }
    with mock.patch.object(setup_plan.sb_clients, "sb_get_as_service",
                           side_effect=_sb_router(overrides)), \
         mock.patch("offering_profiles.business_state",
                    return_value={"stripe_connected": False, "booking_enabled": False}):
        plan = setup_plan.build_setup_plan(dict(_BIZ))

    kinds = {i["kind"] for i in plan["inserts"]}
    assert kinds == {"offerings_from_packages", "profile_fields", "financial_state"}
    assert plan["actionable"] is True
    by_id = {c["id"]: c for c in plan["connects"]}
    assert by_id["stripe"]["done"] is False
    assert by_id["bank"]["done"] is False


def test_plan_goes_quiet_when_everything_is_set_up():
    overrides = {
        "/strategy_tracks": [{"service_packages": [{"name": "X", "price": "$1"}],
                              "pricing_strategy": {}}],
        "/offerings": [{"id": "off-1"}],        # offerings exist -> no insert
        "/business_profiles": [{"service_models": ["one_on_one"],
                                "pricing_models": ["package"],
                                "governing_state": ""}],
        "/plaid_items": [{"item_id": "it-1"}],
        "/quickbooks_connections": [{"business_id": "biz-1"}],
    }
    with mock.patch.object(setup_plan.sb_clients, "sb_get_as_service",
                           side_effect=_sb_router(overrides)), \
         mock.patch("offering_profiles.business_state",
                    return_value={"stripe_connected": True, "booking_enabled": True}):
        plan = setup_plan.build_setup_plan(dict(_BIZ))

    assert plan["inserts"] == []
    assert all(c["done"] for c in plan["connects"])
    assert plan["actionable"] is False


def test_routes_exist_and_are_authed():
    from auth_supabase import require_user

    by_path = {}
    for r in setup_plan.router.routes:
        by_path.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "GET" in by_path.get("/strategy/setup-plan", set())
    assert "POST" in by_path.get("/strategy/setup-plan/apply", set())
    for r in setup_plan.router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"
