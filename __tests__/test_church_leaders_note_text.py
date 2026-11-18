"""The leaders note as a text too (church_leaders_note.py, "Text it too").

Kevin, 2026-11-17, approving it for the Office & Leadership admin: "Send
the Monday leaders note as a short text to the leaders" ... "make this
happen please".

Pins:
  * the text is short and only the note's own words: the subject and the
    note's first lines, the headings left out, cut at a word to 300 letters
    with plain dots, in plain letters (the app's textVersion says the same,
    tests/church-leaders-note-check.ts)
  * GET says how many of the leaders get texts (`texts`), and a read of who
    said yes that fails is None, never a number, with the note still a 200
  * POST with also_text texts only the leaders whose numbers said yes (STOP
    wins, a shared number gets one text), the church's name first and the
    way out last, logged as the leaders note's text and never as an
    announcement, and records how many were texted and skipped
  * no also_text: no text and no reads for one
  * the gate is the note's (a Manager holding leaders_note, not weekly_text)
  * quiet hours and a missing card refuse the send before the week is
    taken: nothing is emailed or texted
  * a text that can't go leaves the email sent and says why
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_leaders_note as cln  # noqa: E402
import sms_alerts  # noqa: E402
import sms_routing  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from test_church_leaders_note import BIZ, C, NY, client, db, note, ok, page, send  # noqa: E402,F401

A, B, S, X = "+15550000001", "+15550000002", "+15550000003", "+15550000009"
SUBJECT = "Leaders, the week of October 26"
TEXT = "This week\nSunday, November 1\n10:30 AM · Sunday service\n\nOne win\nA family came back."


@pytest.fixture
def texts(db, monkeypatch):
    """Phones on the leaders, who said yes, and a send that never leaves."""
    phone = {"hayes": A, "moore": B, "grant": "(555) 000-0002", "reed": S, "price": X}
    for c in db.t["contacts"]:
        for k, v in phone.items():
            if c["id"] == C[k]:
                c["phone"] = v
    world = {"yes": {A, B}, "stopped": set(), "sent": [], "events": [], "fail": set(), "checked": [],
             "said_yes_calls": 0}

    async def said_yes(client, business_id, phones, **kw):
        world["said_yes_calls"] += 1
        if world["yes"] is None:
            return None
        return {p for p in phones if p in world["yes"]} - world["stopped"]

    async def biz_name(client, business_id):
        return "Love City Church"

    async def opted_out(client, phone, business_id=None):
        return phone in world["stopped"]

    async def sms(phone, body, *, business_id, client=None):
        if phone in world["fail"]:
            raise RuntimeError("carrier said no")
        world["sent"].append((phone, body))
        return f"SM{len(world['sent'])}"

    async def store(client, **kw):
        return "row"

    async def log_event(client, business_id, contact_id, kind, data):
        world["events"].append((kind, data))

    async def no_wait(_):
        return None

    import billing_limits
    import church_texts
    monkeypatch.setattr(sms_alerts, "said_yes_to_texts", said_yes)
    monkeypatch.setattr(sms_routing, "_biz_name", biz_name)
    monkeypatch.setattr(sms_routing, "is_opted_out", opted_out)
    monkeypatch.setattr(sms_routing, "_send_platform_sms", sms)
    monkeypatch.setattr(sms_routing, "_store_sms", store)
    monkeypatch.setattr(sms_routing, "_log_event", log_event)
    monkeypatch.setattr(sms_routing.asyncio, "sleep", no_wait)
    monkeypatch.setattr(church_texts, "check_allowance", lambda bid, *a, **k: world["checked"].append(bid))
    monkeypatch.setattr(billing_limits, "require_card", lambda b, what: None)
    monkeypatch.setattr(cln, "quiet_now", lambda biz: False)
    return world


def send_text(who="clerk", **kw):
    r = client(who).post("/church/leaders-note/send",
                         json={"business_id": BIZ, "subject": SUBJECT, "text": TEXT, "also_text": True, **kw})
    return r


# ─── The text version ─────────────────────────────────────────────────

def test_the_text_is_the_subject_and_the_notes_lines_in_plain_letters():
    assert cln.text_version(SUBJECT, TEXT) == (
        "Leaders, the week of October 26\nSunday, November 1\n10:30 AM - Sunday service\nA family came back.")
    # A heading typed with a plain apostrophe is still left out; curly
    # quotes, long dashes and the ellipsis go plain, spaces fold.
    assert cln.text_version("  The   week ", "What's needed\n“Ushers” — two\n…and a cook") == (
        "The week\n\"Ushers\" - two\n...and a cook")
    import twilio_sms
    assert twilio_sms.is_gsm7(cln.text_version(SUBJECT, TEXT + "\n“Bring a friend” — it’s…"))


def test_a_long_note_is_cut_at_a_word_with_plain_dots():
    long = cln.text_version("S", "One win\n" + "word " * 80)
    assert len(long) <= cln.TEXT_SHORT and long.endswith("word...") and "  " not in long
    # One long word is cut where it has to be.
    assert cln.text_version("S", "x" * 400) == "S\n" + "x" * (cln.TEXT_SHORT - 5) + "..."
    # Ending on a word that fits whole keeps it.
    assert cln.text_version("S", "a" * 290 + " bbbb ccccc") == "S\n" + "a" * 290 + " bbbb..."
    # A stop or a comma before the cut isn't doubled up.
    assert cln.text_version("S", "a" * 290 + ", " + "b" * 20) == "S\n" + "a" * 290 + "..."
    assert cln.text_version("", "") == ""
    # Letters, never halves of an emoji (the app counts the same way).
    assert len(cln.text_version("S", "🙏" * 150 + " " + "b" * 200)) == 2 + 150 + 3


def test_the_text_never_carries_who_has_no_email_or_anyones_address(db, texts):
    ok(send_text())
    body = texts["sent"][0][1]
    for private in ("Noah Price", "Mia Ellis", "@", "darnell", "clerk@lovecity.org", A):
        assert private not in body, private


# ─── The reach ────────────────────────────────────────────────────────

def test_the_page_says_how_many_of_the_leaders_get_texts(db, texts):
    d = ok(page())
    # Six leaders; Darnell (A) and the Moores sharing B said yes: three
    # leaders reached on two numbers. Pastor Reed and Noah haven't said yes.
    assert d["texts"] == {"leaders": 6, "reach": 3, "numbers": 2, "quiet": False, "quiet_words": "",
                          "name": "Love City Church", "most": cln.TEXT_SHORT}
    # The email side is unchanged.
    assert d["recipients"] == {"leaders": 6, "reach": 3, "no_email": ["Mia Ellis", "Noah Price"]}


def test_who_said_yes_that_cant_be_read_is_no_reach_never_a_number(db, texts):
    texts["yes"] = None
    d = ok(page())
    assert d["texts"] is None and d["recipients"]["reach"] == 3


def test_quiet_hours_are_said_on_the_page(db, texts, monkeypatch):
    monkeypatch.setattr(cln, "quiet_now", lambda biz: True)
    t = ok(page())["texts"]
    assert t["quiet"] is True
    assert t["quiet_words"] == ("It's quiet hours at Love City Church (9 PM to 7 AM), so texts can't go now. "
                                "Send it with the text after 7 AM, or send the email alone now.")


# ─── The send ─────────────────────────────────────────────────────────

def test_text_it_too_texts_only_the_leaders_who_said_yes(db, texts):
    r = ok(send_text())
    assert r["sent"] == 3 and len(db.sent) == 3                       # the emails still go
    assert sorted(p for p, _ in texts["sent"]) == [A, B]              # one text a number; Reed, Noah never
    body = texts["sent"][0][1]
    assert body == ("Love City Church: Leaders, the week of October 26\nSunday, November 1\n"
                    "10:30 AM - Sunday service\nA family came back. Reply STOP to opt out.")
    assert all(b == body for _, b in texts["sent"])
    assert r["texts"] == {"sent": 3, "texts": 2, "skipped": 3, "failed": 0, "body": body, "error": ""}
    kept = note(db)["texts"]
    # And, for Text them again, the words it sent and who a failed text
    # missed (no one here).
    assert kept == {"sent": 3, "texts": 2, "skipped": 3, "failed": 0, "body": body,
                    "short": cln.text_version(SUBJECT, TEXT), "failed_ids": []}
    assert r["last"]["texts"]["sent"] == 3
    # Logged as the note's text, never as an announcement (My week's weekly
    # text check reads sms_broadcast), and counted on the church's texts.
    assert [k for k, _ in texts["events"]] == [cln.TEXT_EVENT] and cln.TEXT_EVENT != "sms_broadcast"
    assert texts["checked"] == [BIZ]


def test_stop_always_wins(db, texts):
    texts["stopped"] = {A}
    r = ok(send_text())
    assert [p for p, _ in texts["sent"]] == [B]
    assert r["texts"]["sent"] == 2 and r["texts"]["skipped"] == 4


def test_without_also_text_nothing_is_texted_or_read_for_it(db, texts):
    calls = texts["said_yes_calls"]
    ok(send())
    assert texts["sent"] == [] and "texts" not in note(db)
    assert texts["said_yes_calls"] == calls
    # Only a real true asks for the text.
    db.now = db.now + timedelta(days=7)
    ok(client("clerk").post("/church/leaders-note/send",
                            json={"business_id": BIZ, "subject": SUBJECT, "text": TEXT, "also_text": "yes"}))
    assert texts["sent"] == []


def test_the_gate_is_the_notes_own_not_the_weekly_text(db, texts, monkeypatch):
    # The clerk holds leaders_note; the weekly text was moved to someone else,
    # so announcements are refused to it. The note's text still goes: the
    # same note to the same people.
    import church_duties
    real = church_duties.holds
    monkeypatch.setattr(cln, "holds", lambda b, u, duty: duty == cln.LEADERS_NOTE and real(b, u, duty))
    monkeypatch.setattr(church_duties, "holds", lambda b, u, duty: False if duty == "weekly_text" else real(b, u, duty))

    def refused(*a, **k):
        raise HTTPException(403, "The weekly text is Naiya's job here.")
    monkeypatch.setattr(sms_routing, "_may_announce", refused)
    r = ok(send_text())
    assert r["texts"]["texts"] == 2
    # A member still can't send it, text or not.
    assert send_text("deacon").status_code == 404 and len(texts["sent"]) == 2


def test_quiet_hours_refuse_before_anything_is_taken_or_sent(db, texts, monkeypatch):
    monkeypatch.setattr(cln, "quiet_now", lambda biz: True)
    r = send_text()
    assert r.status_code == 409 and "quiet hours" in r.json()["detail"] and "email alone" in r.json()["detail"]
    assert note(db) is None and not db.sent and not texts["sent"]
    # The email alone still goes.
    assert ok(send())["sent"] == 3 and not texts["sent"]


def test_quiet_hours_are_the_churchs_own(db, monkeypatch):
    import business_marketing
    monkeypatch.setenv("MEMBER_QUIET_HOURS", "on")
    monkeypatch.setattr(business_marketing, "business_tz", lambda row: NY)
    biz = next(b for b in db.t["businesses"] if b["id"] == BIZ)
    db.now = datetime(2026, 10, 27, 2, 30, tzinfo=timezone.utc)          # 10:30 PM in New York
    assert cln.quiet_now(biz) is True
    db.now = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)          # 10 AM
    assert cln.quiet_now(biz) is False
    biz["settings"]["texting_hours"] = {"quiet_from": 19, "quiet_until": 9}
    db.now = datetime(2026, 10, 26, 12, 30, tzinfo=timezone.utc)         # 8:30 AM: still quiet here
    assert cln.quiet_now(biz) is True


def test_no_card_refuses_before_the_week_is_taken(db, texts, monkeypatch):
    import billing_limits

    def no_card(b, what):
        raise HTTPException(402, {"error": "card_required", "what": what, "message": "Add a card to send texts."})
    monkeypatch.setattr(billing_limits, "require_card", no_card)
    r = send_text()
    assert r.status_code == 402 and note(db) is None and not db.sent and not texts["sent"]


def test_a_text_that_cant_go_leaves_the_email_sent_and_says_why(db, texts):
    texts["yes"] = None
    r = ok(send_text())
    assert r["sent"] == 3 and len(db.sent) == 3 and not texts["sent"]
    assert r["texts"]["error"].startswith("Couldn't check who has said yes")
    assert note(db)["state"] == "sent" and note(db)["texts"]["error"]


def test_a_failed_text_is_counted_and_the_rest_still_go(db, texts):
    texts["fail"] = {B}
    r = ok(send_text())
    assert [p for p, _ in texts["sent"]] == [A]
    assert r["texts"] == {**r["texts"], "sent": 1, "texts": 1, "failed": 2, "skipped": 3}


def test_the_shared_send_is_the_announcements_own():
    # One loop for both: an announcement and the note's text (sms_routing._text_each).
    import inspect
    assert "_text_each(" in inspect.getsource(sms_routing.announce)
    assert "_text_each(" in inspect.getsource(sms_routing.text_people)
    assert "said_yes_to_texts" in inspect.getsource(sms_routing.text_people)
    out = asyncio.run(sms_routing.text_people(BIZ, [], "  ", event=cln.TEXT_EVENT))
    assert out["status"] == 400
