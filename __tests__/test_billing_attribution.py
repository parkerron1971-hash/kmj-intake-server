"""Every paid AI call names the business it was spent for.

api_usage has a business_id column and 42 of the 49 direct
log_api_usage call sites fill it. The gap was llm_call._meter: ONE call
site standing in for 22 modules that reach the seam and never metered
themselves — brand_engine, growth_engine, discovery, foundation_agent,
contract_agent, module_spec_generator, site_llm, studio_designer_agent
and the rest. Their rows landed with business_id NULL.

That was survivable while the spend ceiling was a single global number,
because a global sum does not care whose spend it is. It stops being
survivable the moment the ceiling is per-tenant: a per-business sum that
silently omits 22 modules is a control that reports safety it is not
providing. So attribution lands FIRST, on its own, and this file is
where it is held down.

The mechanism is a ContextVar rather than a threaded parameter, and the
tests below care about three things in particular:

  * an explicit business_id still wins (the 42 good call sites must not
    change behaviour),
  * the context never leaks between businesses,
  * attribution follows an ownership check, never precedes one.

That last one is not tidiness. Once a per-tenant ceiling exists, an
account that can name someone else's business can spend that business's
allowance.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import billing_context

BIZ_A = "aaaaaaaa-1111-1111-1111-111111111111"
BIZ_B = "bbbbbbbb-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _clean_context():
    """Each test starts with no ambient tenant."""
    token = billing_context._CURRENT.set(None)
    yield
    billing_context._CURRENT.reset(token)


class TestTheContext:
    def test_starts_empty(self):
        assert billing_context.current() is None

    def test_set_and_read(self):
        billing_context.set_current(BIZ_A)
        assert billing_context.current() == BIZ_A

    def test_bill_to_restores_the_previous_tenant(self):
        """A scheduled job looping over tenants must not leak one
        business's id into the next iteration — that misattributes real
        money, and it would do so silently."""
        billing_context.set_current(BIZ_A)
        with billing_context.bill_to(BIZ_B):
            assert billing_context.current() == BIZ_B
        assert billing_context.current() == BIZ_A

    def test_bill_to_restores_even_when_the_body_raises(self):
        billing_context.set_current(BIZ_A)
        with pytest.raises(ValueError):
            with billing_context.bill_to(BIZ_B):
                raise ValueError("boom")
        assert billing_context.current() == BIZ_A

    @pytest.mark.parametrize("empty", [None, "", 0])
    def test_an_empty_business_is_a_no_op_not_an_error(self, empty):
        """Platform-level work (health checks, cross-tenant jobs) has no
        tenant. It should stay unattributed rather than borrow one."""
        billing_context.set_current(BIZ_A)
        billing_context.set_current(empty)
        assert billing_context.current() == BIZ_A
        with billing_context.bill_to(empty):
            assert billing_context.current() == BIZ_A

    def test_concurrent_tasks_do_not_see_each_others_tenant(self):
        """The property that makes a ContextVar safe here at all. Two
        practitioners' turns run in the same process at the same time."""
        seen = {}

        async def one(name, biz, delay):
            with billing_context.bill_to(biz):
                await asyncio.sleep(delay)
                seen[name] = billing_context.current()

        async def go():
            await asyncio.gather(one("a", BIZ_A, 0.02),
                                 one("b", BIZ_B, 0.01))

        asyncio.run(go())
        assert seen == {"a": BIZ_A, "b": BIZ_B}


@pytest.fixture
def captured_row(monkeypatch):
    """Intercept the api_usage row on its way to PostgREST.

    log_api_usage_sync calls httpx.post at MODULE level (not through a
    Client), so that is what gets replaced. Patching Client instead let
    the real request escape to the network — which the logger swallows
    by design, so the test failed on a missing capture rather than on
    anything it meant to assert.
    """
    posted = {}

    class _Resp:
        status_code = 201
        text = ""

        def json(self):
            return {}

    def _post(url, headers=None, json=None, **k):
        posted["body"] = json
        return _Resp()

    import api_usage_logger
    monkeypatch.setattr(api_usage_logger, "SUPABASE_URL", "https://x.test")
    monkeypatch.setattr(api_usage_logger, "SUPABASE_SERVICE_ROLE_KEY", "svc")
    monkeypatch.setattr(api_usage_logger.httpx, "post", _post)
    return posted


class TestTheLoggerUsesIt:
    """api_usage_logger defaults business_id from the context. This is
    the single change that gives all 22 seam modules attribution."""


    def test_ambient_tenant_is_written(self, captured_row):
        posted = captured_row
        import api_usage_logger
        billing_context.set_current(BIZ_A)
        api_usage_logger.log_api_usage_sync(
            endpoint="llm:brand_engine", model="claude-sonnet-5",
            input_tokens=10, output_tokens=5)
        assert posted["body"]["business_id"] == BIZ_A

    def test_an_explicit_business_still_wins(self, captured_row):
        """The 42 call sites that pass their own id must be unaffected —
        a default that overrode them would silently rewrite correct
        attribution into ambient guesswork."""
        posted = captured_row
        import api_usage_logger
        billing_context.set_current(BIZ_A)
        api_usage_logger.log_api_usage_sync(
            endpoint="/ai/proxy", model="claude-sonnet-5",
            input_tokens=10, output_tokens=5, business_id=BIZ_B)
        assert posted["body"]["business_id"] == BIZ_B

    def test_no_context_leaves_the_field_absent(self, captured_row):
        """Unattributed must stay unattributed, not become a guess."""
        posted = captured_row
        import api_usage_logger
        api_usage_logger.log_api_usage_sync(
            endpoint="llm:platform_job", model="claude-sonnet-5",
            input_tokens=10, output_tokens=5)
        assert "business_id" not in posted["body"]


