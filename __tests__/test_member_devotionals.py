"""Plans & devotionals (member app round three, part 4; Kevin approved the
canvas's boards 10 and 11 on 2026-10-19 and said yes to Listen): a church's
own devotionals (devotionals.py), what members do with them
(member_portal_devotionals.py), and Listen (devotional_voice.py)."""
import asyncio
import json
from datetime import date, timedelta
from unittest import mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import devotional_voice as dvv
import devotionals as dv
import member_portal_devotionals as mpd

BIZ = {"id": "11111111-1111-4111-8111-111111111111", "name": "Love City Church", "type": "church", "settings": {}}
ME = {"id": "22222222-2222-4222-8222-222222222222", "name": "Jasmine Carter"}
DEV_ID = "33333333-3333-4333-8333-333333333333"
TODAY = date(2026, 10, 21)          # a Wednesday: day 3 of Focus Week


def day(title, scripture="Proverbs 4:25", **more):
    return {"title": title, "scripture": scripture, "body": "You cannot walk in two directions at once.\n\nToday is a check.",
            "pull": "", "pray": "Lord, turn my eyes back to You.", "act": "Do your One Thing block.",
            "together": "Wednesday service.", "journal": "", **more}


def devotional(**over):
    out = {"id": DEV_ID, "business_id": BIZ["id"], "title": "Consecrate Your Focus", "kind": "Focus Week",
           "author": "Pastor Kevin McCloud Jr.", "about": "For seven days we consecrate our focus.",
           "practices": [{"key": "a1b2c3d4", "title": "First Look", "sub": "Before my phone"},
                         {"key": "e5f6a7b8", "title": "One Thing", "sub": "25 minutes"}],
           "days": [day(f"Day {n} title") for n in range(1, 8)], "day_count": 7,
           "starts_on": date(2026, 10, 19), "voice": "grace", "status": "published", "audio": {}}
    out.update(over)
    out["day_count"] = len(out["days"])
    return out


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    import giving_router
    import reading_plans as rp
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    monkeypatch.setattr(rp, "current", lambda biz: None)
    import member_app_photos as photos
    monkeypatch.setattr(photos, "photos", lambda biz, site, limit=None: [])


# ─── a day at a time ─────────────────────────────────────────────────


def test_a_dated_devotional_opens_a_day_a_day_and_all_of_it_once_over():
    start = date(2026, 10, 19)
    assert dv.open_upto(start, 7, start - timedelta(days=1)) == 0
    assert dv.open_upto(start, 7, start) == 1
    assert dv.open_upto(start, 7, TODAY) == 3
    assert dv.open_upto(start, 7, start + timedelta(days=30)) == 7
    assert dv.day_number(start, 7, TODAY) == 3
    assert dv.day_number(start, 7, start + timedelta(days=7)) is None
    assert dv.open_upto(None, 7, TODAY) == 0                     # not started: nothing open


def test_where_a_member_is():
    d = devotional()
    assert mpd.state(d, None, set(), TODAY)["kind"] == "running"
    st = mpd.state(d, None, {1, 2}, TODAY)
    assert (st["now"], st["upto"], st["next"]) == (3, 3, 3)
    assert mpd.chip(st) == ("Day 3 of 7", "")
    assert mpd.state(d, None, set(range(1, 8)), TODAY)["kind"] == "finished"
    assert mpd.state(d, None, set(), date(2026, 10, 1))["kind"] == "upcoming"
    assert mpd.chip(mpd.state(d, None, set(), date(2026, 10, 1)))[0] == "Starts Mon, Oct 19"
    assert mpd.state(d, None, {1}, date(2026, 11, 30))["kind"] == "over"
    own = devotional(starts_on=None)
    assert mpd.state(own, None, set(), TODAY)["kind"] == "new"
    assert mpd.chip(mpd.state(own, None, set(), TODAY)) == ("Start", "is-start")
    assert mpd.state(own, TODAY, set(), TODAY)["now"] == 1      # started today: day 1
    assert mpd.state(own, None, set(), TODAY, preview=True)["upto"] == 7    # the owner sees every day


