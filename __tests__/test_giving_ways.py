# __tests__/test_giving_ways.py
#
# The ways a church's people give (giving_ways, Kevin 2026-11-01): the list
# the church keeps, the treasurer's menu it makes, "Other ways to give" on
# the give page, card-or-bank (never pay-later) on a gift checkout, and the
# books never treating a PayPal or other-app gift as a Stripe gift.

import asyncio
import urllib.parse
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import gl_engine
import giving_router
import giving_ways
import stripe_checkout_helpers

BIZ = "biz-0000-1111"


class FakeSB:
    def __init__(self, business=None):
        self.business = business or {}
        self.patches, self.posts = [], []

    def sb_get_as_service(self, path):
        if path.startswith("/businesses?"):
            return [self.business] if self.business else []
        if path.startswith("/business_sites?"):
            return [{"business_id": BIZ, "slug": "first-light"}]
        if path.startswith("/invoices?"):
            return []
        if path.startswith("/contacts?"):
            return [{"id": "c1"}]
        return []

    def sb_patch_as_service(self, path, payload):
        self.patches.append((path, payload))
        if path.startswith("/businesses?"):
            self.business = {**self.business, **payload}
        return [payload]

    def sb_post_as_service(self, path, payload):
        self.posts.append((path, payload))
        return [{"id": "new-gift", **payload}]


def _church(**over):
    biz = {"id": BIZ, "name": "First Light Church", "type": "church", "owner_id": "u1",
           "stripe_account_id": "acct_123",
           "settings": {"giving": {"enabled": True, "funds": ["General", "Building"]}}}
    biz.update(over)
    return biz


def _request(ip="9.9.9.9"):
    return SimpleNamespace(headers={}, client=SimpleNamespace(host=ip))


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(giving_ways, "switched_on", lambda bid: True)


@pytest.fixture(autouse=True)
def no_wallets(monkeypatch):
    monkeypatch.setattr(giving_router, "_schedule_wallet_domains", lambda biz: None)
    monkeypatch.setattr(giving_router, "ensure_business_site", lambda biz: ({"slug": "first-light"}, False))
    monkeypatch.delenv("STRIPE_GIVING_PMC", raising=False)


# ─── The list ──────────────────────────────────────────────────────────

def test_handles_are_checked_and_written_one_way():
    ways = giving_ways.clean_ways([
        {"app": "cashapp", "handle": "LoveCity", "show": True},
        {"app": "zelle", "handle": "231-555-0100", "show": True},
        {"app": "venmo", "handle": "@love-city"},
        {"app": "paypal", "handle": "https://paypal.me/LoveCity/"},
        {"app": "subsplash"},
        {"app": "other", "label": "Givelify", "link": "https://givelify.com/love"},
    ])
    assert [w["app"] for w in ways] == ["cashapp", "zelle", "venmo", "paypal", "subsplash", "other"]
    assert ways[0]["handle"] == "$LoveCity" and ways[0]["show"] is True
    assert ways[1]["handle"] == "(231) 555-0100"
    assert ways[2]["handle"] == "@love-city" and ways[2]["show"] is False
    assert ways[3]["handle"] == "LoveCity"
    assert "handle" not in ways[4]
    assert ways[5]["label"] == "Givelify"


@pytest.mark.parametrize("bad", [
    [{"app": "cashapp", "handle": "$1abc"}],                      # must start with a letter
    [{"app": "zelle", "handle": "555-0100"}],                     # not ten digits
    [{"app": "venmo", "handle": "ab"}],                           # too short
    [{"app": "other"}],                                           # unnamed
    [{"app": "other", "label": "X", "link": "http://insecure"}],   # https only
    [{"app": "zelle", "show": True}],                             # shown with nothing to show
    [{"app": "cashapp"}, {"app": "cashapp"}],                     # twice
    [{"app": "bitcoin"}],
    "cashapp",
])
def test_a_way_the_church_cant_use_is_refused_in_words(bad):
    with pytest.raises(giving_ways.WayError) as e:
        giving_ways.clean_ways(bad)
    assert str(e.value)


def test_a_saved_row_that_no_longer_checks_is_left_out():
    cfg = {"ways": [{"app": "cashapp", "handle": "$Love", "show": True}, {"app": "nope"}, "junk"]}
    assert giving_ways.stored_ways(cfg) == [{"app": "cashapp", "handle": "$Love", "show": True}]


