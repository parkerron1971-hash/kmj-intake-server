"""The router's pure logic: scoring, policy, the cache and the two gates.

2026-09-25 (Dev Desk): route low-complexity requests to Haiku and escalate
reasoning-, code- and synthesis-heavy ones to Sonnet, defaulting upward when
unsure; cache repeated and near-repeated questions; stream a first word
inside ~500ms. For Chief, "low complexity" also means "needs none of the
business's records and no action" — model_router's header says why.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import model_router as mr


def _route(msg, prior=None, **kw):
    c = mr.score(msg, prior)
    return c, mr.decide(c, **kw)


# ── routing ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("msg", [
    "thanks!", "Thank you so much", "perfect, thanks", "awesome thanks chief",
    "appreciate it", "you're amazing", "lol", "good job", "how are you?",
    "What does ROI mean?", "what's the difference between a W-2 and a 1099?",
    "define gross margin", "synonym for amazing",
])
def test_record_free_requests_go_to_haiku_alone(msg):
    c, r = _route(msg)
    assert r.lane == mr.LANE_FAST, (msg, c, r)


@pytest.mark.parametrize("msg,why", [
    ("Did Maria pay her invoice yet?", "needs_records"),
    ("How many new leads came in since Friday?", "needs_records"),
    ("Book Sam for a haircut Thursday at 3", "needs_action"),
    ("send the invoice to the Johnsons", "needs_action"),
    ("Draft a follow-up email about their deposit", "needs_action"),
    ("write me a tagline for the spring sale", "needs_action"),
    ("What should I focus on this week to grow revenue?", "needs_records"),
    ("Why is my conversion rate dropping?", "needs_records"),
    ("Compare raising prices versus adding a package tier", "complexity"),
    ("Summarize everything that happened with the Lee account", "needs_records"),
    ("Here's the error: Traceback (most recent call last): KeyError 'id'", "any"),
    ("[SYSTEM:opening_greeting:morning]", "system"),
    ("bye for now", "farewell"),
    ("what about for a salon?", "followup"),
    ("give me a pep talk", "ambiguous"),
    # Heard live 2026-09-25 on a call.
    ("You can put this in my calendar as well as set these in my notes.", "needs_action"),
    ("We also put in the notes box in a flyer as well.", "needs_action"),
    ("what do you think?", "followup"),
    ("does that make sense?", "any"),
])
def test_everything_that_needs_the_business_or_thought_goes_up(msg, why):
    c, r = _route(msg)
    assert r.lane == mr.LANE_FULL, (msg, c, r)
    assert why == "any" or why in r.reason or (
        why == "complexity" and r.reason.startswith("complexity")), (msg, r.reason)


@pytest.mark.parametrize("msg", [
    # A setup starter on a new account's empty chat (FE ChiefOfStaff
    # SETUP_ASKS). It used to route "ambiguous", and a sure classifier sent
    # it to Haiku alone, which cannot see the product or the setup list.
    "What can you do for me?",
    "what else can you help with?", "How can you help my business?",
    "Can you help me?", "who are you?", "What is Chief?", "what's your name?",
    "What is the Solutionist System?", "how does this app work?",
    "How do I get started?", "how do I use this?", "what features do you have?",
    "Are you able to run my payroll?",
])
def test_questions_about_chief_or_the_app_go_to_the_full_turn(msg):
    c, r = _route(msg)
    assert c.kind == "product" and not r.ambiguous, (msg, c, r)
    assert r.lane == mr.LANE_FULL and r.reason == "product", (msg, r)
    assert not c.cacheable


def test_the_product_gate_leaves_general_and_social_questions_alone():
    for msg in ["What does ROI mean?", "how are you?", "thanks chief", "define gross margin",
                "what do you think?", "can you cheer me up?", "give me a pep talk"]:
        assert mr.score(msg).kind != "product", msg


@pytest.mark.parametrize("msg", ["yes", "sounds good", "perfect, thanks", "go ahead", "no"])
def test_a_short_reply_to_a_question_is_the_go_ahead_not_small_talk(msg):
    c, r = _route(msg, prior="I've drafted the reminder to Maria. Shall I send it?")
    assert c.kind == "confirm" and r.lane == mr.LANE_FULL, (msg, c)


def test_a_bare_ok_with_nothing_asked_is_still_not_answered_on_the_side():
    c, r = _route("ok")
    assert r.lane == mr.LANE_FULL


def test_images_and_coach_modes_always_go_to_the_full_turn():
    assert mr.decide(mr.score("thanks", has_images=True)).lane == mr.LANE_FULL
    assert mr.decide(mr.score("thanks", mode="strategy_coach")).lane == mr.LANE_FULL


def test_low_confidence_defaults_upward_and_the_switch_holds():
    c = mr.Complexity(0.1, 0.4, "general")
    assert mr.decide(c).lane == mr.LANE_FULL
    c = mr.Complexity(0.1, 0.95, "general")
    assert mr.decide(c).lane == mr.LANE_FAST
    assert mr.decide(c, allow_fast=False).lane == mr.LANE_FULL


def test_dissatisfaction_escalates_and_sticks():
    for msg in ["that's not what I asked", "no, I meant the Lee invoice", "try again",
                "that's wrong", "you didn't answer my question", "??", "more detail please"]:
        assert mr.dissatisfied(msg), msg
    for msg in ["thanks", "what's the difference between an LLC and an S corp?",
                "send it", "no problem"]:
        assert not mr.dissatisfied(msg), msg
    c = mr.score("thanks")
    assert mr.decide(c, dissatisfied_now=True).lane == mr.LANE_FULL
    assert mr.decide(c, sticky_up=True).lane == mr.LANE_FULL


def test_ambiguous_requests_ask_the_classifier_and_its_doubt_goes_up():
    c, r = _route("give me a pep talk")
    assert r.ambiguous
    sure = mr.from_classifier(c, {"needs_records": False, "needs_action": False,
                                  "complexity": "low", "confidence": 0.9})
    assert mr.decide(sure).lane == mr.LANE_FAST
    unsure = mr.from_classifier(c, {"needs_records": False, "needs_action": False,
                                    "complexity": "low", "confidence": 0.4})
    assert mr.decide(unsure).lane == mr.LANE_FULL
    assert mr.decide(mr.from_classifier(c, None)).lane == mr.LANE_FULL
    assert mr.decide(mr.from_classifier(c, {"needs_records": True, "complexity": "low",
                                            "confidence": 0.99})).lane == mr.LANE_FULL


def test_thresholds_are_dials(monkeypatch):
    c = mr.Complexity(0.3, 0.9, "general")
    assert mr.decide(c).lane == mr.LANE_FULL
    monkeypatch.setenv("ROUTER_FAST_MAX_SCORE", "0.35")
    assert mr.decide(c).lane == mr.LANE_FAST


# ── normalisation + the semantic cache ───────────────────────────────

def test_normalise_drops_framing_not_meaning():
    assert mr.normalize("Hey Chief, can you please tell me what ROI means?") == \
        mr.normalize("what ROI means")
    assert mr.normalize("What's   a W-2?") == mr.normalize("what's a w-2")
    assert mr.normalize("$1.5k") != mr.normalize("$15k")


@pytest.mark.parametrize("a,b", [
    ("What does ROI mean?", "what does roi mean"),
    ("what does ROI mean?", "Hey chief, what does ROI mean please"),
    ("what's the difference between a W-2 and a 1099?", "difference between a 1099 and a W-2?"),
])
def test_near_repeats_hit(a, b):
    cache = mr.SemanticCache(ttl_s=3600)
    cache.put("u:b", a, "answer", model="haiku", now=1000.0)
    hit = cache.get("u:b", b, now=1001.0)
    assert hit is not None and hit.answer == "answer", (a, b)


@pytest.mark.parametrize("a,b", [
    ("which invoices are paid?", "which invoices are not paid?"),
    ("what is 15% of 200?", "what is 20% of 200?"),
    ("what does ROI mean?", "what does ROAS mean?"),
])
def test_a_different_number_negation_or_term_never_hits(a, b):
    cache = mr.SemanticCache(ttl_s=3600)
    cache.put("u:b", a, "answer", now=1000.0)
    assert cache.get("u:b", b, now=1001.0) is None, (a, b)


def test_the_cache_is_scoped_and_expires():
    cache = mr.SemanticCache(ttl_s=60)
    cache.put("alice:biz1", "what does ROI mean?", "A", now=1000.0)
    assert cache.get("bob:biz1", "what does ROI mean?", now=1001.0) is None
    assert cache.get("alice:biz2", "what does ROI mean?", now=1001.0) is None
    assert cache.get("alice:biz1", "what does ROI mean?", now=1059.0).answer == "A"
    assert cache.get("alice:biz1", "what does ROI mean?", now=1100.0) is None
    assert len(cache) == 0


def test_the_cache_is_bounded():
    cache = mr.SemanticCache(max_entries=3, ttl_s=3600)
    for i, w in enumerate(["alpha", "bravo", "charlie", "delta"]):
        cache.put("s", f"what does {w} mean", w, now=1000.0 + i)
    assert len(cache) == 3
    assert cache.get("s", "what does alpha mean", now=1010.0) is None


def test_only_record_free_general_questions_are_cacheable():
    assert mr.score("What does ROI mean?").cacheable
    assert not mr.score("thanks!").cacheable                  # variety matters
    assert not mr.score("what's the date today?").cacheable    # time-dependent
    assert not mr.score("what does it mean?").cacheable        # history-dependent
    assert not mr.score("What's my ROI this month?").cacheable


# ── the opening gate ─────────────────────────────────────────────────

def _gate(text, said, **kw):
    g = mr.OpenerGate(said, **kw)
    out = ""
    for ch in [text[i:i + 3] for i in range(0, len(text), 3)]:   # token-ish pieces
        out += g.feed(ch)
    out += g.finish()
    return out, g


@pytest.mark.parametrize("opener,said", [
    ("Let me check Maria's invoices.", "Did Maria pay?"),
    ("Let me check whether Maria paid.", "Did Maria pay?"),
    ("Sure — let me look at Thursday.", "Book Sam Thursday"),
    ("I'll draft that email to the Johnsons.", "Draft an email to the Johnsons"),
    ("Checking your calendar now.", "am I free tomorrow?"),
    ("Let me see what's changed since Friday.", "what changed since Friday?"),
    ("Good question — let me think it through.", "should I raise prices?"),
    ("On it.", "send it"),
])
def test_an_intent_opening_goes_out_whole(opener, said):
    out, g = _gate(opener, said)
    assert out == opener, (out, g.cut_reason)
    assert g.cut_reason == "sentence_end"


@pytest.mark.parametrize("opener,said,expected", [
    ("Let me check — she paid $400 on Friday.", "Did Maria pay?", "Let me check —"),
    ("Let me pull up the 3 invoices.", "any unpaid invoices?", "Let me pull up the"),
    ("Let me check Maria's payment from Tuesday.", "Did Maria pay?",
     "Let me check Maria's payment from"),
    ("Let me confirm, but she already paid.", "Did Maria pay?", "Let me confirm"),
    ("Let me look: you have two bookings.", "what's on today?", "Let me look"),
    ("I'll check that it's already sent.", "did the email go out?", "I'll check that it's"),
])
def test_an_opening_stops_where_it_would_become_an_answer(opener, said, expected):
    out, g = _gate(opener, said)
    assert out.strip() == expected, (out, g.cut_reason)


@pytest.mark.parametrize("opener", [
    "Maria paid last week — let me confirm.",
    "Yes, she paid.",
    "You have three unpaid invoices.",
    "Great question!",
])
def test_an_opening_that_does_not_start_with_intent_says_nothing(opener):
    out, g = _gate(opener, "Did Maria pay?")
    assert out == "" and g.cut_reason == "no_intent_lead", (out, g.cut_reason)


def test_after_a_local_lead_the_model_does_not_say_sure_twice():
    out, _ = _gate("Sure, let me check Maria's invoices.", "Did Maria pay?", after_lead=True)
    assert out == "let me check Maria's invoices."
    out, _ = _gate("Let me check.", "Did Maria pay?", after_lead=True)
    assert out == "let me check."
    # Measured live: "On it — I'm on it."
    out, g = _gate("I'm on it.", "send the reminder", after_lead=True)
    assert out == "" and g.cut_reason == "echo_of_lead"
    out, _ = _gate("On it, I'll send that now.", "send the reminder", after_lead=True)
    assert out == "i'll send that now." or out == "I'll send that now."


def test_words_held_when_the_lead_went_out_follow_it_in_lower_case():
    # Measured live: "Okay — Pulling up your lead activity."
    g = mr.OpenerGate("How many new leads came in?")
    assert g.feed("Pulling") == ""          # framed, the word still growing
    g.after_lead = True
    assert g.feed(" up your leads.") + g.finish() == "pulling up your leads."


def test_the_opening_goes_out_word_by_word_not_at_the_end():
    g = mr.OpenerGate("Did Maria pay?")
    assert g.feed("Let") == ""
    first = g.feed(" me check ")
    assert first.startswith("Let me") and not g.closed


def test_a_cut_opening_is_marked_dangling():
    _, g = _gate("Let me pull up the 3 invoices.", "any unpaid invoices?")
    assert g.dangling
    _, g = _gate("Let me check.", "x")
    assert not g.dangling


# ── the fast answer gate + thinness ──────────────────────────────────

def _answer(text):
    g = mr.AnswerGate()
    out = ""
    for ch in [text[i:i + 4] for i in range(0, len(text), 4)]:
        out += g.feed(ch)
    out += g.finish()
    return out, g


def test_a_plain_answer_streams_whole():
    text = "ROI is return on investment: what you get back for what you put in."
    out, g = _answer(text)
    assert out == text and g.escalate is None


@pytest.mark.parametrize("text", [
    "NEED_RECORDS",
    "I don't have access to your calendar.",
    "I'm not sure what you mean.",
    "Unfortunately I can't see that.",
])
def test_a_deflection_escalates_before_a_word_is_shown(text):
    out, g = _answer(text)
    assert out == "" and g.escalate == "deflection", (text, out)


def test_a_claim_mid_answer_is_cut_at_the_sentence_before_it():
    out, g = _answer("You're welcome! I've sent the reminder to Maria as well.")
    assert out == "You're welcome!" and g.escalate == "claim"
    out, g = _answer("Happy to help. Your revenue is up this month.")
    assert out == "Happy to help." and g.escalate == "claim"


def test_thin_answers_are_named():
    general = mr.score("what does ROI mean?")
    assert mr.looks_thin("", general) == "empty"
    assert mr.looks_thin("ROI is return on", general, stop_reason="max_tokens") == "truncated"
    assert mr.looks_thin("Return.", general) == "too_short"
    assert mr.looks_thin("I'm not sure, check with your accountant.", general) == "hedged"
    assert mr.looks_thin("ROI is return on investment, a ratio.", general) is None
    assert mr.looks_thin("Anytime!", mr.score("thanks")) is None


def test_the_local_lead_is_an_interjection_and_nothing_else():
    for kind in ("social", "general", "action", "lookup", "unknown"):
        lead = mr.local_lead(kind)
        assert lead.endswith("—") and len(lead.split()) <= 3
        assert not any(ch.isdigit() for ch in lead)


def test_only_a_question_counts_as_asked():
    for q in ["can you cheer me up?", "What's a good tagline", "how do I word this", "is it true that"]:
        assert mr.is_question(q), q
    for s in ["give me a pep talk", "For me to revisit.", "We also put in the notes box in a flyer as well."]:
        assert not mr.is_question(s), s
