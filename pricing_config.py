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
    """A build's price INCLUDING the first build_included_sections()
    sections. At the opening defaults a typical ~3-section build is 600
    — 20% of the Starter tank, so the first build leaves plenty behind
    (3,000 -> 2,400)."""
    return _dial("BUILD_BASE", "PRICE_", 600)


def build_included_sections() -> int:
    """How many sections build_base() already covers.

    ADDED 2026-08-08 (second pass) TO MAKE KEVIN'S OWN ARITHMETIC TRUE.
    The first implementation charged base + sections x per_section for
    EVERY section, which made a 3-section build cost 900 — 30% of the
    Starter tank, not the 20% / "3,000 -> 2,400" the ruling states, and
    it left the $10 pack unable to afford a single section rewrite after
    one build. Set to 0 for a pure base-plus-every-section model."""
    return _dial("BUILD_INCLUDED_SECTIONS", "PRICE_", 3)


def build_per_section() -> int:
    """Charged per composed section BEYOND build_included_sections()."""
    return _dial("BUILD_PER_SECTION", "PRICE_", 100)


def price_for_build(sections: int) -> int:
    """What a full site build costs, given its composed section count.

    The single place this arithmetic lives — call sites must not
    re-derive it, or the two copies drift the moment a dial moves."""
    extra = max(0, int(sections or 0) - build_included_sections())
    return build_base() + extra * build_per_section()


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
    """One Chief turn.

    RAISED 1 -> 8 on 2026-08-10, against measured data rather than the
    estimate it shipped on. This module says opening defaults get refined
    once the meter works; the meter now works (#448/#450 made it record
    anything at all, #470/#471 made it record WHOSE), and 640 real turns
    say a Chief turn costs:

        mean 7.37c   p50 5.18c   p95 20.15c   max 52.55c

    At 1 credit per turn the credit stopped being a currency. A build is
    600 credits for roughly $2.00 of cost — about 0.333c of COGS per
    credit. A turn at 7.37c was being sold for one credit, which is 22x
    more expensive per credit than a build. A customer spending their
    whole tank on conversation cost, against what they paid:

        starter   3,000 turns   $221 COGS   vs $79     2.8x
        pro      10,000 turns   $737 COGS   vs $199    3.7x
        practice 25,000 turns $1,842 COGS   vs $399    4.6x

    WHY 8 AND NOT 22

    Strict parity with the build's implied credit cost is 22, which
    leaves a Starter 136 turns a month — four and a half a day, for a
    product sold as a chief of staff you talk to. That is a repricing
    that fixes the spreadsheet by breaking the thing being sold.

    8 is solved from the opposite end: cap the ENTRY tier's worst case —
    a customer who spends every credit on chat — at about a third of what
    they pay. 3,000 / 8 x 7.37c = $27.64 against $79. It leaves a Starter
    375 turns a month, twelve a day, which a practitioner can live in.

    WHAT 8 DOES NOT FIX

    The same worst case runs hotter on the bigger tiers, because credits
    per dollar go UP with tier while the cost of a turn does not:

        starter  35%   pro 46%   practice 58%

    That is a tank-SIZING question, not a chat-price one — one price
    cannot flatten it, and chat_tank_economics() below makes it visible
    instead of leaving it implied. Practice is the one to look at first.

    Nothing changes for a customer today: BILLING_ENFORCE is off in
    production, so allowances are recorded and not enforced. This is
    positioning for the day that flips, which is the safe moment to do it.
    """
    return _dial("CHAT_PRICE", "PRICE_", 8)


def concierge_price() -> int:
    """One customer-facing website reply.

    Left at 1 while chat_price went to 8, deliberately. Its docstring
    used to say "same rate as a Chief turn", and the honest reason it no
    longer tracks is that there is ONE metered concierge call in all of
    production, at 0.12c. That is not a sample, it is an anecdote, and
    repricing a customer-facing surface off a single row would be
    inventing a number and calling it data.

    Revisit once the meter has seen real traffic. If it lands near a
    Chief turn's cost it should move with it."""
    return _dial("CONCIERGE_PRICE", "PRICE_", 1)