# ─── The treasurer's menu ──────────────────────────────────────────────

def test_the_menu_is_cash_check_the_churchs_ways_then_bank_and_other():
    ways = giving_ways.clean_ways([{"app": "cashapp"}, {"app": "subsplash"},
                                   {"app": "other", "label": "Givelify"}])
    ids = [m["id"] for m in giving_ways.method_menu(ways)]
    assert ids == ["cash", "check", "cashapp", "subsplash bank payout", "other:Givelify",
                   "bank_transfer", "other"]


def test_menu_ids_become_the_gifts_method_token():
    assert giving_ways.parse_method("cashapp") == ("cashapp", None)
    assert giving_ways.parse_method("subsplash bank payout") == ("subsplash bank payout", None)
    assert giving_ways.parse_method("other:Givelify") == ("other", "Givelify")
    with pytest.raises(giving_ways.WayError):
        giving_ways.parse_method("crypto")
    with pytest.raises(giving_ways.WayError):
        giving_ways.parse_method("other:")


@pytest.mark.parametrize("token,account", [
    ("cashapp", "1000"), ("zelle", "1000"), ("venmo", "1000"), ("paypal", "1000"),
    ("other", "1000"), ("subsplash bank payout", "1000"), ("stripe", "1150"),
])
def test_the_books_never_treat_an_app_gift_as_a_stripe_gift(token, account):
    inv = {"id": "g1", "total": 50, "status": "paid", "paid_at": "2026-11-01T12:00:00Z",
           "payment_method": token, "is_gift": True, "invoice_number": "GIVE-manual-x"}
    debits = {l["code"] for e in gl_engine.desired_for_invoice(inv, "church") for l in e["lines"] if l.get("debit")}
    assert account in debits and not ({"1000", "1150"} - {account}) & debits


def test_the_ways_menu_follows_the_switch(monkeypatch):
    fake = FakeSB(business=_church(settings={"giving": {"ways": [{"app": "zelle"}]}}))
    monkeypatch.setattr(giving_router, "sb_clients", fake)
    import giving_records
    monkeypatch.setattr(giving_records, "require_finance", lambda b, u: "owner")
    user = SimpleNamespace(id="u1")
    monkeypatch.setattr(giving_ways, "switched_on", lambda bid: False)
    off = giving_router.giving_ways_menu(BIZ, user)
    assert off["on"] is False and [m["id"] for m in off["methods"]] == ["cash", "check", "bank_transfer", "other"]
    assert off["funds"] == ["General"]                    # no funds set: the default
    monkeypatch.setattr(giving_ways, "switched_on", lambda bid: True)
    on_ = giving_router.giving_ways_menu(BIZ, user)
    assert on_["on"] is True and "zelle" in [m["id"] for m in on_["methods"]]


def test_the_ways_menu_says_so_when_the_church_cant_be_read(monkeypatch, on):
    class Down(FakeSB):
        def sb_get_as_service(self, path):
            return None if path.startswith("/businesses?") else super().sb_get_as_service(path)
    monkeypatch.setattr(giving_router, "sb_clients", Down(business=_church()))
    import giving_records
    monkeypatch.setattr(giving_records, "require_finance", lambda b, u: "owner")
    with pytest.raises(HTTPException) as e:
        giving_router.giving_ways_menu(BIZ, SimpleNamespace(id="u1"))
    assert e.value.status_code == 503


def test_a_recorded_gift_takes_the_way_and_names_an_other_app(monkeypatch, on):
    fake = FakeSB(business=_church())
    monkeypatch.setattr(giving_router, "sb_clients", fake)
    import giving_records, vertical_family, church_keys
    monkeypatch.setattr(giving_records, "require_finance", lambda b, u: "owner")
    monkeypatch.setattr(church_keys, "wall", lambda *a, **k: None)
    monkeypatch.setattr(vertical_family, "is_nonprofit_like", lambda t: True)
    user = SimpleNamespace(id="u1")
    body = {"request_id": "00000000-0000-4000-8000-000000000001", "amount_cents": 2500,
            "received_on": "2026-10-25", "method": "other:Givelify", "fund": "General"}
    assert giving_router.create_manual_gift(BIZ, body, user)["ok"]
    row = fake.posts[-1][1]
    assert row["payment_method"] == "other" and "Given through Givelify" in row["notes"]
    assert "_way_name" not in row
    giving_router.create_manual_gift(BIZ, {**body, "request_id": "00000000-0000-4000-8000-000000000002",
                                           "method": "cashapp"}, user)
    assert fake.posts[-1][1]["payment_method"] == "cashapp"


