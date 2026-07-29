"""
test_vertical_autopilot.py — every vertical gets one overnight job, and no
default job may exceed what Chief is allowed to do unprompted.

The safety tests here matter more than the coverage ones. A default job runs
UNATTENDED on a schedule the practitioner did not ask for at the moment it
fires; if one of them could send email or move money, the first anyone would
know is a customer asking why they got a message at 6am.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import action_registry
import vertical_autopilot as va
import vertical_registry


# ── coverage: no vertical ships with nothing ─────────────────────────

def test_every_canonical_vertical_has_a_default_job():
    missing = [k for k in vertical_registry.canonical_keys()
               if not va.defaults_for(k)]
    assert not missing, f"verticals with no default autopilot: {missing}"


def test_barber_gets_the_rebooking_cadence():
    """The audit question for this vertical — 'what's the one overnight job
    it would miss?' — has exactly one right answer."""
    keys = [j["key"] for j in va.defaults_for("personal_services")]
    assert "rebooking" in keys


def test_lawyer_deadline_sweep_runs_on_weekdays():
    """A Friday-to-Monday gap is where a filing date goes missing."""
    jobs = va.defaults_for("lawyer")
    deadlines = next(j for j in jobs if j["key"] == "deadlines")
    assert deadlines["recurrence"] == "weekdays"


def test_ministry_follows_up_with_new_attendees():
    keys = [j["key"] for j in va.defaults_for("ministry")]
    assert "new_attendee" in keys


# ── the safety wall ──────────────────────────────────────────────────

def _all_jobs():
    for vertical, jobs in va.DEFAULT_AUTOPILOT.items():
        for job in jobs:
            yield vertical, job


def test_every_default_job_is_autonomy_eligible():
    """The load-bearing test. A default job may only be a verb Chief is
    permitted to run without being asked."""
    for vertical, job in _all_jobs():
        verb = job["action"]["type"]
        assert action_registry.is_autonomy_eligible(verb), (
            f"{vertical}/{job['key']} schedules '{verb}', which is not "
            f"autonomy-eligible (class {action_registry.reversibility(verb)!r})")


def test_no_default_job_is_a_class_c_verb():
    """Stated separately from the test above because this is the rule that
    must never be relaxed: class C is the wall around sending and money."""
    for vertical, job in _all_jobs():
        verb = job["action"]["type"]
        assert action_registry.reversibility(verb) != "C", (
            f"{vertical}/{job['key']} would run the class C verb '{verb}' "
            f"unattended")


def test_no_default_job_is_bulk():
    for vertical, job in _all_jobs():
        assert not action_registry.is_bulk(job["action"]["type"])


def test_every_default_verb_is_a_real_handler():
    """A scheduled verb that does not exist fails silently every week."""
    from chief_of_staff import ACTION_HANDLERS
    for vertical, job in _all_jobs():
        assert job["action"]["type"] in ACTION_HANDLERS, (
            f"{vertical}/{job['key']}: no handler for "
            f"'{job['action']['type']}'")


def test_run_agent_jobs_name_a_real_agent():
    """The bug this prevents: draft_nurture requires a contact_id and would
    have failed every single week as a standing job. run_agent batch mode
    needs a valid agent name instead — so validate the name."""
    from chief_of_staff import AGENT_ENDPOINT_MAP
    for vertical, job in _all_jobs():
        action = job["action"]
        if action["type"] != "run_agent":
            continue
        assert action.get("agent") in AGENT_ENDPOINT_MAP, (
            f"{vertical}/{job['key']}: '{action.get('agent')}' is not a "
            f"known agent. Valid: {sorted(AGENT_ENDPOINT_MAP)}")


def test_import_guard_rejects_an_unsafe_job(monkeypatch):
    """The guard is not decoration — prove it actually raises."""
    monkeypatch.setitem(
        va.DEFAULT_AUTOPILOT, "_probe",
        [va._job("bad", "Send everything", "nurture", "weekly", 11, "no")])
    va.DEFAULT_AUTOPILOT["_probe"][0]["action"] = {"type": "send_sms"}
    with pytest.raises(RuntimeError, match="not autonomy-eligible"):
        va._assert_safe()


# ── shape ────────────────────────────────────────────────────────────

def test_recurrence_values_are_ones_the_scheduler_understands():
    """chief_scheduler._next_run only steps daily / weekdays / weekly. Any
    other value returns None and the job silently never repeats."""
    for vertical, job in _all_jobs():
        assert job["recurrence"] in ("daily", "weekdays", "weekly"), (
            f"{vertical}/{job['key']}: chief_scheduler cannot step "
            f"'{job['recurrence']}' — the job would run once and stop")


def test_every_job_explains_itself():
    for vertical, job in _all_jobs():
        assert job["why"].strip(), f"{vertical}/{job['key']} has no rationale"
        assert job["label"].strip()


# ── alias resolution ─────────────────────────────────────────────────

@pytest.mark.parametrize("alias,canonical", [
    ("church",   "ministry"),
    ("coaching", "coach"),
    ("attorney", "lawyer"),
    ("agency",   "creative"),
])
def test_aliases_get_the_same_schedule(alias, canonical):
    assert va.defaults_for(alias) == va.defaults_for(canonical)


def test_unknown_type_still_gets_something():
    """Falling back to nothing is how a vertical ends up with no autopilot
    at all — the exact gap this module closes."""
    jobs = va.defaults_for("crypto_yacht_rental")
    assert jobs
    assert jobs == va.defaults_for("custom")


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_missing_type_does_not_raise(empty):
    assert va.defaults_for(empty)


# ── first-run scheduling ─────────────────────────────────────────────

def test_first_run_is_never_in_the_past():
    """A run_at in the past fires the instant the scheduler ticks, which
    turns 'your weekly briefing' into 'a briefing during signup'."""
    for recurrence in ("daily", "weekly", "weekdays"):
        for hour in range(24):
            run = va._first_run_at(hour, recurrence)
            assert run > datetime.now(timezone.utc)


def test_weekday_jobs_never_first_run_on_a_weekend():
    for hour in (0, 11, 23):
        assert va._first_run_at(hour, "weekdays").weekday() < 5


# ── describe() ───────────────────────────────────────────────────────

def test_describe_lists_the_jobs():
    text = va.describe("personal_services")
    assert "Rebooking" in text
    assert "weekly" in text
