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
from datetime import timedelta

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
from test_event_volunteers import (BIZ, E_LOCK, E_OUT, NOW, ask, church, rows)  # noqa: E402,F401
from test_sunday_planning import JO, LEE, MARCUS  # noqa: E402

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
    assert refs == sorted(f"event-moved-{x}-2026-11-01T00:00:00+00:00" for x in (A_YES, A_ASKED))
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
    assert evv.sync(BIZ, E_LOCK, now=later)["date"] is None
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


def test_a_sample_church_follows_and_tells_nobody(ev, monkeypatch):
    c = ev
    sid = on_with_people(c)
    import sample_church
    monkeypatch.setattr(sample_church, "skip", lambda row: True)
    entry(c)["data"]["date"] = "2026-10-31T19:00"
    assert changed(c).json() == {"date": "moved", "told": 0, "requests": 0}
    assert c.pushes == [] and c.db.t["member_push_sends"] == []
    assert svc(c, sid)["starts_at"] == "2026-11-01T00:00:00+00:00"


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
    assert m["idempotency_key"] == f"event-moved-{A_YES}-2026-11-01T00:00:00+00:00"
    assert "Change my answer" in m["body"] and "Stop these emails" in m["body"]
    assert svc(c, sid)["starts_at"] == "2026-11-01T00:00:00+00:00"


def test_the_words_are_plain(ev):
    for w in (evv.moved_words("Youth Lock-in", NOW, "Greeter", "yes"), evv.moved_words("Youth Lock-in", NOW, "Greeter", "asked"),
              evv.cancelled_words("Youth Lock-in", NOW, "Greeter"),
              evv.moved_flag({"at": None, "day": NOW.date()}, "no_time")):
        for v in w.values():
            if isinstance(v, str):
                assert "—" not in v and "event_volunteer" not in v and "sync" not in v.lower()