def test_without_the_switch_the_plain_four_still_rule(monkeypatch):
    monkeypatch.setattr(giving_ways, "switched_on", lambda bid: False)
    with pytest.raises(HTTPException):
        giving_router._manual_gift_fields("b", {"amount_cents": 100, "received_on": "2026-10-25",
                                                "method": "cashapp"})


# ─── Saving the list and bank payments ─────────────────────────────────

def test_saving_ways_checks_them(monkeypatch, on):
    fake = FakeSB(business=_church())
    monkeypatch.setattr(giving_router, "sb_clients", fake)
    user = SimpleNamespace(id="u1")
    out = giving_router.patch_giving_config(BIZ, {"ways": [{"app": "cashapp", "handle": "Love", "show": True}]}, user)
    assert out["ways_on"] and out["ways"] == [{"app": "cashapp", "handle": "$Love", "show": True}]
    with pytest.raises(HTTPException) as e:
        giving_router.patch_giving_config(BIZ, {"ways": [{"app": "zelle", "show": True}]}, user)
    assert e.value.status_code == 400 and "Zelle" in e.value.detail


def test_ways_cant_be_saved_where_the_switch_is_off(monkeypatch):
    monkeypatch.setattr(giving_ways, "switched_on", lambda bid: False)
    monkeypatch.setattr(giving_router, "sb_clients", FakeSB(business=_church()))
    with pytest.raises(HTTPException) as e:
        giving_router.patch_giving_config(BIZ, {"ways": []}, SimpleNamespace(id="u1"))
    assert e.value.status_code == 409


def test_bank_payments_need_the_giving_set_and_stripes_yes(monkeypatch, on):
    fake = FakeSB(business=_church())
    monkeypatch.setattr(giving_router, "sb_clients", fake)
    user = SimpleNamespace(id="u1")
    with pytest.raises(HTTPException) as e:
        giving_router.patch_giving_config(BIZ, {"bank_payments": True}, user)
    assert e.value.status_code == 409                      # no giving set on the platform
    monkeypatch.setenv("STRIPE_GIVING_PMC", "pmc_1GivingSetAbc")
    monkeypatch.setattr(giving_ways, "bank_available", lambda acct: None)
    with pytest.raises(HTTPException) as e:
        giving_router.patch_giving_config(BIZ, {"bank_payments": True}, user)
    assert e.value.status_code == 503                      # Stripe couldn't be asked
    monkeypatch.setattr(giving_ways, "bank_available", lambda acct: False)
    with pytest.raises(HTTPException) as e:
        giving_router.patch_giving_config(BIZ, {"bank_payments": True}, user)
    assert e.value.status_code == 409 and "ACH" in e.value.detail
    monkeypatch.setattr(giving_ways, "bank_available", lambda acct: True)
    out = giving_router.patch_giving_config(BIZ, {"bank_payments": True}, user)
    assert out["bank_payments"] is True and out["bank_possible"] is True


# ─── The checkout ──────────────────────────────────────────────────────

def _checkout(monkeypatch, body, biz=None, ip="5.5.5.5"):
    fake = FakeSB(business=biz or _church())
    monkeypatch.setattr(giving_router, "sb_clients", fake)
    monkeypatch.setattr(giving_router, "_give_rate", {})
    captured = {}

    class StubAdapter:
        async def create_giving_checkout(self, biz, **kwargs):
            captured.update(kwargs)
            return {"url": "https://checkout.stripe.com/c/pay_z"}

    import payments_core
    monkeypatch.setattr(payments_core, "provider_for", lambda biz: StubAdapter())
    asyncio.run(giving_router.public_giving_checkout("first-light", body, _request(ip)))
    return captured


def test_a_gift_offers_card_and_link_never_pay_later(monkeypatch, on):
    got = _checkout(monkeypatch, {"amount_cents": 5000, "cover_fee": True})
    assert got["extra_form"] == {"allowed_payment_method_types[0]": "card",
                                 "allowed_payment_method_types[1]": "link"}
    assert got["cover_fee_cents"] == giving_router.covered_fee_cents(5000)
    assert got["success_url"].endswith("/give?thanks=1")


