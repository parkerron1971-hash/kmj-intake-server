"""An event's date follows the event (event_volunteers.sync, the /changed route
and the 15-minute sweep; docs/EVENT_VOLUNTEERS.md 6.7, step S3).

The table, row by row:
  * a new day or time: the date follows, and whoever said yes or was asked
    (and told) hears once; a second sync tells nobody; the ledger
    (member_push_sends) holds even when a replica told and never moved it
  * a new title or place: the date follows, nobody is told
  * into the past, more than 180 days out, into a Sunday service, or no time:
    the date stays and Who serves when flags it (event_moved); a waiting ask
    is cancelled when past
  * archived, inactive, deleted: every ask taken back by Take back's own path,
    the date off, each person told once, the ask cancelled
  * waiting asks keep their copies of the title, starts_at and place
  * quiet hours hold the whole change; the sweep does it after 7
Each pin was broken on purpose once to see it go red (the PR lists them)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import event_volunteers as evv  # noqa: E402
import member_push  # noqa: E402
import sb_clients  # noqa: E402
import sunday_planning as sp  # noqa: E402
from test_event_volunteers import (BIZ, E_LOCK, E_OUT, E_THEIRS, NOW, OTHER, ask, church, rows)  # noqa: E402,F401
from test_sunday_planning import JO, LEE, MARCUS, ZONE  # noqa: E402

A_YES, A_ASKED, A_FRESH = (f"a5500000-0000-4000-8000-00000000000{i}" for i in (1, 2, 3))
FIRST = "2026-10-30T23:00:00+00:00"       # Fri Oct 30, 6:00 PM in Chicago


@pytest.fixture
def ev(church, monkeypatch):
    """The S2 church, plus the once-only ledger (member_push_sends, unique on
    business, kind and ref_id) and every push recorded."""
    c = church
    c.db.KEYS = {**c.db.KEYS, "member_push_sends": ("business_id", "kind", "ref_id")}
    c.db.t["member_push_sends"] = []
    c.db.t["serve_prefs"] = []
    pushes = []

    def send(biz, kind, *, title, body="", url="/my", contact_ids=None, tag=None, **_):
        pushes.append({"kind": kind, "title": title, "body": body, "url": url, "to": list(contact_ids or [])})
        return 1
    monkeypatch.setattr(member_push, "send", send)
    c.pushes = pushes
    return c


def on_with_people(c):
    """The Youth Lock-in on Who serves when (put straight on by the owner),
    with Jo's yes and Lee's ask (told) on Greeter, and Marcus asked on Usher
    but not told yet."""
    r = ask(c, "owner", E_LOCK, {c.greeter: 2})
    assert r.status_code == 200, r.text
    sid = r.json()["date"]["id"]
    assert svc(c, sid)["starts_at"] == FIRST
    base = {"business_id": BIZ, "service_id": sid, "note": "", "swap_to": None, "asked_by": "Pastor Kevin",
            "asked_at": NOW.isoformat()}
    c.db.t["serve_assignments"] += [
        {**base, "id": A_YES, "position_id": c.greeter, "slot": 1, "contact_id": JO, "status": "yes",
         "notified_at": NOW.isoformat(), "week_sent_at": NOW.isoformat(), "day_sent_at": NOW.isoformat()},
        {**base, "id": A_ASKED, "position_id": c.greeter, "slot": 2, "contact_id": LEE, "status": "asked",
         "notified_at": NOW.isoformat()},
        {**base, "id": A_FRESH, "position_id": c.usher, "slot": 1, "contact_id": MARCUS, "status": "asked",
         "notified_at": None},
    ]
    c.pushes.clear()
    return sid


def entry(c, eid=E_LOCK):
    return next(e for e in c.db.t["module_entries"] if e["id"] == eid)


def svc(c, sid):
    return next(s for s in c.db.t["worship_services"] if s["id"] == sid)


def held(c, sid):
    return {a["id"]: a for a in c.db.t["serve_assignments"] if a["service_id"] == sid}


def changed(c, who="owner", eid=E_LOCK):
    return c.as_(who).post(f"/church/event-volunteers/{eid}/changed", json={"business_id": BIZ})


def said(c):
    return sorted((p["to"][0], p["title"], p["body"]) for p in c.pushes)


def moved_flag(c, sid, weeks=6):
    r = c.as_("owner").get(f"/planning/schedule?business_id={BIZ}&weeks={weeks}")
    assert r.status_code == 200, r.text
    return next(s for s in r.json()["services"] if s["id"] == sid).get("event_moved")


# ─── a new day or time ───────────────────────────────────────────────


def test_a_new_day_or_time_moves_the_date_and_each_person_hears_once(ev):
    c = ev
    sid = on_with_people(c)
    entry(c)["data"]["date"] = "2026-10-31T19:00"
    r = changed(c)
    assert r.status_code == 200, r.text
    assert r.json() == {"date": "moved", "told": 2, "requests": 0}
    assert svc(c, sid)["starts_at"] == "2026-11-01T00:00:00+00:00"
    assert said(c) == [
        (JO, "The Youth Lock-in moved to Sat, Oct 31, 7:00 PM",
         "You're still on Greeter. If you can't make it, tap Change my answer."),
        (LEE, "The Youth Lock-in moved to Sat, Oct 31, 7:00 PM", "You were asked for Greeter. Tap Yes or Can't that day."),
    ], "an ask not sent yet (Marcus) goes out with the new time, so he hears nothing now"
    assert all(p["kind"] == "serving" for p in c.pushes)
    assert {p["url"] for p in c.pushes} == {f"/my/serving/{A_YES}", f"/my/serving/{A_ASKED}"}
    a = held(c, sid)
    assert a[A_YES]["status"] == "yes" and a[A_ASKED]["status"] == "asked", "their yes stays"
    assert a[A_YES]["day_sent_at"] is None and a[A_YES]["week_sent_at"] is None, "the reminders follow the new time"
    refs = sorted(x["ref_id"] for x in c.db.t["member_push_sends"])
    assert refs == sorted(f"event-moved-{x}-20261101T0000Z-0" for x in (A_YES, A_ASKED))
    # A second sync tells nobody.
    assert changed(c).json() == {"date": "same", "told": 0, "requests": 0} and len(c.pushes) == 2
    # A replica that told them and died before the date moved: the next sync
    # moves it, and the ledger keeps anyone from hearing twice.
    svc(c, sid)["starts_at"] = FIRST
    assert changed(c).json()["date"] == "moved" and len(c.pushes) == 2
    assert svc(c, sid)["starts_at"] == "2026-11-01T00:00:00+00:00"
    # Another move is another change: each hears once more.
    entry(c)["data"]["date"] = "2026-10-31T20:00"
    assert changed(c).json()["told"] == 2 and len(c.pushes) == 4


def test_a_new_title_or_place_follows_and_nobody_is_told(ev):
    c = ev
    sid = on_with_people(c)
    entry(c)["data"].update(title="Youth Lock-in Night", location="The gym")
    assert changed(c).json() == {"date": "renamed", "told": 0, "requests": 0}
    s = svc(c, sid)
    assert (s["title"], s["place"], s["starts_at"]) == ("Youth Lock-in Night", "The gym", FIRST)
    assert c.pushes == [] and c.db.t["member_push_sends"] == []


def test_a_waiting_ask_keeps_its_copies_of_the_event(ev):
    c = ev
    r = ask(c, "shapretta", E_OUT, {c.greeter: 1})
    assert r.status_code == 200 and r.json()["request"]["status"] == "waiting"
    entry(c, E_OUT)["data"].update(title="Outreach night in the park", location="Kiwanis park",
                                   date="2026-10-23T18:30")
    got = changed(c, "shapretta", E_OUT).json()
    assert got == {"date": None, "told": 0, "requests": 1}
    req = rows(c)[0]
    assert (req["title"], req["place"], req["starts_at"], req["status"]) == (
        "Outreach night in the park", "Kiwanis park", "2026-10-23T23:30:00+00:00", "waiting")
    assert changed(c, "shapretta", E_OUT).json()["requests"] == 0, "nothing new: nothing written"


# ─── the date doesn't follow ─────────────────────────────────────────


@pytest.mark.parametrize("to, why, words", [
    ("2026-10-20T18:00", "past", "The event moved to Tue, Oct 20, 6:00 PM; this date didn't follow. Take it off or keep it."),
    ("2027-06-05T18:00", "far", "The event moved to Sat, Jun 5, 6:00 PM; this date didn't follow. Take it off or keep it."),
    ("2026-10-25T11:00", "sunday", "The event moved to Sun, Oct 25, 11:00 AM; this date didn't follow. Take it off or keep it."),
    ("2026-10-31", "no_time", "The event moved to Sat, Oct 31, with no start time; this date didn't follow. Take it off or "
                              "keep it."),
])
def test_a_move_the_date_cant_follow_leaves_it_flagged(ev, to, why, words):
    c = ev
    sid = on_with_people(c)
    assert moved_flag(c, sid) is None
    entry(c)["data"]["date"] = to
    assert changed(c).json() == {"date": "flagged", "told": 0, "requests": 0}
    assert svc(c, sid)["starts_at"] == FIRST and c.pushes == [], "the date stays; nobody is told"
    flag = moved_flag(c, sid)
    assert flag["why"] == why and flag["words"] == words
    # Put back: the flag goes.
    entry(c)["data"]["date"] = "2026-10-30T18:00"
    assert moved_flag(c, sid) is None


def test_a_waiting_ask_is_cancelled_when_its_event_moves_into_the_past(ev):
    c = ev
    ask(c, "shapretta", E_OUT, {c.greeter: 1})
    entry(c, E_OUT)["data"]["date"] = "2027-06-05T18:00"
    changed(c, "shapretta", E_OUT)
    assert rows(c)[0]["status"] == "waiting" and rows(c)[0]["starts_at"] == "2027-06-05T23:00:00+00:00", \
        "more than 180 days out: it waits, with the new time"
    entry(c, E_OUT)["data"]["date"] = "2026-10-20T19:00"
    assert changed(c, "shapretta", E_OUT).json()["requests"] == 1
    assert rows(c)[0]["status"] == "cancelled"


# ─── the event went away ─────────────────────────────────────────────


@pytest.mark.parametrize("how", ["archived", "inactive"])
def test_an_event_that_went_away_takes_its_asks_back_and_its_date_off(ev, monkeypatch, how):
    c = ev
    sid = on_with_people(c)
    taken = []
    real = sp.do_take_back
    monkeypatch.setattr(sp, "do_take_back", lambda biz, aid: taken.append(aid) or real(biz, aid))
    if how == "archived":
        entry(c)["status"] = "archived"
    else:
        c.db.t["custom_modules"][0]["is_active"] = False
    got = changed(c).json()
    assert got == {"date": "cancelled", "told": 2, "requests": 1}
    assert sorted(taken) == sorted([A_YES, A_ASKED, A_FRESH]), "Take back's own path, for every ask on the date"
    assert held(c, sid) == {}
    assert svc(c, sid)["archived_at"] is not None
    assert rows(c)[0]["status"] == "cancelled"
    assert said(c) == [(JO, "The Youth Lock-in on Fri, Oct 30 was cancelled", "You're off Greeter."),
                       (LEE, "The Youth Lock-in on Fri, Oct 30 was cancelled", "You're off Greeter.")]
    assert {p["url"] for p in c.pushes} == {"/my/serving"}
    assert sorted(x["ref_id"] for x in c.db.t["member_push_sends"]) == sorted(
        f"event-cancelled-{x}" for x in (A_YES, A_ASKED))
    assert changed(c).json() == {"date": None, "told": 0, "requests": 0} and len(c.pushes) == 2


def test_a_deleted_event_closes_its_ask_and_takes_its_date_off_in_the_sweep(ev):
    c = ev
    sid = on_with_people(c)
    w = ask(c, "shapretta", E_OUT, {c.greeter: 1}).json()["request"]
    # Deleted: both links go null (on delete set null).
    c.db.t["module_entries"] = [e for e in c.db.t["module_entries"] if e["id"] not in (E_LOCK, E_OUT)]
    for r in rows(c):
        r["entry_id"] = None
    svc(c, sid)["event_entry_id"] = None
    got = evv.sweep_tick(NOW + timedelta(minutes=5))
    assert got["people_told"] == 2
    assert held(c, sid) == {} and svc(c, sid)["archived_at"] is not None
    assert {r["id"]: r["status"] for r in rows(c)}[w["id"]] == "cancelled"
    assert all(r["status"] == "cancelled" for r in rows(c))
    assert len(c.pushes) == 2 and evv.sweep_tick(NOW + timedelta(minutes=20))["people_told"] == 0


def test_a_date_that_already_happened_is_left_alone(ev):
    c = ev
    sid = on_with_people(c)
    entry(c)["status"] = "archived"
    later = NOW + timedelta(days=10)
    assert evv.sync(BIZ, E_LOCK, now=later)["date"] == "past"
    assert len(held(c, sid)) == 3 and svc(c, sid)["archived_at"] is None and rows(c)[0]["status"] == "on"


# ─── quiet hours, the sweep, the switch, the gate ────────────────────


def test_quiet_hours_hold_the_whole_change_and_the_sweep_does_it_after(ev):
    c = ev
    sid = on_with_people(c)
    entry(c)["data"]["date"] = "2026-10-31T19:00"
    c.quiet["on"] = True
    assert changed(c).json()["date"] == "held"
    assert svc(c, sid)["starts_at"] == FIRST and c.pushes == []
    assert evv.sweep_tick(NOW + timedelta(minutes=15))["moved"] == 0
    c.quiet["on"] = False
    got = evv.sweep_tick(NOW + timedelta(minutes=30))
    assert got["moved"] == 1 and got["people_told"] == 2
    assert svc(c, sid)["starts_at"] == "2026-11-01T00:00:00+00:00" and len(c.pushes) == 2
    assert evv.sweep_tick(NOW + timedelta(minutes=45))["people_told"] == 0


def test_a_ledger_that_cant_be_read_moves_nothing_yet(ev, monkeypatch):
    c = ev
    sid = on_with_people(c)
    entry(c)["data"]["date"] = "2026-10-31T19:00"
    real = sb_clients.sb_post_as_service
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, body, prefer=None, **k: None if path.startswith("/member_push_sends")
                        else real(path, body, prefer, **k))
    assert changed(c).json()["date"] == "unsent"
    assert svc(c, sid)["starts_at"] == FIRST and c.pushes == []
    monkeypatch.setattr(sb_clients, "sb_post_as_service", real)
    assert changed(c).json() == {"date": "moved", "told": 2, "requests": 0}


def test_a_sample_church_doesnt_follow_so_nothing_changes_in_silence(ev, monkeypatch):
    c = ev
    sid = on_with_people(c)
    import sample_church
    monkeypatch.setattr(sample_church, "skip", lambda row: True)
    entry(c)["data"]["date"] = "2026-10-31T19:00"
    assert changed(c).status_code == 404
    assert evv.sweep_tick(NOW + timedelta(minutes=30)).get("moved", 0) == 0
    assert c.pushes == [] and svc(c, sid)["starts_at"] == FIRST


def test_the_platform_owners_login_moves_nothing_where_nobody_would_be_told(ev, monkeypatch):
    """Owner mode: the platform owner's own login opens the switch for them
    anywhere, but a church the switch isn't open for gets no silent change."""
    c = ev
    sid = on_with_people(c)
    monkeypatch.setenv("EVENT_VOLUNTEERS", "owner")
    entry(c)["data"]["date"] = "2026-10-31T19:00"
    assert changed(c).status_code == 404
    entry(c)["status"] = "archived"
    assert changed(c).status_code == 404
    assert c.pushes == [] and svc(c, sid)["starts_at"] == FIRST and svc(c, sid)["archived_at"] is None
    assert len(held(c, sid)) == 3
    import member_asks
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: True)
    assert changed(c).json()["date"] == "cancelled" and len(c.pushes) == 2, "its own church: changed and told"


