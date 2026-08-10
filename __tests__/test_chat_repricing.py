"""A Chief turn is priced against what a Chief turn costs.

margin.py said it in its own docstring and could not act on it: "a Chief
turn sells for between 1.490c (founder) and 2.633c (starter) and costs
7.16c at the mean, 19.84c at p95. Every tier loses money on conversation
and makes it back on builds. That is a decision to take deliberately or
not at all, and it cannot be taken while the number is invisible."

The number is visible now. 640 real turns in api_usage, 2026-07-23 to
08-10: mean 7.37c, p50 5.18c, p95 20.15c, max 52.55c — which confirms
the estimate rather than overturning it.

At 1 credit per turn the credit had stopped being a currency. A build is
600 credits for ~$2.00 of cost, about 0.333c of COGS per credit; a turn
at 7.37c was sold for one. Twenty-two times more expensive per credit
than a build, in the same wallet.

These tests pin the RELATIONSHIP, not the digit. A price is allowed to
move — that is the entire point of pricing_config — but it is not
allowed to drift back to a token value, and the tank is not allowed to
quietly become unfundable again.
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
ENTRY_TIER_COGS_CEILING_PCT = 40.0
ANY_TIER_COGS_CEILING_PCT = 70.0


class TestThePriceReflectsTheCost:
    def test_a_turn_is_no_longer_a_token_price(self):
        """1 credit was not a price, it was a placeholder. Anything in
        low single digits means the credit is not tracking cost."""
        assert pc.chat_price() >= 5, (
            f"chat_price is {pc.chat_price()} — at 7.37c a turn, that is "
            f"back to selling conversation below cost in credit terms")

    def test_it_is_not_so_high_the_product_stops_working(self):
        """Strict parity with a build's implied credit cost is 22, which
        leaves a Starter four turns a day. A repricing that fixes the
        spreadsheet by breaking the product is not a fix."""
        starter_turns = pc.chat_tank_economics()["starter"]["turns_in_the_tank"]
        assert starter_turns >= 200, (
            f"a Starter gets {starter_turns:.0f} turns a month — too few for "
            f"something sold as a chief of staff you talk to")

    def test_the_measured_cost_is_recorded_not_guessed(self):
        assert 5.0 <= pc.MEASURED_CHAT_COST_CENTS <= 12.0, (
            "the measured cost constant drifted somewhere implausible — "
            "re-measure against api_usage before moving it")


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
        """The floor. Above 100% the customer costs more than they pay,
        which is where every tier sat before this change: 280%, 370%,
        462%."""
        e = pc.chat_tank_economics()[plan]
        assert e["cogs_pct"] < 100.0, (
            f"{plan} at full-tank chat costs {e['cogs_pct']}% of revenue")
        assert e["cogs_pct"] <= ANY_TIER_COGS_CEILING_PCT, (
            f"{plan} is at {e['cogs_pct']}% — above the ceiling this "
            f"repricing was solved against")

    def test_the_bigger_tiers_run_hotter_and_that_is_known(self):
        """Credits per dollar go UP with tier while a turn's cost does
        not, so one chat price cannot flatten this. Asserting the shape
        keeps it from being rediscovered as a surprise — the lever is
        tank SIZE, and Practice is the one to look at."""
        e = pc.chat_tank_economics()
        assert e["practice"]["cogs_pct"] > e["starter"]["cogs_pct"]

    def test_it_would_fail_at_the_old_price(self, monkeypatch):
        """Guards the guard. If these ceilings passed at 1 credit too,
        they would be measuring nothing."""
        monkeypatch.setenv("PRICE_CHAT_PRICE", "1")
        assert pc.chat_price() == 1
        e = pc.chat_tank_economics()["starter"]
        assert e["cogs_pct"] > 100.0, (
            "at 1 credit a turn the entry tier should be underwater — if it "
            "is not, this suite is not measuring what it claims")


class TestItStaysADial:
    def test_railway_can_still_move_it_without_a_deploy(self, monkeypatch):
        """The rule this module exists for: tuning is a config change,
        never a code change."""
        monkeypatch.setenv("PRICE_CHAT_PRICE", "11")
        assert pc.chat_price() == 11

    def test_a_typo_falls_back_to_the_shipped_default(self, monkeypatch):
        """Fail safe and loud, not silently free."""
        monkeypatch.setenv("PRICE_CHAT_PRICE", "8o")
        assert pc.chat_price() == 8

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
