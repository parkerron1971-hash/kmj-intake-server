# __tests__/test_group_study.py
#
# This week's study (group_study.py; the approved canvas "Church Groups,
# Together", boards Meet, Lead, Settings and Main: "Questions from Sunday's
# message: Chief drafts them each week; Tasha approves before the group
# sees them"). Pins:
#   1. the office's own questions are used as written; Chief drafts only
#      when there are none, once per message, shared by every group
#   2. a draft only for groups with study on and a leader, for a message
#      from the last 8 days, published, once per group
#   3. nobody in the group sees a draft; only a leader posts it, as it is or
#      changed, checked like a Board post; the group hears once
#   4. the Meet tab and Home: the Chief card for leaders, the study card
#      for everyone after it's posted; the 5 PM reminder names it

import asyncio
import pathlib
import sys
from datetime import date

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_gatherings as gg
import group_study as gy
import msg_screen
from test_group_gatherings import _at, _g, _page, meet  # noqa: F401
from test_member_portal_group_space import (BIZ, BUSINESS, G, G_OPEN, MONIQUE, ROCHELLE, TASHA, TEEN,  # noqa: F401
                                            _client, _me, fake)

SUNDAY = "2026-10-18"
TUESDAY = date(2026, 10, 20)
SERMON = "55555555-0000-0000-0000-000000000001"
SERIES = "55555555-0000-0000-0000-0000000000aa"
OFFICE_QS = "1. What made the difference between the two builders?\n2) Where is it easiest to hear and not do?\n\n- What is holding?"


@pytest.fixture
def study(meet, monkeypatch):
    for g in meet.t["groups"]:
        g["study_on"] = True
    meet.t["sermon_series"] = [{"id": SERIES, "business_id": BIZ, "title": "To the Future"}]
    meet.t["sermons"] = [{"id": SERMON, "business_id": BIZ, "series_id": SERIES, "title": "Built to Last",
                          "scripture": "Luke 6:46-49", "summary": "Hearing and doing.", "questions": "",
                          "preached_on": SUNDAY, "video_url": "https://youtu.be/abc", "audio_url": "", "published": True,
                          "created_at": "2026-10-18T18:00:00+00:00"}]
    meet.t["group_studies"] = []
    meet.drafts = []

    def draft(business_id, sermon, series):
        meet.drafts.append((sermon["title"], series))
        return ["What did the wise builder do?", "What does building on rock mean?",
                "Where do you hear and not do?", "What one step will you take?"]
    monkeypatch.setattr(gy, "draft", draft)
    meet.screened = []

    async def screen(business_id, text):
        meet.screened.append(text)
        if meet.screen == "down":
            raise msg_screen.ScreenUnavailable()
        return meet.screen
    meet.screen = "ok"
    monkeypatch.setattr(msg_screen, "screen", screen)
    meet.told = []
    import member_push
    monkeypatch.setattr(member_push, "send", lambda biz, kind, **k: meet.told.append((kind, k)) or 1)
    return meet


def _post(who, questions=None, sid=None, f=None):
    sid = sid or f.t["group_studies"][0]["id"]
    return asyncio.run(gy.post(BUSINESS, _me(who, "x"), G, sid, questions))


# ── 1. what the questions are ────────────────────────────────────────

def test_the_offices_questions_as_written():
    assert gy.split_questions(OFFICE_QS) == ["What made the difference between the two builders?",
                                             "Where is it easiest to hear and not do?", "What is holding?"]
    assert gy.split_questions("Who heard? Who did? Why?") == ["Who heard?", "Who did?", "Why?"]
    assert len(gy.split_questions("\n".join(f"Q{i}?" for i in range(12)))) == 8
    assert gy.split_questions(" x" * 400)[0] == ("x " * 150).strip()[:300]


def test_chiefs_draft_is_a_json_list_or_nothing():
    assert gy.parse_draft('Here you go:\n["One?", "Two?", "Three?", "Four?"]') == ["One?", "Two?", "Three?", "Four?"]
    assert gy.parse_draft("I can't help with that.") is None
    assert gy.parse_draft('["One?", "Two?"]') is None                 # too few
    assert gy.parse_draft('["One?", 2, "Three?"]') is None


def test_the_office_questions_win_over_chief(study):
    study.t["sermons"][0]["questions"] = OFFICE_QS
    assert gy.sweep_tick(TUESDAY) == 1                                  # Sisters has a leader; the others don't
    row = study.t["group_studies"][0]
    assert (row["group_id"], row["source"], len(row["questions"])) == (G, "office", 3) and study.drafts == []


