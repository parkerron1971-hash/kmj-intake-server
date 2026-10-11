"""Booking money reaches the books.

Before this, money a client paid online for an appointment (service,
deposit, tip) and a charged no-show fee were written onto the booking and
nowhere else. Worse, the payout that later landed in the bank cleared
Stripe Clearing against nothing, so that income appeared on no report at
all. Store and counter sales had a smaller version of the same gap: they
posted to the ledger but the default (cash) P&L never read them, and a
cash counter sale was posted as if Stripe held it.

Pinned here:
  1. desired_for_booking posts payment / refund / no-show fee / fee refund,
     balanced, from what Stripe actually charged.
  2. Every P&L (ledger cash, ledger accrual, source-table H.3a) shows
     bookings, tips and store sales, and the ledger and H.3a agree.
  3. The ledger reads orders.payment_method, so a cash counter sale is cash.
  4. The live-sync wiring and its SQL trigger stay in step with the generator.
  5. The webhook records the charged amount, and a refunded no-show fee is
     not booked as a refund of the service.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import date
from unittest import mock

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import gl_engine as gl  # noqa: E402
import gl_reports  # noqa: E402
import reports_engine as re_  # noqa: E402
import test_i1_gl as base  # noqa: E402  (the synthetic KMJ-like dataset + PostgREST fake)


def _booking(bid="bk1", *, paid_at="2026-06-10T15:00:00Z", pi="pi_1", **data):
    return {"id": bid, "paid_at": paid_at, "stripe_payment_intent_id": pi,
            "data": {"service_name_at_booking": "Fade", **data}}


def _by_type(specs):
    return {s["source_type"]: s for s in specs}


def _amounts(spec):
    return sorted((l["code"], l["debit"], l["credit"]) for l in spec["lines"])


def _balanced(specs):
    for s in specs:
        assert round(sum(l["debit"] for l in s["lines"]), 2) == \
               round(sum(l["credit"] for l in s["lines"]), 2), s["source_type"]


# ─── 1. the generator ─────────────────────────────────────────────────

def test_full_payment_with_tip_splits_service_and_tip():
    specs = gl.desired_for_booking(_booking(price_at_booking=40.0, tip_cents=800,
                                            amount_charged_cents=4800))
    _balanced(specs)
    pay = _by_type(specs)["booking_payment"]
    assert _amounts(pay) == [("1150", 48.0, 0.0), ("4000", 0.0, 40.0), ("4300", 0.0, 8.0)]
    assert pay["entry_date"] == "2026-06-10"


def test_what_stripe_charged_wins_over_the_list_price():
    # A Stripe-side promotion code: $40 booked, $32 charged.
    pay = _by_type(gl.desired_for_booking(
        _booking(price_at_booking=40.0, amount_charged_cents=3200)))["booking_payment"]
    assert _amounts(pay) == [("1150", 32.0, 0.0), ("4000", 0.0, 32.0)]


def test_deposit_posts_only_what_was_taken_online():
    pay = _by_type(gl.desired_for_booking(
        _booking(price_at_booking=60.0, deposit_paid_cents=1500, tip_cents=500)))["booking_payment"]
    assert _amounts(pay) == [("1150", 20.0, 0.0), ("4000", 0.0, 15.0), ("4300", 0.0, 5.0)]


def test_money_taken_in_person_is_not_stripe_money():
    assert gl.desired_for_booking(_booking(pi=None, price_at_booking=40.0)) == []
    assert gl.desired_for_booking(_booking(paid_at=None, price_at_booking=40.0)) == []


def test_partial_refund_comes_off_the_service_first():
    specs = gl.desired_for_booking(_booking(
        price_at_booking=40.0, tip_cents=800, amount_charged_cents=4800,
        refunded_amount_cents=2000, refunded_at="2026-06-12T09:00:00Z"))
    _balanced(specs)
    ref = _by_type(specs)["booking_refund"]
    assert _amounts(ref) == [("1150", 0.0, 20.0), ("4000", 20.0, 0.0)]
    assert ref["entry_date"] == "2026-06-12"


def test_full_refund_takes_back_the_tip_too():
    ref = _by_type(gl.desired_for_booking(_booking(
        price_at_booking=40.0, tip_cents=800, amount_charged_cents=4800,
        refunded_amount_cents=4800)))["booking_refund"]
    assert _amounts(ref) == [("1150", 0.0, 48.0), ("4000", 40.0, 0.0), ("4300", 8.0, 0.0)]


def test_no_show_fee_and_its_refund():
    specs = gl.desired_for_booking(_booking(
        pi=None, paid_at=None, price_at_booking=40.0,
        no_show_fee_charged_at="2026-06-11T18:00:00Z", no_show_fee_charged_cents=2500,
        no_show_fee_refunded_cents=2500, no_show_fee_refunded_at="2026-06-13T10:00:00Z"))
    _balanced(specs)
    st = _by_type(specs)
    assert set(st) == {"booking_no_show_fee", "booking_no_show_fee_refund"}
    assert _amounts(st["booking_no_show_fee"]) == [("1150", 25.0, 0.0), ("4900", 0.0, 25.0)]
    assert _amounts(st["booking_no_show_fee_refund"]) == [("1150", 0.0, 25.0), ("4900", 25.0, 0.0)]


# ─── 2. every P&L shows them, and the two engines agree ──────────────

BOOKINGS = [
    _booking("bk_full", price_at_booking=40.0, tip_cents=800, amount_charged_cents=4800),
    _booking("bk_dep", paid_at="2026-06-11T15:00:00Z", pi="pi_2",
             price_at_booking=60.0, deposit_paid_cents=1500),
    _booking("bk_ref", paid_at="2026-06-12T15:00:00Z", pi="pi_3", price_at_booking=30.0,
             amount_charged_cents=3000, refunded_amount_cents=1000,
             refunded_at="2026-06-14T00:00:00Z"),
    _booking("bk_noshow", paid_at=None, pi=None, price_at_booking=40.0,
             no_show_fee_charged_at="2026-06-13T18:00:00Z", no_show_fee_charged_cents=2500),
]
ORDERS = [
    {"id": "ord_store", "status": "paid", "subtotal_cents": 2000, "tax_cents": 160,
     "shipping_cents": 500, "total_cents": 2660, "paid_at": "2026-06-09T00:00:00Z",
     "refund_amount_cents": None, "refunded_at": None, "payment_method": None},
    {"id": "ord_counter", "status": "paid", "subtotal_cents": 1500, "tax_cents": 0,
     "shipping_cents": 0, "total_cents": 1500, "paid_at": "2026-06-10T00:00:00Z",
     "refund_amount_cents": None, "refunded_at": None, "payment_method": "cash"},
]
SERVICE = 40 + 15 + 30 - 10          # 75: full, deposit, refunded booking net
TIPS = 8
NO_SHOW = 25
STORE = (20 + 5) + 15                # goods + shipping charged + counter sale (tax is a liability)
SEEN_PATHS: list = []


def _route(path):
    SEEN_PATHS.append(path)
    if path.startswith("/module_entries"):
        return base._apply(BOOKINGS, path)
    if path.startswith("/orders"):
        return base._apply(ORDERS, path)
    return base._route(path)


@pytest.fixture
def books(monkeypatch):
    import sb_clients
    SEEN_PATHS.clear()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _route)


def _lines():
    return gl._lines_from_specs(gl.generate_entries(gl._fetch_sources("biz1")))


def test_books_balance_with_bookings_and_sales(books):
    specs = gl.generate_entries(gl._fetch_sources("biz1"))
    _balanced(specs)
    assert gl.trial_balance(gl._lines_from_specs(specs))["difference"] == 0.0


def test_cash_pnl_lists_bookings_tips_and_store_sales(books):
    pl = gl_reports._pl_window(_lines(), date(2026, 6, 1), date(2026, 6, 30))
    rev = pl["revenue"]
    assert rev["bookings"] == SERVICE + NO_SHOW
    assert rev["tips"] == TIPS
    assert rev["store_sales"] == STORE
    assert rev["gross_revenue"] == round(rev["invoiced"] - rev["refunds"] + rev["plaid_other_income"]
                                         + rev["bookings"] + rev["tips"] + rev["store_sales"], 2)


def test_accrual_pnl_names_them_instead_of_calling_them_other_income(books):
    pl = gl_reports._pl_window_accrual(_lines(), date(2026, 6, 1), date(2026, 6, 30))
    rev = pl["revenue"]
    assert (rev["bookings"], rev["tips"], rev["store_sales"]) == (SERVICE + NO_SHOW, TIPS, STORE)


def test_ledger_and_source_pnl_agree_with_bookings_present(books):
    lines = _lines()
    start, end = date(2000, 1, 1), base.TODAY
    gl_pl = gl.gl_pl_cash_basis(lines, start, end)
    h_pl = re_.profit_and_loss("biz1", "custom", None, start.isoformat(), end.isoformat())["current"]
    assert gl_pl["revenue"] == h_pl["revenue"]["gross_revenue"]
    assert h_pl["revenue"]["bookings"] == SERVICE + NO_SHOW
    assert h_pl["revenue"]["tips"] == TIPS
    assert h_pl["revenue"]["store_sales"] == STORE
    assert gl_pl["net_income"] == h_pl["net_income"]


# ─── 3. a cash counter sale is cash ───────────────────────────────────

def test_cash_counter_sale_lands_in_cash_not_stripe_clearing(books):
    specs = _by_type([s for s in gl.generate_entries(gl._fetch_sources("biz1"))
                      if s["source_id"] == "ord_counter"])
    debit_codes = {l["code"] for l in specs["order_payment"]["lines"] if l["debit"]}
    assert debit_codes == {"1000"}
    assert any(p.startswith("/orders") and "payment_method" in p for p in SEEN_PATHS)
    assert "payment_method" in gl._SOURCE_FETCH["orders"]


# ─── 4. live sync + trigger stay in step with the generator ──────────

def test_module_entries_is_a_live_sync_source():
    assert gl._TABLE_SOURCE_TYPES["module_entries"] == gl.BOOKING_SOURCE_TYPES
    assert gl._TABLE_DESIRED["module_entries"] is gl.desired_for_booking
    assert "/module_entries?id=eq.{id}" in gl._SOURCE_FETCH["module_entries"]


def test_trigger_watches_every_amount_the_generator_reads():
    sql = (_here.parent / "supabase" / "APPLY-2026-10-04-booking-money-gl.sql").read_text(encoding="utf-8")
    for key in ("amount_charged_cents", "tip_cents", "deposit_paid_cents", "amount_paid_cents",
                "price_at_booking", "refunded_amount_cents", "no_show_fee_charged_at",
                "no_show_fee_charged_cents", "no_show_fee_refunded_cents"):
        assert f"'{key}'" in sql, key
    for col in ("paid_at", "stripe_payment_intent_id"):
        assert f"OLD.{col} IS DISTINCT FROM NEW.{col}" in sql


def test_tips_account_is_in_every_chart():
    assert "4300" in {c[0] for c in gl._coa_for("personal_services")}
    assert "4300" in gl._INCOME_CODES


# ─── 5. the webhook side ──────────────────────────────────────────────

def _webhook(fn, entry, *args, **kwargs):
    import stripe_connect_router as scr
    import event_spine
    patched = []
    with mock.patch.object(scr.sb_clients, "sb_get_as_service",
                           lambda path: [entry] if path.startswith("/module_entries") else []), \
         mock.patch.object(scr.sb_clients, "sb_patch_as_service",
                           lambda path, payload: patched.append(payload)), \
         mock.patch.object(event_spine, "emit", lambda *a, **k: True):
        getattr(scr, fn)(*args, **kwargs)
    return [p["data"] for p in patched if "data" in p]


def test_paid_webhook_records_what_stripe_charged():
    entry = {"id": "bk-1", "paid_at": None, "business_id": "biz-1", "contact_id": None,
             "data": {"price_at_booking": 40.0}}
    data = _webhook("_mark_booking_paid", entry, "bk-1", payment_intent_id="pi_1",
                    charge_id=None, metadata={"tip_cents": "800"}, amount_charged_cents=4800)
    assert data and data[0]["amount_charged_cents"] == 4800


# module_entries' columns (live schema, 2026-10-11). A booking keeps its
# contact in data; there is no contact_id column.
MODULE_ENTRIES_COLUMNS = {
    "id", "module_id", "business_id", "data", "status", "created_by", "created_at", "updated_at", "source",
    "source_form_id", "paid_at", "stripe_charge_id", "stripe_payment_intent_id", "appointment_at",
    "duration_min_at_booking",
}


def test_paid_webhook_reads_only_columns_that_exist():
    """The read named a contact_id column that module_entries doesn't have,
    so PostgREST answered 400, the read came back empty, and every paid
    booking returned before paid_at, the deposit, the tip or the card on
    file was recorded (found 2026-10-11: no booking had ever been marked paid)."""
    import stripe_connect_router as scr
    import event_spine
    paths = []

    def read(path):
        paths.append(path)
        return [{"id": "bk-1", "paid_at": None, "business_id": "biz-1", "contact_id": "c-1",
                 "data": {"price_at_booking": 40.0, "contact_id": "c-1"}}]

    emitted = []
    with mock.patch.object(scr.sb_clients, "sb_get_as_service", read), \
         mock.patch.object(scr.sb_clients, "sb_patch_as_service", lambda path, payload: [payload]), \
         mock.patch.object(event_spine, "emit", lambda *a, **k: emitted.append(k)):
        scr._mark_booking_paid("bk-1", payment_intent_id="pi_1", charge_id=None, metadata={},
                               amount_charged_cents=4000)
    select = paths[0].split("select=")[1].split("&")[0]
    for field in select.split(","):
        source = field.split(":", 1)[-1]
        column = source.split("->", 1)[0]
        assert column in MODULE_ENTRIES_COLUMNS, f"module_entries has no column {column!r} ({field})"
    assert "contact_id:data->>contact_id" in select
    assert emitted and emitted[0]["contact_id"] == "c-1"


def test_first_recorded_charge_amount_is_kept():
    entry = {"id": "bk-1", "paid_at": "2026-06-10T00:00:00Z", "business_id": "biz-1",
             "contact_id": None, "data": {"price_at_booking": 40.0, "amount_charged_cents": 4800}}
    data = _webhook("_mark_booking_paid", entry, "bk-1", payment_intent_id="pi_1",
                    charge_id=None, metadata={}, amount_charged_cents=9999)
    assert all(d.get("amount_charged_cents") in (None, 4800) for d in data)


def test_refunded_no_show_fee_is_not_a_service_refund():
    entry = {"id": "bk-1", "business_id": "biz-1",
             "data": {"price_at_booking": 40.0, "no_show_fee_charged_cents": 2500}}
    data = _webhook("_handle_charge_refunded", entry, {
        "amount_refunded": 2500, "refunded": True,
        "metadata": {"source_type": "booking", "source_id": "bk-1", "payment_kind": "no_show_fee"}})
    assert data[0]["no_show_fee_refunded_cents"] == 2500
    assert data[0]["no_show_fee_refunded_at"]
    assert "refunded_amount_cents" not in data[0]


def test_service_refund_is_dated():
    entry = {"id": "bk-1", "business_id": "biz-1", "data": {"price_at_booking": 40.0}}
    data = _webhook("_handle_charge_refunded", entry, {
        "amount_refunded": 1000, "refunded": False,
        "metadata": {"source_type": "booking", "source_id": "bk-1"}})
    assert data[0]["refunded_amount_cents"] == 1000
    assert data[0]["refunded_at"]
