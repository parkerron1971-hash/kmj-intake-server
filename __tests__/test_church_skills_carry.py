"""A church job's steps carried to its follow-ups (church_skills.carried_block).

Kevin, 2026-11-27 (through KAI): the log check found the follow-up turn of a giving job ("ok, now record
it") had no steps. Carry them a turn or two, bounded so stale steps never reach an unrelated turn.

Pins:
  * a short follow-up right after a job's message gets that job's steps, marked as carried
  * turns: never more than CARRY_TURNS user messages back
  * time: the last turn over CARRY_MINUTES ago, or the job's message over CARRY_JOB_MINUTES ago, carries
    nothing
  * the same chat: the saved turns must be the history's own messages; another chat, a read that fails, or
    turns not saved by login carry nothing
  * a change of topic carries nothing: another job's words, a new-topic opening, a long new request, or a
    turn since the job's message that did other work
  * the login's key and the church's features still gate the carried job
  * a message that matches a job itself is never "carried" (it gets its own steps)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import church_skills as cs  # noqa: E402

CHURCH = {"id": "11111111-1111-4111-8111-111111111111", "owner_id": "o", "type": "church", "settings": {}}
CARE = {"areas": ["people_care"], "role": "manager", "lane": "people_care"}
ALL_ON = {"giving_services": True, "giving_deposits": True, "serving_spots": True}
NOW = datetime(2026, 11, 29, 17, 0, tzinfo=timezone.utc)
JOB = "Can you record Sunday's offering for the 22nd?"
REPLY = "Sure. Give me each giver, the amount and how they gave, and I'll record them."


def turn(on=True, ready=None):
    return cs.Turn(CHURCH, on, dict(ALL_ON if ready is None else ready))


def hist(*users):
    out = []
    for u in users:
        out += [{"role": "user", "content": u}, {"role": "assistant", "content": REPLY}]
    return out


def saved(*turns):
    """Saved turns newest first: (the user's message, minutes ago, the actions it ran)."""
    return [{"ended_at": (NOW - timedelta(minutes=m)).isoformat(), "key_topics": list(kinds),
             "messages": [{"role": "user", "content": u}, {"role": "assistant", "content": REPLY}]}
            for u, m, kinds in turns]


@pytest.fixture
def rows(monkeypatch):
    box = {"rows": [], "reads": 0}

    def read(bid, uid, n):
        box["reads"] += 1
        return None if box["rows"] is None else box["rows"][:n]
    monkeypatch.setattr(cs, "_saved_turns", read)
    return box


def carry(message, history, scope=None, t=None, uid="u-1"):
    return cs.carried_block(t or turn(), message, history, scope, uid, now=NOW)


# ─── It carries ───────────────────────────────────────────────────────

def test_a_follow_up_right_after_the_job_gets_its_steps_marked_carried(rows):
    rows["rows"] = saved((JOB, 2, ["giving_counts"]))
    out = carry("ok, now record it", hist(JOB))
    assert out.startswith("CHURCH JOB STEPS, CARRIED from this chat's message 1 turn ago")
    assert "only if this message continues that job" in out and "sunday-giving-count" in out
    assert "record_service_gifts" in out


def test_two_turns_back_while_the_turn_between_kept_to_the_job(rows):
    rows["rows"] = saved(("Maria gave 100 by check", 1, ["record_service_gifts"]), (JOB, 4, ["giving_counts"]))
    out = carry("and John gave 50 cash", hist(JOB, "Maria gave 100 by check"))
    assert "message 2 turns ago" in out


def test_the_serving_job_carries_too(rows):
    ask = "We need someone to serve on sound Sunday"
    rows["rows"] = saved((ask, 1, ["serving_spot"]))
    assert "fill-a-serving-spot" in carry("yes, ask Kendra", hist(ask))


# ─── Turns ────────────────────────────────────────────────────────────

def test_never_more_than_two_turns_back(rows):
    rows["rows"] = saved(("ok", 1, []), ("thanks", 2, []), (JOB, 3, []))
    assert carry("great", hist(JOB, "thanks", "ok")) == ""
    assert rows["reads"] == 0, "the history alone says no: nothing is read"


def test_no_job_in_the_history_reads_nothing(rows):
    assert carry("ok, do it", hist("what's the weather tomorrow")) == ""
    assert carry("ok, do it", []) == "" and carry("ok, do it", None) == ""
    assert rows["reads"] == 0


# ─── Time ─────────────────────────────────────────────────────────────

def test_a_stale_last_turn_carries_nothing(rows):
    rows["rows"] = saved((JOB, cs.CARRY_MINUTES + 1, []))
    assert carry("ok, now record it", hist(JOB)) == ""


def test_a_stale_job_message_carries_nothing_even_with_a_fresh_turn_between(rows):
    rows["rows"] = saved(("Maria gave 100", 5, []), (JOB, cs.CARRY_JOB_MINUTES + 1, []))
    assert carry("and John 50", hist(JOB, "Maria gave 100")) == ""


# ─── The same chat ────────────────────────────────────────────────────

def test_saved_turns_from_another_chat_carry_nothing(rows):
    rows["rows"] = saved(("what's on the calendar", 1, []))
    assert carry("ok, now record it", hist(JOB)) == ""


def test_a_read_that_fails_or_finds_nothing_carries_nothing(rows):
    rows["rows"] = None
    assert carry("ok, now record it", hist(JOB)) == ""
    rows["rows"] = []
    assert carry("ok, now record it", hist(JOB)) == ""
    assert carry("ok, now record it", hist(JOB), uid="") == ""


def test_the_history_that_already_holds_this_message_is_read_without_it(rows):
    rows["rows"] = saved((JOB, 2, []))
    h = hist(JOB) + [{"role": "user", "content": "ok, now record it"}]
    assert "1 turn ago" in carry("ok, now record it", h)


# ─── A change of topic ────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "also, who is preaching next week?",
    "different question: when is choir practice",
    "by the way the furnace is broken",
    "never mind",
    "run the giving statements for last year",           # another job's own words
    " ".join(["word"] * (cs.CONTINUE_WORDS + 1)),           # a long new request
])
def test_a_new_topic_carries_nothing(rows, message):
    rows["rows"] = saved((JOB, 1, []))
    assert carry(message, hist(JOB)) == "", message