def test_chief_drafts_once_per_message_for_every_group(study):
    study.t["group_members"].append({"group_id": G_OPEN, "contact_id": MONIQUE, "business_id": BIZ, "role": "leader"})
    assert gy.sweep_tick(TUESDAY) == 2
    assert study.drafts == [("Built to Last", "To the Future")]
    assert {r["source"] for r in study.t["group_studies"]} == {"chief"}
    assert all(r["questions"] == r["drafted"] and r.get("posted_at") is None for r in study.t["group_studies"])


def test_a_group_that_comes_later_shares_the_draft(study):
    gy.sweep_tick(TUESDAY)
    study.t["group_members"].append({"group_id": G_OPEN, "contact_id": MONIQUE, "business_id": BIZ, "role": "leader"})
    study.t["group_studies"][0]["questions"] = ["Tasha's own?"]          # a leader's edit never spreads
    assert gy.sweep_tick(TUESDAY) == 1 and len(study.drafts) == 1
    later = next(r for r in study.t["group_studies"] if r["group_id"] == G_OPEN)
    assert later["questions"] == study.t["group_studies"][0]["drafted"]


# ── 2. who gets a draft ──────────────────────────────────────────────

def test_once_per_group_and_only_with_study_on(study):
    assert gy.sweep_tick(TUESDAY) == 1
    assert gy.sweep_tick(TUESDAY) == 0 and len(study.drafts) == 1
    study.t["group_studies"] = []
    _g(study)["study_on"] = False
    assert gy.sweep_tick(TUESDAY) == 0


def test_only_a_recent_published_message(study):
    assert gy.sweep_tick(date(2026, 10, 27)) == 0                       # 9 days on
    study.t["sermons"][0]["published"] = False
    assert gy.sweep_tick(TUESDAY) == 0
    study.t["sermons"][0]["published"] = True
    study.t["sermons"][0]["preached_on"] = "2026-10-25"                  # next Sunday's, planned ahead
    assert gy.sweep_tick(TUESDAY) == 0


def test_no_draft_no_row(study, monkeypatch):
    monkeypatch.setattr(gy, "draft", lambda *a: None)                    # an outage: try again next time
    assert gy.sweep_tick(TUESDAY) == 0 and study.t["group_studies"] == []


# ── 3. posting ───────────────────────────────────────────────────────

def test_nobody_in_the_group_sees_a_draft(study):
    gy.sweep_tick(TUESDAY)
    assert gy.view(BUSINESS, _g(study), leader=False, today=TUESDAY) == {}
    assert gy.view(BUSINESS, _g(study), leader=True, today=TUESDAY)["study"].get("posted_at") is None


def test_a_leader_posts_it_as_it_is_and_the_group_hears_once(study):
    gy.sweep_tick(TUESDAY)
    assert _post(MONIQUE, f=study) == (False, "not_group_leader")
    assert _post(TASHA, f=study) == (True, "study_posted")
    row = study.t["group_studies"][0]
    assert row["posted_by"] == TASHA and row["posted_at"] and len(study.screened) == 1
    kind, k = study.told[0]
    assert kind == "groups" and TASHA not in k["contact_ids"] and sorted(k["contact_ids"]) == sorted([MONIQUE, TEEN])
    assert "Built to Last" in k["body"] and k["ref_id"] == f"study:{row['id']}"
    assert gy.view(BUSINESS, _g(study), leader=False, today=TUESDAY)["sermon"]["title"] == "Built to Last"
    assert _post(TASHA, ["Changed?"], f=study) == (True, "study_saved")
    assert row["questions"] == ["Changed?"] and len(study.told) == 1         # no second note


def test_a_leaders_own_version(study):
    gy.sweep_tick(TUESDAY)
    assert _post(TASHA, ["  1. First?  ", "", "Second?", "   "], f=study) == (True, "study_posted")
    assert study.t["group_studies"][0]["questions"] == ["First?", "Second?"]
    assert study.t["group_studies"][0]["drafted"] != ["First?", "Second?"]   # Chief's stays as made


def test_nothing_goes_out_unchecked_or_empty(study):
    gy.sweep_tick(TUESDAY)
    assert _post(TASHA, ["", "  "], f=study) == (False, "study_empty")
    study.screen = "harm"
    assert _post(TASHA, f=study) == (False, "post_no")
    study.screen = "down"
    assert _post(TASHA, f=study) == (False, "post_busy")
    assert study.t["group_studies"][0].get("posted_at") is None and study.told == []
    assert _post(TASHA, sid="55555555-0000-0000-0000-00000000dead", f=study) == (False, "study_gone")