def test_the_gate_and_the_switch(ev, monkeypatch):
    c = ev
    sid = on_with_people(c)
    assert changed(c, "viewer").status_code == 403
    assert changed(c, "outsider").status_code == 403
    assert changed(c, "stranger").status_code == 404
    entry(c)["data"]["date"] = "2026-10-31T19:00"
    monkeypatch.setenv("EVENT_VOLUNTEERS", "off")
    assert changed(c).status_code == 404
    seen = []
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: seen.append(path) or real(path))
    assert "moved" not in evv.sweep_tick(NOW + timedelta(minutes=30)) and seen == [], "not one read with it off"
    assert svc(c, sid)["starts_at"] == FIRST
    monkeypatch.setenv("EVENT_VOLUNTEERS", "on")
    assert changed(c, "shapretta").json()["date"] == "moved", "any office login that may ask"


def test_a_volunteer_with_no_phone_hears_by_email_unless_they_stopped_them(ev, monkeypatch):
    c = ev
    sid = on_with_people(c)
    import email_sender
    import group_email
    import serve_links
    for p in c.db.t["contacts"]:
        if p["id"] in (JO, LEE):
            p["email"] = f"{p['name'].split()[0].lower()}@example.org"
    c.db.t["serve_prefs"] = [{"business_id": BIZ, "contact_id": LEE, "email": True,
                              "email_stopped_at": NOW.isoformat()}]
    monkeypatch.setattr(member_push, "send", lambda *a, **k: 0)
    monkeypatch.setattr(group_email, "app_url", lambda biz: "https://lovecity.example")
    monkeypatch.setattr(serve_links, "stop_token", lambda biz, cid: f"stop-{cid}")
    mailed = []

    async def resend(**kw):
        mailed.append(kw)
        return {"id": "x"}
    monkeypatch.setattr(email_sender, "send_via_resend", resend)
    entry(c)["data"]["date"] = "2026-10-31T19:00"
    assert changed(c).json()["told"] == 2
    assert [m["to_email"] for m in mailed] == ["jo@example.org"], "Lee pressed Stop these emails"
    m = mailed[0]
    assert m["subject"] == "The Youth Lock-in moved to Sat, Oct 31, 7:00 PM"
    assert m["idempotency_key"] == f"event-moved-{A_YES}-20261101T0000Z-0"
    assert "Change my answer" in m["body"] and "Stop these emails" in m["body"]
    assert svc(c, sid)["starts_at"] == "2026-11-01T00:00:00+00:00"


