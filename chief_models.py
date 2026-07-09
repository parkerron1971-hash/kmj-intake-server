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
    "voice": 700,
}


def model_for(lane: str) -> str:
    """Model ID for a lane; unknown lanes fall back to chat."""
    key = (lane or "chat").strip().lower()
    if key not in _LANE_DEFAULTS:
        key = "chat"
    env = (os.environ.get(f"CHIEF_MODEL_{key.upper()}") or "").strip()
    return env or _LANE_DEFAULTS[key]


def lane_for_chat(mode: str = "", client_surface: str = "") -> str:
    """Pick the lane for a /agents/chief/chat turn."""
    if (mode or "") == "strategy_coach":
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
- If the full answer genuinely needs a screen (long lists, tables), do the essential part now and say the rest is on their screen.
"""