def test_off_or_old_shows_nothing(study):
    gy.sweep_tick(TUESDAY)
    _post(TASHA, f=study)
    assert gy.view(BUSINESS, _g(study), leader=False, today=date(2026, 11, 2)) == {}     # two weeks on
    study.t["sermons"][0]["published"] = False
    assert gy.view(BUSINESS, _g(study), leader=False, today=TUESDAY) == {}
    study.t["sermons"][0]["published"] = True
    _g(study)["study_on"] = False
    assert gy.view(BUSINESS, _g(study), leader=True, today=TUESDAY) == {}
    _g(study)["study_on"] = True
    study.fail.add("group_studies")
    assert gy.view(BUSINESS, _g(study), leader=False, today=TUESDAY) is None


# ── 4. the pages ─────────────────────────────────────────────────────

def _pg(who, tab="meet"):
    import member_portal_groups as mpg
    from test_member_portal_group_space import _req
    data = mpg.space(BIZ, G, _me(who, "x"), tab=tab)
    data["meet"] = gg.view(BUSINESS, data["group"], who, data["people"])
    data["study"] = gy.view(BUSINESS, data["group"], leader=data.get("role") == "leader", today=TUESDAY)
    html, _ = mpg.render(BUSINESS, None, _req(), _me(who, "x"), data, tab)
    return html


def test_the_chief_card_for_a_leader(study):
    gy.sweep_tick(TUESDAY)
    html = _pg(TASHA)
    assert "has 4 questions ready for Thursday" in html and "Built to Last" in html
    assert "Post them as they are" in html and "Review the questions" in html and "What did the wise builder do?" in html
    assert html.index("Post them as they are") < html.index("Thursday, October 22 · 7:00 PM")   # first on the tab
    assert "Post them as they are" in _pg(TASHA, "")                                         # and on Home
    for tab in ("meet", ""):
        member = _pg(MONIQUE, tab)
        assert "Built to Last" not in member and "What did the wise builder" not in member


def test_the_office_said_so(study):
    study.t["sermons"][0]["questions"] = OFFICE_QS
    gy.sweep_tick(TUESDAY)
    assert "came with 3 questions from the church office for Thursday" in _pg(TASHA)


def test_the_study_card_once_posted(study):
    gy.sweep_tick(TUESDAY)
    _post(TASHA, f=study)
    html = _pg(MONIQUE)
    assert "From Sunday · To the Future" in html and "Built to Last" in html and "What one step will you take?" in html
    assert "Drafted from Sunday’s message · Tasha Williams approved them" in html
    assert 'href="/my/bible/luke/6?v=46-49#v46"' in html and "Read Luke 6" in html
    assert f'href="/my/sermons/{SERMON}"' in html and "Watch the message" in html
    assert "Change the questions" not in html and "Change the questions" in _pg(TASHA)
    assert "Post them as they are" not in _pg(TASHA)
    home = _pg(MONIQUE, "")
    assert "This week’s study" in home and "Built to Last · 4 questions from Sunday" in home


def test_the_reminder_names_the_study(study):
    gy.sweep_tick(TUESDAY)
    _post(TASHA, f=study)
    study.told.clear()
    assert gg.reminders(BUSINESS, _at(2026, 10, 22, 17)) == 1
    assert study.told[0][1]["body"].endswith("· Study: Built to Last")


def test_the_route(study, monkeypatch):
    gy.sweep_tick(TUESDAY)
    sid = study.t["group_studies"][0]["id"]
    c = _client(monkeypatch, _me(TASHA, "Tasha"))
    r = c.post("/my/groups/meet/study", data={"group_id": G, "study": sid, "edited": "1", "q": ["Mine?", ""]})
    assert r.headers["location"] == f"/my/groups/{G}/meet?done=study_posted"
    assert study.t["group_studies"][0]["questions"] == ["Mine?"]
    r = c.post("/my/groups/meet/study", data={"group_id": G, "study": "nope"})
    assert r.headers["location"] == f"/my/groups/{G}/meet?err=study_gone"


def test_every_code_has_words_and_the_export():
    import account_lifecycle as al
    import member_portal_church as mpc
    assert {"study_posted", "study_saved"} <= set(mpc.DONE) and {"study_gone", "study_empty"} <= set(mpc.ERRORS)
    t = al.BUSINESS_CHILD_TABLES
    assert t.index("group_studies") < t.index("groups") < t.index("sermons") and "group_studies" in al._IMPORT_SKIP


def test_the_weekly_drafts_are_scheduled():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'g("group_study_drafts", _group_study.sweep_tick)' in src
