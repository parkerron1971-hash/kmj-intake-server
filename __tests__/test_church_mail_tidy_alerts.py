"""Church mail: archive, delete, Trash, and new-mail alerts
(church_mail_room.py, church_mail_alerts.py).

Kevin, 2026-11-14, on the mock (artifact 1fGHqCVMe9fxwceAbjbaJZ): "I love the
design. lets build it".

Pins:
  * new mail alerts whoever the box reaches now, on their phone, by their own
    choice (all / mine / off, phone on or off); the church's quiet hours hold
    it until they end, then several from one box go as one; never twice
  * nobody hears about mail they already opened; prayer@ never alerts
  * archive is for me alone: out of my list, in my Archive, and back
  * delete is for the whole box: its Trash with who deleted it; anyone on the
    box puts it back; Empty Trash deletes for good; nobody touches mail they
    don't read; Trash older than 30 days goes by itself
  * the bell lists my new mail of the week, and an answer on a shared box
    clears it for everyone"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_mail_alerts as cma  # noqa: E402
import church_mail_room as room  # noqa: E402
import push_notifications  # noqa: E402
from test_church_mail import BIZ, JESSICA, MANAGER, TIA, db, resend  # noqa: E402,F401
from test_church_mail_room import _all_in, _arrive, _row_for, _tray, call, mail  # noqa: E402,F401


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(push_notifications, "send_to_user", lambda uid, **kw: sent.append((uid, kw)) or 1)
    monkeypatch.setattr(cma, "quiet_now", lambda biz: False)
    return sent


def _ids(view):
    return [i["id"] for i in view["items"]]


# ─── Alerts ──────────────────────────────────────────────────────────

def test_new_mail_alerts_whoever_the_box_reaches(mail, resend, pushes):
    _arrive(resend, "a1", "jessica@lovecityc.com", subject="Keys")
    assert [(u, k["title"]) for u, k in pushes] == [(JESSICA, "Sam Sender")], "their own box: just who it's from"
    assert pushes[0][1]["nav"] == "operate:email" and pushes[0][1]["data"]["mail"] == _row_for(mail, "a1")["id"]
    assert pushes[0][1]["data"]["biz"] == BIZ and "business_id" not in pushes[0][1],         "every device the person turned on, whatever business it signed up from"
    assert pushes[0][1]["body"].split("\n")[0] == "Keys", "the subject, then the first line on its own line"
    assert pushes[0][1]["tag"] == f"church-mail-{_row_for(mail, 'a1')['id']}", "one email, one alert"
    pushes.clear()
    _arrive(resend, "a2", "office@lovecityc.com", subject="The hall")
    assert sorted(u for u, _ in pushes) == sorted([JESSICA, TIA])
    assert {k["title"] for _, k in pushes} == {"Sam Sender · Office"}
    row = _row_for(mail, "a2")
    assert row["alert_at"] and row["alerted_at"]


def test_each_person_chooses_how_much(mail, resend, pushes):
    call(room.put_alerts, mail, TIA, room.AlertsIn(mode="mine"))
    call(room.put_alerts, mail, JESSICA, room.AlertsIn(mode="all", push=False))
    _arrive(resend, "b1", "office@lovecityc.com")
    assert pushes == [], "Tia: only her own box; Jessica: phone alerts off"
    assert call(room.get_room, mail, TIA)["me"]["alerts"]["mode"] == "mine"
    call(room.put_alerts, mail, JESSICA, room.AlertsIn(mode="off"))
    _arrive(resend, "b2", "jessica@lovecityc.com")
    assert pushes == []
    call(room.put_alerts, mail, JESSICA, room.AlertsIn(mode="mine"))
    _arrive(resend, "b3", "jessica@lovecityc.com")
    assert [u for u, _ in pushes] == [JESSICA], "her own box, with mine"


def test_quiet_hours_hold_alerts_until_they_end_then_one_per_box(mail, resend, pushes, monkeypatch):
    monkeypatch.setattr(cma, "quiet_now", lambda biz: True)
    _arrive(resend, "q1", "office@lovecityc.com", subject="One")
    _arrive(resend, "q2", "office@lovecityc.com", subject="Two")
    assert pushes == []
    assert all(_row_for(mail, e)["alert_at"] and not _row_for(mail, e).get("alerted_at") for e in ("q1", "q2"))
    cma.sweep()
    assert pushes == [], "still quiet"
    monkeypatch.setattr(cma, "quiet_now", lambda biz: False)
    cma.sweep()
    assert sorted((u, k["title"]) for u, k in pushes) == [(JESSICA, "Office · 2 new emails"), (TIA, "Office · 2 new emails")]
    assert sorted(pushes[0][1]["body"].split("\n")) == ["Sam Sender: One", "Sam Sender: Two"]
    assert pushes[0][1]["tag"].startswith("church-mail-box:")
    cma.sweep()
    assert len(pushes) == 2, "never twice"


def test_nobody_hears_of_mail_they_opened_and_prayer_never_alerts(mail, resend, pushes, monkeypatch):
    _arrive(resend, "p1", "prayer@lovecityc.com", subject="Please pray")
    assert pushes == []
    monkeypatch.setattr(cma, "quiet_now", lambda biz: True)
    _arrive(resend, "r1", "office@lovecityc.com", subject="Seen it")
    _all_in(mail)
    call(room.get_message, mail, JESSICA, id=_row_for(mail, "r1")["id"])
    monkeypatch.setattr(cma, "quiet_now", lambda biz: False)
    cma.sweep()
    assert [u for u, _ in pushes] == [TIA], "Jessica opened it before the alert went"


def test_a_day_late_is_no_alert(mail, resend, pushes, monkeypatch):
    monkeypatch.setattr(cma, "quiet_now", lambda biz: True)
    _arrive(resend, "s1", "office@lovecityc.com")
    _row_for(mail, "s1")["alert_at"] = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    monkeypatch.setattr(cma, "quiet_now", lambda biz: False)
    assert cma.sweep()["stale"] == 1
    assert pushes == [] and _row_for(mail, "s1")["alerted_at"]


# ─── Archive, delete, Trash ──────────────────────────────────────────

def test_archive_is_for_me_alone_and_comes_back(mail, resend, pushes):
    _arrive(resend, "c1", "office@lovecityc.com", subject="Chairs")
    _all_in(mail)
    rid = _row_for(mail, "c1")["id"]
    office = _tray(call(room.get_room, mail, TIA), "Office")["id"]
    assert call(room.post_archive, mail, TIA, room.ArchiveIn(ids=[rid]))["changed"] == 1
    assert _ids(call(room.get_list, mail, TIA, tray=office)) == []
    assert _ids(call(room.get_list, mail, JESSICA, tray=office)) == [rid], "Jessica still sees it"
    arch = call(room.get_list, mail, TIA, tray="archive")["items"]
    assert [i["id"] for i in arch] == [rid] and arch[0]["archived"] is True
    tia = call(room.get_room, mail, TIA)
    assert tia["archive"] == 1 and _tray(tia, "Office")["total"] == 0
    call(room.post_archive, mail, TIA, room.ArchiveIn(ids=[rid], archived=False))
    assert _ids(call(room.get_list, mail, TIA, tray=office)) == [rid]


def test_delete_is_for_the_whole_box_and_anyone_on_it_can_put_it_back(mail, resend, pushes):
    _arrive(resend, "d1", "office@lovecityc.com", subject="Old flyer")
    _all_in(mail)
    rid = _row_for(mail, "d1")["id"]
    office = _tray(call(room.get_room, mail, TIA), "Office")["id"]
    assert call(room.post_delete_mail, mail, JESSICA, room.IdsIn(ids=[rid]))["changed"] == 1
    assert _ids(call(room.get_list, mail, TIA, tray=office)) == []
    assert _ids(call(room.get_list, mail, JESSICA, tray=office)) == []
    trash = call(room.get_list, mail, TIA, tray="trash")["items"]
    assert [i["id"] for i in trash] == [rid] and trash[0]["deleted"]["name"] == "Jessica McCloud"
    assert call(room.get_room, mail, TIA)["trash"] == 1
    assert call(room.post_restore, mail, TIA, room.IdsIn(ids=[rid]))["changed"] == 1
    assert _ids(call(room.get_list, mail, JESSICA, tray=office)) == [rid]
    call(room.post_delete_mail, mail, TIA, room.IdsIn(ids=[rid]))
    assert call(room.post_empty_trash, mail, JESSICA)["deleted"] == 1
    assert not [r for r in mail.t["church_mail"] if r["id"] == rid], "gone for good"


def test_nobody_archives_or_deletes_what_they_dont_read(mail, resend, pushes):
    _arrive(resend, "n1", "jessica@lovecityc.com", subject="Mine")
    _all_in(mail)
    rid = _row_for(mail, "n1")["id"]
    assert call(room.post_delete_mail, mail, TIA, room.IdsIn(ids=[rid]))["changed"] == 0
    assert call(room.post_archive, mail, MANAGER, room.ArchiveIn(ids=[rid]))["changed"] == 0
    call(room.post_delete_mail, mail, JESSICA, room.IdsIn(ids=[rid]))
    assert call(room.post_empty_trash, mail, TIA)["deleted"] == 0, "Tia can't empty Jessica's Trash"
    assert call(room.post_restore, mail, TIA, room.IdsIn(ids=[rid]))["changed"] == 0
    assert [r for r in mail.t["church_mail"] if r["id"] == rid]


def test_trash_goes_by_itself_after_30_days(mail, resend, pushes):
    _arrive(resend, "t1", "office@lovecityc.com")
    _arrive(resend, "t2", "office@lovecityc.com")
    now = datetime.now(timezone.utc)
    _row_for(mail, "t1")["deleted_at"] = (now - timedelta(days=31)).isoformat()
    _row_for(mail, "t2")["deleted_at"] = (now - timedelta(days=5)).isoformat()
    assert cma.trash_sweep()["ok"]
    left = {r["email_id"] for r in mail.t["church_mail"]}
    assert "t1" not in left and "t2" in left


# ─── The bell ────────────────────────────────────────────────────────

def test_the_bell_lists_my_new_mail_and_an_answer_clears_it(mail, resend, pushes):
    _arrive(resend, "e1", "office@lovecityc.com", subject="The hall")
    _arrive(resend, "e2", "jessica@lovecityc.com", subject="Keys")
    _all_in(mail)
    bell = call(room.get_alerts, mail, JESSICA)
    assert sorted(i["subject"] for i in bell["items"]) == ["Keys", "The hall"] and bell["unread"] == 2
    office = _tray(call(room.get_room, mail, TIA), "Office")["id"]
    orig = _row_for(mail, "e1")
    call(room.post_send, mail, TIA, room.SendIn(sender=office, to="sam@sender.example", subject="Re: The hall",
                                               body="Yes.", reply_to_id=orig["id"], idem="bell1"))
    bell = call(room.get_alerts, mail, JESSICA)
    hall = next(i for i in bell["items"] if i["subject"] == "The hall")
    assert hall["answered"]["name"] == "Tia Brown" and hall["unread"] is False and bell["unread"] == 1
    call(room.put_alerts, mail, JESSICA, room.AlertsIn(mode="mine"))
    assert [i["subject"] for i in call(room.get_alerts, mail, JESSICA)["items"]] == ["Keys"]
    call(room.put_alerts, mail, TIA, room.AlertsIn(mode="all", bell=False))
    assert call(room.get_alerts, mail, TIA)["items"] == []


def test_the_alert_reads_like_a_mail_app(mail, resend, pushes):
    reply = ("Yes, I'll be there at 9:30 with the welcome table signs and the sign-in sheets for the new families, "
             "plus the extra name tags.\n\nOn Thu, Nov 13, 2026 at 4:00 PM Office <office@lovecityc.com> wrote:\n> Can you come early?")
    _arrive(resend, "w1", "jessica@lovecityc.com", subject="Re: Sunday", text=reply)
    body = pushes[0][1]["body"]
    subject, preview = body.split("\n")
    assert subject == "Re: Sunday"
    assert preview.endswith("…") and len(preview) <= 112 and "wrote:" not in preview, "the quoted email left out, cut at a word"
