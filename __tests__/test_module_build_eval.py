"""
test_module_build_eval.py — the eval harness has to work the first time.

scripts/module_build_eval.py is manual and makes real API calls, so it can
never run in this suite. That is exactly why its PURE parts are tested
here: a scorer that silently passes everything, or a comparer that cannot
see a regression, would only be discovered by trusting a bad result.

Nothing below makes a network call.
"""

import importlib.util
import json
import pathlib
import sys

import pytest

_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "module_build_eval.py"
_spec = importlib.util.spec_from_file_location("module_build_eval", _PATH)
mbe = importlib.util.module_from_spec(_spec)
sys.modules["module_build_eval"] = mbe
_spec.loader.exec_module(mbe)


def _good_spec():
    return {
        "name": "Appointments",
        "archetype": "booking_calendar",
        "schema": {
            "fields": [
                {"name": "appointment_at", "type": "date", "label": "When"},
                {"name": "status", "type": "select", "label": "Status",
                 "options": ["scheduled", "completed", "no_show"]},
                {"name": "client", "type": "contact_link", "label": "Client"},
            ],
            "views": ["list", "board"],
            "board_column": "status",
        },
        "agent_config": {"triggers": [{"type": "overdue", "field": "appointment_at",
                                       "action": "draft_reminder"}],
                         "closed_statuses": ["completed", "no_show"]},
    }


BOOKING_CASE = next(c for c in mbe.CASES if c["id"] == "booking")


# ─── The fixtures themselves ──────────────────────────────────────────

def test_every_case_expects_only_real_vocabulary():
    """A case that demands a field type the vocabulary does not have would
    fail forever and look like a permanent regression."""
    import module_vocabulary as mv

    for case in mbe.CASES:
        for t in case.get("expect_field_types", []) + case.get("expect_any_field_types", []):
            assert t in mv.FIELD_TYPES, f"{case['id']} expects unknown type {t}"
        for v in case.get("expect_views", []):
            assert v in mv.VIEW_KINDS, f"{case['id']} expects unknown view {v}"
        for k in case.get("expect_trigger_kinds", []):
            assert k in mv.TRIGGER_KINDS, f"{case['id']} expects unknown trigger {k}"


def test_case_ids_are_unique():
    ids = [c["id"] for c in mbe.CASES]
    assert len(ids) == len(set(ids))


# ─── Scoring ──────────────────────────────────────────────────────────

def test_a_good_spec_scores_full_marks():
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [_good_spec()]},
                            ["booking-module"])
    failing = [c for c in scored["checks"] if not c["ok"]]
    assert not failing, failing
    assert scored["score"] == scored["total"]


def test_a_failed_generation_scores_zero_and_says_why():
    scored = mbe.score_case(BOOKING_CASE, {"ok": False, "error": "boom"}, [])
    assert scored["score"] == 0
    assert any("boom" in c["detail"] for c in scored["checks"])


def test_a_spec_that_would_not_render_loses_the_render_check():
    """The check that matters most: the practitioner sees a red panel."""
    spec = _good_spec()
    spec["schema"]["board_column"] = None          # board view, no column
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [spec]}, ["booking-module"])
    renders = next(c for c in scored["checks"] if c["check"] == "renders")
    assert renders["ok"] is False
    assert "board_column" in renders["detail"]


def test_a_missing_expected_field_type_is_caught():
    spec = _good_spec()
    spec["schema"]["fields"] = [f for f in spec["schema"]["fields"] if f["type"] != "date"]
    spec["schema"]["views"] = ["list"]             # keep the board legal
    spec["schema"].pop("board_column", None)
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [spec]}, ["booking-module"])
    assert not next(c for c in scored["checks"] if c["check"] == "field_type:date")["ok"]


def test_an_invented_field_type_is_caught():
    spec = _good_spec()
    spec["schema"]["fields"].append({"name": "x", "type": "colour_picker", "label": "X"})
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [spec]}, ["booking-module"])
    known = next(c for c in scored["checks"] if c["check"] == "known_field_types")
    assert known["ok"] is False
    assert "colour_picker" in known["detail"]


def test_any_of_passes_on_one_match():
    spec = _good_spec()   # has contact_link but no offering_ref
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [spec]}, ["booking-module"])
    any_check = next(c for c in scored["checks"] if c["check"].startswith("field_type:any_of"))
    assert any_check["ok"] is True


