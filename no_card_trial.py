"""
no_card_trial.py — the trial starts without a card (2026-10-03).

Kevin: "build the no card 500 credit version". Until now a brand-new
business met the paywall the moment onboarding finished: /billing/access
answered locked/no_subscription, and the only way past it was Stripe
Checkout with a card. The card was not what capped the cost — the trial
tank was (pricing_config.trial_credits, a hard ceiling while
BILLING_ENFORCE is on) — so it was friction without protection.

THE SHAPE
  · Business creation starts a trial with no Stripe subscription behind
    it — the row shape Platform Chief's extend_trial already writes:
    subscription_status=trialing, trial_ends_at, the plan's price id. So
    access_state, the trial emails, trial_expiry (which ends it on the
    calendar) and every report already understand it.
  · The tank is smaller: pricing_config.trial_credits_no_card() (500).
    The first site build stays free (trial_build_free). It is the pitch,
    and a real build is charged 1,000-1,300 credits, so 500 could never
    pay for one: without the free build, "build a site and talk to
    Chief" would be false.
  · Adding a card is the existing Checkout. stripe_billing keeps the SAME
    trial end (checkout_trial_end), so the card unlocks the rest of the
    full tank (trial_credits(), 1,000) and nothing is charged before the
    date the practitioner was already given.
  · Until a card is on file: no texts, no phone numbers, no bulk email
    (billing_limits.require_card) and no second site build — the things
    that cost real money or put the shared sending reputation at risk.

WHO GETS ONE — once per person: never a business that has had any
subscription or trial, never if the owner has had one on another
business, never grandfathered or comped accounts (they never lock
anyway), and only while BILLING_ENFORCE is on (with it off nothing
locks, and a trial clock would only mislead).

Marker: businesses.settings.no_card_trial = {started_at, plan, credits}.
It stays after a card is added: "no card" means the marker AND no
stripe_subscription_id, so the Stripe webhook ends the no-card state by
itself, with nothing to clean up.

Kill switch: PRICE_NO_CARD_TRIAL=0. New signups then meet the card
paywall exactly as before; trials already running are untouched.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import sb_clients
import pricing_config
import feature_gates

logger = logging.getLogger("no_card_trial")

MARKER = "no_card_trial"

# Stripe Checkout refuses a subscription_data.trial_end less than 48
# hours away. An hour of margin covers the time between minting the
# session and the customer finishing it.
_CHECKOUT_MIN_TRIAL = timedelta(hours=49)


def _trial_days() -> int:
    try:
        return max(0, int(os.environ.get("BILLING_TRIAL_DAYS") or "7"))
    except ValueError:
        return 7


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def marker(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    m = ((row or {}).get("settings") or {}).get(MARKER)
    return m if isinstance(m, dict) else None


def is_no_card(row: Optional[Dict[str, Any]]) -> bool:
    """On a trial that started without a card and still has none.

    Only the marker plus the absence of a Stripe subscription: a card
    added through Checkout writes stripe_subscription_id, and that alone
    ends the no-card state. The status is deliberately NOT tested — a
    no-card trial that ran out (canceled by trial_expiry) is still a
    business that has never given a card, and the copy it sees and the
    checkout it gets both depend on knowing that.

    A row read WITHOUT the stripe_subscription_id column cannot tell a
    no-card trial from one that has since added a card (the marker stays
    on both), so it answers False — the full tank and no held sends, the
    fail-open direction every billing read here takes."""
    if not row or "stripe_subscription_id" not in row:
        return False
    if (row.get("stripe_subscription_id") or "").strip():
        return False
    # A comp (Kevin's override) outranks the trial it was given during.
    if (row.get("comp_tier") or "").strip():
        return False
    return marker(row) is not None


def is_running(row: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> bool:
    """A no-card trial that is still on the calendar."""
    if not is_no_card(row):
        return False
    if (row.get("subscription_status") or "").strip().lower() != "trialing":
        return False
    ends = _parse(row.get("trial_ends_at"))
    return bool(ends and ends > (now or datetime.now(timezone.utc)))


def _plan() -> str:
    plan = (os.environ.get("NO_CARD_TRIAL_PLAN") or "professional").strip().lower()
    return plan if plan in feature_gates.PLANS else "professional"


def _price_id(plan: str) -> str:
    return (os.environ.get(f"STRIPE_PRICE_ID_{plan.upper()}") or "").strip()


def eligible(row: Optional[Dict[str, Any]]) -> Optional[str]:
    """None when this business may start a no-card trial now, otherwise
    the reason it may not (logged, never shown)."""
    if not pricing_config.no_card_trial_enabled():
        return "disabled"
    if not feature_gates.enforcement_on():
        return "enforcement_off"
    if _trial_days() <= 0:
        return "no_trial_days"
    if not row or not row.get("id"):
        return "no_business"
    if (row.get("comp_tier") or "").strip():
        return "comped"
    if (row.get("stripe_subscription_id") or "").strip():
        return "has_subscription"
    if (row.get("trial_ends_at") or "").strip() or marker(row) is not None:
        return "had_trial"
    if (row.get("subscription_status") or "").strip():
        return "has_status"
    if not _price_id(_plan()):
        return "plan_not_configured"
    owner = str(row.get("owner_id") or "")
    if not owner:
        return "no_owner"
    import usage_metering
    if usage_metering.is_grandfathered_user(owner):
        return "grandfathered"
    # Once per PERSON, not per business: a second business must not be a
    # second free tank. Any business of theirs that has had a trial or a
    # subscription counts (the marker always comes with trial_ends_at).
    others = sb_clients.sb_get_as_service(
        f"/businesses?owner_id=eq.{owner}&id=neq.{row['id']}"
        f"&or=(trial_ends_at.not.is.null,stripe_subscription_id.not.is.null)"
        f"&select=id&limit=1")
    if others is None:
        return "owner_history_unreadable"     # fail closed: the card door stays
    if others:
        return "owner_had_trial"
    return None


def start(row: Optional[Dict[str, Any]], source: str = "signup") -> Optional[Dict[str, Any]]:
    """Start the no-card trial on this business if it is eligible.

    Returns {trial_ends_at, plan, credits} when it started, else None.
    Never raises: a business that could not get its trial simply meets
    the card paywall, which is exactly how every signup worked before.

    The PATCH is conditional on the row still having no trial and no
    subscription, so two racing callers (signup and the access check)
    start ONE trial, and a Stripe webhook that landed first wins."""
    try:
        why = eligible(row)
        if why:
            logger.info(f"[no-card] not starting for {str((row or {}).get('id'))[:8]}: {why}")
            return None
        plan = _plan()
        now = datetime.now(timezone.utc)
        ends = now + timedelta(days=_trial_days())
        credits = pricing_config.trial_credits_no_card()
        settings = dict(row.get("settings") or {})
        settings[MARKER] = {"started_at": now.isoformat(), "plan": plan,
                            "credits": credits, "source": source}
        patch = {
            "subscription_status": "trialing",
            "trial_ends_at": ends.isoformat(),
            "subscription_plan": _price_id(plan),
            "tier": plan,
            "settings": settings,
        }
        where = (f"/businesses?id=eq.{row['id']}&stripe_subscription_id=is.null"
                 f"&trial_ends_at=is.null")
        res = sb_clients.sb_patch_as_service(where, patch)
        if res is None:
            # The tier mirror can trip an old CHECK (the Stripe webhook
            # has the same fallback); the trial is the part that matters.
            patch.pop("tier", None)
            res = sb_clients.sb_patch_as_service(where, patch)
        if not res:
            # Lost the race, or the write failed. Either way there is no
            # trial of OURS on the row to report.
            return None
        logger.info(f"[no-card] trial started for {row['id'][:8]} ({plan}, "
                    f"{credits} credits, ends {ends.date()})")
        try:
            import first_run_arc
            first_run_arc.begin(row["id"], source="subscription",
                                trial_ends_at=ends.isoformat())
        except Exception as e:
            logger.warning(f"[no-card] first-run arc align failed (non-fatal): {e}")
        return {"trial_ends_at": ends.isoformat(), "plan": plan, "credits": credits}
    except Exception as e:
        logger.warning(f"[no-card] start failed (card paywall stays): {e}")
        return None


def checkout_trial(row: Optional[Dict[str, Any]],
                   now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """What Checkout should do about the trial for a no-card business.

    None              not a no-card business; the caller's usual rule applies.
    {"trial_end": ts} the trial is still running: keep its end date, so the
                      card buys the rest of the tank, not a fresh 7 days.
                      Stripe needs 48h; a trial closer to its end than
                      that is given the 48h, which is the customer's way.
    {}                the trial already ended: no second trial."""
    if not is_no_card(row):
        return None
    now = now or datetime.now(timezone.utc)
    if not is_running(row, now):
        return {}
    ends = _parse(row.get("trial_ends_at"))
    end = max(ends, now + _CHECKOUT_MIN_TRIAL)
    return {"trial_end": int(end.timestamp())}


def describe(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The fields the app needs to word a no-card trial honestly."""
    no_card = is_no_card(row)
    out: Dict[str, Any] = {"no_card_trial": no_card}
    if no_card:
        out["trial_credits"] = pricing_config.trial_credits_no_card()
        out["card_trial_credits"] = pricing_config.trial_credits()
    return out


