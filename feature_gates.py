"""
feature_gates.py — Phase E — tier entitlements (gate-ready, UNENFORCED).

Per Kevin's pricing ruling: pricing is locked AFTER the full build, so every
feature is free for all practitioners today. This module makes the gates
REAL but DORMANT — has_feature() returns True unless BILLING_ENFORCE=on.
The tier→feature map below is the gate-ready scaffold; final assignments are
the pricing decision, changed here in one place.

Tiers resolve from businesses.subscription_plan (a Stripe price id) via the
STRIPE_PRICE_ID_{STARTER,PROFESSIONAL,PRACTICE} env vars.
"""
from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from typing import Any, Dict, Optional

import pricing_config

PLANS = ("starter", "professional", "practice")   # the public ladder

# Plans sold to ONE kind of business (2026-10-04): barbers and salons get
# Solo $49 / Booked $79 / Boss $99. Each carries its own feature list
# (AUDIENCE_PLAN_FEATURES): Boss has Professional's bookkeeping without
# Professional's AI surfaces, which a single minimum-tier rank can't say.
# PLANS stays the public ladder, so the site and the compare table are
# untouched; ALL_PLANS is every key a subscription or comp can resolve to.
AUDIENCE_PLANS = ("solo", "booked", "boss")
ALL_PLANS = PLANS + AUDIENCE_PLANS

# ORDERING only (the best-plan pick behind the business cap, the billing
# rehearsal). Access comes from plan_features(), never from this number.
_PLAN_RANK = {"starter": 1, "professional": 2, "practice": 3,
              "solo": 1, "booked": 1, "boss": 2}

# Gate-ready map: feature → minimum tier. Working pricing hypothesis
# (2026-06-09 review): Starter $79 / Professional $199 / Practice $399;
# re-set 2026-09-04 to $79 / $149 / $299 with a $99 Founder seat.
FEATURE_MIN_PLAN: Dict[str, str] = {
    # Starter — operational core (incl. reconciliation: it's the upgrade wedge)
    "bookkeeping_basic": "starter",        # transactions + cash flow + reconciliation
    "reports_basic": "starter",            # P&L, AR aging, balance sheet lite
    "invoicing": "starter",
    "general_ledger": "starter",           # GL, trial balance, journal.
                                           # Kevin's ruling 2026-08-19: the ledger
                                           # is the RECORD — every business gets to
                                           # see its own authoritative books
                                           # ("that's for safety"). The upgrade is
                                           # the advanced layer (reports_full,
                                           # period_close, accountant_package),
                                           # never the ledger itself.
    # Professional — the real accounting system (the hero tier)
    "period_close": "professional",
    "contractor_payments": "professional", # F.1 pay + 1099
    "reports_full": "professional",        # GL-authoritative + comparison
    "chief_bookkeeping": "professional",
    "chief_unlimited": "professional",     # Starter gets the capped Chief
    "accountant_package": "professional",  # year-end ZIP + IIF — every solo files taxes
    "vertical_ledgers": "professional",    # IOLTA trust / restricted-fund MECHANICS —
                                           # compliance is table stakes for a solo lawyer
    "site_concierge": "professional",      # customer-facing website chat
                                           # (site_concierge.py) — an AI
                                           # surface, so it rides the hero
                                           # tier with chief_unlimited
    "agent_connector": "starter",          # connect the business to the AI
                                           # the practitioner already carries
                                           # (mcp_server.py + mcp_oauth.py).
                                           # READ on every plan (2026-09-04):
                                           # their model does the thinking, so
                                           # a read costs the platform nothing,
                                           # and feeling it is the upgrade path.
    "agent_connector_write": "professional",  # the write key — records kept
                                           # by an outside agent — rides the
                                           # hero tier, like site_concierge.
                                           # NOT Practice — that tier is
                                           # collaboration and compliance
                                           # deliverables, and this is
                                           # neither.
    "sourcing_desk": "professional",       # find vendors on the live web +
                                           # RFQ them (sourcing_router).
                                           # Kevin's ruling 2026-08-22: the
                                           # same AI-surface-rides-the-hero-
                                           # tier rule. Gates NEW searches
                                           # and RFQ compose/send only —
                                           # vendors and quotes already
                                           # landed stay readable on every
                                           # plan (data is never plan-
                                           # locked).
    # Practice — collaboration + compliance deliverables + scale
    "dedicated_sms_number": "practice",    # a private texting line (sms_numbers_router).
                                           # Kevin's call 2026-09-02: included at
                                           # Practice first; a Professional add-on
                                           # is a later, separate change.
    "accountant_collaborator": "practice",
    "audit_trail": "practice",
    "vertical_reports": "practice",        # Trust Reconciliation, 990 prep (I.10)
    "multi_seat": "practice",              # seat CAPS enforce via business_users_router
                                           # (max_seats limit); the frontend still hides
                                           # this key from plan cards (HIDDEN_FEATURES)
                                           # until the full team experience ships
    "ai_clips": "practice",                # Find my best clips (clip_finder.py): a
                                           # recording becomes short captioned clips.
                                           # Kevin 2026-10-05: the Growth marketing
                                           # level (the Solutionist plan), 10 hours a
                                           # month included, then 75 actions an hour.
    # The marketing suite (Kevin 2026-10-07, docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md):
    # one desk for every business; the plan decides how much of the work
    # Chief does. Posting what the owner asks stays on every plan (the
    # pricing page promises it) and needs no key.
    "marketing_suggestion": "starter",     # one suggested post a week to approve
    "marketing_week": "professional",      # the Thursday plan: five posts with flyers
                                           # (Boss gets it barber-sized, below)
    "marketing_autopilot": "practice",     # standing permissions for marketing posts
}

