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
    assert {p['id'] for p in people} == {cte.CONTACT_IDS['marcus'], cte.CONTACT_IDS['monica'], cte.CONTACT_IDS['ada']}
    new = cte._fixture_context(cte.BIZ, {'id': 'create_contact_lead'})
    assert all(p['id'] != cte.CONTACT_IDS['ada'] for p in new['contacts_lookup'])
    invoices = cte._fixture_context(cte.BIZ, {'id': 'send_is_class_c_tag'})['open_invoices']
    assert invoices[0]['contact_id'] == cte.CONTACT_IDS['marcus']


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


def test_live_contact_deep_dive_returns_the_requested_fixture_contact(monkeypatch):
    import asyncio
    cte._stub_turn(monkeypatch, cte.BIZ, {'id': 'draft_email_not_send'})
    result = asyncio.run(cos.handle_contact_deep_dive(None, cte.BIZ,
                        {'contact_id': cte.CONTACT_IDS['ada']}))
    assert not cos._action_failed(result)
    assert result['contact']['name'] == 'Ada Lovelace'
    assert 'program outline' in result['contact']['notes']


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
    if r.get("skipped"):
        pytest.skip(r["skipped"])
    failing = [c for c in r["checks"] if not c["ok"] and "pending" not in c]
    assert not failing, f"{case['id']}: {failing} (took {r['taken']})"
    pending = [c for c in r["checks"] if not c["ok"]]
    if pending:
        # Reported, not failed: the row names the open PR or the unbuilt
        # work that fixes it. An XPASS here means the marker can come out.
        pytest.xfail("; ".join(f"{c['check']}: {c['pending']}" for c in pending))


def test_replay_summary_is_all_green():
    report = cte.run_replay(cte.CASES)
    assert report["failed_cases"] == []
    missed = [(r["id"], c["check"]) for r in report["results"] for c in r["checks"]
              if not c["ok"]]
    assert missed == [(p["id"], p["check"]) for p in report["pending"]]
    assert report["total"] + len(missed) == report["possible"] > 0


# ─── day one: four businesses that signed up today ───────────────────

DAY_ONE = [c for c in cte.CASES if c.get("business")]


def test_day_one_covers_every_new_business_and_the_setup_verbs():
    assert {c["business"] for c in DAY_ONE} == set(cte.NEW_BUSINESSES)
    expected = {v for c in DAY_ONE for v in c["expect"]}
    assert {"set_availability_day", "create_offering", "create_contact",
            "create_client_form"} <= expected
    assert {c["message"] for c in DAY_ONE} >= {
        cte.GREETING, "What can you do for me?", "Do I have any invoices?",
        "Any appointments this week?"}


def test_day_one_rows_are_well_formed():
    for case in DAY_ONE:
        assert case["business"] in cte.NEW_BUSINESSES, case["id"]
        for v in (case.get("allow") or []) + list(case.get("expect_args") or {}):
            assert v in cos.ACTION_HANDLERS, f"{case['id']}: {v} is not a Chief verb"
        assert set(case.get("expect_args") or {}) <= set(case["expect"]), case["id"]
        for name in case.get("reply_checks") or []:
            assert name in cte.REPLY_CHECKS, f"{case['id']}: unknown reply check {name}"
        # A pending marker must name a check this row actually makes,
        # and say what fixes it.
        made = {c["check"] for c in cte.score_case(case, [], reply="", actions=[])["checks"]}
        for check, reason in (case.get("pending") or {}).items():
            assert check in made, f"{case['id']}: pending {check} is not one of its checks"
            assert reason.strip(), case["id"]


def test_day_one_types_are_the_keys_the_product_resolves():
    import vertical_registry
    for spec in cte.NEW_BUSINESSES.values():
        assert vertical_registry.resolve(spec["type"]) == spec["type"], spec


def test_day_one_fixture_is_what_signup_writes(monkeypatch):
    """The real _gather_context, the setup probes and the first-run arc
    all read the fixture: nothing in the business, the coached session
    not started, no introduction delivered, setup at zero."""
    import asyncio
    import first_run_arc
    biz = cte._business_for({"business": "barber"})
    cte._stub_turn(monkeypatch, biz)
    ctx = asyncio.run(cos._gather_context(None, biz["id"], query_text=None))
    assert ctx["business"]["id"] == biz["id"] and ctx["contacts_total"] == 0
    for key in ("contacts_lookup", "sessions", "open_invoices", "offerings", "products",
                "projects"):
        assert ctx[key] == [], key
    assert ctx["business_track"]["status"] == "in_progress"
    assert first_run_arc.intro_delivered(biz["id"]) is False
    assert cos._business_age_days(biz) < 1
    snapshot = cos._fetch_setup_snapshot(biz)
    assert snapshot["done"] == 0 and snapshot["total"] > 0


def test_live_runs_a_day_one_row_against_the_real_day_one_prompt(monkeypatch):
    """No key is spent: the model and the reviewer are stubbed, and what
    is checked is what live mode would have sent — the launch greeting,
    built from the fixture by the real gather and the real prompt."""
    from unittest.mock import AsyncMock
    import chief_truth
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-only-key")
    case = next(c for c in cte.CASES if c["id"] == "nb_ministry_greeting")
    model = AsyncMock(return_value=case["reply"])
    monkeypatch.setattr(cos, "_call_claude", model)
    monkeypatch.setattr(chief_truth, "review_reply", AsyncMock(return_value=""))
    report = cte.run_live([case])
    system = model.call_args.args[1]
    assert "LAUNCH GREETING" in system and "Grace Street Fellowship" in system
    assert "SETUP STATUS" in system and "Connected: 0 of" in system
    assert report["results"][0]["reply"].startswith("Good morning, James.")


