"""The leaders schedule: who is told, and the hourly sweep
(church_schedule_tell.py; docs/CHURCH_SCHEDULE.md sections 3 and 5, PR S1-4).
Kevin, 2026-11-18: "this is for when leaders are planning time off and have
certain obiligations so that we as a church can plan around meeting".

Driven through the real routes and the real senders (member_push.send, the
church's conversation, push_notifications.send_to_user, the email's own
render), at New Hope, a made-up church of 500, on church_schedule_fake's
tables. Only the last hop is recorded instead of sent: a phone's push
(push_notifications._send_one) and an email (church_leader_tasks.deliver).

Pins:
  * THE REASON AND THE NOTE ARE IN NO NOTICE AND NO LOG LINE: not a push, an
    email, the church's conversation, the push log, stdout or the logger; the
    sweep never asks the database for either, and a refused write is sent
    redacted. A lock screen says who and which days
  * nothing is told inside a write, and a notice that fails never fails it
  * a new ask tells whoever it went to once (told_at claimed first, let go
    when nothing could be sent, and the sweep tries again); "can't make it"
    at once, a planned ask after the church's quiet hours
  * an answer tells the one who asked once; a yes nobody had to give tells
    nobody
  * a person: a push and the church's conversation, an email only with no
    phone reached; a login: the office app's push and an email; a login whose
    address can't be read is not claimed
  * one nudge three days on, never a second
  * a waiting ask follows whoever is over the asker now; never one that
    needs no yes; it stays put while its `to` is still one of those over them
  * the reason and the note that came with the answer, and only those, go
    90 days after the last day
  * the sweep's reads name their state and go page by page
  * taken back: by the asker, whoever had been told hears; by the owner, the
    asker hears; sent once, never tried again
  * where a notice points: Dates on the Lead tab for a person, the office
    app for a login
  * two sweeps at once, or the write's notice and the sweep, tell once
  * a sample church is told nothing; before the migration, and with the
    switch off, the sweep reads nothing; on `owner` only the platform
    owner's church is swept
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import app_base  # noqa: E402
import church_assignments as cas  # noqa: E402
import church_duties as cd  # noqa: E402
import church_leader_tasks as clt  # noqa: E402
import church_over as co  # noqa: E402
import church_schedule as cs  # noqa: E402
import church_schedule_fake as fake  # noqa: E402
import church_schedule_tell as tell  # noqa: E402
import church_threads  # noqa: E402
import church_three as c3  # noqa: E402
import member_push  # noqa: E402
import push_notifications  # noqa: E402
import sample_church  # noqa: E402
import sb_clients  # noqa: E402
from church_schedule_fake import NOW, as_, day  # noqa: E402

HOPE = c3.NEW_HOPE                       # a made-up church of 500: every name in it is made up
OURS = c3.CHURCHES[0]                    # the one church the platform owner owns (the `owner` switch)
SECRET = "Surgery for my mother that week"
NOTE = "Praying for her and for you"
HOUR = timedelta(hours=1)
NIGHT = datetime(2026, 11, 19, 4, 0, tzinfo=timezone.utc)       # 11 PM at the church, still the 18th there
MORNING = NIGHT + 9 * HOUR                                      # 8 AM
SEATED = ("elena", "yusuf", "amara")     # leaders who sign in to the office app on a Member seat
REAL_LATER = member_push._later
ZERO = {"churches": 0, "moved": 0, "told": 0, "answers": 0, "nudged": 0, "cleared": 0, "held": 0, "unsent": 0,
        "unread": 0}


@pytest.fixture
def db(monkeypatch, request):
    """A database with step 1's file alone; `db` asked for with True
    (indirect) has step 2's file too."""
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    monkeypatch.setenv("CHURCH_THREADS", "on")
    monkeypatch.delenv("MEMBER_QUIET_HOURS", raising=False)
    d = fake.build(monkeypatch, limits=bool(getattr(request, "param", False)))
    for h in SEATED:
        fake.seat(d, HOPE, h)
    for t in ("church_thread_notes", "church_thread_reads", "member_push_subscriptions", "member_push_sends",
              "member_push_prefs", "member_push_held", "push_subscriptions"):
        d.t[t] = []
    for b in d.t["businesses"]:              # every church has Serving alerts on
        b["settings"] = {**b["settings"], "member_portal": {"notifications": {"serving": True}}}
    d.t["business_sites"].append({"business_id": HOPE, "slug": "new-hope", "site_config": {}})
    monkeypatch.setattr(church_threads, "_READY", {"at": 0.0, "ok": None})
    monkeypatch.setattr(push_notifications, "push_enabled", lambda: True)
    d.rang, d.mail, d.fail_to, d.patches = [], [], set(), []

    def send_one(sub, payload, table="push_subscriptions"):
        staff = table == "push_subscriptions"
        d.rang.append({"to": sub.get("user_id") if staff else sub.get("contact_id"), "staff": staff, **payload})
        return True
    monkeypatch.setattr(push_notifications, "_send_one", send_one)

    def deliver(biz, to, name, subject, html, key, reply_to=None):
        if to in d.fail_to:
            raise RuntimeError("the mail service said no")
        d.mail.append({"to": to, "name": name, "subject": subject, "html": html, "key": key, "biz": biz["id"],
                       "reply_to": reply_to})
    monkeypatch.setattr(clt, "deliver", deliver)

    real_post, real_patch = sb_clients.sb_post_as_service, sb_clients.sb_patch_as_service

    def post(path, body, prefer=None, **k):
        # member_push_sends is unique on (business_id, kind, ref_id): a note is claimed once.
        if path.startswith("/member_push_sends") and "ignore-duplicates" in (prefer or "") and any(
                all(r.get(x) == body.get(x) for x in ("business_id", "kind", "ref_id"))
                for r in d.t["member_push_sends"]):
            return []
        return real_post(path, body, prefer, **k)

    def patch(path, body, **k):
        d.patches.append((path, dict(body), bool(k.get("redact"))))
        return real_patch(path, body, **k)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    return d


@pytest.fixture
def app(db):
    return fake.client(db)


def church(db, biz=HOPE):
    return co.Church(c3.church(db, biz))


def ask(app, who, biz=HOPE, **kw):
    as_(app, biz, who)
    r = app.post("/church/schedule/asks", json={"business_id": biz, "starts_on": day(30), "ends_on": day(37),
                                                 "kind": "time_off", **kw})
    assert r.status_code == 200, r.text
    return r.json()["saved"]


def answer(app, who, ask_id, yes, biz=HOPE, **kw):
    as_(app, biz, who)
    r = app.post(f"/church/schedule/asks/{ask_id}/answer", json={"business_id": biz, "yes": yes, **kw})
    assert r.status_code == 200, r.text
    return r.json()["saved"]


def withdraw(app, who, ask_id, biz=HOPE):
    as_(app, biz, who)
    r = app.post(f"/church/schedule/asks/{ask_id}/withdraw", json={"business_id": biz})
    assert r.status_code == 200, r.text
    return r.json()["saved"]


def row(db, ask_id):
    return next(r for r in db.t["church_away_asks"] if r["id"] == ask_id)


def raw(db, handle, biz=HOPE, **kw):
    """A row put in the table as it would sit there: what the routes can't
    be made to leave (a thousand of them, one from last summer)."""
    r = {"id": str(uuid.uuid4()), "business_id": biz, "contact_id": db.who[biz][handle], "made_by": None,
         "grp": "leaders", "department_id": None, "kind": "time_off", "starts_on": day(30), "ends_on": day(37),
         "reason": None, "cover_contact_id": None, "cover_name": None, "to_user_id": None, "to_contact_id": None,
         "state": "asked", "flags": [], "decided_by_user_id": None, "decided_by_contact_id": None,
         "decided_at": None, "decided_note": None, "withdrawn_at": None, "told_at": None, "answer_told_at": None,
         "nudged_at": None, "created_at": NOW.isoformat(), "updated_at": NOW.isoformat(), **kw}
    db.t["church_away_asks"].append(r)
    return r


