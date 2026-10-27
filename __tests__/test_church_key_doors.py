"""Church Areas, step 2, part 1b: the Giving doors (church_keys.wall at each
route that shows who gave what, the bank or the payouts). Kevin 2026-10-23:
"if Pastor look at money another leader is notified and have to recieve a
code from that person to get into money"; his picks 2026-10-26: the lock
binds the owner too, a yes opens an hour.

Pins:
  * once the church names a Giving keeper, the gift records, the mailed
    statements, Chief's statements, the donor report, giver statements, the
    bank reconciliation, the Stripe pages and the bank pages refuse everyone
    else with 403 area_locked, the owner and the admins too; nothing is
    written or sent first
  * the keeper gets in; so does anyone holding an open key, until it ends
  * revenue and profitability keep their totals and leave out the givers
  * a church with no keeper, and any other business, is not locked
  * a failed read of the keepers is a 503, never an open door
  * the church's outside accountant (no seat) is locked too, asks for
    Giving's key like anyone, is named to the keepers, and never answers one
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_keys as ck  # noqa: E402
import giving_router  # noqa: E402
import giving_statement_mail  # noqa: E402
import plaid_router  # noqa: E402
import reports_router  # noqa: E402
import sb_clients  # noqa: E402
import stripe_data_proxy  # noqa: E402
from auth_supabase import AuthedUser  # noqa: E402
from test_church_keys import BIZ, ID, PEOPLE, _later, _refused, db  # noqa: E402,F401

ACCOUNTANT = AuthedUser(id="00000000-0000-4000-8000-000000000099", email="books@cpa.example", role="authenticated")
SHOP = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def church(db, monkeypatch):
    db.t["businesses"][0]["stripe_account_id"] = "acct_love"
    db.t["businesses"].append({"id": SHOP, "name": "Fade Shop", "type": "barber", "owner_id": ID["owner"],
                               "stripe_account_id": "acct_fade"})
    db.t["business_collaborators"] = [{"business_id": BIZ, "user_id": ACCOUNTANT.id, "status": "active",
                                       "role": "accountant", "invited_email": "books@cpa.example"}]
    db.t["invoices"] = []
    import billing_limits
    monkeypatch.setattr(billing_limits, "require_feature", lambda *a, **k: None)
    monkeypatch.setattr(reports_router, "_fiscal_period", lambda row, period, f, t: (period, f, t))
    ck.put_keeper(BIZ, PEOPLE["admin"], "giving_money", ID["treasurer"], True)
    # Who each alert's email reaches, as _tell would address it.
    db.emailed = []

    def tell(biz, to, title, body, seats, tag):
        db.told.append((sorted(to), title, body))
        db.emailed.append(sorted(ck._email_of(uid, biz.get("owner_id"), seats) for uid in to))
    monkeypatch.setattr(ck, "_tell", tell)
    return db


def _locked(fn, *args, **kw):
    e = _refused(fn, *args, **kw)
    assert e.status_code == 403 and e.detail["code"] == "area_locked" and e.detail["area"] == "giving_money", e.detail
    return e


def _key(db, who="pastor"):
    asked = ck.ask(BIZ, PEOPLE[who] if who in PEOPLE else ACCOUNTANT, "giving_money", "Year-end statements")
    ck.answer(BIZ, PEOPLE["treasurer"], asked["key"]["id"], True)


GIFT = {"request_id": "00000000-0000-4000-8000-0000000000aa", "amount_cents": 5000,
        "received_on": "2026-10-25", "method": "cash"}


def _doors():
    """Each Giving door, called the way its route calls it."""
    async def mail_send(user):
        return await giving_statement_mail.statements_mail_send(BIZ, 2025, {"confirm": True}, user=user)

    async def statement_send(user):
        return await reports_router.customer_statement_send(BIZ, "c1", user=user)
    return {
        "gift records": lambda u: giving_router.giving_records(BIZ, 2026, user=u),
        "record a gift": lambda u: giving_router.create_manual_gift(BIZ, dict(GIFT), user=u),
        "correct a gift": lambda u: giving_router.correct_manual_gift(BIZ, "00000000-0000-4000-8000-0000000000ab",
                                                                      {"reason": "typo"}, user=u),
        "statements mail plan": lambda u: giving_statement_mail.statements_mail_plan(BIZ, 2025, user=u),
        "statements mail send": lambda u: asyncio.run(mail_send(u)),
        "donor report": lambda u: reports_router.donors(BIZ, user=u),
        "donor export": lambda u: reports_router.export(BIZ, "donors", user=u),
        "giver list": lambda u: reports_router.statement_customers(BIZ, user=u),
        "giver statement": lambda u: reports_router.customer_statement(BIZ, "c1", user=u),
        "giver statement export": lambda u: reports_router.export(BIZ, "customer_statement", contact_id="c1", user=u),
        "giver statement email": lambda u: asyncio.run(statement_send(u)),
        "bank reconciliation": lambda u: reports_router.bank_reconciliation(BIZ, user=u),
        "bank reconciliation export": lambda u: reports_router.export(BIZ, "bank_reconciliation", user=u),
        "bank reads": lambda u: plaid_router._require_reader(BIZ, u),
    }


@pytest.fixture
def reader(monkeypatch):
    monkeypatch.setattr(reports_router, "_owner_or_reader",
                        lambda biz, user: {"id": biz, "name": "Love City Church", "type": "ministry"})


@pytest.mark.parametrize("door", sorted(_doors()))
@pytest.mark.parametrize("who", ["pastor", "admin", "owner"])
def test_every_giving_door_refuses_everyone_but_the_keeper(church, reader, door, who):
    before = len(church.writes)
    _locked(_doors()[door], PEOPLE[who])
    assert len(church.writes) == before, "nothing is written before the lock"


def test_the_owner_is_held_at_the_owner_only_money_pages_too(church):
    _locked(stripe_data_proxy._require_owner_with_acct, BIZ, PEOPLE["owner"])
    _locked(plaid_router._require_owner, BIZ, PEOPLE["owner"])
    _key(church, "owner")
    assert stripe_data_proxy._require_owner_with_acct(BIZ, PEOPLE["owner"])["stripe_account_id"] == "acct_love"
    assert plaid_router._require_owner(BIZ, PEOPLE["owner"])["id"] == BIZ


def test_the_keeper_gets_in_and_a_key_opens_it_for_an_hour(church, reader):
    assert giving_router.giving_records(BIZ, 2026, user=PEOPLE["treasurer"]) == {"rows": [], "year": 2026}
    assert plaid_router._require_reader(BIZ, PEOPLE["treasurer"])["id"] == BIZ
    _key(church)
    assert giving_router.giving_records(BIZ, 2026, user=PEOPLE["pastor"])["year"] == 2026
    assert giving_router.create_manual_gift(BIZ, dict(GIFT), user=PEOPLE["pastor"])["ok"]
    assert reports_router.statement_customers(BIZ, user=PEOPLE["pastor"])["ok"]
    assert plaid_router._require_reader(BIZ, PEOPLE["pastor"])["id"] == BIZ
    _later(church, minutes=61)
    _locked(giving_router.giving_records, BIZ, 2026, user=PEOPLE["pastor"])


def test_chiefs_statements_are_locked_the_same_way(church):
    import chief_giving_actions as chief
    from chief_of_staff import _TURN_USER_ID
    token = _TURN_USER_ID.set(ID["pastor"])
    try:
        with pytest.raises(HTTPException) as e:
            chief._authorize({"id": BIZ})
        assert e.value.status_code == 403 and "locked" in e.value.detail and "key" in e.value.detail
        _key(church)
        chief._authorize({"id": BIZ})
    finally:
        _TURN_USER_ID.reset(token)
    token = _TURN_USER_ID.set(ID["treasurer"])
    try:
        chief._authorize({"id": BIZ})
    finally:
        _TURN_USER_ID.reset(token)


def test_revenue_and_profitability_keep_their_totals_and_leave_out_the_givers(church, reader, monkeypatch):
    import gl_reports
    import gl_reports_t2
    import gl_reports_t3
    givers = [{"customer": "Marcus Hill", "amount": 500.0}]
    monkeypatch.setattr(gl_reports, "gl_active", lambda biz: True)
    monkeypatch.setattr(gl_reports_t2, "revenue_report",
                        lambda *a: {"report": "revenue", "total_revenue": 500.0, "by_customer": list(givers)})
    monkeypatch.setattr(gl_reports_t3, "profitability",
                        lambda *a: {"report": "profitability", "by_customer": list(givers), "by_offering": []})
    for fn in (reports_router.revenue, reports_router.profitability):
        shut = fn(BIZ, user=PEOPLE["pastor"])
        assert shut["by_customer"] == [] and shut["givers_locked"] is True
        assert fn(BIZ, user=PEOPLE["treasurer"])["by_customer"] == givers
    assert reports_router.revenue(BIZ, user=PEOPLE["pastor"])["total_revenue"] == 500.0
    out = reports_router.export(BIZ, "revenue", user=PEOPLE["pastor"]).body.decode()
    assert "Marcus" not in out and "500" in out
    assert "Marcus" in reports_router.export(BIZ, "revenue", user=PEOPLE["treasurer"]).body.decode()


def test_no_keeper_no_lock_and_other_businesses_are_never_locked(db, reader):
    db.t["businesses"][0]["stripe_account_id"] = "acct_love"
    db.t["invoices"] = []
    assert giving_router.giving_records(BIZ, 2026, user=PEOPLE["pastor"])["year"] == 2026
    assert stripe_data_proxy._require_owner_with_acct(BIZ, PEOPLE["owner"])["id"] == BIZ
    db.t["businesses"].append({"id": SHOP, "name": "Fade Shop", "type": "barber", "owner_id": ID["owner"],
                               "stripe_account_id": "acct_fade"})
    assert plaid_router._require_owner(SHOP, PEOPLE["owner"])["id"] == SHOP
    assert _refused(ck.put_keeper, SHOP, PEOPLE["owner"], "giving_money", ID["owner"], True).status_code == 404
    assert db.t["church_keepers"] == []


def test_a_failed_read_of_the_keepers_is_a_503_never_an_open_door(church, monkeypatch):
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **k: None if path.startswith("/church_keepers") else real(path, **k))
    for who in ("pastor", "treasurer"):
        assert _refused(giving_router.giving_records, BIZ, 2026, user=PEOPLE[who]).status_code == 503
        assert _refused(plaid_router._require_reader, BIZ, PEOPLE[who]).status_code == 503


# ─── The outside accountant ───────────────────────────────────────────

def test_the_outside_accountant_is_locked_and_asks_for_givings_key(church):
    _locked(plaid_router._require_reader, BIZ, ACCOUNTANT)
    _locked(giving_router.giving_records, BIZ, 2026, user=ACCOUNTANT)
    seen = ck.keys_overview(BIZ, user=ACCOUNTANT)
    assert [a["area"] for a in seen["areas"]] == ["giving_money"] and seen["areas"][0]["locked"]
    asked = ck.keys_ask({"business_id": BIZ, "area": "giving_money", "reason": "Year-end close"}, user=ACCOUNTANT)
    assert asked["told"] == 1
    assert church.told[-1][0] == [ID["treasurer"]] and church.told[-1][1].startswith("books@cpa.example asks")
    ck.put_keeper(BIZ, PEOPLE["admin"], "kids_youth", ID["second"], True)
    assert _refused(ck.keys_ask, {"business_id": BIZ, "area": "kids_youth"}, user=ACCOUNTANT).status_code == 400
    waiting = ck.overview(BIZ, PEOPLE["treasurer"])["waiting"]
    assert [w["who"] for w in waiting] == ["books@cpa.example"]
    ck.answer(BIZ, PEOPLE["treasurer"], asked["key"]["id"], True)
    assert church.told[-1][0] == [ACCOUNTANT.id] and church.emailed[-1] == ["books@cpa.example"]
    assert plaid_router._require_reader(BIZ, ACCOUNTANT)["id"] == BIZ
    assert giving_router.giving_records(BIZ, 2026, user=ACCOUNTANT)["year"] == 2026


def test_the_accountant_never_answers_and_a_stranger_still_sees_nothing(church):
    asked = ck.ask(BIZ, PEOPLE["pastor"], "giving_money", "")
    assert _refused(ck.keys_answer, asked["key"]["id"], {"business_id": BIZ, "yes": True},
                    user=ACCOUNTANT).status_code == 404
    assert _refused(ck.keepers_put, {"business_id": BIZ, "area": "giving_money", "user_id": ACCOUNTANT.id},
                    user=ACCOUNTANT).status_code == 404
    for fn, args in ((ck.keys_overview, (BIZ,)), (ck.keys_ask, ({"business_id": BIZ, "area": "giving_money"},))):
        assert _refused(fn, *args, user=PEOPLE["stranger"]).status_code == 404
    church.t["business_collaborators"][0]["status"] = "revoked"
    assert _refused(ck.keys_overview, BIZ, user=ACCOUNTANT).status_code == 404


def test_an_accountant_is_never_named_a_keeper(church):
    e = _refused(ck.put_keeper, BIZ, PEOPLE["treasurer"], "giving_money", ACCOUNTANT.id, True)
    assert e.status_code == 400


def test_a_church_that_changes_its_type_stays_locked(church, reader):
    # A church can change its own type, so the lock never asks what type a
    # business is: it asks whether anyone keeps the area.
    church.t["businesses"][0]["type"] = "consultant"
    _locked(plaid_router._require_owner, BIZ, PEOPLE["owner"])
    _locked(stripe_data_proxy._require_owner_with_acct, BIZ, PEOPLE["owner"])
    _locked(reports_router.statement_customers, BIZ, user=PEOPLE["pastor"])


def test_an_accountant_whose_name_cant_be_read_still_asks_only_for_giving(church, monkeypatch):
    ck.put_keeper(BIZ, PEOPLE["admin"], "kids_youth", ID["second"], True)
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: None
                        if path.startswith("/business_collaborators") and "invited_email" in path else real(path, **k))
    assert _refused(ck.keys_ask, {"business_id": BIZ, "area": "kids_youth"}, user=ACCOUNTANT).status_code == 400
    assert [a["area"] for a in ck.keys_overview(BIZ, user=ACCOUNTANT)["areas"]] == ["giving_money"]
    assert ck.keys_ask({"business_id": BIZ, "area": "giving_money"}, user=ACCOUNTANT)["told"] == 1
