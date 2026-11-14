"""Church mail in the Email room (church_mail_room.py).

Kevin, 2026-11-13, on the mock (artifact HuNVNSzCydvvzJ4vE5iu88): "this is
good build it".

Pins:
  * a login reads only the boxes that reach it now: its own, the office box
    it shares, a role it holds; never someone else's own box, never prayer@
    (a count only), never a forward; the pastor reads mail to addresses with
    no box only when no office box catches it
  * opening a message marks it read for that person alone (a shared box)
  * a send goes from the box, its answers come back to the box, it threads
    on the message it answers, it marks that message answered for everyone
    on the box, and it sits in the box's Sent
  * nobody sends from an address they don't read; the church's own address
    is the pastor's, the Admins' and the church email duty's
  * nothing is sent before mail to the domain comes here
  * copies off: mail is kept for the room and not copied to their own email
  * held mail is the pastor's and the duty's: let through (copied to whoever
    the box reaches now) or deleted; a virus can only be deleted
  * a reply by email to a copy shows as answered, and in the box's Sent

The tables are the church mail tests' in-memory PostgREST."""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_mail  # noqa: E402
import church_mail_room as room  # noqa: E402
import email_sender  # noqa: E402
import sb_clients  # noqa: E402
from test_church_mail import (  # noqa: E402,F401
    BIZ, DOMAIN, JESSICA, MANAGER, OWNER, TIA, _box, _inbound, _rows, db, resend,
)


@pytest.fixture
def mail(db, resend, monkeypatch):
    """Jessica's own box, an office box she shares with Tia (it catches
    every address with no box), and prayer@."""
    db.t["church_mailboxes"] += [_box("jessica", "person", user_id=JESSICA),
                                 _box("office", "office", share_with=[JESSICA, TIA], catch_all=True),
                                 _box("prayer", "prayer"), _box("giving", "forward", forward_to="treasurer@else.example")]
    db.t["church_mail_people"] = []
    db.t["events"] = []
    monkeypatch.setattr(sb_clients, "sb_count_as_service", lambda path: len(db.get(path)))
    orig_post = db.post

    def post(path, body, prefer=None, **kw):
        if path.startswith("/church_mail_people"):
            have = [r for r in db.t["church_mail_people"]
                    if r["business_id"] == body["business_id"] and r["user_id"] == body["user_id"]]
            if have:
                have[0].update(body)
                return [dict(have[0])]
        return orig_post(path, body, prefer, **kw)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    for r in db.t["church_mail"]:
        r.setdefault("direction", "in")
    return db


def _biz(db, uid):
    b = dict(db.t["businesses"][0])
    from business_users_router import role_of
    b["_caller_role"] = role_of(BIZ, uid)
    return b


def _s(uid):
    return SimpleNamespace(user=SimpleNamespace(id=uid))


def call(fn, db, uid, *args, **kw):
    out = fn(*args, business_id=BIZ, biz=_biz(db, uid), session=_s(uid), **kw)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


def _arrive(resend, email_id, to, **kw):
    _inbound(resend.add(email_id, to=[to], **kw))


def _row_for(db, email_id):
    r = next(r for r in db.t["church_mail"] if r["email_id"] == email_id)
    r.setdefault("direction", "in")
    r.setdefault("read_by", [])
    return r


def _all_in(db):
    for r in db.t["church_mail"]:
        r.setdefault("direction", "in")
        r.setdefault("read_by", [])


def _tray(view, label):
    return next(t for t in view["trays"] if t["label"] == label)


# ─── Who reads what ──────────────────────────────────────────────────

def test_a_login_reads_its_own_box_and_the_office_it_shares_never_another_persons(mail, resend):
    _arrive(resend, "m1", "jessica@lovecityc.com", subject="Your spot this Sunday")
    _arrive(resend, "m2", "office@lovecityc.com", subject="The hall on the 21st")
    _arrive(resend, "m3", "typo@lovecityc.com", subject="To nobody")
    _all_in(mail)
    jess = call(room.get_room, mail, JESSICA)
    assert [t["label"] for t in jess["trays"]] == ["Yours", "Office"]
    assert _tray(jess, "Yours")["unread"] == 1 and _tray(jess, "Office")["total"] == 2, \
        "mail to an address with no box sits in the office box that catches it"
    assert jess["me"]["address"] == "jessica@lovecityc.com" and jess["on"] is True

    tia = call(room.get_room, mail, TIA)
    assert [t["label"] for t in tia["trays"]] == ["Office"]
    with pytest.raises(HTTPException) as e:
        call(room.get_list, mail, TIA, tray=_tray(jess, "Yours")["id"])
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        call(room.get_message, mail, TIA, id=_row_for(mail, "m1")["id"])
    assert e.value.status_code == 404

    manny = call(room.get_room, mail, MANAGER)
    assert manny["trays"] == [] and manny["held"] is None and manny["prayer"] is None


