"""chief_bookkeeping tier gate (2026-08-22).

The feature has been ADVERTISED as Professional on the live plan cards
since the 8/18 offer pass, but none of its eleven routes enforced it —
the exact 7/30-audit class (a mapped feature with zero callers ships on
every plan). These tests pin the fix: the six intelligence routes gate,
and the resolution/read routes deliberately do NOT — a downgraded
practitioner must still see and resolve proposals Chief already made.
"""
from __future__ import annotations

import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from test_i2_gl_sync import FakeSB  # noqa: E402

import chief_bookkeeping  # noqa: E402
import chief_bookkeeping_router as cbr  # noqa: E402


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
    # The gate is what's under test — stub the engine behind it.
    monkeypatch.setattr(chief_bookkeeping, "analyze_unmatched", lambda b: [])
    monkeypatch.setattr(chief_bookkeeping, "analyze_uncategorized", lambda b: [])
    monkeypatch.setattr(chief_bookkeeping, "analyze_period_close", lambda b: [])
    monkeypatch.setattr(chief_bookkeeping, "analyze_gl", lambda b: [])
    monkeypatch.setattr(chief_bookkeeping, "list_proposals", lambda b, s=None: [])
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


_ANALYZERS = (cbr.analyze_unmatched, cbr.analyze_uncategorized,
              cbr.analyze_period_close, cbr.analyze_gl)


def test_dormant_gate_never_blocks(fake):
    """BILLING_ENFORCE off: a Starter business runs every analyzer."""
    _biz(fake, "b1", plan="price_starter")
    for route in _ANALYZERS:
        assert route("b1", _User())["ok"] is True


def test_starter_locked_out_of_the_analyzers(fake, monkeypatch):
    _biz(fake, "b1", plan="price_starter")
    _enforce(monkeypatch)
    for route in _ANALYZERS:
        with pytest.raises(HTTPException) as e:
            route("b1", _User())
        assert e.value.status_code == 402
        assert e.value.detail["feature"] == "chief_bookkeeping"
        assert e.value.detail["required_plan"] == "professional"


def test_professional_passes(fake, monkeypatch):
    _biz(fake, "b1", plan="price_professional")
    _enforce(monkeypatch)
    for route in _ANALYZERS:
        assert route("b1", _User())["ok"] is True


def test_resolution_routes_stay_open_on_starter(fake, monkeypatch):
    """A downgraded practitioner still SEES proposals Chief already made
    (and the counts nudge still answers) — data is never plan-locked."""
    _biz(fake, "b1", plan="price_starter")
    _enforce(monkeypatch)
    assert cbr.list_proposals("b1", None, _User())["ok"] is True
