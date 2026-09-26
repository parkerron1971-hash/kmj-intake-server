"""
test_no_profile_yet_is_not_a_failure.py — a new practitioner with no profile yet isn't a failed read (2026-09-26).

_gather_context's _soft() records "A secondary context source is
unavailable; do not infer absence." whenever a source returns None.
practitioner_profile_agent.get_profile returned None when no
practitioner_profiles row exists, and a practitioner who signed up today
has none. So every prompt from their first turn carried a false
"unavailable" line (the new-business turn eval saw it).
business_profile_agent.get_profile had the same shape.

Both reads now say {} for "read fine, no row" when the caller asks
(empty_if_missing=True) and None only when the read failed. _gather_context
asks, so a new business gets no unavailable line and a real failure still
gets one. The other _soft sources (foundation, business profile block,
maturity, growth, brand, playbook, semantic match, blueprint,
practitioner and voice blocks) already answer "" or [] for no row; the
day-one test runs them for real against empty tables so a future None
shows up here.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import business_profile_agent
import chief_of_staff as cos
import practitioner_profile_agent

UNAVAILABLE = "A secondary context source is unavailable; do not infer absence."
FAILED = "A secondary context source failed; do not infer absence."

_BIZ = {"id": "biz-new", "name": "Fade Street Barbers", "type": "personal_services",
        "owner_id": "owner-new", "settings": {}, "created_at": "2026-09-26T12:00:00Z"}


# ── the reads ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("agent,seam,key", [
    (practitioner_profile_agent, "_sb_get", "owner-new"),
    (business_profile_agent, "_sb_get", "biz-new"),
])
def test_no_row_is_an_empty_profile_and_a_failed_read_is_none(monkeypatch, agent, seam, key):
    monkeypatch.setattr(agent, seam, lambda path: [])
    assert agent.get_profile(key, empty_if_missing=True) == {}
    # Every other caller keeps the old answer.
    assert agent.get_profile(key) is None

    monkeypatch.setattr(agent, seam, lambda path: None)
    assert agent.get_profile(key, empty_if_missing=True) is None
    assert agent.get_profile(key) is None

    row = {"owner_id": key, "business_id": key, "timezone": "America/Detroit"}
    monkeypatch.setattr(agent, seam, lambda path: [row])
    assert agent.get_profile(key, empty_if_missing=True) == row
    assert agent.get_profile(key) == row


# ── the context a turn is built from ─────────────────────────────────

@pytest.fixture
def day_one(monkeypatch):
    """The real _gather_context and the real context blocks, against a
    business that signed up today: its business row and no other rows
    anywhere. Returns run() -> the context's unavailable lines."""
    import chief_memory_semantic
    import foundation_agent
    import sb_clients
    import voice_depth_agent

    # No URL, so nothing can reach a network; a key, so the blocks that
    # build service headers get as far as reading their (empty) tables.
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")

    async def _sb(client, method, path, body=None):
        return [dict(_BIZ)] if path.startswith("/businesses") else []

    async def _count(client, path):
        return 0

    async def _foundation_get(client, path):
        return []

    monkeypatch.setattr(cos, "_sb", _sb)
    monkeypatch.setattr(cos, "_sb_count", _count)
    for name in ("sb_get_as_service", "sb_get_current_context", "sb_get_as_user",
                 "sb_get_as_anon"):
        monkeypatch.setattr(sb_clients, name, lambda *a, **k: [])
    for name in ("sb_patch_as_service", "sb_post_as_service", "sb_patch_current_context",
                 "sb_post_current_context"):
        monkeypatch.setattr(sb_clients, name, lambda *a, **k: None)
    monkeypatch.setattr(practitioner_profile_agent, "_sb_get", lambda path: [])
    monkeypatch.setattr(business_profile_agent, "_sb_get", lambda path: [])
    monkeypatch.setattr(voice_depth_agent, "_sb_get", lambda path: [])
    monkeypatch.setattr(foundation_agent, "_sb_get", _foundation_get)
    monkeypatch.setattr(chief_memory_semantic, "match", lambda *a, **k: [])

    def run():
        ctx = asyncio.run(cos._gather_context(None, _BIZ["id"], query_text="Where should I start?"))
        assert ctx.get("business"), "the gather itself must succeed"
        return ctx, (ctx.get("context_quality") or {}).get("unavailable") or []
    return run


def test_a_new_business_with_no_rows_has_no_unavailable_line(day_one):
    ctx, unavailable = day_one()
    assert UNAVAILABLE not in unavailable, unavailable
    assert FAILED not in unavailable, unavailable
    assert ctx["practitioner_profile_raw"] == {}
    assert ctx["business_profile_raw"] == {}


@pytest.mark.parametrize("agent", [practitioner_profile_agent, business_profile_agent])
def test_a_failed_profile_read_still_says_unavailable(day_one, monkeypatch, agent):
    monkeypatch.setattr(agent, "_sb_get", lambda path: None)
    _, unavailable = day_one()
    assert UNAVAILABLE in unavailable, unavailable


@pytest.mark.parametrize("agent", [practitioner_profile_agent, business_profile_agent])
def test_a_profile_read_that_raises_still_says_it_failed(day_one, monkeypatch, agent):
    def boom(path):
        raise RuntimeError("PostgREST is down")
    monkeypatch.setattr(agent, "_sb_get", boom)
    _, unavailable = day_one()
    assert FAILED in unavailable, unavailable


def test_a_practitioner_with_a_profile_is_read_as_one(day_one, monkeypatch):
    row = {"owner_id": "owner-new", "timezone": "America/Detroit", "preferred_title": "Barber"}
    monkeypatch.setattr(practitioner_profile_agent, "_sb_get", lambda path: [row])
    ctx, unavailable = day_one()
    assert ctx["practitioner_profile_raw"] == row
    assert UNAVAILABLE not in unavailable
