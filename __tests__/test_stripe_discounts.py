"""Coupons: tenant isolation, retry safety, Stripe version compatibility and settlement."""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import discount_settlement as settlement
import stripe_discounts as discounts
import stripe_checkout_helpers as checkout
import sb_clients


def run(coro):
    return asyncio.run(coro)


def body(**changes):
    return discounts.CreateDiscount(request_id=uuid4(), code=" welcome20 ", percent_off=20, **changes)


def promo(**changes):
    return {"id": "promo_1", "active": True, "code": "WELCOME20", "times_redeemed": 0,
            "coupon": {"id": "coupon_1", "valid": True, "percent_off": 20, "duration": "once"}, **changes}


@pytest.mark.parametrize("change", [
    {"percent_off": 0}, {"percent_off": 101}, {"percent_off": float('nan')},
    {"percent_off": None}, {"amount_off": 100}, {"code": "bad/code"},
    {"code": "x" * 65}, {"code": ""}, {"max_redemptions": 0},
    {"expires_at": int(time.time()) - 10}, {"duration": "repeating"},
    {"duration_in_months": 2},
])
def test_invalid_discount_rejected(change):
    with pytest.raises(ValidationError):
        discounts.CreateDiscount(**{"request_id": uuid4(), "code": "ok", "percent_off": 20, **change})


def test_code_normalized_and_fixed_amount_supported():
    assert body().code == "WELCOME20"
    fixed = discounts.CreateDiscount(request_id=uuid4(), code="SAVE5", amount_off=500)
    assert fixed.amount_off == 500 and fixed.percent_off is None


def test_create_uses_connected_account_and_stable_retry_keys(monkeypatch):
    call = AsyncMock(side_effect=[{"data": []}, {"id": "coupon_1"}, promo()])
    monkeypatch.setattr(discounts, "stripe_request", call)
    draft = body()
    assert run(discounts.create_discount(draft, "acct_business"))["code"] == "WELCOME20"
    assert all(c.kwargs["account"] == "acct_business" for c in call.call_args_list)
    coupon_call, promo_call = call.call_args_list[1:]
    assert coupon_call.kwargs["key"] == f"discount:{draft.request_id}:coupon"
    assert promo_call.kwargs["form"]["promotion"] == {"type": "coupon", "coupon": "coupon_1"}


def test_duplicate_code_never_creates_another_coupon(monkeypatch):
    call = AsyncMock(return_value={"data": [promo()]})
    monkeypatch.setattr(discounts, "stripe_request", call)
    with pytest.raises(HTTPException) as error:
        run(discounts.create_discount(body()))
    assert error.value.status_code == 409
    assert call.await_count == 1


def test_successful_create_retry_reuses_same_promotion(monkeypatch):
    saved = []
    async def stripe(method, path, **kw):
        if method == "GET":
            return {"data": saved}
        if path == "/coupons":
            return {"id": "coupon_1"}
        result = promo(metadata=kw["form"]["metadata"])
        saved.append(result)
        return result
    call = AsyncMock(side_effect=stripe)
    monkeypatch.setattr(discounts, "stripe_request", call)
    draft = body()
    assert run(discounts.create_discount(draft)) == run(discounts.create_discount(draft))
    assert sum(c.args[0] == "POST" for c in call.call_args_list) == 2


def test_legacy_fallback_only_for_unknown_promotion_parameter(monkeypatch):
    call = AsyncMock(side_effect=[{"data": []}, {"id": "coupon_1"},
        discounts.StripeDiscountError(400, {"code": "parameter_unknown", "param": "promotion"}), promo()])
    monkeypatch.setattr(discounts, "stripe_request", call)
    run(discounts.create_discount(body()))
    assert call.call_args.kwargs["form"]["coupon"] == "coupon_1"
    assert call.call_args.kwargs["key"].endswith(":legacy")


def test_validation_failure_is_not_retried_as_legacy(monkeypatch):
    call = AsyncMock(side_effect=[{"data": []}, {"id": "coupon_1"},
        discounts.StripeDiscountError(400, {"code": "resource_already_exists", "param": "code"})])
    monkeypatch.setattr(discounts, "stripe_request", call)
    with pytest.raises(HTTPException):
        run(discounts.create_discount(body()))
    assert call.await_count == 3


