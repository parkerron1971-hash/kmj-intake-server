# __tests__/test_online_giving.py
#
# Online giving for ministry/nonprofit verticals. Pins:
#   1. the activation rubric — give surface only for nonprofit-family
#      businesses, and only when enabled + Stripe-connected
#   2. gift → PAID invoice shape: category='restricted' (the EXACT
#      gl_engine._RESTRICTED_HINTS token) for designated funds, empty
#      for General; statement-compatible fields; giving language
#      ('Gift — <Fund>', never 'Invoice')
#   3. webhook idempotency — same Stripe ref never posts twice
#   4. recurring cycle attribution via invoice.subscription_details
#      .metadata; subscription checkout sessions are a deliberate no-op
#      (the first cycle records ONCE, from invoice.paid)
#   5. rate limiting runs BEFORE any read/write on the public endpoint
#   6. contact find-or-create dedup by email within the business
#   7. the pure Checkout form contract (payment vs subscription modes)

import asyncio
import sys
import types
import urllib.parse
from types import SimpleNamespace
from unittest import mock

import pytest
from fastapi import HTTPException

import gl_engine
import giving_router
import stripe_connect_router
from stripe_checkout_helpers import ALLOWED_SOURCE_TYPES, _giving_checkout_form

BIZ = "biz-0000-1111"


# ─── Fakes ───────────────────────────────────────────────────────────


class FakeSB:
    """Stateful Supabase fake: invoices + contacts POSTed here are
    visible to subsequent GETs, so idempotency/dedup tests exercise the
    real read-before-write logic rather than a canned answer."""

    def __init__(self, business=None):
        self.posts = []            # (path, payload)
        self.patches = []          # (path, payload)
        self.business = business or {}
        self._id = 0

    # -- helpers --
    def _posted(self, path_prefix):
        return [p for (path, p) in self.posts if path.startswith(path_prefix)]

    def sb_get_as_service(self, path):
        if path.startswith("/businesses?"):
            return [self.business] if self.business else []
        if path.startswith("/business_sites?"):
            return [{"business_id": BIZ, "slug": "first-light"}]
        if path.startswith("/invoices?") and "invoice_number=eq." in path:
            num = urllib.parse.unquote(
                path.split("invoice_number=eq.")[1].split("&")[0])
            return [{"id": r["_id"], **r} for r in self._posted("/invoices")
                    if r.get("invoice_number") == num][:1]
        if path.startswith("/contacts?") and "email=ilike." in path:
            pattern = urllib.parse.unquote(
                path.split("email=ilike.")[1].split("&")[0])
            email = pattern.replace("\\%", "%").replace("\\_", "_").replace("\\\\", "\\")
            return [{"id": r["_id"]} for r in self._posted("/contacts")
                    if (r.get("email") or "").lower() == email.lower()][:1]
        return []

    def sb_post_as_service(self, path, payload):
        self._id += 1
        row = dict(payload)
        row["_id"] = f"row-{self._id}"
        self.posts.append((path, row))
        return [{"id": row["_id"], **payload}]

    def sb_patch_as_service(self, path, payload):
        self.patches.append((path, payload))
        return []


class ExplodingSB:
    """Any call proves the rate limiter did NOT run first."""

    def __getattr__(self, name):
        raise AssertionError(f"sb_clients.{name} called before rate limit")


@pytest.fixture
def fake_sb(monkeypatch):
    fake = FakeSB()
    monkeypatch.setattr(giving_router, "sb_clients", fake)
    monkeypatch.setattr(stripe_connect_router, "sb_clients", fake)
    # event_spine stub — spine writes use their own sb import.
    spine = types.ModuleType("event_spine")
    spine.emitted = []
    spine.emit = lambda *a, **k: spine.emitted.append((a, k))
    monkeypatch.setitem(sys.modules, "event_spine", spine)
    fake.spine = spine
    return fake


def _church(**over):
    biz = {"id": BIZ, "name": "First Light Church", "type": "church",
           "stripe_account_id": "acct_123",
           "settings": {"giving": {"enabled": True,
                                   "funds": ["General", "Building", "Missions"]}}}
    biz.update(over)
    return biz


# ─── 1. Activation rubric ────────────────────────────────────────────


def test_active_for_enabled_connected_church():
    assert giving_router.giving_is_active(_church()) is True