# Gated but not yet on sale: kept off the plan cards (/billing/plans) until
# the screen that sells it is live, so a card never lists a raw key or a
# feature nobody can open. Remove a key here when its screen ships.
# (ai_clips left 2026-10-05: Kevin opened Find my best clips to every
# business on the plan, after the live Church proof. The marketing suite's
# three levels left 2026-10-08, plan B14: Kevin opened the desk to every
# business.)
UNANNOUNCED_FEATURES: frozenset = frozenset()

# What Chief does for a business's marketing on each plan, in the words the
# pricing table, the plan cards and the FAQ use (plan B14, the ladder of
# docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md). Boss's week is the open-
# chairs shape of marketing_week; Solutionist's is marketing_autopilot.
# __tests__/test_marketing_open_to_all.py holds these to plan_features().
MARKETING_SUGGEST_WORDS = "Chief suggests one post a week for you to approve"
MARKETING_WEEK_WORDS = "Chief plans your week: five posts with flyers, approve in one tap"
MARKETING_OPENINGS_WORDS = "Chief turns open chairs into posts, with your own work photos"
MARKETING_AUTOPILOT_WORDS = "Chief runs your week: flyers and your own video clips, and the kinds of posts you trust can go out without asking"
MARKETING_LADDER: Dict[str, str] = {
    "starter": MARKETING_SUGGEST_WORDS,
    "solo": MARKETING_SUGGEST_WORDS,
    "booked": MARKETING_SUGGEST_WORDS,
    "professional": MARKETING_WEEK_WORDS,
    "boss": MARKETING_OPENINGS_WORDS,
    "practice": MARKETING_AUTOPILOT_WORDS,
}

# ─── Plans for one kind of business ──────────────────────────────────
# Solo = everything Starter carries (derived, so a new Starter feature
# reaches Solo too). Booked adds the business's own texting line (the
# front desk's number). Boss adds the books done for them: month-end
# close, the full reports, Chief's bookkeeping, the accountant package
# and 1099s for an assistant. Features the plan lists ship as they land
# (missed-call text-back, posting) — a key here never sells a feature.
_STARTER_FEATURES = frozenset(f for f, mp in FEATURE_MIN_PLAN.items() if mp == "starter")
AUDIENCE_PLAN_FEATURES: Dict[str, frozenset] = {
    "solo":   _STARTER_FEATURES,
    "booked": _STARTER_FEATURES | {"dedicated_sms_number"},
    "boss":   _STARTER_FEATURES | {"dedicated_sms_number", "period_close", "reports_full",
                                   "chief_bookkeeping", "accountant_package",
                                   "contractor_payments",
                                   # Kevin 2026-10-07: the weekly plan, barber-sized
                                   # (open chairs, work photos, three posts).
                                   "marketing_week"},
}

