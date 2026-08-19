"""
chief_models.py — Chief Layers arc (2026-07-09)

ONE place that decides which Claude model each Chief lane runs on.
Before this module the IDs were hardcoded constants scattered across
chief_of_staff / chief_llm / platform_console — changing Chief's brain
meant a grep hunt. Now every lane is named, defaulted, and
env-overridable without a deploy diff.

Lanes:
  chat        typed conversation — the everyday Chief turn.
  voice       spoken conversation. SAME model as chat ON PURPOSE:
              prompt caching is per-model, and voice + text share the
              same cached UNIVERSAL/per-business prefix. Splitting the
              models would double cache writes and cold-start every
              voice session. Voice differences (short spoken replies,
              smaller token budget) are handled at the call site, not
              by swapping the brain.
  deep        Strategy Coach sessions + future heavy-reasoning turns.
              Coach sessions are long and multi-turn, so they amortize
              their own (per-model) prompt cache.
  draft       inner draft calls (_draft_short — nurture/email drafts in
              the practitioner's voice). Kevin's 2026-07-03 ruling:
              drafts ride the conversational tier, so quality of the
              words that reach clients never drops. Env-switchable if
              that ruling ever changes.
  insight     the weekly longitudinal synthesis (chief_insights.py).
              Low volume — a handful of calls per business per week —
              so it gets the strongest model.
  background  mechanical work: classification, consolidation,
              summarization. Cheap and fast.

Override any lane with CHIEF_MODEL_<LANE>, e.g. CHIEF_MODEL_DEEP.
NOTE: Sonnet 5 / Opus 4.8 / Fable reject the `temperature` param
(see model_ladder.supports_sampling) — callers here don't send it.
"""
from __future__ import annotations

import os

_LANE_DEFAULTS = {
    "chat":       "claude-sonnet-5",
    "voice":      "claude-sonnet-5",
    "deep":       "claude-opus-4-8",
    "draft":      "claude-sonnet-5",
    "insight":    "claude-opus-4-8",
    "background": "claude-haiku-4-5-20251001",
}

# Per-lane reply budgets. Voice is deliberately tight: replies are read
# aloud by TTS, so 700 tokens ≈ the ceiling of a listenable answer —
# faster to first audio AND cheaper per turn. Coach deliverables
# (save_packages / save_launch_plan) can be large, hence 2400.
_LANE_MAX_TOKENS = {
    "deep":  2400,
    # 700 was set when a voice reply was ONLY spoken words, and ~110 of
    # them fit with room to spare. It stopped being true the day Chief
    # could put things on screen: an [ACTION:] tag is emitted in the
    # same completion as the reply and usually AFTER it, so a rich one
    # — an 8-step show_plan, a 4-block show_readout — ran the budget out
    # mid-JSON. The parser drops a truncated tag, so the practitioner
    # heard "here, look at this" and nothing appeared.
    #
    # This ceiling does not make replies longer; the prompt still asks
    # for under ~110 words. It only stops the tag being cut off.
    "voice": 1400,
}


# Pricing v2 model ladder (Kevin's ruling 2026-07-12, spec §4): the
# HEAVY lanes (deep/insight) scale with the plan tier — Starter thinks
# on Sonnet 5, Professional on Opus 4.8, Practice/Elite on Fable 5.
# chat/voice/draft stay Sonnet 5 for EVERY tier on purpose: latency,
# and the shared per-model prompt cache (splitting would cold-start
# every conversation). Env overrides (CHIEF_MODEL_<LANE>) still win —
# they're the platform kill switch, not a per-tier setting.
_TIER_LADDER = {
    "starter":      "claude-sonnet-5",
    "professional": "claude-opus-4-8",
    "practice":     "claude-fable-5",
}
_LADDER_LANES = ("deep", "insight")

# Display names for the ladder, used by billing surfaces (/billing/plans
# plan_details). Keyed by model id so a ladder change flows through.
_TIER_LADDER_LABELS = {
    "claude-sonnet-5": "Claude Sonnet 5",
    "claude-opus-4-8": "Claude Opus 4.8",
    "claude-fable-5": "Claude Fable 5",
}


