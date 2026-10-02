"""Every picker card provisions something, and aliases reach the rows.

A blueprint with no rows is not an error anywhere: provision_modules
creates nothing and reports success, so the practitioner simply lands in
an empty workspace. Both failures below were exactly that shape.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import module_blueprint_agent as mba
import vertical_registry as reg


def test_get_blueprint_resolves_aliases(monkeypatch):
    """The table is keyed canonically, so a raw lookup returned zero rows
    for every alias — and a business stamped 'agency' (the most common
    type in the live table) was provisioned an empty workspace."""
    asked = []
    monkeypatch.setattr(mba, "_sb_get", lambda q: asked.append(q) or [])

    for alias, canonical in [("agency", "creative"), ("church", "ministry"),
                             ("coaching", "coach"), ("plumber", "contractor"),
                             ("counselor", "therapist"), ("online_store", "ecommerce")]:
        asked.clear()
        mba.get_blueprint(alias)
        assert f"business_type=eq.{canonical}" in asked[0], (
            f"'{alias}' queried {asked[0]!r} instead of the '{canonical}' rows")


def test_get_blueprint_is_still_empty_for_nothing(monkeypatch):
    monkeypatch.setattr(mba, "_sb_get", lambda q: [])
    assert mba.get_blueprint("") == []
    assert mba.get_blueprint(None) == []


def test_unrecognised_type_falls_to_custom(monkeypatch):
    """resolve() answers 'custom' for anything unknown, and custom has no
    blueprint rows on purpose — that is what triggers Chief's interactive
    discovery instead of provisioning a guessed workspace."""
    asked = []
    monkeypatch.setattr(mba, "_sb_get", lambda q: asked.append(q) or [])
    mba.get_blueprint("sasquatch_grooming")
    assert "business_type=eq.custom" in asked[0]


def test_every_canonical_vertical_has_blueprint_rows_except_custom():
    """Reads the LIVE table. OPT-IN — run with BLUEPRINT_LIVE_CHECK=1.

    contractor and therapist shipped as full verticals in July 2026 —
    picker card, profile, terminology, autopilot — and neither ever got a
    blueprint row, so both cards led to an empty workspace. Nothing caught
    it because nothing asserted it.

    WHY THIS IS OPT-IN RATHER THAN AMBIENT
      The first version keyed off `SUPABASE_URL` being present. It passed
      alone and FAILED in the full suite, because another test module
      leaks Supabase env vars into os.environ — so this ran with fake
      credentials, `_sb_get` returned None, and an empty read was reported
      as "every vertical is missing a blueprint". A test that reads
      nothing and calls it a finding is worse than no test, and one whose
      result depends on file ordering is not a result.

      A dedicated flag cannot be set by accident, so CI stays offline and
      deterministic. The cost is that CI does NOT prove the rows are
      applied — only that someone who ran this deliberately saw them.
      Applied state is verified against the live table when a migration
      ships, which is the discipline the nonprofit gap exists to enforce:
      writing a migration is not applying it, and neither is having a test
      that skips.
    """
    import os
    import pytest

    if os.environ.get("BLUEPRINT_LIVE_CHECK") != "1":
        pytest.skip("set BLUEPRINT_LIVE_CHECK=1 to check the live table")

    rows = mba._sb_get(
        "/business_type_module_blueprint?select=business_type&limit=2000")
    # An unreachable table returns None and a broken read returns []. Either
    # way this must FAIL rather than report every vertical as missing — the
    # message would be true-looking and completely wrong.
    assert rows, (
        "blueprint table read returned nothing. Fix the credentials or the "
        "connection; do not read this as 'no blueprints exist'.")

    have = {r.get("business_type") for r in rows if isinstance(r, dict)}
    # 'custom' is intentionally empty — vertical_registry.KNOWN_GAPS records
    # it as "intentionally no rows — triggers Chief interactive discovery".
    missing = [v for v in reg.canonical_keys() if v != "custom" and v not in have]
    assert not missing, (
        f"canonical verticals with NO module blueprint rows: {missing}. "
        f"A picker card with no blueprint provisions nothing and raises "
        f"nothing — the practitioner lands in an empty workspace.")