def test_the_giving_set_rides_every_gift_once_it_exists(monkeypatch, on):
    monkeypatch.setenv("STRIPE_GIVING_PMC", "pmc_1GivingSetAbc")
    got = _checkout(monkeypatch, {"amount_cents": 5000})
    assert got["extra_form"]["payment_method_configuration"] == "pmc_1GivingSetAbc"


def test_a_bank_gift_covers_the_bank_fee_and_says_so_on_return(monkeypatch, on):
    monkeypatch.setenv("STRIPE_GIVING_PMC", "pmc_1GivingSetAbc")
    biz = _church(settings={"giving": {"enabled": True, "funds": ["General"], "bank_payments": True}})
    got = _checkout(monkeypatch, {"amount_cents": 10000, "cover_fee": True, "pay_with": "bank"}, biz)
    assert got["extra_form"]["allowed_payment_method_types[0]"] == "us_bank_account"
    assert got["cover_fee_cents"] == giving_ways.fee_cents(10000, "bank") == 81
    assert got["success_url"].endswith("?thanks=1&bank=1")


def test_bank_is_refused_where_the_church_hasnt_turned_it_on(monkeypatch, on):
    with pytest.raises(HTTPException) as e:
        _checkout(monkeypatch, {"amount_cents": 5000, "pay_with": "bank"})
    assert e.value.status_code == 400
    with pytest.raises(HTTPException):
        _checkout(monkeypatch, {"amount_cents": 5000, "pay_with": "crypto"}, ip="6.6.6.6")


def test_where_the_switch_is_off_the_checkout_is_unchanged(monkeypatch):
    monkeypatch.setattr(giving_ways, "switched_on", lambda bid: False)
    got = _checkout(monkeypatch, {"amount_cents": 5000, "cover_fee": True})
    assert "extra_form" not in got
    assert got["cover_fee_cents"] == giving_router.covered_fee_cents(5000)


def test_the_bank_fee_is_capped_at_five_dollars():
    assert giving_ways.fee_cents(62000, "bank") == 500
    assert giving_ways.fee_cents(500000, "bank") == 500
    assert giving_ways.fee_cents(5000, "card") == giving_router.covered_fee_cents(5000)
    assert giving_ways.fee_cents(0, "bank") == 0


class _Resp:
    def __init__(self, code, text="", data=None):
        self.status_code, self.text, self._data = code, text, data or {}

    def json(self):
        return self._data


def _stripe(monkeypatch, refuse):
    """A Stripe that 400s naming `refuse` while that field is sent."""
    sent = []

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, auth=None, headers=None, data=None):
            sent.append(dict(data))
            if any(k.split("[")[0] == refuse for k in data):
                return _Resp(400, "refused", {"error": {"param": refuse, "message": "Received unknown parameter"}})
            return _Resp(200, "", {"id": "cs_1", "url": "https://checkout.stripe.com/x"})

    monkeypatch.setattr(stripe_checkout_helpers.httpx, "AsyncClient", Client)
    monkeypatch.setattr(stripe_checkout_helpers, "require_stripe_write", lambda acct: None)
    monkeypatch.setattr(stripe_checkout_helpers, "_secret_key", lambda: "sk_test_x")
    return sent


def _gift(extras):
    return asyncio.run(stripe_checkout_helpers.create_giving_checkout(
        stripe_account_id="acct_1", gift_id="g", business_id="b", amount_cents=5000, fund="General",
        fund_label="General Fund", fund_kind="general", monthly=False, giver_name=None, giver_email=None,
        success_url="https://x/give?thanks=1", cancel_url="https://x/give?canceled=1", extra_form=extras))


def test_a_refused_card_filter_never_stops_a_gift_and_keeps_the_giving_set(monkeypatch):
    monkeypatch.setenv("STRIPE_GIVING_PMC", "pmc_1GivingSetAbc")
    sent = _stripe(monkeypatch, "allowed_payment_method_types")
    assert _gift(giving_ways.checkout_extras("card"))["id"] == "cs_1" and len(sent) == 2
    assert "allowed_payment_method_types[0]" not in sent[1]
    assert sent[1]["payment_method_configuration"] == "pmc_1GivingSetAbc"
    assert sent[1]["metadata[pay_filter_fallback]"] == "allowed_payment_method_types"