def test_a_turn_between_that_did_other_work_is_a_new_topic(rows):
    rows["rows"] = saved(("send the note to the team", 1, ["send_sms"]), (JOB, 3, ["giving_counts"]))
    assert carry("ok, now record it", hist(JOB, "send the note to the team")) == ""


def test_a_turn_between_that_changed_topic_stops_the_carry(rows):
    rows["rows"] = saved(("by the way, the furnace", 1, []), (JOB, 3, []))
    assert carry("ok", hist(JOB, "by the way, the furnace")) == ""
    assert rows["reads"] == 0


def test_a_screen_move_beside_the_jobs_own_work_is_not_a_new_topic(rows):
    rows["rows"] = saved(("show me what is in it", 1, ["navigate", "giving_counts"]), (JOB, 3, ["giving_counts"]))
    assert "2 turns ago" in carry("ok, record Maria's 100", hist(JOB, "show me what is in it"))


# ─── After the Codex review ───────────────────────────────────────────

def test_a_turn_between_that_only_talked_is_a_new_topic(rows):
    """Codex: "Who is preaching Sunday?" ran nothing, so its empty list of actions passed as the job's."""
    rows["rows"] = saved(("is Pastor Ray preaching", 1, []), (JOB, 3, ["giving_counts"]))
    assert carry("ok", hist(JOB, "is Pastor Ray preaching")) == ""
    rows["rows"] = saved(("open the gifts page", 1, ["navigate"]), (JOB, 3, ["giving_counts"]))
    assert carry("ok", hist(JOB, "open the gifts page")) == "", "a screen move alone is not the job"


@pytest.mark.parametrize("message", ["Who is preaching Sunday?", "when is choir practice?", "what's for lunch?"])
def test_a_new_question_is_a_new_topic(rows, message):
    rows["rows"] = saved((JOB, 1, []))
    assert carry(message, hist(JOB)) == "", message


@pytest.mark.parametrize("kinds", [None, "giving_counts", [None], [1]])
def test_a_turn_between_whose_actions_cant_be_read_carries_nothing(rows, kinds):
    rows["rows"] = saved(("Maria gave 100", 1, []), (JOB, 3, []))
    rows["rows"][0]["key_topics"] = kinds
    assert carry("and John 50", hist(JOB, "Maria gave 100")) == ""


def test_malformed_saved_turns_carry_nothing(rows):
    for bad in ({"ended_at": NOW.isoformat()}, {"ended_at": NOW.isoformat(), "messages": "x"},
                {"ended_at": "not a time", "messages": [{"role": "user", "content": JOB}]},
                {"ended_at": NOW.isoformat(), "messages": [{"role": "assistant", "content": JOB}]}):
        rows["rows"] = [bad]
        assert carry("ok, now record it", hist(JOB)) == "", bad


def test_the_whole_message_must_match_not_its_opening(rows):
    long_job = JOB + " " + "x" * 200
    rows["rows"] = saved((long_job + " but a different ending", 1, []))
    assert carry("ok, now record it", hist(long_job)) == ""
    rows["rows"] = saved((long_job, 1, []))
    assert "1 turn ago" in carry("ok, now record it", hist(long_job))


def test_the_time_bounds_are_strict_and_the_future_is_refused(rows):
    rows["rows"] = saved((JOB, cs.CARRY_MINUTES, []))
    assert carry("ok, now record it", hist(JOB)) == "", "exactly 30 minutes is not under 30"
    rows["rows"] = saved((JOB, -5, []))
    assert carry("ok, now record it", hist(JOB)) == "", "five minutes in the future"
    rows["rows"] = saved((JOB, -0.5, []))
    assert carry("ok, now record it", hist(JOB)), "half a minute of another replica's clock is fine"


def test_only_one_turn_rows_are_read():
    import inspect
    assert "message_count=eq.2" in inspect.getsource(cs._saved_turns), "the browser's whole-chat rows are left out"


# ─── The gates still hold ─────────────────────────────────────────────

def test_the_logins_key_and_the_churchs_features_still_gate_it(rows):
    rows["rows"] = saved((JOB, 1, []))
    assert carry("ok, now record it", hist(JOB), scope=CARE) == "", "care has no Giving & money"
    assert carry("ok, now record it", hist(JOB), t=turn(ready={**ALL_ON, "giving_services": False})) == ""
    assert carry("ok, now record it", hist(JOB), t=turn(on=False)) == ""


def test_a_message_that_names_a_job_gets_its_own_steps_never_a_carry(rows):
    rows["rows"] = saved((JOB, 1, []))
    assert carry("record the offering for the 29th too", hist(JOB)) == ""
    assert cs.turn_block(turn(), "record the offering for the 29th too", None).startswith(
        "CHURCH JOB STEPS: sunday-giving-count")


def test_the_chat_turn_carries_only_when_this_message_named_no_job():
    import inspect
    import chief_of_staff
    src = inspect.getsource(chief_of_staff)
    fresh = src.index("_job_steps = _church_skills.turn_block(")
    carried = src.index("_church_skills.carried_block", fresh)
    assert "if not _job_steps and _skills_turn.on:" in src[fresh:carried]
    assert carried < src.index("_login_block = chief_areas.block(", fresh), "the tail, before the login block"
