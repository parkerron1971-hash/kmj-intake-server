"""Provisioning must carry the archetype's CONFIGURATION, not just its name.

business_type_module_blueprint gained an `archetype` column so a lawyer's
auto-provisioned Matters would render as a pipeline instead of a plain
list. It worked there by luck: the lawyer schema happens to use the
conventional field names work_pipeline falls back to.

nonprofit/grants does not. Its schema is funder / deadline / amount, while
work_pipeline's DEFAULT_FIELDS are title / due_date / value. Naming the
archetype without shipping archetype_params would render a board where
every card has no title, no date and no value — a worse failure than the
generic list it replaced, because it looks broken rather than plain.

So the blueprint carries params too, and this pins that they survive the
trip into custom_modules.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import module_blueprint_agent as mba

GRANTS_PARAMS = {
    "stage_field": "stage",
    "title_field": "funder",
    "date_field": "deadline",
    "value_field": "amount",
    "item_noun": "grant",
    "stages": [
        {"id": "researching", "label": "Researching"},
        {"id": "applied", "label": "Applied"},
        {"id": "awarded", "label": "Awarded"},
        {"id": "reporting", "label": "Reporting"},
        {"id": "declined", "label": "Declined", "done": True},
        {"id": "closed", "label": "Closed", "done": True},
    ],
}


def _blueprint_row(**over):
    row = {
        "business_type": "nonprofit",
        "module_slug": "grants",
        "module_name": "Grants",
        "icon": "📝",
        "description": "Grant pipeline",
        "schema": {"fields": [{"name": "funder", "type": "text"}]},
        "agent_config": {"enabled": True, "triggers": []},
        "tier": "core",
        "maturity_stage": "launching",
        "sort_order": 3,
        "archetype": "work_pipeline",
        "archetype_params": GRANTS_PARAMS,
    }
    row.update(over)
    return row


@pytest.fixture
def captured(monkeypatch):
    """Run provision_modules against a fake blueprint, capture the POSTs."""
    posts = []

    def fake_post(path, payload):
        posts.append((path, payload))
        return [{"id": "new-module-id"}]

    monkeypatch.setattr(mba, "_sb_post", fake_post)
    monkeypatch.setattr(mba, "_existing_slugs", lambda _bid: set())
    return posts


def test_archetype_params_reach_custom_modules(captured, monkeypatch):
    monkeypatch.setattr(mba, "get_blueprint", lambda _t: [_blueprint_row()])
    report = mba.provision_modules("biz-1", "nonprofit", max_stage="launching")

    assert report["created"] == ["grants"], report
    assert len(captured) == 1
    _path, payload = captured[0]
    assert payload["archetype"] == "work_pipeline"
    assert payload["archetype_params"] == GRANTS_PARAMS, (
        "the board would render with no title, no date and no value"
    )


def test_the_grants_field_names_are_not_the_archetype_defaults(captured, monkeypatch):
    """The reason params are mandatory here, stated as a check.

    If work_pipeline's defaults ever change to match these names this test
    should be revisited — but silently relying on that coincidence is what
    made this a bug in the first place.
    """
    monkeypatch.setattr(mba, "get_blueprint", lambda _t: [_blueprint_row()])
    mba.provision_modules("biz-1", "nonprofit", max_stage="launching")
    params = captured[0][1]["archetype_params"]
    # DEFAULT_FIELDS in src/core/components/archetypes/work_pipeline/types.ts
    assert params["title_field"] != "title"
    assert params["date_field"] != "due_date"
    assert params["value_field"] != "value"


def test_a_row_without_params_still_provisions(captured, monkeypatch):
    """Most blueprint rows have no params and must not gain an empty key."""
    monkeypatch.setattr(mba, "get_blueprint",
                        lambda _t: [_blueprint_row(archetype_params=None)])
    mba.provision_modules("biz-1", "nonprofit", max_stage="launching")
    payload = captured[0][1]
    assert payload["archetype"] == "work_pipeline"
    assert "archetype_params" not in payload


def test_a_row_with_no_archetype_at_all_is_unchanged(captured, monkeypatch):
    monkeypatch.setattr(
        mba, "get_blueprint",
        lambda _t: [_blueprint_row(archetype=None, archetype_params=None)])
    mba.provision_modules("biz-1", "nonprofit", max_stage="launching")
    payload = captured[0][1]
    assert "archetype" not in payload
    assert "archetype_params" not in payload


def test_terminal_stages_are_marked_done():
    """Declined and closed collapse; reporting must NOT.

    An awarded grant with reports still owed is the most live work in the
    pipeline — federal interim reports fall due within 30 days of a period
    end and finals within 120 — so collapsing it would hide exactly the
    deadlines the sweep exists to catch.
    """
    by_id = {s["id"]: s for s in GRANTS_PARAMS["stages"]}
    assert by_id["declined"].get("done") is True
    assert by_id["closed"].get("done") is True
    assert by_id["reporting"].get("done") is not True
    assert by_id["awarded"].get("done") is not True


def test_stage_ids_match_the_schema_select_options():
    """A stage id the schema cannot store orphans every entry in it."""
    schema_options = ["researching", "applied", "awarded", "declined", "reporting", "closed"]
    assert sorted(s["id"] for s in GRANTS_PARAMS["stages"]) == sorted(schema_options)