def test_a_refused_giving_set_keeps_the_filter(monkeypatch):
    monkeypatch.setenv("STRIPE_GIVING_PMC", "pmc_1GivingSetAbc")
    sent = _stripe(monkeypatch, "payment_method_configuration")
    assert _gift(giving_ways.checkout_extras("card"))["id"] == "cs_1"
    assert "payment_method_configuration" not in sent[1]
    assert sent[1]["allowed_payment_method_types[0]"] == "card"


def test_a_bank_gift_is_never_turned_into_a_card_gift(monkeypatch):
    monkeypatch.setenv("STRIPE_GIVING_PMC", "pmc_1GivingSetAbc")
    sent = _stripe(monkeypatch, "allowed_payment_method_types")
    with pytest.raises(RuntimeError):
        _gift(giving_ways.checkout_extras("bank"))
    assert len(sent) == 1


def test_a_400_that_names_no_extra_is_not_retried(monkeypatch):
    sent = _stripe(monkeypatch, "line_items")
    with pytest.raises(RuntimeError):
        _gift(giving_ways.checkout_extras("card"))
    assert len(sent) == 1


# ─── The give page ─────────────────────────────────────────────────────

def test_the_give_page_shows_the_ways_the_church_chose(monkeypatch, on):
    biz = _church(settings={"giving": {"enabled": True, "funds": ["General"], "ways": [
        {"app": "cashapp", "handle": "$LoveCity", "show": True},
        {"app": "zelle", "handle": "give@lovecity.org", "show": True},
        {"app": "venmo", "handle": "@lovecity-church", "show": False}]}})
    html = giving_router.render_give_page(biz, "https://first-light.mysolutionist.app/give", "first-light",
                                          api_origin="https://api.example")
    assert 'id="gv-ways-h"' in html
    assert 'data-way-base="https://cash.app/$LoveCity" data-way-amt' in html
    assert 'data-copy="give@lovecity.org"' in html
    assert "venmo.com" not in html                     # not shown
    assert 'class="gv-paywith"' not in html           # no bank choice without the giving set
    embed = giving_router.render_give_embed(biz, "first-light", api_origin="https://api.example")
    assert "Other ways to give" in embed


def test_the_bank_choice_shows_only_where_bank_is_ready(monkeypatch, on):
    monkeypatch.setenv("STRIPE_GIVING_PMC", "pmc_1GivingSetAbc")
    biz = _church(settings={"giving": {"enabled": True, "funds": ["General"], "bank_payments": True}})
    html = giving_router.render_give_page(biz, "https://x/give", "first-light", api_origin="https://api.example")
    assert 'data-pay="bank"' in html and "pay_with: payWith ? pay : undefined" in html


def test_where_the_switch_is_off_the_give_page_is_unchanged(monkeypatch):
    monkeypatch.setattr(giving_ways, "switched_on", lambda bid: False)
    biz = _church(settings={"giving": {"enabled": True, "funds": ["General"], "bank_payments": True,
                                       "ways": [{"app": "cashapp", "handle": "$L", "show": True}]}})
    html = giving_router.render_give_page(biz, "https://x/give", "first-light", api_origin="https://api.example")
    assert 'id="gv-ways-h"' not in html and 'class="gv-paywith"' not in html


def test_a_handle_is_escaped_on_the_page(on):
    ways = [{"app": "other", "label": "Give<b>", "handle": "a\"b<script>", "show": True}]
    html = giving_ways.ways_html(ways)
    assert "<script>" not in html and "&lt;b&gt;" in html


def test_the_treasurer_gets_every_fund_the_church_set(monkeypatch):
    fake = FakeSB(business=_church(settings={"giving": {"funds": ["Tithes", "Outreach", "Youth Department", "Offering"]}}))
    monkeypatch.setattr(giving_router, "sb_clients", fake)
    import giving_records
    monkeypatch.setattr(giving_records, "require_finance", lambda b, u: "owner")
    for on_ in (True, False):
        monkeypatch.setattr(giving_ways, "switched_on", lambda bid, v=on_: v)
        got = giving_router.giving_ways_menu(BIZ, SimpleNamespace(id="u1"))
        assert got["funds"] == ["Tithes", "Outreach", "Youth Department", "Offering"]
