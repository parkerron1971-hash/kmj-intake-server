"""The columns these routers ASK FOR have to exist.

WHY THIS FILE EXISTS
  `_owner()` asked PostgREST for `businesses.industry`. There is no such
  column on this schema — it is `type`. PostgREST answers an unknown
  column with a 400, sb_clients turns any 4xx into None, and the callers'
  `or []` turned that into "business not found". Every owner-gated
  sourcing endpoint 404'd: the vendor search, both RFQ endpoints, and
  turning vendor sharing ON.

  Nothing caught it. Every other test in this arc stubs
  sb_get_as_service with a function that answers ANY `/businesses` path
  with a row, no matter which columns were requested — so the wrong
  query and the right query were indistinguishable. A mock that answers
  everything cannot fail on a bad question.

  So these stubs are STRICT: they parse the select= clause and behave
  exactly like PostgREST does when a column is unknown — they return
  None. A test using them fails on the query, not just on the answer.

  The column lists below were read from production information_schema
  on 2026-08-21. If a migration adds one, add it here; that is the
  intended maintenance and it is cheaper than an outage.
"""
from __future__ import annotations

import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import HTTPException

import sb_clients
import sourcing_router as sr
import suppliers_router as supr

# public.businesses, production, 2026-08-21. Note: `type` — NOT `industry`.
BUSINESS_COLUMNS = {
    "brand_kit_history", "cancel_at_period_end", "cdi_vocabulary", "comp_tier",
    "created_at", "current_period_end", "entity_group_id", "id", "in_the_clear",
    "in_the_clear_at", "is_active", "name", "owner_id", "settings",
    "stripe_account_id", "stripe_customer_id", "stripe_subscription_id",
    "subscription_plan", "subscription_status", "tier", "trial_ends_at", "type",
    "updated_at", "use_composer", "voice_profile",
}

BIZ = "biz1"
ROW = {"id": BIZ, "owner_id": "owner", "name": "Kev's", "type": "agency"}


class _U:
    id = "owner"


def _select_of(path: str):
    m = re.search(r"[?&]select=([^&]+)", path)
    if not m:
        return None
    return [c.strip() for c in m.group(1).split(",") if c.strip()]


def strict_get(path: str):
    """Answers /businesses the way PostgREST really does: None (a 400) when
    the select names a column that does not exist."""
    if path.startswith("/businesses"):
        cols = _select_of(path)
        if cols and cols != ["*"]:
            unknown = [c for c in cols if c not in BUSINESS_COLUMNS]
            if unknown:
                return None      # PostgREST 400 -> sb_clients returns None
        return [ROW]
    return []


# ─── The paths that were broken ──────────────────────────────────────

def test_owner_lookup_asks_only_for_columns_that_exist(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", strict_get)
    row = sr._owner(BIZ, _U())
    assert row["id"] == BIZ


def test_reader_lookup_asks_only_for_columns_that_exist(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", strict_get)
    assert sr._reader(BIZ, _U())["id"] == BIZ


def test_the_suppliers_router_lookups_are_clean_too(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", strict_get)
    assert supr._owner(BIZ, _U())["id"] == BIZ
    assert supr._reader(BIZ, _U())["id"] == BIZ


def test_turning_vendor_sharing_ON_survives_the_owner_lookup(monkeypatch):
    """The exact reported symptom: the toggle 404'd because _owner did."""
    def _get(path):
        if path.startswith("/vendor_sharing_consent"):
            return []
        return strict_get(path)

    posts = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, **kw: posts.append((p, b)) or [b])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: b)

    out = sr.set_sharing(BIZ, sr.SharingBody(sharing=True), user=_U())
    assert out["sharing"] is True
    assert any("vendor_sharing_consent" in p for p, _ in posts)


def test_running_a_search_survives_the_owner_lookup(monkeypatch):
    """The other reported symptom."""
    def _get(path):
        if path.startswith("/sourcing_searches"):
            return []
        if path.startswith("/offerings"):
            return [{"name": "Shop Hoodie"}]
        return strict_get(path)

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, **kw: [b])
    monkeypatch.setattr(sr.billing_limits, "require_units", lambda biz: None)
    monkeypatch.setattr(sr.sourcing_engine, "search_vendors", lambda **kw: {
        "candidates": [], "sources": [], "coverage_note": "n",
        "proposed_count": 0, "dropped_count": 0, "model": "m"})

    out = sr.run_search(BIZ, sr.SearchBody(need="blank hoodies"), user=_U())
    assert out["ok"] is True


# ─── The trade line reads as a sentence ──────────────────────────────

def test_the_trade_reaches_the_prompt_and_reads_like_words(monkeypatch):
    """`type` holds keys like "personal_services". A prompt that says "a
    personal_services business" is a prompt written by a database."""
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path: [] if path.startswith("/offerings")
                        else strict_get(path))
    ctx = sr._business_context({"name": "Kev's", "type": "personal_services"}, BIZ)
    assert "personal services business" in ctx
    assert "_" not in ctx


def test_a_business_with_no_trade_on_file_still_produces_context(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path: [] if path.startswith("/offerings")
                        else strict_get(path))
    ctx = sr._business_context({"name": "Kev's", "type": None}, BIZ)
    assert "Kev's" in ctx
    assert "business" not in ctx.replace("Kev's", "")


# ─── A genuinely missing business still 404s ─────────────────────────

def test_a_business_that_really_is_missing_still_404s(monkeypatch):
    """The fix must not paper over the case the 404 was meant for."""
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [])
    with pytest.raises(HTTPException) as e:
        sr._owner(BIZ, _U())
    assert e.value.status_code == 404
