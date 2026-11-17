"""The giving block beside a church's weekly briefing (giving_week.py,
GET /giving/{business_id}/week).

Pins:
  * only the people who may see giving get it: the owner, an Admin seat, the
    church's outside accountant. Any other seat and any stranger get a 403
    before a single gift is read
  * the numbers are the Giving page's: paid gifts less refunds, a gift
    refunded in full not counted, an unpaid gift or an ordinary bill never
    counted, the fund as the gift names it
  * a week is seven days on the church's clock, and the week before is the
    seven days before it
  * counts and totals only: never a giver's name or id
  * a failed read is a 503, never zero; nothing is written anywhere
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import giving_router  # noqa: E402
import giving_services  # noqa: E402
import giving_week as gw  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser  # noqa: E402
from test_church_keys import BIZ, ID, PEOPLE, _refused, db  # noqa: E402,F401

ACCOUNTANT = AuthedUser(id="00000000-0000-4000-8000-000000000099", email="books@cpa.example", role="authenticated")
STRANGER = AuthedUser(id="00000000-0000-4000-8000-000000000077", email="who@example.com", role="authenticated")
CHICAGO = ZoneInfo("America/Chicago")
# Sunday 2026-11-15, 2 PM in Chicago. This week: Mon Nov 9 .. Sun Nov 15.
NOW = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)


def _gift(gid, paid_at, total=50.0, **kw):
    return {"id": gid, "business_id": BIZ, "is_gift": True, "status": "paid", "paid_at": paid_at,
            "invoice_number": f"GIVE-{gid}", "total": total, "refund_amount_cents": 0, "gift_fund": "General",
            "category": None, "notes": "", "payment_method": "card", "contact_id": "c1",
            "contacts": {"name": "Marcus Hill", "email": "marcus@example.com"}, **kw}


WEEK = [
    # This week (Nov 9 .. Nov 15 in Chicago).
    _gift("a01", "2026-11-09T06:00:00Z", 100.0),                                     # Mon 00:00 Chicago: the first minute
    _gift("a02", "2026-11-15T16:30:00Z", 250.0, contact_id="c2"),                    # Sunday morning
    _gift("a03", "2026-11-15T16:31:00Z", 40.0, contact_id="c2", gift_fund="Building"),
    _gift("a04", "2026-11-12T18:00:00Z", 120.0, refund_amount_cents=2000,            # part refunded: worth 100
          gift_fund=" building ", contact_id="c3"),
    _gift("a05", "2026-11-13T18:00:00Z", 75.0, contact_id=None, contacts=None,       # cash in the plate, no giver
          invoice_number="GIVE-manual-9c1", payment_method="cash"),
    _gift("a06", "2026-11-14T18:00:00Z", 60.0, refund_amount_cents=6000),            # refunded in full: not a gift
    _gift("a07", "2026-11-14T18:00:00Z", 999.0, status="sent"),                      # not paid
    _gift("a08", "2026-11-14T18:00:00Z", 999.0, is_gift=False, invoice_number="INV-0007"),  # a bill, not a gift
    # The week before (Nov 2 .. Nov 8).
    _gift("a09", "2026-11-09T05:59:00Z", 300.0, contact_id="c4"),                    # Sun Nov 8, 11:59 PM Chicago
    _gift("a10", "2026-11-02T06:00:00Z", 20.0),                                      # Mon Nov 2, 00:00 Chicago
    # Outside both.
    _gift("a11", "2026-11-02T05:59:00Z", 5000.0),                                    # Sun Nov 1, 11:59 PM Chicago
    _gift("a12", "2026-11-16T06:00:00Z", 7000.0),                                    # Mon Nov 16, 00:00 Chicago
]


@pytest.fixture
def church(db, monkeypatch):
    db.t["business_collaborators"] = [{"business_id": BIZ, "user_id": ACCOUNTANT.id, "status": "active",
                                       "role": "accountant", "invited_email": "books@cpa.example"}]
    db.t["invoices"] = [dict(g) for g in WEEK]
    monkeypatch.setattr(gw, "_zone", lambda biz: CHICAGO)
    monkeypatch.setattr(gw, "_now", lambda: NOW)
    return db


def _week(user=None, day=None, biz=BIZ):
    return giving_router.giving_week(biz, day, user=user or PEOPLE["owner"])


# ─── Who gets it ──────────────────────────────────────────────────────

def test_the_owner_an_admin_and_the_accountant_get_it(church):
    want = _week(PEOPLE["owner"])
    assert want["uses_giving"] is True
    for who in (PEOPLE["pastor"], PEOPLE["admin"], PEOPLE["treasurer"], ACCOUNTANT):
        assert _week(who) == want


def test_any_other_login_is_refused_before_a_gift_is_read(church, monkeypatch):
    read = []
    real = sb_clients.sb_get_as_service

    def spy(path, **k):
        read.append(path)
        return real(path, **k)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", spy)
    for who in (PEOPLE["member"], STRANGER):
        read.clear()
        e = _refused(giving_router.giving_week, BIZ, None, user=who)
        assert e.status_code == 403 and "Giving records" in e.detail
        assert not any(p.startswith("/invoices") for p in read), read


def test_an_id_that_is_not_an_id_never_reaches_a_query(church, monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: pytest.fail(f"read {path}"))
    for bad in ("", "nope", f"{BIZ}&select=*", f"{BIZ} or 1=1"):
        assert _refused(giving_router.giving_week, bad, None, user=PEOPLE["owner"]).status_code == 404


# ─── The numbers ──────────────────────────────────────────────────────

def test_this_week_and_the_week_before_on_the_churchs_clock(church):
    got = _week()
    assert got["day"] == "2026-11-15"
    assert got["week"] == {"from": "2026-11-09", "to": "2026-11-15",
                           "total_cents": 10000 + 25000 + 4000 + 10000 + 7500, "gifts": 5,
                           "givers": 3, "no_giver_cents": 7500}
    assert got["before"] == {"from": "2026-11-02", "to": "2026-11-08",
                             "total_cents": 30000 + 2000, "gifts": 2, "givers": 2, "no_giver_cents": 0}


def test_the_week_by_fund_largest_first_and_one_fund_whatever_its_case(church):
    assert _week()["funds"] == [
        {"fund": "General", "total_cents": 10000 + 25000 + 7500, "gifts": 3},
        {"fund": "Building", "total_cents": 4000 + 10000, "gifts": 2},
    ]


def test_never_a_giver(church):
    said = str(_week())
    for word in ("Marcus", "marcus@", "contact", "c1", "c2", "GIVE-", "notes"):
        assert word not in said, word


def test_the_total_is_the_giving_pages_for_the_same_days(church):
    """The gift amounts the Giving page and Home add up (GET /giving/{biz}/amounts),
    netted the way they net them, come to the same week."""
    rows = giving_router.giving_amounts(BIZ, 2026, user=PEOPLE["owner"])["rows"]
    lo, hi = "2026-11-09T06:00:00Z", "2026-11-16T06:00:00Z"
    page_total = sum(giving_services.net_cents(r) for r in rows if lo <= r["paid_at"] < hi)
    assert _week()["week"]["total_cents"] == page_total


def test_an_earlier_letters_week_is_asked_for_by_its_day(church):
    got = _week(day="2026-11-08")
    assert (got["week"]["from"], got["week"]["to"]) == ("2026-11-02", "2026-11-08")
    assert got["week"]["total_cents"] == 32000
    assert (got["before"]["from"], got["before"]["to"]) == ("2026-10-26", "2026-11-01")
    assert got["before"]["total_cents"] == 500000


def test_a_day_that_has_not_come_is_today_and_a_bad_day_is_refused(church):
    assert _week(day="2027-01-01")["day"] == "2026-11-15"
    for bad in ("yesterday", "2026-13-40", "11/15/2026", "1999-01-01"):
        assert _refused(giving_router.giving_week, BIZ, bad, user=PEOPLE["owner"]).status_code == 400


def test_a_church_with_no_gift_ever_gets_no_card_of_zeros(church):
    church.t["invoices"] = [g for g in church.t["invoices"] if not g["is_gift"] or g["status"] != "paid"]
    assert _week() == {"uses_giving": False, "day": "2026-11-15"}


def test_a_quiet_week_in_a_church_that_gives_is_said_as_nothing_given(church):
    church.t["invoices"] = [_gift("b01", "2026-09-06T16:00:00Z", 80.0)]
    got = _week()
    assert got["uses_giving"] is True and got["funds"] == []
    assert got["week"]["total_cents"] == 0 and got["week"]["gifts"] == 0 and got["before"]["gifts"] == 0


# ─── What cannot be read is never zero ────────────────────────────────

def test_a_failed_read_of_the_gifts_is_a_503(church, monkeypatch):
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **k: None if path.startswith("/invoices") else real(path, **k))
    assert _refused(giving_router.giving_week, BIZ, None, user=PEOPLE["owner"]).status_code == 503


def test_a_clock_that_cannot_be_read_is_a_503(church, monkeypatch):
    def no_clock(biz):
        raise HTTPException(503, "The church's clock couldn't be read just now. Try again.")
    monkeypatch.setattr(gw, "_zone", no_clock)
    assert _refused(giving_router.giving_week, BIZ, None, user=PEOPLE["owner"]).status_code == 503


def test_nothing_is_written(church):
    _week()
    _week(PEOPLE["admin"], day="2026-11-08")
    assert church.writes == []


# ─── The small parts ──────────────────────────────────────────────────

def test_a_gifts_worth_and_its_fund():
    assert gw.net_cents({"total": 120.0, "refund_amount_cents": 2000}) == 10000
    assert gw.net_cents({"total": 19.99, "refund_amount_cents": None}) == 1999
    assert gw.net_cents({"total": 10.0, "refund_amount_cents": 5000}) == 0
    assert gw.fund_of({"gift_fund": "  Building   Fund "}) == "Building Fund"
    assert gw.fund_of({"gift_fund": None}) == "General"
    assert gw.fund_of({"gift_fund": "", "category": "Missions"}) == "General"   # the Giving page reads the fund, not the category