# Who may buy each audience plan: canonical vertical keys
# (vertical_registry.resolve — barber, salon, spa all land on
# personal_services). Enforced at checkout; a comp ignores it on purpose
# (the owner tries a plan on a test business).
PLAN_AUDIENCE: Dict[str, frozenset] = {
    "solo": frozenset({"personal_services"}),
    "booked": frozenset({"personal_services"}),
    "boss": frozenset({"personal_services"}),
}


def plan_features(plan: Optional[str]) -> frozenset:
    """The features a plan includes. Public ladder: by minimum tier, as
    always. Audience plans: their own list. Anything else: nothing."""
    p = (plan or "").strip().lower()
    if p in AUDIENCE_PLAN_FEATURES:
        return AUDIENCE_PLAN_FEATURES[p]
    if p not in PLANS:
        return frozenset()
    rank = _PLAN_RANK[p]
    return frozenset(f for f, mp in FEATURE_MIN_PLAN.items() if rank >= _PLAN_RANK[mp])


def audience_plans_for(business_type: Optional[str], *, offered_only: bool = True) -> list:
    """The audience plans this kind of business may buy (in ladder order)."""
    import vertical_registry
    canon = vertical_registry.resolve(business_type or "")
    return [p for p in AUDIENCE_PLANS
            if canon in PLAN_AUDIENCE[p]
            and (not offered_only or pricing_config.audience_plan_offered(p))]


def upgrade_plan_for(feature: str, current_plan: Optional[str]) -> Optional[str]:
    """The cheapest plan that unlocks `feature` from where this business
    stands: within its audience ladder when it is on one, else the public
    minimum. Upgrade prompts name THIS, so a barber on Solo is pointed at
    Boss, not at Professional."""
    p = (current_plan or "").strip().lower()
    if p in AUDIENCE_PLANS:
        for cand in AUDIENCE_PLANS[AUDIENCE_PLANS.index(p):]:
            if feature in AUDIENCE_PLAN_FEATURES[cand]:
                return cand
    return FEATURE_MIN_PLAN.get(feature)


# Numeric limits per tier. plaid_connections = connected bank account
# limit per tier (F-A2); max_businesses needs an onboarding check.
def plan_limits() -> Dict[str, Dict[str, Optional[int]]]:
    """Numeric limits per tier.

    `chief_messages_monthly` is the monthly CREDIT GRANT and now comes
    from pricing_config, where it is env-overridable — the 2026-08-08
    config-driven launch ruling: we ship conservative opening defaults
    and refine against real data once the meter works.

    Opening defaults 3,000 / 10,000 / 25,000 (7,500 / 17,500 for the two
    bigger tiers since the 2026-09-04 ladder), up ~10x from the
    300/1000/3000 of the 2026-07-12 spec. That rescale is what makes
    per-action pricing expressible at all — a build priced at 600 is
    impossible against a 300 tank. Beyond the allowance, prepaid credits
    (credit_ledger) draw down.

    A FUNCTION, not a constant, so a price change is a value change and
    there is exactly one source of truth."""
    credits = pricing_config.tier_credits()
    return {
        "starter":      {"max_businesses": 1,
                         "chief_messages_monthly": credits["starter"],
                         "max_seats": 1, "plaid_connections": 2,
                         "open_assignments": 1},
        "professional": {"max_businesses": 1,
                         "chief_messages_monthly": credits["professional"],
                         "max_seats": 1, "plaid_connections": 5,
                         "open_assignments": 3},
        "practice":     {"max_businesses": 3,
                         "chief_messages_monthly": credits["practice"],
                         "max_seats": 5, "plaid_connections": None,
                         "open_assignments": 10},
        **_audience_limits(),
    }


