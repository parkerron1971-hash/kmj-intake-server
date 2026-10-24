# __tests__/test_sunday_serving_alerts.py
#
# ChurchSavvy Planning, step 3: asks and reminders reach people
# (sunday_serving_alerts.py; canvas boards 6 and 8). Pins:
#   * the ask goes on the sweep after it's made, never before (so a month can
#     be taken back), never in quiet hours, and a Sunday more than three
#     weeks off waits; each step is said once
#   * no answer in two days: one nudge, never a third; still none five days
#     out: the office hears, with who else could take it
#   * someone asked to cover hears once for each ask
#   * a yes: a week before (not when they said yes inside the week), the day
#     before after 6 PM, that morning; a passed moment is skipped, not late
#   * phone alerts follow the church's switch and the member's own box; the
#     email copy goes to grown-ups who keep it, and to anyone the phone
#     didn't reach; a teen gets no email
#   * How I hear shows only once the church switched Serving on, and saves
#     the member's own choice
#   * the office's switch for Serving shows only where Planning is open

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from test_sunday_planning import (ANA, BIZ, JO, KENDRA, NOW, PEOPLE, PRODUCTION, TY, ZONE, api, ask, make_team, place,  # noqa: F401
                                  services, sundays, train)

import member_push
import push_notifications
import sunday_planning as sp
import sunday_serving as ss
import sunday_serving_alerts as ssa

ON = {"member_portal": {"notifications": {"serving": True}}}
CHURCH = {"id": BIZ, "name": "Love City Church", "owner_id": "u-owner", "settings": ON}


def local(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=ZONE).astimezone(timezone.utc)


@pytest.fixture
def heard(api, monkeypatch):
    """Production on five Sundays from 10/25 (10:30 each): Sound (Kendra and
    Jo trained, Ty learning) and Slides (Ana). Every member has a phone; the
    pushes, emails and office alerts are recorded."""
    db, as_ = api
    db.KEYS = {**db.KEYS, "member_push_prefs": ("business_id", "contact_id")}
    db.t["member_push_prefs"] = []
    db.t["member_push_subscriptions"] = [
        {"id": f"s-{c}", "business_id": BIZ, "contact_id": c, "endpoint": f"https://push/{c}", "subscription": {}}
        for c in (KENDRA, JO, ANA, TY)]
    sundays(as_, 5)
    team = make_team(as_)
    sound, slides = place(team, "Sound"), place(team, "Slides")
    train(as_, sound, [(KENDRA, "trained"), (JO, "trained"), (TY, "learning")])
    train(as_, slides, [(ANA, "trained"), (TY, "trained")])
    got = {"push": [], "email": [], "office": []}
    monkeypatch.setenv("MEMBER_QUIET_HOURS", "on")
    monkeypatch.setattr(push_notifications, "push_enabled", lambda: True)
    monkeypatch.setattr(push_notifications, "_send_one",
                        lambda s, payload, table=None: got["push"].append((s["contact_id"], payload)) or True)

    async def email(biz, person, step, w, link, ctx):
        got["email"].append((person["id"], step, w["title"]))

    async def office(biz_id, title, body, key, person_id):
        got["office"].append((title, body))
        return True

    monkeypatch.setattr(ssa, "_email", email)
    monkeypatch.setattr(ssa, "_office", office)
    s = [x["id"] for x in services(db)]
    return db, as_, s, sound, slides, got


def tick(at):
    return ssa.church_tick(CHURCH, at)


def row(db, aid):
    return next(r for r in db.t["serve_assignments"] if r["id"] == aid)


def titles(got, who=None):
    return [p["title"] for c, p in got["push"] if who is None or c == who]