def test_the_words_are_plain(ev):
    for w in (evv.moved_words("Youth Lock-in", NOW, "Greeter", "yes"), evv.moved_words("Youth Lock-in", NOW, "Greeter", "asked"),
              evv.cancelled_words("Youth Lock-in", NOW, "Greeter"),
              evv.moved_flag({"at": None, "day": NOW.date()}, "no_time")):
        for v in w.values():
            if isinstance(v, str):
                assert "—" not in v and "event_volunteer" not in v and "sync" not in v.lower()


# ─── the latest notice always names the date's time ──────────────────


def last_said(c, cid):
    return [p["title"] for p in c.pushes if p["to"] == [cid]][-1]


def test_going_back_to_a_time_it_had_before_is_told_again(ev):
    c = ev
    on_with_people(c)
    for when, said_ in (("2026-10-30T19:00", "The Youth Lock-in moved to Fri, Oct 30, 7:00 PM"),
                        ("2026-10-30T18:00", "The Youth Lock-in moved to Fri, Oct 30, 6:00 PM"),
                        ("2026-10-30T19:00", "The Youth Lock-in moved to Fri, Oct 30, 7:00 PM")):
        entry(c)["data"]["date"] = when
        assert changed(c).json()["told"] == 2, when
        assert last_said(c, JO) == said_ and last_said(c, LEE) == said_
    refs = sorted(x["ref_id"] for x in c.db.t["member_push_sends"] if A_YES in x["ref_id"])
    assert refs == sorted([f"event-moved-{A_YES}-20261031T0000Z-0", f"event-moved-{A_YES}-20261030T2300Z-1",
                           f"event-moved-{A_YES}-20261031T0000Z-2"])
    assert all(len(r) <= 200 for r in refs)


