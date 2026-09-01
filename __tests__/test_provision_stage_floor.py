"""A brand-new business gets its starting modules.

THE DEADLOCK THIS PINS
    a new business has 0 modules and 0 entries
    -> maturity_engine's 'launching' band needs module_count >= 1 AND
       entry_count >= 1, so derive_stage returns 'idea'
    -> every core blueprint row is maturity_stage 'launching'
    -> _stage_le('launching', 'idea') is False for all of them
    -> nothing is created, an empty report is returned, NOTHING ERRORS

A business needed at least one module to reach the stage that permits it
to be given its first module. It failed silently, which is why it
survived: provision_modules returned {"created": []} and every caller
treats that as success.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import maturity_engine as me
import module_blueprint_agent as mba


LAUNCHING_ROW = {
    "module_slug": "jobs", "module_name": "Jobs", "icon": "J",
    "schema": {"fields": []}, "tier": "core", "maturity_stage": "launching",
    "sort_order": 1,
}
OPERATING_ROW = {
    "module_slug": "reporting", "module_name": "Reporting", "icon": "R",
    "schema": {"fields": []}, "tier": "core", "maturity_stage": "operating",
    "sort_order": 2,
}


def _harness(monkeypatch, stage, rows):
    """Fake the two seams: what stage the business is, and what the
    blueprint holds. Returns the slugs that got POSTed."""
    created = []
    monkeypatch.setattr(me, "get_maturity_stage", lambda bid, force=False: stage)
    monkeypatch.setattr(mba, "get_blueprint", lambda bt: list(rows))
    monkeypatch.setattr(mba, "_existing_slugs", lambda bid: set())
    monkeypatch.setattr(
        mba, "_sb_post",
        lambda path, body: created.append(body.get("slug")) or [{"id": "m1", **body}])
    return created


# ─── the deadlock ────────────────────────────────────────────────────

def test_the_maturity_bands_really_do_start_a_business_at_idea():
    """Not an assumption — the reason the floor is needed. If the band
    thresholds change so a new business starts at 'launching', this test
    fails and the floor can be reconsidered."""
    assert me.derive_stage({}) == "idea"
    assert me.derive_stage({
        "age_days": 0, "module_count": 0, "entry_count": 0,
        "paid_invoice_count": 0,
    }) == "idea"
    band = next(b for b in me._BANDS if b["stage"] == "launching")
    assert band["module_count"] >= 1 and band["entry_count"] >= 1, (
        "the launching band no longer requires prior activity — the "
        "deadlock this floor works around may be gone")


def test_an_idea_stage_business_still_gets_its_launching_modules(monkeypatch):
    """The bug, stated as the fix. Before the floor this created nothing."""
    created = _harness(monkeypatch, "idea", [LAUNCHING_ROW])
    report = mba.provision_modules("b1", "contractor")
    assert created == ["jobs"], report
    assert report["created"] == ["jobs"]


def test_the_gate_still_holds_back_later_stages(monkeypatch):
    """The floor must not become 'provision everything'. An idea-stage
    business gets launching rows and NOT operating ones — that is the
    gate's actual purpose and it is still doing it."""
    created = _harness(monkeypatch, "idea", [LAUNCHING_ROW, OPERATING_ROW])
    mba.provision_modules("b1", "contractor")
    assert created == ["jobs"]
    assert "reporting" not in created


def test_a_grown_business_still_gets_its_operating_modules(monkeypatch):
    """The floor raises a low ceiling; it must never lower a high one."""
    created = _harness(monkeypatch, "operating", [LAUNCHING_ROW, OPERATING_ROW])
    mba.provision_modules("b1", "contractor")
    assert set(created) == {"jobs", "reporting"}


def test_an_explicit_max_stage_is_still_honoured(monkeypatch):
    """Callers passing max_stage bypass the maturity lookup entirely, and
    the floor must not silently override a deliberate choice."""
    created = _harness(monkeypatch, "operating", [LAUNCHING_ROW, OPERATING_ROW])
    mba.provision_modules("b1", "contractor", max_stage="launching")
    assert created == ["jobs"]


def test_a_failed_maturity_lookup_still_provisions(monkeypatch):
    """This branch already worked, and its existence is the evidence the
    silent path was a bug: a lookup that FAILED provisioned more than one
    that succeeded."""
    def boom(bid, force=False):
        raise RuntimeError("supabase down")
    monkeypatch.setattr(me, "get_maturity_stage", boom)
    monkeypatch.setattr(mba, "get_blueprint", lambda bt: [LAUNCHING_ROW])
    monkeypatch.setattr(mba, "_existing_slugs", lambda bid: set())
    created = []
    monkeypatch.setattr(
        mba, "_sb_post",
        lambda path, body: created.append(body.get("slug")) or [{"id": "m1", **body}])

    mba.provision_modules("b1", "contractor")
    assert created == ["jobs"]