def test_inactive_outside_nonprofit_family():
    # A coach with giving flipped on somehow still gets NO give surface.
    assert giving_router.giving_is_active(_church(type="coaching")) is False
    assert giving_router.giving_is_active(_church(type="barber")) is False
    # ...and family membership is exact — no substring accidents.
    assert giving_router.giving_is_active(_church(type="sports ministry coach")) is False


def test_inactive_when_disabled_or_disconnected():
    off = _church(settings={"giving": {"enabled": False}})
    assert giving_router.giving_is_active(off) is False
    assert giving_router.giving_is_active(_church(stripe_account_id=None)) is False
    assert giving_router.giving_is_active(_church(settings={})) is False


def test_ministry_and_nonprofit_types_both_qualify():
    assert giving_router.giving_is_active(_church(type="ministry")) is True
    assert giving_router.giving_is_active(_church(type="nonprofit")) is True


# ─── 2. Fund rubric + gift → invoice shape ───────────────────────────


def test_designated_rubric_not_lookup_table():
    assert giving_router.is_designated("Building") is True
    assert giving_router.is_designated("Missions") is True
    assert giving_router.is_designated("General") is False
    assert giving_router.is_designated("general fund") is False
    assert giving_router.is_designated("  GENERAL  ") is False
    assert giving_router.is_designated("") is False
    assert giving_router.fund_label("Building") == "Building Fund"
    assert giving_router.fund_label("Building Fund") == "Building Fund"
    assert giving_router.fund_label("") == "General Fund"


def test_designated_gift_lands_as_restricted_paid_invoice(fake_sb):
    giving_router.record_gift(
        BIZ, amount_cents=5000, fund="Building",
        giver_name="Sarah Chen", giver_email="sarah@example.com",
        stripe_ref="pi_abc123")
    invs = fake_sb._posted("/invoices")
    assert len(invs) == 1
    inv = invs[0]
    # The load-bearing token: EXACTLY what gl_engine matches, so the
    # restricted-fund GL routing (4200) fires.
    assert inv["category"] in gl_engine._RESTRICTED_HINTS
    assert inv["category"] == "restricted"
    # Statement/donor/990-compatible shape: paid + refund-adjustable.
    assert inv["status"] == "paid"
    assert inv["paid_at"]
    assert inv["payment_method"] == "stripe"   # 1150 Stripe Clearing, not cash
    assert inv["total"] == 50.0
    assert inv["invoice_number"] == "GIVE-pi_abc123"
    # Giving language — a ministry never says 'Invoice'.
    assert inv["items"][0]["description"] == "Gift — Building Fund"
    assert "Invoice" not in inv["items"][0]["description"]
    assert "Building Fund" in inv["notes"]
    # Restricted routing double-gate: nonprofit family + this category.
    assert gl_engine._income_code_for_invoice(inv, "church") == "4200"


def test_general_fund_gift_is_unrestricted(fake_sb):
    giving_router.record_gift(
        BIZ, amount_cents=2500, fund="General",
        giver_email="tom@example.com", stripe_ref="pi_gen1")
    inv = fake_sb._posted("/invoices")[0]
    # Empty category → giving_statements renders the fund as "General"
    # and gl_engine routes plain 4000 income.
    assert not (inv.get("category") or "").strip()
    assert gl_engine._income_code_for_invoice(inv, "church") == "4000"
    assert inv["items"][0]["description"] == "Gift — General Fund"


def test_gift_statement_fund_display_matches_statements_logic(fake_sb):
    """The exact expression giving_statements uses to display the fund."""
    giving_router.record_gift(BIZ, amount_cents=1000, fund="Missions",
                              stripe_ref="pi_m1")
    giving_router.record_gift(BIZ, amount_cents=1000, fund="General",
                              stripe_ref="pi_g1")
    funds = [((i.get("category") or "").strip() or "General")
             for i in fake_sb._posted("/invoices")]
    assert funds == ["restricted", "General"]


# ─── 3. Idempotency ──────────────────────────────────────────────────


def test_same_stripe_ref_never_posts_twice(fake_sb):
    a = giving_router.record_gift(BIZ, amount_cents=5000, fund="General",
                                  stripe_ref="pi_dup")
    b = giving_router.record_gift(BIZ, amount_cents=5000, fund="General",
                                  stripe_ref="pi_dup")
    assert len(fake_sb._posted("/invoices")) == 1
    assert a == b  # retry returns the same row


# ─── 4. Recurring cycles ─────────────────────────────────────────────


