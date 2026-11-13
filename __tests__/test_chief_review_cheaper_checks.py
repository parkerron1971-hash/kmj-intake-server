"""
test_chief_review_cheaper_checks.py — the answer check stops sending true
answers to a repair (2026-11-13).

When the first review rejects an answer and cutting cannot save it, the
check writes a repair and reviews it again: three Sonnet calls instead of
one. That was 71 of 263 checked turns in the 30 days to 2026-11-13, and the
repair often came back worse ("I can't confirm that ... open your site in a
browser yourself") than the true answer it replaced. Railway's chief.truth
lines for the week named the wrong rejections this file pins:

1. The site. Chief's prompt carries PRACTITIONER SITE (where it lives,
   published or draft, the custom domain); the review never did, so "your
   site is published at <domain>" was a gap every time.
2. Who is talking. An office login is greeted by her own name ("Good
   morning, Laquesha."); the only name in the review's records was the
   owner's.
3. What a saved record holds ("Yes, both are in that answer.", "That's
   saved in your private business knowledge") filed by the reviewer as an
   action. With no write receipt that withheld the whole answer, though
   REVIEW_SYSTEM itself calls it a fact to cite and quote.

Every one of them still needs its record and a quote that holds it.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_areas
import chief_truth as truth


BIZ = {"id": "biz-1", "name": "Northstar Coaching", "type": "coach", "settings": {}}
SITE = {"slug": "northstar-coaching", "status": "published",
        "site_config": {"custom_domain": "northstarcoaching.com"}}
DANA = {"role": "office", "name": "Dana Price", "first_name": "Dana"}


def _sources(ctx, who=None):
    token = truth.begin("owner-1", "q")
    who_token = chief_areas.WHO.set(who)
    try:
        return truth.evidence_for_review(ctx, {}, [])
    finally:
        chief_areas.WHO.reset(who_token)
        truth.end(token)


# ── 1. The site record is evidence ───────────────────────────────────

def test_the_review_reads_the_site_record_chief_reads():
    sources = _sources({"business": BIZ, "site": SITE})
    site = sources["context:site"]
    assert "Status: published" in site["text"]
    assert "Custom domain: northstarcoaching.com" in site["text"]
    assert "northstar-coaching.mysolutionist.app" in site["text"]
    assert site["kind"] == "context" and site["complete"] is True


@pytest.mark.parametrize("site", [None, {}, {"status": "published"}])
def test_no_site_row_is_unknown_never_no_site(site):
    # A site read that failed must not become "(no site generated yet)"
    # evidence for "you don't have a website".
    ctx = {"business": BIZ, **({"site": site} if site is not None else {})}
    assert "context:site" not in _sources(ctx)


def test_the_site_record_sits_with_the_steady_records():
    groups = truth._cacheable_review_messages([{"role": "user", "content": json.dumps(
        {"sources": _sources({"business": BIZ, "site": SITE}), "draft": "x"})}])[0]["content"]
    assert '"context:site"' in groups[0]["text"]


# ── 2. Who is talking is evidence ────────────────────────────────────

def test_an_office_login_is_named_in_the_evidence():
    sources = _sources({"business": BIZ}, who=DANA)
    login = sources["context:login"]["text"]
    assert "TALKING WITH: Dana Price" in login and "Call them Dana" in login


def test_the_owner_adds_no_login_source():
    assert "context:login" not in _sources({"business": BIZ})


def test_the_login_rides_with_the_records_that_move():
    # It differs by login: the owner and an office login on one business
    # must not re-write the steady group between them.
    assert "login" in truth._REVIEW_ACTIVITY
    groups = truth._cacheable_review_messages([{"role": "user", "content": json.dumps(
        {"sources": _sources({"business": BIZ, "contacts_total": 3}, who=DANA), "draft": "x"})}])[0]["content"]
    assert '"context:login"' not in groups[0]["text"]


# ── finalize_reply: a cited true answer goes out in ONE review ───────

def _finalize(draft, review, *, ctx, who=None, message="Is my website up?"):
    calls = []

    async def reviewer(client, system, messages, **kw):
        calls.append(kw.get("model_lane", "review"))
        return json.dumps(review)

    async def repairer(client, system, messages, **kw):
        calls.append("repair")
        return "I can't confirm that."

    token = truth.begin("owner-1", message)
    who_token = chief_areas.WHO.set(who)
    try:
        text, meta = asyncio.run(truth.finalize_reply(
            None, draft, ctx=ctx, view_detail={}, taken=[], message=message,
            business_id=None, reviewer=reviewer, repairer=repairer))
    finally:
        chief_areas.WHO.reset(who_token)
        truth.end(token)
    return text, meta, calls


SITE_DRAFT = "Yes. Your site is published at northstarcoaching.com. Want me to walk through the home page?"
SITE_REVIEW = {"verdict": "supported", "claims": [
    {"text": "Your site is published at northstarcoaching.com", "kind": "fact",
     "source_id": "context:site", "quote": "Status: published"},
    {"text": "northstarcoaching.com", "kind": "fact",
     "source_id": "context:site", "quote": "Custom domain: northstarcoaching.com"}]}


def test_a_true_site_answer_passes_without_a_repair():
    text, meta, calls = _finalize(SITE_DRAFT, SITE_REVIEW, ctx={"business": BIZ, "site": SITE})
    assert meta["status"] == "supported" and "context:site" in meta["sources"]
    assert text == SITE_DRAFT
    assert calls == ["review"]


def test_a_site_answer_the_record_does_not_hold_is_still_stopped():
    draft_site = {**SITE, "status": "draft"}
    text, meta, calls = _finalize(SITE_DRAFT, SITE_REVIEW, ctx={"business": BIZ, "site": draft_site})
    assert meta["status"] != "supported"
    assert "is published" not in text


GREETING = "Good morning, Dana. Marcus Reed has a session on the calendar."
GREETING_CTX = {"business": BIZ, "sessions": [{"title": "Session with Marcus Reed",
                                               "starts_at": "2026-11-14T15:00:00Z"}]}


def _greeting_review(name):
    return {"verdict": "supported", "claims": [
        {"text": f"Good morning, {name}.", "kind": "fact", "source_id": "context:login",
         "quote": f"TALKING WITH: {name} Price"},
        {"text": "Marcus Reed has a session on the calendar", "kind": "fact",
         "source_id": "context:sessions", "quote": "Session with Marcus Reed"}]}


def test_an_office_login_greeted_by_name_passes_without_a_repair():
    text, meta, calls = _finalize(GREETING, _greeting_review("Dana"), ctx=GREETING_CTX, who=DANA,
                                  message="[SYSTEM:opening_greeting:morning]")
    assert meta["status"] == "supported" and text.startswith("Good morning, Dana.")
    assert calls == ["review"]


def test_the_wrong_name_is_still_stopped():
    wrong = GREETING.replace("Dana", "Marcus")
    text, meta, _calls = _finalize(wrong, _greeting_review("Marcus"), ctx=GREETING_CTX, who=DANA,
                                   message="[SYSTEM:opening_greeting:morning]")
    assert meta["status"] != "supported"
    assert "Good morning, Marcus." not in text


# ── 3. What a saved record holds is a fact ───────────────────────────

@pytest.mark.parametrize("text", [
    "Yes, both are in that answer.",
    "That's saved in your private business knowledge",
    "The kids answer now has the Children's Church and teen Bible study details you gave",
    "the email is drafted to monica@example.com",
    "Your FAQ has both answers.",
    "It's on file.",
])
def test_what_a_record_holds_is_record_state(text):
    assert truth.is_record_state(text)


@pytest.mark.parametrize("text", [
    "I've also texted your clients a reminder about it.",
    "I've saved that you meet at 412 Harbor Street.",
    "We saved it to your notes.",
    "Your reminder has been sent.",
    "The invoice is in their inbox.",
    "It's on their calendar for Friday.",
    "The email went out.",
    "The changes are in your site now.",
    "Your hours are listed on your booking page.",
    "The booking is scheduled for Friday.",
    "Your message is on its way.",
    "Everything is taken care of.",
])
def test_work_done_or_delivered_is_not(text):
    assert not truth.is_record_state(text)


PICTURE = {"business_picture": {"faq": [{"q": "What do you have for kids and teens?",
                                         "a": "Children's Church at 10 AM, and teen Bible study on Wednesdays."}]}}
FAQ_CTX = {"business": {**BIZ, "settings": PICTURE}}
FAQ_DRAFT = "Yes, both are in that answer. It lists Children's Church and teen Bible study."


def _faq_review(kind, quote="Children's Church at 10 AM, and teen Bible study on Wednesdays"):
    return {"verdict": "supported", "claims": [
        {"text": "Yes, both are in that answer.", "kind": kind,
         "source_id": "context:business_picture", "quote": quote},
        {"text": "It lists Children's Church and teen Bible study", "kind": "fact",
         "source_id": "context:business_picture", "quote": quote}]}


def test_a_record_state_filed_as_an_action_is_checked_as_a_fact():
    # Filed as an action it had no write receipt, and a turn that wrote
    # nothing withheld the whole answer and paid for a repair.
    text, meta, calls = _finalize(FAQ_DRAFT, _faq_review("action"), ctx=FAQ_CTX,
                                  message="Did the kids answer get both?")
    assert meta["status"] == "supported" and text == FAQ_DRAFT
    assert calls == ["review"]


def test_a_record_state_still_needs_a_quote_the_record_holds():
    text, meta, _calls = _finalize(FAQ_DRAFT, _faq_review("action", quote="teen Bible study on Thursdays"),
                                   ctx=FAQ_CTX, message="Did the kids answer get both?")
    assert meta["status"] != "supported"
    assert "both are in that answer" not in text


def test_a_first_person_write_keeps_the_action_rule():
    review = {"verdict": "supported", "claims": [
        {"text": "I've also texted your clients a reminder about it.", "kind": "action",
         "source_id": "context:business_picture", "quote": "teen Bible study"}]}
    verdict, _cited, reason = truth.assess_review(
        json.dumps(review), "I've also texted your clients a reminder about it.",
        _sources(FAQ_CTX))
    assert verdict == "unsupported" and reason.startswith(truth.ACTION_WITHOUT_RECEIPT)


def test_an_unsourced_record_state_is_cut_not_repaired():
    draft = ("Children's Church is at 10 AM. That's saved in your private business knowledge.")
    review = {"verdict": "unsupported", "claims": [
        {"text": "Children's Church is at 10 AM", "kind": "fact",
         "source_id": "context:business_picture", "quote": "Children's Church at 10 AM"},
        {"text": "That's saved in your private business knowledge", "kind": "action",
         "source_id": "", "quote": "", "gap": "no record of a save"}]}
    text, meta, calls = _finalize(draft, review, ctx=FAQ_CTX, message="When is Children's Church?")
    assert "repair" not in calls
    assert "saved in your private business knowledge" not in text
    assert "Children's Church is at 10 AM" in text