def tank(row: Optional[Dict[str, Any]]) -> int:
    """The trial tank this business draws from."""
    if is_no_card(row):
        return pricing_config.trial_credits_no_card()
    return pricing_config.trial_credits()


# ─── What waits for a card ───────────────────────────────────────────
# Texts (every one goes out on our Twilio account, from the shared
# platform number for anyone without their own line), phone numbers
# (bought on our account), bulk email (sent on our Resend account, whose
# reputation every paying customer's mail rides on) and a second site
# build (the first is free; the next is 1,000+ credits, double the
# whole tank). One-to-one mail — a booking confirmation, an invoice, a
# reply to a client — is how a practitioner tries the product, and
# stays open.

class CardRequired(RuntimeError):
    """Raised where a no-card trial reaches something that waits for a
    card. str() is the practitioner-readable message."""

    def __init__(self, what: str, message: str):
        super().__init__(message)
        self.what = what
        self.message = message


_WHAT = {
    "texts": "Texting turns on once there's a card on file.",
    "number": "A texting number comes once there's a card on file.",
    "bulk_email": "Sending to a group of contacts at once turns on once there's a card on file.",
    "rebuild": "Your free trial includes one site build, and you've used it.",
}


def card_message(what: str, row: Optional[Dict[str, Any]] = None) -> str:
    """The refusal, in the practitioner's words. While the trial is still
    running it says the true thing about adding a card: nothing is
    charged before the end date, and the tank grows."""
    lead = _WHAT.get(what, "That turns on once there's a card on file.")
    action = "To build again, add a card" if what == "rebuild" else "Add a card"
    msg = f"{lead} {action} in Settings → Billing"
    if row is not None and is_running(row):
        ends = _parse(row.get("trial_ends_at"))
        extra = max(0, pricing_config.trial_credits()
                    - pricing_config.trial_credits_no_card())
        msg += " — nothing is charged until your trial ends"
        if ends:
            msg += f" on {ends.strftime('%B')} {ends.day}"
        if extra:
            msg += f", and the card adds {extra:,} more credits"
    return msg + "."


