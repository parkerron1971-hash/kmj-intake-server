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
  5. The site says it under the cards while places are left; the app reads
     it from /billing/plans and /billing/church/move.
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
    assert seen[0].startswith("/businesses?settings->founding_church=not.is.null&select=id")
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


def test_the_line_says_how_many_places_are_left(monkeypatch):
    html = _line(monkeypatch, {"spots": 10, "left": 7})
    assert "Founding price</b>" in html
    assert ("The first ten churches keep the price they start at, for as long as they stay. "
            '<b style="color: #0B0C11">7</b> of 10 left.') in html


@pytest.mark.parametrize("state", [None, {"spots": 10, "left": 0}])
def test_no_line_while_off_unread_or_gone(monkeypatch, state):
    assert _line(monkeypatch, state) == ""


def test_the_line_is_in_the_solutionist_voice(monkeypatch):
    import brand_voice
    html = _line(monkeypatch, {"spots": 10, "left": 10})
    assert html and brand_voice.offenses(f"<html><body>{html}</body></html>") == []


def test_the_overview_carries_it_under_the_cards(monkeypatch):
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    monkeypatch.setattr(cf, "public_state", lambda: {"spots": 10, "left": 9})
    html = cs.render("")
    assert html.index("Founding price</b>") > html.index("Good to know</b>") > html.index('<div class="plans four">')
    assert "<b style=\"color: #0B0C11\">9</b> of 10 left." in html


def test_public_state_follows_the_switch_and_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(cf, "left", lambda: calls.append(1) or 6)
    assert cf.public_state() == {"spots": 10, "left": 6}
    assert cf.public_state() == {"spots": 10, "left": 6} and len(calls) == 1      # read once per five minutes
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
    assert out["church_founding"] == {"on": True, "spots": 10, "left": 8}
    assert asyncio.run(sb.billing_plans(for_type="barber"))["church_founding"] is None

    async def load(bid):
        return {"id": bid, "owner_id": "u-1", "type": "church", "comp_tier": "church_growing",
                "settings": {"founding_church": {"n": 2, "plan": GROWING}}}
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(cb, "_founding_taken", lambda: 1)
    status = asyncio.run(cb.move_status(BIZ, user=USER))
    assert status["founding_church"] == {"n": 2, "plan": GROWING}
    assert status["founding_price"] == {"on": True, "spots": 10, "left": 8}