@pytest.mark.parametrize("changes", [
    {"expires_at": int(time.time()) - 1},
    {"times_redeemed": 3, "max_redemptions": 3},
    {"coupon": {"valid": False}},
])
def test_expired_exhausted_and_deleted_coupons_rejected(monkeypatch, changes):
    monkeypatch.setattr(discounts, "stripe_request", AsyncMock(return_value={"data": [promo(**changes)]}))
    with pytest.raises(HTTPException):
        run(discounts.resolve_code("welcome20"))


def test_modern_coupon_shape_and_pagination(monkeypatch):
    call = AsyncMock(side_effect=[{"data": [promo(coupon=None, promotion={"coupon": "coupon_1"})], "has_more": True},
                                  {"id": "coupon_1", "valid": True, "percent_off": 20}])
    monkeypatch.setattr(discounts, "stripe_request", call)
    page = run(discounts.list_discounts("acct_owner", "promo_previous"))
    assert page["next_cursor"] == "promo_1"
    assert page["items"][0]["coupon"]["percent_off"] == 20
    assert call.call_args_list[0].kwargs["params"]["starting_after"] == "promo_previous"
    assert call.call_args_list[1].kwargs["account"] == "acct_owner"


def test_financial_lock_blocks_stripe_writes(monkeypatch):
    monkeypatch.setattr(discounts, "require_stripe_write", Mock(side_effect=HTTPException(403, "locked")))
    with pytest.raises(HTTPException) as error:
        run(discounts.stripe_request("POST", "/coupons", account="acct_locked"))
    assert error.value.status_code == 403


def test_http_transport_carries_account_version_and_idempotency(monkeypatch):
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "coupon_1"})
    original = httpx.AsyncClient
    monkeypatch.setattr(discounts.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr(discounts, "_stripe_key", lambda: "sk_test_fake")
    monkeypatch.setattr(discounts, "require_stripe_write", lambda account: None)
    monkeypatch.setenv("STRIPE_API_VERSION", "2025-09-30.clover")
    run(discounts.stripe_request("POST", "/coupons", account="acct_a", key="retry-key", form={"percent_off": 20}))
    assert seen[0].headers["Stripe-Account"] == "acct_a"
    assert seen[0].headers["Stripe-Version"] == "2025-09-30.clover"
    assert seen[0].headers["Idempotency-Key"] == "retry-key"


def test_business_account_comes_from_persisted_business():
    assert discounts._account({"stripe_account_id": "acct_real"}) == "acct_real"
    with pytest.raises(HTTPException):
        discounts._account({"settings": {"payments": {"provider": "square"}}, "stripe_account_id": "acct_old"})


def test_coupon_endpoints_require_auth():
    app = FastAPI()
    app.include_router(discounts.router)
    client = TestClient(app)
    for path in ("/billing/discounts", "/billing/discount-targets", "/payments/00000000-0000-0000-0000-000000000001/discounts"):
        assert client.get(path).status_code in (401, 403)


def test_business_owner_cannot_read_another_business_coupons(monkeypatch):
    import business_access
    app = FastAPI()
    app.include_router(discounts.router)
    app.dependency_overrides[sb_clients.authed_request] = lambda: SimpleNamespace(user=SimpleNamespace(id="user_a"))
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{"id": "business_b", "stripe_account_id": "acct_b"}])
    monkeypatch.setattr(business_access, "_resolve_role", lambda business, user: None)
    call = AsyncMock()
    monkeypatch.setattr(discounts, "stripe_request", call)
    assert TestClient(app).get("/payments/business_b/discounts").status_code == 404
    call.assert_not_called()


def test_apply_discount_rejects_non_platform_owner_before_reading_business(monkeypatch):
    import lead_admin
    import stripe_billing
    app = FastAPI()
    app.include_router(discounts.router)
    client = TestClient(app)
    payload = {"business_id": str(uuid4()), "code": "WELCOME20", "request_id": str(uuid4())}
    load = AsyncMock()
    call = AsyncMock()
    monkeypatch.setattr(stripe_billing, "_load_business", load)
    monkeypatch.setattr(discounts, "stripe_request", call)
    assert client.post("/billing/apply-discount", json=payload).status_code in (401, 403)
    app.dependency_overrides[lead_admin.require_user] = lambda: SimpleNamespace(
        id="business_owner", email="another-business@example.com")
    assert client.post("/billing/apply-discount", json=payload).status_code == 403
    load.assert_not_called()
    call.assert_not_called()