def test_told_then_the_move_lost_then_put_back_is_corrected(ev, monkeypatch):
    """Told 7 PM, the date's write lost (a blip, a crash), and the office
    puts it back to 6: everyone told 7 hears it's back to 6."""
    c = ev
    sid = on_with_people(c)
    entry(c)["data"]["date"] = "2026-10-30T19:00"
    real = sb_clients.sb_patch_as_service
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body, **k: None if path.startswith("/worship_services") else real(path, body, **k))
    assert changed(c).json() == {"date": "unsent", "told": 2, "requests": 0}
    assert svc(c, sid)["starts_at"] == FIRST
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", real)
    entry(c)["data"]["date"] = "2026-10-30T18:00"
    assert changed(c).json() == {"date": "corrected", "told": 2, "requests": 0}
    assert last_said(c, JO) == "The Youth Lock-in is back to Fri, Oct 30, 6:00 PM"
    assert changed(c).json() == {"date": "same", "told": 0, "requests": 0} and len(c.pushes) == 4
    # And the sweep's own pass finds nothing more to say.
    assert evv.sweep_tick(NOW + timedelta(minutes=15))["people_told"] == 0


# ─── a rain date ─────────────────────────────────────────────────────


def _started(c, sid, hours):
    """The date (and its event) started `hours` ago."""
    at = NOW - timedelta(hours=hours)
    svc(c, sid)["starts_at"] = at.isoformat()
    entry(c)["data"]["date"] = at.astimezone(ZONE).strftime("%Y-%m-%dT%H:%M")
    return at