def phone(db, handle, biz=HOPE):
    """This person has the church's app on a phone."""
    db.t["member_push_subscriptions"].append({
        "id": str(uuid.uuid4()), "business_id": biz, "contact_id": db.who[biz][handle],
        "endpoint": f"https://push.example/{handle}", "subscription": {}})


def desk(db, user_id, biz=HOPE):
    """This login has the office app on a phone."""
    db.t["push_subscriptions"].append({"business_id": biz, "user_id": user_id,
                                       "endpoint": f"https://push.example/{user_id}", "subscription": {}})


def owner(db, biz=HOPE):
    return c3.church(db, biz)["owner_id"]


def notes(db):
    return db.t["church_thread_notes"]


def said(db) -> str:
    """Every word that left: phones, emails, the church's conversation, the
    push log, and what waited for the morning."""
    return json.dumps([db.rang, db.mail, notes(db), db.t["member_push_sends"], db.t["member_push_held"]],
                      ensure_ascii=False)


def marks(db, ask_id):
    r = row(db, ask_id)
    return r["told_at"], r["answer_told_at"], r["nudged_at"]


def quiet(db):
    return db.rang == [] and db.mail == [] and notes(db) == []


# ─── No reason, no note, anywhere ─────────────────────────────────────

def test_no_notice_and_no_log_line_ever_says_the_reason_or_the_note(app, db, caplog, capsys):
    """Every kind of notice, to a person and to a login, by phone and by
    email, with a reason on every ask and a note on every answer."""
    w = db.who[HOPE]
    caplog.set_level(logging.DEBUG)
    phone(db, "amara")
    desk(db, w["owen@"])
    planned = ask(app, "elena", reason=SECRET, cover_name="A friend")           # to a person, by phone
    office = ask(app, "sunny", reason=SECRET)                                    # to a login
    short = ask(app, "yusuf", reason=SECRET, starts_on=day(3), ends_on=day(4))   # short notice
    cant = ask(app, "elena", reason=SECRET, kind="cant", starts_on=day(1), ends_on=day(1))
    assert fake.later(db) == 4
    answer(app, "amara", planned["id"], True, note=NOTE)                         # the asker hears, by email
    answer(app, "owen", office["id"], False, note=NOTE)                          # the asker is a login
    fake.later(db)
    assert tell.sweep_tick(NOW + timedelta(days=3, hours=1))["nudged"] == 1      # the short-notice one still waits
    withdraw(app, "yusuf", short["id"])                                          # the asker takes it back
    withdraw(app, "owner", cant["id"])                                           # the owner takes one back
    fake.later(db)
    late = ask(app, "yusuf", reason=SECRET)
    db.fail_to.add("amara@newhope.church")                                       # an email that fails is logged
    db.t["member_push_subscriptions"].clear()
    fake.later(db)
    assert row(db, late["id"])["told_at"] is None
    old = raw(db, "elena", state="no", decided_at=NOW.isoformat(), decided_by_user_id=owner(db), reason=SECRET,
              decided_note=NOTE, starts_on=day(-120), ends_on=day(-110))
    tell.sweep_tick(NOW + timedelta(days=3, hours=2))
    assert old["reason"] is None
    out = capsys.readouterr()
    everything = said(db) + caplog.text + out.out + out.err
    for word in (SECRET, NOTE, "Surgery", "mother", "Praying"):
        assert word not in everything, word
    # The notices did go: this isn't an empty page being searched.
    assert len(db.rang) >= 6 and len(db.mail) >= 5 and len(notes(db)) >= 5
    for name in ("Elena", "Sunny", "Yusuf", "Amara", "Pastor Nathan"):
        assert name in everything, name
    assert "an email didn't go" in caplog.text
    # And every write this module made to the table was sent so a refusal's body is never logged.
    assert db.patches and all(redact for path, _body, redact in db.patches if path.startswith("/church_away_asks"))


def test_the_words_never_change_with_the_reason_or_the_note(app, db):
    """The same asks with and without a reason and a note read the same."""
    def run(reason, note):
        for t in ("church_away_asks", "serve_away", "church_thread_notes", "member_push_sends"):
            db.t[t].clear()
        db.rang.clear()
        db.mail.clear()
        got = ask(app, "elena", **({"reason": reason} if reason else {}))
        other = ask(app, "sunny", **({"reason": reason} if reason else {}))
        fake.later(db)
        answer(app, "amara", got["id"], False, **({"note": note} if note else {}))
        answer(app, "owen", other["id"], True, **({"note": note} if note else {}))
        fake.later(db)
        return ([(p["title"], p["body"]) for p in db.rang], [(m["subject"], m["html"]) for m in db.mail],
                [(n["title"], n["body"]) for n in notes(db)])
    phone(db, "amara")
    desk(db, db.who[HOPE]["owen@"])
    assert run(SECRET, NOTE) == run(None, None)


def test_a_lock_screen_says_who_and_which_days(app, db):
    w = db.who[HOPE]
    phone(db, "amara")
    ask(app, "elena", reason=SECRET)
    ask(app, "yusuf", reason=SECRET, starts_on=day(3), ends_on=day(3))
    fake.later(db)
    assert [(p["to"], p["title"], p["body"]) for p in db.rang] == [
        (w["amara"], "New Hope Church", "Elena asked for Dec 18 to 25 — Say yes or not this one when you can."),
        (w["amara"], "New Hope Church", "Yusuf asked for Nov 21 — Short notice. Say yes or not this one when you can.")]
    assert [(n["contact_id"], n["title"], n["body"]) for n in notes(db)] == [
        (w["amara"], "Elena asked for Dec 18 to 25", "Say yes or not this one when you can."),
        (w["amara"], "Yusuf asked for Nov 21", "Short notice. Say yes or not this one when you can.")]
    assert tell.days("2026-12-28", "2027-01-03") == "Dec 28 to Jan 3"
    assert tell.long_days("2026-12-20", "2026-12-20") == "Sunday, December 20"


def test_only_what_a_notice_may_know_gets_past_the_door():
    kept = tell._bare({"id": "a", "reason": SECRET, "decided_note": NOTE, "cover_name": "A friend", "kind": "cant",
                       "starts_on": "2026-12-20"})
    assert kept == {"id": "a", "kind": "cant", "starts_on": "2026-12-20"}
    assert "reason" not in tell.FIELDS and "note" not in tell.FIELDS


def test_a_refused_write_sent_redacted_logs_no_row(monkeypatch, caplog):
    """sb_clients logs a refusal's body unless the call is redacted, and the
    database's refusal can quote the whole row ("Failing row contains ...")."""
    import httpx
    monkeypatch.setenv("SUPABASE_URL", "https://db.example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")

    def send(self, request, **kw):
        return httpx.Response(400, request=request, json={
            "code": "23514", "message": "new row violates a check", "details": f"Failing row contains ({SECRET})"})
    monkeypatch.setattr(httpx.Client, "send", send)
    with caplog.at_level(logging.DEBUG):
        assert sb_clients.sb_patch_as_service("/church_away_asks?id=eq.abc&select=id", {"told_at": None},
                                              redact=True) is None
    assert SECRET not in caplog.text and "id=eq.…" in caplog.text


# ─── Never inside the write ───────────────────────────────────────────