def test_the_scorer_is_not_vacuous():
    """A scorer that passes everything is worse than none — it would bless
    an extraction that broke the generator. An empty spec must fail
    several distinct checks, not merely score fewer points."""
    empty = {"name": "X", "schema": {"fields": [], "views": []}, "agent_config": {}}
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [empty]}, ["booking-module"])
    failed = {c["check"] for c in scored["checks"] if not c["ok"]}
    assert "renders" in failed
    assert "field_type:date" in failed
    assert scored["score"] < scored["total"] / 2


# ─── Compare ──────────────────────────────────────────────────────────

def _report(score):
    return {
        "prompt_chars": 100,
        "total": score,
        "possible": 10,
        "results": [{"id": "booking", "score": score, "total": 10,
                     "checks": [{"check": "renders", "ok": score > 5, "detail": "d"}]}],
    }


def test_compare_flags_a_regression(capsys):
    rc = mbe.compare(_report(9), _report(3))
    out = capsys.readouterr().out
    assert rc == 1
    assert "!!" in out
    assert "-6" in out


def test_compare_is_quiet_when_nothing_regressed(capsys):
    rc = mbe.compare(_report(9), _report(9))
    assert rc == 0
    assert "scored lower" not in capsys.readouterr().out


def test_compare_always_warns_about_temperature(capsys):
    """Temperature 0.4 means two runs of the same code differ. A harness
    that reports a diff without saying so invites a confident wrong
    conclusion from one sample."""
    mbe.compare(_report(9), _report(9))
    assert "temperature" in capsys.readouterr().out.lower()


def test_compare_reads_files_without_touching_the_network(tmp_path, monkeypatch):
    before, after = tmp_path / "b.json", tmp_path / "a.json"
    before.write_text(json.dumps(_report(9)), encoding="utf-8")
    after.write_text(json.dumps(_report(9)), encoding="utf-8")

    def _no(*a, **k):
        raise AssertionError("--compare must not generate anything")

    monkeypatch.setattr(mbe.module_spec_generator, "generate_module_proposal", _no)
    monkeypatch.setattr(sys, "argv",
                        ["module_build_eval.py", "--compare", str(before), str(after)])
    assert mbe.main() == 0


