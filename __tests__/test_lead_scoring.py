"""
test_lead_scoring.py — the rubric, and the four doors that must use it.

The bug this arc closes was not that scoring was wrong; it was that
scoring only ran on ONE of four capture doors, so `contacts.lead_score`
was null for most real leads and every reader gated on it went quiet.
Two thirds of this file is therefore wiring tests: proof that each door
actually calls the scorer. A rubric nobody invokes is worth nothing.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lead_scoring  # noqa: E402


SYNC = {"LEAD_SCORING_MODE": "sync"}


# ═══════════════════════════════════════════════════════════════════════
# The rubric
# ═══════════════════════════════════════════════════════════════════════

def test_score_is_never_null_and_always_in_range():
    """The whole point of a deterministic first pass: every reader gated
    on lead_score works with the AI switched off."""
    for submission in ({}, {"name": "A"}, {"junk": None}, {"x": ["a", "b"]}):
        result = lead_scoring.score_lead(submission)
        assert isinstance(result.score, int)
        assert 0 <= result.score <= 100


def test_unreachable_lead_scores_low():
    """A name and nothing else. We cannot contact this person; they
    must not outrank someone who left an email and a paragraph."""
    result = lead_scoring.score_lead({"name": "Anon"})
    assert result.score < 40
    assert result.priority == "low"


def test_reachable_and_specific_scores_high():
    result = lead_scoring.score_lead(
        {"name": "Dana Whitfield", "email": "dana@example.com",
         "phone": "555-0142",
         "message": "Our back office is drowning in paperwork and I need "
                    "someone to take it over before the quarter closes. "
                    "We are a six-person team and have budget approved."},
        email="dana@example.com", phone="555-0142")
    assert result.score >= 70
    assert result.priority == "high"


def test_urgency_lifts_the_score():
    base = {"name": "Sam", "email": "sam@example.com",
            "message": "I would like to talk about getting some help with "
                       "the thing we discussed at the meetup last week."}
    calm = lead_scoring.score_lead(base, email="sam@example.com")
    urgent = lead_scoring.score_lead(
        dict(base, message=base["message"] + " I need this handled ASAP."),
        email="sam@example.com")
    assert urgent.score > calm.score
    assert "signalled urgency" in urgent.signals


def test_length_of_answer_counts_as_intent():
    short = lead_scoring.score_lead(
        {"name": "P", "email": "p@example.com", "message": "hi"},
        email="p@example.com")
    long = lead_scoring.score_lead(
        {"name": "P", "email": "p@example.com", "message": "x" * 240},
        email="p@example.com")
    assert long.score > short.score


def test_honeypot_fields_do_not_count_toward_completeness():
    """A bot filling the hidden field must not look like a thorough
    human who answered every question."""
    clean = lead_scoring.score_lead(
        {"name": "R", "email": "r@example.com"}, email="r@example.com")
    trapped = lead_scoring.score_lead(
        {"name": "R", "email": "r@example.com", "_hp": "http://spam",
         "fax": "999"}, email="r@example.com")
    assert trapped.score <= clean.score


def test_source_bonuses():
    """Committing to a time, or holding a conversation first, are
    signals no form field carries."""
    plain = lead_scoring.score_lead(
        {"name": "T", "email": "t@example.com"}, email="t@example.com")
    booked = lead_scoring.score_lead(
        {"name": "T", "email": "t@example.com"}, source="booking_widget",
        email="t@example.com")
    talked = lead_scoring.score_lead(
        {"name": "T", "email": "t@example.com"}, source="site_concierge",
        email="t@example.com")
    assert booked.score > plain.score
    assert talked.score > plain.score


def test_an_invalid_email_earns_no_reachability_credit():
    good = lead_scoring.score_lead({"name": "V"}, email="v@example.com")
    bad = lead_scoring.score_lead({"name": "V"}, email="not-an-email")
    assert good.score > bad.score


# ═══════════════════════════════════════════════════════════════════════
# Generalization — the rubric replaced a two-vertical lookup table
# ═══════════════════════════════════════════════════════════════════════

SEVEN_TRADES = [
    ("barber", "My clippers guy retired and I need a regular cut, "
               "every other Thursday if you have the slot. Booking today."),
    ("attorney", "I was served on Monday and the response window is "
                 "twenty days. I need representation this week."),
    ("contractor", "The roof is leaking into the upstairs bedroom after "
                   "the storm. Need someone out here as soon as possible."),
    ("therapist", "I have been struggling since the move and would like "
                  "to start weekly sessions. Insurance is through work."),
    ("coach", "I am two years into the business and stuck at the same "
              "revenue. I want a plan and someone to hold me to it."),
    ("consultant", "Our onboarding takes six weeks and should take one. "
                   "Board wants a fix before the quarter closes."),
    ("pastor", "My family just moved to the area and we are looking for "
               "a church home. We would like to visit this Sunday."),
]


def test_every_trade_scores_the_same_shape_of_enquiry_the_same_way():
    """The scorer this replaced enumerated `warm_welcome (church/ministry
    visitor)` and `discovery_invite (coaching/consulting prospect)` — a
    lookup table covering two of seven verticals. Urgent, specific and
    reachable has to mean the same thing in all seven."""
    scores = {}
    for trade, message in SEVEN_TRADES:
        result = lead_scoring.score_lead(
            {"name": "A Person", "email": "a@example.com",
             "phone": "555-0100", "message": message},
            email="a@example.com", phone="555-0100")
        scores[trade] = result.score
        assert result.score >= 70, f"{trade} scored {result.score}: {result.signals}"
    # And no trade is systematically favoured: the spread across seven
    # equally-strong enquiries stays inside one priority band.
    assert max(scores.values()) - min(scores.values()) <= 20, scores


def test_response_type_describes_the_ask_not_the_trade():
    booked = lead_scoring.score_lead(
        {"name": "A", "email": "a@example.com", "preferred_date": "Friday"},
        email="a@example.com")
    assert booked.response_type == "book_time"
    thin = lead_scoring.score_lead({"name": "A"})
    assert thin.response_type == "nurture"
    assert booked.response_type in lead_scoring.RESPONSE_TYPES
    assert thin.response_type in lead_scoring.RESPONSE_TYPES


# ═══════════════════════════════════════════════════════════════════════
# The refinement can only nudge
# ═══════════════════════════════════════════════════════════════════════

def _rich():
    return {"name": "Dana", "email": "d@example.com",
            "message": "A specific and reasonably detailed description of "
                       "the problem I would like solved, thank you."}


def _keyed():
    """A fake key plus a stubbed spend guard — otherwise `over_budget`
    reaches for api_usage and these become network tests."""
    return (mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}),
            mock.patch("spend_guard.over_budget", return_value=False))


def test_refine_is_a_no_op_without_a_key():
    base = lead_scoring.score_lead(_rich(), email="d@example.com")
    with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
        out = lead_scoring.refine(base, _rich())
    assert out is base
    assert out.refined is False


def test_refine_does_not_run_on_a_submission_with_no_prose():
    """No free text, nothing for a model to read, no reason to spend."""
    bare = lead_scoring.score_lead({"name": "A", "email": "a@example.com"},
                                   email="a@example.com")
    env, guard = _keyed()
    with env, guard, mock.patch("llm_call.post") as post:
        out = lead_scoring.refine(bare, {"name": "A", "email": "a@example.com"})
    assert out is bare
    post.assert_not_called()


def test_refine_is_skipped_when_the_business_is_over_budget():
    base = lead_scoring.score_lead(_rich(), email="d@example.com")
    with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}), \
         mock.patch("spend_guard.over_budget", return_value=True), \
         mock.patch("llm_call.post") as post:
        out = lead_scoring.refine(base, _rich(), business_id="biz-1")
    assert out is base
    post.assert_not_called()


def _fake_llm(delta, response_type="book_time", reasoning="because"):
    payload = ('{"delta": %s, "reasoning": "%s", "response_type": "%s"}'
               % (delta, reasoning, response_type))
    resp = mock.Mock(status_code=200)
    resp.json.return_value = {"content": [{"type": "text", "text": payload}]}
    return resp


def test_refine_is_clamped_to_the_band():
    """A model having a bad day must not be able to turn a
    well-qualified lead cold, or invent a hot one."""
    base = lead_scoring.score_lead(_rich(), email="d@example.com")
    env, guard = _keyed()
    with env, guard, mock.patch("llm_call.post", return_value=_fake_llm(-95)):
        down = lead_scoring.refine(base, _rich())
    env, guard = _keyed()
    with env, guard, mock.patch("llm_call.post", return_value=_fake_llm(95)):
        up = lead_scoring.refine(base, _rich())
    assert down.score == max(0, base.score - lead_scoring.REFINE_BAND)
    assert up.score == min(100, base.score + lead_scoring.REFINE_BAND)
    assert down.refined is True and up.refined is True


def test_refine_survives_garbage_from_the_model():
    base = lead_scoring.score_lead(_rich(), email="d@example.com")
    junk = mock.Mock(status_code=200)
    junk.json.return_value = {"content": [{"type": "text", "text": "sorry!"}]}
    env, guard = _keyed()
    with env, guard, mock.patch("llm_call.post", return_value=junk):
        out = lead_scoring.refine(base, _rich())
    assert out.score == base.score


def test_refine_rejects_an_unknown_response_type():
    base = lead_scoring.score_lead(_rich(), email="d@example.com")
    env, guard = _keyed()
    with env, guard, mock.patch(
            "llm_call.post",
            return_value=_fake_llm(0, response_type="warm_welcome")):
        out = lead_scoring.refine(base, _rich())
    assert out.response_type in lead_scoring.RESPONSE_TYPES
    assert out.response_type == base.response_type


# ═══════════════════════════════════════════════════════════════════════
# Storage — high-water mark
# ═══════════════════════════════════════════════════════════════════════

def _store(existing_score, new_score):
    import sb_clients
    import event_spine
    patches, events = [], []

    def fake_get(path):
        return [{"lead_score": existing_score}]

    with mock.patch.object(sb_clients, "sb_get_as_service", side_effect=fake_get), \
         mock.patch.object(sb_clients, "sb_patch_as_service",
                           side_effect=lambda p, b: patches.append((p, b))), \
         mock.patch.object(event_spine, "emit",
                           side_effect=lambda t, b, d=None, contact_id=None,
                           source="system": events.append((t, d)) or True):
        lead_scoring.store("biz-1", "c-1",
                           lead_scoring.LeadScore(score=new_score),
                           source="website_contact_form")
    return patches, events


def test_a_terse_follow_up_does_not_demote_a_hot_lead():
    """lead_score is the high-water mark of their best enquiry. Someone
    who wrote three paragraphs last week and 'any update?' today has not
    become a colder prospect — and must not fall out of Hot Leads."""
    patches, events = _store(existing_score=82, new_score=31)
    assert not patches, "a lower reading must never overwrite a higher score"
    assert events[0][0] == "lead_scored"
    assert events[0][1]["score"] == 31          # the reading is still recorded
    assert events[0][1]["previous_score"] == 82


def test_a_stronger_enquiry_raises_the_score():
    patches, _ = _store(existing_score=31, new_score=82)
    assert len(patches) == 1
    assert patches[0][1] == {"lead_score": 82}


def test_first_score_is_always_written():
    patches, _ = _store(existing_score=None, new_score=44)
    assert patches[0][1] == {"lead_score": 44}


def test_store_never_raises_when_the_database_is_down():
    import sb_clients
    with mock.patch.object(sb_clients, "sb_get_as_service",
                           side_effect=RuntimeError("boom")), \
         mock.patch.object(sb_clients, "sb_patch_as_service",
                           side_effect=RuntimeError("boom")):
        assert lead_scoring.store("b", "c", lead_scoring.LeadScore(score=50)) is False


# ═══════════════════════════════════════════════════════════════════════
# The wiring — every door, which is the entire point of the arc
# ═══════════════════════════════════════════════════════════════════════

def test_dispatch_modes():
    calls = []
    with mock.patch.object(lead_scoring, "score_and_store",
                           side_effect=lambda *a, **k: calls.append(a)):
        with mock.patch.dict(os.environ, {"LEAD_SCORING_MODE": "off"}):
            lead_scoring.score_in_background("b", "c", {})
        assert not calls
        with mock.patch.dict(os.environ, SYNC):
            lead_scoring.score_in_background("b", "c", {})
        assert len(calls) == 1


def _door_fires(call_the_door):
    """Run a capture path with scoring in sync mode and report what it
    handed to the scorer."""
    seen = {}

    def fake_score(business_id, contact_id, submission, **kwargs):
        seen.update(business_id=business_id, contact_id=contact_id,
                    submission=submission, **kwargs)

    with mock.patch.dict(os.environ, SYNC), \
         mock.patch.object(lead_scoring, "score_and_store",
                           side_effect=fake_score):
        call_the_door()
    return seen


def test_website_contact_form_scores_its_lead():
    import sb_clients
    import event_spine
    import public_site

    with mock.patch.object(sb_clients, "sb_get_as_service", return_value=[]), \
         mock.patch.object(sb_clients, "sb_post_as_service",
                           return_value=[{"id": "c-web"}]), \
         mock.patch.object(event_spine, "emit", return_value=True):
        seen = _door_fires(lambda: public_site._capture_contact_from_form(
            "biz-1", "Visitor", "v@example.com", "555-0111", "I need help."))

    assert seen["contact_id"] == "c-web"
    assert seen["business_id"] == "biz-1"
    assert seen["source"] == "website_contact_form"
    assert seen["email"] == "v@example.com"
    assert seen["submission"]["message"] == "I need help."


def test_site_concierge_scores_its_lead():
    import sb_clients
    import site_concierge

    with mock.patch.object(sb_clients, "sb_get_as_service", return_value=[]), \
         mock.patch.object(sb_clients, "sb_post_as_service",
                           return_value=[{"id": "c-con"}]):
        seen = _door_fires(lambda: site_concierge._find_or_create_contact(
            "biz-1", "Visitor", "v@example.com", "Do you take walk-ins?"))

    assert seen["contact_id"] == "c-con"
    assert seen["source"] == "site_concierge"


def test_site_concierge_scores_a_returning_visitor_too():
    """A second, richer enquiry is new information about the same
    person — the door must re-score, not skip."""
    import sb_clients
    import site_concierge

    with mock.patch.object(sb_clients, "sb_get_as_service",
                           return_value=[{"id": "c-old", "metadata": {}}]), \
         mock.patch.object(sb_clients, "sb_patch_as_service", return_value=[]):
        seen = _door_fires(lambda: site_concierge._find_or_create_contact(
            "biz-1", "Visitor", "v@example.com", "Following up on this."))

    assert seen["contact_id"] == "c-old"


def test_booking_widget_scores_a_new_lead():
    import sb_clients
    import booking_widget_router

    with mock.patch.object(sb_clients, "sb_get_as_service", return_value=[]), \
         mock.patch.object(sb_clients, "sb_post_as_service",
                           return_value=[{"id": "c-book"}]):
        seen = _door_fires(lambda: booking_widget_router._find_or_create_contact(
            "biz-1", "Booker", "b@example.com"))

    assert seen["contact_id"] == "c-book"
    assert seen["source"] == "booking_widget"


def test_booking_widget_does_not_rescore_a_returning_customer():
    """Someone who already exists and books again is a customer, not a
    lead to qualify."""
    import sb_clients
    import booking_widget_router

    with mock.patch.object(sb_clients, "sb_get_as_service",
                           return_value=[{"id": "c-known"}]):
        seen = _door_fires(lambda: booking_widget_router._find_or_create_contact(
            "biz-1", "Booker", "b@example.com"))

    assert seen == {}


# ═══════════════════════════════════════════════════════════════════════
# The readers that had been wired to one door
# ═══════════════════════════════════════════════════════════════════════

def _urgent_check_queries():
    """Run _check_urgent against a stubbed database and return the GET
    paths it asked for."""
    import asyncio
    import notification_engine as ne

    paths = []

    async def fake_sb(client, method, path, body=None):
        paths.append(path)
        if path.startswith("/businesses"):
            return [{"id": "biz-1", "settings": {}}]
        return []

    async def allow(client, biz, key, default=True):
        return True

    with mock.patch.object(ne, "_sb", side_effect=fake_sb), \
         mock.patch.object(ne, "_settings_allow", side_effect=allow):
        asyncio.run(ne._check_urgent(None, "biz-1"))
    return paths


def test_hot_lead_alert_watches_every_inquiry_door():
    """It filtered `event_type=eq.form_submit`, which only the embeddable
    intake form emits — so a lead from the site's own contact form or the
    concierge could never trigger it, and lead_score being null on those
    doors excluded them a second time."""
    events_query = [p for p in _urgent_check_queries()
                    if p.startswith("/events")]
    assert events_query, "the hot-lead check no longer reads events"
    query = events_query[0]
    for event_type in ("form_submit", "contact_form_submitted",
                       "concierge_lead_captured"):
        assert event_type in query, f"hot-lead query ignores {event_type}"


def test_hot_lead_alert_ignores_bookings():
    """Someone who already picked a time is not a lead to chase today."""
    query = [p for p in _urgent_check_queries() if p.startswith("/events")][0]
    assert "booking" not in query


def test_lead_scored_is_in_the_spine_catalog():
    """An uncataloged emit() fails the drift test; this is the guard for
    the new event rather than a restatement of it."""
    import event_spine
    assert "lead_scored" in event_spine.EVENT_CATALOG
    assert "score" in event_spine.EVENT_CATALOG["lead_scored"]["payload"]