def test_the_ask_goes_on_the_next_sweep_once(heard):
    db, as_, s, sound, slides, got = heard
    a = ask(as_, s[0], sound, KENDRA).json()["assignment"]["id"]
    far = ask(as_, s[4], sound, JO).json()["assignment"]["id"]          # Nov 22: 32 days off
    out = tick(NOW)
    assert titles(got) == ["Can you serve on Sound, Oct 25?"]
    assert got["push"][0][1]["url"] == f"/my/serving/{a}"
    assert "Tap Yes or Can't" in got["push"][0][1]["body"]
    assert got["email"] == [(KENDRA, "ask", "Can you serve on Sound, Oct 25?")]
    assert row(db, a)["notified_at"] and row(db, far)["notified_at"] is None
    assert out["asks"] == 1
    # Said once: the next sweep has nothing new.
    tick(NOW + timedelta(minutes=15))
    assert len(got["push"]) == 1 and len(got["email"]) == 1
    # Three weeks out, the far one goes.
    tick(local(2026, 11, 1, 11))
    assert f"/my/serving/{far}" in [p["url"] for _, p in got["push"]]


def test_a_month_taken_back_before_the_sweep_says_nothing(heard):
    db, as_, s, sound, slides, got = heard
    a = ask(as_, s[0], sound, KENDRA).json()["assignment"]["id"]
    r = as_("owner").post("/planning/unfill", json={"business_id": BIZ, "ids": [a]})
    assert r.json()["taken_back"] == 1
    tick(NOW)
    assert got["push"] == [] and got["email"] == []
    # Once it's out, it can't be taken back quietly.
    b = ask(as_, s[0], sound, JO).json()["assignment"]["id"]
    tick(NOW)
    assert as_("owner").post("/planning/unfill", json={"business_id": BIZ, "ids": [b]}).json()["taken_back"] == 0


def test_quiet_hours_wait_for_seven(heard):
    db, as_, s, sound, slides, got = heard
    ask(as_, s[0], sound, KENDRA)
    tick(local(2026, 10, 21, 22))
    tick(local(2026, 10, 22, 6, 45))
    assert got["push"] == [] and got["email"] == []
    tick(local(2026, 10, 22, 7, 0))
    assert titles(got) == ["Can you serve on Sound, Oct 25?"]


def test_one_nudge_then_the_office(heard):
    db, as_, s, sound, slides, got = heard
    a = ask(as_, s[1], sound, KENDRA).json()["assignment"]["id"]      # Nov 1
    tick(NOW)                                                          # Wed 10/21: the ask
    tick(NOW + timedelta(days=1))
    assert len(got["push"]) == 1
    tick(NOW + timedelta(days=2))                                      # Fri 10/23: the nudge
    assert titles(got) == ["Can you serve on Sound, Nov 1?"] * 2
    assert "still hoping to hear" in got["push"][1][1]["body"]
    assert [e[1] for e in got["email"]] == ["ask", "nudge"]
    tick(NOW + timedelta(days=3))
    assert len(got["push"]) == 2 and got["office"] == []
    # Tue 10/27, five days before: the office hears, with who else could take it.
    # (Nov 1 is when the clocks go back: 10:30 that morning is 4 days 23 hours
    # after 12:00 on Tuesday.)
    tick(local(2026, 10, 27, 12))
    assert got["office"] == [("No answer yet: Sound, Nov 1", "Kendra hasn't answered. Jo could take it.")]
    tick(local(2026, 10, 28, 9))
    assert len(got["push"]) == 2 and len(got["office"]) == 1, "never a third"
    assert row(db, a)["leader_told_at"]


def test_a_late_ask_gets_a_day_before_the_office_hears(heard):
    db, as_, s, sound, slides, got = heard
    ask(as_, s[0], sound, KENDRA)                                      # Oct 25, four days off
    tick(NOW)
    tick(NOW + timedelta(hours=12))
    assert got["office"] == []
    tick(NOW + timedelta(days=1))
    assert len(got["office"]) == 1