def test_a_rain_date_follows_a_new_time_when_the_old_start_is_recent(ev):
    c = ev
    sid = on_with_people(c)
    _started(c, sid, 2)
    entry(c)["data"]["date"] = "2026-10-24T18:00"       # postponed after it should have started
    assert changed(c).json() == {"date": "moved", "told": 2, "requests": 0}
    assert svc(c, sid)["starts_at"] == "2026-10-24T23:00:00+00:00"
    assert last_said(c, JO) == "The Youth Lock-in moved to Sat, Oct 24, 6:00 PM"


def test_a_date_that_started_longer_ago_is_flagged_not_followed(ev):
    c = ev
    sid = on_with_people(c)
    at = _started(c, sid, 60)
    entry(c)["data"]["date"] = "2026-10-24T18:00"
    assert changed(c).json()["date"] is None, "past the rain-date window: not followed"
    assert svc(c, sid)["starts_at"] == at.isoformat() and c.pushes == []
    s = {"id": sid, "kind": "event", "event_entry_id": E_LOCK, "starts_at": at.isoformat()}
    evv.date_extras(BIZ, [s], c_user(c), now=NOW)
    assert s["event_moved"]["why"] == "started" and "didn't follow" in s["event_moved"]["words"]


def c_user(c):
    from test_event_volunteers import PEOPLE
    return PEOPLE["owner"]