def _audience_limits() -> Dict[str, Dict[str, Optional[int]]]:
    """Solo / Booked / Boss: one business, one seat (they are built for
    the solo pro; shop seats come with per-staff calendars)."""
    credits = pricing_config.audience_credits()
    return {
        "solo":   {"max_businesses": 1, "chief_messages_monthly": credits["solo"],
                   "max_seats": 1, "plaid_connections": 2, "open_assignments": 1},
        "booked": {"max_businesses": 1, "chief_messages_monthly": credits["booked"],
                   "max_seats": 1, "plaid_connections": 2, "open_assignments": 2},
        "boss":   {"max_businesses": 1, "chief_messages_monthly": credits["boss"],
                   "max_seats": 1, "plaid_connections": 5, "open_assignments": 3},
    }


def _limits_of(plan: Optional[str]) -> Dict[str, Optional[int]]:
    """A plan's limits, FAILING CLOSED: a plan key with no entry gets
    Starter's limits, never none. `limits.get(plan, {})` read a missing
    entry as None — unlimited — so a new plan key added without limits
    would have granted unlimited AI."""
    limits = plan_limits()
    return limits.get((plan or "").strip().lower()) or limits["starter"]


def limit_for(business_row: Optional[Dict[str, Any]], limit: str) -> Optional[int]:
    """The numeric limit for a business's tier; None = unlimited. Unenforced
    (and unlimited) until BILLING_ENFORCE=on AND a plan exists."""
    if not enforcement_on():
        return None
    plan = plan_of(business_row)
    if not plan:
        return plan_limits()["starter"].get(limit)
    if limit == "chief_messages_monthly":
        return monthly_credits(business_row, plan)
    return _limits_of(plan).get(limit)


def is_founder_price(business_row: Optional[Dict[str, Any]]) -> bool:
    """Is this business on the Founder seat? Decided by the Stripe price
    id it subscribes to, never by a flag someone could set by hand."""
    pid = str((business_row or {}).get("subscription_plan") or "").strip()
    if not pid:
        return False
    founder = {(os.environ.get("STRIPE_PRICE_ID_FOUNDER") or "").strip(),
               (os.environ.get("STRIPE_PRICE_ID_FOUNDER_ANNUAL") or "").strip()} - {""}
    return pid in founder


def monthly_credits(business_row: Optional[Dict[str, Any]],
                    plan: Optional[str] = None) -> Optional[int]:
    """The monthly tank for this business: the plan's, except on the
    Founder seat, which carries Professional's features with its own
    smaller tank (pricing_config.founder_credits). A comped business is
    never on the founder tank — comp_tier wins in plan_of and the comp
    is the whole plan. None when there is no plan."""
    plan = plan or plan_of(business_row)
    if not plan:
        return None
    comp = str((business_row or {}).get("comp_tier") or "").strip().lower()
    if plan == "professional" and comp not in ALL_PLANS and is_founder_price(business_row):
        return pricing_config.founder_credits()
    return _limits_of(plan).get("chief_messages_monthly")


# Price-id env aliases → the tier they entitle (2026-07-21 pricing
# ruling). FOUNDER = the launch cohort's Professional price, locked for
# the life of the subscription and capped at FOUNDER_SEAT_LIMIT seats
# (enforced at checkout in stripe_billing.py); *_ANNUAL = yearly
# billing (2 months free) for the same tier. Entitlements never differ
# from the base tier — only the price does.
PRICE_ENV_TO_PLAN: Dict[str, str] = {
    "STARTER":             "starter",
    "PROFESSIONAL":        "professional",
    "PRACTICE":            "practice",
    "STARTER_ANNUAL":      "starter",
    "PROFESSIONAL_ANNUAL": "professional",
    "PRACTICE_ANNUAL":     "practice",
    "FOUNDER":             "professional",
    "FOUNDER_ANNUAL":      "professional",
    # Audience plans (barbers and salons). Checkout enforces who may buy.
    "SOLO":                "solo",
    "SOLO_ANNUAL":         "solo",
    "BOOKED":              "booked",
    "BOOKED_ANNUAL":       "booked",
    "BOSS":                "boss",
    "BOSS_ANNUAL":         "boss",
}


