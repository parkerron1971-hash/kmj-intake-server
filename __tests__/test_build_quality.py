"""
test_build_quality.py — the second look a proposal gets.

The rubric is deterministic, so it is tested like arithmetic. The loop
around it is tested with a fake model that returns a bad envelope first
and a good one on revision — and one that returns a WORSE revision, which
must be discarded.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import build_quality as bq
import module_spec_generator as msg


def _tracker(**over):
    base = {
        "slug": "credit-profiles", "name": "Credit Profiles",
        "archetype": "progress_tracker",
        "archetype_params": {"mode": "reading", "subject_field": "client", "value_field": "score",
                             "target": 720, "milestones": [620, 680, 720]},
        "schema": {"fields": [
            {"name": "client", "type": "contact_link", "label": "Client", "required": True},
            {"name": "score", "type": "number", "label": "Score", "required": True},
            {"name": "pulled_on", "type": "date", "label": "Pulled on"},
        ], "views": ["list"]},
        "agent_config": {"enabled": True, "triggers": [
            {"type": "target_reached", "action": "draft_notification"}]},
        "presentation": {"empty_line": "Pull the first report and the climb starts here.",
                         "reached_line": "Prime territory.",
                         "milestone_labels": {"620": "Fair", "680": "Good", "720": "Prime"}},
    }
    base.update(over)
    return base


INTAKE = ("I help clients repair their credit and want to watch each score "
          "climb toward 720, and be told the day someone gets there.")


# ─── the rubric ───────────────────────────────────────────────────────

def test_a_great_tracker_is_clean():
    rep = bq.assess([_tracker()], INTAKE, "consultant")
    assert not rep.needs_revision, rep.as_dict()
    assert rep.score == 0


def test_a_tracker_on_the_plain_list_is_the_first_finding():
    spec = _tracker(archetype="fallback_generic", archetype_params={},
                    archetype_fallback_reason="needs a tracker")
    rep = bq.assess([spec], INTAKE, "consultant")
    codes = [f.code for f in rep.findings]
    assert "archetype_fits" in codes
    assert rep.needs_revision
    assert "progress_tracker" in next(f.message for f in rep.findings if f.code == "archetype_fits")


def test_the_alert_they_asked_for_must_exist():
    spec = _tracker(agent_config={"enabled": True, "triggers": []})
    rep = bq.assess([spec], INTAKE, "consultant")
    codes = {f.code for f in rep.findings}
    assert "no_trigger" in codes
    assert "tracker_no_alert" in codes


def test_no_alert_asked_no_alert_finding():
    spec = _tracker(archetype="fallback_generic", archetype_params={},
                    agent_config={"enabled": True, "triggers": []},
                    presentation={"empty_line": "First recipe goes here."})
    rep = bq.assess([spec], "I want to store my grandmother's recipes", "custom")
    assert "no_trigger" not in {f.code for f in rep.findings}


def test_status_select_on_a_tracker_is_refused():
    spec = _tracker()
    spec["schema"]["fields"].append({"name": "status", "type": "select", "label": "S",
                                     "options": ["on track", "behind"]})
    rep = bq.assess([spec], INTAKE, "consultant")
    assert "tracker_status_select" in {f.code for f in rep.findings}


def test_unnamed_milestones_and_missing_lines():
    spec = _tracker(presentation={})
    rep = bq.assess([spec], INTAKE, "consultant")
    codes = {f.code for f in rep.findings}
    assert {"milestones_unnamed", "no_reached_line", "no_empty_line"} <= codes


@pytest.mark.parametrize("line", ["No data yet", "Nothing here", "Empty", "No entries yet."])
def test_generic_empty_line_is_caught(line):
    spec = _tracker(presentation={"empty_line": line, "reached_line": "x",
                                  "milestone_labels": {"620": "Fair"}})
    rep = bq.assess([spec], INTAKE, "consultant")
    assert "generic_empty_line" in {f.code for f in rep.findings}


def test_a_person_as_text_is_caught():
    spec = {
        "slug": "jobs", "name": "Jobs", "archetype": "work_pipeline", "archetype_params": {},
        "schema": {"fields": [
            {"name": "customer", "type": "text", "label": "Customer"},
            {"name": "stage", "type": "select", "label": "Stage", "options": ["a", "b", "done"]},
        ], "views": ["list", "board"], "board_column": "stage"},
        "agent_config": {"enabled": True, "triggers": [], "closed_statuses": ["done"]},
        "presentation": {"empty_line": "The first job opens the board."},
    }
    rep = bq.assess([spec], "track my jobs for customers", "contractor")
    assert "person_as_text" in {f.code for f in rep.findings}


def test_closed_statuses_named_when_a_stage_exists():
    spec = {
        "slug": "jobs", "name": "Jobs", "archetype": "work_pipeline", "archetype_params": {},
        "schema": {"fields": [
            {"name": "contact_id", "type": "contact_link", "label": "Customer"},
            {"name": "stage", "type": "select", "label": "Stage", "options": ["a", "b", "done"]},
        ], "views": ["list", "board"], "board_column": "stage"},
        "agent_config": {"enabled": True, "triggers": []},
        "presentation": {"empty_line": "The first job opens the board."},
    }
    rep = bq.assess([spec], "track my jobs", "contractor")
    assert "no_closed_statuses" in {f.code for f in rep.findings}


def test_notes_do_not_force_a_revision():
    spec = _tracker()
    spec["schema"]["fields"] = [dict(f, required=True) for f in spec["schema"]["fields"]] + [
        {"name": f"x{i}", "type": "text", "label": "x", "required": True} for i in range(3)]
    rep = bq.assess([spec], INTAKE, "consultant")
    assert [f.code for f in rep.findings] == ["many_required"]
    assert not rep.needs_revision


def test_revision_block_lists_only_revise_findings():
    spec = _tracker(presentation={})
    rep = bq.assess([spec], INTAKE, "consultant")
    block = rep.revision_block()
    assert block.startswith("REVISE")
    assert "no_empty_line" in block and "many_required" not in block


# ─── the loop ─────────────────────────────────────────────────────────

def _envelope(spec):
    return json.dumps({"decomposition_reasoning": "one module", "specs": [spec]})


def _full(spec):
    """A spec dict the envelope validator accepts."""
    s = dict(spec)
    s.setdefault("description", "d"); s.setdefault("intake_excerpt", "i"); s.setdefault("reasoning", "r")
    return s


class _Fake:
    """Returns the queued envelopes in order; records every prompt."""
    def __init__(self, envelopes):
        self.queue = list(envelopes)
        self.calls = []

    class _Block:
        type = "text"
        def __init__(self, t): self.text = t

    def create(self, **kw):
        self.calls.append(kw)
        text = self.queue.pop(0)
        class _Msg: content = [self._Block(text)]
        return _Msg()


def _wire(monkeypatch, fake):
    class _Client: messages = fake
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(msg.llm_call, "sdk_client", lambda **kw: _Client())
    monkeypatch.setattr(msg, "CRITIQUE_ENABLED", True)


def test_a_bad_first_answer_is_revised_and_the_revision_used(monkeypatch):
    bad = _full(_tracker(archetype="fallback_generic", archetype_params={},
                         archetype_fallback_reason="needs a tracker", presentation={}))
    good = _full(_tracker())
    fake = _Fake([_envelope(bad), _envelope(good)])
    _wire(monkeypatch, fake)

    res = msg.generate_module_proposal({"name": "Clear Path", "type": "consultant"}, INTAKE)
    assert res["ok"]
    assert len(fake.calls) == 2, "the rubric found revise-worthy findings; a second call was owed"
    assert "REVISE" in fake.calls[1]["messages"][0]["content"]
    assert res["quality"]["used"] == "revised"
    assert res["specs"][0]["archetype"] == "progress_tracker"
    assert res["quality"]["first"]["needs_revision"] is True
    assert res["quality"]["revised"]["score"] == 0


def test_a_worse_revision_is_discarded(monkeypatch):
    first = _full(_tracker(presentation={"empty_line": "Pull the first report.",
                                         "reached_line": "Prime.", "milestone_labels": {}}))
    worse = _full(_tracker(archetype="fallback_generic", archetype_params={},
                           archetype_fallback_reason="x", presentation={}))
    fake = _Fake([_envelope(first), _envelope(worse)])
    _wire(monkeypatch, fake)

    res = msg.generate_module_proposal({"name": "Clear Path", "type": "consultant"}, INTAKE)
    assert res["ok"]
    assert len(fake.calls) == 2
    assert res["quality"]["used"] == "first"
    assert res["specs"][0]["archetype"] == "progress_tracker"


def test_a_clean_first_answer_costs_one_call(monkeypatch):
    fake = _Fake([_envelope(_full(_tracker()))])
    _wire(monkeypatch, fake)
    res = msg.generate_module_proposal({"name": "Clear Path", "type": "consultant"}, INTAKE)
    assert res["ok"] and len(fake.calls) == 1
    assert res["quality"]["used"] == "first" and res["quality"]["revised"] is None


def test_a_failed_revision_keeps_the_first(monkeypatch):
    bad = _full(_tracker(presentation={}))
    fake = _Fake([_envelope(bad), "this is not json"])
    _wire(monkeypatch, fake)
    res = msg.generate_module_proposal({"name": "Clear Path", "type": "consultant"}, INTAKE)
    assert res["ok"] and res["quality"]["used"] == "first"


def test_the_kill_switch(monkeypatch):
    bad = _full(_tracker(presentation={}))
    fake = _Fake([_envelope(bad), _envelope(_full(_tracker()))])
    _wire(monkeypatch, fake)
    monkeypatch.setattr(msg, "CRITIQUE_ENABLED", False)
    res = msg.generate_module_proposal({"name": "Clear Path", "type": "consultant"}, INTAKE)
    assert res["ok"] and len(fake.calls) == 1


def test_the_generator_no_longer_sends_a_temperature(monkeypatch):
    """Sampling parameters are rejected by the current models (400)."""
    fake = _Fake([_envelope(_full(_tracker()))])
    _wire(monkeypatch, fake)
    msg.generate_module_proposal({"name": "Clear Path", "type": "consultant"}, INTAKE)
    assert "temperature" not in fake.calls[0]
    assert fake.calls[0]["model"] == msg.GENERATOR_MODEL


# ─── the first live eval's miss (2026-09-06) ──────────────────────────

def test_a_feedback_log_on_the_booking_calendar_is_revised():
    """72/72 on the harness, and the feedback case had landed on
    booking_calendar — single-instance, with a customer form — because
    the intake said "session". The harness could not score it; now the
    rubric can, and the eval asserts it."""
    spec = {
        "slug": "session-feedback", "name": "Session Feedback",
        "archetype": "booking_calendar",
        "archetype_params": {"primary_date_field": "session_date"},
        "schema": {"fields": [
            {"name": "session_date", "type": "date", "label": "When", "customer_facing": True},
            {"name": "contact_id", "type": "contact_link", "label": "Client"},
            {"name": "rating", "type": "rating", "label": "Rating"},
            {"name": "what_they_said", "type": "textarea", "label": "Words"},
        ], "views": ["list"]},
        "agent_config": {"enabled": True, "triggers": []},
        "presentation": {"empty_line": "Log the first session's rating."},
    }
    intake = ("After each session I want to record how the client rated it out "
              "of five and what they said, so I can spot a bad trend.")
    rep = bq.assess([spec], intake, "coach")
    codes = [f.code for f in rep.findings]
    assert "not_a_booking" in codes, codes
    assert "composed_dashboard" in next(f.message for f in rep.findings if f.code == "not_a_booking")
    assert rep.needs_revision


def test_a_real_booking_is_not_flagged():
    spec = {
        "slug": "bookings", "name": "Bookings", "archetype": "booking_calendar",
        "archetype_params": {"primary_date_field": "appointment_at"},
        "schema": {"fields": [
            {"name": "appointment_at", "type": "date", "label": "When", "customer_facing": True},
            {"name": "contact_id", "type": "contact_link", "label": "Customer"},
        ], "views": ["list", "calendar"], "calendar_field": "appointment_at"},
        "agent_config": {"enabled": True, "triggers": [{"type": "overdue", "field": "appointment_at", "action": "draft_reminder"}]},
        "presentation": {"empty_line": "Book the first head and the day starts filling up."},
    }
    rep = bq.assess([spec], "I need to keep track of my appointments and who showed up", "barber")
    assert "not_a_booking" not in {f.code for f in rep.findings}


def test_keep_track_of_does_not_pull_the_tracker_skill():
    """'track' fired the tracker skill on 'keep track of my appointments'
    and on 'track the gear I lend out' — two of six live cases got a
    playbook for a shape they were not."""
    import build_skills as bs
    for text in ("I need to keep track of my appointments and who showed up",
                 "Track the gear I lend out: what it is, who has it, when it's due back"):
        names = [s["name"] for s in bs.select_skills(text, "custom")]
        assert "tracker-module" not in names, (text, names)
    names = [s["name"] for s in bs.select_skills("a credit score tracker toward 720", "consultant")]
    assert names[0] == "tracker-module"
