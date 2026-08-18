"""
test_show_view.py — Chief can SHOW a list, not just narrate around one.

Kevin's 8/14 transcript, asking about his own invoices:

    "I don't have the individual invoice breakdown loaded here, just the
    totals ... let me take you to the actual screen."

Two fixes live here and both are pinned:

  1. show_view — a read verb that fetches rows server-side and returns
     them as typed columns+rows for an in-chat table card, plus a
     `speak` digest so the second-pass reply can SAY the real values.
  2. Itemized open invoices in _gather_context — so even without the
     card, "who owes what?" is answerable from the prompt and the
     web_search reach (the exact class fixed for projects on 8/01)
     has nothing to reach for.

The trust properties, mapped to the four-question standard:
  (b) the action returns type/result/label + columns/rows/summary/speak,
      honest on empty and honest on refused reads;
  (c) the second pass sees the row values through `speak` — asserted
      against _format_action_results_for_reply, not assumed;
  (d) unknown views fail listing the valid set; a refused read (RLS,
      outage) FAILS rather than rendering as "you have no invoices".
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_of_staff as cos


_BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "type": "coach",
        "owner_id": "user-1", "settings": {}}

_INVOICE_ROWS = [
    {"id": "inv-1", "invoice_number": "INV-2026-005", "total": 520,
     "status": "overdue", "due_date": "2026-06-23",
     "contact_id": "c-1", "contacts": {"name": "Marcus Webb"}},
    {"id": "inv-2", "invoice_number": "INV-2026-006", "total": 380.50,
     "status": "sent", "due_date": "2026-06-30",
     "contact_id": "c-2", "contacts": {"name": "Sandra Ellis"}},
    {"id": "inv-3", "invoice_number": "INV-2026-007", "total": 964.50,
     "status": "viewed", "due_date": "2026-07-02",
     "contact_id": "c-3", "contacts": {"name": "Dana Cole"}},
]


class _DB:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.queries = []

    async def sb(self, client, method, path, body=None):
        self.queries.append((method, path))
        return self.rows


def _show(action, db):
    return asyncio.run(cos.handle_show_view(None, _BIZ, action))


@pytest.fixture
def db(monkeypatch):
    d = _DB(list(_INVOICE_ROWS))
    monkeypatch.setattr(cos, "_sb", d.sb)
    return d


# ─────────────────────────────────────────────────────────────────────
# The rows reach the card
# ─────────────────────────────────────────────────────────────────────

def test_invoices_return_typed_columns_and_rows(db):
    r = _show({"type": "show_view", "view": "invoices"}, db)
    assert r["type"] == "show_view"
    assert r.get("result") and r.get("label"), "the house contract"
    assert [c["key"] for c in r["columns"]] == ["number", "client", "amount", "status", "due"]
    assert len(r["rows"]) == 3
    assert r["rows"][0] == {"id": "inv-1", "number": "INV-2026-005",
                            "client": "Marcus Webb", "amount": 520.0,
                            "status": "overdue", "due": "2026-06-23"}


def test_the_total_is_summed_from_the_rows_not_the_model(db):
    r = _show({"type": "show_view", "view": "invoices"}, db)
    assert r["summary"] == {"count": 3, "total": 1865.0}
    assert "$1,865.00" in r["label"]


def test_the_query_is_scoped_to_the_business(db):
    _show({"type": "show_view", "view": "invoices"}, db)
    method, path = db.queries[0]
    assert method == "GET"
    assert "business_id=eq.biz-1" in path
    assert "limit=25" in path, "bounded — a card, not an export"


def test_filters_shape_the_query(db):
    _show({"type": "show_view", "view": "invoices", "filter": "paid"}, db)
    assert "status=eq.paid" in db.queries[0][1]
    _show({"type": "show_view", "view": "invoices", "filter": "nonsense"}, db)
    assert "status=in.(sent,viewed,overdue)" in db.queries[1][1], (
        "an unknown filter falls back to the view default, never to 'all'"
    )


def test_overdue_filter_uses_z_form_dates(db):
    _show({"type": "show_view", "view": "sessions", "filter": "upcoming"}, db)
    path = db.queries[0][1]
    assert "+00:00" not in path, (
        "PostgREST timestamp class: isoformat +00:00 in a query string "
        "returns silent empties — Z form ALWAYS"
    )


@pytest.mark.parametrize("view", ["invoices", "contacts", "sessions", "products"])
def test_every_view_serves_rows(view, monkeypatch):
    rows_by_view = {
        "invoices": _INVOICE_ROWS,
        "contacts": [{"id": "c-1", "name": "Marcus Webb", "status": "lead",
                      "health_score": 61, "last_interaction": "2026-08-01"}],
        "sessions": [{"id": "s-1", "title": "Strategy call", "status": "scheduled",
                      "scheduled_for": "2026-08-20T14:00:00Z",
                      "contacts": {"name": "Dana Cole"}}],
        "products": [{"id": "p-1", "name": "Coaching block", "type": "service",
                      "price": 500, "pricing_type": "flat"}],
    }
    d = _DB(rows_by_view[view])
    monkeypatch.setattr(cos, "_sb", d.sb)
    r = _show({"type": "show_view", "view": view}, d)
    assert not cos._action_failed(r)
    assert len(r["rows"]) == len(rows_by_view[view])
    keys = {c["key"] for c in r["columns"]}
    for row in r["rows"]:
        assert keys <= set(row), f"{view} row missing declared columns"


# ─────────────────────────────────────────────────────────────────────
# The second pass can SAY the values
# ─────────────────────────────────────────────────────────────────────

def test_speak_carries_the_real_values(db):
    r = _show({"type": "show_view", "view": "invoices"}, db)
    assert "Marcus Webb $520.00" in r["speak"]
    assert "overdue" in r["speak"]


def test_the_reply_composer_forwards_the_speak_digest(db):
    r = _show({"type": "show_view", "view": "invoices"}, db)
    block = cos._format_action_results_for_reply([r])
    assert "Marcus Webb $520.00" in block, (
        "the second-pass prompt must carry the row values — without this "
        "Chief renders a card it cannot talk about"
    )


def test_speak_is_capped_not_a_dump(monkeypatch):
    rows = [dict(_INVOICE_ROWS[0], id=f"inv-{i}", invoice_number=f"INV-{i:03d}")
            for i in range(25)]
    d = _DB(rows)
    monkeypatch.setattr(cos, "_sb", d.sb)
    r = _show({"type": "show_view", "view": "invoices"}, d)
    assert "and 17 more" in r["speak"]
    assert len(r["speak"]) < 1200, "a digest, not a table dump into the prompt"


# ─────────────────────────────────────────────────────────────────────
# Honest failure modes
# ─────────────────────────────────────────────────────────────────────

def test_an_unknown_view_fails_and_names_the_valid_ones(db):
    r = _show({"type": "show_view", "view": "unicorns"}, db)
    assert cos._action_failed(r)
    for v in ("invoices", "contacts", "sessions", "products"):
        assert v in r["result"]
    assert not db.queries, "a rejected view must not query anything"


def test_an_empty_view_is_reported_empty_not_invented(monkeypatch):
    d = _DB([])
    monkeypatch.setattr(cos, "_sb", d.sb)
    r = _show({"type": "show_view", "view": "invoices"}, d)
    assert not cos._action_failed(r)
    assert r["rows"] == [] and r["summary"]["count"] == 0
    assert "do NOT invent rows" in r["result"], (
        "the second pass needs the explicit instruction, or the optimistic "
        "first-pass narration survives over an empty table"
    )


def test_a_refused_read_is_a_failure_not_an_empty_list(monkeypatch):
    """_sb returns None on a 4xx/RLS refusal/outage. Presenting that as
    'you have no invoices' would be an empty state that lies."""
    async def _none(*a, **k):
        return None
    monkeypatch.setattr(cos, "_sb", _none)
    r = _show({"type": "show_view", "view": "invoices"}, None)
    assert cos._action_failed(r)


# ─────────────────────────────────────────────────────────────────────
# The context fix — who-owes-what is in the prompt itself
# ─────────────────────────────────────────────────────────────────────

def test_open_invoices_render_itemized_into_the_prompt():
    ctx = {
        "business": _BIZ, "contacts_total": 17,
        "contacts_by_status": {}, "avg_health": 61, "at_risk": [],
        "queue": [], "sessions": [], "insights": [], "modules": [],
        "events": [], "memories": [], "notifications": [],
        "recent_queue_24h": [], "projects": [], "products": [],
        "contacts_lookup": [], "site": None, "strategy_track": None,
        "business_track": None, "email_replies": [], "sms_messages": [],
        "open_invoices": [
            {"id": "inv-1", "number": "INV-2026-005", "client": "Marcus Webb",
             "total": 520.0, "status": "overdue", "due_date": "2026-06-23"},
        ],
    }
    block = cos._format_context_for_prompt(ctx)
    assert "OPEN INVOICES" in block
    assert "INV-2026-005 · Marcus Webb · $520.00" in block
    assert "never say you don't have the breakdown" in block, (
        "the sentence is the fix — the projects block earned the same one "
        "on 8/01 for the same web_search reach"
    )


def test_no_open_invoices_says_none_open():
    ctx = {
        "business": _BIZ, "contacts_total": 0,
        "contacts_by_status": {}, "avg_health": 0, "at_risk": [],
        "queue": [], "sessions": [], "insights": [], "modules": [],
        "events": [], "memories": [], "notifications": [],
        "recent_queue_24h": [], "projects": [], "products": [],
        "contacts_lookup": [], "site": None, "strategy_track": None,
        "business_track": None, "email_replies": [], "sms_messages": [],
        "open_invoices": [],
    }
    assert "(none open)" in cos._format_context_for_prompt(ctx)


# ─────────────────────────────────────────────────────────────────────
# The prompt is the capability surface
# ─────────────────────────────────────────────────────────────────────

def test_the_prompt_documents_the_verb():
    """A word the prompt never says is a word Chief doesn't have — the
    handler alone ships nothing."""
    src = pathlib.Path(cos.__file__).read_text(encoding="utf-8")
    assert '"type":"show_view"' in src.replace(" ", "").replace("{{", "{"), \
        "show_view is not documented in the system prompt"
    assert "never answer \"I don't have the breakdown\"" in src or \
           "NEVER say \"I don't have the itemized breakdown\"" in src


# ─────────────────────────────────────────────────────────────────────
# The FORM the practitioner asked for (2026-08-18)
#
# Kevin: "I specifically asked, can you create a timeline from my first
# invoice to my most recent invoice ... it brought it back in a list
# which wasn't bad but it just didn't do the web form that I asked."
#
# That was not Chief weighing options and picking the safe one. A table
# was the only shape this handler could produce, so every named form
# collapsed into it. `form` gives the request somewhere to land.
# ─────────────────────────────────────────────────────────────────────

def test_a_list_is_still_the_default(db):
    r = _show({"type": "show_view", "view": "invoices"}, db)
    assert r["form"] == "list", "no form named = the table everyone already gets"


def test_a_requested_timeline_comes_back_as_a_timeline(db):
    r = _show({"type": "show_view", "view": "invoices", "form": "timeline"}, db)
    assert r["form"] == "timeline"
    # The client needs to know which column is the axis, and it must be
    # a column the reader can actually see — no hidden sort key.
    assert r["date_key"] == "due"
    assert any(c["key"] == r["date_key"] and c["kind"] == "date" for c in r["columns"])


def test_a_timeline_is_ordered_chronologically_not_by_the_list_default(db):
    """"From my first to my most recent" is a chronological question, and
    a list's default order is usually something else entirely.

    Deliberately tested on CONTACTS, not invoices: the invoices list is
    already ordered by due_date.asc, so asserting the timeline order
    there would pass whether or not the override existed — a test that
    cannot fail is not a test."""
    db.queries.clear()
    _show({"type": "show_view", "view": "contacts"}, db)
    assert "order=health_score.desc" in db.queries[-1][1], "the list default"

    db.queries.clear()
    _show({"type": "show_view", "view": "contacts", "form": "timeline"}, db)
    q = db.queries[-1][1]
    assert "order=last_interaction.asc" in q, q
    assert "health_score" not in q.split("order=")[1], "the list order must be replaced, not appended"


def test_the_rows_are_identical_whatever_the_form(db):
    """The form is a drawing instruction. It must never change what the
    server authored, or the shape becomes a second source of truth."""
    as_list = _show({"type": "show_view", "view": "invoices"}, db)
    as_time = _show({"type": "show_view", "view": "invoices", "form": "timeline"}, db)
    assert as_list["columns"] == as_time["columns"]
    assert sorted(r["id"] for r in as_list["rows"]) == sorted(r["id"] for r in as_time["rows"])
    assert as_list["summary"] == as_time["summary"]


def test_an_unknown_form_fails_naming_the_valid_ones(db):
    r = _show({"type": "show_view", "view": "invoices", "form": "hologram"}, db)
    assert r.get("success") is False or "error" in r or "failed" in str(r).lower()
    assert "timeline" in str(r) and "list" in str(r)


def test_a_view_with_no_date_refuses_the_timeline_instead_of_serving_a_list(db):
    """Products have no date to lay a timeline along. Silently serving a
    table is exactly the substitution this change exists to stop."""
    r = _show({"type": "show_view", "view": "products", "form": "timeline"}, db)
    assert r.get("form") != "timeline"
    assert "timeline" in str(r).lower()


def test_the_prompt_documents_the_form_and_forbids_substituting(db):
    """The prompt is the capability surface: a parameter the prompt never
    mentions is a parameter the model never sends."""
    import inspect
    src = inspect.getsource(cos)
    assert '"form":"list|timeline"' in src
    assert "WHEN THE PRACTITIONER NAMES A FORM, USE THAT FORM" in src
