"""
test_chief_turn_eval.py — the Chief turn eval, in CI, every PR.

scripts/chief_turn_eval.py has two modes. `replay` is deterministic and
needs no key, so it runs HERE: every golden row is driven through the
real chief_chat pipeline with its recorded reply, and the verbs that
reached the door are scored. `live` needs a key and is workflow_dispatch
only — its pure parts (the scorer, the comparer, the golden set's
vocabulary) are tested here too, so a scorer that passes everything or a
row naming a verb nobody wrote cannot ship.

Nothing below makes a network call.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "chief_turn_eval.py"
_spec = importlib.util.spec_from_file_location("chief_turn_eval", _PATH)
cte = importlib.util.module_from_spec(_spec)
sys.modules["chief_turn_eval"] = cte
_spec.loader.exec_module(cte)

import chief_of_staff as cos  # noqa: E402
import chief_tool_loop as ctl  # noqa: E402


# ─── the golden set is well-formed ───────────────────────────────────

def test_every_case_names_only_real_verbs():
    for case in cte.CASES:
        for v in list(case.get("expect") or []) + list(case.get("must_not") or []):
            assert v in cos.ACTION_HANDLERS, f"{case['id']}: {v} is not a Chief verb"


def test_every_case_has_a_dangerous_neighbour():
    """must_not is the point of a row, not decoration."""
    for case in cte.CASES:
        assert case.get("must_not"), f"{case['id']} names no dangerous neighbour"
        assert not set(case["must_not"]) & set(case.get("expect") or []), case["id"]


def test_tool_rows_call_a_tool_that_exists():
    tools = {t["name"] for t in ctl.write_tool_definitions()}
    for case in cte.CASES:
        if case.get("encoding") == "tool":
            assert case["tool_call"]["name"] in tools, (
                f"{case['id']}: {case['tool_call']['name']} is not a write tool")
            assert case["tool_call"]["name"] in (case.get("expect") or [])


def test_both_encodings_are_covered():
    enc = {c.get("encoding") for c in cte.CASES}
    assert enc == {"tag", "tool"}, "with two write mechanisms live, cover both"


def test_ids_are_unique():
    ids = [c["id"] for c in cte.CASES]
    assert len(ids) == len(set(ids))


def test_live_harness_keeps_real_prompt_available_without_live_io(monkeypatch):
    from unittest.mock import AsyncMock
    import chief_truth
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fixture-only-key')
    model = AsyncMock(return_value='[ACTION:{"type":"log_expense","amount":45}]')
    monkeypatch.setattr(cos, '_call_claude', model)
    monkeypatch.setattr(chief_truth, 'review_reply', AsyncMock(return_value=''))
    original = cos._build_system_prompt
    case = {'id': 'live-harness', 'message': 'Log a $45 expense',
            'expect': ['log_expense'], 'must_not': ['create_invoice']}
    result = cte.run_live([case])
    assert not result['failed_cases']
    assert cos._build_system_prompt is original
    assert 'Eval Co' in model.call_args.args[1]


def test_live_fixtures_supply_referenced_people_without_precreating_new_contacts():
    people = cte._fixture_context(cte.BIZ, {'id': 'note_on_contact'})['contacts_lookup']
    assert {p['id'] for p in people} == {'c-marcus', 'c-monica', 'c-ada'}
    new = cte._fixture_context(cte.BIZ, {'id': 'create_contact_lead'})
    assert all(p['id'] != 'c-ada' for p in new['contacts_lookup'])
    invoices = cte._fixture_context(cte.BIZ, {'id': 'send_is_class_c_tag'})['open_invoices']
    assert invoices[0]['contact_id'] == 'c-marcus'


def test_live_scorer_counts_native_reads_that_do_not_create_action_cards(monkeypatch):
    from unittest.mock import AsyncMock
    import chief_truth
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fixture-only-key')
    async def model(*args, **kwargs):
        await ctl.execute_tool_use(None, cte.BIZ, 'check_goals', {})
        return 'No goals were found.'
    monkeypatch.setattr(cos, '_call_claude', model)
    monkeypatch.setitem(cos.ACTION_HANDLERS, 'check_goals', AsyncMock(return_value={
        'type': 'check_goals', 'result': 'No goals found', 'label': 'Goals'}))
    monkeypatch.setattr(chief_truth, 'review_reply', AsyncMock(return_value=''))
    report = cte.run_live([{'id': 'native-read', 'message': 'Check my goals',
                           'expect': ['check_goals'], 'must_not': ['create_goal']}])
    assert not report['failed_cases']


# ─── the scorer cannot be vacuous ────────────────────────────────────

def test_scorer_rewards_the_expected_verb_and_punishes_the_neighbour():
    case = {"id": "x", "expect": ["log_expense"], "must_not": ["create_invoice"]}
    good = cte.score_case(case, ["log_expense"])
    assert good["score"] == good["total"] == 2
    bad = cte.score_case(case, ["create_invoice"])
    assert bad["score"] == 0
    both = cte.score_case(case, ["log_expense", "create_invoice"])
    assert both["score"] == 1


def test_a_row_that_expects_nothing_fails_on_any_verb():
    case = {"id": "x", "expect": [], "must_not": ["send_sms"]}
    assert cte.score_case(case, [])["score"] == 2
    r = cte.score_case(case, ["create_task"])
    assert r["score"] == 1 and any(c["check"] == "no_action" and not c["ok"] for c in r["checks"])


def test_compare_flags_a_regression(capsys):
    before = cte.summarize([cte.score_case({"id": "a", "expect": ["log_time"], "must_not": ["x"]},
                                           ["log_time"])], "replay")
    after = cte.summarize([cte.score_case({"id": "a", "expect": ["log_time"], "must_not": ["x"]},
                                          [])], "replay")
    assert cte.compare(before, after) == 1
    assert "newly failing: expect:log_time" in capsys.readouterr().out
    assert cte.compare(before, before) == 0


# ─── replay: every golden row, through the real pipeline ─────────────

@pytest.mark.parametrize("case", cte.CASES, ids=[c["id"] for c in cte.CASES])
def test_replay(case, monkeypatch):
    r = cte.run_replay_case(monkeypatch, case)
    failing = [c for c in r["checks"] if not c["ok"]]
    assert not failing, f"{case['id']}: {failing} (took {r['taken']})"


def test_replay_summary_is_all_green():
    report = cte.run_replay(cte.CASES)
    assert report["failed_cases"] == []
    assert report["total"] == report["possible"] > 0
