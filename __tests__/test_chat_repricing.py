"""A Chief message is priced against what a Chief message costs.

margin.py said it in its own docstring and could not act on it: "a Chief
turn sells for between 1.490c (founder) and 2.633c (starter) and costs
7.16c at the mean, 19.84c at p95. Every tier loses money on conversation
and makes it back on builds. That is a decision to take deliberately or
not at all, and it cannot be taken while the number is invisible."

The number became visible on 2026-08-10: 640 real model calls, mean
7.37c. At 1 credit a call the credit had stopped being a currency, and
the price went 1 -> 8 -> 12 per CALL.

On 2026-10-16 the price moved to once per MESSAGE (pricing_config.
chat_price), because per call a message was charged a varying 13-37
credits and failed calls were charged too. Measured that day: credits
charged per message median 15, mean 19.6; real cost per message mean
21.5c over 199 messages (2026-10-07). 20 per message is what customers
were already charged on average.

That move also exposed something the old suite could not see: its 40%
ceilings were computed with the per-CALL 7.37c, so they passed while a
real message cost three times that. At 21.5c a message the honest
worst case is about 41% / 54% / 63%. The ceilings below are a RATCHET
at that level: they may only come down, and the way they come down is
the cost of a message (the Chief cost plan), not this dial.

These tests pin the RELATIONSHIP, not the digit. A price is allowed to
move — that is the entire point of pricing_config — but it is not
allowed to drift back to a token value, and the tank is not allowed to
quietly become less fundable than it is today.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import pricing_config as pc

# What a customer who spends their WHOLE tank on chat may cost, as a
# share of what they pay. Not a typical customer — the one who decides
# whether a tier can be sold at all.
#
# A RATCHET at today's honest level (2026-10-16, 20 credits and 21.5c a
# message): starter 40.8%, professional 54.1%, practice 62.9%. Until
# that day these read 40 and 40, which held only because the cost they
# were checked against was a per-call 7.37c. Lower them as the cost of a
# message comes down; never raise them.
ENTRY_TIER_COGS_CEILING_PCT = 42.0
ANY_TIER_COGS_CEILING_PCT = 65.0

# Where the ratchet is meant to end: the 40% the per-call era believed
# it had. Reached by cost per message, not by price (see TestTheTarget).
TARGET_COGS_PCT = 40.0


class TestThePriceReflectsTheCost:
    def test_a_message_is_not_a_token_price(self):
        """1 credit was not a price, it was a placeholder. Anything in
        low single digits means the credit is not tracking cost."""
        assert pc.chat_price() >= 5, (
            f"chat_price is {pc.chat_price()} — at "
            f"{pc.MEASURED_CHAT_COST_CENTS}c a message, that is back to "
            f"selling conversation below cost in credit terms")

    def test_it_is_not_so_high_the_product_stops_working(self):
        """A repricing that fixes the spreadsheet by breaking the product
        is not a fix. The floor is 150 messages a month for a Starter,
        five a day: exactly what a Starter actually got under per-call
        charging, when a message was charged 19.6 credits on average.
        Below it, per-message pricing would be a price rise in disguise."""
        starter_turns = pc.chat_tank_economics()["starter"]["turns_in_the_tank"]
        assert starter_turns >= 150, (
            f"a Starter gets {starter_turns:.0f} messages a month — fewer "
            f"than per-call charging gave them")

    def test_the_measured_cost_is_recorded_not_guessed(self):
        """A per-MESSAGE figure now (all of a message's calls together).
        Outside this band it is either per-call again or a typo."""
        assert 10.0 <= pc.MEASURED_CHAT_COST_CENTS <= 40.0, (
            "the measured cost constant drifted somewhere implausible — "
            "re-measure per message against api_usage before moving it")


class TestTheTankCanBeFunded:
    def test_the_entry_tier_worst_case_is_survivable(self):
        """The case that decides whether Starter can be sold: someone who
        spends every credit talking to Chief."""
        e = pc.chat_tank_economics()["starter"]
        assert e["cogs_pct"] <= ENTRY_TIER_COGS_CEILING_PCT, (
            f"a Starter spending their whole tank on chat costs "
            f"${e['cogs_cents']/100:.2f} against $79 ({e['cogs_pct']}%)")

    @pytest.mark.parametrize("plan", ["starter", "professional", "practice"])
    def test_no_tier_loses_money_on_conversation(self, plan):
        """The floor. Above 100% the customer costs more than they pay."""
        e = pc.chat_tank_economics()[plan]
        assert e["cogs_pct"] < 100.0, (
            f"{plan} at full-tank chat costs {e['cogs_pct']}% of revenue")
        assert e["cogs_pct"] <= ANY_TIER_COGS_CEILING_PCT, (
            f"{plan} is at {e['cogs_pct']}% — above the ratchet")

    def test_the_bigger_tiers_run_hotter_and_that_is_known(self):
        """Credits per dollar go UP with tier while a message's cost does
        not, so one chat price cannot flatten this. Asserting the shape
        keeps it from being rediscovered as a surprise — the lever is
        tank SIZE or message cost, and Practice is the one to look at."""
        e = pc.chat_tank_economics()
        assert e["practice"]["cogs_pct"] > e["starter"]["cogs_pct"]

    def test_it_would_fail_at_a_token_price(self, monkeypatch):
        """Guards the guard. If these ceilings passed at 1 credit too,
        they would be measuring nothing."""
        monkeypatch.setenv("PRICE_CHAT_PRICE", "1")
        assert pc.chat_price() == 1
        e = pc.chat_tank_economics()["starter"]
        assert e["cogs_pct"] > 100.0, (
            "at 1 credit a message the entry tier should be underwater — if "
            "it is not, this suite is not measuring what it claims")

    def test_twelve_per_message_was_never_an_option(self, monkeypatch):
        """Why the move to per-message pricing came with a move to 20:
        keeping 12 and charging it once per message would have handed
        out more messages than customers were getting and put Practice
        over 100% at full tank."""
        monkeypatch.setenv("PRICE_CHAT_PRICE", "12")
        e = pc.chat_tank_economics()
        assert e["practice"]["cogs_pct"] > 100.0
        assert e["professional"]["cogs_pct"] > ANY_TIER_COGS_CEILING_PCT


class TestTheTarget:
    """Where the ratchet is meant to end, and what gets it there."""

    def _target_cost(self):
        """The per-message cost at which the binding tier (the cheapest
        credit a new customer can buy) sits exactly on TARGET_COGS_PCT
        at today's price."""
        cheapest = min(pc.purchasable_tier_cents_per_credit().values())
        return TARGET_COGS_PCT / 100 * pc.chat_price() * cheapest

    def test_the_lever_is_the_cost_of_a_message(self):
        """At 20 credits a message, Practice reaches 40% when a message
        costs about 13.7c. That number is the Chief cost plan's target."""
        need = self._target_cost()
        e = pc.chat_tank_economics(cost_cents=need)
        assert e["practice"]["cogs_pct"] == pytest.approx(TARGET_COGS_PCT, abs=0.1)
        assert 12.0 < need < 16.0, f"target cost moved to {need:.2f}c"

    def test_the_target_is_not_met_yet(self):
        """This failing is good news: the measured cost of a message has
        reached the target. Re-measure, then lower ENTRY/ANY ceilings
        toward TARGET_COGS_PCT and delete this test."""
        assert pc.MEASURED_CHAT_COST_CENTS > self._target_cost(), (
            "a message now costs no more than the target — tighten the "
            "ratchet to TARGET_COGS_PCT")


class TestItStaysADial:
    def test_railway_can_still_move_it_without_a_deploy(self, monkeypatch):
        """The rule this module exists for: tuning is a config change,
        never a code change."""
        monkeypatch.setenv("PRICE_CHAT_PRICE", "11")
        assert pc.chat_price() == 11

    def test_a_typo_falls_back_to_the_shipped_default(self, monkeypatch):
        """Fail safe and loud, not silently free."""
        monkeypatch.setenv("PRICE_CHAT_PRICE", "12o")
        assert pc.chat_price() == 20

    def test_the_economics_helper_follows_the_dial(self, monkeypatch):
        monkeypatch.setenv("PRICE_CHAT_PRICE", "16")
        e = pc.chat_tank_economics()["starter"]
        assert e["turns_in_the_tank"] == pytest.approx(3000 / 16, rel=0.01)


class TestConciergeWasHeldBack:
    def test_it_did_not_move_on_one_data_point(self):
        """There is exactly ONE metered concierge call in production, at
        0.12c. Repricing a customer-facing surface off a single row would
        be inventing a number and calling it data."""
        assert pc.concierge_price() == 1

    def test_and_the_reason_is_written_down(self):
        import inspect
        src = inspect.getsource(pc.concierge_price)
        assert "anecdote" in src or "single row" in src, (
            "if concierge no longer tracks a Chief turn, the docstring has "
            "to say why, or the next reader treats it as an oversight")


class TestTheIdentityHolds:
    """Everything about this reduces to one relationship, and pinning it
    means the next repricing is arithmetic instead of guess-and-check.

        worst-case chat COGS % = cost_per_message / (chat_price x cents_per_credit)
    """

    @pytest.mark.parametrize("plan", ["starter", "professional", "practice"])
    def test_the_helper_agrees_with_the_formula(self, plan):
        rate = pc.tier_cents_per_credit()[plan]
        expected = pc.MEASURED_CHAT_COST_CENTS / (pc.chat_price() * rate) * 100
        assert pc.chat_tank_economics()[plan]["cogs_pct"] == pytest.approx(
            expected, rel=0.01)

    def test_the_cheapest_credit_is_the_binding_tier(self):
        """Practice was never specially broken — it is just the tier with
        the cheapest credit. Whichever tier that is sets the required
        chat_price, so a future tier priced more generously than Practice
        would silently become the new problem."""
        worst = max(pc.chat_tank_economics(),
                    key=lambda t: pc.chat_tank_economics()[t]["cogs_pct"])
        buyable = pc.purchasable_tier_cents_per_credit()
        assert worst == min(buyable, key=lambda t: buyable[t])

    def test_chat_price_clears_the_threshold_every_tier_needs(self):
        """chat_price x cents_per_credit >= cost / ceiling, for all of
        them — the single check the first repricing was missing."""
        needed = pc.MEASURED_CHAT_COST_CENTS / (ANY_TIER_COGS_CEILING_PCT / 100)
        for plan, rate in pc.purchasable_tier_cents_per_credit().items():
            assert pc.chat_price() * rate >= needed, (
                f"{plan}: {pc.chat_price()} x {rate:.3f} = "
                f"{pc.chat_price()*rate:.2f}, needs {needed:.2f}")

    def test_it_would_fail_at_the_previous_price(self, monkeypatch):
        """Guards the guard, again: at the old 12, now charged once per
        message, the bigger tiers must breach the ratchet, or this class
        is measuring nothing."""
        monkeypatch.setenv("PRICE_CHAT_PRICE", "12")
        e = pc.chat_tank_economics()
        assert e["practice"]["cogs_pct"] > ANY_TIER_COGS_CEILING_PCT
        assert e["professional"]["cogs_pct"] > ANY_TIER_COGS_CEILING_PCT