def test_nothing_is_told_inside_a_write(app, db):
    phone(db, "amara")
    phone(db, "elena")
    got = ask(app, "elena")
    assert quiet(db) and marks(db, got["id"]) == (None, None, None) and len(db.later) == 1
    fake.later(db)
    assert len(db.rang) == 1
    answer(app, "amara", got["id"], True)
    assert len(db.rang) == 1 and len(db.later) == 1, "the answer waits for the write to be back too"
    fake.later(db)
    withdraw(app, "elena", got["id"])
    assert len(db.rang) == 2 and len(db.later) == 1
    fake.later(db)
    assert len(db.rang) == 3


def test_a_notice_that_fails_never_fails_the_write(app, db, monkeypatch):
    """member_push._later as production runs it: a thread of its own."""
    ran = threading.Event()

    def boom(*a, **k):
        ran.set()
        raise RuntimeError("the notice broke")
    monkeypatch.setattr(member_push, "_later", REAL_LATER)
    monkeypatch.setattr(tell, "tell_new", boom)
    got = ask(app, "elena")
    assert ran.wait(5), "it did run, on its own thread"
    assert row(db, got["id"])["state"] == "asked"

    def cant_hand_on(*a, **k):
        raise RuntimeError("no thread to be had")
    monkeypatch.setattr(member_push, "_later", cant_hand_on)
    assert ask(app, "yusuf")["state"] == "asked", "nor does failing to hand it on"


# ─── A new ask ────────────────────────────────────────────────────────

def test_a_new_ask_tells_whoever_it_went_to_once(app, db):
    w = db.who[HOPE]
    phone(db, "amara")
    got = ask(app, "elena")
    fake.later(db)
    assert [p["to"] for p in db.rang] == [w["amara"]] and row(db, got["id"])["told_at"] == NOW.isoformat()
    ch = church(db)
    assert tell.tell_new(ch, row(db, got["id"])) == "none", "the row says it was told"
    assert tell.tell_new(ch, dict(row(db, got["id"]), told_at=None)) == "taken", "another replica, an old copy"
    for n in range(1, 4):
        assert tell.sweep_tick(NOW + n * HOUR)["told"] == 0
    assert len(db.rang) == 1 and len(notes(db)) == 1 and db.mail == []


def test_a_claim_is_let_go_when_nothing_could_be_sent_and_the_sweep_tries_again(app, db):
    db.fail_to.add("amara@newhope.church")           # no phone, and the email fails
    got = ask(app, "elena")
    fake.later(db)
    assert db.rang == [] and db.mail == [] and row(db, got["id"])["told_at"] is None
    claims = [body for path, body, _r in db.patches if "told_at" in body]
    assert [bool(b["told_at"]) for b in claims] == [True, False], "claimed first, then let go"
    assert tell.sweep_tick(NOW + HOUR)["unsent"] == 1 and row(db, got["id"])["told_at"] is None
    db.fail_to.clear()
    assert tell.sweep_tick(NOW + 2 * HOUR)["told"] == 1
    assert [m["to"] for m in db.mail] == ["amara@newhope.church"] and row(db, got["id"])["told_at"]
    assert len(notes(db)) == 1, "the line in the church's conversation was written once, not once a try"
    assert tell.sweep_tick(NOW + 3 * HOUR)["told"] == 0 and len(db.mail) == 1


def test_cant_make_it_is_told_at_once_and_a_planned_ask_waits_out_quiet_hours(app, db, monkeypatch):
    w = db.who[HOPE]
    monkeypatch.setattr(cs, "_now", lambda: NIGHT)
    phone(db, "amara")
    planned = ask(app, "elena")
    cant = ask(app, "yusuf", kind="cant", starts_on=day(1), ends_on=day(1))
    fake.later(db)
    assert [(p["to"], p["body"]) for p in db.rang] == [
        (w["amara"], "Yusuf can’t make it Nov 19 — It’s on the calendar. Nothing for you to answer.")]
    assert row(db, planned["id"])["told_at"] is None and row(db, cant["id"])["told_at"]
    stats = tell.sweep_tick(NIGHT + HOUR)             # midnight
    assert stats["held"] == 1 and stats["told"] == 0 and len(db.rang) == 1
    stats = tell.sweep_tick(MORNING)
    assert stats["told"] == 1 and "Elena asked for Dec 18 to 25" in db.rang[-1]["body"]
    assert row(db, planned["id"])["told_at"] == MORNING.isoformat()


def test_an_untold_cant_make_it_is_told_by_the_sweep_until_its_days_pass(app, db):
    phone(db, "amara")
    amara = db.who[HOPE]["amara"]
    still = raw(db, "elena", kind="cant", state="yes", decided_at=NOW.isoformat(), to_contact_id=amara,
                starts_on=day(0), ends_on=day(1))
    past = raw(db, "yusuf", kind="cant", state="yes", decided_at=NOW.isoformat(), to_contact_id=amara,
               starts_on=day(-3), ends_on=day(-2))
    assert tell.sweep_tick(NOW + HOUR)["told"] == 1
    assert still["told_at"] and past["told_at"] is None and len(db.rang) == 1


# ─── An answer ────────────────────────────────────────────────────────

def test_an_answer_tells_the_one_who_asked_once(app, db):
    w = db.who[HOPE]
    phone(db, "elena")
    got = ask(app, "elena", reason=SECRET)
    other = ask(app, "yusuf")
    fake.later(db)
    db.mail.clear()
    answer(app, "amara", got["id"], True, note=NOTE)
    answer(app, "owner", other["id"], False, note=NOTE)
    fake.later(db)
    assert [(p["to"], p["body"]) for p in db.rang] == [
        (w["elena"], "Amara said yes to Dec 18 to 25 — Your time away is on the calendar.")]
    [mail] = db.mail                                   # Yusuf has no phone: the email
    assert (mail["to"], mail["subject"]) == ("yusuf@newhope.church", "New Hope Church: an answer about Dec 18 to 25")
    assert "Pastor Nathan said not this one to your time away, Friday, December 18 to Friday, December 25." \
        in mail["html"]
    assert all(row(db, a["id"])["answer_told_at"] for a in (got, other))
    for n in range(1, 4):
        assert tell.sweep_tick(NOW + n * HOUR)["answers"] == 0
    assert len(db.rang) == 1 and len(db.mail) == 1
    assert tell.tell_answer(church(db), dict(row(db, got["id"]), answer_told_at=None)) == "taken"


def test_an_answer_given_in_quiet_hours_waits_for_the_sweep(app, db, monkeypatch):
    phone(db, "elena")
    got = ask(app, "elena")
    fake.later(db)
    monkeypatch.setattr(cs, "_now", lambda: NIGHT)
    answer(app, "owner", got["id"], True)
    fake.later(db)
    assert db.rang == [] and row(db, got["id"])["answer_told_at"] is None
    assert tell.sweep_tick(MORNING)["answers"] == 1
    assert "Pastor Nathan said yes to Dec 18 to 25" in db.rang[-1]["body"] and len(db.rang) == 1


def test_a_yes_nobody_had_to_give_tells_nobody(app, db):
    w = db.who[HOPE]
    for h in ("nathan", "elena", "amara", "owen"):
        phone(db, h)
    desk(db, owner(db))
    desk(db, w["owen@"])
    own = ask(app, "owner", reason=SECRET)             # the owner's own: nobody is over them
    assert own["state"] == "yes" and own["to"] is None
    fake.later(db)
    assert quiet(db) and marks(db, own["id"]) == (None, None, None)
    assert tell.sweep_tick(NOW + HOUR) == ZERO and quiet(db), "no read of the sweep's even finds it"
    assert tell.tell_answer(church(db), row(db, own["id"])) == "none" and quiet(db), "nor is it an answer to tell"
    cant = ask(app, "elena", kind="cant", starts_on=day(0), ends_on=day(0))
    fake.later(db)
    assert [p["to"] for p in db.rang] == [w["amara"]], "whoever is over her hears; she pressed it herself"
    assert tell.sweep_tick(NOW + 2 * HOUR)["answers"] == 0 and len(db.rang) == 1
    assert tell.tell_answer(church(db), row(db, cant["id"])) == "none" and len(db.rang) == 1
    assert row(db, cant["id"])["answer_told_at"] is None