def test_run_refuses_without_an_api_key(monkeypatch):
    """Better a clear exit than a run of failed generations that reads as
    a catastrophic regression."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit) as e:
        mbe.run(mbe.CASES)
    assert e.value.code == 2


# ─── Selection is scored ──────────────────────────────────────────────

def test_the_wrong_skill_fails_the_case():
    """The first live run had the feedback case pulling booking-module
    while every structural check passed — Chief was handed the wrong
    playbook and the score said nothing. Now it says something."""
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [_good_spec()]},
                            ["pipeline-module"])
    c = next(c for c in scored["checks"] if c["check"].startswith("skill:"))
    assert c["ok"] is False
    assert "pipeline-module" in c["detail"]


def test_selection_is_scored_even_when_generation_fails():
    """Checked before generation, so a total failure still reports which
    skill attached — otherwise the one run that most needs diagnosing is
    the one that tells you least."""
    scored = mbe.score_case(BOOKING_CASE, {"ok": False, "error": "boom"},
                            ["booking-module"])
    c = next(c for c in scored["checks"] if c["check"].startswith("skill:"))
    assert c["ok"] is True


def test_cases_without_an_expected_skill_are_not_penalised():
    equip = next(c for c in mbe.CASES if c["id"] == "equipment")
    scored = mbe.score_case(equip, {"ok": False, "error": "x"}, [])
    assert not any(c["check"].startswith("skill:") for c in scored["checks"])


def test_every_expected_skill_actually_exists():
    """An expect_skill naming a file nobody wrote would fail forever."""
    import build_skills as bs

    names = {s["name"] for s in bs.load_skills()}
    for case in mbe.CASES:
        want = case.get("expect_skill")
        if want:
            assert want in names, f"{case['id']} expects missing skill {want!r}"


# ─── Confidence, the contract a vague intake actually has ─────────────

VAGUE_CASE = next(c for c in mbe.CASES if c["id"] == "vague")


def test_a_confident_answer_to_a_vague_question_fails():
    """Run 2 produced a full 'Items' module for "I need to stay on top of
    things" and scored 4/4 — the score ROSE while the behaviour looked
    worse, because every check only asked "did it build something that
    renders".

    The generator's stated contract for a vague intake is not refusal
    (that rule is in the frontend AI tab, a different path) — it is
    confidence: 'low'. Building a reasonable guess is fine. Claiming
    certainty about it is not."""
    spec = {"name": "Items", "confidence": "high",
            "schema": {"fields": [{"name": "t", "type": "text", "label": "T"}],
                       "views": ["list"]},
            "agent_config": {}}
    scored = mbe.score_case(VAGUE_CASE, {"ok": True, "specs": [spec]}, [])
    c = next(c for c in scored["checks"] if c["check"].startswith("confidence:"))
    assert c["ok"] is False
    assert "high" in c["detail"]


def test_low_confidence_on_a_vague_intake_passes():
    spec = {"name": "Items", "confidence": "low",
            "schema": {"fields": [{"name": "t", "type": "text", "label": "T"}],
                       "views": ["list"]},
            "agent_config": {}}
    scored = mbe.score_case(VAGUE_CASE, {"ok": True, "specs": [spec]}, [])
    c = next(c for c in scored["checks"] if c["check"].startswith("confidence:"))
    assert c["ok"] is True


def test_confidence_is_only_checked_where_declared():
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [_good_spec()]},
                            ["booking-module"])
    assert not any(c["check"].startswith("confidence:") for c in scored["checks"])


def test_expected_confidence_values_are_real():
    """Literal["high","medium","low"] — an expectation outside that set
    could never be satisfied."""
    for case in mbe.CASES:
        want = case.get("expect_confidence")
        if want:
            assert want in {"high", "medium", "low"}, case["id"]


# ─── A proposal is one answer; score all of it ────────────────────────

LINKED_CASE = next(c for c in mbe.CASES if c["id"] == "linked")


def _two_specs():
    """What a correct decomposition looks like: a parent and a child that
    references it. The reference is on the CHILD."""
    parent = {"name": "Jobs", "slug": "jobs", "confidence": "high",
              "schema": {"fields": [{"name": "title", "type": "text", "label": "T"}],
                         "views": ["list"]},
              "agent_config": {}}
    child = {"name": "Invoices", "slug": "invoices", "confidence": "high",
             "schema": {"fields": [
                 {"name": "job", "type": "module_ref", "label": "Job",
                  "module_slug": "jobs"},
                 {"name": "amount", "type": "currency", "label": "Amount"}],
                 "views": ["list"]},
             "agent_config": {}}
    return [parent, child]


def test_a_field_on_the_second_spec_is_seen():
    """THE bug. score_case read specs[0] and nothing else, so the `linked`
    case scored field_type:module_ref as a MISS while the module_ref sat
    on the Invoices spec pointing back at Jobs.

    The parent of a relationship never holds the reference — the child
    does. A harness that reads one spec can never see a link, which made
    it blind to precisely what it was extended to check."""
    scored = mbe.score_case(LINKED_CASE, {"ok": True, "specs": _two_specs()},
                            ["payments-module"])
    failed = {c["check"] for c in scored["checks"] if not c["ok"]}
    assert "field_type:module_ref" not in failed, scored["checks"]
    assert scored["score"] == scored["total"], failed


def test_a_broken_second_spec_still_fails_the_case():
    """One red module in a two-module proposal is still a practitioner
    staring at an error panel."""
    specs = _two_specs()
    specs[1]["schema"]["views"] = ["board"]        # board, no board_column
    scored = mbe.score_case(LINKED_CASE, {"ok": True, "specs": specs},
                            ["payments-module"])
    renders = next(c for c in scored["checks"] if c["check"] == "renders")
    assert renders["ok"] is False
    assert "invoices" in renders["detail"], renders["detail"]


def test_every_spec_appears_in_the_output():
    """Showing only the first is how a correct decomposition read as a
    failure — the answer was on the module the summary omitted."""
    scored = mbe.score_case(LINKED_CASE, {"ok": True, "specs": _two_specs()},
                            ["payments-module"])
    assert [s["slug"] for s in scored["specs"]] == ["jobs", "invoices"]


def test_a_module_ref_summary_names_its_target():
    """Reading the output should answer 'pointing at what?' without
    cross-referencing anything."""
    scored = mbe.score_case(LINKED_CASE, {"ok": True, "specs": _two_specs()},
                            ["payments-module"])
    invoices = scored["specs"][1]
    assert ("job", "module_ref", "jobs") in [tuple(f) for f in invoices["fields"]]


def test_single_spec_cases_are_unaffected():
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [_good_spec()]},
                            ["booking-module"])
    assert scored["score"] == scored["total"]
    assert len(scored["specs"]) == 1
