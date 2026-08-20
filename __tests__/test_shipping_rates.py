"""Shipping rates — what it costs and who decides.

The contract under test:
  • a business that set a flat fee and never opens the new screen keeps
    charging EXACTLY what it charged yesterday. `flat_shipping_cents`
    has been the whole of shipping since Arc 27 and silently changing
    it would alter live prices on live storefronts;
  • nothing physical in the basket = shipping is not a question;
  • the surcharge is per UNIT — per-line would let somebody order ten
    heavy chairs and pay the postage for one;
  • "free over $50" means FREE. A threshold that still charges the
    heavy-item surcharge is a promise broken on the last screen;
  • a carrier being slow, down or malformed cannot stop a sale;
  • the client sends a CODE, never an amount. resolve() prices it here.
"""
from __future__ import annotations

import shipping_rates as sr


def _biz(**store):
    return {"settings": {"store": store}}


def _item(price_cents=1000, qty=1, physical=True, surcharge=0, weight=None):
    return {"requires_shipping": physical, "quantity": qty,
            "ship_surcharge_cents": surcharge, "weight_oz": weight,
            "unit_amount_cents": price_cents}


# ─── Settings, and not breaking live storefronts ─────────────────────


def test_the_old_flat_fee_still_rules_when_nothing_new_is_set():
    # THE ALARM. Every business on the platform is in this state right
    # now. If this drifts, real storefronts change price overnight.
    cfg = sr.settings_of(_biz(flat_shipping_cents=500))
    assert cfg["flat_cents"] == 500
    assert cfg["free_over_cents"] is None
    assert cfg["pickup_enabled"] is False
    assert cfg["countries"] == ["US"]


def test_a_new_flat_rate_overrides_the_old_one():
    cfg = sr.settings_of(_biz(flat_shipping_cents=500,
                              shipping={"flat_cents": 700}))
    assert cfg["flat_cents"] == 700


def test_a_new_flat_rate_of_zero_is_respected_not_treated_as_unset():
    # "Shipping is free, always" has to be expressible. Falling back to
    # the legacy fee here would make free shipping impossible to set.
    cfg = sr.settings_of(_biz(flat_shipping_cents=500,
                              shipping={"flat_cents": 0}))
    assert cfg["flat_cents"] == 0


def test_settings_survive_junk():
    for junk in ({}, {"store": None}, {"store": {"shipping": "nonsense"}},
                 {"store": {"flat_shipping_cents": "abc"}}):
        cfg = sr.settings_of({"settings": junk})
        assert cfg["flat_cents"] == 0
        assert cfg["countries"] == ["US"]


def test_countries_are_normalised_and_capped():
    cfg = sr.settings_of(_biz(shipping={"countries": ["us", "ca", "gb"]}))
    assert cfg["countries"] == ["US", "CA", "GB"]
    big = sr.settings_of(_biz(shipping={"countries": ["US"] * 100}))
    assert len(big["countries"]) <= 40


def test_an_empty_country_list_falls_back_rather_than_blocking_everyone():
    # An empty allowed-countries list would refuse every address on
    # earth, which is a worse failure than being US-only was.
    assert sr.settings_of(_biz(shipping={"countries": []}))["countries"] == ["US"]


# ─── Is shipping even a question? ────────────────────────────────────


def test_a_basket_of_digital_goods_has_no_shipping_options():
    cfg = sr.settings_of(_biz(flat_shipping_cents=500))
    assert sr.quote([_item(physical=False)], cfg, subtotal_cents=5000) == []


def test_one_physical_item_makes_it_a_question():
    cfg = sr.settings_of(_biz(flat_shipping_cents=500))
    rates = sr.quote([_item(physical=False), _item()], cfg, subtotal_cents=5000)
    assert [r["amount_cents"] for r in rates] == [500]


# ─── The surcharge ───────────────────────────────────────────────────


def test_the_surcharge_is_per_unit_not_per_line():
    # THE ALARM. Per-line would let somebody order ten barber chairs and
    # pay the postage for one.
    cfg = sr.settings_of(_biz(shipping={"flat_cents": 500}))
    rates = sr.quote([_item(surcharge=4000, qty=3)], cfg, subtotal_cents=90000)
    assert rates[0]["amount_cents"] == 500 + 12000


def test_a_digital_item_never_adds_a_surcharge():
    assert sr.surcharge_cents([_item(physical=False, surcharge=9999)]) == 0


def test_surcharges_survive_junk():
    assert sr.surcharge_cents([{"requires_shipping": True,
                                "ship_surcharge_cents": "x", "quantity": "y"}]) == 0


# ─── Free over a threshold ───────────────────────────────────────────


def test_free_shipping_over_the_threshold_means_free():
    cfg = sr.settings_of(_biz(shipping={"flat_cents": 500, "free_over_cents": 5000}))
    rates = sr.quote([_item()], cfg, subtotal_cents=5000)
    assert rates[0]["amount_cents"] == 0
    assert "Free" in rates[0]["label"]


def test_the_threshold_beats_the_surcharge():
    # THE ALARM. "Free shipping over $50" that still charges $40 for the
    # heavy item is a promise broken at the most expensive possible
    # moment — the last screen before paying.
    cfg = sr.settings_of(_biz(shipping={"flat_cents": 500, "free_over_cents": 5000}))
    rates = sr.quote([_item(surcharge=4000)], cfg, subtotal_cents=9000)
    assert rates[0]["amount_cents"] == 0