def premium_voice_price() -> int:
    """ElevenLabs spoken chunk. Standard OpenAI TTS stays free (0)."""
    return _dial("PREMIUM_VOICE_PRICE", "PRICE_", 1)


# ─── Does the tank pay for itself? ───────────────────────────────────

# Measured from api_usage over 640 real Chief turns, 2026-07-23..08-10.
# A constant rather than a live query on purpose: this is a PRICING
# input, and a price that silently re-derives itself from yesterday's
# traffic is a price nobody can reason about. Re-measure deliberately
# and move the number deliberately.
MEASURED_CHAT_COST_CENTS = 7.37


def chat_tank_economics(cost_cents: Optional[float] = None) -> Dict[str, Dict[str, float]]:
    """Worst case per tier: a customer who spends their ENTIRE monthly
    credit allowance on conversation.

    Not the typical case — most credits go to builds — but it is the one
    that decides whether a tier can be sold at all, and it was invisible
    until now. `cogs_pct` above 100 means that customer costs more than
    they pay.
    """
    cost = float(cost_cents if cost_cents is not None else MEASURED_CHAT_COST_CENTS)
    price = max(1, chat_price())
    out: Dict[str, Dict[str, float]] = {}
    for plan, credits in tier_credits().items():
        revenue_c = float(tier_price_cents().get(plan, 0))
        turns = credits / price
        cogs_c = turns * cost
        out[plan] = {
            "turns_in_the_tank": round(turns, 1),
            "cogs_cents": round(cogs_c, 2),
            "revenue_cents": revenue_c,
            "cogs_pct": round(cogs_c / revenue_c * 100, 1) if revenue_c else 0.0,
        }
    return out


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

        # ── Chief chat: THE unit everything else is denominated in ──
        # These were missing in #448, which meant chat_price() moved the
        # number the UI QUOTED while the meter went on charging
        # DEFAULT_WEIGHT — the exact quote-vs-charge divergence that PR
        # claimed to close. Explicit now, at the same value, so the dial
        # reaches the endpoint it names.
        "/chief/backend": chat_price(),
        "/chief/backend-fallback": chat_price(),   # backup brain, same turn
        "/chief/draft": chat_price(),
        "/ai/proxy": chat_price(),
        "/composer/coach/turn": chat_price(),
        # Chief's REASONING sub-calls inside a single turn — the
        # practitioner asked one question and must not pay three times.
        "/chief/action-reasoner": 0,
        "/chief/analyze-hard": 0,
        "/chief/ask-transaction": 0,
        # PROACTIVE work the practitioner did not ask for. Priced 0 —
        # flagged to Kevin 2026-08-09: these are scheduled/background
        # (insights sweeps, playbook warm-ups), so billing them charges
        # someone for a job they never started. If they should bill,
        # they are dials like everything else.
        "/chief/insights": 0,
        "/chief/playbook": 0,
        "/platform/chief/message": 0,      # platform owner, never billable

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


# ─── Tier list prices ────────────────────────────────────────────────
# Needed here (not just in Stripe) to compute the per-credit rate that
# the pack guard below compares against.

def tier_price_cents() -> Dict[str, int]:
    """Monthly list price per tier, in cents. `founder` is the launch
    cohort's Professional price locked for the subscription's life — it
    buys the Professional grant, so it is the CHEAPEST subscription
    credit on the platform and therefore the binding constraint on how
    cheap a top-up pack may be."""
    return {
        "starter":      _dial("TIER_STARTER_CENTS", "PRICE_", 7900),
        "professional": _dial("TIER_PROFESSIONAL_CENTS", "PRICE_", 19900),
        "practice":     _dial("TIER_PRACTICE_CENTS", "PRICE_", 39900),
        "founder":      _dial("TIER_FOUNDER_CENTS", "PRICE_", 14900),
    }


