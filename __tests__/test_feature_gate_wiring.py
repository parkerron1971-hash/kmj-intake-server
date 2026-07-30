"""7/30 tier arc — require_feature() wiring: the feature→tier map's first
production callers. Every gate is DORMANT (BILLING_ENFORCE off → never
raises) and honors grandfather + comp_tier when enforcement is on."""
from __future__ import annotations

import asyncio
import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import billing_limits as bl  # noqa: E402
import reports_router as rr  # noqa: E402
import business_collaborators_router as bc  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


class _User:
    id = "owner1"


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    for k in ("BILLING_ENFORCE", "STRIPE_PRICE_ID_STARTER",
              "STRIPE_PRICE_ID_PROFESSIONAL", "STRIPE_PRICE_ID_PRACTICE"):
        monkeypatch.delenv(k, raising=False)
    return fb


def _biz(fb, bid, *, plan=None, status="active", comp=None):
    fb.rows("businesses").append({
        "id": bid, "owner_id": "owner1", "is_active": True, "name": bid,
        "subscription_status": status if plan else None,
        "subscription_plan": plan, "comp_tier": comp, "settings": {}})


def _enforce(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_professional")
    monkeypatch.setenv("STRIPE_PRICE_ID_PRACTICE", "price_practice")


def test_dormant_gate_never_blocks(fake):
    """BILLING_ENFORCE off: a Starter business uses every gated surface."""
    _biz(fake, "b1", plan="price_starter")
    bl.require_feature("b1", "reports_full")          # no raise
    bl.require_feature("b1", "vertical_reports")      # no raise
    out = rr.trial_balance("b1", None, _User())       # endpoint passes the gate
    assert out["ok"] is True


def test_starter_locked_out_of_reports_full(fake, monkeypatch):
    _biz(fake, "b1", plan="price_starter")
    _enforce(monkeypatch)
    with pytest.raises(HTTPException) as e:
        rr.trial_balance("b1", None, _User())
    assert e.value.status_code == 402
    d = e.value.detail
    assert d["error"] == "feature_locked"
    assert d["feature"] == "reports_full"
    assert d["required_plan"] == "professional"


def test_professional_passes_reports_full(fake, monkeypatch):
    _biz(fake, "b1", plan="price_professional")
    _enforce(monkeypatch)
    out = rr.trial_balance("b1", None, _User())
    assert out["ok"] is True
    # ...but Practice-only vertical reports still lock.
    with pytest.raises(HTTPException) as e:
        rr.prep_990("b1", None, _User())
    assert e.value.status_code == 402
    assert e.value.detail["required_plan"] == "practice"


def test_comp_tier_and_grandfather_pass(fake, monkeypatch):
    # comp_tier wins with no subscription at all.
    _biz(fake, "b1", comp="practice")
    _enforce(monkeypatch)
    assert rr.prep_990("b1", None, _User())["ok"] is True
    # Grandfathered owner passes even on a bare Starter row.
    _biz(fake, "b2", plan="price_starter")
    import usage_metering
    monkeypatch.setattr(usage_metering, "is_grandfathered_business",
                        lambda bid, row=None: bid == "b2")
    assert rr.trial_balance("b2", None, _User())["ok"] is True


def test_export_gates_like_screen(fake, monkeypatch):
    """Gated reports refuse export on Starter; Starter reports export free."""
    _biz(fake, "b1", plan="price_starter")
    _enforce(monkeypatch)
    with pytest.raises(HTTPException) as e:
        rr.export("b1", "general_ledger", "csv", "this_month", None, None,
                  None, None, None, None, _User())
    assert e.value.status_code == 402
    # Basic report export is NOT in _REPORT_FEATURES — the escape hatch.
    assert "pl" not in rr._REPORT_FEATURES
    assert "balance_sheet" not in rr._REPORT_FEATURES


def test_collaborator_invite_is_practice_gated(fake, monkeypatch):
    _biz(fake, "b1", plan="price_professional")
    _enforce(monkeypatch)
    with pytest.raises(HTTPException) as e:
        asyncio.run(bc.invite("b1", bc.InviteBody(email="cpa@x.com"), _User()))
    assert e.value.status_code == 402
    assert e.value.detail["feature"] == "accountant_collaborator"
    # Accepting an existing invite is never plan-locked: seed a pending row
    # and accept as the invitee even while the business is under-tiered.
    fake.rows("business_collaborators").append({
        "id": "c1", "business_id": "b1", "invited_email": "cpa@x.com",
        "role": "accountant", "status": "pending", "token": "tok1",
        "expiration_at": "2099-01-01T00:00:00+00:00"})
    out = bc.accept(bc.AcceptBody(token="tok1"),
                    type("U", (), {"id": "cpa9", "email": "cpa@x.com"})())
    assert out["ok"] is True
