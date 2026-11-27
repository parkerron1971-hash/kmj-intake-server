"""Written steps for church jobs, loaded only when a job needs them (church_skills).

Kevin, 2026-11-26: "Church Skills for Chief", with his cost idea (only the
contents ride every turn; a job's steps are loaded for the turn that needs
them, and only for a login with the key to that job).

Pins:
  * every skill file parses, names only Chief's own actions, and its steps
    never mention an action it doesn't list
  * the contents carry one line per job the church can do; a job's steps come
    only with a message that asks for that job, and only for a login that may
    use every action it names, at a church where its features are on
  * the giving keeper with a Work tick gets the Sunday count's steps
  * ordinary church words that only sound like a job load nothing
  * the same gate holds for the action_guide lookup by name
  * off by default; "owner" is the platform owner's church only; only with the
    short manual; never the sample church or a business that isn't a church
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
import chief_of_staff as cos  # noqa: E402
import church_skills as cs  # noqa: E402

CHURCH = {"id": "11111111-1111-4111-8111-111111111111", "owner_id": "o", "type": "church", "settings": {}}
COACH = {"id": "22222222-2222-4222-8222-222222222222", "owner_id": "o", "type": "coach", "settings": {}}
CARE = {"areas": ["people_care"], "role": "manager", "lane": "people_care"}
MONEY = {"areas": ["office", "giving_money"], "role": "manager", "lane": "office"}
KEEPER_WORKS = {"areas": ["office", "giving_money"], "role": "manager", "lane": "office",
                "money": {"level": "work", "can_work": True}}
KEEPER_SEES = {"areas": ["office", "giving_money"], "role": "manager", "lane": "office",
               "money": {"level": "see", "can_work": False}}
ALL_ON = {"giving_services": True, "giving_deposits": True, "serving_spots": True}


def turn(biz=CHURCH, on=True, ready=None):
    return cs.Turn(biz, on, dict(ALL_ON if ready is None else ready))


@pytest.fixture(autouse=True)
def clean():
    cs._TURN.set(None)
    yield
    cs._TURN.set(None)


def steps(message, scope=None, t=None):
    return cs.turn_block(t or turn(), message, scope)


# ─── The files ────────────────────────────────────────────────────────

def test_the_starting_skills_parse_and_name_only_chiefs_own_actions():
    assert [s["name"] for s in cs.skills()] == ["fill-a-serving-spot", "giving-bank-match", "sunday-giving-count",
                                                "year-end-giving-statements"]
    for s in cs.skills():
        assert s["use_when"] and s["triggers"] and s["actions"]
        for v in s["actions"]:
            assert v in cos.ACTION_HANDLERS, f"{s['name']}: {v} has no handler"
            assert action_registry.classification(v), f"{s['name']}: {v} is unclassified"
        for n in s["needs"]:
            assert n in cs.NEEDS, (s["name"], n)
        for section in ("STEPS", "HAND BACK", "NEVER"):
            assert section in s["body"], (s["name"], section)


def test_a_skills_steps_mention_only_the_actions_it_lists():
    """A step that used an action the skill doesn't list would slip past the key check."""
    verbs = set(cos.ACTION_HANDLERS)
    for s in cs.skills():
        named = {w for w in re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", s["body"]) if w in verbs}
        assert named <= set(s["actions"]), (s["name"], named - set(s["actions"]))


def test_the_steps_say_what_the_handlers_really_do():
    count = next(s for s in cs.skills() if s["name"] == "sunday-giving-count")["body"]
    assert "look again with giving_counts" in count, "record_service_gifts returns no totals by way"
    assert "up to 50 gifts at a time" in count
    from chief_giving_counts import MAX_GIFTS
    assert MAX_GIFTS == 50
    years = next(s for s in cs.skills() if s["name"] == "year-end-giving-statements")["body"]
    assert 'pass it as "year" every time' in years, "the handler picks this year from July"
    assert "loose plate cash and gifts given anonymously on purpose" in years
    assert "contact id" in years


def test_a_file_without_its_fields_is_not_a_skill():
    assert cs.parse("no frontmatter") is None
    assert cs.parse("---\nname: x\n---\nbody") is None
    assert cs.parse("---\nname: x\nuse_when: y\nactions: a\n---\n") is None
    got = cs.parse("---\nname: x\nuse_when: y\ntriggers: a, b c\nactions: v_one, v_two\nneeds: q\n---\nSTEPS\n1. go")
    assert got["triggers"] == ["a", "b c"] and got["actions"] == ["v_one", "v_two"] and got["needs"] == ["q"]


# ─── Which turn gets which steps ──────────────────────────────────────

@pytest.mark.parametrize("message,skill", [
    ("Can you record Sunday's offering? Grace gave 100 by check", "sunday-giving-count"),
    ("what's in the count for second service", "sunday-giving-count"),
    ("did Sunday's plate money make it to the bank", "giving-bank-match"),
    ("match the deposits please", "giving-bank-match"),
    ("run the year-end giving statements for 2025", "year-end-giving-statements"),
    ("I need Marcus's contribution statement", "year-end-giving-statements"),
])
def test_a_message_that_asks_for_a_job_gets_its_steps(message, skill):
    block = steps(message)
    assert block.startswith(f"CHURCH JOB STEPS: {skill} ") and "STEPS" in block
    assert block.count("CHURCH JOB STEPS:") == 1


@pytest.mark.parametrize("message", [
    "what time is choir practice", "who is serving Sunday", "head count for the retreat", "count me in",
    "does this count as attendance", "count the chairs", "the deposit for the venue", "bring a plate to the potluck",
    "we're offering a class on Tuesday", "the bank called about our loan", "can you update our statement of faith",
    "write a mission statement", "a statement to the press", "the end of year party", "my bank statement is late",
])
def test_ordinary_church_words_that_only_sound_like_a_job_load_nothing(message):
    assert steps(message) == "", message


def test_a_word_inside_another_word_doesnt_match():
    assert steps("the countdown is broken") == "" and steps("our account manager") == ""


# ─── The key, and the church's features ───────────────────────────────

def test_a_login_without_the_key_to_the_job_is_handed_nothing():
    """Kevin's rule: check the login's key BEFORE loading a job's steps. A care login has no Giving & money."""
    for s in cs.skills():
        if s["name"] == "fill-a-serving-spot":
            continue        # who schedules a team is the serving page's, by duties, never a lane: below
        assert not cs.allowed(s, CARE, ALL_ON), s["name"]
    assert steps("record Sunday's offering", CARE) == "" and steps("run the giving statements", CARE) == ""


def test_the_serving_spot_steps_follow_the_page_not_a_lane():
    """Who may schedule which team is sunday_planning's (_scheduler: the owner, Admins, and whoever holds a
    duty that schedules a team's door), and a duty can move to any office lane, so no lane is refused the
    steps; the page refuses whoever schedules nothing. A church where the switch is off gets none."""
    spot = next(s for s in cs.skills() if s["name"] == "fill-a-serving-spot")
    assert cs.allowed(spot, CARE, ALL_ON) and cs.allowed(spot, MONEY, ALL_ON)
    assert steps("we need someone to serve on sound Sunday", CARE).startswith("CHURCH JOB STEPS: fill-a-serving-spot")
    assert steps("we need someone to serve on sound Sunday", None, turn(ready={**ALL_ON, "serving_spots": False})) == ""


def test_the_giving_keeper_who_works_gets_the_count_and_one_who_only_sees_does_not():
    assert steps("record Sunday's offering", MONEY).startswith("CHURCH JOB STEPS: sunday-giving-count")
    assert steps("record Sunday's offering", KEEPER_WORKS).startswith("CHURCH JOB STEPS: sunday-giving-count")
    assert steps("record Sunday's offering", KEEPER_SEES) == "", "can't record: no steps for recording"


def test_a_church_whose_features_are_off_gets_no_steps_for_them():
    t = turn(ready={"giving_services": True, "giving_deposits": False})
    assert steps("match the deposits", None, t) == ""
    assert steps("record Sunday's offering", None, t).startswith("CHURCH JOB STEPS: sunday-giving-count")
    t = turn(ready={})
    assert steps("record Sunday's offering", None, t) == ""
    assert steps("run the giving statements", None, t).startswith("CHURCH JOB STEPS: year-end-giving-statements")
    text = cs.contents_for(t)
    assert "year-end-giving-statements" in text and "sunday-giving-count" not in text and "giving-bank-match" not in text


def test_features_on_reads_each_feature_and_cant_tell_is_off(monkeypatch):
    import giving_deposits
    import giving_ways
    monkeypatch.setattr(giving_ways, "switched_on", lambda bid: True)
    monkeypatch.setattr(giving_deposits, "switched_on", lambda bid: (_ for _ in ()).throw(RuntimeError("down")))
    import chief_serving_spots
    monkeypatch.setattr(chief_serving_spots, "turn_ready", lambda bid: True)
    assert cs.features_on(CHURCH) == {"giving_services": True, "giving_deposits": False, "serving_spots": True}
    assert cs.features_on(None) == {"giving_services": False, "giving_deposits": False, "serving_spots": False}


def test_the_lookup_by_name_has_the_same_gate():
    assert cs.lookup("sunday-giving-count") is None, "outside a turn"
    cs.begin_turn(turn(), None)
    assert cs.lookup("sunday-giving-count").startswith("CHURCH JOB STEPS: sunday-giving-count")
    assert cs.lookup("Sunday giving count").startswith("CHURCH JOB STEPS: sunday-giving-count")
    assert cs.lookup("sunday_giving_count").startswith("CHURCH JOB STEPS: sunday-giving-count")
    assert cs.lookup("not-a-skill") is None
    cs.begin_turn(turn(), CARE)
    assert cs.lookup("sunday-giving-count") is None
    cs.begin_turn(turn(ready={}), None)
    assert cs.lookup("sunday-giving-count") is None
    cs.begin_turn(turn(on=False), None)
    assert cs.lookup("sunday-giving-count") is None


def test_the_lean_manuals_lookup_answers_with_a_jobs_steps():
    import chief_lean_brief
    cs.begin_turn(turn(), None)
    is_error, content = chief_lean_brief.tool_result({"name": "year-end-giving-statements"})
    assert not is_error and content.startswith("CHURCH JOB STEPS: year-end-giving-statements")
    cs.begin_turn(turn(), CARE)
    is_error, content = chief_lean_brief.tool_result({"name": "year-end-giving-statements"})
    assert is_error, "no key, no steps"
    for s in cs.skills():
        assert chief_lean_brief.guide(s["name"]) is None, f"{s['name']} would shadow a how-to in the manual"


def test_the_contents_are_one_line_a_job():
    text = cs.contents_for(turn())
    assert text.startswith("CHURCH JOBS WITH WRITTEN STEPS")
    assert text.count("\n  ") == len(cs.skills()) and "action_guide" in text and "isn't open to this login" in text
    for s in cs.skills():
        assert f"  {s['name']}: {s['use_when']}" in text
        assert s["body"][:40] not in text, "only the contents, never the steps"
    assert cs.contents_for(turn(on=False)) == "" and cs.contents_for(None) == ""


# ─── The switch ───────────────────────────────────────────────────────

@pytest.fixture
def lean(monkeypatch):
    monkeypatch.setenv("CHIEF_BRIEF", "lean")
    import sample_church
    monkeypatch.setattr(sample_church, "is_sample", lambda bid: False)


def test_off_by_default(monkeypatch, lean):
    monkeypatch.delenv("CHIEF_CHURCH_SKILLS", raising=False)
    assert cs.mode() == "off" and not cs.switched_on(CHURCH)
    assert cs.prepare(CHURCH).on is False


def test_owner_is_the_platform_owners_church_only(monkeypatch, lean):
    monkeypatch.setenv("CHIEF_CHURCH_SKILLS", "owner")
    import member_asks
    monkeypatch.setattr(member_asks, "platform_church", lambda bid: bid == CHURCH["id"])
    assert cs.switched_on(CHURCH)
    assert not cs.switched_on(dict(CHURCH, id="33333333-3333-4333-8333-333333333333"))
    monkeypatch.setattr(member_asks, "platform_church", lambda bid: (_ for _ in ()).throw(RuntimeError("down")))
    assert not cs.switched_on(CHURCH), "can't tell: off"


def test_only_with_the_short_manual(monkeypatch, lean):
    monkeypatch.setenv("CHIEF_CHURCH_SKILLS", "on")
    assert cs.switched_on(CHURCH)
    monkeypatch.delenv("CHIEF_BRIEF")
    assert not cs.switched_on(CHURCH), "the contents point at action_guide, which only the short manual has"


def test_never_the_sample_church_or_a_business_that_isnt_a_church(monkeypatch, lean):
    monkeypatch.setenv("CHIEF_CHURCH_SKILLS", "on")
    assert not cs.switched_on(COACH) and not cs.switched_on(None) and not cs.switched_on({})
    import sample_church
    monkeypatch.setattr(sample_church, "is_sample", lambda bid: True)
    assert not cs.switched_on(CHURCH)


# ─── Wired into the turn, adding only ─────────────────────────────────

def test_it_rides_the_turn_and_the_per_church_segment_and_only_adds():
    import inspect
    import chief_prompt
    chat = inspect.getsource(cos.chief_chat)
    assert "_skills_turn = await asyncio.to_thread(_church_skills.prepare, biz)" in chat, "its reads off the loop"
    at = chat.index("_church_skills.turn_block(")
    assert at < chat.index("_login_block = chief_areas.block("), "the turn's tail, before the login's block"
    assert "_church_skills.begin_turn(_skills_turn, chief_areas.TURN.get())" in chat
    assert "church_skills_contents=_church_skills.contents_for(_skills_turn)," in chat
    assert "chief_truth.record('context:church_job_steps', _job_steps, kind='conversation')" in chat
    src = inspect.getsource(chief_prompt)
    seg = src[src.index('return _universal + f"""[[CHIEF_GLOBAL_SPLIT]]'):]
    assert seg.index("{church_skills_block}") < seg.index("[[CHIEF_CACHE_SPLIT]]")
    for line in ("[ACTION:{{\"type\":\"record_service_gifts\"", "[ACTION:{{\"type\":\"giving_statements_run\"}}]",
                 "[ACTION:{{\"type\":\"match_giving_deposits\"}}]"):
        assert line in src, line
    assert "CHIEF_CHURCH_SKILLS=" in open(os.path.join(ROOT, ".env.example"), encoding="utf-8").read()
