"""The hourly sweeps take back a hand-off that wasn't the login's to make
(church_leader_tasks.take_back, church_over.wrong_hands;
docs/CHURCH_ASSIGNMENTS.md, "Every path that hands someone a task"). Kevin,
2026-11-12: "admins can not give work to elders and pastors": only the
church's owner, or the ministry chain on the leaders map, can.

Every server route asks that. The office's Tasks screen writes `tasks`
straight to the database from the browser, so a request made by hand can
hand a pastor or an elder a task and no server code runs. The sweeps that
tell someone a task is theirs are where the server first sees it, so they
ask church_over.may_hand before anyone is told.

Pins, at Love City (church_three), through both real sweeps
(church_office_tasks for a login, church_leader_tasks for one of the
church's people):
  * an office seat's hand-off to a pastor or an elder is taken back as the
    board leaves one: the task stays, handed to no one, their name in its
    title, why in its notes; nobody is told it is theirs; the login that
    handed it is told once, in one email and one push
  * to someone who isn't a pastor or an elder: told as before
  * the owner's hand-off to a pastor is told; a task to yourself; one no
    login handed; the ministry chain on the map still counts
  * closed (CHURCH_ASSIGNMENTS off): told as before, nothing more read
  * who is a pastor unread: the task is left exactly as it is, nobody is
    told, and the next sweep decides
  * a second sweep changes nothing more; handed out again, the name and the
    note are on it once
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_board as cb  # noqa: E402
import church_leader_tasks as clt  # noqa: E402
import church_office_tasks as cot  # noqa: E402
import church_over as co  # noqa: E402
import church_three as c3  # noqa: E402
import sb_clients  # noqa: E402
from church_three import LOVE_CITY  # noqa: E402

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)      # Thursday, 10 AM in Detroit
WHY = "Only the owner, or whoever is over them on the leaders map, gives a pastor or an elder work."


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "on")
    d = c3.build(monkeypatch)
    for b in d.t["businesses"]:                                # each church's clock, as its own data says it
        tz = (b.get("settings") or {}).get("timezone")
        if tz:
            b["settings"] = {**b["settings"], "availability": {"timezone": tz}}
    monkeypatch.delenv("PLATFORM_DEFAULT_TZ", raising=False)
    d.t["tasks"] = [t for t in d.t["tasks"] if t["business_id"] != LOVE_CITY]      # only what these tests hand out
    d.sent, d.pushes, d.fail_to = [], [], set()

    def deliver(biz, to, name, subject, html, key, reply_to=None):
        if to in d.fail_to:
            raise RuntimeError("Resend said no")
        d.sent.append({"to": to, "name": name, "subject": subject, "html": html, "key": key})
    monkeypatch.setattr(clt, "deliver", deliver)
    import push_notifications
    monkeypatch.setattr(push_notifications, "send_to_user", lambda uid, **kw: d.pushes.append({"to": uid, **kw}) or 1)
    return d


def login(db, handle):
    return c3.church(db, LOVE_CITY)["owner_id"] if handle == "owner" else db.who[LOVE_CITY][handle + "@"]


def person(db, handle):
    return db.who[LOVE_CITY][handle]


def hand(db, n, title, *, by, to=None, to_person=None, notes=None):
    """A task as the Tasks screen's own write leaves it: handed to a login
    (`to`) or to one of the church's people (`to_person`), handed_by stamped
    by the database with the login that wrote it."""
    tid = f"7a000000-0000-4000-8000-{n:012d}"
    db.t["tasks"].append({
        "id": tid, "business_id": LOVE_CITY, "title": title, "description": notes, "status": "todo",
        "priority": "medium", "due_date": "2026-11-20", "assigned_to": login(db, to) if to else None,
        "assigned_contact_id": person(db, to_person) if to_person else None,
        "handed_by": login(db, by) if by else None, "seat_told_at": None, "seat_late_told_at": None,
        "leader_told_at": None, "late_told_at": None, "done_by_contact_id": None, "completed_at": None,
        "created_at": "2026-11-12T14:30:00+00:00"})
    return tid


def task(db, tid):
    return next(t for t in db.t["tasks"] if t["id"] == tid)


def yours(db):
    """Every "this is yours" email and push: who was told a task is theirs."""
    mails = [m["to"] for m in db.sent if m["key"].startswith(("office-task-", "office-tasks-", "leader-task"))
             and not m["key"].startswith("office-task-back-") and "-late-" not in m["key"]]
    return sorted(mails), sorted(p["to"] for p in db.pushes if not p["tag"].startswith("task-back-"))


def back(db):
    return [m for m in db.sent if m["key"].startswith("office-task-back-")]


# ─── A login's task (church_office_tasks) ─────────────────────────────

def test_an_office_seats_hand_off_to_a_pastors_login_is_taken_back_and_never_told(db):
    tid = hand(db, 1, "Review the safety policy", by="minnie", to="jessica", notes="Before the board meets.")
    stats = cot.sweep_tick(NOW)
    t = task(db, tid)
    assert stats["office_taken_back"] == 1 and stats["office_told"] == 0 and stats["office_rule_unread"] == 0
    assert t["assigned_to"] is None and t["assigned_contact_id"] is None, "handed to no one"
    assert t["title"] == "Review the safety policy (Jessica McCloud)", "her name, as the board writes it"
    assert t["description"] == ("Before the board meets.\n\nThis was handed to Jessica McCloud, then taken back. " + WHY)
    assert t["status"] == "todo" and t["due_date"] == "2026-11-20" and t["seat_told_at"] is None, "the task stays"
    assert yours(db) == ([], []), "nobody is told it is theirs"
    [mail] = back(db)
    assert mail["to"] == "minnie@lovecity.org" and mail["subject"] == "Love City Church: a task was taken back"
    assert "Hi Minnie" in mail["html"] and "You handed Jessica McCloud a task: Review the safety policy." in mail["html"]
    assert WHY in mail["html"] and "for the owner to hand out" in mail["html"]
    [push] = db.pushes
    assert push["to"] == login(db, "minnie") and push["title"] == "A task was taken back"
    assert push["body"] == "Review the safety policy (Jessica McCloud)" and push["nav"] == "operate:tasks"


def test_a_second_sweep_changes_nothing_more(db):
    tid = hand(db, 1, "Review the safety policy", by="minnie", to="jessica")
    cot.sweep_tick(NOW)
    after, mails, pushes = dict(task(db, tid)), len(db.sent), len(db.pushes)
    again = cot.sweep_tick(NOW)
    assert again["office_taken_back"] == 0 and again["office_told"] == 0
    assert task(db, tid) == after and len(db.sent) == mails and len(db.pushes) == pushes


def test_to_someone_who_isnt_a_pastor_it_is_told_as_before(db):
    tid = hand(db, 1, "Book the fellowship hall", by="minnie", to="naiya")
    stats = cot.sweep_tick(NOW)
    assert stats["office_told"] == 1 and stats["office_taken_back"] == 0
    assert task(db, tid)["assigned_to"] == login(db, "naiya") and task(db, tid)["title"] == "Book the fellowship hall"
    assert yours(db) == (["naiya@lovecity.org"], [login(db, "naiya")]) and not back(db)


def test_the_owners_hand_off_to_a_pastor_is_told(db):
    tid = hand(db, 1, "Review the safety policy", by="owner", to="jessica")
    stats = cot.sweep_tick(NOW)
    assert stats["office_told"] == 1 and stats["office_taken_back"] == 0
    assert task(db, tid)["assigned_to"] == login(db, "jessica") and task(db, tid)["seat_told_at"]
    assert yours(db) == (["jessica@lovecity.org"], [login(db, "jessica")])


def test_a_pastors_task_to_herself_and_one_no_login_handed_are_left_alone(db):
    own = hand(db, 1, "Call the Owens family", by="jessica", to="jessica")
    server = hand(db, 2, "Read the weekly report", by=None, to="jessica")
    stats = cot.sweep_tick(NOW)
    assert stats["office_taken_back"] == 0 and stats["office_self"] == 1 and stats["office_told"] == 1
    assert task(db, own)["assigned_to"] == task(db, server)["assigned_to"] == login(db, "jessica")
    assert task(db, own)["seat_told_at"] and task(db, server)["seat_told_at"]


def test_an_office_seat_never_hands_the_owner_who_is_the_senior_pastor_a_task(db):
    tid = hand(db, 1, "Preach at the lodge", by="naiya", to="owner")
    assert cot.sweep_tick(NOW)["office_taken_back"] == 1
    assert task(db, tid)["assigned_to"] is None and task(db, tid)["title"] == "Preach at the lodge (Kevin McCloud)"
    assert yours(db) == ([], []) and [m["to"] for m in back(db)] == ["naiya@lovecity.org"]


def test_a_login_that_has_left_has_no_standing_and_is_not_emailed(db):
    tid = hand(db, 1, "Review the safety policy", by="laquesha", to="jessica")
    next(s for s in db.t["business_users"] if s["user_id"] == login(db, "laquesha"))["status"] = "revoked"
    assert cot.sweep_tick(NOW)["office_taken_back"] == 1
    assert task(db, tid)["assigned_to"] is None and yours(db) == ([], []) and not db.sent and not db.pushes


def test_closed_every_hand_off_is_told_as_before_and_nothing_more_is_read(db, monkeypatch):
    tid = hand(db, 1, "Review the safety policy", by="minnie", to="jessica")
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    monkeypatch.setattr(co, "Church", lambda biz: pytest.fail("closed: who is a pastor is never read"))
    stats = cot.sweep_tick(NOW)
    assert stats["office_told"] == 1 and stats["office_taken_back"] == 0
    assert task(db, tid)["assigned_to"] == login(db, "jessica") and task(db, tid)["title"] == "Review the safety policy"
    assert yours(db)[0] == ["jessica@lovecity.org"] and not back(db)


def test_who_is_a_pastor_unread_leaves_the_task_as_it_is_for_the_next_sweep(db, monkeypatch):
    wrong = hand(db, 1, "Review the safety policy", by="minnie", to="jessica")
    fine = hand(db, 2, "Book the fellowship hall", by="minnie", to="naiya")
    owners = hand(db, 3, "Plan the staff retreat", by="owner", to="jessica")
    before = {tid: dict(task(db, tid)) for tid in (wrong, fine)}
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/church_leader_roles") else real(path, **kw))
    stats = cot.sweep_tick(NOW)
    assert stats["office_rule_unread"] == 2 and stats["office_taken_back"] == 0
    assert all(task(db, tid) == row for tid, row in before.items()), "never un-handed on a guess, never claimed"
    assert stats["office_told"] == 1 and task(db, owners)["seat_told_at"], "the owner's needs no asking"
    assert yours(db) == (["jessica@lovecity.org"], [login(db, "jessica")]) and not back(db), "never told on a guess"
    monkeypatch.setattr(sb_clients, "sb_get_as_service", real)
    stats = cot.sweep_tick(NOW)
    assert stats["office_taken_back"] == 1 and stats["office_told"] == 1 and stats["office_rule_unread"] == 0
    assert task(db, wrong)["assigned_to"] is None and task(db, fine)["seat_told_at"]
    assert yours(db)[0] == ["jessica@lovecity.org", "naiya@lovecity.org"]


def test_several_taken_back_from_one_login_are_one_email_and_one_push(db):
    hand(db, 1, "Review the safety policy", by="minnie", to="jessica")
    hand(db, 2, "Preach at the lodge", by="minnie", to="owner")
    hand(db, 3, "Book the fellowship hall", by="minnie", to="naiya")
    stats = cot.sweep_tick(NOW)
    assert stats["office_taken_back"] == 2 and stats["office_told"] == 1
    [mail] = back(db)
    assert mail["subject"] == "Love City Church: 2 tasks were taken back"
    assert "“Review the safety policy” (Jessica McCloud)" in mail["html"]
    assert "“Preach at the lodge” (Kevin McCloud)" in mail["html"] and "Book the fellowship hall" not in mail["html"]
    assert [p["title"] for p in db.pushes if p["tag"].startswith("task-back-")] == ["Tasks were taken back"]


def test_the_email_failing_still_leaves_it_taken_back_with_why_on_the_task(db):
    tid = hand(db, 1, "Review the safety policy", by="minnie", to="jessica")
    db.fail_to.add("minnie@lovecity.org")
    assert cot.sweep_tick(NOW)["office_taken_back"] == 1
    assert task(db, tid)["assigned_to"] is None and WHY in task(db, tid)["description"]
    assert not db.sent and not db.pushes


# ─── One of the church's people (church_leader_tasks) ─────────────────

def test_an_office_seats_hand_off_to_an_elder_is_taken_back_and_never_told(db):
    tid = hand(db, 1, "Plan the elders' retreat", by="minnie", to_person="marcus")
    stats = clt.sweep_tick(NOW)
    t = task(db, tid)
    assert stats["taken_back"] == 1 and stats["told"] == 0 and stats["rule_unread"] == 0
    assert t["assigned_contact_id"] is None and t["assigned_to"] is None and t["leader_told_at"] is None
    assert t["title"] == "Plan the elders' retreat (Marcus Taylor)"
    assert t["description"] == "This was handed to Marcus Taylor, then taken back. " + WHY
    assert yours(db) == ([], [])
    [mail] = back(db)
    assert mail["to"] == "minnie@lovecity.org" and "You handed Marcus Taylor a task" in mail["html"]
    again = clt.sweep_tick(NOW)
    assert again["taken_back"] == 0 and again["told"] == 0 and task(db, tid) == t and len(back(db)) == 1


def test_a_leader_who_isnt_a_pastor_is_told_as_before(db):
    tid = hand(db, 1, "Order the welcome gifts", by="minnie", to_person="tasha")
    stats = clt.sweep_tick(NOW)
    assert stats["told"] == 1 and stats["taken_back"] == 0
    assert task(db, tid)["assigned_contact_id"] == person(db, "tasha") and task(db, tid)["leader_told_at"]
    assert yours(db)[0] == ["tasha@lovecity.org"] and not back(db)


def test_the_owner_and_the_ministry_chain_still_hand_an_elder_work(db):
    owners = hand(db, 1, "Plan the elders' retreat", by="owner", to_person="marcus")
    chain = hand(db, 2, "Visit the Owens family", by="jessica", to_person="marcus")     # Marcus answers to her on the map
    other = hand(db, 3, "Lead the prayer night", by="jessica", to_person="tanya")       # Tanya answers to no one under her
    stats = clt.sweep_tick(NOW)
    assert stats["told"] == 2 and stats["taken_back"] == 1
    assert task(db, owners)["leader_told_at"] and task(db, chain)["leader_told_at"]
    assert task(db, other)["assigned_contact_id"] is None
    assert task(db, other)["title"] == "Lead the prayer night (Tanya Brooks)"
    assert [m["to"] for m in back(db)] == ["jessica@lovecity.org"]


def test_a_pastors_own_record_is_hers_to_hand_herself(db):
    tid = hand(db, 1, "Read the weekly report", by="jessica", to_person="jessica")
    stats = clt.sweep_tick(NOW)
    assert stats["taken_back"] == 0 and task(db, tid)["assigned_contact_id"] == person(db, "jessica")


def test_closed_an_elders_hand_off_is_told_as_before(db, monkeypatch):
    tid = hand(db, 1, "Plan the elders' retreat", by="minnie", to_person="marcus")
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    monkeypatch.setattr(co, "Church", lambda biz: pytest.fail("closed: who is a pastor is never read"))
    stats = clt.sweep_tick(NOW)
    assert stats["told"] == 1 and stats["taken_back"] == 0
    assert task(db, tid)["assigned_contact_id"] == person(db, "marcus") and yours(db)[0] == ["marcus@lovecity.org"]


def test_an_elders_hand_off_unread_waits_for_the_next_sweep(db, monkeypatch):
    tid = hand(db, 1, "Plan the elders' retreat", by="minnie", to_person="marcus")
    before = dict(task(db, tid))
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/church_leader_roles") else real(path, **kw))
    stats = clt.sweep_tick(NOW)
    assert stats["rule_unread"] == 1 and stats["taken_back"] == 0 and stats["told"] == 0
    assert task(db, tid) == before and not db.sent and not db.pushes, "never un-handed and never told on a guess"
    monkeypatch.setattr(sb_clients, "sb_get_as_service", real)
    stats = clt.sweep_tick(NOW)
    assert stats["taken_back"] == 1 and stats["rule_unread"] == 0 and task(db, tid)["assigned_contact_id"] is None


def test_handed_out_again_the_name_and_the_note_are_on_it_once(db):
    tid = hand(db, 1, "Plan the elders' retreat", by="minnie", to_person="marcus")
    clt.sweep_tick(NOW)
    task(db, tid).update(assigned_contact_id=person(db, "marcus"), handed_by=login(db, "minnie"))
    assert clt.sweep_tick(NOW)["taken_back"] == 1
    t = task(db, tid)
    assert t["assigned_contact_id"] is None and t["title"] == "Plan the elders' retreat (Marcus Taylor)"
    assert t["description"].count("taken back") == 1


# ─── The rule's own pieces ────────────────────────────────────────────

def test_only_a_church_is_ever_asked(db, monkeypatch):
    monkeypatch.setattr(co, "Church", lambda biz: pytest.fail("not a church: nothing is read"))
    rows = [{"id": "t1", "assigned_to": login(db, "jessica"), "handed_by": login(db, "minnie"), "title": "x"}]
    stats: dict = {}
    assert clt.take_back({**c3.church(db, LOVE_CITY), "type": "salon"}, rows, "assigned_to", "seat_told_at",
                         stats, "office_") is rows
    assert stats == {}


def test_what_is_asked_about_and_what_never_is(db):
    biz, minnie, jess = c3.church(db, LOVE_CITY), login(db, "minnie"), login(db, "jessica")
    ask = lambda by, to: co.asks_rule(biz, {"handed_by": by, "assigned_to": to}, "assigned_to")  # noqa: E731
    assert ask(minnie, jess)
    assert not ask(biz["owner_id"], jess), "the owner always may"
    assert not ask(jess, jess), "a task to yourself"
    assert not ask(None, jess), "the server's own, with no login behind it"
    assert not ask(minnie, None), "handed to no one"


def test_the_words_are_the_boards_and_did_not_change(db):
    assert co.WHO_HANDS == WHY and cb.WHO_HANDS is co.WHO_HANDS and cb.NOT_HANDED is co.NOT_HANDED
    assert co.NOT_HANDED == "The board named {name} for this. It isn't handed to them yet. " + WHY
    assert co.TAKEN_BACK.endswith(WHY)
