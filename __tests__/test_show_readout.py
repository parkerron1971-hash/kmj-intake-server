"""show_readout — several blocks as one artifact.

show_view answers one question with one shape. "How is the month going"
is not one question: it wants the headline, the shape over time, and
the rows behind it. Asking three times gets three cards the
practitioner has to hold in their head at once.

The design rule that matters here is that this is a CONTAINER over
handle_show_view, not a second resolver. Every block is literally a
show_view call, so a block can only ever contain what that verb would
have returned alone — same authorship, same filters, same limits — and
a view added to _SHOW_VIEW_SPECS works here the same day. A parallel
resolver would be a second place for the rules to drift.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from __tests__._chief_source import chief_source  # noqa: E402
import pytest

import chief_of_staff as cos

_BIZ = {"id": "biz-1", "name": "KMJ", "type": "coach", "owner_id": "user-1", "settings": {}}

_ROWS = [
    {"id": "i1", "invoice_number": "INV-1", "total": 520, "status": "overdue",
     "due_date": "2026-06-23", "contact_id": "c1", "contacts": {"name": "Marcus"}},
    {"id": "i2", "invoice_number": "INV-2", "total": 380, "status": "sent",
     "due_date": "2026-06-30", "contact_id": "c2", "contacts": {"name": "Sandra"}},
]


@pytest.fixture
def db(monkeypatch):
    calls = []

    async def sb(client, method, path, body=None):
        calls.append(path)
        return list(_ROWS)

    monkeypatch.setattr(cos, "_sb", sb)
    return calls


def _readout(action):
    return asyncio.run(cos.handle_show_readout(None, _BIZ, action))


def test_blocks_come_back_in_the_order_asked_for():
    pass  # covered below with the db fixture


def test_a_readout_draws_every_block(db):
    r = _readout({"type": "show_readout", "title": "How the month is running", "blocks": [
        {"view": "invoices", "filter": "open", "form": "chart", "group_by": "status"},
        {"view": "invoices", "filter": "overdue", "form": "list"},
    ]})
    assert r["type"] == "show_readout"
    assert r.get("result") and r.get("label"), "the house contract"
    assert r["title"] == "How the month is running"
    assert len(r["blocks"]) == 2
    assert r["blocks"][0]["form"] == "chart" and r["blocks"][0]["series"]
    assert r["blocks"][1]["form"] == "list"


def test_every_block_is_a_show_view_call_not_a_second_resolver(db):
    """If a block ever stops going through handle_show_view, the filters,
    the 25-row cap and the server-authored cells become two codebases."""
    _readout({"type": "show_readout", "blocks": [
        {"view": "invoices", "filter": "overdue"},
        {"view": "contacts", "filter": "leads"},
    ]})
    assert any("/invoices?" in q for q in db)
    assert any("/contacts?" in q for q in db)


def test_a_failed_block_stays_in_the_payload_marked(monkeypatch):
    """Dropping it would leave a readout that LOOKS complete. The result
    the model reads must also say so, or Chief narrates a whole picture
    over a missing piece."""
    async def sb(client, method, path, body=None):
        if "/contacts" in path:
            return None          # a refused read, not an empty one
        return list(_ROWS)
    monkeypatch.setattr(cos, "_sb", sb)

    r = _readout({"type": "show_readout", "blocks": [
        {"view": "invoices"}, {"view": "contacts"},
    ]})
    kinds = [b.get("kind") or b.get("type") for b in r["blocks"]]
    assert "failed" in kinds, kinds
    assert len(r["blocks"]) == 2, "the failed block is kept, not dropped"
    assert "COULD NOT LOAD" in r["speak"]
    assert "missing" in r["result"].lower()


def test_the_block_cap_holds(db):
    r = _readout({"type": "show_readout",
                  "blocks": [{"view": "invoices"} for _ in range(9)]})
    assert len(r["blocks"]) == cos._READOUT_MAX_BLOCKS


def test_an_empty_readout_fails_rather_than_drawing_a_frame(db):
    for bad in ({}, {"blocks": []}, {"blocks": "invoices"}):
        r = _readout({"type": "show_readout", **bad})
        assert r.get("failed") or "fail" in str(r).lower(), bad


def test_a_readout_of_unknown_views_fails(monkeypatch):
    async def sb(client, method, path, body=None):
        return []
    monkeypatch.setattr(cos, "_sb", sb)
    r = _readout({"type": "show_readout", "blocks": [{"view": "unicorns"}]})
    # Every block failed, so the readout is a failure — not an empty frame.
    assert r["blocks"][0].get("kind") == "failed"


def test_the_note_is_marked_as_chiefs_own_words(db):
    r = _readout({"type": "show_readout", "blocks": [{"view": "invoices"}],
                  "note": "Week four carried the month."})
    assert r["note"] == "Week four carried the month."
    assert r["authored_note"] == "chief"


def test_no_note_means_no_attribution_field(db):
    r = _readout({"type": "show_readout", "blocks": [{"view": "invoices"}]})
    assert r["note"] is None and r["authored_note"] is None


def test_one_digest_feeds_the_spoken_reply(db):
    """What Chief SAYS and what the practitioner SEES must come from the
    same numbers — the seam every display verb here uses."""
    r = _readout({"type": "show_readout", "blocks": [
        {"view": "invoices", "filter": "overdue"},
    ]})
    assert "Marcus" in r["speak"] or "520" in r["speak"]


def test_it_is_registered_as_UI_and_never_offered_off_app():
    import action_registry, mcp_server
    assert "show_readout" in cos.ACTION_HANDLERS
    assert action_registry.REGISTRY["show_readout"]["effect"] == action_registry.UI
    assert "show_readout" not in {t["name"] for t in mcp_server.tool_definitions()}


def test_the_prompt_documents_it_and_the_missing_block_rule():
    import inspect
    src = chief_source()
    assert '"type":"show_readout"' in src
    assert "SAY WHICH PART IS MISSING" in src