def test_an_answer_nobody_could_be_told_of_in_a_week_is_left(app, db):
    phone(db, "elena")
    week_old = raw(db, "elena", state="yes", decided_by_user_id=owner(db),
                   decided_at=(NOW - timedelta(days=8)).isoformat(), told_at=NOW.isoformat())
    recent = raw(db, "elena", state="no", decided_by_user_id=owner(db), starts_on=day(60), ends_on=day(61),
                 decided_at=(NOW - timedelta(days=6)).isoformat(), told_at=NOW.isoformat())
    assert tell.sweep_tick(NOW + HOUR)["answers"] == 1
    assert recent["answer_told_at"] and week_old["answer_told_at"] is None and len(db.rang) == 1


# ─── How someone is told ──────────────────────────────────────────────

def test_a_person_gets_a_push_and_a_line_in_the_churchs_conversation_and_no_email(app, db):
    w = db.who[HOPE]
    phone(db, "amara")
    ask(app, "elena")
    fake.later(db)
    [push], [line] = db.rang, notes(db)
    assert (push["to"], push["staff"], push["url"]) == (w["amara"], False, "/my/inbox/church")
    assert (line["contact_id"], line["thread"], line["kind"], line["direction"]) == (w["amara"], "church", "serving",
                                                                                     "church")
    assert db.mail == [], "a phone was reached"


def test_a_person_with_no_phone_gets_the_email_and_one_with_no_address_is_tried_again(app, db):
    w = db.who[HOPE]
    got = ask(app, "elena")
    fake.later(db)
    [mail] = db.mail
    assert (mail["to"], mail["name"], mail["biz"]) == ("amara@newhope.church", "Amara Stone", HOPE)
    assert mail["subject"] == "New Hope Church: Elena asked for Dec 18 to 25"
    assert "Hi Amara," in mail["html"] and "Elena Ruiz asked to be away Friday, December 18 to Friday, December 25." \
        in mail["html"]
    assert db.rang == [] and row(db, got["id"])["told_at"] and len(notes(db)) == 1
    amara = next(c for c in db.t["contacts"] if c["id"] == w["amara"])
    amara["email"] = ""
    again = ask(app, "yusuf")
    fake.later(db)
    assert len(db.mail) == 1 and row(db, again["id"])["told_at"] is None, "nothing could be sent: not claimed"
    amara["email"] = "amara@newhope.church"
    assert tell.sweep_tick(NOW + HOUR)["told"] == 1 and db.mail[-1]["subject"].endswith("Yusuf asked for Dec 18 to 25")
    switched_off = next(b for b in db.t["businesses"] if b["id"] == HOPE)
    switched_off["settings"] = {**switched_off["settings"], "member_portal": {"notifications": {}}}
    phone(db, "amara")
    third = ask(app, "elena", starts_on=day(50), ends_on=day(51))
    fake.later(db)
    assert db.rang == [] and len(db.mail) == 3 and row(db, third["id"])["told_at"], \
        "a church with Serving alerts off: the email only"


def test_an_office_login_gets_the_office_apps_push_and_an_email(app, db):
    w = db.who[HOPE]
    desk(db, w["owen@"])
    phone(db, "owen")
    got = ask(app, "sunny", reason=SECRET)
    assert got["to"]["id"] == w["owen@"]
    fake.later(db)
    [push], [mail] = db.rang, db.mail
    assert (push["to"], push["staff"], push["nav"]) == (w["owen@"], True, cas.NAV)
    assert (push["title"], push["body"]) == ("Sunny asked for Dec 18 to 25", "Say yes or not this one when you can.")
    assert (mail["to"], mail["subject"]) == ("owen@newhope.church", "New Hope Church: Sunny asked for Dec 18 to 25")
    assert "Hi Owen," in mail["html"] and "Sunny Vale asked to be away" in mail["html"]
    assert notes(db) == [], "the church's conversation is the member app's: a login isn't told there"
    assert row(db, got["id"])["told_at"]


def test_a_login_whose_address_cant_be_read_is_not_claimed(app, db, monkeypatch):
    w = db.who[HOPE]
    desk(db, w["owen@"])
    got = ask(app, "sunny")
    real = cas._login_email
    monkeypatch.setattr(cas, "_login_email", lambda ch, uid: None)
    db.patches.clear()
    fake.later(db)
    assert quiet(db) and row(db, got["id"])["told_at"] is None
    assert db.patches == [], "nothing was claimed: not even tried"
    assert tell.sweep_tick(NOW + HOUR)["unread"] == 1 and quiet(db)
    assert tell.to_login(church(db), w["owen@"], title="t", body="b", ref="r", subject="s", text="x") == {
        "rang": 0, "mailed": 0}
    monkeypatch.setattr(cas, "_login_email", real)
    assert tell.sweep_tick(NOW + 2 * HOUR)["told"] == 1 and len(db.rang) == 1 and len(db.mail) == 1


def test_a_login_with_no_address_still_gets_the_push(app, db):
    w = db.who[HOPE]
    desk(db, w["owen@"])
    next(s for s in db.t["business_users"] if s["user_id"] == w["owen@"])["invited_email"] = ""
    next(c for c in db.t["contacts"] if c["id"] == w["owen"])["email"] = ""
    got = ask(app, "sunny")
    fake.later(db)
    assert len(db.rang) == 1 and db.mail == [] and row(db, got["id"])["told_at"]


# ─── One nudge ────────────────────────────────────────────────────────

def test_one_nudge_three_days_on_and_never_a_second(app, db):
    w = db.who[HOPE]
    phone(db, "amara")
    got = ask(app, "elena", reason=SECRET)
    fake.later(db)
    db.rang.clear()
    assert tell.sweep_tick(NOW + timedelta(days=3) - HOUR)["nudged"] == 0 and db.rang == []
    assert tell.sweep_tick(NOW + timedelta(days=3, hours=1))["nudged"] == 1
    assert [(p["to"], p["body"]) for p in db.rang] == [
        (w["amara"], "Elena is still waiting on Dec 18 to 25 — Say yes or not this one when you can.")]
    assert row(db, got["id"])["nudged_at"]
    for n in range(2, 30):
        assert tell.sweep_tick(NOW + timedelta(days=3, hours=n))["nudged"] == 0
    assert len(db.rang) == 1
    assert tell.tell_nudge(church(db), dict(row(db, got["id"]), nudged_at=None),
                           now=NOW + timedelta(days=5)) == "taken"


def test_nobody_is_nudged_about_one_answered_or_one_that_needs_no_yes(app, db):
    phone(db, "amara")
    got = ask(app, "elena")
    ask(app, "yusuf", kind="cant", starts_on=day(1), ends_on=day(1))
    fake.later(db)
    answer(app, "owner", got["id"], True)
    fake.later(db)
    told = len(db.rang)
    stuck = raw(db, "yusuf", kind="cant", to_contact_id=db.who[HOPE]["amara"], told_at=NOW.isoformat(),
                starts_on=day(5), ends_on=day(5))      # a failed settle left it waiting: nobody can answer it
    assert tell.sweep_tick(NOW + timedelta(days=3, hours=1))["nudged"] == 0
    assert len(db.rang) == told and stuck["nudged_at"] is None


# ─── A waiting ask follows whoever is over them now ───────────────────

