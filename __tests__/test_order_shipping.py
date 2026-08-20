"""Marking an order shipped, and telling the customer where it is.

The contract under test:
  • /ship is SEPARATE from /fulfill. "Fulfilled" has meant "the
    practitioner dealt with it" since Arc 27 and covers a pickup, a
    hand-off, a download. Shipping is a narrower claim with a date and
    a number, so it gets its own stamp instead of quietly redefining
    what every past fulfilled order meant;
  • a tracking number goes into a URL, so anything that is not a plain
    alphanumeric code is not a tracking number;
  • an unknown carrier gets NO link — the number is still in the email,
    and a wrong link is worse than none;
  • marked shipped with no number says so, rather than leaving a gap
    where a tracking number should be.
"""
from __future__ import annotations

import receipts


ITEMS = [{"name_at_purchase": "Pomade", "quantity": 2}]


# ─── Tracking links ──────────────────────────────────────────────────


def test_each_carrier_gets_its_real_tracking_url():
    n = "9400111899223197428490"
    assert receipts.tracking_url("usps", n).startswith("https://tools.usps.com/")
    assert receipts.tracking_url("ups", n).startswith("https://www.ups.com/")
    assert receipts.tracking_url("fedex", n).startswith("https://www.fedex.com/")
    assert receipts.tracking_url("dhl", n).startswith("https://www.dhl.com/")
    assert n in receipts.tracking_url("usps", n)


def test_an_unknown_carrier_gets_no_link():
    # A wrong tracking link is worse than none: it sends somebody to a
    # page that says their parcel does not exist.
    assert receipts.tracking_url("other", "123456789") is None
    assert receipts.tracking_url(None, "123456789") is None
    assert receipts.tracking_url("", "123456789") is None


def test_a_tracking_number_that_is_not_one_never_reaches_a_url():
    # THE ALARM. This value is interpolated into a link that gets
    # emailed. Anything with punctuation, spaces or markup is not a
    # tracking number.
    for junk in ("", "   ", "no; drop table", "1234", "a" * 41,
                 "<script>alert(1)</script>", "9400 1118 9922",
                 "../../etc/passwd", "abc?x=1&y=2"):
        assert receipts.tracking_url("usps", junk) is None, junk


def test_a_real_looking_number_is_accepted():
    assert receipts.tracking_url("ups", "1Z999AA10123456784") is not None
    assert receipts.tracking_url("usps", "abc123") is not None      # 6 chars


def test_carrier_labels_are_human():
    assert receipts.carrier_label("usps") == "USPS"
    assert receipts.carrier_label("fedex") == "FedEx"
    assert receipts.carrier_label("other") == "the carrier"
    assert receipts.carrier_label(None) == "the carrier"


# ─── The email ───────────────────────────────────────────────────────


def test_the_shipped_email_leads_with_the_new_fact():
    out = receipts.render_shipped(
        {"tracking_carrier": "usps", "tracking_number": "9400111899223197428490"},
        ITEMS, business_name="Studio One")
    assert out["subject"] == "Your order from Studio One is on its way"
    assert "has shipped" in out["body"]
    assert "USPS tracking: 9400111899223197428490" in out["body"]
    assert "https://tools.usps.com/" in out["body"]
    assert "2 × Pomade" in out["body"]


def test_it_does_not_repeat_the_receipt():
    # The receipt already said what it cost. Repeating it buries the one
    # new fact, which is the tracking number.
    out = receipts.render_shipped(
        {"tracking_carrier": "usps", "tracking_number": "abc123"},
        ITEMS, business_name="X")
    assert "Total" not in out["body"]
    assert "$" not in out["body"]


def test_no_tracking_number_says_so_rather_than_leaving_a_hole():
    out = receipts.render_shipped({"tracking_carrier": None, "tracking_number": ""},
                                  ITEMS, business_name="X")
    assert "no tracking number" in out["body"].lower()
    assert "tracking:" not in out["body"].lower()


def test_a_number_without_a_recognised_carrier_still_shows_the_number():
    out = receipts.render_shipped(
        {"tracking_carrier": "other", "tracking_number": "XY123456"},
        ITEMS, business_name="X")
    assert "XY123456" in out["body"]
    assert "http" not in out["body"]


def test_an_empty_order_still_renders():
    out = receipts.render_shipped({}, [], business_name="")
    assert out["subject"] and out["body"]


# ─── The endpoint ────────────────────────────────────────────────────


def test_ship_is_its_own_endpoint_not_a_fulfil_flag():
    import store_router
    paths = {}
    for r in store_router.router.routes:
        paths.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "POST" in paths.get("/store/orders/{order_id}/ship", set())
    # /fulfill stays exactly as it was — a pickup or a download is
    # fulfilled without ever being shipped.
    assert "POST" in paths.get("/store/orders/{order_id}/fulfill", set())


def test_shipping_stamps_its_own_date_and_does_not_redefine_fulfilled():
    import inspect
    import store_router
    src = inspect.getsource(store_router.ship_order)
    assert '"shipped_at": now' in src
    assert '"status": "fulfilled"' in src
    # An unpaid order cannot be shipped.
    assert '("paid", "fulfilled")' in src
    # A mail failure must never make a shipped order look unshipped.
    assert "non-fatal" in src


def test_only_known_carriers_are_accepted_at_the_wire():
    import inspect
    import store_router
    src = inspect.getsource(store_router.ship_order)
    assert "receipts.CARRIERS" in src
    assert receipts.CARRIERS == ["usps", "ups", "fedex", "dhl", "other"]