def test_streak_counts_back_from_the_last_open_day():
    assert dv.streak({1, 2, 3}, 3) == 3
    assert dv.streak({1, 2}, 3) == 2              # today's not done yet: yesterday's run still counts
    assert dv.streak({1, 3}, 3) == 1
    assert dv.streak(set(), 3) == 0


def test_reading_time_and_paragraphs():
    assert dv.minutes({"body": "word " * 850}) == 6
    assert dv.minutes({}) == 2
    assert dv.paragraphs("One\nline.\n\n\nTwo.") == ["One line.", "Two."]


# ─── what staff save ─────────────────────────────────────────────────


def test_staff_fields_are_checked_and_practice_keys_are_kept():
    out = dv.clean({"title": " Consecrate Your Focus ", "starts_on": "2026-10-19", "voice": "elijah",
                    "practices": [{"key": "a1b2c3d4", "title": "First Look", "sub": "Before my phone"},
                                  {"title": "One Thing"}, {"title": "  "}],
                    "days": [day("Not Here Before")]})
    assert out["title"] == "Consecrate Your Focus"
    assert out["practices"][0]["key"] == "a1b2c3d4"           # a practice keeps its key (members' ticks stay)
    assert len(out["practices"]) == 2 and len(out["practices"][1]["key"]) == 8
    assert out["days"][0]["title"] == "Not Here Before" and set(out["days"][0]) == set(dv.DAY_FIELDS)
    assert dv.clean({"title": "x", "starts_on": ""})["starts_on"] is None
    for bad, words in (({"title": ""}, "title"),
                       ({"title": "x", "voice": "robot"}, "voices"),
                       ({"title": "x", "starts_on": "soon"}, "start date"),
                       ({"title": "x", "starts_on": "2030-01-01"}, "within a year"),
                       ({"title": "x", "days": [day("t", body="w" * 12001)]}, "Day 1's words"),
                       ({"title": "x", "days": [day("t")] * 91}, "at most 90"),
                       ({"title": "x", "practices": [{"title": f"P{i}"} for i in range(9)]}, "at most 8")):
        with pytest.raises(ValueError) as e:
            dv.clean(bad)
        assert words in str(e.value), (bad, str(e.value))


def test_a_devotional_goes_out_only_when_every_day_has_a_title_and_words():
    assert dv.ready({"days": []}) == "Add at least one day before it goes out."
    assert "Day 2 needs a title" in dv.ready({"days": [day("a"), day("")]})
    assert "Day 1 needs its words" in dv.ready({"days": [day("a", scripture="", body="")]})
    assert dv.ready({"days": [day("a"), day("b", body="")]}) is None    # a scripture alone is enough


PASTED = """Consecrate Your Focus: Focus Week

Welcome to Focus Week. For seven days we consecrate our focus.

First Look (morning, before your phone).
Your first look goes to God, not a screen.
One Thing (midday).
Choose one task and give it 25 minutes.

Day 1, Monday: Not Here Before
"...that ye may know the way by which ye must go: for ye have not passed this way heretofore." Joshua 3:4
This is not a rerun. You are preparing for ground you have never walked.

Give God your first look today.
Pray: Lord, I have not been this way before.
Do today: Do your First Look before your phone.
Together: 6 PM prayer line.

Day 2, Tuesday: Set Apart
"And Joshua said unto the people, Sanctify yourselves: for to morrow the LORD will do wonders among you." Joshua 3:5
The word consecrate means to set apart for God.
Pray: Father, I am not giving this up, I am giving it to You.
Journal: What did you lay down today?
"""


def test_a_pasted_devotional_is_read_into_its_days():
    got = dv.parse(PASTED)
    assert (got["title"], got["kind"]) == ("Consecrate Your Focus", "Focus Week")
    assert [p["title"] for p in got["practices"]] == ["First Look", "One Thing"]
    assert got["practices"][0]["sub"] == "Morning, before your phone"
    assert "Welcome to Focus Week" in got["about"] and "First Look (" not in got["about"]
    d1, d2 = got["days"]
    assert d1["title"] == "Not Here Before" and d1["scripture"] == "Joshua 3:4"
    assert d1["body"].startswith("This is not a rerun") and d1["pull"] == "Give God your first look today."
    assert d1["pray"] == "Lord, I have not been this way before." and d1["act"].startswith("Do your First Look")
    assert d1["together"] == "6 PM prayer line."
    assert d2["title"] == "Set Apart" and d2["scripture"] == "Joshua 3:5"
    assert d2["journal"] == "What did you lay down today?" and d2["pull"] == ""
    assert dv.parse("Just some words")["days"] == []


