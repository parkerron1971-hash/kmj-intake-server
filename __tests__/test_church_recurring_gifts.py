"""The office's list of recurring gifts (church_recurring_gifts.py, served by
church_pledges' GET /church/giving/recurring). A recurring gift is a Stripe
subscription on the church's own connected account; nothing on our side
stores it, so the list is read from Stripe, server-side.

Pins:
  * only gifts to THIS church (metadata source_type=gift + business_id),
    read on the church's own account
  * each row: giver, amount, how often, fund, next date, state (active /
    paused / ended; late when Stripe's last try failed); a gift that never
    started isn't listed
  * the month's figure: weekly x 52/12, every two weeks x 26/12, monthly x 1,
    active gifts only, by fund
  * a giver with a record here is matched by email, for "Open their record"
  * never card data, whatever Stripe sends
  * a failed Stripe read is a 503, never an empty list; no Stripe, no gifts
"""
from __future__ import annotations

import json
import os
import sys

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_pledges as cp  # noqa: E402
import church_recurring_gifts as crg  # noqa: E402
from test_church_pledges import ADMIN, ANN, BIZ, MEMBER, OTHER, OWNER, db  # noqa: E402,F401

NOV_1 = 1793500000  # a Stripe timestamp (2026-11-01)


def _sub(sid, cents, every=("month", 1), *, fund="Building", status="active", biz=BIZ, email="ann@example.com",
         name="", pause=None, fee=0, **extra):
    items = [{"id": f"si_{sid}", "quantity": 1, "current_period_end": NOV_1,
              "price": {"unit_amount": cents, "currency": "usd", "product": "prod_x",
                        "recurring": {"interval": every[0], "interval_count": every[1]}}}]
    if fee:
        items.append({"id": f"si_fee_{sid}", "quantity": 1,
                      "price": {"unit_amount": fee, "recurring": {"interval": every[0], "interval_count": every[1]}}})
    md = {"source_type": "gift", "business_id": biz, "fund": fund, "frequency": "monthly"}
    if email:
        md["giver_email"] = email
    if name:
        md["giver_name"] = name
    return {"id": f"sub_{sid}", "status": status, "metadata": md, "items": {"data": items},
            "pause_collection": pause, "start_date": NOV_1 - 86400 * 90, "created": NOV_1 - 86400 * 90, **extra}


@pytest.fixture
def stripe(monkeypatch):
    calls = []
    pages = {"subs": []}

    def fake(path, account, params):
        calls.append((path, account, dict(params)))
        if pages.get("fail"):
            return None
        return {"data": pages["subs"], "has_more": False}
    monkeypatch.setattr(crg, "_stripe_get", fake)
    return pages, calls


def test_the_list_reads_this_churchs_own_account_and_only_its_gifts(db, stripe):
    pages, calls = stripe
    pages["subs"] = [
        _sub("a", 10_000),
        _sub("theirs", 99_900, biz=OTHER),
        {**_sub("membership", 5_000), "metadata": {"source_type": "membership", "business_id": BIZ}},
    ]
    out = cp.recurring(BIZ, user=OWNER)
    assert [g["id"] for g in out["gifts"]] == ["sub_a"]
    assert {c[1] for c in calls} == {"acct_lovecity"}
    assert calls[0][2]["status"] == "all"


def test_each_row_says_who_how_much_how_often_the_fund_the_next_date_and_the_state(db, stripe):
    pages, _ = stripe
    pages["subs"] = [
        _sub("weekly", 2_500, ("week", 1), name="Ann Avery"),
        _sub("biweekly", 5_000, ("week", 2), fund="General", email="ben@example.com"),
        _sub("paused", 10_000, pause={"behavior": "void", "resumes_at": NOV_1 + 86400 * 30}, email="cal@example.com"),
        _sub("late", 4_000, status="past_due", email="nobody@example.com", name="Dee Walker"),
        _sub("ended", 7_500, status="canceled", ended_at=NOV_1 - 86400, email=""),
        _sub("never", 1_000, status="incomplete"),
        _sub("fee", 10_000, fee=320, email="ann@example.com"),
    ]
    out = cp.recurring(BIZ, user=ADMIN)
    rows = {g["id"]: g for g in out["gifts"]}
    assert "sub_never" not in rows, "a gift whose first payment never went through isn't one"
    w = rows["sub_weekly"]
    assert (w["giver"], w["amount_cents"], w["every"], w["fund"], w["state"], w["late"]) == \
        ("Ann Avery", 2_500, "weekly", "Building", "active", False)
    assert w["next_at"].startswith("2026-1") and w["contact_id"] == ANN
    assert rows["sub_biweekly"]["every"] == "biweekly" and rows["sub_biweekly"]["giver"] == "Ben Brooks"
    p = rows["sub_paused"]
    assert p["state"] == "paused" and p["next_at"] > w["next_at"], "a paused gift's next date is when it resumes"
    late = rows["sub_late"]
    assert late["state"] == "active" and late["late"] is True and late["contact_id"] is None and late["giver"] == "Dee Walker"
    e = rows["sub_ended"]
    assert e["state"] == "ended" and e["next_at"] is None and e["ended_at"] and e["giver"] == "A giver"
    assert rows["sub_fee"]["amount_cents"] == 10_000 and rows["sub_fee"]["fee_cents"] == 320
    # Active first, then paused, then ended.
    states = [g["state"] for g in out["gifts"]]
    assert states == sorted(states, key=lambda s: {"active": 0, "paused": 1, "ended": 2}[s])


