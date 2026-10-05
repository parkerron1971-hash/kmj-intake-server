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


# ─── The SI score (2026-10-05) ────────────────────────────────────────

def test_one_question_at_most_and_a_quoted_script_is_not_a_question():
    two = "Raise it to $175. What's your current rate? And how many clients do you carry?"
    assert not ev.score_reply(two, [])["checks"]["one_question_max"]
    scripted = ("Name it once, warmly. Something like: 'What's going on in your week, and is there "
                "a better rhythm?' Is it one client or several?")
    assert ev.score_reply(scripted, [])["checks"]["one_question_max"]
    assert ev.score_reply(GOOD, [])["checks"]["one_question_max"]
    assert not ev.score_reply(truth.NO_ACTION_REPLY, [])["checks"]["one_question_max"]


def test_finds_cause_is_scored_only_on_hidden_cause_cases():
    assert "finds_cause" not in ev.score_reply(GOOD, [])["checks"]
    hit = ev.score_reply("The real problem is Tom Baker's $7,000 invoice, still unpaid.", [],
                         r"7,000|Tom Baker")
    assert hit["checks"]["finds_cause"] and hit["total"] == 9
    miss = ev.score_reply("Raise your prices and post more on Instagram.", [], r"7,000|Tom Baker")
    assert not miss["checks"]["finds_cause"]
    walled = ev.score_reply(truth.NO_ACTION_REPLY, [], r"7,000|Tom Baker")
    assert not walled["checks"]["finds_cause"]


def test_the_planted_causes_are_really_in_the_records():
    cases = {c["id"]: c for c in ev.CASES if c.get("cause")}
    assert len(cases) >= 5
    est = ev._ESTABLISHED
    assert ("Tom Baker", 7000, "sent") in est["contractor"]["invoices"]
    assert ("Monica Walton", 1200, "overdue") in est["coach"]["invoices"]
    assert {"Ada Lovelace", "Sam Ortiz"} <= {n for n, s, _h in est["coach"]["contacts"] if s == "lead"}
    biz, make_ctx = ev.BUSINESSES["coach_new"]
    assert not make_ctx(biz).get("offerings")
    import re
    for case in cases.values():
        re.compile(case["cause"])


def test_the_summary_handles_mixed_checks_and_carries_the_si_score():
    rows = [
        {"id": "a", "checks": ev.score_reply(GOOD, [])["checks"], "seconds": 1, "cents": 1},
        {"id": "b", "checks": ev.score_reply("Tom Baker owes $7,000.", [], r"Tom Baker")["checks"],
         "seconds": 1, "cents": 1},
        {"id": "c", "checks": ev.score_reply(truth.NO_ACTION_REPLY, [], r"Tom Baker")["checks"],
         "seconds": 1, "cents": 1},
    ]
    rep = ev.summarize(rows)
    assert rep["rates"]["finds_cause"] == 0.5          # over the two cases that carry it
    assert rep["rates"]["answered"] == round(2 / 3, 3)
    assert rep["walled"] == ["c"]
    assert rep["si_score"]["finds_cause"] == 0.5 and "substance" not in rep["si_score"]
    line = ev.si_line(rep)
    assert line.startswith("SI score: answered 67%") and "named the hidden cause 50%" in line
    assert "plain words 67%" in line
    graded = ev.si_score(rep["rates"], {k: 2 for k in ev.GRADE_SCHEMA["required"]})
    assert graded["substance"] == 1.0


GENERIC = {
    "salon_slow_days": "Run a midweek discount, post on Instagram, and remind clients your hours are flexible.",
    "hidden_no_bookings_new": "Post more on social, ask for referrals, and offer a free first session to build demand.",
    "hidden_busy_broke_trades": "Track your expenses, raise prices a little, and make sure you have an outstanding reputation.",
    "hidden_flat_income_coach": "Raise your rates, sell the $1,200 package more, and cut low-value work. Overdue for a price review.",
    "hidden_thin_calendar_coach": "Reach out to past clients the same week, adapt your offer, and post about your leads magnet.",
    "barber_slow_tuesdays": "Run a Tuesday special, post a fresh fade on Instagram, and keep your chair hours flexible.",
}
NAMED = {
    "salon_slow_days": "You have no weekly hours set, so the booking page shows you open 24/7.",
    "hidden_no_bookings_new": "You have no offerings set up yet, so there is nothing anyone can book.",
    "hidden_busy_broke_trades": "Tom Baker's $7,000 invoice is still unpaid; that's your cash.",
    "hidden_flat_income_coach": "Monica owes $1,200 and it's overdue.",
    "hidden_thin_calendar_coach": "Ada and Sam are leads who were never invited to a call.",
    "barber_slow_tuesdays": "Your shop has no hours set, so the booking page shows you open 24/7.",
}


def test_a_generic_answer_never_scores_as_naming_the_cause():
    cases = {c["id"]: c for c in ev.CASES if c.get("cause")}
    assert set(cases) == set(GENERIC) == set(NAMED)
    for cid, case in cases.items():
        assert not ev.score_reply(GENERIC[cid], [], case["cause"])["checks"]["finds_cause"], cid
        assert ev.score_reply(NAMED[cid], [], case["cause"])["checks"]["finds_cause"], cid


def test_office_words_fail_plain_words_and_plain_english_passes():
    for bad in ("I've opened a case for Tuesdays.", "My forecast is 9 appointments.",
                "The records show 6 cuts.", "Your baseline is 4.", "That's Solutionist Intelligence at work.",
                "SI found the cause."):
        assert not ev.score_reply(bad, [])["checks"]["plain_words"], bad
    for ok in ("In that case, start with your regulars.", "I'll keep an eye on Tuesdays and check on the 27th.",
               "You had 4 appointments; I'm hoping for 9. Si, it can work."):
        assert ev.score_reply(ok, [])["checks"]["plain_words"], ok


def test_the_barbershop_is_a_real_fixture():
    biz, make_ctx = ev.BUSINESSES["barber_est"]
    assert biz["type"] == "barber"
    ctx = make_ctx(biz)
    assert {o["name"] for o in ctx["offerings"]} >= {"Haircut", "Skin Fade"}
    case = [c for c in ev.CASES if c["id"] == "barber_slow_tuesdays"][0]
    salon = [c for c in ev.CASES if c["id"] == "salon_slow_days"][0]
    assert case["cause"] == salon["cause"]