# Kevin's document as it really copies out: a byline, headings, a table, the
# anchors running on, and a checklist and closing word after the last day.
DOC = """Consecrate Your Focus: 7-Day Devotional

October 18, 2026 · Kevin McCloud

Welcome to Focus Week

For seven days we consecrate our focus, because tomorrow the Lord will do wonders among us (Joshua 3:5).

Consecration isn't subtraction, it's dedication.

How to Consecrate Your Day

A consecrated day has five anchors.

1. First Look (morning, before your phone). Your first look goes to God, not a screen.
2. Guarded Evening (replaces the binge). Set a hard stop for screens at 9 PM.

What you set aside, and what you pick up

Set aside\tPick up
Phone beside the bed\tA Bible beside the bed

Day 1, Monday: Not Here Before

"...that ye may know the way by which ye must go: for ye have not passed this way heretofore." Joshua 3:4

This is not a rerun.

Pray: Lord, I have not been this way before.

Together: 6 PM prayer line.

Day 7, Sunday: Tomorrow the Lord Will Do Wonders

"Sanctify yourselves: for to morrow the LORD will do wonders among you." Joshua 3:5

You have consecrated your focus for seven days.

Gather with the church today and look back at the week.

Pray: Lord, I have set my focus apart for You.

Do today: Come to the gathering expectant.

Together: Sunday service. Close the Focus week together.
"""
CHECKLIST = """
Your Daily Checklist

Tick these off each day. Mark the First Look first, since it holds the day together.

First Look: verse, prayer, and one ask before my phone
Guarded Evening: screens off by 9 PM, something that builds me instead
Together: joined the 6 PM prayer line or the service

A closing charge

You are not giving up your focus. You are giving it to God.
"""


def test_a_real_document_keeps_its_welcome_practices_and_last_day():
    got = dv.parse(DOC + CHECKLIST)
    assert (got["title"], got["kind"]) == ("Consecrate Your Focus", "")    # the page already says "7-day devotional"
    # the welcome is the first section's words: no byline, headings, anchors or table
    assert got["about"] == ("For seven days we consecrate our focus, because tomorrow the Lord will do wonders "
                            "among us (Joshua 3:5).\n\nConsecration isn't subtraction, it's dedication.")
    # the checklist is what a member ticks, so it wins over the anchors; "9 PM" keeps its capitals
    assert [(p["title"], p["sub"]) for p in got["practices"]] == [
        ("First Look", "Verse, prayer, and one ask before my phone"),
        ("Guarded Evening", "Screens off by 9 PM, something that builds me instead"),
        ("Together", "Joined the 6 PM prayer line or the service")]
    d1, d7 = got["days"]
    assert d1["pray"] == "Lord, I have not been this way before." and d1["together"] == "6 PM prayer line."
    # the last day ends at the checklist: its Together isn't the checklist's, its words aren't the closing charge
    assert d7["together"] == "Sunday service. Close the Focus week together."
    assert d7["body"] == "You have consecrated your focus for seven days."
    assert d7["pull"] == "Gather with the church today and look back at the week."
    assert d7["act"] == "Come to the gathering expectant."


def test_without_a_checklist_the_numbered_anchors_are_the_practices():
    for doc in (DOC, DOC.replace("1. First", "First").replace("2. Guarded", "Guarded")):
        got = dv.parse(doc)
        assert [(p["title"], p["sub"]) for p in got["practices"]] == [
            ("First Look", "Morning, before your phone"), ("Guarded Evening", "Replaces the binge")]
        assert "First Look" not in got["about"]