def test_the_month_figure_counts_active_gifts_at_their_monthly_worth(db, stripe):
    pages, _ = stripe
    pages["subs"] = [
        _sub("w", 2_500, ("week", 1)),                       # 2,500 x 52/12 = 10,833
        _sub("b", 5_000, ("week", 2), fund="General"),       # 5,000 x 26/12 = 10,833
        _sub("m", 10_000),                                   # 10,000
        _sub("p", 9_000, pause={"behavior": "void"}),        # paused: not in the month
        _sub("x", 9_000, status="canceled"),                 # ended: not in the month
    ]
    t = cp.recurring(BIZ, user=OWNER)["totals"]
    assert t["monthly_cents"] == 10_833 + 10_833 + 10_000
    assert t["paused_monthly_cents"] == 9_000
    assert (t["active"], t["paused"], t["ended"], t["late"]) == (3, 1, 1, 0)
    assert t["by_fund"] == [{"fund": "Building", "monthly_cents": 20_833, "count": 2},
                            {"fund": "General", "monthly_cents": 10_833, "count": 1}]


def test_the_list_never_carries_card_data(db, stripe):
    pages, _ = stripe
    card = {"id": "pm_1Card", "object": "payment_method", "type": "card",
            "card": {"brand": "visa", "last4": "4242", "exp_month": 12, "exp_year": 2030, "fingerprint": "fp_secret"},
            "billing_details": {"address": {"line1": "1 Main St"}}}
    sub = _sub("a", 10_000, default_payment_method=card, default_source="card_1Legacy",
               latest_invoice={"id": "in_1", "payment_intent": {"client_secret": "pi_secret_123"}})
    sub["customer"] = {"id": "cus_1", "email": "ann@example.com", "name": "Ann Avery",
                       "invoice_settings": {"default_payment_method": card}, "sources": {"data": [card]},
                       "address": {"line1": "1 Main St"}, "phone": "+15555550100"}
    pages["subs"] = [sub]
    out = cp.recurring(BIZ, user=OWNER)
    dumped = json.dumps(out)
    for secret in ("4242", "visa", "last4", "pm_1Card", "card_1Legacy", "fp_secret", "exp_", "pi_secret",
                   "Main St", "5555550100", "cus_1", "payment_method", "brand"):
        assert secret not in dumped, secret
    assert set(out["gifts"][0]) == {"id", "giver", "email", "contact_id", "amount_cents", "fee_cents", "every",
                                    "fund", "state", "late", "next_at", "started_at", "ended_at", "monthly_cents"}


def test_the_givers_name_comes_from_stripes_customer_when_the_gift_has_none(db, stripe):
    pages, _ = stripe
    sub = _sub("a", 10_000, email="", name="")
    sub["customer"] = {"id": "cus_9", "email": "Walk.In@Example.com", "name": "Walk In"}
    pages["subs"] = [sub]
    g = cp.recurring(BIZ, user=OWNER)["gifts"][0]
    assert (g["giver"], g["email"]) == ("Walk In", "walk.in@example.com")


def test_a_failed_stripe_read_is_an_error_never_an_empty_list_and_no_stripe_means_none(db, stripe):
    pages, _ = stripe
    pages["fail"] = True
    assert pytest.raises(HTTPException, cp.recurring, BIZ, user=OWNER).value.status_code == 503
    db.t["businesses"][0]["stripe_account_id"] = None
    crg._cache.clear()
    out = cp.recurring(BIZ, user=OWNER)
    assert out["connected"] is False and out["gifts"] == []


def test_the_list_is_kept_two_minutes_and_fresh_never_hammers_stripe(db, stripe):
    pages, calls = stripe
    pages["subs"] = [_sub("a", 10_000)]
    cp.recurring(BIZ, user=OWNER)
    cp.recurring(BIZ, user=OWNER)
    assert len(calls) == 1
    # Refresh pressed again and again: one read per FRESH_FLOOR seconds.
    for _ in range(5):
        cp.recurring(BIZ, fresh=True, user=OWNER)
    assert len(calls) == 1
    at, account, payload = crg._cache[BIZ]
    crg._cache[BIZ] = (at - crg.FRESH_FLOOR - 1, account, payload)
    cp.recurring(BIZ, fresh=True, user=OWNER)
    assert len(calls) == 2


def test_a_member_never_reaches_stripe(db, stripe):
    _, calls = stripe
    assert pytest.raises(HTTPException, cp.recurring, BIZ, user=MEMBER).value.status_code == 403
    assert calls == []


def test_pages_are_followed_and_a_cut_list_says_so(monkeypatch):
    seen = []

    def fake(path, account, params):
        seen.append(params.get("starting_after"))
        return {"data": [{"id": f"sub_{len(seen)}"}], "has_more": True}
    monkeypatch.setattr(crg, "_stripe_get", fake)
    subs, cut = crg.read_subscriptions("acct_x")
    assert len(subs) == crg.MAX_PAGES and cut is True
    assert seen[:3] == [None, "sub_1", "sub_2"]