def test_reminders_before_a_yes(heard):
    db, as_, s, sound, slides, got = heard
    a = ask(as_, s[1], sound, KENDRA).json()["assignment"]["id"]      # Nov 1, 10:30
    tick(NOW)
    as_("owner").post(f"/planning/assignments/{a}/answer", json={"business_id": BIZ, "status": "yes"})
    ask(as_, s[1], slides, ANA)
    tick(NOW + timedelta(minutes=1))
    aa = next(r for r in db.t["serve_assignments"] if r["contact_id"] == ANA)
    as_("owner").post(f"/planning/assignments/{aa['id']}/answer", json={"business_id": BIZ, "status": "yes"})
    got["push"].clear()
    got["email"].clear()
    # A week before (Sun 10/25 10:30): Kendra said yes earlier than that.
    tick(local(2026, 10, 25, 11))
    assert titles(got, KENDRA) == ["Next Sunday you're on Sound"]
    assert got["email"] == [], "the week before is a phone note only"
    # Saturday 6 PM: tomorrow, with who's on with her.
    tick(local(2026, 10, 31, 17, 45))
    assert len(titles(got, KENDRA)) == 1
    tick(local(2026, 10, 31, 18))
    assert titles(got, KENDRA)[-1] == "Tomorrow: Sound, 10:30"
    assert [p["body"] for c, p in got["push"] if c == KENDRA][-1] == "Ana is on with you."
    assert (KENDRA, "day", "Tomorrow: Sound, 10:30") in got["email"]
    # That morning at 7, then nothing more.
    tick(local(2026, 11, 1, 7))
    assert titles(got, KENDRA)[-1] == "Today: Sound, 10:30"
    tick(local(2026, 11, 1, 9))
    assert len(titles(got, KENDRA)) == 3
    assert row(db, a)["week_sent_at"] and row(db, a)["day_sent_at"] and row(db, a)["morning_sent_at"]


def test_a_passed_reminder_is_skipped_not_sent_late(heard):
    db, as_, s, sound, slides, got = heard
    a = ask(as_, s[0], sound, KENDRA).json()["assignment"]["id"]      # Oct 25
    tick(NOW)
    as_("owner").post(f"/planning/assignments/{a}/answer", json={"business_id": BIZ, "status": "yes"})
    got["push"].clear()
    # Said yes inside the week: no "next Sunday".
    tick(NOW + timedelta(hours=1))
    assert titles(got) == [] and row(db, a)["week_sent_at"]
    # The sweep missed Saturday evening entirely: Sunday morning only says today.
    tick(local(2026, 10, 25, 7, 30))
    assert titles(got) == ["Today: Sound, 10:30"]
    assert row(db, a)["week_sent_at"] and row(db, a)["day_sent_at"]
    # The call time decides the morning: under an hour away, it's skipped.
    b = ask(as_, s[1], slides, ANA).json()["assignment"]["id"]
    tick(local(2026, 10, 25, 11))
    as_("owner").post(f"/planning/assignments/{b}/answer", json={"business_id": BIZ, "status": "yes"})
    as_("owner").patch(f"/planning/teams/{PRODUCTION}", json={"business_id": BIZ, "call_time": "07:30"})
    got["push"].clear()
    tick(local(2026, 11, 1, 7))
    assert "Today: Slides, 7:30" not in titles(got, ANA)
    assert row(db, b)["morning_sent_at"]


def test_a_cover_is_told_once_per_ask(heard):
    db, as_, s, sound, slides, got = heard
    a = ask(as_, s[1], sound, KENDRA).json()["assignment"]["id"]
    tick(NOW)
    as_("owner").post(f"/planning/assignments/{a}/answer", json={"business_id": BIZ, "status": "yes"})
    ss.ask_sub(CHURCH, KENDRA, a, JO)
    tick(NOW + timedelta(minutes=15))
    assert titles(got, JO) == ["Can you cover Sound, Nov 1?"]
    assert [p["body"] for c, p in got["push"] if c == JO][0].startswith("Kendra asked you to cover for them.")
    assert (JO, "cover", "Can you cover Sound, Nov 1?") in got["email"]
    tick(NOW + timedelta(minutes=30))
    assert len(titles(got, JO)) == 1
    # Asking again (after a stop) is a new ask.
    ss.stop_sub(CHURCH, KENDRA, a)
    ss.ask_sub(CHURCH, KENDRA, a, JO)
    tick(NOW + timedelta(minutes=45))
    assert len(titles(got, JO)) == 2
    # Jo says yes: the place is Jo's, and Jo's reminders start fresh.
    row(db, a)["week_sent_at"] = NOW.isoformat()
    ss.answer(CHURCH, JO, a, "yes")
    r = row(db, a)
    assert r["contact_id"] == JO and r["week_sent_at"] is None and r["swap_told_at"] is None


