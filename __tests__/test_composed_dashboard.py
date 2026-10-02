"""
test_composed_dashboard.py — the seventh archetype: a log with a front page.

The everything-else shape. An expense log, a workout log, a sales log —
rows that pile up, whose real question is what they add up to. Before
this every one of them rendered as the generic table. The model now
assembles a front page from a closed catalog of blocks bound to the
module's own fields; the surface draws them.

What has to hold:
  1. Registered everywhere (enum test covers parity); the params contract
     refuses a block that cannot be drawn — a series over text, a
     breakdown by a number, a progress with no target.
  2. The prompt teaches every block kind, and the skill fires on the
     words a practitioner uses for a log.
  3. build_quality knows the shape, so a log on the plain list is a
     finding the builder revises.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import build_quality as bq
import build_skills as bs
import module_spec_generator as msg


def _fields():
    return [
        {"name": "vendor", "type": "text", "label": "Vendor", "required": True},
        {"name": "amount", "type": "currency", "label": "Amount", "required": True},
        {"name": "spent_on", "type": "date", "label": "Spent on", "required": True},
        {"name": "category", "type": "select", "label": "Category",
         "options": ["Software", "Travel", "Supplies", "Other"]},
        {"name": "notes", "type": "textarea", "label": "Notes"},
    ]


BLOCKS = [
    {"kind": "stat", "agg": "sum", "field": "amount", "window": "month", "label": "Spent this month"},
    {"kind": "stat", "agg": "count", "window": "7d", "label": "This week"},
    {"kind": "series", "field": "amount", "agg": "sum", "bucket": "month", "label": "By month"},
    {"kind": "breakdown", "field": "category", "agg": "sum", "fields": ["amount"], "label": "Where it goes"},
    {"kind": "progress", "field": "amount", "target": 2000, "window": "month", "direction": "down", "label": "Budget"},
    {"kind": "recent", "limit": 5, "fields": ["spent_on", "vendor", "amount"]},
    {"kind": "notes", "field": "notes", "limit": 3},
]


def _dash(blocks=None, **params):
    base = {"blocks": blocks if blocks is not None else BLOCKS,
            "date_field": "spent_on", "title_field": "vendor", "item_noun": "Expense"}
    base.update(params)
    return {
        "slug": "expenses", "name": "Expenses", "description": "Business expenses",
        "intake_excerpt": "log my expenses", "reasoning": "a log with a front page",
        "archetype": "composed_dashboard", "archetype_params": base,
        "schema": {"fields": _fields(), "views": ["list", "summary"], "default_view": "list"},
        "presentation": {"empty_line": "Log the first expense and the month starts adding up."},
    }


# ─── 1. registered, and the params contract ──────────────────────────

def test_registered_everywhere():
    assert "composed_dashboard" in msg.ARCHETYPE_METADATA
    assert "composed_dashboard" in msg._ARCHETYPE_PARAM_MODELS
    assert "composed_dashboard" in msg.suggestable_archetypes()
    assert "composed_dashboard" not in msg._SINGLE_INSTANCE_ARCHETYPES
    assert msg.ARCHETYPE_METADATA["composed_dashboard"].get("pitch")


def test_a_good_dashboard_validates():
    spec = msg.ModuleSpec.model_validate(_dash())
    assert len(spec.archetype_params["blocks"]) == 7
    assert spec.archetype_params["blocks"][0]["agg"] == "sum"


def test_needs_at_least_one_block():
    with pytest.raises(ValueError):
        msg.ModuleSpec.model_validate(_dash(blocks=[]))


def test_nine_blocks_is_a_wall():
    with pytest.raises(ValueError):
        msg.ModuleSpec.model_validate(_dash(blocks=[BLOCKS[1]] * 9))


def test_kind_is_closed():
    with pytest.raises(ValueError):
        msg.ModuleSpec.model_validate(_dash(blocks=[{"kind": "pie", "field": "category"}]))


def test_series_over_text_is_refused():
    with pytest.raises(ValueError, match="series field 'vendor' must be one of"):
        msg.ModuleSpec.model_validate(_dash(blocks=[
            {"kind": "series", "field": "vendor", "bucket": "month"}]))


def test_series_needs_a_date_somewhere():
    with pytest.raises(ValueError, match="series needs a date_field"):
        msg.ModuleSpec.model_validate(_dash(blocks=[
            {"kind": "series", "field": "amount", "bucket": "month"}], date_field=None))
    # on the block is fine
    msg.ModuleSpec.model_validate(_dash(blocks=[
        {"kind": "series", "field": "amount", "date_field": "spent_on"}], date_field=None))


def test_breakdown_by_a_number_is_refused():
    with pytest.raises(ValueError, match="breakdown field 'amount' must be one of"):
        msg.ModuleSpec.model_validate(_dash(blocks=[{"kind": "breakdown", "field": "amount"}]))


def test_breakdown_sum_needs_its_amount():
    with pytest.raises(ValueError, match="breakdown sum field"):
        msg.ModuleSpec.model_validate(_dash(blocks=[
            {"kind": "breakdown", "field": "category", "agg": "sum"}]))


def test_progress_needs_a_target():
    with pytest.raises(ValueError, match="progress needs a target"):
        msg.ModuleSpec.model_validate(_dash(blocks=[{"kind": "progress", "field": "amount"}]))


def test_progress_without_a_field_counts_rows():
    msg.ModuleSpec.model_validate(_dash(blocks=[{"kind": "progress", "target": 20}]))


def test_stat_sum_needs_a_number():
    with pytest.raises(ValueError, match="stat sum field 'category' must be one of"):
        msg.ModuleSpec.model_validate(_dash(blocks=[{"kind": "stat", "agg": "sum", "field": "category"}]))


def test_stat_count_needs_no_field():
    msg.ModuleSpec.model_validate(_dash(blocks=[{"kind": "stat", "agg": "count"}]))


def test_notes_over_a_number_is_refused():
    with pytest.raises(ValueError, match="notes field 'amount' must be one of"):
        msg.ModuleSpec.model_validate(_dash(blocks=[{"kind": "notes", "field": "amount"}]))


def test_recent_fields_must_exist():
    with pytest.raises(ValueError, match="recent fields 'ghost'"):
        msg.ModuleSpec.model_validate(_dash(blocks=[{"kind": "recent", "fields": ["ghost"]}]))


def test_upcoming_needs_a_date():
    with pytest.raises(ValueError, match="upcoming needs a date_field"):
        msg.ModuleSpec.model_validate(_dash(blocks=[{"kind": "upcoming"}], date_field=None))


def test_limit_is_bounded():
    with pytest.raises(ValueError):
        msg.ModuleSpec.model_validate(_dash(blocks=[{"kind": "recent", "limit": 200}]))


# ─── 2. the prompt and the skill ──────────────────────────────────────

@pytest.mark.parametrize("kind", msg.BLOCK_KINDS)
def test_prompt_teaches_every_block_kind(kind):
    block = msg._SYSTEM_PROMPT.split("composed_dashboard", 1)[1]
    assert f'"kind":"{kind}"' in block


def test_prompt_picking_discipline_names_it():
    assert "(composed_dashboard)" in msg._SYSTEM_PROMPT


@pytest.mark.parametrize("intake", [
    "I want to log my business expenses and see where the money goes each month",
    "a sales log with monthly totals",
    "log my workouts and see how many hours I train per week",
])
def test_the_dashboard_skill_fires_on_a_log(intake):
    names = [s["name"] for s in bs.select_skills(intake, "creative")]
    assert names and names[0] == "dashboard-module", (intake, names)


def test_the_dashboard_skill_does_not_hijack_a_tracker():
    names = [s["name"] for s in bs.select_skills(
        "watch each client's credit score climb toward 720", "consultant")]
    assert names[0] == "tracker-module", names


# ─── 3. the second look knows the shape ───────────────────────────────

def test_a_log_on_the_plain_list_is_revised():
    spec = _dash()
    spec["archetype"] = "fallback_generic"
    spec["archetype_params"] = {}
    spec["archetype_fallback_reason"] = "needs a dashboard"
    rep = bq.assess([spec], "log my expenses and see where the money goes each month", "creative")
    f = next(x for x in rep.findings if x.code == "archetype_fits")
    assert "composed_dashboard" in f.message
    assert rep.needs_revision


def test_a_good_dashboard_is_clean():
    rep = bq.assess([_dash()], "log my expenses and see where the money goes each month", "creative")
    assert not rep.needs_revision, rep.as_dict()


# ─── where: the rows a block reads (2026-09-06) ───────────────────────

def test_a_where_on_a_select_validates():
    msg.ModuleSpec.model_validate(_dash(blocks=[
        {"kind": "stat", "agg": "sum", "field": "amount", "label": "Software",
         "where": {"field": "category", "is_in": ["Software"]}}]))


def test_a_where_needs_a_side():
    with pytest.raises(ValueError, match="where needs is_in or not_in"):
        msg.ModuleSpec.model_validate(_dash(blocks=[
            {"kind": "stat", "agg": "sum", "field": "amount", "where": {"field": "category"}}]))


def test_a_where_on_a_number_is_refused():
    with pytest.raises(ValueError, match="where field 'amount' must be one of"):
        msg.ModuleSpec.model_validate(_dash(blocks=[
            {"kind": "stat", "agg": "count", "where": {"field": "amount", "is_in": ["1"]}}]))


def test_a_where_on_a_ghost_field_is_refused():
    with pytest.raises(ValueError, match="where field 'status' is not in"):
        msg.ModuleSpec.model_validate(_dash(blocks=[
            {"kind": "stat", "agg": "count", "where": {"field": "status", "not_in": ["paid"]}}]))


def test_prompt_teaches_where():
    block = msg._SYSTEM_PROMPT.split("composed_dashboard", 1)[1]
    assert '"where":{"field":"status","not_in":' in block


def test_payments_maps_to_the_dashboard():
    assert bq.SKILL_ARCHETYPE["payments-module"] == "composed_dashboard"
    skill = next(s for s in bs.load_skills() if s["name"] == "payments-module")
    assert '"where"' in skill["body"] and "composed_dashboard" in skill["body"]


# ─── the structural blocks: list / board / calendar (2026-09-06) ──────

def test_structural_blocks_validate():
    msg.ModuleSpec.model_validate(_dash(blocks=[
        {"kind": "stat", "agg": "count"},
        {"kind": "list", "fields": ["spent_on", "vendor", "amount"], "sort": "spent_on"},
        {"kind": "board", "field": "category", "label": "By category"},
        {"kind": "calendar", "label": "When"},
    ]))


def test_board_needs_a_select_with_options():
    with pytest.raises(ValueError, match="board field 'amount' must be one of"):
        msg.ModuleSpec.model_validate(_dash(blocks=[{"kind": "board", "field": "amount"}]))
    spec = _dash(blocks=[{"kind": "board", "field": "category"}])
    spec["schema"]["fields"][3]["options"] = []
    with pytest.raises(ValueError, match="has no options"):
        msg.ModuleSpec.model_validate(spec)


def test_calendar_needs_a_date():
    with pytest.raises(ValueError, match="calendar needs a date_field"):
        msg.ModuleSpec.model_validate(_dash(blocks=[{"kind": "calendar"}], date_field=None))


def test_list_sort_must_exist():
    with pytest.raises(ValueError, match="sort 'ghost' is not in"):
        msg.ModuleSpec.model_validate(_dash(blocks=[{"kind": "list", "sort": "ghost"}]))


@pytest.mark.parametrize("kind", ["list", "board", "calendar"])
def test_prompt_teaches_the_structural_blocks(kind):
    block = msg._SYSTEM_PROMPT.split("composed_dashboard", 1)[1]
    assert f'"kind":"{kind}"' in block