def test_prayer_is_a_count_and_never_a_tray(mail, resend):
    _arrive(resend, "m1", "prayer@lovecityc.com", text="Please pray for my mother.")
    _all_in(mail)
    pastor = call(room.get_room, mail, OWNER)
    assert pastor["prayer"] == {"address": "prayer@lovecityc.com", "week": 1}
    assert not any(t["kind"] == "prayer" for t in pastor["trays"])
    with pytest.raises(HTTPException):
        call(room.get_message, mail, OWNER, id=_row_for(mail, "m1")["id"])


def test_the_pastor_reads_other_addresses_only_when_no_office_box_catches_them(db, resend, monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_count_as_service", lambda path: len(db.get(path)))
    db.t["church_mail_people"] = []
    _arrive(resend, "m1", "anyone@lovecityc.com", subject="Hello")
    _all_in(db)
    pastor = call(room.get_room, db, OWNER)
    assert [(t["id"], t["unread"]) for t in pastor["trays"]] == [("other", 1)]
    items = call(room.get_list, db, OWNER, tray="other")["items"]
    assert [i["subject"] for i in items] == ["Hello"]
    assert call(room.get_room, db, TIA)["trays"] == []


def test_opening_a_message_marks_it_read_for_that_person_only(mail, resend):
    _arrive(resend, "m1", "office@lovecityc.com", subject="The hall")
    _all_in(mail)
    mid = _row_for(mail, "m1")["id"]
    got = call(room.get_message, mail, TIA, id=mid)
    assert got["body"] == "See you" and got["reply_from"].startswith("box:")
    assert _tray(call(room.get_room, mail, TIA), "Office")["unread"] == 0
    assert _tray(call(room.get_room, mail, JESSICA), "Office")["unread"] == 1
    call(room.post_read, mail, TIA, room.ReadIn(ids=[mid], read=False))
    assert _tray(call(room.get_room, mail, TIA), "Office")["unread"] == 1


# ─── Sending ─────────────────────────────────────────────────────────

def test_an_answer_goes_from_the_box_threads_and_marks_the_message_answered(mail, resend):
    _arrive(resend, "m1", "office@lovecityc.com", subject="The hall on the 21st")
    _all_in(mail)
    orig = _row_for(mail, "m1")
    office = _tray(call(room.get_room, mail, TIA), "Office")["id"]
    out = call(room.post_send, mail, TIA, room.SendIn(sender=office, to="sam@sender.example", to_name="Sam Sender",
                                                     subject="Re: The hall on the 21st", body="Yes, it's yours.",
                                                     reply_to_id=orig["id"], idem="abc"))
    sent = resend.sent[-1]
    assert out["from"] == "office@lovecityc.com"
    assert sent["from"] == "Love City Church <office@lovecityc.com>" and sent["reply_to"] == ["office@lovecityc.com"]
    assert sent["to"] == ["Sam Sender <sam@sender.example>"]
    assert sent["headers"] == {"In-Reply-To": "<m1@mail.example>", "References": "<m1@mail.example>"}
    assert sent["text"].startswith("Yes, it's yours.\n\nTia Brown\nLove City Church\noffice@lovecityc.com")
    assert "List-Unsubscribe" not in sent.get("headers", {}), "a person's own mail, not a mailing"
    assert orig["answered_name"] == "Tia Brown", "Jessica sees Tia answered: nobody answers twice"
    kept = next(r for r in mail.t["church_mail"] if r.get("direction") == "out")
    assert kept["sent_by"] == TIA and kept["outcome"] == "sent" and kept["mailbox_id"] == office[4:]
    # Office's Sent is everyone's on the box; it isn't Manny's.
    assert [i["to_address"] for i in call(room.get_list, mail, JESSICA, tray="sent")["items"]] == ["sam@sender.example"]
    assert call(room.get_list, mail, MANAGER, tray="sent")["items"] == []


def test_nobody_sends_from_an_address_they_dont_read(mail, resend):
    yours = _tray(call(room.get_room, mail, JESSICA), "Yours")["id"]
    for who, sender in ((TIA, yours), (TIA, "church"), (MANAGER, "church")):
        with pytest.raises(HTTPException) as e:
            call(room.post_send, mail, who, room.SendIn(sender=sender, to="sam@sender.example", subject="Hi",
                                                       body="Hello"))
        assert e.value.status_code == 403
    assert not resend.sent
    pastor = call(room.get_room, mail, OWNER)
    assert any(s["id"] == "church" and s["address"] == "hello@lovecityc.com" for s in pastor["senders"])


def test_nothing_is_sent_before_mail_to_the_domain_comes_here(mail, resend, monkeypatch):
    monkeypatch.setattr(church_mail, "receiving_live", lambda d: False)
    church_mail._LIVE_CACHE.clear()
    yours = "box:" + next(b["id"] for b in mail.t["church_mailboxes"] if b["local"] == "jessica")
    with pytest.raises(HTTPException) as e:
        call(room.post_send, mail, JESSICA, room.SendIn(sender=yours, to="sam@sender.example", subject="Hi",
                                                       body="Hello"))
    assert e.value.status_code == 400 and "isn't on yet" in e.value.detail and not resend.sent


def test_a_send_to_someone_who_bounced_is_refused(mail, resend, monkeypatch):
    async def _bounced(email):
        return {"reason": "bounced"}
    monkeypatch.setattr(email_sender, "is_suppressed", _bounced)
    yours = _tray(call(room.get_room, mail, JESSICA), "Yours")["id"]
    with pytest.raises(HTTPException) as e:
        call(room.post_send, mail, JESSICA, room.SendIn(sender=yours, to="sam@sender.example", subject="Hi",
                                                       body="Hello"))
    assert e.value.status_code == 400 and not resend.sent


# ─── Copies to their own email ───────────────────────────────────────

def test_copies_off_keeps_mail_for_the_room_and_sends_no_copy(mail, resend):
    call(room.put_copies, mail, JESSICA, room.CopiesIn(on=False))
    _arrive(resend, "m1", "jessica@lovecityc.com", subject="Room only")
    _arrive(resend, "m2", "office@lovecityc.com", subject="Shared")
    _all_in(mail)
    assert [s["to"][0] for s in resend.sent] == ["Tia Brown <tia@example.com>"], "Tia still gets the office copy"
    assert _row_for(mail, "m1")["outcome"] == "stored"
    assert _row_for(mail, "m1")["delivered"][0]["why"] == "reads it in the Email room"
    jess = call(room.get_room, mail, JESSICA)
    assert jess["me"]["copies"] is False and _tray(jess, "Yours")["unread"] == 1
    call(room.put_copies, mail, JESSICA, room.CopiesIn(on=True))
    assert call(room.get_room, mail, JESSICA)["me"]["copies"] is True


# ─── Held mail ───────────────────────────────────────────────────────

def test_held_mail_is_the_pastors_and_the_dutys_and_can_be_let_through(mail, resend):
    _arrive(resend, "m1", "jessica@lovecityc.com", subject="Gift cards", auth=("fail", "fail", "none"))
    _all_in(mail)
    row = _row_for(mail, "m1")
    assert row["outcome"] == "held" and not resend.sent
    with pytest.raises(HTTPException) as e:
        call(room.get_list, mail, TIA, tray="held")
    assert e.value.status_code == 403
    assert call(room.get_room, mail, OWNER)["held"] == 1
    mail.duty.add(MANAGER)
    items = call(room.get_list, mail, MANAGER, tray="held")["items"]
    assert items[0]["can_release"] and "couldn't be checked" in items[0]["why"]
    got = call(room.get_message, mail, MANAGER, id=row["id"])
    assert got["release_to"] == "Jessica McCloud"
    call(room.post_release, mail, MANAGER, room.HeldIn(id=row["id"]))
    assert resend.sent[-1]["to"] == ["Jessica McCloud <jess@example.com>"]
    assert row["outcome"] == "copied" and row["why"].startswith("let through by Manny Cole")
    assert [i["subject"] for i in call(room.get_list, mail, JESSICA, tray=_tray(
        call(room.get_room, mail, JESSICA), "Yours")["id"])["items"]] == ["Gift cards"]


def test_a_virus_can_only_be_deleted(mail, resend):
    _arrive(resend, "m1", "office@lovecityc.com", headers={"X-SES-Virus-Verdict": "FAIL"})
    _all_in(mail)
    row = _row_for(mail, "m1")
    with pytest.raises(HTTPException) as e:
        call(room.post_release, mail, OWNER, room.HeldIn(id=row["id"]))
    assert e.value.status_code == 400 and not resend.sent
    call(room.post_delete, mail, OWNER, room.HeldIn(id=row["id"]))
    assert not any(r["email_id"] == "m1" for r in mail.t["church_mail"])


# ─── A reply by email ────────────────────────────────────────────────

def test_a_reply_by_email_shows_as_answered_and_in_the_boxs_sent(mail, resend, monkeypatch):
    monkeypatch.setenv("CHURCH_MAIL_SECRET", "test-secret")
    _arrive(resend, "m1", "jessica@lovecityc.com", subject="Thursday")
    relay = resend.sent[0]["reply_to"][0]
    _arrive(resend, "m2", relay, frm="jess@example.com", name="Jessica McCloud", subject="Re: Thursday",
            text="See you there!", html="")
    _all_in(mail)
    assert _row_for(mail, "m1")["answered_name"] == "Jessica McCloud"
    sent = call(room.get_list, mail, JESSICA, tray="sent")["items"]
    assert [(i["from_email"], i["to_address"]) for i in sent] == [("jessica@lovecityc.com", "sam@sender.example")]
    yours = _tray(call(room.get_room, mail, JESSICA), "Yours")
    assert yours["total"] == 1, "the relay itself never shows as mail in"


# ─── Addresses ───────────────────────────────────────────────────────

def test_addresses_shows_who_has_none_and_gives_them(mail, resend):
    with pytest.raises(HTTPException):
        call(room.get_addresses, mail, TIA)
    view = call(room.get_addresses, mail, OWNER)
    tia = next(t for t in view["team"] if t["user_id"] == TIA)
    assert tia["address"] is None and tia["suggest"] == "tia"
    assert {b["address"] for b in view["shared"]} == {"office@lovecityc.com", "prayer@lovecityc.com",
                                                     "giving@lovecityc.com"}
    got = call(room.post_give, mail, OWNER, room.GiveIn(items=[room.GiveItem(to=tia["to"], address="tia")]))
    assert got["results"][0]["ok"] and got["results"][0]["address"] == "tia@lovecityc.com"
    assert "Yours" in [t["label"] for t in call(room.get_room, mail, TIA)["trays"]]


# ─── Files, and older mail (Kevin, 2026-11-13: "build these") ─────────

def test_a_send_carries_its_files_and_sent_keeps_their_names(mail, resend):
    import base64
    yours = _tray(call(room.get_room, mail, JESSICA), "Yours")["id"]
    pdf = base64.b64encode(b"%PDF-1.4 the order of service").decode()
    call(room.post_send, mail, JESSICA, room.SendIn(
        sender=yours, to="sam@sender.example", subject="Sunday", body="Here it is.",
        files=[room.FileIn(filename="Order of service.pdf", content_type="application/pdf",
                           content=f"data:application/pdf;base64,{pdf}")]))
    sent = resend.sent[-1]
    assert sent["attachments"] == [{"filename": "Order of service.pdf", "content": pdf,
                                    "content_type": "application/pdf"}]
    kept = next(r for r in mail.t["church_mail"] if r.get("direction") == "out")
    assert kept["attachments"] == [{"filename": "Order of service.pdf", "size": 29, "content_type": "application/pdf"}]
    assert call(room.get_list, mail, JESSICA, tray="sent")["items"][0]["attachments"] == 1


def test_program_files_and_too_much_are_refused_before_anything_goes(mail, resend, monkeypatch):
    import base64
    yours = _tray(call(room.get_room, mail, JESSICA), "Yours")["id"]
    small = base64.b64encode(b"x" * 20).decode()
    for files, word in (([room.FileIn(filename="setup.exe", content=small)], "program files"),
                        ([room.FileIn(filename="a.pdf", content="not base64!")], "didn't come through")):
        with pytest.raises(HTTPException) as e:
            call(room.post_send, mail, JESSICA, room.SendIn(sender=yours, to="sam@sender.example", subject="Hi",
                                                           body="Hello", files=files))
        assert e.value.status_code == 400 and word in e.value.detail
    monkeypatch.setattr(room, "MAX_SEND_BYTES", 30)
    with pytest.raises(HTTPException) as e:
        call(room.post_send, mail, JESSICA, room.SendIn(
            sender=yours, to="sam@sender.example", subject="Hi", body="Hello",
            files=[room.FileIn(filename="a.pdf", content=small), room.FileIn(filename="b.pdf", content=small)]))
    assert "10 MB" in e.value.detail and not resend.sent


def test_older_mail_comes_a_page_at_a_time(mail, resend, monkeypatch):
    for i, at in enumerate(("2026-11-13T10:00:00+00:00", "2026-11-13T09:00:00+00:00", "2026-11-13T08:00:00+00:00")):
        _arrive(resend, f"m{i}", "jessica@lovecityc.com", subject=f"Note {i}")
        _row_for(mail, f"m{i}")["received_at"] = at
    monkeypatch.setattr(room, "MAX_LIST", 2)
    yours = _tray(call(room.get_room, mail, JESSICA), "Yours")["id"]
    first = call(room.get_list, mail, JESSICA, tray=yours)
    assert [i["subject"] for i in first["items"]] == ["Note 0", "Note 1"] and first["more"] is True
    older = call(room.get_list, mail, JESSICA, tray=yours, before=first["items"][-1]["at"])
    assert [i["subject"] for i in older["items"]] == ["Note 2"] and older["more"] is False
    with pytest.raises(HTTPException):
        call(room.get_list, mail, JESSICA, tray=yours, before="yesterday")


# ─── Each person's own signature ─────────────────────────────────────
# Kevin, 2026-11-14: "add where the signature can be edited. just incase
# they want to change up how it looks."

def _send_hello(db, who, sender, idem):
    call(room.post_send, db, who, room.SendIn(sender=sender, to="sam@sender.example", subject="Hi",
                                             body="Hello.", idem=idem))


def test_a_person_writes_their_own_signature_and_their_sends_carry_it(mail, resend):
    yours = _tray(call(room.get_room, mail, JESSICA), "Yours")["id"]
    out = call(room.put_signature, mail, JESSICA,
               room.SignatureIn(text="  Jessica McCloud\r\nOffice Administrator\n\n\n\nLove City Church \u0007\n\n"))
    assert out["signature"] == "Jessica McCloud\nOffice Administrator\n\nLove City Church"
    assert call(room.get_room, mail, JESSICA)["me"]["signature"] == out["signature"]
    _send_hello(mail, JESSICA, yours, "sig1")
    assert resend.sent[-1]["text"] == "Hello.\n\nJessica McCloud\nOffice Administrator\n\nLove City Church"
    assert call(room.get_room, mail, TIA)["me"]["signature"] is None, "Tia keeps the standard one"


def test_an_empty_signature_is_the_standard_one_again_and_copies_stay_as_they_were(mail, resend):
    call(room.put_copies, mail, JESSICA, room.CopiesIn(on=False))
    call(room.put_signature, mail, JESSICA, room.SignatureIn(text="Jess"))
    assert call(room.put_signature, mail, JESSICA, room.SignatureIn(text="  \n  "))["signature"] is None
    view = call(room.get_room, mail, JESSICA)
    assert view["me"]["signature"] is None and view["me"]["copies"] is False
    _send_hello(mail, JESSICA, _tray(view, "Yours")["id"], "sig2")
    assert resend.sent[-1]["text"] == "Hello.\n\nJessica McCloud\nLove City Church\njessica@lovecityc.com"


def test_a_signature_is_kept_short_in_whole_lines(mail, resend):
    many = "\n".join(f"Line {i}" for i in range(12))
    assert call(room.put_signature, mail, JESSICA, room.SignatureIn(text=many))["signature"].split("\n") == \
        [f"Line {i}" for i in range(8)], "eight lines at most"
    long = "\n".join(f"Line {i} " + "x" * 200 for i in range(12))
    sig = call(room.put_signature, mail, JESSICA, room.SignatureIn(text=long))["signature"]
    lines = sig.split("\n")
    assert len(sig) <= 600 and len(lines) == 4 and all(len(x) == 120 for x in lines), "600 in all, never half a line"


def test_a_signature_that_cant_be_read_is_the_standard_one(mail, resend, monkeypatch):
    call(room.put_signature, mail, JESSICA, room.SignatureIn(text="Jess"))
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, *a, **k: {"message": "column church_mail_people.signature does not exist"}
                        if "select=signature" in path else real(path, *a, **k))
    view = call(room.get_room, mail, JESSICA)
    assert view["me"]["signature"] is None
    _send_hello(mail, JESSICA, _tray(view, "Yours")["id"], "sig3")
    assert resend.sent[-1]["text"].endswith("Jessica McCloud\nLove City Church\njessica@lovecityc.com")