class TestTheSeamIsCovered:
    """The row that used to land NULL for all 22 seam modules.

    This goes through the REAL logger to the REAL row body. Stubbing
    log_api_usage_sync instead would only prove _meter called it — and
    _meter still passes no business_id of its own, so such a test would
    pass happily while every row continued to land unattributed. The
    assertion has to be on what PostgREST would receive.
    """

    class _Resp:
        status_code = 200

        def json(self):
            return {"model": "claude-sonnet-5",
                    "usage": {"input_tokens": 100, "output_tokens": 50}}

    def test_meter_attributes_the_ambient_tenant(self, captured_row):
        posted = captured_row
        import llm_call
        with billing_context.bill_to(BIZ_A):
            llm_call._meter(self._Resp(), {}, "brand_engine", 0.0)
        assert posted["body"]["endpoint"] == "llm:brand_engine"
        assert posted["body"]["business_id"] == BIZ_A

    def test_meter_without_a_tenant_stays_unattributed(self, captured_row):
        """Guards the guard: if business_id were being set from
        something other than the context, the test above would pass and
        this one would fail."""
        posted = captured_row
        import llm_call
        llm_call._meter(self._Resp(), {}, "brand_engine", 0.0)
        assert "business_id" not in posted["body"]


class TestAttributionFollowsAuthorization:
    """The ordering that stops attribution becoming an attack.

    business_access sets the tenant only after the role check passes. A
    refused caller must not be able to name the business a later row is
    billed to.
    """

    def test_business_access_sets_it_after_the_check_not_before(self):
        import inspect

        import business_access
        src = inspect.getsource(business_access)
        for fn in ("_dep", "assert_access"):
            body = src[src.index(f"def {fn}("):]
            body = body[:body.index("\n\ndef ")] if "\n\ndef " in body else body
            deny = body.index('detail="business not found"')
            attribute = body.index("billing_context.set_current")
            assert attribute > deny, (
                f"{fn} attributes spend BEFORE it refuses a stranger — a "
                f"caller with no role could name the tenant to bill")

    def test_ai_proxy_checks_the_role_before_attributing(self):
        """ai_proxy's business id comes from caller metadata with no RLS
        read behind it, so it is the one place the check has to be
        explicit rather than inherited."""
        import inspect

        import ai_proxy
        src = inspect.getsource(ai_proxy)
        assert "role_of" in src
        role_at = src.index("role_of(str(_cap_biz)")
        set_at = src.index("billing_context.set_current")
        assert role_at < set_at

    def test_chief_attributes_only_a_business_rls_returned(self):
        """Chief's id is caller-supplied too, but corroborated: the
        attribution sits inside `if biz_lite:`, and biz_lite is a row
        read under the practitioner's own JWT."""
        import inspect

        import chief_of_staff
        src = inspect.getsource(chief_of_staff.chief_chat)
        assert "billing_context.set_current(req.business_id)" in src
        guard = src.index("if biz_lite:")
        attribute = src.index("billing_context.set_current(req.business_id)")
        assert guard < attribute


class TestDrift:
    """The seam is one call site standing in for many modules. If it
    stops defaulting from the context, 22 modules go dark at once and
    nothing else in the suite would notice."""

    def test_the_logger_still_consults_the_context(self):
        import inspect

        import api_usage_logger
        src = inspect.getsource(api_usage_logger)
        # Both variants — sync and async — or half the callers regress.
        assert src.count("billing_context.current()") == 2, (
            "api_usage_logger must default business_id from the billing "
            "context in BOTH log_api_usage and log_api_usage_sync")

    def test_there_really_are_seam_modules_to_cover(self):
        """Guards the guard: if this drops to zero the sweep broke,
        rather than the problem being solved."""
        import re

        root = pathlib.Path(__file__).resolve().parent.parent
        markers = ("llm_call.post", "llm_call.apost", "llm_call.post_with",
                   "llm_call.sdk_client", "llm_call.astream")
        meters = ("log_api_usage", "log_api_usage_sync")
        n = 0
        for p in root.rglob("*.py"):
            s = str(p)
            if ("__pycache__" in s or "__tests__" in s
                    or p.name in ("llm_call.py", "model_ladder.py")):
                continue
            try:
                src = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if any(m in src for m in markers) and not any(m in src for m in meters):
                n += 1
        assert n > 10, f"sweep looks broken — found only {n} seam modules"