def test_the_flag_never_fails_the_page(ev, monkeypatch):
    c = ev
    sid = on_with_people(c)
    entry(c)["data"]["date"] = "2026-10-25T11:00"        # a Sunday: the service check reads

    def blip(*a, **k):
        from fastapi import HTTPException
        raise HTTPException(503, "Who serves when couldn't be read just now.")
    monkeypatch.setattr(sp, "during_sunday_service", blip)
    r = c.as_("owner").get(f"/planning/schedule?business_id={BIZ}&weeks=6")
    assert r.status_code == 200
    assert next(s for s in r.json()["services"] if s["id"] == sid).get("event_moved") is None


# ─── the reminders ───────────────────────────────────────────────────


def test_a_move_re_arms_only_the_reminders_still_to_come(ev):
    c = ev
    sid = on_with_people(c)
    morning = datetime(2026, 10, 30, 8, 0, tzinfo=ZONE)       # the day itself, after 7 AM
    entry(c)["data"]["date"] = "2026-10-30T20:00"
    assert evv.sync(BIZ, E_LOCK, now=morning)["date"] == "moved"
    a = held(c, sid)[A_YES]
    assert a["day_sent_at"] and a["week_sent_at"], "the day-before and the week-before had opened: kept, never twice"
    a["morning_sent_at"] = morning.isoformat()
    entry(c)["data"]["date"] = "2026-11-06T20:00"
    assert evv.sync(BIZ, E_LOCK, now=morning)["date"] == "moved"
    a = held(c, sid)[A_YES]
    assert (a["day_sent_at"], a["morning_sent_at"], a["week_sent_at"]) == (None, None, None),         "a week out (its week-before opens Oct 30 at 8 PM): all still to come"


def test_nothing_goes_out_for_a_date_whose_change_is_held(ev, monkeypatch):
    """A cancel held through quiet hours: the serving sweep says nothing for
    the date meanwhile, even at 7 AM when its morning reminder is due."""
    import sunday_serving_alerts as ssa
    c = ev
    sid = on_with_people(c)
    seven = datetime(2026, 10, 30, 7, 5, tzinfo=ZONE)
    biz = c.db.t["businesses"][0]
    assert evv.unsettled(biz, [{"id": sid, "event": True, "entry_id": E_LOCK,
                                "at": datetime(2026, 10, 30, 18, 0, tzinfo=ZONE)}], seven) == set(), "as it was"
    entry(c)["status"] = "archived"
    c.quiet["on"] = True
    assert changed(c).json()["date"] == "held"
    c.quiet["on"] = False
    for r in held(c, sid).values():
        r.update(day_sent_at=None, morning_sent_at=None, week_sent_at=seven.isoformat())
    monkeypatch.setattr(sp, "_now", lambda: seven)
    import sunday_serving as sv
    services = sv._services(BIZ, ZONE, seven, seven + timedelta(days=22))
    assert evv.unsettled(biz, services.values(), seven) == {sid}
    got = ssa.church_tick(biz, now=seven)
    assert got["reminders"] == 0 and got["asks"] == 0 and c.pushes == [], "no reminder for a cancelled event"
    entry(c)["status"] = "active"
    assert evv.unsettled(biz, sv._services(BIZ, ZONE, seven, seven + timedelta(days=22)).values(), seven) == set()
    assert ssa.church_tick(biz, now=seven)["reminders"] >= 1, "back: its reminders go as before"