def test_just_under_the_threshold_still_pays():
    cfg = sr.settings_of(_biz(shipping={"flat_cents": 500, "free_over_cents": 5000}))
    assert sr.quote([_item()], cfg, subtotal_cents=4999)[0]["amount_cents"] == 500


def test_no_threshold_never_makes_anything_free():
    cfg = sr.settings_of(_biz(shipping={"flat_cents": 500, "free_over_cents": None}))
    assert sr.quote([_item()], cfg, subtotal_cents=999999)[0]["amount_cents"] == 500


# ─── Pickup ──────────────────────────────────────────────────────────


def test_pickup_is_offered_free_and_first():
    cfg = sr.settings_of(_biz(shipping={
        "flat_cents": 500, "pickup": {"enabled": True, "note": "Back counter"}}))
    rates = sr.quote([_item()], cfg, subtotal_cents=1000)
    assert rates[0]["code"] == sr.PICKUP
    assert rates[0]["amount_cents"] == 0
    assert rates[0]["note"] == "Back counter"


def test_pickup_is_absent_unless_switched_on():
    cfg = sr.settings_of(_biz(shipping={"flat_cents": 500}))
    assert all(r["code"] != sr.PICKUP
               for r in sr.quote([_item()], cfg, subtotal_cents=1000))


# ─── Carrier rates, and surviving without them ───────────────────────


def test_carrier_rates_join_the_list_and_sort_by_price():
    cfg = sr.settings_of(_biz(shipping={"flat_cents": 900}))
    rates = sr.quote([_item()], cfg, subtotal_cents=1000, carrier_rates=[
        {"code": "usps_ground", "label": "USPS Ground", "amount_cents": 615},
        {"code": "usps_priority", "label": "USPS Priority", "amount_cents": 940},
    ])
    assert [r["amount_cents"] for r in rates] == [615, 900, 940]


def test_a_carrier_outage_still_leaves_the_customer_a_price():
    # THE ALARM. A checkout must never fail because somebody else's
    # server is slow.
    cfg = sr.settings_of(_biz(shipping={"flat_cents": 500}))
    for outage in (None, []):
        rates = sr.quote([_item()], cfg, subtotal_cents=1000, carrier_rates=outage)
        assert rates and rates[0]["amount_cents"] == 500


def test_one_malformed_carrier_rate_does_not_cost_the_good_ones():
    cfg = sr.settings_of(_biz(shipping={"flat_cents": 500}))
    rates = sr.quote([_item()], cfg, subtotal_cents=1000, carrier_rates=[
        {"label": "no code"},
        {"code": "ok", "label": "Fine", "amount_cents": 300},
        {"code": "bad", "amount_cents": "nonsense"},
    ])
    assert [r["code"] for r in rates] == ["ok", sr.FLAT]


def test_no_weight_means_do_not_ask_a_carrier():
    # A quote for the wrong weight is worse than no quote, because it
    # gets charged.
    assert sr.total_weight_oz([_item(weight=None)]) is None
    assert sr.total_weight_oz([_item(weight=12), _item(weight=None)]) is None
    assert sr.total_weight_oz([_item(weight=12, qty=2)]) == 24.0
    # Digital items weigh nothing and must not veto a carrier quote.
    assert sr.total_weight_oz([_item(weight=10), _item(physical=False)]) == 10.0


# ─── resolve: the price we actually charge ───────────────────────────


def test_the_chosen_code_is_priced_here_not_by_the_client():
    cfg = sr.settings_of(_biz(shipping={"flat_cents": 500,
                                        "pickup": {"enabled": True}}))
    got = sr.resolve([_item()], cfg, subtotal_cents=1000, chosen_code=sr.PICKUP)
    assert got["amount_cents"] == 0 and got["code"] == sr.PICKUP
    got = sr.resolve([_item()], cfg, subtotal_cents=1000, chosen_code=sr.FLAT)
    assert got["amount_cents"] == 500


def test_a_stale_code_falls_back_rather_than_failing_the_sale():
    # The basket may have changed since the page rendered. Dropping
    # somebody at the last step over a stale radio button is a lost
    # sale, not a security win — the PRICE is ours either way, which is
    # the part that actually matters.
    cfg = sr.settings_of(_biz(shipping={"flat_cents": 500}))
    got = sr.resolve([_item()], cfg, subtotal_cents=1000,
                     chosen_code="usps_priority_from_an_old_page")
    assert got["amount_cents"] == 500 and got["code"] == sr.FLAT


def test_nobody_is_silently_defaulted_into_collecting_it_themselves():
    # Pickup sorts first because it is free. It must never become the
    # DEFAULT — somebody who cannot get to the shop would be quietly
    # signed up to.
    cfg = sr.settings_of(_biz(shipping={"flat_cents": 500,
                                        "pickup": {"enabled": True}}))
    got = sr.resolve([_item()], cfg, subtotal_cents=1000, chosen_code=None)
    assert got["code"] == sr.FLAT


def test_a_digital_basket_resolves_to_nothing_to_charge():
    cfg = sr.settings_of(_biz(shipping={"flat_cents": 500}))
    got = sr.resolve([_item(physical=False)], cfg, subtotal_cents=1000,
                     chosen_code=sr.FLAT)
    assert got["amount_cents"] == 0 and got["code"] is None
