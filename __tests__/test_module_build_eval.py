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
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [_good_spec()]})
    failing = [c for c in scored["checks"] if not c["ok"]]
    assert not failing, failing
    assert scored["score"] == scored["total"]


def test_a_failed_generation_scores_zero_and_says_why():
    scored = mbe.score_case(BOOKING_CASE, {"ok": False, "error": "boom"})
    assert scored["score"] == 0
    assert "boom" in scored["checks"][0]["detail"]


def test_a_spec_that_would_not_render_loses_the_render_check():
    """The check that matters most: the practitioner sees a red panel."""
    spec = _good_spec()
    spec["schema"]["board_column"] = None          # board view, no column
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [spec]})
    renders = next(c for c in scored["checks"] if c["check"] == "renders")
    assert renders["ok"] is False
    assert "board_column" in renders["detail"]


def test_a_missing_expected_field_type_is_caught():
    spec = _good_spec()
    spec["schema"]["fields"] = [f for f in spec["schema"]["fields"] if f["type"] != "date"]
    spec["schema"]["views"] = ["list"]             # keep the board legal
    spec["schema"].pop("board_column", None)
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [spec]})
    assert not next(c for c in scored["checks"] if c["check"] == "field_type:date")["ok"]


def test_an_invented_field_type_is_caught():
    spec = _good_spec()
    spec["schema"]["fields"].append({"name": "x", "type": "colour_picker", "label": "X"})
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [spec]})
    known = next(c for c in scored["checks"] if c["check"] == "known_field_types")
    assert known["ok"] is False
    assert "colour_picker" in known["detail"]


def test_any_of_passes_on_one_match():
    spec = _good_spec()   # has contact_link but no offering_ref
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [spec]})
    any_check = next(c for c in scored["checks"] if c["check"].startswith("field_type:any_of"))
    assert any_check["ok"] is True


def test_the_scorer_is_not_vacuous():
    """A scorer that passes everything is worse than none — it would bless
    an extraction that broke the generator. An empty spec must fail
    several distinct checks, not merely score fewer points."""
    empty = {"name": "X", "schema": {"fields": [], "views": []}, "agent_config": {}}
    scored = mbe.score_case(BOOKING_CASE, {"ok": True, "specs": [empty]})
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