# Founder is a closed 50-seat promotion, not something a new customer
# can choose. Pricing packs against IT left them undercutting every tier
# anyone can actually buy — which is the behaviour the invariant exists
# to prevent, passing its own check. Kept separate so the distinction is
# a named thing rather than a fact someone has to remember.
PROMOTIONAL_TIERS = frozenset({"founder"})


def purchasable_tier_cents_per_credit() -> Dict[str, float]:
    """Tier rates a NEW customer can choose between today."""
    return {t: r for t, r in tier_cents_per_credit().items()
            if t not in PROMOTIONAL_TIERS}


def tier_cents_per_credit() -> Dict[str, float]:
    """What one credit costs inside each subscription."""
    prices, credits = tier_price_cents(), tier_credits()
    grant = dict(credits)
    grant["founder"] = credits["professional"]   # founder = the pro grant
    return {t: (prices[t] / grant[t]) for t in prices if grant.get(t)}


# ─── Credit packs ────────────────────────────────────────────────────
#
# RESCALED 2026-08-08 (Kevin's ruling, second pass) to 1000 / 2750 /
# 6000 units, so a pack could complete one action at the new tank scale.
# That fixed the product and broke the economics: it left every pack
# CHEAPER per credit than every subscription — 1.000c / 0.909c / 0.833c
# against a 1.490c founder credit. warn_on_pack_economics() has been
# saying so at every boot since.
#
# RESCALED AGAIN 2026-08-10 (Kevin: "fix the pack pricing so it's not
# cheaper than the tiers") to 740 / 1555 / 3120, and the SMALL PACK MOVED
# FROM $10 TO $12 — the one price point that had to give, because two of
# Kevin's own rules turned out to be jointly impossible at $10:
#
#   shape rule    the small pack covers a build PLUS an edit  -> >= 720 credits
#   ladder rule   it must not undercut a buyable tier         -> <= 626 credits at $10
#
# 720 credits cannot honestly cost less than $11.49. Holding $10 would
# have meant quietly dropping one of the two rules; $12 keeps both, and
# it is the smaller change.
#
# The two invariants pull in opposite directions and both have to hold,
# which is what makes this arithmetic rather than taste:
#
#   a pack must not undercut a subscription   -> FEWER credits per dollar
#   a pack must complete a build with change  -> MORE credits per dollar
#
# A build is 600 credits and an edit is 120, so the small pack needs 720
# and $12 to buy them honestly. The ladder still rewards buying bigger:
# 1.622c / 1.608c / 1.603c.
#
# The benchmark moved too, and deliberately. The old one was the FOUNDER
# rate, 1.490c — but founder is a closed 50-seat promotion, so pricing
# against it left packs undercutting every tier a customer can actually
# buy. These clear PRACTICE at 1.596c, the cheapest generally available
# tier, which is the number that decides whether topping up beats
# upgrading.
#
# Cents are unchanged: the packs stay $10 / $25 / $50.
#
# Safe to change today: zero credit packs have ever been sold (verified
# against credit_ledger — no purchase rows exist), so no customer is
# holding a balance bought at the old rate.

def credit_packs() -> Dict[str, Dict[str, int]]:
    return {
        "small":  {"cents": _dial("PACK_SMALL_CENTS", "PRICE_", 1200),
                   "units": _dial("PACK_SMALL_UNITS", "PRICE_", 740)},
        "medium": {"cents": _dial("PACK_MEDIUM_CENTS", "PRICE_", 2500),
                   "units": _dial("PACK_MEDIUM_UNITS", "PRICE_", 1555)},
        "large":  {"cents": _dial("PACK_LARGE_CENTS", "PRICE_", 5000),
                   "units": _dial("PACK_LARGE_UNITS", "PRICE_", 3120)},
    }


