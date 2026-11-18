"""Text them again (church_leaders_note.py, POST /church/leaders-note/text-again).

Kevin, 2026-11-17, on resending a leaders-note text that failed: "build that".

Pins:
  * the send keeps who a failed text missed as contact ids (never numbers)
    and the exact words it sent; GET says how many it missed (`text_failed`)
    and what Text them again would send (`text_again`)
  * Text them again sends those same words to those leaders only: never
    one it already reached, never a number that hasn't said yes or has said
    STOP (both checked again as it goes, whatever the record says)
  * who it still missed is kept; at most AGAIN_MOST tries a week, and only
    in the week the note went
  * the note's own gate; the card and quiet hours refuse before anything
    is taken or sent
  * a failed read is a 503, never a send; when nothing went the try is
    given back; two presses text once; a send that broke partway never goes
    again
  * the email alone (or a text that couldn't go at all) can be texted for
    the first time that week, to every leader who said yes
  * a record in a shape no send writes offers nothing
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_leaders_note as cln  # noqa: E402
import sms_routing  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from test_church_leaders_note import BIZ, C, ID, client, db, note, ok, page, send  # noqa: E402,F401
from test_church_leaders_note_text import A, B, S, SUBJECT, TEXT, X, send_text, texts  # noqa: E402,F401

SHORT = cln.text_version(SUBJECT, TEXT)
BODY = f"Love City Church: {SHORT} Reply STOP to opt out."
MISSED = sorted([C["moore"], C["grant"]])     # the Moores share B


def again(who="clerk", biz=BIZ):
    return client(who).post("/church/leaders-note/text-again", json={"business_id": biz})


def failed_send(db, texts):
    """This week's note with its text, B's text failing: the Moores missed."""
    texts["fail"] = {B}
    r = ok(send_text())
    texts["fail"] = set()
    texts["sent"].clear()
    texts["events"].clear()
    return r


# ─── What the send keeps ──────────────────────────────────────────────

def test_a_failed_text_is_kept_by_contact_id_with_the_words_it_sent(db, texts):
    r = failed_send(db, texts)
    kept = note(db)["texts"]
    assert kept["failed_ids"] == MISSED and kept["short"] == SHORT and kept["failed"] == 2
    # Never a number in what's kept for it.
    for number in (B, "555", "(555)"):
        assert number not in str(kept["failed_ids"]) + kept["short"]
    want = {"mode": "again", "leaders": 2, "body": BODY, "tries_left": cln.AGAIN_MOST, "allowed": True, "why": ""}
    assert r["text_failed"] == 2 and r["text_again"] == want
    d = ok(page())
    assert d["sent_this_week"] is True and d["text_failed"] == 2 and d["text_again"] == want


def test_nothing_to_offer_when_every_text_went(db, texts):
    r = ok(send_text())
    assert r["text_failed"] == 0 and r["text_again"] is None
    d = ok(page())
    assert d["text_failed"] == 0 and d["text_again"] is None
    got = again()
    assert got.status_code == 409 and "nothing to text again" in got.json()["detail"]
    assert len(texts["sent"]) == 2


def test_before_the_note_goes_there_is_nothing_to_text_again(db, texts):
    d = ok(page())
    assert d["sent_this_week"] is False and d["text_failed"] == 0 and d["text_again"] is None
    got = again()
    assert got.status_code == 409 and "hasn't gone yet" in got.json()["detail"]
    assert not texts["sent"] and note(db) is None


# ─── Who gets it ──────────────────────────────────────────────────────

def test_it_goes_only_to_the_leaders_it_missed_in_the_same_words(db, texts):
    failed_send(db, texts)
    r = ok(again())
    # One text to the Moores' number; Darnell (A) already had his.
    assert texts["sent"] == [(B, BODY)]
    assert r["reached"] == 2 and r["failed"] == 0 and r["unsure"] is False and r["recorded"] is True
    kept = note(db)["texts"]
    assert {k: kept[k] for k in ("sent", "texts", "skipped", "failed", "failed_ids", "tries", "body", "short")} == {
        "sent": 3, "texts": 2, "skipped": 3, "failed": 0, "failed_ids": [], "tries": 1, "body": BODY, "short": SHORT}
    assert [(a["by_name"], a["sent"], a["failed"]) for a in kept["again"]] == [("Kim Lee", 2, 0)]
    assert "state" not in kept
    assert r["texts"]["sent"] == 3 and r["text_failed"] == 0 and r["text_again"] is None
    # Logged as the note's text, never as an announcement.
    assert [k for k, _ in texts["events"]] == [cln.TEXT_EVENT]
    d = ok(page())
    assert d["text_failed"] == 0 and d["text_again"] is None and d["last"]["texts"]["sent"] == 3
    # Nothing left to send.
    assert again().status_code == 409 and len(texts["sent"]) == 1


def test_never_a_number_that_has_said_stop_or_no_longer_says_yes(db, texts):
    failed_send(db, texts)
    texts["stopped"] = {B}
    r = ok(again())
    assert texts["sent"] == [] and r["reached"] == 0 and r["failed"] == 0
    kept = note(db)["texts"]
    # STOP took them off: counted as skipped, never tried again.
    assert kept["failed"] == 0 and kept["failed_ids"] == [] and kept["skipped"] == 5 and kept["sent"] == 1


def test_who_it_texts_is_held_to_yes_whatever_the_record_says(db, texts):
    failed_send(db, texts)
    texts["yes"] = {A}               # the Moores' number no longer says yes
    ok(again())
    assert texts["sent"] == []
    # Even a record naming leaders who never said yes (Reed on S, Noah on X)
    # texts no one: the yes is checked as it goes.
    db.now = db.now + timedelta(days=7)
    texts["fail"] = {S, X}
    texts["yes"] = {A, B, S, X}
    ok(send_text())
    texts["sent"].clear()
    texts["fail"] = set()
    assert note(db)["texts"]["failed_ids"] == sorted([C["reed"], C["price"]])
    texts["yes"] = {A, B}
    ok(again())
    assert texts["sent"] == []


def test_a_leader_no_longer_in_the_leaders_room_isnt_texted(db, texts):
    failed_send(db, texts)
    db.room[BIZ] = [r for r in db.room[BIZ] if r["contact_id"] not in MISSED]
    got = again()
    assert got.status_code == 409 and "no one to text" in got.json()["detail"]
    assert texts["sent"] == [] and note(db)["texts"].get("tries", 0) == 0


def test_who_it_still_missed_is_kept_and_twice_a_week_is_the_most(db, texts):
    failed_send(db, texts)
    texts["fail"] = {B}
    r = ok(again())
    assert r["reached"] == 0 and r["failed"] == 2
    kept = note(db)["texts"]
    assert kept["failed_ids"] == MISSED and kept["failed"] == 2 and kept["tries"] == 1
    assert r["text_again"]["allowed"] is True and r["text_again"]["tries_left"] == 1
    r = ok(again())
    assert note(db)["texts"]["tries"] == 2 and len(note(db)["texts"]["again"]) == 2
    assert r["text_again"] == {"mode": "again", "leaders": 2, "body": BODY, "tries_left": 0, "allowed": False,
                               "why": cln.AGAIN_LIMIT}
    texts["fail"] = set()
    got = again()
    assert got.status_code == 409 and got.json()["detail"] == cln.AGAIN_LIMIT
    assert texts["sent"] == []
    d = ok(page())
    assert d["text_failed"] == 2 and d["text_again"]["allowed"] is False


def test_only_in_the_week_the_note_went(db, texts):
    failed_send(db, texts)
    db.now = db.now + timedelta(days=7)
    d = ok(page())
    assert d["sent_this_week"] is False and d["text_failed"] == 0 and d["text_again"] is None
    got = again()
    assert got.status_code == 409 and "hasn't gone yet" in got.json()["detail"]
    assert texts["sent"] == []


# ─── Who may ──────────────────────────────────────────────────────────

def test_the_gate_is_the_notes_own(db, texts):
    import church_duties
    failed_send(db, texts)
    for who in ("deacon", "watcher", "stranger", "other_clerk"):
        assert again(who).status_code == 404, who
    for s in db.t["business_users"]:
        if s["user_id"] == ID["clerk"]:
            s["lane"] = "media_comms"      # a lane that doesn't do the note
    church_duties._CACHE.clear()
    got = again("clerk")
    assert got.status_code == 403 and got.json()["detail"] == church_duties.refusal(BIZ, "leaders_note")
    assert texts["sent"] == [] and note(db)["texts"].get("tries", 0) == 0
    assert ok(again("admin"))["reached"] == 2


def test_quiet_hours_refuse_before_anything_is_taken(db, texts, monkeypatch):
    failed_send(db, texts)
    monkeypatch.setattr(cln, "quiet_now", lambda biz: True)
    got = again()
    assert got.status_code == 409
    assert got.json()["detail"] == ("It's quiet hours at Love City Church (9 PM to 7 AM), so texts can't go now. "
                                    "Send the text after 7 AM.")
    assert texts["sent"] == [] and note(db)["texts"].get("tries", 0) == 0
    a = ok(page())["text_again"]
    assert a["allowed"] is False and a["why"] == got.json()["detail"] and a["tries_left"] == cln.AGAIN_MOST


def test_no_card_refuses_before_anything_is_taken(db, texts, monkeypatch):
    import billing_limits
    failed_send(db, texts)

    def no_card(b, what):
        raise HTTPException(402, {"error": "card_required", "what": what, "message": "Add a card to send texts."})
    monkeypatch.setattr(billing_limits, "require_card", no_card)
    assert again().status_code == 402
    assert texts["sent"] == [] and note(db)["texts"].get("tries", 0) == 0


# ─── When a read fails ────────────────────────────────────────────────

def test_a_failed_read_is_a_503_never_a_send(db, texts, monkeypatch):
    failed_send(db, texts)
    before = dict(note(db))
    # The church's record (read fresh before anything goes).
    real = cln._business
    calls = {"n": 0}

    def second_fails(biz_id):
        calls["n"] += 1
        if calls["n"] == 2:
            raise HTTPException(503, "The leaders note couldn't be put together just now. Try again.")
        return real(biz_id)
    monkeypatch.setattr(cln, "_business", second_fails)
    assert again().status_code == 503 and calls["n"] == 2
    monkeypatch.setattr(cln, "_business", real)
    # The leaders room, and the leaders' records.
    room = db.room
    db.room = None
    assert again().status_code == 503
    db.room = room
    db.failing = {"contacts"}
    assert again().status_code == 503
    db.failing = set()
    # Who said yes: nothing went, so the try is given back as it was.
    texts["yes"] = None
    got = again()
    assert got.status_code == 503 and got.json()["detail"].startswith("Couldn't check who has said yes")
    assert texts["sent"] == [] and note(db) == before
    texts["yes"] = {A, B}
    assert ok(again())["reached"] == 2


def test_two_presses_text_once(db, texts, monkeypatch):
    failed_send(db, texts)
    real = cln.recipients

    def another_press_won(biz_id):
        out = real(biz_id)
        row = next(b for b in db.t["businesses"] if b["id"] == BIZ)
        row["settings"] = {**row["settings"], cln.KEY: {**note(db), "id": "f" * 32}}   # someone else took it first
        return out
    monkeypatch.setattr(cln, "recipients", another_press_won)
    got = again()
    assert got.status_code == 409 and "Someone else is texting" in got.json()["detail"]
    assert texts["sent"] == []


def test_a_send_that_breaks_partway_never_goes_again(db, texts, monkeypatch):
    failed_send(db, texts)

    async def broke(client, phone, business_id=None):
        raise RuntimeError("the line dropped")
    monkeypatch.setattr(sms_routing, "is_opted_out", broke)
    r = ok(again())
    assert r["unsure"] is True and r["reached"] == 0
    kept = note(db)["texts"]
    assert kept["unsure"] is True and kept["failed_ids"] == [] and kept["tries"] == 1
    a = ok(page())["text_again"]
    assert a["allowed"] is False and a["why"] == cln.UNSURE
    got = again()
    assert got.status_code == 409 and got.json()["detail"] == cln.UNSURE


# ─── The week's text for the first time ───────────────────────────────

def test_after_the_email_alone_the_text_can_go_once(db, texts):
    ok(send(subject=SUBJECT, text=TEXT))
    assert texts["sent"] == []
    d = ok(page())
    assert d["text_failed"] == 0
    assert d["text_again"] == {"mode": "first", "leaders": 3, "body": BODY, "tries_left": cln.AGAIN_MOST,
                               "allowed": True, "why": ""}
    r = ok(again())
    assert sorted(p for p, _ in texts["sent"]) == [A, B] and all(b == BODY for _, b in texts["sent"])
    assert r["reached"] == 3 and r["texts"]["sent"] == 3 and r["texts"]["skipped"] == 3
    kept = note(db)["texts"]
    assert kept["tries"] == 1 and kept["short"] == SHORT and kept["failed_ids"] == []
    assert ok(page())["text_again"] is None
    assert again().status_code == 409 and len(texts["sent"]) == 2


def test_no_offer_when_no_leader_gets_texts(db, texts):
    ok(send(subject=SUBJECT, text=TEXT))
    texts["yes"] = set()
    assert ok(page())["text_again"] is None


def test_a_text_that_couldnt_go_at_all_can_go_later(db, texts):
    texts["yes"] = None
    r = ok(send_text())
    assert r["texts"]["error"] and note(db)["texts"]["none_went"] is True
    assert ok(page())["text_again"] is None          # who said yes still can't be read
    texts["yes"] = {A, B}
    a = ok(page())["text_again"]
    assert a["mode"] == "first" and a["leaders"] == 3 and a["body"] == BODY
    ok(again())
    assert sorted(p for p, _ in texts["sent"]) == [A, B]
    kept = note(db)["texts"]
    assert "error" not in kept and "none_went" not in kept and kept["sent"] == 3


# ─── What's kept is read strictly ─────────────────────────────────────

def _rec(**texts_):
    t = {"sent": 1, "texts": 1, "skipped": 3, "failed": 2, "body": BODY, "short": SHORT, "failed_ids": MISSED, **texts_}
    return {"id": "x", "week": "2026-10-26", "state": "sent", "subject": SUBJECT, "text": TEXT, "texts": t}


def test_a_record_in_a_shape_no_send_writes_offers_nothing():
    assert cln.again_of(_rec())["mode"] == "again" and cln.again_of(_rec())["ids"] == MISSED
    # Numbers where contact ids belong, or too many: never a guess at who.
    for bad in ([B], MISSED + ["not-an-id"], [C["moore"]] * 3 + ["x"], "moore", [C["moore"]] * (cln.IDS_MOST + 1)):
        a = cln.again_of(_rec(failed_ids=bad))
        assert a["ids"] == [] and a["why"], bad
    # Words that aren't a text version.
    for bad in ("", "   ", "x" * (cln.TEXT_SHORT + 1), 7, None):
        assert cln.again_of(_rec(short=bad))["why"], bad
    # Tries that aren't a count a send writes.
    for bad in ("1", True, -1, cln.AGAIN_MOST + 1, 1.0):
        assert cln.again_of(_rec(tries=bad))["mode"] is None, bad
    assert cln.again_of({**_rec(), "texts": "sent"})["mode"] is None
    assert cln.again_of({**_rec(), "state": "sending"})["mode"] is None
    assert cln.again_of(_rec(state="sending"))["why"]
    # A record from before who it missed was kept says so; it never sends.
    old = _rec()
    del old["texts"]["failed_ids"], old["texts"]["short"]
    assert cln.again_of(old)["why"].startswith("This week's text went before")
    # A text that couldn't go and can't be told about offers nothing.
    assert cln.again_of(_rec(error="The text didn't go just now.", failed=0))["mode"] is None
    # Duplicates fold.
    assert cln.again_of(_rec(failed_ids=MISSED + MISSED))["ids"] == MISSED


def test_an_old_record_shows_the_miss_but_never_sends(db, texts):
    failed_send(db, texts)
    rec = note(db)
    del rec["texts"]["failed_ids"]
    d = ok(page())
    assert d["text_failed"] == 2 and d["text_again"]["allowed"] is False
    assert again().status_code == 409 and texts["sent"] == []


def test_the_record_is_the_servers_and_tries_have_their_own_limit():
    import business_settings
    import rate_limit
    assert cln.KEY in business_settings.SERVER_KEYS
    assert "church_leaders_note_text_again" in rate_limit._LIMITS