def test_a_waiting_ask_follows_whoever_is_over_them_now(app, db):
    w = db.who[HOPE]
    phone(db, "amara")
    phone(db, "abel")
    got = ask(app, "elena", reason=SECRET)
    fake.later(db)
    assert tell.sweep_tick(NOW + HOUR)["moved"] == 0, "nothing changed: it stays"
    for h in db.t["church_leader_roles"]:              # she now answers to someone else
        if h["business_id"] == HOPE and h["contact_id"] == w["elena"]:
            h["answers_to_contact_id"] = w["abel"]
    stats = tell.sweep_tick(NOW + 2 * HOUR)
    r = row(db, got["id"])
    assert (stats["moved"], stats["told"]) == (1, 1)
    assert (r["to_contact_id"], r["to_user_id"], r["state"]) == (w["abel"], None, "asked")
    assert r["told_at"] == (NOW + 2 * HOUR).isoformat(), "cleared, then claimed for the new person"
    assert [p["to"] for p in db.rang] == [w["amara"], w["abel"]]
    stats = tell.sweep_tick(NOW + 3 * HOUR)
    assert (stats["moved"], stats["told"]) == (0, 0) and len(db.rang) == 2


def test_one_whose_login_left_the_office_or_that_names_nobody_goes_to_whoever_is_over_them(app, db):
    w = db.who[HOPE]
    desk(db, owner(db))
    got = ask(app, "sunny")
    fake.later(db)
    assert row(db, got["id"])["to_user_id"] == w["owen@"] and len(db.mail) == 1
    next(s for s in db.t["business_users"] if s["user_id"] == w["owen@"])["role"] = "member"
    cd._CACHE.clear()
    stats = tell.sweep_tick(NOW + HOUR)
    r = row(db, got["id"])
    assert (stats["moved"], stats["told"]) == (1, 1) and (r["to_user_id"], r["to_contact_id"]) == (owner(db), None)
    assert db.rang[-1]["to"] == owner(db) and db.mail[-1]["to"] == "nathan@newhope.church"
    nobody = ask(app, "elena")
    db.later.clear()
    row(db, nobody["id"]).update(to_contact_id=None, to_user_id=None)
    stats = tell.sweep_tick(NOW + 2 * HOUR)
    assert (stats["moved"], stats["told"]) == (1, 1) and row(db, nobody["id"])["to_contact_id"] == w["amara"]


def test_one_that_needs_no_yes_is_never_sent_on(app, db):
    """A "can't make it", or the owner's own, left waiting by a settle that
    failed: nobody answers it, so it is nobody's to be sent."""
    cant = raw(db, "elena", kind="cant", starts_on=day(1), ends_on=day(1))
    own = raw(db, "nathan")
    before = [dict(cant), dict(own)]
    assert tell.sweep_tick(NOW + HOUR) == {**ZERO, "churches": 1}
    assert [cant, own] == before and quiet(db)


def test_it_stays_where_it_is_while_its_to_is_still_one_of_those_over_them(app, db):
    """Two oversee the office, and the ask names the second of them: it is
    not sent round the step, which would only widen who reads the reason."""
    w = db.who[HOPE]
    db.t["church_duty_holders"] += [{"business_id": HOPE, "duty": "oversee_lanes", "user_id": w[h + "@"]}
                                    for h in ("olive", "paige")]
    cd._CACHE.clear()
    got = ask(app, "sunny")
    fake.later(db)
    first = row(db, got["id"])["to_user_id"]
    second = next(w[h + "@"] for h in ("olive", "paige") if w[h + "@"] != first)
    assert first in (w["olive@"], w["paige@"])
    row(db, got["id"]).update(to_user_id=second)
    told = len(db.mail)
    assert tell.sweep_tick(NOW + HOUR)["moved"] == 0
    assert row(db, got["id"])["to_user_id"] == second and len(db.mail) == told


# ─── The reason goes after ninety days ────────────────────────────────

def test_the_reason_and_the_answers_note_go_ninety_days_after_the_last_day_and_only_those(app, db):
    """The note that came with an answer can say why, so it is as private as
    the reason and goes with it (the review of #1934)."""
    done = dict(state="yes", decided_at="2026-07-01T12:00:00+00:00", decided_by_user_id=owner(db),
                decided_note=NOTE, told_at="2026-07-01T12:00:00+00:00", answer_told_at="2026-07-01T12:00:00+00:00")
    old = raw(db, "elena", reason=SECRET, starts_on=day(-100), ends_on=day(-91), **done)
    edge = raw(db, "yusuf", reason=SECRET, starts_on=day(-95), ends_on=day(-90), **done)
    noted = raw(db, "esther", reason=None, starts_on=day(-150), ends_on=day(-140), **done)      # a note, no reason
    said = raw(db, "kara", reason=SECRET, starts_on=day(-150), ends_on=day(-140), **{**done, "decided_note": None})
    never = raw(db, "amara", reason=None, starts_on=day(-200), ends_on=day(-190), **{**done, "decided_note": None})
    waiting = ask(app, "elena", reason=SECRET)
    before = [dict(r) for r in (old, edge, noted, said, never)]
    assert tell.sweep_tick(NOW + HOUR)["cleared"] == 3
    gone = {"reason": None, "decided_note": None}
    assert old == {**before[0], **gone}, "only those two: the ask, its answer and its marks stay"
    assert edge == before[1], "ninety days exactly: one more day, for the reason and the note alike"
    assert noted == {**before[2], **gone}, "a note with no reason is found and cleared too"
    assert said == {**before[3], **gone} and never == before[4]
    assert row(db, waiting["id"])["reason"] == SECRET
    assert tell.sweep_tick(NOW + timedelta(days=1, hours=1))["cleared"] == 1
    assert edge["reason"] is None and edge["decided_note"] is None
    assert tell.sweep_tick(NOW + timedelta(days=1, hours=2))["cleared"] == 0
    assert len(db.t["church_away_asks"]) == 6
    kept = json.dumps([r for r in db.t["church_away_asks"] if r["id"] != waiting["id"]])
    assert SECRET not in kept and NOTE not in kept


# ─── What the sweep reads ─────────────────────────────────────────────

def test_every_read_of_the_sweep_names_its_state_and_goes_page_by_page(app, db):
    ask(app, "elena", reason=SECRET)
    fake.later(db)
    db.reads.clear()
    tell.sweep_tick(NOW + HOUR)
    asks = [p for p in db.reads if p.startswith("/church_away_asks?")]
    assert len(asks) == 4, asks
    for path in asks:
        q = dict(part.partition("=")[::2] for part in path.partition("?")[2].split("&"))
        assert ("order", "limit") <= tuple(k for k in q if k in ("order", "limit")) and q["limit"] == "1000", path
        assert q["order"] == "id.asc", path
        assert q.get("state", "").startswith(("eq.", "in.")) or q.get("or") == (
            "(reason.not.is.null,decided_note.not.is.null)"), path
        assert "reason" not in q["select"].split(",") and "decided_note" not in q["select"].split(","), path
    assert sum(1 for p in asks if "state=eq.asked" in p) == 1


def test_an_answered_or_taken_back_ask_is_never_told_as_new(app, db, monkeypatch):
    """Asked in quiet hours, so nobody was told yet; then answered, and
    another taken back. The untold index still holds both rows."""
    w = db.who[HOPE]
    phone(db, "amara")
    phone(db, "elena")
    monkeypatch.setattr(cs, "_now", lambda: NIGHT)
    a = ask(app, "elena")
    b = ask(app, "yusuf")
    fake.later(db)
    answer(app, "owner", a["id"], True)
    withdraw(app, "yusuf", b["id"])
    fake.later(db)
    assert quiet(db)
    stats = tell.sweep_tick(MORNING)
    assert (stats["told"], stats["answers"]) == (0, 1)
    assert [p["to"] for p in db.rang] == [w["elena"]], "the answer, to the one who asked; nothing to the one over her"
    assert row(db, a["id"])["told_at"] is None and row(db, b["id"])["told_at"] is None