def test_phone_follows_the_boxes_and_email_always_reaches(heard):
    db, as_, s, sound, slides, got = heard
    # Kendra turned phone alerts off and the email copy off: the ask still emails.
    ss.set_hearing(CHURCH, KENDRA, "phone", False)
    ss.set_hearing(CHURCH, KENDRA, "email", False)
    ask(as_, s[0], sound, KENDRA)
    # Jo keeps phone alerts and turned the email copy off: the phone only.
    ss.set_hearing(CHURCH, JO, "email", False)
    ask(as_, s[0], slides, ANA)
    ask(as_, s[1], sound, JO)
    # Ty is sixteen: the phone, never an email.
    ask(as_, s[2], slides, TY)
    tick(NOW)
    assert titles(got, KENDRA) == []
    assert [e[0] for e in got["email"]].count(KENDRA) == 1
    assert titles(got, JO) and JO not in [e[0] for e in got["email"]]
    assert titles(got, ANA) and ANA in [e[0] for e in got["email"]]
    assert titles(got, TY) and TY not in [e[0] for e in got["email"]]


def test_no_church_switch_no_sweep(heard, monkeypatch):
    db, as_, s, sound, slides, got = heard
    ask(as_, s[0], sound, KENDRA)
    db.t["businesses"][0]["settings"] = {}
    assert ssa._churches() == []
    monkeypatch.setenv("SUNDAY_PLANNING", "off")
    assert ssa.sweep_tick(NOW) == {}
    assert got["push"] == [] and got["email"] == []


def test_how_i_hear(heard):
    db, as_, s, sound, slides, got = heard
    assert ss.hearing({**CHURCH, "settings": {}}, KENDRA) is None
    h = ss.hearing(CHURCH, KENDRA)
    assert h == {"phone_shown": True, "phone": True, "devices": 1, "email": True}
    ss.set_hearing(CHURCH, KENDRA, "phone", False)
    ss.set_hearing(CHURCH, KENDRA, "email", False)
    assert ss.hearing(CHURCH, KENDRA)["phone"] is False and ss.hearing(CHURCH, KENDRA)["email"] is False
    # Turning Serving off on My serving leaves the member's other boxes alone.
    db.t["member_push_prefs"][0]["off"] = ["news", "serving"]
    ss.set_hearing(CHURCH, KENDRA, "phone", True)
    assert db.t["member_push_prefs"][0]["off"] == ["news"]
    with pytest.raises(Exception):
        ss.set_hearing(CHURCH, KENDRA, "texts", True)
    # Serving isn't a box on Notifications: it's chosen here.
    assert "serving" not in member_push.visible_kinds({})


def test_the_office_switch_waits_for_planning(heard, monkeypatch):
    import member_portal
    kinds = lambda biz, user: [k["key"] for k in member_portal._notifications_payload(biz, user)["kinds"]]
    off = {"id": BIZ, "settings": {}}
    assert "serving" in kinds(off, PEOPLE["owner"])
    monkeypatch.setenv("SUNDAY_PLANNING", "owner")
    assert "serving" in kinds(off, PEOPLE["owner"])
    assert "serving" not in kinds(off, PEOPLE["viewer"])
    assert "serving" not in kinds(off, None)
    # One already on still shows, so it can be turned off.
    assert "serving" in kinds(CHURCH, PEOPLE["viewer"])


def test_two_sweeps_at_once_say_it_once(heard):
    """Both read the row before either marked it: only one claim wins."""
    db, as_, s, sound, slides, got = heard
    a = ask(as_, s[0], sound, KENDRA).json()["assignment"]["id"]
    stale = dict(row(db, a))
    assert ssa._claim(BIZ, stale, "notified_at", NOW) is True
    assert ssa._claim(BIZ, stale, "notified_at", NOW) is False
    # Nor for someone the place has since moved to.
    other = dict(stale, contact_id=JO)
    assert ssa._claim(BIZ, other, "nudged_at", NOW) is False
