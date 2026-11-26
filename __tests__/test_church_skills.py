"""Written steps for church jobs, loaded only when a job needs them (church_skills).

Kevin, 2026-11-26: "Church Skills for Chief", with his cost idea (only the
contents ride every turn; a chapter is loaded for the turn that needs it, and
only for a login with the key to that job).

Pins:
  * every skill file parses, names only Chief's own actions, and its steps
    never mention an action it doesn't list
  * the contents carry one line per skill; a chapter comes only with a message
    that matches its words, and only for a login that may use every action it
    names
  * the same gate holds for the action_guide lookup by name
  * off by default; "owner" is the platform owner's church only; never the
    sample church or a business that isn't a church
  * only adds: the manual is not shortened
"""
from __future__ import annotations

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import action_registry  # noqa: E402
import chief_areas as ca  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import church_skills as cs  # noqa: E402

CHURCH = {"id": "11111111-1111-4111-8111-111111111111", "owner_id": "o", "type": "church", "settings": {}}
COACH = {"id": "22222222-2222-4222-8222-222222222222", "owner_id": "o", "type": "coach", "settings": {}}
CARE = {"areas": ["people_care"], "role": "manager", "lane": "people_care"}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("CHIEF_CHURCH_SKILLS", "on")
    import sample_church
    monkeypatch.setattr(sample_church, "is_sample", lambda bid: False)
    cs._TURN.set(None)
    yield
    cs._TURN.set(None)


# ─── The files ────────────────────────────────────────────────────────

def test_the_two_starting_skills_parse_and_name_only_chiefs_own_actions():
    names = [s["name"] for s in cs.skills()]
    assert names == ["sunday-giving-count", "year-end-giving-statements"]
    for s in cs.skills():
        assert s["use_when"] and s["triggers"] and s["actions"]
        for v in s["actions"]:
            assert v in cos.ACTION_HANDLERS, f"{s['name']}: {v} has no handler"
            assert action_registry.classification(v), f"{s['name']}: {v} is unclassified"
        for section in ("STEPS", "HAND BACK", "NEVER"):
            assert section in s["body"], (s["name"], section)