def pack_economics() -> Dict[str, object]:
    """The two invariants Kevin asked for, computed rather than asserted.

    (1) NO PACK CREDIT MAY BE CHEAPER THAN A SUBSCRIPTION CREDIT.
        Otherwise a heavy user rationally buys packs forever instead of
        upgrading, and the tier ladder stops meaning anything. The
        comparison is against the CHEAPEST tier rate — today the Founder
        seat at $149 for the Professional grant (1.490c/credit).

    (2) EVERY PACK MUST COMPLETE AT LEAST ONE FULL ACTION AND HAVE
        SOMETHING LEFT. A pack that funds 90% of a build is a refund
        request.

    Returned as data, not raised: pricing is Kevin's to set, and a guard
    that hard-fails startup on a deliberate promotional price would be
    worse than the problem. The test suite asserts on this, and
    warn_on_pack_economics() logs it at boot."""
    packs = credit_packs()
    tier_rates = tier_cents_per_credit()
    floor_tier = min(tier_rates, key=lambda t: tier_rates[t])
    floor = tier_rates[floor_tier]

    # The rate that actually decides "top up or upgrade?" — a customer
    # cannot choose the founder promotion, so beating it is not the test
    # that matters.
    buyable = purchasable_tier_cents_per_credit()
    buy_tier = min(buyable, key=lambda t: buyable[t])
    buy_floor = buyable[buy_tier]

    typical_build = price_for_build(build_included_sections())

    rows = {}
    for name, p in packs.items():
        units = p["units"] or 1
        rate = p["cents"] / units
        rows[name] = {
            "cents": p["cents"], "units": units,
            "cents_per_credit": round(rate, 4),
            "pct_of_cheapest_tier_rate": round(rate / floor * 100, 1),
            "pct_of_cheapest_buyable_rate": round(rate / buy_floor * 100, 1),
            "undercuts_subscription": rate < floor,
            "undercuts_buyable_tier": rate < buy_floor,
            "builds_afforded": units // typical_build if typical_build else None,
            "credits_left_after_one_build": units - typical_build,
            "completes_an_action_with_change": units > typical_build,
        }
    return {
        "cheapest_tier": floor_tier,
        "cheapest_tier_cents_per_credit": round(floor, 4),
        "cheapest_buyable_tier": buy_tier,
        "cheapest_buyable_cents_per_credit": round(buy_floor, 4),
        "typical_build_credits": typical_build,
        "packs": rows,
        "warnings": (
            [f"{n}: {r['cents_per_credit']}c/credit is "
             f"{r['pct_of_cheapest_tier_rate']}% of the {floor_tier} rate "
             f"({round(floor, 3)}c) — a top-up credit is cheaper than a "
             f"subscription credit"
             for n, r in rows.items() if r["undercuts_subscription"]]
            + [f"{n}: {r['cents_per_credit']}c/credit undercuts the "
               f"{buy_tier} rate ({round(buy_floor, 3)}c) — topping up beats "
               f"upgrading, which is the ladder inverting"
               for n, r in rows.items()
               if r["undercuts_buyable_tier"] and not r["undercuts_subscription"]]
            + [f"{n}: {r['units']} credits cannot complete one "
               f"{typical_build}-credit build with change to spare"
               for n, r in rows.items()
               if not r["completes_an_action_with_change"]]),
    }


def warn_on_pack_economics() -> None:
    """Log any pack-pricing warning once, at import. Silent when clean."""
    try:
        for w in pack_economics()["warnings"]:
            logger.warning(f"[pricing] pack economics: {w}")
    except Exception as e:      # never let a diagnostic break boot
        logger.warning(f"[pricing] pack economics check skipped: {e}")


# ─── Introspection ───────────────────────────────────────────────────

def snapshot() -> Dict[str, object]:
    """Every live dial in one payload — for /billing/config, Mission
    Control, and 'what is this instance actually charging?' at 2am."""
    return {
        "tier_credits": tier_credits(),
        "prices": {
            "build_base": build_base(),
            "build_included_sections": build_included_sections(),
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
        "tier_price_cents": tier_price_cents(),
        "pack_economics": pack_economics(),
    }


warn_on_pack_economics()