def _stripe_cycle_invoice(inv_id="in_cycle1", amount=2500):
    return {
        "id": inv_id,
        "amount_paid": amount,
        "customer_email": "ruth@example.com",
        "customer_name": "Ruth Adams",
        "billing_reason": "subscription_create",
        "subscription": "sub_1",
        "subscription_details": {"metadata": {
            "source_type": "gift", "source_id": "gift-uuid-1",
            "business_id": BIZ, "fund": "Building",
            "fund_kind": "restricted", "frequency": "monthly",
            "giver_email": "ruth@example.com", "giver_name": "Ruth Adams",
        }},
    }


def test_cycle_records_one_paid_invoice_with_attribution(fake_sb):
    giving_router.record_gift_from_cycle(_stripe_cycle_invoice())
    inv = fake_sb._posted("/invoices")[0]
    assert inv["invoice_number"] == "GIVE-in_cycle1"
    assert inv["business_id"] == BIZ
    assert inv["category"] == "restricted"
    assert "monthly" in inv["notes"]
    # Contact attributed from subscription metadata.
    contacts = fake_sb._posted("/contacts")
    assert len(contacts) == 1 and contacts[0]["email"] == "ruth@example.com"


def test_webhook_invoice_paid_routes_gift_cycles(fake_sb, monkeypatch):
    calls = []
    monkeypatch.setattr(giving_router, "record_gift_from_cycle",
                        lambda inv: calls.append(inv.get("id")))
    stripe_connect_router._handle_invoice_paid(_stripe_cycle_invoice("in_x"))
    assert calls == ["in_x"]
    # Non-gift Stripe invoices keep the PR 3a logged-only behavior.
    stripe_connect_router._handle_invoice_paid({"id": "in_other",
                                                "subscription_details": {}})
    assert calls == ["in_x"]


def test_subscription_checkout_session_is_a_noop(fake_sb):
    """The first cycle records from invoice.paid — never from the
    session — so one dollar can't post twice."""
    session = {
        "payment_status": "paid", "mode": "subscription", "id": "cs_1",
        "metadata": {"source_type": "gift", "source_id": "g1",
                     "business_id": BIZ, "fund": "General"},
    }
    stripe_connect_router._handle_checkout_session_completed(session)
    assert fake_sb._posted("/invoices") == []


def test_one_time_session_records_the_gift(fake_sb):
    session = {
        "payment_status": "paid", "mode": "payment", "id": "cs_2",
        "payment_intent": "pi_one1",
        "customer_details": {"email": "walkin@example.com", "name": "Walk In"},
        "metadata": {"source_type": "gift", "source_id": "g2",
                     "business_id": BIZ, "fund": "General",
                     "frequency": "once"},
        "amount_total": 7500,
    }
    stripe_connect_router._handle_checkout_session_completed(session)
    inv = fake_sb._posted("/invoices")[0]
    assert inv["invoice_number"] == "GIVE-pi_one1"
    assert inv["total"] == 75.0


def test_cycle_delivery_retry_is_idempotent(fake_sb):
    giving_router.record_gift_from_cycle(_stripe_cycle_invoice("in_r"))
    giving_router.record_gift_from_cycle(_stripe_cycle_invoice("in_r"))
    assert len(fake_sb._posted("/invoices")) == 1


# ─── 5. Contact dedup ────────────────────────────────────────────────


def test_repeat_giver_gets_one_contact(fake_sb):
    giving_router.record_gift(BIZ, amount_cents=1000, fund="General",
                              giver_email="Same@Example.com", stripe_ref="pi_c1")
    giving_router.record_gift(BIZ, amount_cents=2000, fund="Building",
                              giver_email="same@example.com", stripe_ref="pi_c2")
    assert len(fake_sb._posted("/contacts")) == 1
    assert len(fake_sb._posted("/invoices")) == 2


def test_anonymous_gift_records_without_inventing_a_contact(fake_sb):
    giving_router.record_gift(BIZ, amount_cents=1000, fund="General",
                              stripe_ref="pi_anon")
    assert fake_sb._posted("/contacts") == []
    inv = fake_sb._posted("/invoices")[0]
    assert inv["contact_id"] is None   # statements count it unattributed


# ─── 6. Rate limiting before any write ───────────────────────────────


def _request(ip="9.9.9.9"):
    return SimpleNamespace(headers={}, client=SimpleNamespace(host=ip))