def test_a_skills_steps_mention_only_the_actions_it_lists():
    """A step that uses an action the skill doesn't list would slip past the key check."""
    verbs = set(cos.ACTION_HANDLERS)
    for s in cs.skills():
        named = {w for w in re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", s["body"]) if w in verbs}
        assert named <= set(s["actions"]), (s["name"], named - set(s["actions"]))


def test_a_file_without_its_fields_is_not_a_skill():
    assert cs.parse("no frontmatter") is None
    assert cs.parse("---\nname: x\n---\nbody") is None
    assert cs.parse("---\nname: x\nuse_when: y\nactions: a\n---\n") is None
    got = cs.parse("---\nname: x\nuse_when: y\ntriggers: a, b c\nactions: v_one, v_two\n---\nSTEPS\n1. go")
    assert got["triggers"] == ["a", "b c"] and got["actions"] == ["v_one", "v_two"]


# ─── Which turn gets which chapter ────────────────────────────────────

@pytest.mark.parametrize("message,skill", [
    ("Can you record Sunday's offering? Grace gave 100 by check", "sunday-giving-count"),
    ("did the plate money make it to the bank", "sunday-giving-count"),
    ("run the year-end giving statements for 2025", "year-end-giving-statements"),
    ("I need Marcus's contribution statement", "year-end-giving-statements"),
])
def test_a_message_that_matches_gets_that_chapter_for_the_owner(on, message, skill):
    block = cs.turn_block(CHURCH, message, None)
    assert block.startswith(f"CHURCH JOB STEPS: {skill} ") and "STEPS" in block
    assert block.count("CHURCH JOB STEPS:") == 1


@pytest.mark.parametrize("message", ["what time is choir practice", "who is serving Sunday", "accountant discount"])
def test_a_message_that_matches_no_skill_gets_nothing(on, message):
    assert cs.turn_block(CHURCH, message, None) == ""


def test_a_word_inside_another_word_doesnt_match(on):
    assert cs.turn_block(CHURCH, "the counter is broken", None) == ""
    assert cs.turn_block(CHURCH, "our account manager", None) == ""


def test_a_login_without_the_key_to_the_job_is_handed_nothing(on):
    """Kevin's rule: check the login's key BEFORE loading a chapter. A care login has no Giving & money."""
    for s in cs.skills():
        assert not cs.allowed(s, CARE), s["name"]
    assert cs.turn_block(CHURCH, "record Sunday's offering", CARE) == ""
    assert cs.turn_block(CHURCH, "run the year-end statements", CARE) == ""
    money = {"areas": ["office", "giving_money"], "role": "manager", "lane": "office"}
    assert cs.turn_block(CHURCH, "record Sunday's offering", money).startswith("CHURCH JOB STEPS: sunday-giving-count")
    # A login that only SEES giving (the giving tick, can_work off) can't record or match: no chapter for the job.
    sees = {"areas": ["office", "giving_money"], "role": "manager", "lane": "office", "money": {"can_work": False}}
    assert cs.turn_block(CHURCH, "record Sunday's offering", sees) == ""


def test_the_lookup_by_name_has_the_same_gate(on):
    assert cs.lookup("sunday-giving-count") is None, "outside a turn"
    cs.begin_turn(CHURCH, None)
    assert cs.lookup("sunday-giving-count").startswith("CHURCH JOB STEPS: sunday-giving-count")
    assert cs.lookup("Sunday giving count").startswith("CHURCH JOB STEPS: sunday-giving-count")
    assert cs.lookup("not-a-skill") is None
    cs.begin_turn(CHURCH, CARE)
    assert cs.lookup("sunday-giving-count") is None
    cs.begin_turn(COACH, None)
    assert cs.lookup("sunday-giving-count") is None


def test_the_lean_manuals_lookup_answers_with_a_chapter(on):
    import chief_lean_brief
    cs.begin_turn(CHURCH, None)
    is_error, content = chief_lean_brief.tool_result({"name": "year-end-giving-statements"})
    assert not is_error and content.startswith("CHURCH JOB STEPS: year-end-giving-statements")
    cs.begin_turn(CHURCH, CARE)
    is_error, content = chief_lean_brief.tool_result({"name": "year-end-giving-statements"})
    assert is_error, "no key, no chapter"


def test_the_contents_are_one_line_a_skill(on):
    text = cs.contents_for(CHURCH)
    assert text.startswith("CHURCH JOBS WITH WRITTEN STEPS")
    assert text.count("\n  ") == len(cs.skills()) and "action_guide" in text
    for s in cs.skills():
        assert f"  {s['name']}: {s['use_when']}" in text
        assert s["body"][:40] not in text, "only the contents, never the chapters"


# ─── The switch ───────────────────────────────────────────────────────

def test_off_by_default(monkeypatch):
    monkeypatch.delenv("CHIEF_CHURCH_SKILLS", raising=False)
    assert cs.mode() == "off"
    assert cs.contents_for(CHURCH) == "" and cs.turn_block(CHURCH, "record Sunday's offering", None) == ""


def test_owner_is_the_platform_owners_church_only(monkeypatch):
    monkeypatch.setenv("CHIEF_CHURCH_SKILLS", "owner")
    import member_asks
    import sample_church
    monkeypatch.setattr(sample_church, "is_sample", lambda bid: False)
    monkeypatch.setattr(member_asks, "platform_church", lambda bid: bid == CHURCH["id"])
    assert cs.switched_on(CHURCH)
    assert not cs.switched_on(dict(CHURCH, id="33333333-3333-4333-8333-333333333333"))
    monkeypatch.setattr(member_asks, "platform_church", lambda bid: (_ for _ in ()).throw(RuntimeError("down")))
    assert not cs.switched_on(CHURCH), "can't tell: off"


def test_never_the_sample_church_or_a_business_that_isnt_a_church(on, monkeypatch):
    assert not cs.switched_on(COACH) and not cs.switched_on(None) and not cs.switched_on({})
    import sample_church
    monkeypatch.setattr(sample_church, "is_sample", lambda bid: True)
    assert not cs.switched_on(CHURCH)


# ─── Wired into the turn, adding only ─────────────────────────────────

def test_it_rides_the_turn_and_the_per_church_segment_and_only_adds():
    import inspect
    import chief_prompt
    chat = inspect.getsource(cos.chief_chat)
    at = chat.index("_church_skills.turn_block(")
    assert at < chat.index("_login_block = chief_areas.block("), "the turn's tail, before the login's block"
    assert "_church_skills.begin_turn(biz, chief_areas.TURN.get())" in chat
    assert "church_skills_contents=" in chat
    src = inspect.getsource(chief_prompt)
    seg = src[src.index('return _universal + f"""[[CHIEF_GLOBAL_SPLIT]]'):]
    assert seg.index("{church_skills_block}") < seg.index("[[CHIEF_CACHE_SPLIT]]")
    # Only adds: the giving lines of the manual are all still there.
    for line in ("[ACTION:{{\"type\":\"record_service_gifts\"", "[ACTION:{{\"type\":\"giving_statements_run\"}}]",
                 "[ACTION:{{\"type\":\"match_giving_deposits\"}}]"):
        assert line in src, line
    assert "CHIEF_CHURCH_SKILLS=" in open(os.path.join(ROOT, ".env.example"), encoding="utf-8").read()