def _row(business_id: str) -> Optional[Dict[str, Any]]:
    import usage_metering
    return usage_metering._biz_row(business_id)


def blocks(business_id: Optional[str],
           row: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The business row when it is a no-card trial (so the caller can word
    the refusal), else None. Fails OPEN — a lookup error never stops a
    send — like every billing read in this codebase."""
    if not business_id:
        return None
    try:
        r = row if row is not None and "settings" in row else _row(business_id)
        return r if is_no_card(r) else None
    except Exception as e:
        logger.warning(f"[no-card] gate read failed open for {str(business_id)[:8]}: {e}")
        return None


async def blocks_async(client, business_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """blocks() for async paths, on the caller's httpx client."""
    if not business_id:
        return None
    try:
        rows = await sb_clients.sb_as_service(
            client, "GET",
            f"/businesses?id=eq.{business_id}"
            f"&select=id,settings,subscription_status,stripe_subscription_id,"
            f"trial_ends_at,comp_tier&limit=1") or []
        r = rows[0] if rows else None
        return r if is_no_card(r) else None
    except Exception as e:
        logger.warning(f"[no-card] gate read failed open for {str(business_id)[:8]}: {e}")
        return None


def check(business_id: Optional[str], what: str,
          row: Optional[Dict[str, Any]] = None) -> None:
    """Raise CardRequired when a no-card trial reaches `what`."""
    r = blocks(business_id, row)
    if r is not None:
        raise CardRequired(what, card_message(what, r))


async def check_async(client, business_id: Optional[str], what: str) -> None:
    r = await blocks_async(client, business_id)
    if r is not None:
        raise CardRequired(what, card_message(what, r))


def check_rebuild(business_id: str) -> None:
    """A no-card trial's SECOND site build waits for a card.

    The first build is free (usage_metering.trial_first_build_is_free).
    The next one is charged 1,000+ credits against a 500 tank, and the
    AI gate only asks whether ANY credit is left — so without this a
    trial with one credit to spare could start a full build at our cost.
    Fails open on a read error, like every gate here: the worst that
    leaks is one build."""
    r = blocks(business_id)
    if r is None:
        return
    try:
        prior = sb_clients.sb_get_as_service(
            f"/api_usage?business_id=eq.{business_id}"
            f"&task_type=eq.site_build_marker&select=id&limit=1")
    except Exception as e:
        logger.warning(f"[no-card] rebuild check failed open: {e}")
        return
    if prior:
        raise CardRequired("rebuild", card_message("rebuild", r))
