# growth_doctrine.py
# ─────────────────────────────────────────────────────────────────────
# THE GROWTH DOCTRINE — marketing law for Chief.
#
# The sibling of design_doctrine.py. That module gives the composer a
# fixed set of laws for how a page should LOOK; this one gives Chief a
# fixed set of laws for how a business should be GROWN. Both are
# hand-authored, deterministic, and cost nothing to produce — no LLM
# call, no table, no per-business state.
#
# WHY A DOCTRINE AND NOT A KNOWLEDGE PACK: marketing advice ages, and
# tactic libraries are lookup tables — they encode one industry's moves
# as if they were universal (the "$7 tripwire" that is malpractice for a
# lawyer and tone-deaf for a church). Laws are rubrics. They tell Chief
# HOW to reason about a business it has never seen, in a vertical nobody
# wrote a chapter for. Per-vertical restraint lives in
# vertical_intelligence.py, where the voice/taboo data already lives —
# never here.
#
# NOT chief_playbook.py. That name is taken and it means the opposite
# thing: a per-business brief DISTILLED BY AN LLM from what the platform
# has learned (WHO THIS IS / WHAT WORKS / ...). This module is fixed law
# that is byte-identical for every tenant.
#
# THE GATE (see context_block below): the doctrine is injected only on
# marketing-shaped turns. An always-on block would (a) spend ~700 tokens
# on every bookkeeping question and (b) repeat the 2026-07-16 coach-mode
# leak, where per-turn injectors that were not gated on mode showed up
# inside a persona that should never have seen them.
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

import os
import re
from typing import Optional


DOCTRINE = """THE GROWTH DOCTRINE (marketing law for every growth decision you make)

G1 THE LADDER, NOT THE PUSH. Every business has four rungs: a free
proof (costs a stranger nothing), a first paid step (small, low-risk),
the core offer (the real work), and depth (the thing that repeats).
Before proposing any tactic, work out which rung is missing. A business
with only a core offer does not have a traffic problem.
G2 THE ASK FITS THE DISTANCE. Never met you / gave you an email /
bought once / bought repeatedly are four different people. An ask sized
for the wrong one reads as desperate and is refused for that reason
alone, not because the offer was bad.
G3 DIAGNOSIS BEFORE PRESCRIPTION. Traffic, capture, conversion, and
retention are four different diseases. Read the numbers in the context
above before naming a cure. If the numbers are not there, say which one
you would need rather than guessing.
G4 NAME THE ONE MOVE. One next move, the reason for it, and a size that
fits this week. A list of five options is a way of doing none of them.
G5 OWNED BEATS RENTED. Every content or social move ends in something
the practitioner keeps — a contact, a list, a booking. An audience on a
platform they do not control is a loan that can be called.
G6 THE FIRST LINE IS THE WHOLE ASK. Subject lines, headlines, first
sentences, opening texts: the only job is to earn the second line. Never
open with the business name — nobody is looking for it yet.
G7 SO WHAT, TWICE. Every feature answers "so what?" twice before it
ships as copy. "Twelve sessions" → so what → "a full quarter of
accountability" → so what → "you stop starting over every January."
G8 SPECIFIC BEATS CLEVER. A real number, a real name, a real Tuesday
beats a polished abstraction. Cleverness is what people write when they
have not decided what they are actually saying.
G9 DEPOSIT BEFORE WITHDRAWAL. Value comes before the ask, in every
channel. A list that only ever hears pitches stops being a list, and the
damage shows up two months after the send that caused it.
G10 ONE PERSON PER PIECE. Written to one named someone, never to a
segment. If the practitioner cannot say who it is for, the piece is not
ready to write.
G11 REAL OR REMOVED. Never invent results, proof, numbers, or claims to
make copy stronger. If the proof does not exist, the sentence goes.
(System rule #2 and design doctrine D10 govern; this doctrine may never
override them.)
G12 SUGGEST ONLY WHAT YOU CAN DO. Never propose a move that has no verb
behind it in this system. If the right move genuinely lives outside what
you can do, say so plainly and say what you CAN do toward it — but never
leave the practitioner holding an instruction with no way to act on it."""


# The ladder is the load-bearing frame in G1, so it gets its own block —
# but stated as ROLES, never as an industry's tactics. The same four
# rungs read correctly for a coach, a law firm, and a congregation; the
# examples exist to show that the roles are structural, not to be copied.
LADDER = """THE FOUR RUNGS (how to read a business's offers)

FREE PROOF — costs a stranger nothing and proves you are worth money.
ENTRY — the first small paid step. Low risk, real value, fast.
CORE — the main engagement. Where the business actually earns.
DEPTH — the thing that repeats: retainer, membership, ongoing giving.

The roles are structural, so they hold across every kind of business:
a coach's rungs might be a discovery call / a single session / a 12-week
program / a retainer, a firm's a consultation / a flat-fee document /
representation / ongoing counsel, a congregation's a first visit / a
class / membership / recurring giving. Read the practitioner's OFFERINGS
in the context above and infer which rungs exist. Name a missing rung as
an observation, not a verdict, and never invent an offer they have not
agreed to — proposing one is create_offering, and that is their call."""


