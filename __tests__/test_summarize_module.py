"""
test_summarize_module.py — rows become answers.

Chief stored data beautifully and summarised none of it. A practitioner
with a Payments module could not ask "what am I owed, by stage" — the
data was right there and nothing counted it.

Deliberately arithmetic, not a model call: counting rows is not a
judgement, and routing it through an LLM would make a deterministic fact
cost money and vary between asks. So these tests assert exact numbers.
"""

import asyncio

import pytest

import chief_of_staff as cos

BIZ = {"id": "b1", "type": "consultant"}
MODULE = {
    "id": "22222222-2222-2222-2222-222222222222",
    "name": "Payments", "slug": "payments",
    "schema": {"fields": [
        {"name": "title", "type": "text", "label": "Title"},
        {"name": "status", "type": "select", "label": "Status",
         "options": ["draft", "sent", "paid", "overdue"]},
        {"name": "amount", "type": "currency", "label": "Amount"},
    ], "views": ["list"]},
    "agent_config": {},
}
ROWS = [
    {"data": {"title": "a", "status": "paid", "amount": 100}, "created_at": "2026-07-05T10:00:00Z"},
    {"data": {"title": "b", "status": "paid", "amount": 50.5}, "created_at": "2026-08-02T10:00:00Z"},
    {"data": {"title": "c", "status": "sent", "amount": 200}, "created_at": "2026-08-03T10:00:00Z"},
    {"data": {"title": "d", "status": "overdue", "amount": "75"}, "created_at": "2026-08-04T10:00:00Z"},
    {"data": {"title": "e", "amount": None}, "created_at": "2026-08-05T10:00:00Z"},
]


def _run(action, module=MODULE, rows=ROWS):
    async def fake_sb(client, method, path, body=None):
        if "custom_modules" in path:
            return [module] if module else []
        if "module_entries" in path:
            return rows
        return None

    orig = cos._sb
    cos._sb = fake_sb
    try:
        return asyncio.run(cos.handle_summarize_module(None, BIZ, action))
    finally:
        cos._sb = orig


def test_counts_and_totals_with_no_configuration():
    """A summary nobody had to configure is the one a practitioner asks
    for — it defaults to the first choice field and first money field."""
    out = _run({"module": "payments"})
    s = out["summary"]
    assert s["total_rows"] == 5
    assert s["group_by"] == "status" and s["sum_field"] == "amount"
    assert s["total"] == 425.5           # 100 + 50.5 + 200 + 75, None -> 0


def test_buckets_follow_the_options_order_not_the_data():
    """A summary should read in workflow order, not alphabetically or by
    whichever row happened to be entered first."""
    out = _run({"module": "payments"})
    keys = [b["key"] for b in out["summary"]["buckets"]]
    assert keys[:3] == ["sent", "paid", "overdue"], keys


def test_a_missing_group_value_is_named_not_dropped():
    """Row 'e' has no status. Silently omitting it would make the parts
    disagree with the total, which is how a report loses trust."""
    out = _run({"module": "payments"})
    buckets = {b["key"]: b for b in out["summary"]["buckets"]}
    assert buckets["(not set)"]["count"] == 1
    assert sum(b["count"] for b in out["summary"]["buckets"]) == 5


def test_a_string_amount_still_totals():
    """Row 'd' holds "75" as a string — real data written before the
    currency type existed. Coerce rather than crash or skip."""
    out = _run({"module": "payments"})
    assert out["summary"]["total"] == 425.5


def test_date_window_is_inclusive_on_both_ends():
    out = _run({"module": "payments", "since": "2026-08-02", "until": "2026-08-04"})
    assert out["summary"]["total_rows"] == 3
    assert out["summary"]["total"] == 325.5


def test_explicit_group_by_and_sum():
    out = _run({"module": "payments", "group_by": "status", "sum": "amount"})
    assert out["summary"]["group_by"] == "status"


def test_group_by_must_be_a_choice_field():
    out = _run({"module": "payments", "group_by": "amount"})
    assert "needs a select" in out["result"]


def test_sum_must_be_numeric():
    out = _run({"module": "payments", "sum": "title"})
    assert "needs a currency or number" in out["result"]


def test_an_unknown_field_is_named():
    out = _run({"module": "payments", "group_by": "nope"})
    assert "not a field" in out["result"]


def test_unknown_module_fails_clearly():
    out = _run({"module": "ghost"}, module=None)
    assert "no module called" in out["result"]


def test_an_empty_module_says_so_rather_than_reporting_zero():
    """"$0.00 total" over an unwired or empty module reads as a fact about
    the business. It is a fact about the absence of rows."""
    out = _run({"module": "payments"}, rows=[])
    assert "no rows yet" in out["result"]
    assert out["summary"]["total_rows"] == 0


def test_a_module_with_no_money_field_still_counts():
    mod = {**MODULE, "schema": {"fields": [
        {"name": "title", "type": "text", "label": "T"},
        {"name": "status", "type": "select", "label": "S", "options": ["open", "done"]},
    ], "views": ["list"]}}
    out = _run({"module": "payments"},
               module=mod,
               rows=[{"data": {"status": "open"}, "created_at": "2026-08-01T00:00:00Z"}])
    assert out["summary"]["total"] is None
    assert out["summary"]["total_rows"] == 1


def test_registered_classified_and_exposed():
    import action_registry
    import mcp_server

    assert "summarize_module" in cos.ACTION_HANDLERS
    assert action_registry.effect("summarize_module") == action_registry.READ
    # Safe on the agent surface: it exposes strictly less than
    # list_module_entries, which already returns these rows verbatim.
    assert "summarize_module" in mcp_server.exposed_tools()


def test_chief_is_told_it_exists():
    """A verb the prompt never names is a verb the model never emits."""
    class _Ctx(dict):
        def __missing__(self, k):
            return []

    p = cos._build_system_prompt(
        _Ctx(business={"id": "b1", "name": "T", "type": "coach",
                       "settings": {}, "voice_profile": {}}), False)
    assert "summarize_module" in p