# ─── the sweep's reads ───────────────────────────────────────────────


def test_the_sweep_reads_a_church_once_however_many_events(ev, monkeypatch):
    c = ev
    on_with_people(c)
    assert ask(c, "owner", E_OUT, {c.greeter: 1}).status_code == 200
    entry(c)["data"]["date"] = "2026-10-31T19:00"
    entry(c, E_OUT)["data"]["date"] = "2026-10-23T19:00"
    # An ask on for a date long gone, its event deleted: never taken up.
    c.db.t["event_volunteer_requests"].append({
        "id": "7e700000-0000-4000-8000-000000000009", "business_id": BIZ, "entry_id": None, "status": "on",
        "service_id": "5e900000-0000-4000-8000-000000000009", "starts_at": (NOW - timedelta(days=30)).isoformat(),
        "title": "Old picnic", "created_at": (NOW - timedelta(days=40)).isoformat()})
    seen = []
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: seen.append(path) or real(path))
    got = evv.sweep_tick(NOW + timedelta(minutes=30))
    assert got["moved"] == 2
    church = [x for x in seen if f"business_id=eq.{BIZ}" in x]
    for table, most in (("/module_entries", 1), ("/custom_modules", 1), ("/serve_assignments", 1),
                        ("/member_push_sends", 1), ("/event_volunteer_requests", 2)):
        assert sum(x.startswith(table) for x in church) <= most, (table, [x for x in church if x.startswith(table)])
    assert next(r for r in rows(c) if r["id"].endswith("9"))["status"] == "on", "a long-past ask is left alone"


# ─── past the server's cap (PostgREST answers 1,000 rows at most) ─────


def capped(monkeypatch, cap, tables, only_global=False):
    """The server's cap, made small: a read of these tables returns at most
    `cap` rows, honouring order, offset and limit as PostgREST does."""
    from urllib.parse import parse_qsl
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(evv, "PAGE", cap)

    def get(path, **k):
        rows = real(path)
        table = path.lstrip("/").partition("?")[0]
        q = dict(parse_qsl(path.partition("?")[2], keep_blank_values=True))
        hit = table in tables and not (only_global and "business_id=eq." in path)
        if not isinstance(rows, list) or not (hit or "offset" in q):
            return rows
        for part in reversed((q.get("order") or "").split(",")):
            if part:
                col, _, way = part.partition(".")
                rows.sort(key=lambda r: str(r.get(col) or ""), reverse=way == "desc")
        off = int(q.get("offset") or 0)
        most = min(int(q.get("limit") or cap), cap) if hit else int(q.get("limit") or len(rows))
        if not hit:     # any other paged read pages as the server would, uncapped
            most = cap if "offset" in q else most
        return rows[off:off + most]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)


def test_every_row_on_a_date_is_read_past_the_cap(ev, monkeypatch):
    c = ev
    sid = on_with_people(c)
    held(c, sid)[A_FRESH]["notified_at"] = NOW.isoformat()       # three people who hear
    capped(monkeypatch, 2, {"serve_assignments"})
    entry(c)["data"]["date"] = "2026-10-31T19:00"
    assert changed(c).json()["told"] == 3, "a short read never reads as nobody on the date"
    entry(c)["status"] = "archived"
    assert changed(c).json() == {"date": "cancelled", "told": 3, "requests": 1}
    assert held(c, sid) == {}, "every row taken back"


