"""Revenue minus what it cost to serve.

Nobody had ever computed this. pricing_config knows every price and
pack_economics checks the prices against each other; api_usage knows what
every call cost. Nothing subtracted the second from the first, so the
platform was priced against its own price list rather than against its
bill.

The audit's number: a Chief turn sells for 1.490c-2.633c and costs 7.16c
mean / 19.84c p95. These tests exist so that shape is visible and stays
arithmetically honest.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import margin
import pricing_config
import sb_clients


BIZ_A = "aaaaaaaa-0000-0000-0000-000000000001"
BIZ_B = "bbbbbbbb-0000-0000-0000-000000000002"


def _wire(monkeypatch, businesses, usage, purchases=None):
    def _get(path):
        if path.startswith("/businesses?id=eq."):
            wanted = path.split("id=eq.")[1].split("&")[0]
            return [b for b in businesses if b["id"] == wanted]
        if path.startswith("/businesses?"):
            return businesses
        if path.startswith("/api_usage?"):
            return usage
        if path.startswith("/credit_ledger?"):
            return purchases or []
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)


STARTER = pricing_config.tier_price_cents()["starter"]


class TestOneBusiness:
    def test_a_profitable_account(self, monkeypatch):
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "active"}],
              [{"business_id": BIZ_A, "cost_cents": 100.0}])
        m = margin.business_margin(BIZ_A, days=30)
        assert m["revenue_cents"] == pytest.approx(STARTER)
        assert m["cogs_cents"] == pytest.approx(100.0)
        assert m["margin_cents"] == pytest.approx(STARTER - 100.0)
        assert m["underwater"] is False

    def test_an_underwater_account_is_flagged(self, monkeypatch):
        """The case the audit found: a Starter customer who loves Chief.
        34 turns a day at 7.16c is ~$73/mo of COGS against a $79 tier."""
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "active"}],
              [{"business_id": BIZ_A, "cost_cents": STARTER + 5000}])
        m = margin.business_margin(BIZ_A, days=30)
        assert m["margin_cents"] < 0
        assert m["underwater"] is True

    def test_a_cancelled_account_earns_no_revenue(self, monkeypatch):
        """Still costs money if it is still calling."""
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "canceled"}],
              [{"business_id": BIZ_A, "cost_cents": 250.0}])
        m = margin.business_margin(BIZ_A, days=30)
        assert m["revenue_cents"] == 0
        assert m["cogs_cents"] == pytest.approx(250.0)
        assert m["underwater"] is False, "not underwater — it is not a customer"

    def test_margin_pct_is_none_not_zero_without_revenue(self, monkeypatch):
        """0% reads as break-even; the truth is undefined."""
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": None,
                "subscription_status": None}],
              [])
        assert margin.business_margin(BIZ_A)["margin_pct"] is None

    def test_the_window_prorates_the_subscription(self, monkeypatch):
        """A 7-day view must not be compared against a monthly bill."""
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "active"}],
              [])
        week = margin.business_margin(BIZ_A, days=7)["revenue_cents"]
        # abs=0.01: figures are rounded to the cent on the way out, so a
        # tolerance finer than a cent is testing the rounding, not the
        # proration.
        assert week == pytest.approx(STARTER * 7 / 30.0, abs=0.01)


class TestPlatform:
    def test_tiers_aggregate_and_worst_comes_first(self, monkeypatch):
        _wire(monkeypatch, [
            {"id": BIZ_A, "name": "A", "subscription_plan": "starter",
             "subscription_status": "active"},
            {"id": BIZ_B, "name": "B", "subscription_plan": "practice",
             "subscription_status": "active"},
        ], [
            {"business_id": BIZ_A, "cost_cents": STARTER * 3},   # deeply underwater
            {"business_id": BIZ_B, "cost_cents": 500.0},
        ])
        p = margin.platform_margin(days=30)
        assert p["totals"]["businesses"] == 2
        assert p["totals"]["underwater"] == 1
        assert set(p["by_tier"]) == {"starter", "practice"}
        assert p["by_tier"]["starter"]["underwater"] == 1
        assert p["worst"][0]["business_id"] == BIZ_A

    def test_unattributed_spend_is_reported_separately(self, monkeypatch):
        """AI spend with no business_id is real money with no customer
        attached. Folding it into a tier would blame someone for it;
        dropping it would hide it."""
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "active"}],
              [{"business_id": BIZ_A, "cost_cents": 10.0},
               {"business_id": None, "cost_cents": 640.0}])
        p = margin.platform_margin()
        assert p["unattributed_cogs_cents"] == pytest.approx(640.0)
        assert p["attributed_cogs_cents"] == pytest.approx(10.0)
        assert p["totals"]["cogs_cents"] == pytest.approx(650.0)

    def test_the_caveats_are_carried_with_the_numbers(self, monkeypatch):
        """A margin figure without its caveats attached is misleading, so
        they travel in the payload rather than in a doc nobody opens.

        The sentence this used to assert — "real margin is at least this
        good, never worse" — was true only while pack sales were missing
        entirely. It is now false, and a caveat that is false is worse
        than no caveat, because it is read as reassurance."""
        _wire(monkeypatch, [], [])
        p = margin.platform_margin()
        joined = " ".join(p["caveats"]).lower()
        assert "pack" in joined
        assert "at least this good" not in joined
        assert "guess" in joined, (
            "the estimated-pack caveat must say it is not a measurement")

    def test_inactive_accounts_are_excluded_from_tier_rollups(self, monkeypatch):
        _wire(monkeypatch, [
            {"id": BIZ_A, "name": "A", "subscription_plan": "starter",
             "subscription_status": "canceled"},
        ], [])
        p = margin.platform_margin()
        assert p["by_tier"] == {}
        assert p["totals"]["active"] == 0


class TestItNeverBlowsUp:
    def test_a_dead_database_returns_zeros(self, monkeypatch):
        """A billing panel that 500s tells you less than one showing a
        zero next to a label."""
        def _boom(path):
            raise RuntimeError("supabase down")
        monkeypatch.setattr(sb_clients, "sb_get_as_service", _boom)
        p = margin.platform_margin()
        assert p["totals"]["businesses"] == 0
        assert margin.business_margin(BIZ_A)["revenue_cents"] == 0

    def test_malformed_cost_rows_are_skipped(self, monkeypatch):
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "active"}],
              [{"business_id": BIZ_A, "cost_cents": "not-a-number"},
               {"business_id": BIZ_A, "cost_cents": 25.0}])
        assert margin.business_margin(BIZ_A)["cogs_cents"] == pytest.approx(25.0)

    def test_the_window_uses_z_form_timestamps(self):
        """isoformat's +00:00 makes PostgREST return zero rows silently —
        which would render as 'no spend at all' rather than an error."""
        s = margin._window_start_iso(30)
        assert s.endswith("Z") and "+00:00" not in s


class TestWiring:
    def test_both_endpoints_are_owner_gated(self):
        import platform_console
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(platform_console.router)
        found = 0
        for r in app.routes:
            if getattr(r, "path", "").startswith("/platform/margin"):
                found += 1
                names = [d.call.__name__ for d in r.dependant.dependencies
                         if getattr(d, "call", None)]
                assert "require_owner" in names, f"{r.path} is not owner-gated"
        assert found == 2, f"expected 2 margin routes, found {found}"


class TestPackRevenue:
    """Credit-pack sales used to be missing from margin entirely.

    credit_ledger recorded how many UNITS moved and never how much money
    did, so the panel understated real margin by the value of every pack
    ever sold. credit_ledger.cents (2026-08-09) captures the amount
    charged, at purchase.
    """

    def _pack(self, biz, cents=None, source="stripe:pack_medium"):
        row = {"business_id": biz, "source": source}
        if cents is not None:
            row["cents"] = cents
        return row

    def test_a_captured_purchase_is_revenue(self, monkeypatch):
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "active"}],
              [],
              [self._pack(BIZ_A, 2500)])
        m = margin.business_margin(BIZ_A, days=30)
        assert m["pack_revenue_cents"] == pytest.approx(2500.0)
        assert m["subscription_revenue_cents"] == pytest.approx(STARTER)
        assert m["revenue_cents"] == pytest.approx(STARTER + 2500.0)

    def test_an_uncaptured_purchase_is_estimated_and_kept_out_of_revenue(
            self, monkeypatch):
        """The honesty rule. A row predating the cents column is priced
        from today's list — that is a guess, and margin is a number
        decisions get taken on. It is reported beside the total, never
        inside it."""
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "active"}],
              [],
              [self._pack(BIZ_A, None, "stripe:pack_medium")])
        m = margin.business_margin(BIZ_A, days=30)
        medium = pricing_config.credit_packs()["medium"]["cents"]
        assert m["pack_revenue_estimated_cents"] == pytest.approx(medium)
        assert m["pack_revenue_cents"] == 0
        assert m["revenue_cents"] == pytest.approx(STARTER)

    def test_a_purchase_naming_an_unknown_pack_is_not_invented(
            self, monkeypatch):
        """Excluded rather than guessed at — but logged, because
        silently dropping revenue looks identical to having none."""
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "active"}],
              [],
              [self._pack(BIZ_A, None, "stripe:pack_gigantic")])
        m = margin.business_margin(BIZ_A, days=30)
        assert m["pack_revenue_estimated_cents"] == 0
        assert m["pack_revenue_cents"] == 0

    def test_pack_revenue_reaches_the_platform_totals(self, monkeypatch):
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "active"}],
              [],
              [self._pack(BIZ_A, 1000), self._pack(BIZ_A, 5000)])
        p = margin.platform_margin()
        assert p["totals"]["pack_revenue_cents"] == pytest.approx(6000.0)
        assert p["totals"]["revenue_cents"] == pytest.approx(STARTER + 6000.0)

    def test_the_estimate_is_reported_outside_the_totals_block(
            self, monkeypatch):
        """Structural, not cosmetic: inside `totals` it would eventually
        be summed with the rest by something downstream."""
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "active"}],
              [], [self._pack(BIZ_A, None)])
        p = margin.platform_margin()
        assert "pack_revenue_estimated_cents" in p
        assert "pack_revenue_estimated_cents" not in p["totals"]

    def test_a_cancelled_business_burning_prepaid_credits_still_counts(
            self, monkeypatch):
        """Credits never expire, so they outlive the plan that bought
        them. Such a business has real revenue and real COGS, and the
        rollup used to skip every inactive row — which made the tier
        look more profitable than it was."""
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "canceled"}],
              [{"business_id": BIZ_A, "cost_cents": 4000.0}],
              [self._pack(BIZ_A, 1000)])
        p = margin.platform_margin()
        assert p["by_tier"], "a cancelled account with spend vanished from the rollup"
        assert p["by_tier"]["starter"]["cogs_cents"] == pytest.approx(4000.0)
        assert p["by_tier"]["starter"]["revenue_cents"] == pytest.approx(1000.0)

    def test_such_a_business_is_flagged_underwater(self, monkeypatch):
        """It is being served at a loss, which is the whole point of the
        flag. It was excluded because the check required `active`."""
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "canceled"}],
              [{"business_id": BIZ_A, "cost_cents": 4000.0}],
              [self._pack(BIZ_A, 1000)])
        m = margin.business_margin(BIZ_A)
        assert m["active"] is False
        assert m["underwater"] is True

    def test_a_truly_dormant_account_still_stays_out(self, monkeypatch):
        """Guards the guard: the rollup change must not readmit every
        cancelled account that costs and earns nothing."""
        _wire(monkeypatch,
              [{"id": BIZ_A, "name": "A", "subscription_plan": "starter",
                "subscription_status": "canceled"}],
              [], [])
        p = margin.platform_margin()
        assert p["by_tier"] == {}

    def test_a_ledger_read_failure_does_not_take_the_panel_down(
            self, monkeypatch):
        def _get(path):
            if path.startswith("/credit_ledger?"):
                raise RuntimeError("postgrest down")
            if path.startswith("/businesses?"):
                return [{"id": BIZ_A, "name": "A",
                         "subscription_plan": "starter",
                         "subscription_status": "active"}]
            return []
        monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
        m = margin.business_margin(BIZ_A)
        assert m["pack_revenue_cents"] == 0
        assert m["revenue_cents"] == pytest.approx(STARTER)


class TestTheLedgerCapturesTheMoney:
    def test_grant_pack_writes_the_price_it_charged(self, monkeypatch):
        """Without this the cents column exists and stays empty, and
        pack revenue reads zero forever while looking like it works."""
        import credit_ledger
        posted = {}
        monkeypatch.setattr(credit_ledger.sb_clients, "sb_post_as_service",
                            lambda path, row: posted.update(row) or [{"id": "x"}])
        assert credit_ledger.grant_pack(BIZ_A, "medium", "pi_test_1") is True
        expected = pricing_config.credit_packs()["medium"]["cents"]
        assert posted["cents"] == expected
        assert posted["kind"] == "purchase"

    def test_the_captured_price_comes_from_the_live_table(self, monkeypatch):
        """Not the import-time snapshot. #450 fixed exactly this on the
        checkout side and left the grant side behind, so a customer could
        be charged from one source and credited from another."""
        import credit_ledger
        posted = {}
        monkeypatch.setattr(credit_ledger, "credit_packs",
                            lambda: {"medium": {"units": 9, "cents": 4242}})
        monkeypatch.setattr(credit_ledger.sb_clients, "sb_post_as_service",
                            lambda path, row: posted.update(row) or [{"id": "x"}])
        credit_ledger.grant_pack(BIZ_A, "medium", "pi_test_2")
        assert posted["cents"] == 4242