def test_past_a_thousand_rows_the_sweep_still_reaches_the_last(app, db):
    w = db.who[HOPE]
    phone(db, "amara")
    told = NOW.isoformat()
    for n in range(1003):
        raw(db, "elena", id=f"00000000-0000-4000-8000-{n:012d}", to_contact_id=w["amara"], told_at=told,
            nudged_at=told, starts_on=day(40 + n), ends_on=day(40 + n))
        raw(db, "elena", id=f"10000000-0000-4000-8000-{n:012d}", state="no", decided_at="2026-06-01T12:00:00+00:00",
            reason=SECRET, starts_on=day(-200), ends_on=day(-200))
    last = raw(db, "elena", id="ffffffff-0000-4000-8000-000000000000", to_contact_id=w["amara"])
    db.reads.clear()
    stats = tell.sweep_tick(NOW + HOUR)
    assert (stats["told"], stats["cleared"]) == (1, 1003)
    assert last["told_at"] and len(db.rang) == 1
    assert not any(r["reason"] for r in db.t["church_away_asks"])
    assert sum(1 for p in db.reads if p.startswith("/church_away_asks?") and "id=gt." in p) >= 2, "second pages"


# ─── Taken back ───────────────────────────────────────────────────────

def test_taken_back_by_the_one_who_asked_tells_whoever_had_been_told(app, db):
    w = db.who[HOPE]
    phone(db, "amara")
    phone(db, "elena")
    got = ask(app, "elena", reason=SECRET)
    fake.later(db)
    withdraw(app, "elena", got["id"])
    fake.later(db)
    assert [(p["to"], p["body"]) for p in db.rang][1:] == [
        (w["amara"], "Elena took back Dec 18 to 25 — Nothing for you to do.")]


def test_taken_back_before_anyone_was_told_tells_nobody(app, db, monkeypatch):
    phone(db, "amara")
    phone(db, "elena")
    monkeypatch.setattr(cs, "_now", lambda: NIGHT)
    got = ask(app, "elena")
    fake.later(db)
    withdraw(app, "elena", got["id"])
    fake.later(db)
    assert quiet(db)
    assert tell.sweep_tick(MORNING) == ZERO and quiet(db)


def test_taken_back_by_the_owner_tells_the_one_who_asked(app, db):
    w = db.who[HOPE]
    phone(db, "amara")
    phone(db, "elena")
    got = ask(app, "elena", reason=SECRET)
    fake.later(db)
    withdraw(app, "owner", got["id"])
    fake.later(db)
    assert [(p["to"], p["body"]) for p in db.rang][1:] == [
        (w["elena"], "Your time away, Dec 18 to 25, was taken back — Pastor Nathan took it back.")]
    office = ask(app, "sunny")                         # whoever oversees the office takes back one of the office's
    db.later.clear()
    row(db, office["id"]).update(to_user_id=owner(db))
    withdraw(app, "owen", office["id"])
    fake.later(db)
    assert db.mail[-1]["to"] == "sunny@newhope.church" and "Owen took back your time away" in db.mail[-1]["html"]


def test_a_take_back_is_sent_once_and_never_tried_again(app, db):
    got = ask(app, "elena")
    fake.later(db)                                     # she was told, by email
    assert len(db.mail) == 1
    db.fail_to.add("amara@newhope.church")
    before = dict(row(db, got["id"]))
    withdraw(app, "elena", got["id"])
    after = dict(row(db, got["id"]))
    db.patches.clear()
    fake.later(db)
    db.fail_to.clear()
    for n in range(1, 4):
        tell.sweep_tick(NOW + n * HOUR)
    assert len(db.mail) == 1, "it failed once and is not sent later"
    assert row(db, got["id"]) == after and after["told_at"] == before["told_at"]
    assert not [path for path, _body, _r in db.patches if path.startswith("/church_away_asks")], "no mark claims it"


# ─── Where a notice points ────────────────────────────────────────────

def test_a_person_is_pointed_at_their_dates_and_a_login_at_the_office_app(app, db):
    """Dates on the Lead tab (member_portal_dates) is where a person answers
    and asks, so that is where their notice opens; the button says so."""
    w = db.who[HOPE]
    desk(db, w["owen@"])
    ask(app, "elena")
    ask(app, "sunny")
    fake.later(db)
    to_person, to_login = db.mail
    assert 'href="https://new-hope.mysolutionist.app/my/lead/dates"' in to_person["html"]
    assert "Open your dates</a>" in to_person["html"] and " tab</a>" not in to_person["html"]
    assert notes(db)[0]["url"] == "/my/lead/dates" == tell.MEMBER_PAGE
    assert f'href="{app_base.app_base_url()}' in to_login["html"] and "/my/lead" not in to_login["html"]
    assert "Open your dates" not in to_login["html"]
    assert db.rang[0]["nav"] == cas.NAV


# ─── Told once, whoever gets there first ──────────────────────────────

def test_two_sweeps_at_once_tell_once(app, db, monkeypatch):
    phone(db, "amara")
    monkeypatch.setattr(cs, "_now", lambda: NIGHT)
    got = ask(app, "elena")
    fake.later(db)
    assert quiet(db)
    racing, other = sb_clients.sb_patch_as_service, {}

    def patch(path, body, **k):
        if body.get("told_at") and not other:
            other["stats"] = None
            other["stats"] = tell.sweep_tick(MORNING)       # the other worker gets there first
        return racing(path, body, **k)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    mine = tell.sweep_tick(MORNING)
    assert other["stats"]["told"] == 1 and mine["told"] == 0
    assert len(db.rang) == 1 and len(notes(db)) == 1 and row(db, got["id"])["told_at"]
    assert db.mail == [], "the one who lost the claim sent nothing at all: not a push, not the email instead"


def test_the_writes_own_notice_and_the_sweep_tell_once(app, db):
    phone(db, "amara")
    got = ask(app, "elena")
    assert tell.sweep_tick(NOW + timedelta(seconds=60))["told"] == 0, "this new: left to the write's own notice"
    assert tell.sweep_tick(NOW + HOUR)["told"] == 1, "the write's notice never ran (its replica went away)"
    assert fake.later(db) == 1 and len(db.rang) == 1, "and when it does run, late, it says nothing more"
    assert row(db, got["id"])["told_at"] == (NOW + HOUR).isoformat()


def test_the_same_answer_handed_on_twice_is_told_once(app, db):
    phone(db, "elena")
    got = ask(app, "elena")
    fake.later(db)
    answer(app, "amara", got["id"], True)
    [hand_on] = db.later
    db.later.append(hand_on)
    assert fake.later(db) == 2 and len(db.rang) == 1


# ─── A sample church, the migration, the switch ───────────────────────

