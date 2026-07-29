"""Phase VABI v1.5 — per-business terminology + VI override layer tests.

Covers:
  - vertical_terminology contact-noun additions (BASE + per-vertical)
  - terminology_overrides_router merge semantics (without hitting real DB)
  - vertical_intelligence_router business_id-aware merge
"""
from __future__ import annotations

import sys
import pathlib
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from vertical_terminology import BASE_TERMS, VERTICAL_TERMS, get_term


# ─── vertical_terminology.py — contact noun layer ────────────────────


def test_base_has_contact_noun():
    assert BASE_TERMS["contact"] == "Contact"
    assert BASE_TERMS["contacts"] == "Contacts"


def test_base_has_lead_prospect_nouns():
    # VABI v1.5 — added for the CTS sweep on GROW dashboards + Chief.
    assert BASE_TERMS["lead"] == "Lead"
    assert BASE_TERMS["leads"] == "Leads"
    assert BASE_TERMS["prospect"] == "Prospect"
    assert BASE_TERMS["prospects"] == "Prospects"


def test_lawyer_contact_maps_to_client():
    assert get_term("lawyer", "contact") == "Client"
    assert get_term("lawyer", "contacts") == "Clients"


def test_course_creator_contact_maps_to_student():
    assert get_term("course_creator", "contact") == "Student"
    assert get_term("course_creator", "contacts") == "Students"


def test_ministry_contact_maps_to_member():
    assert get_term("ministry", "contact") == "Member"
    assert get_term("ministry", "contacts") == "Members"


def test_personal_services_contact_maps_to_guest():
    # Was: "personal_services intentionally has NO contact override", which
    # meant a barbershop called the person in the chair a Contact/Customer.
    # The vertical readiness audit called that what it was, and the block is
    # no longer empty. See test_personal_services_terminology.py.
    assert get_term("personal_services", "contact") == "Guest"
    assert get_term("personal_services", "contacts") == "Guests"


def test_service_provider_contact_falls_back_to_generic():
    # The generic-baseline vertical still exercises the fallback path that
    # personal_services used to cover here.
    assert get_term("service_provider", "contact") == "Contact"
    assert get_term("service_provider", "contacts") == "Contacts"


def test_vertical_terms_contact_consistent_with_customer():
    """For every vertical that overrides 'customer', the 'contact'
    override should match (or be intentionally absent for the
    generic-baseline verticals). Catches mirror-drift between
    customer/contact noun families."""
    for vertical, overrides in VERTICAL_TERMS.items():
        if "customer" not in overrides:
            continue
        # personal_services was exempted here while its block was empty.
        # It now overrides both nouns and they agree (Guest/Guest), so it is
        # held to the same rule as every other vertical — the exemption list
        # is only for the genuinely-generic baselines.
        if vertical in ("service_provider", "custom"):
            continue
        assert overrides.get("contact") == overrides["customer"], (
            f"{vertical}: contact override should match customer override"
        )


# ─── terminology_overrides_router — merge semantics ──────────────────
#
# We exercise the merge path without hitting Supabase by monkeypatching
# the sb_clients calls. The merge logic + null-deletion semantics live
# entirely in the route handler, so this is the right test surface.


@pytest.fixture
def fake_sb(monkeypatch):
    """Faked sb_clients service-side calls. Captures patch bodies so
    tests can assert on what would have been written."""
    state: Dict[str, Any] = {
        "biz_rows": [
            {"id": "biz1", "owner_id": "owner1", "type": "lawyer"},
        ],
        "profile_rows": [
            {
                "business_id": "biz1",
                "terminology_overrides": {"customer": "Counterparty"},
                "vertical_intelligence_overrides": {},
            },
        ],
        "captured_patch": None,
    }

    def fake_get(path: str):
        if "/businesses?" in path:
            return list(state["biz_rows"])
        if "/business_profiles?" in path:
            return list(state["profile_rows"])
        return []

    def fake_post(path: str, body):
        return [body]

    def fake_patch(path: str, body):
        state["captured_patch"] = body
        # Reflect the merged row back to subsequent gets.
        if state["profile_rows"]:
            for k, v in body.items():
                state["profile_rows"][0][k] = v
        return state["profile_rows"]

    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake_get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake_post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake_patch)
    return state


def _user(id_: str = "owner1"):
    class _U:
        id = id_
    return _U()


def test_overrides_get_returns_effective_layer(fake_sb):
    from terminology_overrides_router import get_overrides
    resp = get_overrides("biz1", user=_user())
    assert resp["ok"] is True
    eff = resp["effective_terms"]
    # business override masks the lawyer vertical override
    assert eff["customer"] == "Counterparty"
    # lawyer vertical override still wins where business hasn't overridden
    assert eff["service"] == "Matter"
    # BASE-level term that nobody overrode
    assert eff["payment"] == "Payment"


def test_overrides_patch_merges_and_drops_nulls(fake_sb):
    from terminology_overrides_router import patch_overrides, OverridePatchBody
    body = OverridePatchBody(
        business_id="biz1",
        terminology={
            "customer": None,             # delete existing
            "contact": "Counterparty",    # add new
        },
    )
    resp = patch_overrides(body, user=_user())
    assert resp["ok"] is True
    written = fake_sb["captured_patch"]["terminology_overrides"]
    assert "customer" not in written      # null deleted it
    assert written["contact"] == "Counterparty"


def test_overrides_patch_owner_gate_rejects_non_owner(fake_sb):
    from fastapi import HTTPException
    from terminology_overrides_router import patch_overrides, OverridePatchBody
    body = OverridePatchBody(
        business_id="biz1",
        terminology={"customer": "X"},
    )
    with pytest.raises(HTTPException) as exc:
        patch_overrides(body, user=_user("not-the-owner"))
    assert exc.value.status_code == 403


def test_overrides_reset_clears_terminology_scope(fake_sb):
    from terminology_overrides_router import reset_overrides, OverrideResetBody
    body = OverrideResetBody(business_id="biz1", scope="terminology")
    resp = reset_overrides(body, user=_user())
    assert resp["ok"] is True
    written = fake_sb["captured_patch"]
    assert written["terminology_overrides"] == {}
    # VI scope NOT in this patch
    assert "vertical_intelligence_overrides" not in written


def test_overrides_reset_all_clears_both(fake_sb):
    from terminology_overrides_router import reset_overrides, OverrideResetBody
    body = OverrideResetBody(business_id="biz1", scope="all")
    resp = reset_overrides(body, user=_user())
    written = fake_sb["captured_patch"]
    assert written["terminology_overrides"] == {}
    assert written["vertical_intelligence_overrides"] == {}


# ─── vertical_intelligence_router — business_id merge ────────────────


def test_intelligence_endpoint_merges_business_overrides(fake_sb):
    from vertical_intelligence_router import get_vertical
    resp = get_vertical(business_id="biz1")
    eff = resp["effective_terms"]
    # Override layer wins over the lawyer vertical default ('Client')
    assert eff["customer"] == "Counterparty"
    # Vertical defaults still apply where business hasn't overridden
    assert eff["service"] == "Matter"
    assert resp["has_business_overrides"] is True


def test_intelligence_endpoint_no_business_id_returns_vertical_only(monkeypatch):
    from vertical_intelligence_router import get_vertical
    resp = get_vertical(business_type="lawyer")
    eff = resp["effective_terms"]
    assert eff["customer"] == "Client"      # lawyer default
    assert eff["service"] == "Matter"
    assert resp["has_business_overrides"] is False
