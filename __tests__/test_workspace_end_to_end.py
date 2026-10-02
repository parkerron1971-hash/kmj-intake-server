"""
The whole chain, for every business type that actually exists.

The unit tests each prove one link. This proves the CHAIN, because every
production failure in this feature so far has been a JOIN between two
links that each worked alone:

  * the classifier returned `therapist`; the database rejected it
  * the validator accepted `invoices.total_cents`; the column is `total`
  * the layout bound `contractors.trade`; the column is `default_category`
  * the panel asked for `utilization_now`; the view emitted `utilization`

None of those were visible from inside a single module. So this walks a
real `businesses.type` from classification to a rendered bundle and
asserts every hand-off lands.
"""
from __future__ import annotations

import pathlib
import re

import pytest

import workspace_archetypes
import workspace_benchmarks
import workspace_layout_validator as validator
import workspace_layouts
from workspace_composer_router import build_layout

TENANT = "11111111-1111-1111-1111-111111111111"

# Every DISTINCT businesses.type in production on 2026-08-27, plus the two
# presets not yet used by a live business.
LIVE_TYPES = [
    "agency", "coach", "consultant", "course_creator", "creative", "custom",
    "ecommerce", "lawyer", "ministry", "nonprofit", "personal_services",
    "saas", "service_provider", "therapist", "contractor",
]


def _db_allows() -> set:
    sql = pathlib.Path(
        "supabase/APPLY-2026-08-27-workspace-archetype-widen.sql"
    ).read_text(encoding="utf-8")
    body = sql.split("workspace_archetype IN (", 1)[1].split(")", 1)[0]
    return set(re.findall(r"'([a-z_]+)'", body))


@pytest.mark.parametrize("business_type", LIVE_TYPES)
def test_a_real_business_type_survives_the_whole_chain(business_type):
    """type -> classify -> preset -> validate -> savable."""
    archetype = workspace_archetypes.classify({"vertical": business_type})["archetype"]

    assert archetype in workspace_layouts.ARCHETYPES, (
        f"{business_type} classifies to {archetype!r} with no preset")
    assert archetype in _db_allows(), (
        f"{business_type} classifies to {archetype!r}, which the database "
        "would reject — the write would fail silently")

    layout = build_layout(archetype, {})
    result = validator.validate_layout(layout, business_id=TENANT)
    assert result.ok, [e["message"] for e in result.errors]

    # A layout nobody can read is not a layout.
    assert layout.get("surfaces"), f"{archetype} renders nothing"
    assert any(s.get("role") == "lead" for s in layout["surfaces"]), (
        f"{archetype} has no lead surface — the page would open on nothing")


@pytest.mark.parametrize("business_type", LIVE_TYPES)
def test_the_benchmark_panel_and_the_bands_agree(business_type):
    """Every key the panel asks for must have a band behind it.

    A key with no band renders a hole; a band with no key is dead weight.
    The panel binds by key, so a rename on either side is silent.
    """
    for key in workspace_benchmarks.keys_for(business_type):
        assert key in workspace_benchmarks.BANDS, (
            f"{business_type} asks for band {key!r}, which does not exist")


def test_every_preset_is_reachable_from_some_business_type():
    """A preset nothing classifies to is a screen nobody can get to.

    Not a hard failure — `trades` is real and simply has no live business
    yet — but it must be reachable from SOME type, or it is dead code
    wearing a rationale.
    """
    reachable = {
        workspace_archetypes.classify({"vertical": t})["archetype"]
        for t in LIVE_TYPES
    }
    unreachable = set(workspace_layouts.ARCHETYPES) - reachable
    assert not unreachable, (
        f"presets no business type reaches: {sorted(unreachable)} — either "
        "wire a type to them or delete them")