def test_day_one_postgrest_filters_and_selects_like_the_real_one():
    biz = cte._business_for({"business": "coach"})
    tables = cte._day_one_tables(biz)
    welcome = f"/agent_queue?business_id=eq.{biz['id']}&status=eq.draft"
    # A column nobody selected never reaches the caller...
    assert "ai_reasoning" not in cte._postgrest(tables, "GET", welcome + "&select=id,subject")[0]
    # ...and one that is selected does.
    assert cte._postgrest(tables, "GET", welcome + "&select=id,agent,ai_reasoning")[0][
        "ai_reasoning"] == "Standard welcome message created at onboarding."
    assert cte._postgrest(tables, "GET", "/agent_queue?status=eq.sent&select=id") == []
    since = "2020-01-01T00:00:00+00:00"
    assert len(cte._postgrest(tables, "GET", f"/agent_queue?created_at=gte.{since}")) == 1
    assert cte._postgrest(tables, "GET", f"/contacts?business_id=eq.{biz['id']}") == []
    assert cte._postgrest(tables, "PATCH", "/first_run_arc?id=eq.x",
                          {"status": "walking"}) == [{"status": "walking"}]
    assert tables["_writes"][0]["method"] == "PATCH"


@pytest.mark.parametrize("name,good,bad", [
    ("one_question", "Welcome. Who's one regular you'd text today?",
     "Who's first? And what do you charge?"),
    ("no_list", "Start with one name.", "Here's the plan:\n1. Contacts\n2. Prices"),
    ("no_draft_pointer", "Who's one client I should add?",
     "You have 1 draft waiting for your review."),
    ("says_none_yet", "You don't have any invoices yet.", "Let me look into that."),
    ("no_unverified", "Nothing is booked this week.",
     "Your request came through. I couldn't verify the answer from the information available."),
    ("no_price_question", "When does the church gather on Sundays?",
     "What's the one thing people come to you for, and what do you charge?"),
    ("about_the_product", "I keep your client list, book sessions and send invoices.",
     "I'm here to help with whatever you need."),
])
def test_reply_checks_pass_the_good_reply_and_catch_the_bad_one(name, good, bad):
    assert cte.REPLY_CHECKS[name](good)
    assert not cte.REPLY_CHECKS[name](bad)


def test_a_pending_miss_is_reported_and_does_not_fail_the_run():
    case = {"id": "x", "message": "hi", "expect": [], "must_not": ["send_sms"],
            "reply_checks": ["no_unverified", "one_question"],
            "pending": {"reply:no_unverified": "PR #1"}}
    r = cte.score_case(case, [], reply="I couldn't verify that?")
    assert not r["failed"] and r["score"] == r["total"] - 1
    report = cte.summarize([r], "live")
    assert report["failed_cases"] == [] and report["pending"][0]["reason"] == "PR #1"
    # Any other miss on the same row still fails.
    assert cte.score_case(case, ["send_sms"], reply="I couldn't verify that?")["failed"]
    assert cte.score_case(case, [], reply="No question here.")["failed"]
    cleared = cte.summarize([cte.score_case(case, [], reply="All good?")], "live")
    assert cleared["pending_cleared"] == [{"id": "x", "check": "reply:no_unverified"}]


def test_a_read_budget_and_allowed_verbs_are_not_misses_of_restraint():
    case = {"id": "x", "expect": [], "must_not": ["create_invoice"], "max_reads": 1,
            "allow": ["navigate"]}
    assert not cte.score_case(case, ["list_offerings", "navigate"])["failed"]
    storm = cte.score_case(case, ["list_offerings"], reads=["list_offerings"] * 3)
    assert storm["failed"] and any(c["check"] == "reads<=1" and not c["ok"]
                                   for c in storm["checks"])
    assert cte.score_case(case, ["create_task"])["failed"]


def test_argument_checks_read_what_the_verb_carried():
    week = {"id": "x", "expect": ["set_availability_day"], "must_not": ["add_block_range"],
            "expect_week": {"tue": "09:00-18:00", "wed": "09:00-18:00"}}
    calls = [{"type": "set_availability_day", "day": d,
              "hours": [{"start": "9:00", "end": "18:00"}]} for d in ("tue", "wed")]
    closed = [{"type": "set_availability_day", "day": "mon", "hours": []}]
    assert not cte.score_case(week, ["set_availability_day"], actions=calls + closed)["failed"]
    assert cte.score_case(week, ["set_availability_day"], actions=calls[:1])["failed"]
    offer = {"id": "y", "expect": ["create_offering"], "must_not": ["create_invoice"],
             "expect_args": {"create_offering": {"current_price": 40, "duration_min": 45}}}
    right = [{"type": "create_offering", "name": "Haircut", "current_price": 40.0,
              "duration_min": 45}]
    assert not cte.score_case(offer, ["create_offering"], actions=right)["failed"]
    wrong = [{**right[0], "current_price": 45}]
    assert cte.score_case(offer, ["create_offering"], actions=wrong)["failed"]


def test_the_router_check_sees_the_fast_lane():
    assert cte._routes_to_full_turn(cte.GREETING)
    assert cte._routes_to_full_turn("Do I have any invoices?")
    assert not cte._routes_to_full_turn("thanks!")


def test_a_row_without_a_recorded_reply_is_skipped_in_replay_and_says_so():
    case = {"id": "live_only", "message": "Hi", "expect": [], "must_not": ["send_sms"]}
    report = cte.run_replay([case])
    assert report["failed_cases"] == []
    assert report["skipped"] == [{"id": "live_only",
                                  "reason": "no recorded reply: this row runs live only"}]