# Customer-facing wording for the same ladder. Kevin's ruling
# 2026-08-19: public surfaces never name vendor models — other
# providers are coming, and the promise is the CAPABILITY tier, not
# whose model happens to power it today. Owner surfaces (Mission
# Control) keep tier_deep_model_label for the real model names.
_TIER_ANALYSIS_LABELS = {
    "starter": "Standard",
    "professional": "Advanced",
    "practice": "Maximum",
}


def deep_analysis_label(plan: str | None) -> str | None:
    """Vendor-neutral deep-analysis tier for customer-facing surfaces.

    None while a CHIEF_MODEL_DEEP env override is set — with the ladder
    off every tier runs the same model, so a Standard/Advanced/Maximum
    claim would be false and the surfaces drop the line instead."""
    if (os.environ.get("CHIEF_MODEL_DEEP") or "").strip():
        return None
    return _TIER_ANALYSIS_LABELS.get((plan or "").strip().lower())


def tier_deep_model_label(plan: str | None) -> str | None:
    """The deep-lane model this tier's ladder grants, as a display name
    — for OWNER surfaces (Mission Control) only; customer surfaces use
    deep_analysis_label so vendor models are never marketed.

    None while a CHIEF_MODEL_DEEP env override is set: the override is
    the platform kill switch and wins over the ladder in model_for(), so
    a plan card must not advertise a per-tier model nobody would get."""
    if (os.environ.get("CHIEF_MODEL_DEEP") or "").strip():
        return None
    model = _TIER_LADDER.get((plan or "").strip().lower())
    return _TIER_LADDER_LABELS.get(model or "")


def model_for(lane: str, plan: str | None = None) -> str:
    """Model ID for a lane; unknown lanes fall back to chat. Pass the
    business's plan to apply the tier ladder on heavy lanes — no plan
    (beta, grandfathered, plan-less) keeps the lane default."""
    key = (lane or "chat").strip().lower()
    if key not in _LANE_DEFAULTS:
        key = "chat"
    env = (os.environ.get(f"CHIEF_MODEL_{key.upper()}") or "").strip()
    if env:
        return env
    if key in _LADDER_LANES and plan:
        tiered = _TIER_LADDER.get((plan or "").strip().lower())
        if tiered:
            return tiered
    return _LANE_DEFAULTS[key]


def lane_for_chat(mode: str = "", client_surface: str = "") -> str:
    """Pick the lane for a /agents/chief/chat turn."""
    # Both coaches ride the deep lane. The Business Coach in particular
    # needs the long turn budget: one reply can capture several offerings
    # plus profile writes alongside the conversation itself.
    if (mode or "") in ("strategy_coach", "business_coach"):
        return "deep"
    if (client_surface or "") == "voice":
        return "voice"
    return "chat"


def max_tokens_for(lane: str, default: int = 1600) -> int:
    return _LANE_MAX_TOKENS.get((lane or "").strip().lower(), default)


# Appended to the DYNAMIC tail of the system prompt (after
# [[CHIEF_CACHE_SPLIT]]) on voice turns — never to the cached prefix,
# so the cache stays byte-identical across voice and text turns.
VOICE_DELIVERY_BLOCK = """
VOICE DELIVERY — this message arrived by voice and your reply will be spoken aloud via text-to-speech:
- Keep it under ~110 words: one or two short spoken paragraphs. No markdown, no bullet lists, no headers, no emoji — they sound broken when read aloud.
- Say numbers and dates naturally ("about twelve hundred dollars", "next Tuesday").
- [ACTION:{...}] tags still work exactly as normal and are stripped before speech — emit them whenever you act, same as ever.
- If the answer wants a screen (any list, table, or set of figures), PUT IT THERE — emit the show_view tag and say the headline aloud while it lands: "Collection's at seventy-six percent — here, look at this." Never say it is on their screen without emitting the tag that puts it there; on a voice surface there is no transcript behind you, so an unaccompanied "it's on your screen" points at nothing.
- Anything that SENDS, CHARGES, DELETES or PUBLISHES holds the first time you ask for it here and comes back "HELD FOR A SPOKEN YES". That is not a failure and not a refusal — say what is about to happen, out loud, including who it goes to and any amount, then ask them to say "send it" or "go ahead". When they do, emit the same action again and it runs. NEVER say it is done while it is held; nothing has happened yet.
- Speak the shape, not the rows. Once the view is up, say what it MEANS ("three are genuinely late, about two thousand between them") — reading a table aloud is what the screen is for.
"""
