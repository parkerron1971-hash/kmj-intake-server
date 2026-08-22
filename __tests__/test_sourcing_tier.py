"""SOURCING DESK — tier gate + honest metering (2026-08-22).

Two rulings pinned here:

1. Kevin 2026-08-22: the Sourcing Desk rides the hero tier (same
   AI-surface rule as site_concierge / agent_connector). New searches
   and RFQs are Professional+; landed vendors/quotes stay readable on
   every plan.

2. The metering fix. Every sourcing call was logged by the llm_call
   seam as `llm:sourcing_engine` with NO business_id — the platform's
   priciest per-call action could never draw down an allowance. Worse,
   claude-opus-5 was missing from MODEL_PRICING_CENTS, so cost booked
   at the Sonnet fallback (~40% under). Now the engine self-meters:
   /sourcing/search rows with the practitioner attached, the price on
   pass 1's marker row, pass 2 free (the marker carries the whole bill).
"""
from __future__ import annotations

import json
import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import llm_call  # noqa: E402
import sourcing_engine as se  # noqa: E402
import sourcing_router as sr  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


class _User:
    id = "owner1"


class _Resp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._payload


def _search_block(*urls):
    return {"type": "web_search_tool_result",
            "content": [{"type": "web_search_result", "url": u} for u in urls]}


def _text_block(t):
    return {"type": "text", "text": t}


# ─── The tier gate ───────────────────────────────────────────────────

@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sr.sb_clients, "sb_get_as_service", fb.get)
    for k in ("BILLING_ENFORCE", "STRIPE_PRICE_ID_STARTER",
              "STRIPE_PRICE_ID_PROFESSIONAL", "STRIPE_PRICE_ID_PRACTICE"):
        monkeypatch.delenv(k, raising=False)
    return fb


def _biz(fb, bid, *, plan=None, status="active"):
    fb.rows("businesses").append({
        "id": bid, "owner_id": "owner1", "is_active": True, "name": bid,
        "subscription_status": status if plan else None,
        "subscription_plan": plan, "comp_tier": None, "settings": {}})


def _enforce(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_professional")
    monkeypatch.setenv("STRIPE_PRICE_ID_PRACTICE", "price_practice")


class _Search:
    need = "blank hoodies"
    region = None
    qty = None
    budget_per_unit = None


def test_sourcing_desk_is_professional_plus():
    import feature_gates
    assert feature_gates.FEATURE_MIN_PLAN["sourcing_desk"] == "professional"


def test_starter_cannot_run_a_search(fake, monkeypatch):
    _biz(fake, "b1", plan="price_starter")
    _enforce(monkeypatch)
    with pytest.raises(HTTPException) as e:
        sr.run_search("b1", _Search(), _User())
    assert e.value.status_code == 402
    assert e.value.detail["feature"] == "sourcing_desk"
    assert e.value.detail["required_plan"] == "professional"


def test_professional_search_passes_the_gate(fake, monkeypatch):
    _biz(fake, "b1", plan="price_professional")
    _enforce(monkeypatch)
    monkeypatch.setattr(sr.billing_limits, "require_units", lambda b: None)
    monkeypatch.setattr(sr, "searches_today", lambda b: 0)
    seen = {}
    monkeypatch.setattr(sr.sourcing_engine, "search_vendors",
                        lambda **kw: seen.update(kw) or {
                            "candidates": [], "sources": [],
                            "coverage_note": "", "left_out": [],
                            "better_routes": [], "proposed_count": 0,
                            "dropped_count": 0, "model": "m"})
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": [dict(b, id="s1")])
    monkeypatch.setattr(sr.sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": [dict(b, id="s1")])
    out = sr.run_search("b1", _Search(), _User())
    assert out["ok"] is True
    # The engine is told WHO searched — attribution is the metering fix.
    assert seen["business_id"] == "b1"


def test_dormant_gate_never_blocks(fake, monkeypatch):
    """BILLING_ENFORCE off: today nothing changes for anyone."""
    _biz(fake, "b1", plan="price_starter")
    monkeypatch.setattr(sr.billing_limits, "require_units", lambda b: None)
    monkeypatch.setattr(sr, "searches_today", lambda b: 0)
    monkeypatch.setattr(sr.sourcing_engine, "search_vendors",
                        lambda **kw: {"candidates": [], "sources": [],
                                      "coverage_note": "", "left_out": [],
                                      "better_routes": [], "proposed_count": 0,
                                      "dropped_count": 0, "model": "m"})
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": [dict(b, id="s1")])
    monkeypatch.setattr(sr.sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": [dict(b, id="s1")])
    assert sr.run_search("b1", _Search(), _User())["ok"] is True


# ─── Honest metering ─────────────────────────────────────────────────

def _fake_two_pass(monkeypatch):
    calls = []

    def fake_post(payload, **kw):
        calls.append(payload)
        if len(calls) == 1:
            return _Resp({"model": "claude-opus-5",
                          "usage": {"input_tokens": 1000, "output_tokens": 500},
                          "content": [_text_block("notes"),
                                      _search_block("https://northwind.com/w")]})
        return _Resp({"model": "claude-opus-5",
                      "usage": {"input_tokens": 800, "output_tokens": 200},
                      "content": [_text_block(json.dumps({
                          "candidates": [], "coverage_note": "ok"}))]})

    monkeypatch.setattr(llm_call, "post", fake_post)
    return calls


def test_search_writes_attributed_marker_rows(monkeypatch):
    rows = []
    import api_usage_logger

    def capture(**kw):
        rows.append(kw)

    monkeypatch.setattr(api_usage_logger, "log_api_usage_sync", capture)
    _fake_two_pass(monkeypatch)
    se.search_vendors(need="blank hoodies", business_id="b1")

    assert len(rows) == 2, "both passes meter"
    p1, p2 = rows
    for r in (p1, p2):
        assert r["endpoint"] == "/sourcing/search"
        assert r["business_id"] == "b1"
        assert r["model"] == "claude-opus-5"
    import pricing_config
    assert p1["units"] == pricing_config.sourcing_search(), \
        "pass 1 is the marker row — it carries the whole bill"
    assert p2["units"] == 0, "pass 2 is free — no double billing"


def test_the_seam_no_longer_double_meters_sourcing():
    """sourcing_engine self-meters now, so the llm_call seam must skip
    it — otherwise every search is counted twice and the spend brake
    trips early."""
    assert "sourcing_engine" in llm_call._SELF_METERING


def test_opus_5_books_at_opus_rates_not_the_sonnet_fallback():
    """The booking error behind the mispriced first ruling: claude-opus-5
    was absent from MODEL_PRICING_CENTS and fell to Sonnet pricing,
    under-booking every sourcing call ~40%."""
    import api_usage_logger
    assert api_usage_logger._price_for_model("claude-opus-5") == (500.0, 2500.0)


def test_the_price_is_a_dial(monkeypatch):
    import importlib
    import pricing_config
    monkeypatch.setenv("PRICE_SOURCING_SEARCH", "77")
    importlib.reload(pricing_config)
    try:
        assert pricing_config.sourcing_search() == 77
        assert pricing_config.unit_weights()["/sourcing/search"] == 77
    finally:
        monkeypatch.delenv("PRICE_SOURCING_SEARCH", raising=False)
        importlib.reload(pricing_config)