# ─── The gate ────────────────────────────────────────────────────────
#
# Precision over recall, deliberately. A false positive spends ~700
# tokens and drags a marketing frame into a turn about an invoice; a
# false negative just means Chief answers the way it does today. Broad
# words are therefore NOT triggers on their own — "grow", "sell",
# "clients", "customers", "offer", "post", "content" all appear
# constantly in ordinary operational conversation. They qualify only in
# the multi-word forms below.
_TRIGGERS = (
    # unambiguous nouns of the trade
    "marketing", "campaign", "funnel", "lead magnet", "newsletter",
    "email list", "mailing list", "subscribers", "landing page",
    "sales page", "opt-in", "optin", "headline", "subject line",
    "tagline", "copywriting", "ad copy", "call to action", "cta",
    "seo", "open rate", "click rate", "conversion rate", "drip",
    "nurture sequence", "referral program", "content calendar",
    "brand awareness", "cold outreach", "cold email", "promo code",
    # advertising
    "advertise", "advertising", "run ads", "facebook ads", "instagram ads",
    "google ads", "paid ads", "ad spend", "boost a post",
    # the problem, as a practitioner actually says it
    "more clients", "more customers", "more members", "more leads",
    "more bookings", "get the word out", "no one is booking",
    "nobody is booking", "not converting", "not getting leads",
    "slow month", "slow season", "drum up business", "fill my calendar",
    "grow my list", "grow the list", "build an audience", "reach more",
    "attract more", "bring in more", "word of mouth",
    # the act, in unambiguous multi-word form
    "how do i sell", "how should i sell", "how do i promote",
    "promote my", "promote the", "market my", "market the",
    "market myself", "pricing strategy", "raise my prices",
)

# Surfaces that ARE the marketing room. Arriving here with any question
# is enough — the practitioner is already looking at the funnel.
_TRIGGER_VIEWS = frozenset({
    "campaigns", "funnel", "marketing", "growth", "audience",
})

# Personas that must never receive operational law. Strategy Coach is
# structurally excluded already (it returns a different prompt entirely),
# but the 2026-07-16 leak happened precisely because a gate that "could
# not be reached" was reached. Defense in depth.
_EXCLUDED_MODES = frozenset({"strategy_coach"})

_WORD_RE = re.compile(r"[^a-z0-9]+")


def _enabled() -> bool:
    return (os.environ.get("GROWTH_DOCTRINE") or "on").strip().lower() != "off"


def _normalize(text: str) -> str:
    """Lowercase and collapse punctuation to single spaces, padded, so a
    trigger phrase matches on word boundaries without a regex per term.
    'Ads?' and 'ads,' both become ' ads '."""
    return " " + _WORD_RE.sub(" ", (text or "").lower()).strip() + " "


def is_growth_turn(message: str, tab: Optional[str] = None,
                   sub_tab: Optional[str] = None) -> bool:
    """True when this turn is marketing-shaped and the doctrine should
    load. Pure function — no I/O, no LLM, safe to call every turn."""
    if (sub_tab or "").strip().lower() in _TRIGGER_VIEWS:
        return True
    if (tab or "").strip().lower() in _TRIGGER_VIEWS:
        return True
    haystack = _normalize(message)
    return any(f" {t} " in haystack for t in
               (_normalize(x).strip() for x in _TRIGGERS))


def context_block(message: str, mode: Optional[str] = None,
                  tab: Optional[str] = None,
                  sub_tab: Optional[str] = None) -> str:
    """The ready-to-inject prompt block, or '' when this turn should not
    carry it. Belongs in the DYNAMIC tail (after [[CHIEF_CACHE_SPLIT]]):
    it varies per turn, so placing it in a cached segment would break the
    prefix on every toggle. Fail-open — never raises."""
    try:
        if not _enabled():
            return ""
        if (mode or "").strip() in _EXCLUDED_MODES:
            return ""
        if not is_growth_turn(message, tab=tab, sub_tab=sub_tab):
            return ""
        return DOCTRINE + "\n\n" + LADDER + "\n"
    except Exception:  # pragma: no cover — a gate must never break a turn
        return ""


def with_growth_doctrine(system_prompt: str) -> str:
    """Prepend the doctrine to a stage's system prompt — the same shape
    as design_doctrine.with_doctrine, for the site-copy stages, which are
    written under no marketing law today. Unconditional by design: a copy
    stage is a marketing turn, so there is nothing to classify."""
    if not _enabled():
        return system_prompt
    return DOCTRINE + "\n\n" + LADDER + "\n\n" + system_prompt
