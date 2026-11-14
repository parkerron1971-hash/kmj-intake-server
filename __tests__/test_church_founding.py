"""The founding churches keep the price they start at (Kevin, 2026-11-13:
"yes founding prices"; church_founding.py).

  1. A place is taken by the first PAID month on a church plan, once, while
     one is left; never by a comped church or the platform owner's own.
  2. The webhook takes it on `active` church plans only, and a claim that
     fails never fails the webhook.
  3. Checkout gives a founding church (or one taking an open place) the
     founding price once one is set, everyone else the list price, and
     refuses a founding price asked for without a place.
  4. A founding or kept price id still means its plan.
  5. The site says it while places are left: a band above the cards and each
     card's founding price under its regular price crossed out (board C,
     Kevin 2026-11-14); the app reads it from /billing/plans and
     /billing/church/move.
  6. The offer ends on FOUNDING_CHURCHES_UNTIL (2027-01-31) or when the ten
     places are taken: then the regular price alone, for everyone new.
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

import church_billing as cb  # noqa: E402
import church_founding as cf  # noqa: E402
import church_site as cs  # noqa: E402
import feature_gates as fg  # noqa: E402
import stripe_billing as sb  # noqa: E402
from auth_supabase import AuthedUser  # noqa: E402

USER = AuthedUser(id="u-1", email="pastor@church.test", role="authenticated")
BIZ = "b0000000-0000-4000-8000-000000000001"
SMALL, GROWING, ESTABLISHED, LARGE = fg.CHURCH_PLANS


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for k in ("FOUNDING_CHURCHES", "FOUNDING_CHURCH_SPOTS", "STRIPE_PRICE_IDS_KEPT"):
        monkeypatch.delenv(k, raising=False)
    # Far off, so these tests don't start failing on 2027-02-01; the end
    # date's own tests set it.
    monkeypatch.setenv("FOUNDING_CHURCHES_UNTIL", "2099-01-31")
    for plan in fg.CHURCH_PLANS:
        for annual in (False, True):
            monkeypatch.delenv(cf._env_key(plan, annual), raising=False)
    cf.forget()
    yield
    cf.forget()


# ─── 1. taking a place ───────────────────────────────────────────────

@pytest.fixture
def church(monkeypatch):
    state = {"biz": {"id": BIZ, "owner_id": "u-1", "comp_tier": None, "settings": {"other": "kept"}},
             "taken": 3, "owner": False, "writes": []}

    async def load(bid):
        return state["biz"]

    async def patch(bid, body, match=None):
        state["writes"].append(body)
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_patch_business", patch)
    monkeypatch.setattr(cf, "taken", lambda: state["taken"])
    monkeypatch.setattr(cf, "_owner_is_platform", lambda owner_id: state["owner"])
    return state


def _claim(plan=GROWING, price="price_grow"):
    return asyncio.run(cf.claim(BIZ, plan, price))


def test_the_first_paid_month_takes_the_next_place(church):
    place = _claim()
    assert place["n"] == 4 and place["plan"] == GROWING and place["price_id"] == "price_grow" and place["at"]
    [write] = church["writes"]
    assert write == {"settings": {"other": "kept", "founding_church": place}}   # nothing else touched


def test_a_place_is_written_once(church):
    church["biz"]["settings"]["founding_church"] = {"n": 2, "plan": SMALL}
    assert _claim() == {"n": 2, "plan": SMALL}
    assert church["writes"] == []


@pytest.mark.parametrize("taken,spots,takes", [(9, None, True), (10, None, False), (12, None, False),
                                               (4, "5", True), (5, "5", False), (0, "0", False)])
def test_never_past_the_places(church, monkeypatch, taken, spots, takes):
    church["taken"] = taken
    if spots is not None:
        monkeypatch.setenv("FOUNDING_CHURCH_SPOTS", spots)
    assert (_claim() is not None) is takes
    assert bool(church["writes"]) is takes


def test_an_unreadable_count_takes_nothing(church):
    church["taken"] = None
    assert _claim() is None and church["writes"] == []


def test_a_comped_church_takes_no_place(church):
    church["biz"]["comp_tier"] = "church_growing"
    assert _claim() is None and church["writes"] == []


@pytest.mark.parametrize("owner", [True, None])        # the owner's own church, or the owner unread
def test_the_platform_owners_churches_take_no_place(church, owner):
    church["owner"] = owner
    assert _claim() is None and church["writes"] == []


@pytest.mark.parametrize("plan", ["professional", "cs_both", None, "church_tiny"])
def test_only_a_church_plan_takes_a_place(church, plan):
    assert _claim(plan=plan) is None and church["writes"] == []


def test_the_count_reads_the_settings_key(monkeypatch):
    import sb_clients
    seen = []

    def get(path):
        seen.append(path)
        return [{"id": "a"}, {"id": "b"}]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    assert cf.taken() == 2 and cf.left() == 8
    # A sample church never holds a place (sample_church.py, BE-3).
    assert seen[0].startswith("/businesses?settings->founding_church=not.is.null&is_sample=not.is.true&select=id")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: None)
    assert cf.taken() is None and cf.left() is None


# ─── 2. the webhook ──────────────────────────────────────────────────

def _webhook(monkeypatch, status="active", price="price_grow", boom=False):
    claims, patches = [], []
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING", "price_grow")
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")

    async def patch(bid, body, match=None):
        patches.append(body)

    async def sync(*a):
        return None

    async def claim(bid, plan, pid):
        if boom:
            raise RuntimeError("supabase is down")
        claims.append((bid, plan, pid))
    monkeypatch.setattr(sb, "_patch_business", patch)
    monkeypatch.setattr(cb, "sync_extra_logins", sync)
    monkeypatch.setattr(cf, "claim", claim)
    asyncio.run(sb._apply_subscription_state("customer.subscription.updated",
                                             {"id": "sub_1", "status": status,
                                              "items": {"data": [{"price": {"id": price}, "quantity": 1}]}}, BIZ))
    return claims, patches


def test_the_webhook_takes_a_place_on_a_paid_church_plan(monkeypatch):
    claims, patches = _webhook(monkeypatch)
    assert claims == [(BIZ, GROWING, "price_grow")] and patches[0]["subscription_status"] == "active"


@pytest.mark.parametrize("status,price", [("trialing", "price_grow"), ("past_due", "price_grow"),
                                          ("canceled", "price_grow"), ("active", "price_pro")])
def test_no_place_on_a_trial_a_lapse_or_another_plan(monkeypatch, status, price):
    claims, _ = _webhook(monkeypatch, status=status, price=price)
    assert claims == []


def test_a_claim_that_fails_never_fails_the_webhook(monkeypatch):
    claims, patches = _webhook(monkeypatch, boom=True)
    assert patches and patches[0]["subscription_plan"] == "price_grow"


# ─── 3. checkout ─────────────────────────────────────────────────────

@pytest.fixture
def prices(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING", "price_grow_249")
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING_ANNUAL", "price_grow_y_2490")
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING_FOUNDING", "price_grow_199")
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING_ANNUAL_FOUNDING", "price_grow_y_1990")
    state = {"left": 4}
    monkeypatch.setattr(cf, "left", lambda: state["left"])
    return state


def _price(biz, price_id):
    return asyncio.run(cf.checkout_price(biz, GROWING, price_id))


def test_an_open_place_gets_the_founding_price(prices):
    assert _price({}, "price_grow_249") == "price_grow_199"
    assert _price({}, "price_grow_y_2490") == "price_grow_y_1990"          # the yearly one stays yearly


def test_a_founding_church_keeps_it_with_the_places_gone_and_the_offer_off(prices, monkeypatch):
    prices["left"] = 0
    monkeypatch.setenv("FOUNDING_CHURCHES", "off")
    founding = {"settings": {"founding_church": {"n": 3}}}
    assert _price(founding, "price_grow_249") == "price_grow_199"


@pytest.mark.parametrize("left,switch", [(0, "on"), (None, "on"), (4, "off")])
def test_everyone_else_pays_the_list_price(prices, monkeypatch, left, switch):
    prices["left"] = left
    monkeypatch.setenv("FOUNDING_CHURCHES", switch)
    assert _price({}, "price_grow_249") == "price_grow_249"


def test_a_founding_price_without_a_place_is_refused(prices):
    prices["left"] = 0
    with pytest.raises(HTTPException) as e:
        _price({}, "price_grow_199")
    assert e.value.status_code == 409


def test_unset_the_founding_price_is_the_list_price(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING", "price_grow")
    monkeypatch.setattr(cf, "left", lambda: 10)
    assert _price({}, "price_grow") == "price_grow"                         # today: nothing changes


@pytest.fixture
def checkout(monkeypatch, prices):
    posted, switched = [], []
    state = {"biz": {"id": "biz-1", "owner_id": "u-1", "name": "Grace Fellowship", "stripe_customer_id": "cus_1",
                     "type": "church", "settings": {}}}

    async def stripe_post(path, data):
        posted.append((path, data))
        return {"id": "cs_x", "url": "https://checkout.stripe.test/x"}

    async def load(bid):
        return state["biz"]

    async def taken():
        return 0

    async def switch(biz, sub_id, price_id, plan):
        switched.append(price_id)
        return {"switched": True}
    monkeypatch.setattr(sb, "_stripe_post", stripe_post)
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_founder_seats_taken", taken)
    monkeypatch.setattr(sb, "_switch_plan", switch)
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    monkeypatch.setenv("STRIPE_PRICE_ID_DEFAULT", "price_pro")
    return posted, switched, state


def _buy(**body):
    return asyncio.run(sb.create_checkout(sb.CheckoutBody(business_id="biz-1", **body), user=USER))


def test_checkout_sells_the_founding_price_while_a_place_is_open(checkout, prices):
    posted, _, _ = checkout
    _buy(plan=GROWING)
    [session] = [d for p, d in posted if p == "/checkout/sessions"]
    assert session["line_items"] == [{"price": "price_grow_199", "quantity": 1}]
    prices["left"] = 0
    _buy(plan=GROWING)
    assert [d for p, d in posted if p == "/checkout/sessions"][1]["line_items"][0]["price"] == "price_grow_249"


def test_a_founding_church_changing_size_moves_at_the_founding_price(checkout, prices, monkeypatch):
    _, switched, state = checkout
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_LARGE", "price_large_799")
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_LARGE_FOUNDING", "price_large_699")
    prices["left"] = 0
    state["biz"].update(subscription_status="active", stripe_subscription_id="sub_1",
                        settings={"founding_church": {"n": 1}})
    _buy(plan=LARGE)
    _buy(plan=GROWING)
    assert switched == ["price_large_699", "price_grow_199"]


def test_a_raw_founding_price_id_without_a_place_is_refused(checkout, prices):
    posted, _, _ = checkout
    prices["left"] = 0
    with pytest.raises(HTTPException) as e:
        _buy(price_id="price_grow_199")
    assert e.value.status_code == 409 and not [d for p, d in posted if p == "/checkout/sessions"]


# ─── 4. the price still means the plan ───────────────────────────────

def test_founding_and_kept_prices_mean_their_plan(prices, monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_IDS_KEPT", " price_old_229 = church_growing , price_bad=nonsense, =church_large ")
    p2p = fg.price_to_plan()
    assert p2p["price_grow_199"] == p2p["price_grow_y_1990"] == p2p["price_old_229"] == GROWING
    assert "price_bad" not in p2p and "" not in p2p
    assert fg.plan_of({"subscription_status": "active", "subscription_plan": "price_grow_199"}) == GROWING
    for plan in fg.CHURCH_PLANS:
        for annual in (False, True):
            assert fg.PRICE_ENV_TO_PLAN[cf._env_key(plan, annual)[len("STRIPE_PRICE_ID_"):]] == plan


def test_a_kept_price_never_overrides_a_live_one(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING", "price_x")
    monkeypatch.setenv("STRIPE_PRICE_IDS_KEPT", "price_x=church_large")
    assert fg.price_to_plan()["price_x"] == GROWING


# ─── 5. where it's said ──────────────────────────────────────────────

def _line(monkeypatch, state):
    monkeypatch.setattr(cf, "public_state", lambda: state)
    return cs._founding_line()


def _no_saving(monkeypatch):
    """Founding prices equal to the regular ones: nothing to cross out."""
    import pricing_config
    for plan, cents in pricing_config.church_price_cents().items():
        monkeypatch.setenv(f"PRICE_FOUNDING_{plan.upper()}_CENTS", str(cents))


def test_the_line_says_how_many_places_are_left(monkeypatch):
    # Only when no card can show a saving (the band says it otherwise).
    _no_saving(monkeypatch)
    html = _line(monkeypatch, {"spots": 10, "left": 7, "ends": "2099-01-31"})
    assert "Founding price</b>" in html
    assert ("The first ten churches keep the price they start at, for as long as they stay. "
            'The offer ends January 31. <b style="color: #0B0C11">7</b> of 10 left.') in html


@pytest.mark.parametrize("state", [None, {"spots": 10, "left": 0}])
def test_no_line_while_off_unread_or_gone(monkeypatch, state):
    assert _line(monkeypatch, state) == ""


def test_no_line_under_the_cards_while_the_band_says_it(monkeypatch):
    assert _line(monkeypatch, {"spots": 10, "left": 7}) == ""


def _overview(monkeypatch, state):
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    monkeypatch.setattr(cf, "public_state", lambda: state)
    return cs.render("")


def test_the_band_says_what_the_first_ten_save_and_when_it_ends(monkeypatch):
    html = _overview(monkeypatch, {"spots": 10, "left": 7, "ends": "2099-01-31"})
    band = html[html.index('<div class="fband">'):html.index('<div class="plans four">')]
    assert "Founding church offer" in band
    # Large saves the most: ($899 - $699) x 12.
    assert "The first ten churches save up to $2,400 a year, for as long as they stay." in band
    assert ("The offer ends when ten churches have joined or on January 31, whichever comes first. "
            "After that, every new church pays the regular price.") in band
    assert "<b>7</b> of 10 founding places left" in band
    assert band.count('<i class="on"></i>') == 7 and band.count("<i></i>") == 3
    assert "Founding price</b>" not in html                       # not said twice


def test_each_card_leads_with_its_founding_price_and_crosses_out_the_regular(monkeypatch):
    html = _overview(monkeypatch, {"spots": 10, "left": 7, "ends": "2099-01-31"})
    cards = html[html.index('<div class="plans four">'):]
    assert cards.count('<span class="fchip">Founding price</span>') == 4
    for reg, reg_y, fnd, fnd_y, save_m, save_y in (
            ("99", "990", "79", "790", "Save $20 a month · $240 a year", "Save $200 a year"),
            ("249", "2,490", "199", "1,990", "Save $50 a month · $600 a year", "Save $500 a year"),
            ("499", "4,990", "399", "3,990", "Save $100 a month · $1,200 a year", "Save $1,000 a year"),
            ("899", "8,990", "699", "6,990", "Save $200 a month · $2,400 a year", "Save $2,000 a year")):
        assert (f'Regular price <s>$<span class="pnum" data-m="{reg}" data-y="{reg_y}">{reg}</span></s>') in cards
        assert f'<b>$<span class="pnum" data-m="{fnd}" data-y="{fnd_y}">{fnd}</span></b>' in cards
        assert f'data-m="{save_m}" data-y="{save_y}">{save_m}<' in cards
    assert cards.count("Your price stays locked for as long as you stay.") == 4
    assert cards.count(">Claim a founding place</a>") == 4
    # One plan, two prices: the credits are the plan's at both.
    assert "<b>7,500</b><span>AI actions a month</span>" in cards


def test_the_strip_and_the_picker_say_the_founding_price(monkeypatch):
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    monkeypatch.setattr(cf, "public_state", lambda: {"spots": 10, "left": 7, "ends": "2099-01-31"})
    strip = cs._plan_strip()
    assert ('<span class="preg">Regular price <s>$249</s></span>'
            '<span class="pp">$199 <small>a month, founding price</small></span>') in strip
    grow = cs._picker_data()["plans"][1]
    assert grow["m"] == "$199" and grow["y"] == "$1,990"
    assert grow["items"][0] == "Founding price, regular $249 a month"


def test_no_deal_once_the_places_are_gone_or_the_offer_is_off(monkeypatch):
    for state in (None, {"spots": 10, "left": 0, "ends": "2099-01-31"}):
        html = _overview(monkeypatch, state)
        assert 'class="fband"' not in html and "Regular price" not in html and 'class="fchip"' not in html
        assert 'data-m="249" data-y="2,490">249<' in html          # the regular price alone
        assert "Claim a founding place" not in html


def test_nothing_is_crossed_out_that_isnt_a_saving(monkeypatch):
    _no_saving(monkeypatch)
    html = _overview(monkeypatch, {"spots": 10, "left": 7, "ends": "2099-01-31"})
    assert "Regular price" not in html and 'class="fband"' not in html
    assert cf.offer_prices() is None


def test_the_offer_is_in_the_solutionist_voice(monkeypatch):
    import brand_voice
    html = _overview(monkeypatch, {"spots": 10, "left": 10, "ends": "2099-01-31"})
    band = html[html.index('<div class="fband">'):html.index('<div class="plans four">') + 4000]
    assert brand_voice.offenses(f"<html><body>{band}</body></html>") == []
    _no_saving(monkeypatch)
    line = _line(monkeypatch, {"spots": 10, "left": 10, "ends": "2099-01-31"})
    assert line and brand_voice.offenses(f"<html><body>{line}</body></html>") == []


def test_public_state_follows_the_switch_and_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(cf, "left", lambda: calls.append(1) or 6)
    assert cf.public_state() == {"spots": 10, "left": 6, "ends": "2099-01-31"}
    assert cf.public_state() == {"spots": 10, "left": 6, "ends": "2099-01-31"} and len(calls) == 1  # once per 5 min
    monkeypatch.setenv("FOUNDING_CHURCHES", "off")
    assert cf.public_state() is None


def test_the_plans_endpoint_and_the_move_status_carry_it(monkeypatch):
    async def no_display(pid):
        return {}

    async def no_founder():
        return {"configured": False}
    monkeypatch.setattr(sb, "_price_display", no_display)
    monkeypatch.setattr(sb, "_founder_summary", no_founder)
    monkeypatch.setattr(cf, "public_state", lambda: {"spots": 10, "left": 8})
    assert asyncio.run(sb.billing_plans(for_type="church"))["church_founding"] is None     # not on sale yet
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    out = asyncio.run(sb.billing_plans(for_type="church"))
    assert out["church_founding"] == {
        "on": True, "spots": 10, "left": 8, "ends": None,
        "prices": {SMALL: {"month_cents": 7900, "year_cents": 79000},
                   GROWING: {"month_cents": 19900, "year_cents": 199000},
                   ESTABLISHED: {"month_cents": 39900, "year_cents": 399000},
                   LARGE: {"month_cents": 69900, "year_cents": 699000}}}
    assert asyncio.run(sb.billing_plans(for_type="barber"))["church_founding"] is None

    async def load(bid):
        return {"id": bid, "owner_id": "u-1", "type": "church", "comp_tier": "church_growing",
                "settings": {"founding_church": {"n": 2, "plan": GROWING}}}
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(cb, "_founding_taken", lambda: 1)
    status = asyncio.run(cb.move_status(BIZ, user=USER))
    assert status["founding_church"] == {"n": 2, "plan": GROWING}
    assert status["founding_price"] == {"on": True, "spots": 10, "left": 8, "ends": None}


# ─── 6. the end date ─────────────────────────────────────────────────

def test_it_ends_at_midnight_eastern_after_january_31(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setenv("FOUNDING_CHURCHES_UNTIL", "2027-01-31")
    assert cf.until().isoformat() == "2027-01-31" and cf.ends_words() == "January 31"
    assert cf.closes_at() == datetime(2027, 2, 1, 5, 0, tzinfo=timezone.utc)
    assert cf.open_now(datetime(2027, 2, 1, 4, 59, tzinfo=timezone.utc))        # 11:59 PM on the 31st, Eastern
    assert not cf.open_now(datetime(2027, 2, 1, 5, 0, tzinfo=timezone.utc))
    monkeypatch.setenv("FOUNDING_CHURCHES", "off")
    assert not cf.open_now(datetime(2026, 12, 1, tzinfo=timezone.utc))


def test_the_default_end_is_january_31_2027(monkeypatch):
    monkeypatch.delenv("FOUNDING_CHURCHES_UNTIL")
    assert cf.until().isoformat() == "2027-01-31"
    monkeypatch.setenv("FOUNDING_CHURCHES_UNTIL", "not a date")
    assert cf.until().isoformat() == "2027-01-31"                                 # never quietly "no end"
    monkeypatch.setenv("FOUNDING_CHURCHES_UNTIL", "none")
    assert cf.until() is None and cf.closes_at() is None and cf.open_now() and cf.ends_words() == ""


def test_past_the_date_nothing_is_promised_and_new_churches_pay_the_regular_price(prices, monkeypatch):
    monkeypatch.setenv("FOUNDING_CHURCHES_UNTIL", "2026-01-31")
    monkeypatch.setattr(cf, "taken", lambda: 2)
    assert cf.public_state() is None and cf.offer_prices() is None
    assert _price({}, "price_grow_249") == "price_grow_249"
    with pytest.raises(HTTPException):
        _price({}, "price_grow_199")
    # A church that holds a place keeps its price after the date.
    assert _price({"settings": {"founding_church": {"n": 1}}}, "price_grow_249") == "price_grow_199"


def test_past_the_date_a_place_goes_only_to_a_church_on_a_founding_price(church, monkeypatch):
    monkeypatch.setenv("FOUNDING_CHURCHES_UNTIL", "2026-01-31")
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING_FOUNDING", "price_grow_199")
    assert _claim(price="price_grow_249") is None and church["writes"] == []
    assert _claim(price="price_grow_199")["n"] == 4                 # chose its plan in time, paid now


# ─── what a church pays, for its first month and its move ────────────

def test_a_church_pays_its_own_price(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING_FOUNDING", "price_grow_199")
    assert cf.price_cents_for({}, GROWING) == 24900
    assert cf.price_cents_for({"settings": {"founding_church": {"n": 1}}}, GROWING) == 19900
    assert cf.price_cents_for({"subscription_plan": "price_grow_199"}, GROWING) == 19900
    assert cb._move_cents(GROWING, {"settings": {"founding_church": {"n": 1}}}) == 3 * 19900
    assert cb._first_payment_cents(GROWING, {}) == 24900


# ─── Stripe: the catalog says what the dials say ─────────────────────

def test_the_catalog_carries_the_regular_and_the_founding_prices():
    import pricing_config
    cat = {env: (lookup, cents, interval) for env, lookup, _name, cents, interval in sb.BOOTSTRAP_CATALOG}
    regular, founding = pricing_config.church_price_cents(), pricing_config.church_founding_price_cents()
    for plan in fg.CHURCH_PLANS:
        key = f"STRIPE_PRICE_ID_{plan.upper()}"
        assert cat[key][1:] == (regular[plan], "month") and cat[key + "_ANNUAL"][1:] == (regular[plan] * 10, "year")
        assert cat[key][0].endswith("_monthly_2026_11")              # new keys: the old ones name old amounts
        assert cat[key + "_FOUNDING"][1:] == (founding[plan], "month")
        assert cat[key + "_ANNUAL_FOUNDING"][1:] == (founding[plan] * 10, "year")
        # The founding prices are the 2026-11-03 prices, reused by their keys.
        assert cat[key + "_FOUNDING"][0] == f"solutionist_{plan}_monthly"
        assert cf._env_key(plan, False) == key + "_FOUNDING"
        assert cf._env_key(plan, True) == key + "_ANNUAL_FOUNDING"
