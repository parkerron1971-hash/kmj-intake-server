"""
test_chief_first_words.py — Chief's first greeting to a new practitioner.

The first-run greeting is the best new-user moment in the product, and
four things were wrong with it (2026-09-26):

  a) THE DAY WAS A FLOAT. week_day was _business_age_days + 1, and that
     is a float, so the prompt read "FIRST WEEK, DAY 3.4166…". The old
     tests passed week_day=3 by hand and never saw it. The day now comes
     from the day-one arc (first_run_arc.day_of, trial-anchored, whole
     days) and falls back to the business's age, floored.
  b) TWO SHAPES AT ONCE. On days two to seven the model-judged LAUNCH
     GREETING ("list the 3-4 steps") rode alongside FIRST WEEK ("no
     list"). Now one or the other.
  c) THE INTRODUCTION WAS SPENT BEFORE IT WAS SAID. The arc was stamped
     intro-delivered before the reply was even generated, so a failed or
     withheld greeting used up the one introduction. It is stamped only
     after a checked reply goes out.
  d) THE WELCOME NOTE READ AS WORK. Onboarding's agent_queue row (agent
     'system', status 'draft') made the first greeting say "1 waiting
     for your review". Chief's queue read and the brief counts drop it —
     that exact row, never a real draft.

These drive the real code: the real chief_chat computing week_day and
first_run, the real prompt composer, the real _gather_context.

House rules: sync tests + asyncio.run (no pytest-asyncio in this repo).
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import chief_of_staff as cos  # noqa: E402
import chief_truth  # noqa: E402
import first_run_arc as fra  # noqa: E402
import onboarding_welcome as ow  # noqa: E402
from test_first_run_concierge import _EmptyCtx  # noqa: E402
from test_gather_context_wave2 import gather  # noqa: E402,F401  (fixture)

GREETING = "[SYSTEM:opening_greeting:morning]"

WELCOME_ROW = {"id": "q-welcome", "agent": "system", "action_type": "other",
               "subject": "Welcome to The Solutionist System, Marcus!",
               "priority": "medium", "status": "draft",
               "ai_reasoning": "Standard welcome message created at onboarding."}
REAL_DRAFT = {"id": "q-real", "agent": "nurture", "action_type": "email",
              "subject": "Checking in after your first cut", "priority": "high",
              "status": "draft", "ai_reasoning": "Two weeks since the last visit."}


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _biz(days_old: float) -> dict:
    return {"id": "biz-1", "name": "Fade Society", "type": "personal_services",
            "owner_id": "user-1", "created_at": _ago(days_old),
            "settings": {"practitioner_name": "Marcus Reed"}}


def _snapshot(done: int, total: int = 4) -> dict:
    items = [{"key": f"k{i}", "title": f"Step {i}", "why": "because",
              "nav": {"tab": "build", "page": "booking"},
              "done": i < done, "blocked_by": []} for i in range(total)]
    return {"items": items, "done": done, "total": total, "artifact": {}}


# ─── a greeting turn through the real chief_chat ─────────────────────

@pytest.fixture
def greet(monkeypatch):
    """Drive chief_chat on a greeting with the I/O stubbed. Records what
    the prompt composer was told, when the answer check ran, and when the
    introduction was stamped."""
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow", lambda *a, **k: True)

    async def _instant(value=None):
        return value

    state = {"biz": _biz(0.3), "arc": None, "snapshot": _snapshot(0),
             "reply": "Good morning, Marcus.", "status": "supported"}
    log: list = []
    prompt_kwargs: dict = {}

    async def _fake_sb(client, method, path, body=None):
        return [state["biz"]]
    monkeypatch.setattr(cos, "_sb", _fake_sb)
    monkeypatch.setattr(cos, "_generate_missing_recurring_instances", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_autopilot_sweep", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_evaluate_escalations", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_gather_context",
                        lambda *a, **k: _instant({"business": state["biz"], "contacts": []}))
    monkeypatch.setattr(cos, "_fetch_view_detail", lambda *a, **k: _instant(""))
    for name in ["_get_voice_examples", "_get_session_context",
                 "_get_time_context", "_get_habit_insights"]:
        monkeypatch.setattr(cos, name, lambda *a, **k: _instant(""))
    monkeypatch.setattr(cos, "_should_show_mentor_tip", lambda *a, **k: _instant(False))
    monkeypatch.setattr(cos, "_forecast_revenue", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_analyze_relationships", lambda *a, **k: _instant([]))
    monkeypatch.setattr(cos, "_log_chief_activity", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_learn_patterns_async", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_fetch_setup_snapshot", lambda biz: state["snapshot"])
    monkeypatch.setattr(fra, "state", lambda business_id: state["arc"])

    def _prompt(*a, **k):
        prompt_kwargs.clear()
        prompt_kwargs.update(k)
        return "SYSTEM"
    monkeypatch.setattr(cos, "_build_system_prompt", _prompt)

    async def _claude(*a, **k):
        log.append("model")
        return state["reply"]
    monkeypatch.setattr(cos, "_call_claude", _claude)

    async def _finalize(client, reply, **k):
        log.append("check")
        if state["status"] == "withheld":
            return chief_truth.UNVERIFIED_REPLY, {"status": "withheld", "sources": []}
        return reply, {"status": state["status"], "sources": []}
    monkeypatch.setattr(chief_truth, "finalize_reply", _finalize)
    monkeypatch.setattr(cos, "_note_intro_delivered",
                        lambda business_id: log.append(("intro", business_id)))

    import chief_bookkeeping
    import chief_proactive_suggestions
    import vertical_context
    monkeypatch.setattr(chief_bookkeeping, "gather_and_format", lambda *a, **k: "")
    monkeypatch.setattr(vertical_context, "build_vertical_learned_block", lambda *a, **k: "")
    monkeypatch.setattr(chief_proactive_suggestions,
                        "maybe_emit_proactive_suggestions", lambda *a, **k: None)

    class _Session:
        class _User:
            id = "user-1"
        user = _User()
        token = "test-jwt"

    def run(**over):
        state.update(over)
        log.clear()
        out = asyncio.run(cos.chief_chat(
            cos.ChatRequest(business_id="biz-1", message=GREETING), _Session()))
        return out, dict(prompt_kwargs), list(log)

    return run


# a) the day is a whole number, computed for real

def test_the_week_day_chief_is_told_is_a_whole_day(greet):
    # 2.4 days old: the old code sent week_day=3.4 into the prompt.
    _, kw, _ = greet(biz=_biz(2.4), snapshot=_snapshot(1),
                     arc={"started_at": _ago(2.4), "intro_delivered_at": _ago(2.3)})
    assert kw["week_day"] == 3 and isinstance(kw["week_day"], int)
    assert kw["first_run"] is False


def test_the_real_prompt_says_the_day_without_a_fraction(greet, monkeypatch):
    _, kw, _ = greet(biz=_biz(2.4), snapshot=_snapshot(1),
                     arc={"started_at": _ago(2.4), "intro_delivered_at": _ago(2.3)})
    monkeypatch.undo()  # the real composer, fed what the real turn computed
    import chief_prompt
    text = chief_prompt._build_system_prompt(
        _EmptyCtx(business=_biz(2.4)), True, time_of_day="morning",
        setup_block="SETUP STATUS — x", first_run=kw["first_run"],
        week_day=kw["week_day"])
    assert "FIRST WEEK, DAY 3 —" in text
    assert "DAY 3." not in text


def test_the_trial_anchors_the_week_not_the_signup(greet):
    # Signed up three weeks ago, trial started four days ago: day five of
    # THEIR week, which the business's age could never say.
    _, kw, _ = greet(biz=_biz(21.5), snapshot=_snapshot(1),
                     arc={"started_at": _ago(4.2), "intro_delivered_at": _ago(4.1)})
    assert kw["week_day"] == 5


def test_without_an_arc_the_business_age_is_the_fallback(greet):
    _, kw, _ = greet(biz=_biz(5.9), snapshot=_snapshot(3), arc=None)
    assert kw["week_day"] == 6 and isinstance(kw["week_day"], int)


def test_past_day_seven_there_is_no_week_read(greet):
    _, kw, _ = greet(biz=_biz(7.2), snapshot=_snapshot(1),
                     arc={"started_at": _ago(7.2), "intro_delivered_at": _ago(7.1)})
    assert kw["week_day"] == 0


def test_first_week_day_unit():
    assert cos._first_week_day(_biz(0.2), None) == 1
    assert cos._first_week_day(_biz(6.99), None) == 7
    assert cos._first_week_day(_biz(30), {"started_at": _ago(1.5)}) == 2
    assert cos._first_week_day({"created_at": "not a date"}, {"started_at": "nope"}) == 0


# b) days two to seven get ONE shape

def test_days_two_to_seven_never_carry_the_launch_list():
    import chief_prompt
    text = chief_prompt._build_system_prompt(
        _EmptyCtx(business=_biz(3)), True, time_of_day="morning",
        setup_block="SETUP STATUS — x", week_day=4)
    assert "FIRST WEEK, DAY 4" in text and "no list" in text
    assert "LAUNCH GREETING" not in text
    assert "3-4 highest-leverage launch steps" not in text


def test_the_fallback_launch_plan_stays_when_nothing_is_measured():
    import chief_prompt
    text = chief_prompt._build_system_prompt(
        _EmptyCtx(business=_biz(3)), True, time_of_day="morning")
    assert "3-4 highest-leverage launch steps" in text
    assert "FIRST WEEK, DAY" not in text


# c) the introduction is spent only on a reply that went out

def test_the_launch_greeting_is_stamped_after_the_checked_reply(greet):
    out, kw, log = greet(arc={"started_at": _ago(0.3), "intro_delivered_at": None})
    assert kw["first_run"] is True
    assert out["response"] == "Good morning, Marcus."
    assert ("intro", "biz-1") in log
    assert log.index("check") < log.index(("intro", "biz-1")), (
        "the introduction may only be stamped after the answer check")


def test_a_withheld_greeting_leaves_the_introduction_owed(greet):
    _, kw, log = greet(arc={"started_at": _ago(0.3), "intro_delivered_at": None},
                       status="withheld")
    assert kw["first_run"] is True
    assert "check" in log
    assert not any(isinstance(e, tuple) and e[0] == "intro" for e in log)


def test_a_failed_greeting_leaves_the_introduction_owed(greet):
    out, _, log = greet(arc={"started_at": _ago(0.3), "intro_delivered_at": None},
                        reply="")
    assert "trouble connecting" in out["response"]
    assert not any(isinstance(e, tuple) and e[0] == "intro" for e in log)


def test_a_delivered_introduction_is_not_said_or_stamped_again(greet):
    _, kw, log = greet(arc={"started_at": _ago(0.3), "intro_delivered_at": _ago(0.2)})
    assert kw["first_run"] is False
    assert not any(isinstance(e, tuple) and e[0] == "intro" for e in log)


def test_an_ordinary_greeting_never_stamps(greet):
    # Plenty connected: no launch script, nothing to stamp.
    _, kw, log = greet(snapshot=_snapshot(3), arc={"started_at": _ago(0.3),
                                                   "intro_delivered_at": None})
    assert kw["first_run"] is False
    assert not any(isinstance(e, tuple) and e[0] == "intro" for e in log)


def test_intro_went_out_unit():
    assert cos._intro_went_out("Hello", {"status": "supported"})
    assert cos._intro_went_out("Hello", {"status": "caveated"})
    assert not cos._intro_went_out("I couldn't verify that.", {"status": "withheld"})
    assert not cos._intro_went_out("   ", {"status": "supported"})


def test_nothing_stamps_the_introduction_before_the_reply():
    # Stream and plain paths both run chief_chat; the stamp lives at its end.
    src = inspect.getsource(cos.chief_chat)
    assert "mark_intro_delivered" not in src
    assert src.index("chief_truth.finalize_reply(") < src.index("_note_intro_delivered(")


# d) the onboarding welcome note is not a draft waiting on anyone

def test_only_the_exact_welcome_row_is_dropped():
    system_other = dict(WELCOME_ROW, id="q-sys", ai_reasoning="Invoice reminder batch.")
    same_words_other_agent = dict(WELCOME_ROW, id="q-agent", agent="nurture")
    kept = ow.without_welcome([WELCOME_ROW, REAL_DRAFT, system_other,
                               same_words_other_agent])
    assert [r["id"] for r in kept] == ["q-real", "q-sys", "q-agent"]
    assert all("ai_reasoning" not in r for r in kept)
    assert ow.without_welcome(None) is None, "a failed read is not an empty queue"
    assert ow.without_welcome([WELCOME_ROW], keep_reasoning=True) == []


def test_chiefs_queue_read_drops_the_welcome_note(gather, monkeypatch):
    biz = _biz(0.5)

    async def _sb(client, method, path, body=None):
        if path.startswith("/businesses"):
            return [dict(biz)]
        if path.startswith("/agent_queue"):
            assert "ai_reasoning" in path, "the row cannot be recognised without it"
            return [dict(WELCOME_ROW), dict(REAL_DRAFT)]
        return []
    monkeypatch.setattr(cos, "_sb", _sb)
    _, ctx = gather()
    assert [q["id"] for q in ctx["queue"]] == ["q-real"]
    assert [q["id"] for q in ctx["recent_queue_24h"]] == ["q-real"]
    assert all("ai_reasoning" not in q for q in ctx["queue"] + ctx["recent_queue_24h"])


def test_a_new_business_with_only_the_welcome_note_has_nothing_waiting(gather, monkeypatch):
    async def _sb(client, method, path, body=None):
        if path.startswith("/businesses"):
            return [dict(_biz(0.5))]
        if path.startswith("/agent_queue"):
            return [dict(WELCOME_ROW)]
        return []
    monkeypatch.setattr(cos, "_sb", _sb)
    _, ctx = gather()
    assert ctx["queue"] == []
    priorities = cos._build_daily_priorities(ctx["business"], ctx)
    assert not any("waiting for your review" in p for p in priorities)


def test_the_morning_brief_does_not_count_the_welcome_note(monkeypatch):
    import notification_engine as ne

    async def _sb(client, method, path, body=None):
        if path.startswith("/agent_queue") and "channel=eq.action" not in path \
                and "priority=eq.urgent" not in path:
            return [dict(WELCOME_ROW), dict(REAL_DRAFT)]
        return []
    monkeypatch.setattr(ne, "_sb", _sb)
    morning = asyncio.run(ne._gather_morning_data(None, "biz-1"))
    assert [r["id"] for r in morning["pending"]] == ["q-real"]
    evening = asyncio.run(ne._gather_evening_data(None, "biz-1"))
    assert [r["id"] for r in evening["pending_carryover"]] == ["q-real"]
