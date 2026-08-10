"""Topping up never beats upgrading.

Packs shipped at 1.000c / 0.909c / 0.833c per credit against a 1.490c
founder credit and a 1.596c Practice credit — 56% to 67% of the cheapest
subscription. A heavy user was rationally better off staying on the
smallest plan and buying packs forever, which makes the tier ladder
decorative. warn_on_pack_economics() has been logging it at every boot.

The awkward part, and the reason this is arithmetic rather than taste:
the two invariants pull in OPPOSITE directions.

    must not undercut a subscription   -> fewer credits per dollar
    must complete a build with change  -> more credits per dollar

A build is 600 credits, so at $10 the window is 601..626 units. The
small pack lives in a 25-unit gap between two rules.

These tests pin the invariants, not the numbers. Prices are dials and
are expected to move; what may not happen is the ladder inverting again,
or a pack going back to being unable to finish one action.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import pricing_config as pc


class TestTheLadderHolds:
    def test_no_pack_undercuts_any_subscription(self):
        e = pc.pack_economics()
        bad = {n: r["cents_per_credit"] for n, r in e["packs"].items()
               if r["undercuts_subscription"]}
        assert not bad, (
            f"{bad} are cheaper per credit than the {e['cheapest_tier']} rate "
            f"({e['cheapest_tier_cents_per_credit']}c)")

    def test_no_pack_undercuts_a_tier_a_CUSTOMER_CAN_BUY(self):
        """The check that actually decides "top up or upgrade?".

        The original invariant compared against the cheapest tier of
        any kind, which is the founder promotion — 50 seats, closed. A
        pack could clear that and still be cheaper than every plan a new
        customer is allowed to choose, passing the guard while doing the
        exact thing the guard exists to stop.
        """
        e = pc.pack_economics()
        bad = {n: r["cents_per_credit"] for n, r in e["packs"].items()
               if r["undercuts_buyable_tier"]}
        assert not bad, (
            f"{bad} undercut {e['cheapest_buyable_tier']} at "
            f"{e['cheapest_buyable_cents_per_credit']}c — topping up beats "
            f"upgrading")

    def test_founder_is_excluded_as_promotional_not_forgotten(self):
        assert "founder" in pc.PROMOTIONAL_TIERS
        assert "founder" in pc.tier_cents_per_credit()
        assert "founder" not in pc.purchasable_tier_cents_per_credit()

    def test_buying_bigger_still_pays(self):
        """A volume ladder that does not reward volume is just three
        prices."""
        e = pc.pack_economics()["packs"]
        rates = [e[n]["cents_per_credit"] for n in ("small", "medium", "large")]
        assert rates == sorted(rates, reverse=True), (
            f"pack rates {rates} do not improve with size")


class TestAPackStillBuysSomething:
    @pytest.mark.parametrize("pack", ["small", "medium", "large"])
    def test_it_completes_a_build_with_change(self, pack):
        """The rule the 2026-08-08 rescale existed for: a top-up that
        cannot finish one action is a bad checkout."""
        r = pc.pack_economics()["packs"][pack]
        assert r["completes_an_action_with_change"], (
            f"{pack} has {r['units']} credits and a build costs "
            f"{pc.pack_economics()['typical_build_credits']}")

    def test_the_small_pack_is_tight_and_that_is_known(self):
        """Not a failure — a documented squeeze. At $10 the window
        between the two invariants is 25 units wide, so the small pack
        clears a build by very little. If it should breathe, the lever is
        the PRICE POINT ($15), not the invariants."""
        r = pc.pack_economics()["packs"]["small"]
        assert 0 < r["credits_left_after_one_build"] < 200


class TestItIsStillAllDials:
    def test_units_are_env_overridable(self, monkeypatch):
        monkeypatch.setenv("PRICE_PACK_SMALL_UNITS", "777")
        assert pc.credit_packs()["small"]["units"] == 777

    def test_the_guard_would_catch_a_bad_override(self, monkeypatch):
        """Guards the guard: if this passed with an absurdly generous
        pack, the invariant tests above would be measuring nothing."""
        monkeypatch.setenv("PRICE_PACK_SMALL_UNITS", "100000")
        e = pc.pack_economics()
        assert e["packs"]["small"]["undercuts_subscription"] is True
        assert e["warnings"], "an obviously underpriced pack raised no warning"

    def test_boot_time_warning_stays_silent_when_clean(self, caplog):
        pc.warn_on_pack_economics()
        assert not [r for r in caplog.records if "pack economics" in r.message]
