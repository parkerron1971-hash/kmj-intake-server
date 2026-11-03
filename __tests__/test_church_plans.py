"""Church plans by size (Kevin, 2026-11-03: "I agree with the plan").

Small $79 (up to 100 on a Sunday), Growing $149 (100-250), Established $299
(250-500), Large $599 (500-1,500), sold only to churches and ministries.
Every church feature on every plan; the plan sets the room: office logins
3 / 8 / 15 / 35, texts 500 / 1,500 / 3,000 / 8,000, sermon clip hours
2 / 5 / 10 / 20, Chief credits 3,000 / 7,500 / 17,500 / 30,000. Leaders,
volunteers and members use the member app and never count as a login.
Pinned here:
  1. Kevin's numbers, and the economics floor the public ladder holds.
  2. Hidden until PLAN_CHURCH_OFFERED=1; churches and ministries only.
  3. What each plan includes, and upgrades that stay on the church ladder.
  4. The catalog, the price ids, and Stripe's ten-lookup-keys limit.
  5. Checkout: churches only, no discount codes (MINISTRY20 retires here).
  6. The plan cards say the size, the texts and the clip hours.
  7. Sermon clip hours follow the plan.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import billing_limits  # noqa: E402
import chief_models  # noqa: E402
import feature_gates as fg  # noqa: E402
import pricing_config  # noqa: E402
import stripe_billing as sb  # noqa: E402
from auth_supabase import AuthedUser  # noqa: E402

USER = AuthedUser(id="u-1", email="pastor@church.test", role="authenticated")
SMALL, GROWING, ESTABLISHED, LARGE = fg.CHURCH_PLANS


# ─── 1. the numbers ───────────────────────────────────────────────────

def test_the_ladder_is_kevins():
    assert fg.CHURCH_PLANS == ("church_small", "church_growing", "church_established", "church_large")
    assert pricing_config.church_price_cents() == {SMALL: 7900, GROWING: 14900, ESTABLISHED: 29900, LARGE: 59900}
    assert pricing_config.church_seats() == {SMALL: 3, GROWING: 8, ESTABLISHED: 15, LARGE: 35}
    assert pricing_config.church_texts_monthly() == {SMALL: 500, GROWING: 1500, ESTABLISHED: 3000, LARGE: 8000}
    assert pricing_config.church_clip_hours() == {SMALL: 2, GROWING: 5, ESTABLISHED: 10, LARGE: 20}
    assert pricing_config.church_credits() == {SMALL: 3000, GROWING: 7500, ESTABLISHED: 17500, LARGE: 30000}
    assert pricing_config.church_offer() == {"extra_texts_cents_per_thousand": 2000, "extra_login_cents": 1500,
                                             "move_months": 3, "founding_moves": 5,
                                             "multi_site_from_cents": 99900}


@pytest.mark.parametrize("plan", fg.CHURCH_PLANS)
def test_each_clears_the_chat_floor_and_the_trial(plan):
    cents = pricing_config.church_price_cents()[plan]
    credits = pricing_config.church_credits()[plan]
    assert pricing_config.chat_price() * (cents / credits) >= 18.43   # the public ladder's line
    assert credits > pricing_config.trial_credits()


@pytest.mark.parametrize("people,plan", [(0, SMALL), (40, SMALL), (100, SMALL), (101, GROWING), (250, GROWING),
                                         (251, ESTABLISHED), (500, ESTABLISHED), (501, LARGE), (1500, LARGE),
                                         (4000, LARGE)])
def test_a_church_lands_on_its_size(people, plan):
    assert pricing_config.church_plan_for_size(people) == plan


def test_names_and_thinking_follow_the_price():
    assert [billing_limits.PLAN_DISPLAY[p] for p in fg.CHURCH_PLANS] == [
        "Small Church", "Growing Church", "Established Church", "Large Church"]
    assert [chief_models.deep_analysis_label(p) for p in fg.CHURCH_PLANS] == [
        "Standard", "Advanced", "Maximum", "Maximum"]


# ─── 2. who can buy, and when ─────────────────────────────────────────

def test_hidden_until_offered_then_all_four_for_churches(monkeypatch):
    assert fg.audience_plans_for("church") == []
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    for kind in ("church", "ministry", "faith", "religious"):
        assert fg.audience_plans_for(kind) == list(fg.CHURCH_PLANS), kind
    for kind in ("nonprofit", "barber", "coach", "lawyer"):
        assert not set(fg.audience_plans_for(kind)) & set(fg.CHURCH_PLANS), kind


def test_offering_churches_doesnt_open_the_barber_plans(monkeypatch):
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    assert fg.audience_plans_for("barber") == []


# ─── 3. what each plan includes ───────────────────────────────────────

def test_every_church_plan_has_the_church_essentials():
    for plan in fg.CHURCH_PLANS:
        have = fg.plan_features(plan)
        # Own texting number (text-to-give), budgets + full reports, the donors report, sermon clips.
        for key in ("dedicated_sms_number", "reports_full", "vertical_reports", "ai_clips", "multi_seat",
                    "period_close", "marketing_week"):
            assert key in have, (plan, key)


def test_small_and_growing_are_professional_plus_the_church_pieces():
    for plan in (SMALL, GROWING):
        assert fg.plan_features(plan) == fg.plan_features("professional") | {"vertical_reports", "ai_clips"}


def test_established_and_large_carry_everything():
    for plan in (ESTABLISHED, LARGE):
        assert fg.plan_features(plan) == fg.plan_features("practice") == frozenset(fg.FEATURE_MIN_PLAN)
    for key in ("audit_trail", "accountant_collaborator", "marketing_autopilot"):
        assert key not in fg.plan_features(SMALL) and key not in fg.plan_features(GROWING)


def test_limits_are_the_size():
    lim = fg.plan_limits()
    assert [lim[p]["max_seats"] for p in fg.CHURCH_PLANS] == [3, 8, 15, 35]
    assert [lim[p]["texts_monthly"] for p in fg.CHURCH_PLANS] == [500, 1500, 3000, 8000]
    assert [lim[p]["clip_hours_monthly"] for p in fg.CHURCH_PLANS] == [2, 5, 10, 20]
    assert [lim[p]["chief_messages_monthly"] for p in fg.CHURCH_PLANS] == [3000, 7500, 17500, 30000]
    # No other plan is held to a text count.
    for plan in fg.PLANS + ("solo", "booked", "boss"):
        assert lim[plan].get("texts_monthly") is None, plan


def test_a_church_comp_gets_its_plan_and_tank():
    assert fg.plan_of({"comp_tier": GROWING, "type": "church"}) == GROWING
    assert fg.monthly_credits({"comp_tier": LARGE}) == 30000


def test_upgrades_stay_on_the_church_ladder():
    assert fg.upgrade_plan_for("audit_trail", SMALL) == ESTABLISHED
    assert fg.upgrade_plan_for("audit_trail", GROWING) == ESTABLISHED
    # A barber on Boss is never pointed at a church plan.
    assert fg.upgrade_plan_for("audit_trail", "boss") == "practice"
    assert fg.upgrade_plan_for("marketing_week", "solo") == "boss"


# ─── 4. the catalog ───────────────────────────────────────────────────

def test_the_catalog_carries_every_church_price_monthly_and_yearly():
    by_env = {e: cents for (e, _lk, _n, cents, _i) in sb.BOOTSTRAP_CATALOG}
    for plan, cents in pricing_config.church_price_cents().items():
        assert by_env[f"STRIPE_PRICE_ID_{plan.upper()}"] == cents
        assert by_env[f"STRIPE_PRICE_ID_{plan.upper()}_ANNUAL"] == cents * 10
    keys = [lk for (_e, lk, _n, _c, _i) in sb.BOOTSTRAP_CATALOG]
    assert len(keys) == len(set(keys))


def test_price_ids_resolve_to_the_church_plan(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING", "price_grow")
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING_ANNUAL", "price_grow_y")
    p2p = fg.price_to_plan()
    assert p2p["price_grow"] == p2p["price_grow_y"] == GROWING
    assert fg.plan_of({"subscription_status": "active", "subscription_plan": "price_grow"}) == GROWING


def test_bootstrap_asks_stripe_ten_lookup_keys_at_a_time(monkeypatch):
    asked = []

    async def stripe_get(path, params):
        if path == "/prices":
            asked.append([v for k, v in params if k == "lookup_keys[]"])
            return {"data": []}
        if path == "/promotion_codes":
            return {"data": [{"id": "promo"}]}
        return {"data": []}

    async def stripe_post(path, data):
        return {"id": f"x_{len(path)}_{data.get('lookup_key', data.get('name', ''))}"}

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(sb, "_stripe_get", stripe_get)
    monkeypatch.setattr(sb, "_stripe_post", stripe_post)
    out = asyncio.run(sb.bootstrap_prices(_owner=None))
    assert asked and all(len(a) <= 10 for a in asked)
    assert sorted(k for a in asked for k in a) == sorted(lk for (_e, lk, _n, _c, _i) in sb.BOOTSTRAP_CATALOG)
    assert "STRIPE_PRICE_ID_CHURCH_LARGE" in out["env"]


# ─── 5. checkout ──────────────────────────────────────────────────────

@pytest.fixture
def checkout(monkeypatch):
    posted = []
    state = {"type": "church"}

    async def stripe_post(path, data):
        posted.append((path, data))
        return {"id": "cs_x", "url": "https://checkout.stripe.test/x"}

    async def load(bid):
        return {"id": bid, "owner_id": "u-1", "name": "Grace Fellowship",
                "stripe_customer_id": "cus_1", "type": state["type"]}

    async def taken():
        return 0
    monkeypatch.setattr(sb, "_stripe_post", stripe_post)
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_founder_seats_taken", taken)
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    monkeypatch.setenv("STRIPE_PRICE_ID_DEFAULT", "price_pro")
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_SMALL", "price_small")
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING", "price_grow")
    return posted, state


def _buy(**body):
    return asyncio.run(sb.create_checkout(sb.CheckoutBody(business_id="biz-1", **body), user=USER))


def _sessions(posted):
    return [d for p, d in posted if p == "/checkout/sessions"]


def test_not_offered_is_refused(checkout):
    posted, _ = checkout
    with pytest.raises(HTTPException) as e:
        _buy(plan=GROWING)
    assert e.value.status_code == 409 and _sessions(posted) == []


def test_a_church_buys_its_plan_with_no_code_box(checkout, monkeypatch):
    posted, _ = checkout
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    _buy(plan=GROWING)
    [session] = _sessions(posted)
    assert session["line_items"] == [{"price": "price_grow", "quantity": 1}]
    assert session["allow_promotion_codes"] is False


def test_a_discount_code_is_refused_on_a_church_plan(checkout, monkeypatch):
    posted, _ = checkout
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    with pytest.raises(HTTPException) as e:
        _buy(plan=SMALL, promotion_code="MINISTRY20")
    assert e.value.status_code == 409 and _sessions(posted) == []


def test_a_barber_cant_buy_a_church_plan_even_by_raw_price(checkout, monkeypatch):
    posted, state = checkout
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    state["type"] = "barber"
    with pytest.raises(HTTPException) as e:
        _buy(price_id="price_small")
    assert e.value.status_code == 409 and "Small Church" in e.value.detail
    assert _sessions(posted) == []


def test_unpriced_church_plan_never_falls_back_to_professional(checkout, monkeypatch):
    posted, _ = checkout
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    with pytest.raises(HTTPException) as e:
        _buy(plan=LARGE)                 # no STRIPE_PRICE_ID_CHURCH_LARGE
    assert e.value.status_code == 409 and _sessions(posted) == []


# ─── 6. the plan cards ────────────────────────────────────────────────

def test_the_plans_endpoint_draws_the_church_ladder(monkeypatch):
    async def no_display(pid):
        return {}

    async def no_founder():
        return {"configured": False}
    monkeypatch.setattr(sb, "_price_display", no_display)
    monkeypatch.setattr(sb, "_founder_summary", no_founder)
    assert asyncio.run(sb.billing_plans(for_type="church"))["church_offer"] is None
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    out = asyncio.run(sb.billing_plans(for_type="church"))
    assert [p["plan"] for p in out["plans"]] == list(fg.PLANS)            # the public list is untouched
    assert [p["plan"] for p in out["audience_plans"]] == list(fg.CHURCH_PLANS)
    d = out["plan_details"]
    assert d[GROWING]["max_seats"] == 8 and d[GROWING]["texts_monthly"] == 1500
    assert d[GROWING]["clip_hours_monthly"] == 5 and d[GROWING]["people_on_sunday"] == {"from": 100, "to": 250}
    assert d["professional"]["texts_monthly"] is None and d["professional"]["people_on_sunday"] is None
    assert out["church_offer"]["names"][LARGE] == "Large Church"
    assert out["church_offer"]["extra_texts_cents_per_thousand"] == 2000
    assert out["marketing_by_plan"][ESTABLISHED] == fg.MARKETING_AUTOPILOT_WORDS


# ─── 7. sermon clip hours ─────────────────────────────────────────────

@pytest.mark.parametrize("row,hours", [({"comp_tier": SMALL}, 2), ({"comp_tier": LARGE}, 20),
                                       ({"comp_tier": "practice"}, 10), (None, 10)])
def test_clip_hours_follow_the_plan(monkeypatch, row, hours):
    import clip_finder
    import usage_metering
    monkeypatch.setattr(usage_metering, "_biz_row", lambda b: row)
    assert clip_finder.included_seconds("biz-1") == hours * 3600


def test_a_lookup_error_keeps_the_ten_free_hours(monkeypatch):
    import clip_finder
    import usage_metering

    def boom(b):
        raise RuntimeError("db down")
    monkeypatch.setattr(usage_metering, "_biz_row", boom)
    assert clip_finder.included_seconds("biz-1") == 10 * 3600


def test_hours_past_a_small_churchs_two_cost_actions():
    import clip_finder
    two = 2 * 3600
    assert clip_finder.extra_units(0, 3600, two) == 0
    assert clip_finder.extra_units(two, 3600, two) == clip_finder.UNITS_PER_EXTRA_HOUR
    assert clip_finder.extra_units(0, 3600) == 0          # the ten-hour default is unchanged