def test_rate_limit_runs_before_any_read_or_write(monkeypatch):
    monkeypatch.setattr(giving_router, "sb_clients", ExplodingSB())
    monkeypatch.setattr(giving_router, "_give_rate", {})
    ip = "1.2.3.4"
    for _ in range(giving_router.GIVE_RATE_MAX_PER_MIN):
        assert giving_router._check_give_rate(ip) is True
    with pytest.raises(HTTPException) as exc:
        asyncio.run(giving_router.public_giving_checkout(
            "first-light", {"amount_cents": 5000}, _request(ip)))
    assert exc.value.status_code == 429


def test_validation_rejects_before_db(monkeypatch):
    """Bad amounts/frequency fail before any database call — ExplodingSB
    proves the ordering."""
    monkeypatch.setattr(giving_router, "sb_clients", ExplodingSB())
    monkeypatch.setattr(giving_router, "_give_rate", {})
    for body, code in [
        ({"amount_cents": 50}, 400),                     # under $1
        ({"amount_cents": 99_999_999}, 400),             # over ceiling
        ({"amount_cents": 5000, "frequency": "weekly"}, 400),
        ({"amount_cents": 5000, "email": "junk"}, 400),
        ({"amount_cents": 5000, "frequency": "monthly"}, 400),  # monthly needs email
    ]:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(giving_router.public_giving_checkout(
                "first-light", body, _request()))
        assert exc.value.status_code == code, body


def test_checkout_gated_by_vertical_and_fund_list(monkeypatch):
    fake = FakeSB(business=_church(type="coaching"))
    monkeypatch.setattr(giving_router, "sb_clients", fake)
    monkeypatch.setattr(giving_router, "_give_rate", {})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(giving_router.public_giving_checkout(
            "first-light", {"amount_cents": 5000}, _request("2.2.2.2")))
    assert exc.value.status_code == 404      # not nonprofit-like → no give

    fake = FakeSB(business=_church())
    monkeypatch.setattr(giving_router, "sb_clients", fake)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(giving_router.public_giving_checkout(
            "first-light", {"amount_cents": 5000, "fund": "Yacht"},
            _request("3.3.3.3")))
    assert exc.value.status_code == 400      # unknown fund


def test_checkout_happy_path_resolves_fund_and_kind(monkeypatch):
    fake = FakeSB(business=_church())
    monkeypatch.setattr(giving_router, "sb_clients", fake)
    monkeypatch.setattr(giving_router, "_give_rate", {})
    captured = {}

    class StubAdapter:
        async def create_giving_checkout(self, biz, **kwargs):
            captured.update(kwargs)
            return {"url": "https://checkout.stripe.com/c/pay_x"}

    import payments_core
    monkeypatch.setattr(payments_core, "provider_for", lambda biz: StubAdapter())
    out = asyncio.run(giving_router.public_giving_checkout(
        "first-light",
        {"amount_cents": 10000, "fund": "building",   # case-insensitive
         "frequency": "monthly", "email": "b@example.com", "name": "Ben"},
        _request("4.4.4.4")))
    assert out["ok"] and out["url"].startswith("https://checkout.stripe.com/")
    assert captured["fund"] == "Building"
    assert captured["fund_kind"] == "restricted"
    assert captured["monthly"] is True
    assert captured["success_url"].endswith("/give?thanks=1")


# ─── 7. Checkout form contract (pure) ────────────────────────────────


def test_gift_is_an_allowed_source_type():
    assert "gift" in ALLOWED_SOURCE_TYPES


def _form(monthly):
    return _giving_checkout_form(
        amount_cents=5000, fund_display="Building Fund", monthly=monthly,
        success_url="https://x/give?thanks=1", cancel_url="https://x/give?canceled=1",
        gift_id="gift-1", business_id=BIZ, fund="Building",
        fund_kind="restricted", giver_email="a@b.co", giver_name="A B")


def test_one_time_form_mirrors_metadata_onto_payment_intent():
    form = _form(monthly=False)
    assert form["mode"] == "payment"
    assert form["metadata[source_type]"] == "gift"
    assert form["payment_intent_data[metadata][source_type]"] == "gift"
    assert form["payment_intent_data[metadata][business_id]"] == BIZ
    assert form["line_items[0][price_data][product_data][name]"] == "Gift — Building Fund"
    assert form["line_items[0][price_data][unit_amount]"] == 5000
    assert "line_items[0][price_data][recurring][interval]" not in form
    assert not any(k.startswith("subscription_data") for k in form)