def test_a_sample_church_is_told_nothing(app, db, monkeypatch):
    w = db.who[HOPE]
    for h in ("amara", "elena", "yusuf"):
        phone(db, h)
    desk(db, w["owen@"])
    got = ask(app, "elena", reason=SECRET)
    ask(app, "sunny")
    raw(db, "yusuf", kind="cant", state="yes", decided_at=NOW.isoformat(), to_contact_id=w["amara"],
        starts_on=day(0), ends_on=day(1))
    raw(db, "yusuf", state="yes", decided_at=NOW.isoformat(), decided_by_user_id=owner(db),
        to_contact_id=w["amara"], told_at=NOW.isoformat())
    old = raw(db, "elena", state="no", decided_at="2026-06-01T12:00:00+00:00", reason=SECRET,
              starts_on=day(-200), ends_on=day(-200))
    next(b for b in db.t["businesses"] if b["id"] == HOPE)["is_sample"] = True
    monkeypatch.setattr(sample_church, "_columns_ready", lambda: True)
    sample_church._reset_for_tests()
    db.patches.clear()
    assert fake.later(db) == 2
    withdraw(app, "elena", got["id"])
    fake.later(db)
    for n in (1, 2, 80):
        assert tell.sweep_tick(NOW + n * HOUR) == ZERO
    assert quiet(db) and db.patches == [] and db.t["member_push_sends"] == [] and old["reason"] == SECRET


def test_before_the_migration_the_sweep_reads_nothing_and_sends_nothing(app, db, monkeypatch):
    phone(db, "amara")
    ask(app, "elena")
    monkeypatch.setattr(cs, "_FORCE", False)
    db.reads.clear()
    db.patches.clear()
    assert tell.sweep_tick(NOW + HOUR) == ZERO
    assert db.reads == [] and db.patches == [] and quiet(db)
    assert fake.later(db) == 1 and quiet(db), "nor does a notice a write handed on"


