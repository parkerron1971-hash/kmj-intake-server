"""
test_chief_advice_eval.py — the advice eval's deterministic checks say what
they claim (2026-09-28).

The live eval (scripts/chief_advice_eval.py) spends money and runs by hand;
its scorer is pure and runs here on every PR, so a check that silently
passes everything cannot sneak in.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import chief_advice_eval as ev
import chief_truth as truth

GOOD = ("Raise it to $175. Your calendar has three sessions booked and Monica's package is overdue, "
        "so capacity isn't the problem, collections are. I'd move the 1:1 rate from $150 to $175 for new "
        "clients and keep current ones at $150 through December. Want me to update the offering?")
QUIZ = "What's your current rate, and how many clients do you have? Tell me that and I'll help."
HEDGE = ("It depends on a lot of things. Pricing is personal. Some coaches charge more, some less. "
         "\n\nThese parts of my answer are still unverified:\n- “Some coaches charge more”")


def test_a_committed_answer_with_a_next_step_passes_every_check():
    r = ev.score_reply(GOOD, ["list_offerings"])
    assert r["score"] == r["total"], r["checks"]


def test_a_wall_fails_everything_that_needs_an_answer():
    for wall in (truth.NO_ACTION_REPLY, truth.UNVERIFIED_REPLY, ""):
        c = ev.score_reply(wall, [])["checks"]
        assert not c["answered"] and not c["commits"] and not c["offers_next_step"]
        assert not c["leads_with_answer"] and not c["no_caveat_block"]


def test_opening_with_a_question_is_not_leading_with_the_answer():
    assert not ev.score_reply(QUIZ, [])["checks"]["leads_with_answer"]


def test_it_depends_does_not_commit_and_the_caveat_block_is_seen():
    c = ev.score_reply(HEDGE, [])["checks"]
    assert not c["commits"] and not c["no_caveat_block"] and not c["offers_next_step"]


def test_a_write_on_an_advice_turn_is_a_miss_and_reads_are_not():
    assert ev.score_reply(GOOD, ["list_offerings", "growth_report"])["checks"]["wrote_nothing"]
    assert not ev.score_reply(GOOD, ["create_offering"])["checks"]["wrote_nothing"]
    assert not ev.score_reply(GOOD, ["send_sms"])["checks"]["wrote_nothing"]


def test_every_case_names_a_business_the_eval_can_build():
    ids = [c["id"] for c in ev.CASES]
    assert len(ids) == len(set(ids))
    for case in ev.CASES:
        biz, make_ctx = ev.BUSINESSES[case["biz"]]
        ctx = make_ctx(biz)
        assert ctx["contacts_lookup"], case["id"]


def test_the_established_businesses_carry_what_advice_should_use():
    for key in ("coach_est", "salon_est", "trades_est", "church_est"):
        biz, make_ctx = ev.BUSINESSES[key]
        ctx = make_ctx(biz)
        assert ctx["offerings"] and ctx["products"] and ctx["sessions"], key


def test_usage_capture_keeps_fixture_turns_out_of_the_table():
    # In a child process: the capture rebinds names process-wide by design.
    import subprocess
    code = ("import sys; sys.path.insert(0, '.'); import api_usage_logger as a, llm_call; "
            "rows = a.capture_in_memory(); "
            "a.log_api_usage_sync(endpoint='x', model='claude-sonnet-5-5', input_tokens=1000000, output_tokens=0); "
            "print(len(rows), rows[0]['cents'])")
    out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert out.stdout.split() == ["1", "200.0"], out.stderr[-500:]