def price_to_plan() -> Dict[str, str]:
    """Stripe price id → tier name, from env (empty entries skipped)."""
    out: Dict[str, str] = {}
    for env_key, plan in PRICE_ENV_TO_PLAN.items():
        pid = (os.environ.get(f"STRIPE_PRICE_ID_{env_key}") or "").strip()
        if pid:
            out[pid] = plan
    # Legacy single-plan default maps to professional.
    default = (os.environ.get("STRIPE_PRICE_ID_DEFAULT") or "").strip()
    if default and default not in out:
        out[default] = "professional"
    return out


def plan_of(business_row: Optional[Dict[str, Any]]) -> Optional[str]:
    """The business's tier when its subscription is in good standing.

    Launch-ops (2026-07-03): an owner-set `comp_tier` wins over Stripe —
    the manual override for beta testers / partners / comped accounts.
    Set via POST /access/business/{id}/tier; no subscription required."""
    if not business_row:
        return None
    comp = (business_row.get("comp_tier") or "").strip().lower()
    if comp in ALL_PLANS:
        return comp
    status = business_row.get("subscription_status")
    if status not in ("trialing", "active"):
        return None
    return price_to_plan().get(business_row.get("subscription_plan") or "")


def access_state(business_row: Optional[Dict[str, Any]],
                 grandfathered: bool = False,
                 trial_spent: bool = False) -> Dict[str, Any]:
    """Subscription access enforcement (2026-07-03, Kevin's ruling:
    'if no person paid then they lose access').

    Returns {state, reason} where state is:
      'full'   — use the app normally
      'grace'  — payment failed; warn loudly, don't lock yet (Stripe
                 Smart Retries run during past_due/incomplete)
      'free'   — a no-card trial that is over (its credits or its days):
                 the workspace keeps working, Chief and the site wait for
                 a card (the reverse trial, 2026-10-03). AI is held at
                 the meter (usage_metering), not by a wall.
      'locked' — no live subscription, OR a trial that has run out of
                 credits; the frontend shows the paywall (data is never
                 deleted; export stays available)

    A trial ends on WHICHEVER COMES FIRST, the calendar or the tank
    (2026-08-24). `trial_spent` is the tank half — the caller passes
    usage_metering.trial_credits_exhausted(), because this function is
    deliberately pure and does not read the database. Left False, the
    behaviour is exactly what it was: the calendar alone.

    Dormant like everything else: enforcement_on() off → always full.
    Grandfathered users and comp_tier businesses never lock.
    """
    state = _access_state(business_row, grandfathered, trial_spent)
    return _free_workspace(state, business_row)


# The trial reasons a no-card trial softens from 'locked' to 'free'.
_TRIAL_OVER = ("trial_credits_spent", "trial_expired")