def test_a_day_ends_only_when_nothing_of_its_own_is_left():
    # an "Amen" on its own line reads like a heading, but the day's Do today is still to come
    amen = dv.parse("Day 1: Here\n\nWords.\n\nPray: Lord, lead me.\n\nIn Jesus' name, Amen\n\n"
                    "Do today: Walk with someone.\n\nTogether: The 6 PM line.")["days"][0]
    assert (amen["act"], amen["together"]) == ("Walk with someone.", "The 6 PM line.")
    # a label coming round again is past the day, and doesn't overwrite it
    again = dv.parse("Day 1: Here\n\nWords.\n\nTogether: The 6 PM line.\n\nTogether: joined the line")["days"][0]
    assert again["together"] == "The 6 PM line."
    assert [dv._kind(k) for k in (" Focus Week", "21-Day Fast", "7 day devotional", "")] == ["Focus Week", "Fast", "", ""]


def _authed(role):
    """A signed-in user with `role` on the church, through the one access
    check (business_access.assert_access: no seat is a 404)."""
    from auth_supabase import AuthedUser

    def access(biz, user, min_role="viewer"):
        if not role:
            raise HTTPException(404, "business not found")
        return role
    return AuthedUser(id="44444444-4444-4444-8444-444444444444", email="x@example.com", role="authenticated"), \
        mock.patch.object(dv, "assert_access", access)


def test_only_the_owner_an_admin_or_a_manager_writes_devotionals():
    user, role = _authed("member")
    with role, pytest.raises(HTTPException) as e:
        dv.create_devotional({"business_id": BIZ["id"], "title": "x"}, user)
    assert e.value.status_code == 403
    user, role = _authed(None)
    with role, pytest.raises(HTTPException) as e:
        dv.list_devotionals(BIZ["id"], user)
    assert e.value.status_code == 404


def test_publishing_refuses_an_unfinished_devotional(monkeypatch):
    user, role = _authed("admin")
    monkeypatch.setattr(dv, "one", lambda b, i, published=True: (devotional(status="draft", days=[day("")]), True))
    with role, pytest.raises(HTTPException) as e:
        dv.publish_devotional(DEV_ID, {"business_id": BIZ["id"], "publish": True}, user)
    assert e.value.status_code == 400 and "Day 1 needs a title" in e.value.detail


def test_a_published_devotional_cant_be_saved_unfinished(monkeypatch):
    user, role = _authed("owner")
    monkeypatch.setattr(dv, "one", lambda b, i, published=True: (devotional(), True))
    with role, pytest.raises(HTTPException) as e:
        dv.save_devotional(DEV_ID, {"business_id": BIZ["id"], "days": [day("")]}, user)
    assert e.value.status_code == 400 and "take it down first" in e.value.detail


def test_deleting_takes_the_members_own_starts_and_its_listen_files(monkeypatch):
    import sb_clients
    user, role = _authed("manager")
    deleted, forgot = [], []
    monkeypatch.setattr(dv, "one", lambda b, i, published=True: (devotional(), True))
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", lambda p: deleted.append(p) or True)
    monkeypatch.setattr(dvv, "forget", lambda d: forgot.append(d["id"]))
    with role:
        assert dv.delete_devotional(DEV_ID, BIZ["id"], user) == {"ok": True}
    assert deleted[0].startswith("/devotionals?id=eq." + DEV_ID)
    assert "member_plan_starts" in deleted[1] and "devotional%3A" + DEV_ID in deleted[1]
    assert forgot == [DEV_ID]


def test_read_paste_finds_days_or_says_how(monkeypatch):
    user, role = _authed("owner")
    with role:
        assert len(dv.read_paste({"business_id": BIZ["id"], "text": PASTED}, user)["found"]["days"]) == 2
        with pytest.raises(HTTPException) as e:
            dv.read_paste({"business_id": BIZ["id"], "text": "no days here"}, user)
    assert e.value.status_code == 400 and '"Day 1"' in e.value.detail


# ─── the member's pages ──────────────────────────────────────────────