def test_asking_whether_the_tables_are_there_is_all_the_sweep_reads_before_them(db, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://db.example.test")
    monkeypatch.setattr(cs, "_FORCE", None)
    monkeypatch.setattr(cs, "_STATE", {"yes": None, "at": 0.0})
    monkeypatch.setattr(sb_clients, "last_error", lambda: {"status": 404, "code": "PGRST205", "message": ""})
    db.fail = {"get": "/church_away_asks"}
    db.reads.clear()
    assert tell.sweep_tick(NOW + HOUR) == ZERO
    assert db.reads == ["/church_away_asks?select=id&limit=1"]


def test_with_the_switch_off_nothing_is_read_and_nobody_is_told(app, db, monkeypatch):
    phone(db, "amara")
    ask(app, "elena")
    monkeypatch.setenv("CHURCH_SCHEDULE", "off")
    db.reads.clear()
    assert tell.sweep_tick(NOW + HOUR) == ZERO and db.reads == []
    assert fake.later(db) == 1 and quiet(db)


@pytest.mark.parametrize("assignments", ["owner", "on"])
def test_on_owner_only_the_platform_owners_church_is_swept(app, db, monkeypatch, assignments):
    """CHURCH_SCHEDULE=owner, with church assignments on its own `owner` or
    open to every church: either way the sweep works one church."""
    fake.seat(db, OURS, "yolanda")
    monkeypatch.setattr(cs, "_now", lambda: NIGHT)      # asked in quiet hours: both wait for the sweep
    ours = ask(app, "yolanda", OURS)
    theirs = ask(app, "elena")
    fake.later(db)
    assert quiet(db)
    monkeypatch.setenv("CHURCH_SCHEDULE", "owner")
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", assignments)
    monkeypatch.setattr(cas, "_platform_owner_id", lambda: c3.LC_OWNER)
    db.reads.clear()
    stats = tell.sweep_tick(MORNING)
    assert (stats["churches"], stats["told"]) == (1, 1)
    assert [m["biz"] for m in db.mail] == [OURS] and row(db, ours["id"])["told_at"]
    assert row(db, theirs["id"])["told_at"] is None
    if assignments == "owner":
        assert all(HOPE not in p for p in db.reads), "the other church isn't read at all"


def test_the_sweep_follows_church_assignments_switch_too(app, db, monkeypatch):
    phone(db, "amara")
    ask(app, "elena")
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    monkeypatch.setattr(cas, "_platform_owner_id", lambda: c3.LC_OWNER)
    assert tell.sweep_tick(NOW + HOUR) == ZERO and quiet(db)


def test_one_church_that_fails_never_stops_the_others(app, db, monkeypatch):
    fake.seat(db, OURS, "yolanda")
    ask(app, "yolanda", OURS)
    ask(app, "elena")
    db.later.clear()
    real = cs.nearest

    def nearest(ch, cid):
        if ch.b == OURS:
            raise RuntimeError("this church's map broke")
        return real(ch, cid)
    monkeypatch.setattr(cs, "nearest", nearest)
    stats = tell.sweep_tick(NOW + HOUR)
    assert (stats["churches"], stats["told"]) == (2, 1) and [m["biz"] for m in db.mail] == [HOPE]


# ─── The job ──────────────────────────────────────────────────────────

def test_the_sweep_runs_hourly_on_the_worker_and_the_switch_is_read_on_both_services():
    with open(os.path.join(ROOT, "kmj_intake_automation.py"), encoding="utf-8") as f:
        src = f.read()
    assert ('scheduler.add_job(g("church_schedule_sweep", _cst.sweep_tick), "interval", hours=1,\n'
            '                          id="church_schedule_sweep")') in src
    with open(os.path.join(HERE, "test_sample_church_no_sends.py"), encoding="utf-8") as f:
        assert '"church_schedule_sweep": "church_schedule_tell:sweep_tick"' in f.read()
    with open(os.path.join(ROOT, ".env.example"), encoding="utf-8") as f:
        env = f.read()
    block = env[env.index("# The leaders schedule (church_schedule.py"):env.index("# CHURCH_SCHEDULE=on")]
    assert "BOTH services" in block and "kmj-intake-worker" in block and "unset means owner on both" in block


# ─── Step 2: an ask that went up for an exception ─────────────────────

LIMITS = pytest.mark.parametrize("db", [True], indirect=True)
SUNDAY = day(32)                         # Sunday 20 December 2026: inside day(30)..day(37)


def full(db):
    """The leaders number at two, and two leaders away that Sunday."""
    db.t["church_schedule_settings"].append({"business_id": HOPE, "notice_days": 14, "leaders_limit": 2,
                                             "office_limit": None, "service_weekdays": None})
    for h in ("wren", "kara"):
        db.t["serve_away"].append({"id": str(uuid.uuid4()), "business_id": HOPE, "contact_id": db.who[HOPE][h],
                                   "starts_on": SUNDAY, "ends_on": SUNDAY, "note": "", "ask_id": None, "kind": None})


@LIMITS
def test_a_flagged_asks_notice_goes_to_whoever_it_went_up_to_and_says_only_that_it_is_past_the_number(app, db):
    w = db.who[HOPE]
    full(db)
    phone(db, "amara")
    desk(db, w["owen@"])
    got = ask(app, "yusuf", reason=SECRET)
    assert got["flags"] == ["over_limit"] and got["to"]["id"] == w["owen@"]
    assert quiet(db), "nothing is told inside the write"
    assert fake.later(db) == 1
    assert [(p["to"], p["staff"], p["title"], p["body"]) for p in db.rang] == [
        (w["owen@"], True, "Yusuf asked for Dec 18 to 25",
         "It’s past the number who can be away at once, so it came to you. Say yes or not this one when you can.")]
    [mail] = db.mail
    assert mail["to"] == "owen@newhope.church" and mail["subject"] == "New Hope Church: Yusuf asked for Dec 18 to 25"
    assert ("Yusuf Grant asked to be away Friday, December 18 to Friday, December 25. It’s past the number who can "
            "be away at once, so it came to you.") in mail["html"]
    assert notes(db) == [], "the one over him (a person, with a phone) hears nothing: it isn't hers to answer"
    everything = said(db)
    assert SECRET not in everything and "Amara" not in everything
    for word in ("Wren", "Kara", "two", "2 "):            # never who else is away, never how many
        assert word not in json.dumps([db.rang, [m["html"].split("</style>")[-1] for m in db.mail]]), word
    assert row(db, got["id"])["told_at"] is not None


@LIMITS
def test_a_yes_that_no_longer_lands_tells_the_new_person_once_and_never_the_reason(app, db):
    w = db.who[HOPE]
    db.t["church_schedule_settings"].append({"business_id": HOPE, "notice_days": 14, "leaders_limit": 2,
                                             "office_limit": None, "service_weekdays": None})
    phone(db, "amara")
    desk(db, w["owen@"])
    got = ask(app, "yusuf", reason=SECRET)
    fake.later(db)
    assert [p["to"] for p in db.rang] == [w["amara"]], "room when he asked: the one over him"
    db.rang.clear()
    db.mail.clear()
    notes(db).clear()
    for h in ("wren", "kara"):
        db.t["serve_away"].append({"id": str(uuid.uuid4()), "business_id": HOPE, "contact_id": w[h],
                                   "starts_on": SUNDAY, "ends_on": SUNDAY, "note": "", "ask_id": None, "kind": None})
    as_(app, HOPE, "amara")
    r = app.post(f"/church/schedule/asks/{got['id']}/answer", json={"business_id": HOPE, "yes": True})
    assert r.status_code == 409 and quiet(db), "told after the write, never inside it"
    assert fake.later(db) == 1
    assert [(p["to"], p["title"]) for p in db.rang] == [(w["owen@"], "Yusuf asked for Dec 18 to 25")]
    assert "past the number" in db.rang[0]["body"] and SECRET not in said(db)
    assert tell.sweep_tick(NOW + HOUR)["told"] == 0, "once"
    assert len(db.rang) == 1


def test_the_words_for_a_flagged_ask_say_only_that_it_is_past_the_number_or_on_a_protected_day():
    import re

    def words(*flags):
        return tell.new_words("New Hope Church", "Owen Diaz", "Yusuf Grant", {
            "kind": "time_off", "starts_on": day(30), "ends_on": day(37), "flags": list(flags), "reason": SECRET})
    assert words("over_limit")["body"] == ("It’s past the number who can be away at once, so it came to you. Say yes "
                                           "or not this one when you can.")
    assert words("protected_day")["body"] == ("It’s on a protected day, so it came to you. Say yes or not this one "
                                              "when you can.")
    assert words("short_notice", "over_limit", "protected_day")["body"] == (
        "Short notice. It’s past the number who can be away at once, and on a protected day, so it came to you. Say "
        "yes or not this one when you can.")
    assert words("pair")["body"].startswith("It needs an exception, so it came to you.")
    assert words()["body"] == "Say yes or not this one when you can." and words("serving") == words()
    for flags in (("over_limit",), ("protected_day",), ("over_limit", "protected_day"), ("pair",)):
        got = json.dumps(words(*flags), ensure_ascii=False)
        assert SECRET not in got and "Dec 20" not in got and not re.search(r"\d+ (are|is) ", got), got
    assert tell.up_words({"flags": ["short_notice", "serving"]}) == ""


def test_the_sweep_never_sends_a_flagged_ask_back_down_to_the_nearest_step(app, db):
    """It went up for an exception: it stays with whoever may give one."""
    w = db.who[HOPE]
    his = raw(db, "yusuf", flags=["over_limit"], to_user_id=w["owen@"], told_at=NOW.isoformat())
    hers = raw(db, "elena", flags=["protected_day"], to_user_id=owner(db), told_at=NOW.isoformat())
    plain = raw(db, "kara", to_user_id=w["owen@"], told_at=NOW.isoformat(), starts_on=day(40), ends_on=day(41))
    got = tell.sweep_tick(NOW + HOUR)
    assert got["moved"] == 1, "only the one with no flag, which had no business being with him"
    assert (his["to_user_id"], his["to_contact_id"]) == (w["owen@"], None), "not back down to Amara"
    assert (hers["to_user_id"], hers["to_contact_id"]) == (owner(db), None)
    assert (plain["to_user_id"], plain["to_contact_id"]) == (None, w["amara"])
    assert tell.sweep_tick(NOW + 2 * HOUR)["moved"] == 0


def test_the_sweep_sends_a_flagged_ask_on_only_when_it_no_longer_sits_with_someone_who_may_give_the_exception(app, db):
    w = db.who[HOPE]
    # With the one over him (a row the routes never leave), with an Admin, and a guarded leader's with the office.
    down = raw(db, "yusuf", flags=["over_limit"], to_contact_id=w["amara"], told_at=NOW.isoformat())
    admin = raw(db, "celia", flags=["over_limit"], to_user_id=w["tessa@"], told_at=NOW.isoformat())
    guarded = raw(db, "elena", flags=["over_limit"], to_user_id=w["owen@"], told_at=NOW.isoformat())
    own = raw(db, "owen", flags=["over_limit"], to_user_id=w["owen@"], told_at=NOW.isoformat())
    assert tell.sweep_tick(NOW + HOUR)["moved"] == 4
    assert (down["to_user_id"], down["to_contact_id"]) == (w["owen@"], None), "up"
    assert down["told_at"] not in (None, NOW.isoformat()), "and whoever it went up to was told in the same sweep"
    assert admin["to_user_id"] == w["owen@"], "an Admin gives no exception"
    assert guarded["to_user_id"] == owner(db), "a guarded leader's is the owner's alone"
    assert own["to_user_id"] == owner(db), "nobody holds their own"
    assert tell.sweep_tick(NOW + 2 * HOUR)["moved"] == 0
    # Whoever oversees the office stops doing so: what sat with them goes to the owner.
    seat = next(s for s in db.t["business_users"] if s["user_id"] == w["owen@"])
    seat["role"] = "member"
    assert tell.sweep_tick(NOW + 3 * HOUR)["moved"] == 2
    assert down["to_user_id"] == owner(db) and admin["to_user_id"] == owner(db)


def test_the_sweep_never_sends_a_flagged_ask_to_the_login_that_entered_it(app, db):
    """Two oversee the office. One entered the ask for someone (and so can't
    answer it); it went up to the other, who then leaves. The sweep sends
    it to the owner: never to the one who entered it."""
    w = db.who[HOPE]
    lead = next(h for h in db.t["church_leader_roles"] if h["business_id"] == HOPE and h["contact_id"] == w["owen"])
    db.t["church_leader_roles"].append(dict(lead, id=str(uuid.uuid4()), contact_id=w["olive"]))
    assert cs.office_overseers(church(db)) == sorted([w["owen@"], w["olive@"]]), "two of them now"
    his = raw(db, "yusuf", flags=["over_limit"], made_by=w["olive@"], to_user_id=w["owen@"], told_at=NOW.isoformat())
    sat = raw(db, "kara", flags=["over_limit"], made_by=w["olive@"], to_user_id=w["olive@"], told_at=NOW.isoformat(),
              starts_on=day(40), ends_on=day(41))
    assert "made_by" in tell.FIELDS.split(",") and tell._bare(his)["made_by"] == w["olive@"]
    desk(db, w["owen@"])
    got = tell.sweep_tick(NOW + HOUR)
    assert got["moved"] == 1 and his["to_user_id"] == w["owen@"], "the first is with someone who may give it: it stays"
    assert sat["to_user_id"] == w["owen@"], "one that sat with the login that entered it goes to the other"
    seat = next(s for s in db.t["business_users"] if s["user_id"] == w["owen@"])
    seat["role"] = "member"                               # he leaves the office
    assert tell.sweep_tick(NOW + 2 * HOUR)["moved"] == 2
    assert (his["to_user_id"], sat["to_user_id"]) == (owner(db), owner(db)), "the owner, never the one who entered them"
    assert w["olive@"] not in said(db) and "made_by" not in said(db), "who entered it is in no notice"
