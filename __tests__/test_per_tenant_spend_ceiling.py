"""One runaway tenant stops taking Chief offline for everybody else.

spend_guard summed api_usage across the whole platform and compared it
to one shared ceiling. When that ceiling was crossed, every AI entry
point soft-blocked — for every business at once. So roughly fifty
dollars of one account's loop paused Chief for every other paying
practitioner, and the people cut off were precisely the ones who had
done nothing.

There are two ceilings now. The per-tenant one should be what fires in
practice, blocking only the account that is running away. The platform
one stays as the backstop for what a per-tenant ceiling structurally
cannot catch: many tenants drifting up at once, and spend attributed to
no tenant at all.

The tests that matter most here are the isolation ones — a busy business
must NOT block a quiet one — and the fail-open ones, because a spend
guard that starts refusing calls when Supabase hiccups is a worse
outage than the one it prevents.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import billing_context
import spend_guard

BUSY = "11111111-1111-1111-1111-111111111111"
QUIET = "22222222-2222-2222-2222-222222222222"


def _rows(*pairs):
    """(business_id, dollars) -> api_usage rows."""
    return [{"business_id": b, "cost_cents": d * 100.0} for b, d in pairs]


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    """Clear the 60s cache and the alert dedup between tests, and keep
    every test off the network and away from push notifications."""
    spend_guard._cache_at = 0.0
    spend_guard._cache_total_cents = 0.0
    spend_guard._cache_by_business = {}
    spend_guard._alerted.clear()
    monkeypatch.setattr(spend_guard, "_push_owner",
                        lambda *a, **k: None)
    monkeypatch.delenv("SPEND_GUARD", raising=False)
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", "50")
    monkeypatch.setenv("DAILY_SPEND_CAP_PER_BUSINESS_USD", "25")
    token = billing_context._CURRENT.set(None)
    yield
    billing_context._CURRENT.reset(token)
    spend_guard._cache_at = 0.0
    spend_guard._alerted.clear()


def _usage(monkeypatch, rows):
    monkeypatch.setattr(spend_guard.sb_clients, "sb_get_as_service",
                        lambda path: rows)


class TestIsolation:
    """The whole point of the change."""

    def test_a_runaway_tenant_is_blocked(self, monkeypatch):
        _usage(monkeypatch, _rows((BUSY, 30)))
        assert spend_guard.over_budget(BUSY) is True

    def test_and_a_quiet_tenant_beside_it_is_not(self, monkeypatch):
        """This is the assertion the old guard could not have passed:
        $30 on one business used to block everyone."""
        _usage(monkeypatch, _rows((BUSY, 30), (QUIET, 2)))
        assert spend_guard.over_budget(QUIET) is False

    def test_the_quiet_tenant_is_blocked_once_the_PLATFORM_ceiling_goes(
            self, monkeypatch):
        """The backstop still works. Several tenants under their own
        ceilings can still add up to a platform emergency, and then
        everyone does stop — deliberately."""
        _usage(monkeypatch, _rows((BUSY, 24), ("b3", 24), (QUIET, 2)))
        assert spend_guard.over_budget(QUIET) is True

    def test_unattributed_spend_counts_platform_only(self, monkeypatch):
        """Rows with no business_id (platform jobs, or anything not yet
        attributed) must not be chargeable to a tenant — otherwise a
        per-tenant ceiling could be tripped by spend nobody caused."""
        _usage(monkeypatch, _rows((None, 40), (QUIET, 1)))
        assert spend_guard.today_spend_cents(business_id=QUIET) == 100.0
        assert spend_guard.today_spend_cents() == 4100.0
        assert spend_guard.over_budget(QUIET) is False


class TestTheAmbientTenant:
    """over_budget() defaults to the billing context, which is why the
    existing call sites did not have to change."""

    def test_context_selects_the_tenant(self, monkeypatch):
        _usage(monkeypatch, _rows((BUSY, 30), (QUIET, 1)))
        with billing_context.bill_to(BUSY):
            assert spend_guard.over_budget() is True
        with billing_context.bill_to(QUIET):
            assert spend_guard.over_budget() is False

    def test_no_context_falls_back_to_the_platform_ceiling(self, monkeypatch):
        """Not to "allow everything" — an unattributed caller is still
        held to the platform number."""
        _usage(monkeypatch, _rows((BUSY, 30)))
        assert spend_guard.over_budget() is False
        _usage(monkeypatch, _rows((BUSY, 30), ("b3", 25)))
        spend_guard._cache_at = 0.0
        assert spend_guard.over_budget() is True

    def test_an_explicit_business_beats_the_context(self, monkeypatch):
        _usage(monkeypatch, _rows((BUSY, 30), (QUIET, 1)))
        with billing_context.bill_to(QUIET):
            assert spend_guard.over_budget(BUSY) is True


class TestBoundaries:
    def test_exactly_at_the_ceiling_blocks(self, monkeypatch):
        _usage(monkeypatch, _rows((BUSY, 25)))
        assert spend_guard.over_budget(BUSY) is True

    def test_a_cent_under_does_not(self, monkeypatch):
        _usage(monkeypatch, [{"business_id": BUSY, "cost_cents": 2499.0}])
        assert spend_guard.over_budget(BUSY) is False

    def test_the_per_business_cap_is_configurable(self, monkeypatch):
        monkeypatch.setenv("DAILY_SPEND_CAP_PER_BUSINESS_USD", "5")
        _usage(monkeypatch, _rows((BUSY, 6)))
        assert spend_guard.over_budget(BUSY) is True

    @pytest.mark.parametrize("junk", ["", "abc", "None"])
    def test_a_malformed_cap_falls_back_rather_than_crashing(
            self, monkeypatch, junk):
        monkeypatch.setenv("DAILY_SPEND_CAP_PER_BUSINESS_USD", junk)
        assert spend_guard._business_cap_cents() == 2500.0

    def test_the_per_business_ceiling_sits_below_the_platform_one(self):
        """A per-tenant ceiling at or above the platform ceiling could
        never fire first, which would leave the shared-fate behaviour
        exactly as it was."""
        assert spend_guard._business_cap_cents() < spend_guard._cap_cents()


class TestFailOpen:
    """A spend guard that blocks on its own errors is a worse outage
    than the one it exists to prevent."""

    def test_a_read_failure_allows_the_call(self, monkeypatch):
        def _boom(path):
            raise RuntimeError("supabase down")
        monkeypatch.setattr(spend_guard.sb_clients, "sb_get_as_service", _boom)
        assert spend_guard.over_budget(BUSY) is False

    def test_the_off_switch_still_works(self, monkeypatch):
        monkeypatch.setenv("SPEND_GUARD", "off")
        _usage(monkeypatch, _rows((BUSY, 999)))
        assert spend_guard.over_budget(BUSY) is False

    def test_garbage_rows_do_not_raise(self, monkeypatch):
        _usage(monkeypatch, [{"business_id": BUSY},
                             {"cost_cents": None},
                             {"business_id": None, "cost_cents": "x"}])
        assert spend_guard.over_budget(BUSY) in (True, False)


class TestOneQuery:
    def test_both_ceilings_come_from_a_single_read(self, monkeypatch):
        """A per-business SUM issued per tenant would multiply query load
        by the number of active tenants, on the hot path of every AI
        call. One read, aggregated in memory, serves both."""
        calls = []

        def _get(path):
            calls.append(path)
            return _rows((BUSY, 30), (QUIET, 1))

        monkeypatch.setattr(spend_guard.sb_clients, "sb_get_as_service", _get)
        spend_guard.over_budget(BUSY)
        spend_guard.over_budget(QUIET)
        spend_guard.today_spend_cents()
        assert len(calls) == 1, f"expected 1 read, got {len(calls)}"

    def test_the_read_asks_for_the_business_column(self, monkeypatch):
        """Without business_id in the select, every per-tenant sum would
        be zero and the new ceiling would never fire — the failure would
        look exactly like 'nobody is over budget'."""
        seen = {}

        def _get(path):
            seen["path"] = path
            return []

        monkeypatch.setattr(spend_guard.sb_clients, "sb_get_as_service", _get)
        spend_guard.today_spend_cents(force=True)
        assert "business_id" in seen["path"]
        assert "cost_cents" in seen["path"]


class TestAlerting:
    def test_tenant_and_platform_alerts_do_not_share_a_dedup_slot(
            self, monkeypatch):
        """They mean different things — 'one customer is looping' versus
        'the platform is about to go dark' — and the owner needs both."""
        pushed = []
        monkeypatch.setattr(spend_guard, "_push_owner",
                            lambda spent, cap, mark, scope="platform":
                            pushed.append(scope))
        _usage(monkeypatch, _rows((BUSY, 30), ("b3", 21)))
        spend_guard.over_budget(BUSY)
        assert "platform" in pushed
        assert BUSY in pushed

    def test_one_alert_per_threshold_per_scope(self, monkeypatch):
        pushed = []
        monkeypatch.setattr(spend_guard, "_push_owner",
                            lambda spent, cap, mark, scope="platform":
                            pushed.append((scope, mark)))
        _usage(monkeypatch, _rows((BUSY, 30)))
        spend_guard.over_budget(BUSY)
        spend_guard.over_budget(BUSY)
        spend_guard.over_budget(BUSY)
        assert pushed.count((BUSY, 1.0)) == 1


class TestCallSites:
    def test_chief_passes_the_business_explicitly(self):
        """_call_claude is reached from paths that never went through
        chief_chat and so carry no ambient context. There, the parameter
        is the only thing keeping one tenant from being measured against
        the shared platform ceiling."""
        import inspect

        import chief_of_staff
        src = inspect.getsource(chief_of_staff._call_claude)
        assert "spend_guard.over_budget(business_id)" in src

    def test_ai_proxy_attributes_before_it_checks(self):
        """over_budget() reads the ambient tenant to decide WHICH
        ceiling applies. Attribute after the check and every proxy call
        is measured against the platform ceiling alone — the shared-fate
        behaviour this arc removes, quietly restored."""
        import inspect

        import ai_proxy
        src = inspect.getsource(ai_proxy)
        set_at = src.index("billing_context.set_current")
        check_at = src.index("spend_guard.over_budget")
        assert set_at < check_at, (
            "ai_proxy checks the ceiling before it knows whose it is")