def test_monthly_form_uses_subscription_metadata_not_pi():
    form = _form(monthly=True)
    assert form["mode"] == "subscription"
    # Stripe REJECTS payment_intent_data in subscription mode — the
    # mirror must ride subscription_data instead (that mirror is the
    # whole recurring-attribution mechanism).
    assert not any(k.startswith("payment_intent_data") for k in form)
    assert form["subscription_data[metadata][source_type]"] == "gift"
    assert form["subscription_data[metadata][fund]"] == "Building"
    assert form["subscription_data[metadata][business_id]"] == BIZ
    assert form["line_items[0][price_data][recurring][interval]"] == "month"
    assert form["customer_email"] == "a@b.co"


def test_form_rejects_bad_fund_kind():
    with pytest.raises(ValueError):
        _giving_checkout_form(
            amount_cents=5000, fund_display="X", monthly=False,
            success_url="s", cancel_url="c", gift_id="g", business_id=BIZ,
            fund="X", fund_kind="designated")


# ─── 8. Refunds find the gift invoice ────────────────────────────────


def test_charge_refunded_adjusts_the_gift_invoice(fake_sb):
    giving_router.record_gift(BIZ, amount_cents=5000, fund="General",
                              stripe_ref="pi_ref1")
    stripe_connect_router._handle_charge_refunded({
        "metadata": {"source_type": "gift", "source_id": "g-1"},
        "payment_intent": "pi_ref1",
        "amount_refunded": 5000,
        "refunded": True,
    })
    assert any("refund_amount_cents" in p and p["refund_amount_cents"] == 5000
               for _, p in fake_sb.patches)


# ─── 9. SSR page renderers (pure) ────────────────────────────────────


def test_give_page_renders_funds_presets_and_mobile_meta():
    html = giving_router.render_give_page(
        _church(), "https://first-light.mysolutionist.app/give",
        "first-light", api_origin="https://api.example")
    assert 'name="viewport"' in html                     # mobile-first
    assert 'rel="canonical"' in html
    assert 'property="og:title"' in html
    assert "Building Fund" in html and "Missions Fund" in html
    assert 'data-cents="2500"' in html                   # $25 preset
    assert "/public/giving/" in html
    assert "First Light Church" in html


def test_give_page_hides_fund_selector_for_single_fund():
    biz = _church(settings={"giving": {"enabled": True, "funds": ["General"]}})
    html = giving_router.render_give_page(
        biz, "https://x/give", "x", api_origin="https://api.example")
    # The JS null-checks getElementById('gv-fund'); the SELECT itself
    # must not render for a single-fund config.
    assert '<select id="gv-fund"' not in html


def test_unavailable_page_is_noindex():
    html = giving_router.render_giving_unavailable_page(
        _church(type="coaching"), "https://x/give")
    assert "noindex" in html
    assert "isn" in html   # "isn't available"


# ─── 10. Config validation ───────────────────────────────────────────


def test_patch_funds_validation(monkeypatch):
    fake = FakeSB(business=_church(owner_id="u1"))
    monkeypatch.setattr(giving_router, "sb_clients", fake)
    monkeypatch.setattr(giving_router, "ensure_business_site",
                        lambda biz: ({"slug": "first-light"}, False))
    user = SimpleNamespace(id="u1", email="pastor@example.com")

    out = giving_router.patch_giving_config(
        BIZ, {"enabled": True, "funds": ["General", "Building", " building "]},
        user)
    assert out["funds"] == ["General", "Building"]   # dedup, case-insensitive

    with pytest.raises(HTTPException):
        giving_router.patch_giving_config(BIZ, {"funds": []}, user)
    with pytest.raises(HTTPException):
        giving_router.patch_giving_config(BIZ, {"funds": ["x" * 41]}, user)
    with pytest.raises(HTTPException):
        giving_router.patch_giving_config(
            BIZ, {"preset_amounts": [0]}, user)


def test_patch_refused_outside_nonprofit_family(monkeypatch):
    fake = FakeSB(business=_church(owner_id="u1", type="coaching"))
    monkeypatch.setattr(giving_router, "sb_clients", fake)
    user = SimpleNamespace(id="u1", email="x@example.com")
    with pytest.raises(HTTPException) as exc:
        giving_router.patch_giving_config(BIZ, {"enabled": True}, user)
    assert exc.value.status_code == 409