def test_apply_discount_checks_customer_and_keeps_existing_discounts(monkeypatch):
    import stripe_billing
    monkeypatch.setattr(stripe_billing, "_load_business", AsyncMock(return_value={"stripe_subscription_id": "sub_1", "stripe_customer_id": "cus_1"}))
    request = discounts.ApplyDiscount(business_id=uuid4(), code="WELCOME20", request_id=uuid4())
    for sub in ({"customer": "cus_other", "status": "active"},
                {"customer": "cus_1", "status": "active", "discounts": ["di_existing"]}):
        call = AsyncMock(return_value=sub)
        monkeypatch.setattr(discounts, "stripe_request", call)
        with pytest.raises(HTTPException):
            run(discounts.apply_discount(request))
        assert call.await_count == 1


def test_apply_discount_does_not_create_immediate_charge(monkeypatch):
    import stripe_billing
    monkeypatch.setattr(stripe_billing, "_load_business", AsyncMock(return_value={"stripe_subscription_id": "sub_1", "stripe_customer_id": "cus_1"}))
    monkeypatch.setattr(discounts, "resolve_code", AsyncMock(return_value=promo()))
    call = AsyncMock(side_effect=[{"customer": "cus_1", "status": "active"}, {}])
    monkeypatch.setattr(discounts, "stripe_request", call)
    result = run(discounts.apply_discount(discounts.ApplyDiscount(business_id=uuid4(), code="WELCOME20", request_id=uuid4())))
    assert result["ok"]
    assert call.call_args.kwargs["form"]["proration_behavior"] == "none"
    assert call.call_args.kwargs["form"]["discounts"] == [{"promotion_code": "promo_1"}]


def checkout_form(**changes):
    return checkout._checkout_session_form(line_items=[{"name": "Item", "amount_cents": 10000}],
        success_url="https://example.com/success", cancel_url="https://example.com/cancel",
        source_type="order", source_id="order_1", **changes)


def test_store_coupon_keeps_tax_and_shipping_out_of_product_lines():
    form = checkout_form(allow_promotion_codes=True, tax_rate_id="txr_1", shipping_amount_cents=500)
    assert form["allow_promotion_codes"] == "true"
    assert form["line_items[0][tax_rates][0]"] == "txr_1"
    assert form["shipping_options[0][shipping_rate_data][fixed_amount][amount]"] == 500
    assert "line_items[1][quantity]" not in form
    assert form["payment_intent_data[metadata][discount_checkout_v1]"] == "true"


@pytest.mark.parametrize("deposit,tip,enabled", [(None, 0, True), (1000, 0, False), (None, 500, False)])
def test_booking_preserves_disclosed_deposit_and_tip(monkeypatch, deposit, tip, enabled):
    call = AsyncMock(return_value={"url": "https://checkout.stripe.com/example"})
    monkeypatch.setattr(checkout, "create_checkout_session", call)
    run(checkout.create_booking_checkout(stripe_account_id="acct_a", booking_id="booking_1", service_name="Service",
        amount_cents=10000, customer_email=None, success_url="https://example.com", cancel_url="https://example.com",
        deposit_cents=deposit, tip_cents=tip))
    assert call.call_args.kwargs["allow_promotion_codes"] is enabled


def settled_order():
    return {"stripe_checkout_session_id": "cs_1", "subtotal_cents": 10000, "shipping_cents": 500, "currency": "usd"}


def settled_session():
    return {"id": "cs_1", "currency": "usd", "amount_subtotal": 10000, "amount_total": 9300,
            "total_details": {"amount_discount": 2000, "amount_tax": 800, "amount_shipping": 500}}


def test_discounted_order_posts_actual_total():
    assert settlement.order_settlement(settled_order(), settled_session()) == {
        "subtotal_cents": 8000, "tax_cents": 800, "shipping_cents": 500, "total_cents": 9300}


@pytest.mark.parametrize("change", [{"id": "cs_other"}, {"currency": "cad"}, {"amount_total": 10000}, {"amount_total": -1}, {"amount_subtotal": None}])
def test_mismatched_or_invalid_settlement_rejected(change):
    with pytest.raises(ValueError):
        settlement.order_settlement(settled_order(), {**settled_session(), **change})


