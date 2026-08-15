"""The nonprofit briefing must actually read the grants board.

vertical_autopilot seeds a nonprofit with "Grant and deadline sweep",
running the briefing agent every weekday. The briefing routes nonprofit
to _community, which read contacts and event rosters ONLY — no
_scan_pipelines call anywhere in it.

So the sweep would have run every weekday, found nothing, and looked
exactly like working autopilot. vertical_autopilot.py already documents
that failure for a chair-business job it deleted rather than ship:

    The job would have found nothing every weekday forever and looked
    like working autopilot.

This pins the fix at the level that matters — given a grants pipeline
with a deadline, does the nonprofit briefing SAY so.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import date, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import briefing_verticals as bv
import vertical_autopilot as va
import vertical_intelligence as vi

BIZ = "biz-np-1"
MODULE_ID = "mod-grants-1"


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


class FakeSB:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def __call__(self, client, method, path, body=None):
        self.calls.append((method, path))
        if method != "GET":
            return []
        for pred, rows in self.routes:
            if pred(path):
                return rows
        return []

    def tables_touched(self):
        return {p.split("?", 1)[0].lstrip("/") for _, p in self.calls}


GRANTS_MODULE = {
    "id": MODULE_ID, "name": "Grants", "slug": "grants",
    "archetype": "work_pipeline",
    "archetype_params": {
        "stage_field": "stage", "title_field": "funder",
        "date_field": "deadline", "value_field": "amount",
        "item_noun": "grant",
        "stages": [
            {"id": "researching", "label": "Researching"},
            {"id": "applied", "label": "Applied"},
            {"id": "awarded", "label": "Awarded"},
            {"id": "reporting", "label": "Reporting"},
            {"id": "declined", "label": "Declined", "done": True},
            {"id": "closed", "label": "Closed", "done": True},
        ],
    },
}

ENTRIES = [
    {"id": "e1", "module_id": MODULE_ID, "status": "active",
     "updated_at": f"{_day(-1)}T00:00:00Z",
     "data": {"funder": "Hearth Foundation", "stage": "applied",
              "deadline": _day(4), "amount": 25000}},
    {"id": "e2", "module_id": MODULE_ID, "status": "active",
     "updated_at": f"{_day(-2)}T00:00:00Z",
     "data": {"funder": "City Arts Council", "stage": "reporting",
              "deadline": _day(-9), "amount": 8000}},
]


def _routes(module_rows, entry_rows):
    return [
        (lambda p: "/custom_modules" in p and "work_pipeline" in p, module_rows),
        (lambda p: "/custom_modules" in p, []),
        (lambda p: "/module_entries" in p, entry_rows),
        (lambda p: "/contacts" in p, []),
    ]


@pytest.fixture(autouse=True)
def _no_service_reads(monkeypatch):
    import sb_clients

    def _boom(*a, **k):
        raise AssertionError("branch bypassed the recorded sb callable")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _boom)


async def _run(sb):
    return await bv._community(sb, None, {"id": BIZ, "type": "nonprofit"})


@pytest.mark.asyncio
async def test_the_briefing_reads_the_grants_pipeline():
    sb = FakeSB(_routes([GRANTS_MODULE], ENTRIES))
    sections = await _run(sb)
    keys = [s.get("key") for s in sections]
    assert "pipeline" in keys, f"no pipeline section: {keys}"


@pytest.mark.asyncio
async def test_it_names_the_approaching_deadline():
    sb = FakeSB(_routes([GRANTS_MODULE], ENTRIES))
    sections = await _run(sb)
    blob = " ".join(
        " ".join(s.get("lines") or []) for s in sections if s.get("key") == "pipeline")
    assert "Hearth Foundation" in blob, blob
    assert "deadline" in blob.lower(), blob


@pytest.mark.asyncio
async def test_an_overdue_report_is_reported_as_past_due():
    """The award is IN, and the report is nine days late. This is the case
    the whole sweep exists for — and the one a terminal `reporting` stage
    would have hidden."""
    sb = FakeSB(_routes([GRANTS_MODULE], ENTRIES))
    sections = await _run(sb)
    blob = " ".join(
        " ".join(s.get("lines") or []) for s in sections if s.get("key") == "pipeline")
    assert "City Arts Council" in blob, blob
    assert "past due" in blob.lower(), blob


@pytest.mark.asyncio
async def test_no_pipeline_means_no_invented_section():
    """A nonprofit that tracks no grants must not get an empty heading."""
    sb = FakeSB(_routes([], []))
    sections = await _run(sb)
    assert "pipeline" not in [s.get("key") for s in sections]


@pytest.mark.asyncio
async def test_giving_is_still_never_read():
    """The branch's standing rule: restricted giving data is owner-only
    and audited, and the briefing never touches it. Adding a pipeline
    scan must not have widened what this reads."""
    sb = FakeSB(_routes([GRANTS_MODULE], ENTRIES))
    await _run(sb)
    touched = sb.tables_touched()
    assert bv.RESTRICTED_TABLE not in touched, touched
    assert not any("giving" in t for t in touched), touched


def test_the_autopilot_job_exists_and_runs_on_weekdays():
    jobs = {j["key"]: j for j in va.DEFAULT_AUTOPILOT["nonprofit"]}
    assert "grant_deadlines" in jobs, list(jobs)
    job = jobs["grant_deadlines"]
    # Weekdays, for the lawyer's reason: a Friday-to-Monday gap is where a
    # submission date goes missing.
    assert job["recurrence"] == "weekdays", job["recurrence"]
    assert job["action"]["agent"] == "briefing", job["action"]


def test_grants_is_offered_as_a_module():
    slugs = [s["slug"] for s in
             vi.VERTICAL_INTELLIGENCE["nonprofit"]["module_suggestions"]]
    assert "grants" in slugs, slugs
    grants = next(s for s in
                  vi.VERTICAL_INTELLIGENCE["nonprofit"]["module_suggestions"]
                  if s["slug"] == "grants")
    # fallback_generic would render a list, which is what the blueprint
    # row did wrong for a month.
    assert grants["archetype"] == "work_pipeline", grants
