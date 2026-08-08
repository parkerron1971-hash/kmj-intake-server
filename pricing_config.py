"""
pricing_config.py — every credit dial in one place, all env-overridable.

THE RULE THIS MODULE EXISTS TO ENFORCE (Kevin, 2026-08-08): we launch on
config-driven opening defaults and refine against real data once the
meter works. So NO price, grant, or ceiling is hardcoded at its call
site — tuning must be a Railway value change plus a restart, never a
code deploy.

Every accessor reads os.environ at CALL TIME, not import time. That is
deliberate twice over: a Railway variable edit lands on the next restart
with no rebuild, and tests can monkeypatch a single value without
reimporting half the app.

═══════════════════════════════════════════════════════════════════════
THE OPENING DEFAULTS (Kevin's ruling 2026-08-08)
═══════════════════════════════════════════════════════════════════════

Builds are priced off a deliberately conservative ~$2.00 assumed cost —
above the ~$1.82 the ATELIER_MODEL routing fix actually lands at, on
purpose, for hidden margin — at roughly 3x markup, sized so one build is
20% of the Starter tank (3,000 -> 2,400 left). Fixes and docs hold the
same ~3x against their real cost. The chat ceiling is the one genuine
risk dial: chat p95 is 19.84c and rising, so 250 turns/day is a
watch-it-closely number for month one, not a settled price.

These are OPENING defaults. They are expected to move once the meter has
run against real customers. That is the point of the module.

═══════════════════════════════════════════════════════════════════════
ENV NAMES
═══════════════════════════════════════════════════════════════════════

Each dial accepts Kevin's bare name (BUILD_BASE) and a namespaced alias
(PRICE_BUILD_BASE / CREDITS_STARTER). The namespaced form is checked
FIRST and is the one to prefer in Railway — bare names like SMALL_EDIT
and DOC_GEN are collision-prone in a shared environment. Both work, so
existing notes and runbooks keep reading correctly.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger("pricing_config")


def _int_env(names: List[str], default: int) -> int:
    """First env name that parses as an int wins; otherwise the default.

    Fails SAFE and LOUD: a typo'd value ("6oo") logs a warning and falls
    back to the shipped default rather than raising at request time or —
    worse — silently pricing an action at zero."""
    for name in names:
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            logger.warning(
                f"[pricing] {name}={raw!r} is not an integer — "
                f"falling back to default {default}")
    return default


def _dial(bare: str, prefix: str, default: int) -> int:
    return _int_env([f"{prefix}{bare}", bare], default)


# ─── Tier grants — monthly included credits ──────────────────────────
# Replaces the 300/1000/3000 allowances from the 2026-07-12 spec. The
# ~10x rescale is what makes per-action pricing expressible: at 300, a
# single build priced at 600 would have been impossible.

def starter_credits() -> int:
    return _dial("STARTER_CREDITS", "CREDITS_", 3000)


def pro_credits() -> int:
    return _dial("PRO_CREDITS", "CREDITS_", 10000)


def practice_credits() -> int:
    return _dial("PRACTICE_CREDITS", "CREDITS_", 25000)


def tier_credits() -> Dict[str, int]:
    """plan key -> monthly included credits. Keys match feature_gates.PLANS."""
    return {
        "starter":      starter_credits(),
        "professional": pro_credits(),
        "practice":     practice_credits(),
    }


# ─── Action prices ───────────────────────────────────────────────────

def build_base() -> int:
    """A build's fixed price, before per-section. ~3-section build = 600
    at the opening defaults = 20% of the Starter tank."""
    return _dial("BUILD_BASE", "PRICE_", 600)


def build_per_section() -> int:
    """Charged per composed section ON TOP of build_base."""
    return _dial("BUILD_PER_SECTION", "PRICE_", 100)


def revamp_price() -> int:
    """A recompose of an existing site (compose_site refine=True) — flat,
    not base+per-section, because the spec is already authored."""
    return _dial("REVAMP_PRICE", "PRICE_", 300)


def section_rewrite() -> int:
    """One standalone Studio section rewrite. In-build atelier calls are
    FREE (units=0) — the build marker already carries their cost."""
    return _dial("SECTION_REWRITE", "PRICE_", 120)


def small_edit() -> int:
    return _dial("SMALL_EDIT", "PRICE_", 40)


def hero_regen() -> int:
    return _dial("HERO_REGEN", "PRICE_", 30)


def doc_gen() -> int:
    return _dial("DOC_GEN", "PRICE_", 40)


def chat_price() -> int:
    """One Chief turn. The unit everything else is denominated against."""
    return _dial("CHAT_PRICE", "PRICE_", 1)


def concierge_price() -> int:
    """One customer-facing website reply — same rate as a Chief turn."""
    return _dial("CONCIERGE_PRICE", "PRICE_", 1)


def premium_voice_price() -> int:
    """ElevenLabs spoken chunk. Standard OpenAI TTS stays free (0)."""
    return _dial("PREMIUM_VOICE_PRICE", "PRICE_", 1)


# ─── Chat fair-use ───────────────────────────────────────────────────

def chat_daily_soft_ceiling() -> int:
    """Chief turns per business per UTC day before the fair-use brake
    engages. ABUSE-ONLY: at 250/day a human practitioner will never see
    it — sustained traffic above this is a script or a runaway loop.

    0 disables the brake entirely."""
    return _dial("CHAT_DAILY_SOFT_CEILING", "LIMIT_", 250)


def chat_ceiling_enforced() -> bool:
    """Whether the fair-use brake actually blocks.

    DELIBERATELY INDEPENDENT OF BILLING_ENFORCE (flagged to Kevin
    2026-08-08): this is abuse protection, not billing. Gating it behind
    the billing flag would make it a no-op on the day it ships — dead
    weight by the repo's own rule — and would leave the platform's only
    per-account runaway brake switched off during exactly the beta month
    it was built for. CHAT_CEILING_ENFORCE=off disables blocking while
    still logging every trip, if the brake ever proves too eager."""
    return (os.environ.get("CHAT_CEILING_ENFORCE") or "on").strip().lower() in (
        "on", "1", "true")


# ─── Notification thresholds ─────────────────────────────────────────

def usage_thresholds() -> tuple:
    """% of allotment that fires a usage notification, once each per month."""
    raw = (os.environ.get("USAGE_THRESHOLDS") or "").strip()
    if raw:
        try:
            vals = tuple(int(p) for p in raw.split(",") if p.strip())
            if vals:
                return vals
        except ValueError:
            logger.warning(f"[pricing] USAGE_THRESHOLDS={raw!r} unparseable "
                           f"— using the default ladder")
    return (50, 80, 100, 200)


def low_credit_pct() -> int:
    """Combined remaining (allowance + packs) at/below this % of cycle
    capacity fires the soft 'running low' nudge."""
    return _dial("LOW_CREDIT_PCT", "LIMIT_", 20)


# ─── The endpoint -> price table ─────────────────────────────────────
#
# ONE HARD LESSON ENCODED HERE (the /director/build weight hole, 7/30):
# every key below is an endpoint string something in this repo ACTUALLY
# logs. Verified against `grep -rho 'endpoint="/[^"]*"'` on 2026-08-08.
# A key that matches no logged label is not a price — it is a silent
# zero. If you add a price, add the logging line in the same PR.
#
# Endpoint keys are the FALLBACK. Any api_usage row carrying an explicit
# `units` value overrides this table (see usage_metering.weight_for_row)
# — that is what makes base+per-section, revamp-vs-build, and
# in-build-vs-standalone atelier expressible at all.

def unit_weights() -> Dict[str, int]:
    build = build_base()
    return {
        # ── The billable markers ──
        # A full site build. Rows normally carry explicit units
        # (base + sections x per_section); this is the floor for any
        # marker row written before the units column existed.
        "/composer/compose": build,
        "/director/build": build,        # legacy engine marker, old rows

        # ── Per-action prices ──
        "/composer/hero": hero_regen(),
        "/composer/atelier": section_rewrite(),
        "/site/design-intent": small_edit(),
        "/doctemplates/compose": doc_gen(),
        "/doctemplates": doc_gen(),
        "/docintel": doc_gen(),
        "/concierge/reply": concierge_price(),
        "/composer/coach/turn": chat_price(),

        # ── Build internals: FREE. The marker carries the whole bill. ──
        # Charging these too would double-bill every build.
        "/composer/canvas": 0,
        "/composer/canvas-review": 0,
        "/composer/builder-v2": 0,
        "/composer/builder-v2-eyes": 0,
        "/composer/spec": 0,
        "/composer/drl/dro": 0,
        "/composer/drl/dro_minimal": 0,
        "/composer/drl/signals": 0,
        "/vision/grade": 0,

        # ── Voice ──
        "/ai/tts": 0,                    # standard TTS included with every plan
        "/ai/tts-el": premium_voice_price(),
        "/ai/whisper": 0,                # transcription rides the turn it feeds

        # ── Infrastructure, never billed ──
        "/gate/embed": 0,
        "/doctemplates/learn": 0,
        "/doctemplates/state_notes": 0,
    }


DEFAULT_WEIGHT = 1


# ─── Credit packs ────────────────────────────────────────────────────
#
# ⚠ FLAGGED TO KEVIN, NOT CHANGED (2026-08-08). These units were RULED
# in the Pricing v2 spec (§7) against the OLD 300/1000/3000 tank, and I
# do not silently overwrite a ruling. At the new 3,000/10,000/25,000
# scale they no longer cohere:
#
#   $10 / 100u   — cannot buy one section rewrite (120)
#   $25 / 275u   — cannot buy one build (600)
#   $50 / 600u   — buys exactly one build, nothing left over
#
# A top-up that cannot complete a single action is a bad checkout. The
# defaults below are the ruled numbers, unchanged; the env names are
# live, so a decision is a value change. Roughly 10x (1000/2750/6000)
# would restore the original intent — Kevin's call.

def credit_packs() -> Dict[str, Dict[str, int]]:
    return {
        "small":  {"cents": _dial("PACK_SMALL_CENTS", "PRICE_", 1000),
                   "units": _dial("PACK_SMALL_UNITS", "PRICE_", 100)},
        "medium": {"cents": _dial("PACK_MEDIUM_CENTS", "PRICE_", 2500),
                   "units": _dial("PACK_MEDIUM_UNITS", "PRICE_", 275)},
        "large":  {"cents": _dial("PACK_LARGE_CENTS", "PRICE_", 5000),
                   "units": _dial("PACK_LARGE_UNITS", "PRICE_", 600)},
    }


# ─── Introspection ───────────────────────────────────────────────────

def snapshot() -> Dict[str, object]:
    """Every live dial in one payload — for /billing/config, Mission
    Control, and 'what is this instance actually charging?' at 2am."""
    return {
        "tier_credits": tier_credits(),
        "prices": {
            "build_base": build_base(),
            "build_per_section": build_per_section(),
            "revamp": revamp_price(),
            "section_rewrite": section_rewrite(),
            "small_edit": small_edit(),
            "hero_regen": hero_regen(),
            "doc_gen": doc_gen(),
            "chat": chat_price(),
            "concierge": concierge_price(),
            "premium_voice": premium_voice_price(),
        },
        "chat_daily_soft_ceiling": chat_daily_soft_ceiling(),
        "chat_ceiling_enforced": chat_ceiling_enforced(),
        "low_credit_pct": low_credit_pct(),
        "usage_thresholds": list(usage_thresholds()),
        "credit_packs": credit_packs(),
    }