def test_cross_account_webhook_rejected(monkeypatch):
    monkeypatch.setattr(settlement.sb_clients, "sb_get_as_service", Mock(side_effect=[
        [{"business_id": "business_a"}], [{"stripe_account_id": "acct_a"}]]))
    with pytest.raises(ValueError):
        settlement.verify_checkout_account({"metadata": {"source_type": "order", "source_id": "order_a"}}, "acct_b")


def test_payment_intent_cannot_post_undiscounted_order_first(monkeypatch):
    import stripe_connect_router as webhooks
    import store_router
    mark = Mock()
    monkeypatch.setattr(store_router, "mark_order_paid", mark)
    webhooks._handle_payment_intent_succeeded({"id": "pi_1", "metadata": {
        "source_type": "order", "source_id": "order_1", "discount_checkout_v1": "true"}})
    mark.assert_not_called()


def test_fully_discounted_checkout_is_fulfilled(monkeypatch):
    import stripe_connect_router as webhooks
    import store_router
    mark = Mock()
    monkeypatch.setattr(store_router, "mark_order_paid", mark)
    monkeypatch.setattr(webhooks, "_emit_order_paid", Mock())
    session = {"id": "cs_free", "payment_status": "no_payment_required", "amount_total": 0,
               "metadata": {"source_type": "order", "source_id": "order_1", "discount_checkout_v1": "true"}}
    webhooks._handle_checkout_session_completed(session)
    mark.assert_called_once()


def test_coupon_payment_intent_keeps_card_without_marking_booking_paid(monkeypatch):
    import stripe_connect_router as webhooks
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{"data": {"no_show_fee_cents": 1500}}])
    patch = Mock()
    mark = Mock()
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    monkeypatch.setattr(webhooks, "_mark_booking_paid", mark)
    webhooks._handle_payment_intent_succeeded({"id": "pi_1", "payment_method": "pm_saved", "metadata": {
        "source_type": "booking", "source_id": "booking_1", "discount_checkout_v1": "true"}})
    mark.assert_not_called()
    assert patch.call_args.args[1] == {"data": {"no_show_fee_cents": 1500, "stripe_payment_method_id": "pm_saved"}}


@pytest.mark.parametrize("paid,discount", [(8000, 2000), (0, 10000)])
def test_booking_records_actual_price_and_preserves_original(monkeypatch, paid, discount):
    import stripe_connect_router as webhooks
    import event_spine
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{
        "id": "booking_1", "data": {"price_at_booking": 100, "price": 100}, "business_id": "business_1"}])
    patch = Mock()
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    monkeypatch.setattr(event_spine, "emit", Mock())
    webhooks._mark_booking_paid("booking_1", payment_intent_id="pi_1", charge_id=None, metadata={
        "discount_checkout_v1": "true", "amount_paid_cents": paid, "discount_cents": discount, "service_cents": 10000})
    data = patch.call_args_list[0].args[1]["data"]
    assert data["price_before_discount"] == 100
    assert data["price_at_booking"] == data["price"] == paid / 100
    assert data["discount_cents"] == discount
    assert "paid_at" in patch.call_args_list[1].args[1]


@pytest.mark.parametrize("code", [None, "welcome20"])
def test_platform_checkout_enables_entry_or_applies_code_but_never_both(monkeypatch, code):
    import stripe_billing as billing
    biz_id = str(uuid4())
    monkeypatch.setattr(billing, "_load_business", AsyncMock(return_value={
        "id": biz_id, "owner_id": "user_1", "stripe_customer_id": "cus_1"}))
    monkeypatch.setattr(billing, "_subscription_data", lambda *a, **kw: {"metadata": {"business_id": biz_id}})
    monkeypatch.setattr(discounts, "resolve_code", AsyncMock(return_value=promo()))
    post = AsyncMock(return_value={"id": "cs_1", "url": "https://checkout.stripe.com/example"})
    monkeypatch.setattr(billing, "_stripe_post", post)
    run(billing.create_checkout(billing.CheckoutBody(business_id=biz_id, price_id="price_example", promotion_code=code),
                                SimpleNamespace(id="user_1", email="owner@example.com")))
    form = post.call_args.args[1]
    if code:
        assert form["discounts"] == [{"promotion_code": "promo_1"}]
        assert "allow_promotion_codes" not in form
    else:
        assert form["allow_promotion_codes"] is True
        assert "discounts" not in form
