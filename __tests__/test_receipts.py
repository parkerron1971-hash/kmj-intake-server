# __tests__/test_receipts.py
#
# What a customer actually receives.
#
# The reason this is a pure module with its own tests: wording is the
# part of a system nobody reviews, because reviewing it means finding a
# real order and reading the inbox it went to. Now it can be read here.
#
# The load-bearing test is test_the_store_receipt_is_unchanged. This
# refactor touched an email that already goes to real customers, and the
# only acceptable outcome for THAT path is that nothing moved.

import re

import receipts


ITEMS = [{"name_at_purchase": "Pomade", "unit_amount_cents": 2500, "quantity": 2}]

STORE = {"id": "abc12345-9999", "total_cents": 5500, "tax_cents": 500,
         "shipping_cents": 0, "subtotal_cents": 5000, "currency": "usd"}

COUNTER = {"id": "abc12345-9999", "source": "counter", "payment_method": "cash",
           "total_cents": 4400, "tax_cents": 400, "shipping_cents": 0,
           "subtotal_cents": 4000, "currency": "usd"}


# ─── The receipt that already goes to real customers ─────────────────


def test_the_store_receipt_is_unchanged():
    # Pinned against the exact text the old renderer produced. If this
    # ever fails, somebody changed an email that customers already
    # receive — which may be fine, but never by accident.
    out = receipts.render(STORE, ITEMS, business_name="Studio One",
                          notes=["Pomade: ships in 3 days"], downloads=[])
    assert out["subject"] == "Receipt — order ABC12345"
    assert out["body"] == (
        "Thank you for your order from Studio One!\n"
        "\n"
        "  2 × Pomade — $50.00\n"
        "  Sales tax — $5.00\n"
        "\n"
        "Total — $55.00\n"
        "\n"
        "Pomade: ships in 3 days\n"
        "\n"
        "Questions? Just reply to this email.\n"
        "— Studio One")


def test_an_order_with_no_source_is_still_a_store_order():
    # Every order written before today has no `source` at all.
    assert receipts.is_counter({}) is False
    assert receipts.is_counter({"source": "store"}) is False
    assert receipts.is_counter({"source": "counter"}) is True


# ─── The counter receipt ─────────────────────────────────────────────


def test_a_counter_receipt_does_not_thank_them_for_an_order():
    out = receipts.render(COUNTER, ITEMS, business_name="Studio One")
    assert out["subject"] == "Receipt from Studio One"
    assert "Thanks for stopping by Studio One!" in out["body"]
    assert "your order" not in out["body"]


def test_a_counter_receipt_says_how_they_paid():
    for method, label in (("cash", "Paid in cash"), ("card", "Paid by card"),
                          ("other", "Paid")):
        out = receipts.render({**COUNTER, "payment_method": method}, ITEMS,
                              business_name="X")
        assert label in out["body"]


def test_an_unknown_payment_method_still_says_paid():
    out = receipts.render({**COUNTER, "payment_method": "wampum"}, ITEMS,
                          business_name="X")
    assert "Paid" in out["body"]


def test_a_counter_receipt_drops_shipping_notes_but_keeps_downloads():
    # They walked out with it, so "ships in 3 days" is nonsense. A
    # digital item still has to reach them somehow, so its link stays.
    out = receipts.render(COUNTER, ITEMS, business_name="X",
                          notes=["Pomade: ships in 3 days"],
                          downloads=["  Guide — https://x/y"])
    assert "ships in 3 days" not in out["body"]
    assert "https://x/y" in out["body"]


# ─── The discount, which is why this needed doing at all ─────────────


def test_a_discount_appears_so_the_receipt_adds_up():
    out = receipts.render(COUNTER, ITEMS, business_name="X")
    assert "Discount — -$10.00" in out["body"]


def test_the_arithmetic_on_the_page_actually_works():
    # What a customer does with a receipt: add it up. Items minus the
    # discount plus tax has to equal the total, or they stop trusting
    # the shop.
    out = receipts.render(COUNTER, ITEMS, business_name="X")
    body = out["body"]
    line = float(re.search(r"× Pomade — \$([\d,.]+)", body).group(1).replace(",", ""))
    disc = float(re.search(r"Discount — -\$([\d,.]+)", body).group(1).replace(",", ""))
    tax = float(re.search(r"Sales tax — \$([\d,.]+)", body).group(1).replace(",", ""))
    total = float(re.search(r"Total — \$([\d,.]+)", body).group(1).replace(",", ""))
    assert round(line - disc + tax, 2) == total


def test_no_discount_line_when_nothing_came_off():
    out = receipts.render(STORE, ITEMS, business_name="X")
    assert "Discount" not in out["body"]


def test_the_discount_is_derived_and_never_negative():
    assert receipts.discount_cents({"subtotal_cents": 4000}, ITEMS) == 1000
    assert receipts.discount_cents({"subtotal_cents": 5000}, ITEMS) == 0
    # Shipping and tax sit outside the subtotal, so gross < subtotal is
    # malformed — report nothing rather than a negative "discount".
    assert receipts.discount_cents({"subtotal_cents": 9999}, ITEMS) == 0
    assert receipts.discount_cents({}, ITEMS) == 0
    assert receipts.discount_cents({"subtotal_cents": "junk"}, ITEMS) == 0


# ─── Money ───────────────────────────────────────────────────────────


def test_usd_formatting_is_byte_identical_to_the_old_hardcoded_dollar():
    # The refactor is only safe because of this.
    for cents in (0, 5, 999, 5500, 123456789):
        assert receipts.money(cents, "usd") == f"${cents / 100:,.2f}"


def test_other_currencies_stop_being_called_dollars():
    assert receipts.money(5500, "gbp") == "£55.00"
    assert receipts.money(5500, "eur") == "€55.00"


def test_an_unknown_currency_gets_its_code_not_a_wrong_symbol():
    assert receipts.money(5500, "sek") == "55.00 SEK"


def test_money_survives_junk():
    assert receipts.money(None) == "$0.00"
    assert receipts.money("nonsense") == "$0.00"
    assert receipts.money(100, None) == "$1.00"


def test_a_junk_line_item_does_not_break_the_receipt():
    weird = [{"name_at_purchase": "X", "unit_amount_cents": None, "quantity": "two"}]
    out = receipts.render(COUNTER, weird, business_name="X")
    assert "$0.00" in out["body"]


def test_a_nameless_business_still_produces_a_receipt():
    out = receipts.render(COUNTER, ITEMS, business_name="")
    assert out["subject"] == "Receipt from your purchase"
    assert "Thanks for stopping by!" in out["body"]


# ─── The send decision ───────────────────────────────────────────────


def test_the_till_only_claims_a_receipt_when_there_was_an_address():
    import inspect
    import counter_sale
    src = inspect.getsource(counter_sale.counter_sale)
    assert 'if (body.customer_email or "").strip():' in src
    assert '"receipt_emailed": emailed' in src
    # The sale is already recorded by this point — a mail failure must
    # never be allowed to undo it.
    assert "non-fatal" in src