def test_the_day_page_has_the_scripture_words_blocks_checklist_journal_and_done():
    d = devotional()
    st = mpd.state(d, None, {1, 2}, TODAY)
    html = mpd.render_day(BIZ, None, ME, d, 3, st, {"checks": ["a1b2c3d4"], "journal": "Mine", "done_at": None},
                          listen=True)
    assert "Let thine eyes look right on" in html and "Read Proverbs 4" in html
    assert "You cannot walk in two directions at once." in html
    for words in ("Pray", "Do today", "Together", "Your daily checklist", "1 of 2", "Mark day 3 done",
                  "Private to you. Only you can read it.", "Mine", 'id="dv-listen"'):
        assert words in html, words
    assert 'data-live="1"' in html and 'aria-pressed="true"' in html
    # day 4 isn't open yet: its name and when, nothing to tap
    assert f'href="/my/bible/plans/{DEV_ID}/4"' not in html and "Opens Thu, Oct 22" in html
    assert f'href="/my/bible/plans/{DEV_ID}/2"' in html        # an earlier day is


def test_a_preview_saves_nothing_and_says_so():
    d = devotional()
    html = mpd.render_day(BIZ, None, ME, d, 5, mpd.state(d, None, set(), TODAY, preview=True), {}, listen=False)
    assert 'data-live="0"' in html and "This is a preview" in html
    assert 'id="dv-listen"' not in html                     # Listen off: no button at all
    assert "Mark day 5 done</button>" in html and "disabled" in html


def test_a_day_that_couldnt_load_says_so_and_saves_nothing():
    d = devotional()
    html = mpd.render_day(BIZ, None, ME, d, 3, mpd.state(d, None, set(), TODAY), None)
    assert "couldn't load just now" in html and 'data-live="0"' in html


def test_the_plans_page_leads_with_this_week_then_the_churchs_then_reading_plans():
    d, other = devotional(), devotional(id="55555555-5555-4555-8555-555555555555", title="Fast & Prayer",
                                        starts_on=None)
    html = mpd.render_plans(BIZ, None, ME, devs=[d, other], done={DEV_ID: {1, 2}}, mine={},
                            church_today=None, church_done=None, today=TODAY)
    assert html.index('id="dv-now-h">This week at Love City') < html.index('id="dv-lib-h">From Love City') \
        < html.index('id="dv-rp-h">Reading plans')
    assert "Fast &amp; Prayer" in html and ">Start<" in html
    assert 'name="plan" value="reading:gospels-30"' in html
    yours = mpd.render_plans(BIZ, None, ME, devs=[d, other], done={DEV_ID: {1}, f"t:{DEV_ID}": {1}}, mine={},
                             church_today=None, church_done=None, show="yours", today=TODAY)
    assert "Consecrate Your Focus" in yours and "Fast &amp; Prayer" not in yours
    broken = mpd.render_plans(BIZ, None, ME, devs=None, done={}, mine={}, church_today=None, church_done=None)
    assert "couldn't load just now" in broken


def test_a_plan_of_your_own_shows_where_you_are():
    mine = {"reading:gospels-30": TODAY - timedelta(days=8)}
    html = mpd.render_plans(BIZ, None, ME, devs=[], done={}, mine=mine, church_today=None, church_done=None,
                            show="reading", today=TODAY)
    assert "You&#x27;re on day 9" in html and 'href="/my/bible/plans/gospels-30"' in html and ">Yours<" in html


def test_home_shows_the_dated_devotional_running_today():
    dated, own = devotional(), devotional(id="55555555-5555-4555-8555-555555555555", starts_on=None)
    dev, st = mpd.pick_today([own, dated], {}, {f"devotional:{own['id']}": TODAY}, TODAY)
    assert dev is dated and st["now"] == 3
    row = mpd.today_row(dated, st)
    assert "Devotional · Day 3 of 7" in row and "Day 3 title" in row and f"/my/bible/plans/{DEV_ID}/3" in row
    assert mpd.pick_today([devotional(starts_on=date(2026, 12, 1))], {}, {}, TODAY) == (None, None)