def _free_workspace(state: Dict[str, Any],
                    row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """THE REVERSE TRIAL (2026-10-03, Kevin: "build these"). A no-card
    trial that ran out used to meet the same full-screen wall as a
    cancelled subscription. Now it keeps a free workspace — contacts,
    bookings, invoices, books — and loses only what costs money: Chief
    and the other AI (held at the meter), and the live site (already a
    preview until a card). Nothing about a card trial or a paid
    subscription changes. Switch: PRICE_NO_CARD_FREE_WORKSPACE=0."""
    if state.get("state") != "locked" or state.get("reason") not in _TRIAL_OVER:
        return state
    try:
        import no_card_trial
        import pricing_config
        if pricing_config.no_card_free_workspace() and no_card_trial.is_no_card(row):
            return {"state": "free", "reason": state["reason"]}
    except Exception:
        pass
    return state


def _access_state(business_row: Optional[Dict[str, Any]],
                  grandfathered: bool,
                  trial_spent: bool) -> Dict[str, Any]:
    if not enforcement_on():
        return {"state": "full", "reason": "enforcement_off"}
    if grandfathered:
        return {"state": "full", "reason": "grandfathered"}
    row = business_row or {}
    comp = (row.get("comp_tier") or "").strip().lower()
    if comp in PLANS:
        return {"state": "full", "reason": f"comp_{comp}"}
    status = (row.get("subscription_status") or "").strip().lower()
    if status == "active":
        return {"state": "full", "reason": "active"}
    if status == "trialing":
        if trial_spent:
            return {"state": "locked", "reason": "trial_credits_spent"}
        trial_end = (row.get("trial_ends_at") or "").strip()
        if trial_end:
            from datetime import datetime, timezone
            try:
                end = datetime.fromisoformat(trial_end.replace("Z", "+00:00"))
                if end < datetime.now(timezone.utc):
                    return {"state": "locked", "reason": "trial_expired"}
            except ValueError:
                pass  # unparseable date — treat the Stripe status as truth
        return {"state": "full", "reason": "trialing"}
    if status in ("past_due", "unpaid", "incomplete"):
        return {"state": "grace", "reason": "payment_failed"}
    if (status == "canceled" and (row.get("trial_ends_at") or "").strip()
            and not (row.get("stripe_subscription_id") or "").strip()):
        # A trial with no Stripe subscription behind it — a no-card trial
        # or one Platform Chief gave — that trial_expiry closed on the
        # calendar. Nothing was ever paid for, so "your subscription has
        # ended" would be false; the trial ended.
        return {"state": "locked", "reason": "trial_expired"}
    return {"state": "locked",
            "reason": "canceled" if status == "canceled" else "no_subscription"}


# THE REHEARSAL (2026-09-04). Every gate short-circuits on enforcement_on(),
# which made "what would the flip do?" unanswerable without flipping.
# Inside rehearsal(), enforcement_on() answers True for THIS task only —
# a contextvar, so a concurrent request on the same process keeps the
# real value. billing_rehearsal uses it to ask every decision
# hypothetically; nothing else should.
_REHEARSAL: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "billing.rehearsal", default=False)


@contextmanager
def rehearsal():
    token = _REHEARSAL.set(True)
    try:
        yield
    finally:
        _REHEARSAL.reset(token)


def enforcement_on() -> bool:
    if _REHEARSAL.get():
        return True
    return (os.environ.get("BILLING_ENFORCE") or "off").lower() == "on"


def has_feature(business_row: Optional[Dict[str, Any]], feature: str) -> bool:
    """True unless enforcement is on AND the plan doesn't include it.
    Unknown features default to allowed (fail-open by design); an unknown
    plan includes nothing (plan_features)."""
    if not enforcement_on():
        return True
    if feature not in FEATURE_MIN_PLAN:
        return True
    plan = plan_of(business_row)
    if not plan:
        return False
    return feature in plan_features(plan)


def plan_includes(business_row: Optional[Dict[str, Any]], feature: str) -> bool:
    """Whether the business's actual plan includes `feature`, whatever
    BILLING_ENFORCE says. has_feature() lets everything through while
    enforcement is off, which is right for opening a screen and wrong for
    spending money nobody asked for: the marketing suite's weekly work
    (drafted posts, flyers) checks this instead. A comp counts; no plan in
    good standing includes nothing."""
    plan = plan_of(business_row)
    return bool(plan) and feature in plan_features(plan)


def entitlements(business_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Full entitlement picture for the frontend: what's allowed now, and
    what WOULD be allowed per tier once enforcement turns on. `min_plan`
    is the plan to upgrade to from HERE: inside the audience ladder for a
    business on one, the public minimum otherwise."""
    plan = plan_of(business_row)
    included = plan_features(plan)
    return {
        "plan": plan,
        "subscription_status": (business_row or {}).get("subscription_status"),
        "enforce": enforcement_on(),
        "features": {
            f: {
                "allowed": has_feature(business_row, f),
                "min_plan": upgrade_plan_for(f, plan) or mp,
                "included_in_plan": f in included,
            } for f, mp in FEATURE_MIN_PLAN.items()
        },
    }