def _counted_ledger(c, monkeypatch):
    """The ledger's rows written a second apart, as a real one is."""
    real = sb_clients.sb_post_as_service
    tick = {"n": 0}

    def post(path, body, prefer=None, **k):
        got = real(path, body, prefer, **k)
        if path.startswith("/member_push_sends") and got:
            tick["n"] += 1
            for r in c.db.t["member_push_sends"]:
                if r["ref_id"] == body["ref_id"]:
                    r["created_at"] = (NOW + timedelta(seconds=tick["n"])).isoformat()
        return got
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)


def test_the_ledger_is_read_whole_past_the_cap(ev, monkeypatch):
    c = ev
    on_with_people(c)
    _counted_ledger(c, monkeypatch)
    capped(monkeypatch, 1, {"member_push_sends"})
    for when in ("2026-10-30T19:00", "2026-10-30T18:00", "2026-10-30T19:00", "2026-10-30T18:00"):
        entry(c)["data"]["date"] = when
        assert changed(c).json()["told"] == 2, when
    assert last_said(c, JO) == "The Youth Lock-in moved to Fri, Oct 30, 6:00 PM"
    assert sorted(int(x["ref_id"].rsplit("-", 1)[1]) for x in c.db.t["member_push_sends"]
                  if A_YES in x["ref_id"]) == [0, 1, 2, 3]


def test_two_notices_of_one_n_the_later_written_is_the_latest(ev):
    """Two replicas raced two new times and both claimed n: the time the
    person heard last is the later-written one, so nobody is 'corrected'
    to the time they already have."""
    c = ev
    sid = on_with_people(c)
    entry(c)["data"]["date"] = "2026-10-30T19:00"
    assert changed(c).json()["told"] == 2
    c.db.t["member_push_sends"] = [
        {"id": "f1", "business_id": BIZ, "kind": "serving", "ref_id": evv.move_ref(A_YES, svc_at(c, sid), 1),
         "created_at": (NOW + timedelta(minutes=2)).isoformat()},
        {"id": "f2", "business_id": BIZ, "kind": "serving",
         "ref_id": evv.move_ref(A_YES, svc_at(c, sid) + timedelta(hours=2), 1),
         "created_at": (NOW + timedelta(minutes=1)).isoformat()},
        {"id": "f3", "business_id": BIZ, "kind": "serving", "ref_id": evv.move_ref(A_ASKED, svc_at(c, sid), 0),
         "created_at": NOW.isoformat()},
    ]
    assert changed(c).json() == {"date": "same", "told": 0, "requests": 0}


def svc_at(c, sid):
    from datetime import datetime as dt
    return dt.fromisoformat(svc(c, sid)["starts_at"])


def test_every_church_with_work_is_found_past_the_cap(ev, monkeypatch):
    c = ev
    on_with_people(c)
    assert ask(c, "owner", E_OUT, {c.greeter: 1}).status_code == 200
    c.db.t["worship_services"].append({"id": "5e800000-0000-4000-8000-000000000001", "business_id": OTHER,
                                       "title": "Their night", "kind": "event", "event_entry_id": E_THEIRS,
                                       "starts_at": "2026-10-30T23:00:00+00:00", "place": "", "items": [],
                                       "archived_at": None, "is_template": False})
    capped(monkeypatch, 1, {"worship_services", "event_volunteer_requests"}, only_global=True)
    seen = []
    real = evv.follow
    monkeypatch.setattr(evv, "follow", lambda church, now=None, **k: seen.append(str(church["id"])) or real(church, now, **k))
    evv.sweep_tick(NOW + timedelta(minutes=30))
    assert sorted(seen) == sorted([BIZ, OTHER])


def test_a_date_held_for_a_day_old_change_is_said_in_the_logs(ev, capsys):
    c = ev
    sid = on_with_people(c)
    biz = c.db.t["businesses"][0]
    entry(c)["data"]["date"] = "2026-10-31T19:00"
    services = [{"id": sid, "event": True, "entry_id": E_LOCK, "at": svc_at(c, sid)}]
    entry(c)["updated_at"] = (NOW - timedelta(hours=3)).isoformat()
    assert evv.unsettled(biz, services, NOW) == {sid}
    assert "held for a change" not in capsys.readouterr().out, "a fresh change: nothing to say"
    entry(c)["updated_at"] = (NOW - timedelta(days=2)).isoformat()
    assert evv.unsettled(biz, services, NOW) == {sid}
    assert "held for a change made 2 day(s) ago" in capsys.readouterr().out