def test_home_never_stops_for_the_devotional_row(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(dv, "catalog", boom)
    assert asyncio.run(mpd.home_extras(BIZ, ME)) == ("", None, None)


def test_the_bible_tab_features_this_weeks_devotional_and_the_reading_plans():
    d = devotional()
    html = mpd.bible_sections(BIZ, None, devs=[d], done={DEV_ID: {1, 2}}, mine={}, church_today=None,
                              church_done=None, today=TODAY)
    assert "From Love City" in html and "Day 3 today: Day 3 title" in html and "Read day 3" in html
    assert "Reading plans" in html and "+ The whole Bible in a year" in html


# ─── a member's own day ──────────────────────────────────────────────


def test_a_change_to_a_day_is_checked():
    d = devotional()
    assert mpd.clean_change({"checks": ["e5f6a7b8", "a1b2c3d4"]}, d) == {"checks": ["a1b2c3d4", "e5f6a7b8"]}
    assert mpd.clean_change({"journal": "  Where did my focus go?  "}, d) == {"journal": "Where did my focus go?"}
    assert mpd.clean_change({"done": True}, d) == {"done": True}
    for bad in ({"checks": ["nope"]}, {"checks": "a1b2c3d4"}, {"journal": "x" * 4001}, {"done": "yes"}, {}):
        assert mpd.clean_change(bad, d) is None, bad


def _post_day(body, *, session=(BIZ, ME, False), dev=None, started=None, today=TODAY):
    import member_portal as mp
    import member_portal_church as mpc
    import rate_limit

    async def signed_in(request):
        return {"business": session[0]}, session[1], session[2]
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    request = Request({"type": "http", "method": "POST", "path": "/my/bible/plans/day", "query_string": b"",
                       "headers": [(b"content-type", b"application/json")]}, receive)
    saved = []
    real = dv.open_upto
    with mock.patch.object(mpc, "_signed_in", signed_in), mock.patch.object(rate_limit, "allow", lambda b, k: True), \
            mock.patch.object(mp, "_same_origin", lambda r: True), \
            mock.patch.object(dv, "one", lambda b, i, published=True: ((dev or devotional()), True)), \
            mock.patch.object(dv, "open_upto", lambda s, c, t=None: real(s, c, today)), \
            mock.patch.object(mpd, "started_on", lambda b, c, d: started), \
            mock.patch.object(mpd, "save_day", lambda b, c, i, n, ch: saved.append((n, ch)) or
                              {"done_at": "2026-10-21T12:00:00Z" if ch.get("done") else None, "checks": ch.get("checks", [])}), \
            mock.patch.object(mpd, "progress", lambda b, c, i: {1: {"done_at": "x"}, 2: {"done_at": "x"}, 3: {"done_at": "x"}}):
        resp = asyncio.run(mpd.save_my_day(request))
    return resp.status_code, json.loads(resp.body), saved


def test_the_member_keeps_their_own_open_days_only():
    code, out, saved = _post_day({"devotional": DEV_ID, "day": 3, "done": True})
    assert code == 200 and out == {"ok": True, "done": True, "checks": [], "streak": 3} and saved == [(3, {"done": True})]
    assert _post_day({"devotional": DEV_ID, "day": 4, "done": True})[:2] == (403, {"ok": False, "error": "closed"})
    assert _post_day({"devotional": DEV_ID, "day": 3, "done": True}, session=(BIZ, None, "preview"))[0] == 403
    assert _post_day({"devotional": DEV_ID, "day": 3, "done": True}, session=(BIZ, None, False))[0] == 401
    assert _post_day({"devotional": DEV_ID, "day": 3, "checks": ["nope"]})[0] == 400
    own = devotional(starts_on=None)
    assert _post_day({"devotional": DEV_ID, "day": 1, "done": True}, dev=own)[0] == 403          # not started
    assert _post_day({"devotional": DEV_ID, "day": 1, "done": True}, dev=own, started=TODAY)[0] == 200


# ─── Listen ──────────────────────────────────────────────────────────


def test_what_listen_reads():
    d = devotional()
    paras = dvv.script(d, 3)
    assert paras[0] == "Consecrate Your Focus. Day 3. Day 3 title."
    assert paras[1].startswith("Proverbs 4, verse 25. Let thine eyes look right on")
    assert "Pray. Lord, turn my eyes back to You." in paras and "Something to write down." not in " ".join(paras)
    assert dvv.spoken_ref("John 3:16-18") == "John 3, verses 16 to 18" and dvv.spoken_ref("Psalm 23") == "Psalm 23"


def test_long_days_are_read_in_pieces_under_the_providers_limit():
    out = dvv.pieces(["a" * 10 + ". " + "b" * 2995, "short one", "c" * 7000])
    assert all(len(p) <= dvv.PIECE_MAX for p in out)
    assert "".join(out).replace("\n", "").replace(" ", "").count("c") == 7000


def test_a_day_is_read_again_only_when_its_words_or_voice_change():
    d = devotional()
    h = dvv.version(d, 3)
    assert dvv.version(devotional(), 3) == h
    assert dvv.version(devotional(voice="elijah"), 3) != h
    changed = devotional()
    changed["days"][2] = day("Day 3 title", body="New words.")
    assert dvv.version(changed, 3) != h
    kept = {"3": {"hash": h, "url": "https://x.supabase.co/a.mp3", "seconds": 300}}
    assert dvv.kept(devotional(audio=kept), 3)["seconds"] == 300
    assert dvv.kept(changed | {"audio": kept}, 3) is None


def test_two_members_tapping_listen_at_once_get_one_reading(monkeypatch):
    made = []

    async def make(dev, n):
        made.append(n)
        await asyncio.sleep(0.01)
        return {"hash": dvv.version(dev, n), "url": "https://x/a.mp3", "seconds": 1}
    store = {"dev": devotional()}

    def one(b, i, published=True):
        return store["dev"], True
    monkeypatch.setattr(dvv, "make", make)
    monkeypatch.setattr(dv, "one", one)

    async def both():
        first = asyncio.create_task(dvv.ready(store["dev"], 3))
        await asyncio.sleep(0)
        got1 = await first
        store["dev"] = devotional(audio={"3": got1})      # what make() remembered
        return got1, await dvv.ready(devotional(), 3)
    a, b = asyncio.run(both())
    assert made == [3] and a["url"] == b["url"]


def _listen(body, *, session=(BIZ, ME, False), speak=True, started=None):
    import member_portal as mp
    import member_portal_church as mpc
    import rate_limit

    async def signed_in(request):
        return {"business": session[0]}, session[1], session[2]
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    async def ready(dev, n):
        return {"url": "https://x/day.mp3", "seconds": 312}
    request = Request({"type": "http", "method": "POST", "path": "/my/bible/plans/listen", "query_string": b"",
                       "headers": [(b"content-type", b"application/json")]}, receive)
    real = dv.open_upto
    with mock.patch.object(mpc, "_signed_in", signed_in), mock.patch.object(rate_limit, "allow", lambda b, k: True), \
            mock.patch.object(mp, "_same_origin", lambda r: True), mock.patch.object(dvv, "can_speak", lambda: speak), \
            mock.patch.object(dv, "one", lambda b, i, published=True: (devotional(), True)), \
            mock.patch.object(dv, "open_upto", lambda s, c, t=None: real(s, c, TODAY)), \
            mock.patch.object(mpd, "started_on", lambda b, c, d: started), mock.patch.object(dvv, "ready", ready):
        resp = asyncio.run(dvv.listen(request))
    return resp.status_code, json.loads(resp.body)


def test_listen_plays_an_open_day_for_a_member_or_the_owners_preview():
    assert _listen({"devotional": DEV_ID, "day": 3}) == (200, {"ok": True, "url": "https://x/day.mp3", "seconds": 312})
    assert _listen({"devotional": DEV_ID, "day": 6}, session=(BIZ, None, "preview"))[0] == 200
    assert _listen({"devotional": DEV_ID, "day": 6})[0] == 403                 # not open yet
    assert _listen({"devotional": DEV_ID, "day": 3}, session=(BIZ, None, False))[0] == 401
    assert _listen({"devotional": DEV_ID, "day": 3}, speak=False)[0] == 404
    assert _listen({"devotional": DEV_ID, "day": 9})[0] == 400
