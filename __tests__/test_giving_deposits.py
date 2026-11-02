"""
test_giving_deposits.py — the Sunday match: recorded gifts to the deposits
that carried them. Made-up figures throughout.

Kevin, 2026-10-31: everybody gives on Sunday (cash, check, card, Cash App),
the money reaches the bank over Sunday to Tuesday, and the gifts that tally
to $650 should meet the deposits that make $650. "make sure that chief can
either do it for people, match what the person does or verify. make sure
that there is no duplicates."

Pins:
  * the clear matches: a day's cash and check in one to three deposits, two
    Sundays in one deposit, online gifts less their fee in one payout (or a
    run of days), a transfer gift to its own deposit or a few in one; an
    ambiguous one is left for a person; card gifts are Stripe's
  * no duplicates: a gift or a deposit in a match is never matched again,
    by Chief or a person
  * writing is all or nothing (a deposit answered meanwhile, a closed month);
    unmatching puts everything back
  * verify catches a changed gift, a re-answered deposit, a missing fee row
  * the books: a church's non-card gift waits in 1160; a matched deposit
    clears it, its fee riding on it; never income, never waiting
  * the screen can't set or undo 'gifts' on a bank row
  * routes and Chief: readers read, the owner matches; one batch, one undo
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import action_inverse  # noqa: E402
import action_registry  # noqa: E402
import bank_money  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import gl_engine  # noqa: E402
import giving_deposits as gd  # noqa: E402
import plaid_router  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER = "00000000-0000-4000-8000-000000000001"
READER = "00000000-0000-4000-8000-000000000002"
STRANGER = "00000000-0000-4000-8000-000000000009"


def G(n):
    return f"a0000000-0000-4000-8000-{n:012d}"


def _gift(n, day, total, method, notes="", giver="A Giver", refund=None):
    return {"id": G(n), "business_id": BIZ, "is_gift": True, "status": "paid", "paid_at": f"{day}T12:00:00Z",
            "total": total, "payment_method": method, "notes": notes, "refund_amount_cents": refund,
            "contact_id": None, "contacts": {"name": giver}, "invoice_number": f"GIVE-{n}"}


def _dep(tid, day, amount, name):
    return {"transaction_id": tid, "business_id": BIZ, "account_id": "acc", "date": day, "amount": -amount,
            "name": name, "merchant_name": None, "pending": False, "excluded_from_books": False,
            "money_kind": None, "reconciled_to_payout_id": None, "gift_match_fee": 0}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        plaid_accounts=[{"account_id": "acc", "business_id": BIZ, "included_in_bookkeeping": True, "deleted_at": None}],
        # Ids in ascending order: the gift read pages by id.
        invoices=[
            _gift(1, "2026-03-01", 400, "cash"), _gift(2, "2026-03-01", 150, "cash"), _gift(3, "2026-03-01", 100, "check"),
            _gift(4, "2026-03-01", 100, "subsplash bank payout", "fee $3.20"),
            _gift(5, "2026-03-01", 50, "subsplash bank payout", "fee $1.75"),
            _gift(6, "2026-03-01", 50, "other", giver="Pat"),
            _gift(7, "2026-03-01", 25, "stripe"),                                   # Stripe's
            _gift(8, "2026-03-01", 20, "cash", refund=2000),                        # refunded
        ],
        plaid_transactions=[
            _dep("d_plate", "2026-03-02", 650, "DEPOSIT Brch/ATM"),
            _dep("d_sub", "2026-03-03", 145.05, "CITY OF LOVE OUTSUBSPLASH SD"),
            _dep("d_app", "2026-03-02", 50, "Cash App Love City"),
            _dep("d_other", "2026-03-04", 80, "SQUARE INC"),
        ],
        gift_deposit_matches=[], gift_deposit_items=[], business_expenses=[])
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("GIVING_DEPOSITS", "on")
    import period_lock
    monkeypatch.setattr(period_lock, "locked_period", lambda biz, day: None)

    def reader(business_id, user):
        if str(user.id) not in (OWNER, READER) or business_id != BIZ:
            raise HTTPException(403, "not authorized")
        return {"id": BIZ, "owner_id": OWNER}

    def owner(business_id, user):
        if str(user.id) != OWNER or business_id != BIZ:
            raise HTTPException(403, "not authorized")
        return {"id": BIZ, "owner_id": OWNER}
    monkeypatch.setattr(plaid_router, "_require_reader", reader)
    monkeypatch.setattr(plaid_router, "_require_owner", owner)
    monkeypatch.setattr(plaid_router, "_require_money_writer", owner)
    return fake


def _dep_row(db, tid):
    return next(t for t in db.t["plaid_transactions"] if t["transaction_id"] == tid)


def _run(handler, action, who=OWNER):
    token = cos._TURN_USER_ID.set(who)
    try:
        return asyncio.run(handler(None, {"id": BIZ, "owner_id": OWNER}, action))
    finally:
        cos._TURN_USER_ID.reset(token)


# ─── The clear matches (pure) ────────────────────────────────────────

def _g(i, day, cents, kind, fee=0, giver="X"):
    return {"id": f"g{i}", "date": day, "cents": cents, "kind": kind, "fee": fee, "giver": giver}


def _d(i, day, cents, channel):
    return {"id": f"d{i}", "date": day, "cents": cents, "channel": channel, "waiting": True, "money_kind": None}


def test_a_sundays_cash_and_check_meet_the_deposit_that_makes_it():
    gs = [_g(1, "2026-03-01", 40000, "plate"), _g(2, "2026-03-01", 25000, "plate")]
    (p,) = gd.plan(gs, [_d(1, "2026-03-02", 65000, "plate")])
    assert (p["kind"], p["gifts"], p["deposits"], p["fee_cents"]) == ("plate", ["g1", "g2"], ["d1"], 0)
    # Split over two deposits Monday and Tuesday.
    (p,) = gd.plan(gs, [_d(1, "2026-03-02", 40000, "plate"), _d(2, "2026-03-03", 25000, "plate"),
                        _d(3, "2026-03-03", 12000, "plate")])
    assert sorted(p["deposits"]) == ["d1", "d2"]


def test_two_sundays_in_one_deposit_and_an_ambiguous_one_left():
    gs = [_g(1, "2026-03-01", 30000, "plate"), _g(2, "2026-03-08", 20000, "plate")]
    (p,) = gd.plan(gs, [_d(1, "2026-03-09", 50000, "plate")])
    assert sorted(p["gifts"]) == ["g1", "g2"]
    # Two deposits that could each be Sunday's: for a person, never a guess.
    assert gd.plan([_g(1, "2026-03-01", 30000, "plate")],
                   [_d(1, "2026-03-02", 30000, "plate"), _d(2, "2026-03-03", 30000, "plate")]) == []


def test_online_gifts_less_their_fee_meet_the_payout():
    gs = [_g(1, "2026-03-01", 10000, "online", 320), _g(2, "2026-03-01", 5000, "online", 175)]
    (p,) = gd.plan(gs, [_d(1, "2026-03-03", 14505, "online")])
    assert (p["gifts_cents"], p["deposits_cents"], p["fee_cents"]) == (15000, 14505, 495)
    # A weekend paid out together.
    gs2 = [_g(1, "2026-02-28", 10000, "online", 300), _g(2, "2026-03-01", 5000, "online", 150)]
    (p,) = gd.plan(gs2, [_d(1, "2026-03-03", 14550, "online")])
    assert sorted(p["gifts"]) == ["g1", "g2"] and p["fee_cents"] == 450


def test_a_transfer_gift_meets_its_own_deposit_or_a_few_share_one():
    (p,) = gd.plan([_g(1, "2026-03-01", 5000, "transfer", giver="Pat")], [_d(1, "2026-03-02", 5000, "transfer")])
    assert p["gifts"] == ["g1"] and "Pat" in p["why"]
    gs = [_g(1, "2026-03-01", 7000, "transfer"), _g(2, "2026-03-01", 5000, "transfer")]
    (p,) = gd.plan(gs, [_d(1, "2026-03-03", 12000, "transfer")])
    assert sorted(p["gifts"]) == ["g1", "g2"]
    # Two $50 gifts and two $50 deposits: which is whose is a person's call.
    gs = [_g(1, "2026-03-01", 5000, "transfer"), _g(2, "2026-03-01", 5000, "transfer")]
    assert gd.plan(gs, [_d(1, "2026-03-02", 5000, "transfer"), _d(2, "2026-03-02", 5000, "transfer")]) == []


def test_a_gift_or_deposit_already_matched_is_never_matched_again():
    g, d = _g(1, "2026-03-01", 5000, "transfer"), _d(1, "2026-03-02", 5000, "transfer")
    assert gd.check_match([g], [d], set()) == (None, 0)
    why, _ = gd.check_match([g], [d], {("gift", "g1")})
    assert "already matched" in why
    why, _ = gd.check_match([g], [d], {("deposit", "d1")})
    assert "already matched" in why
    why, _ = gd.check_match([g], [{**d, "waiting": False}], set())
    assert "already has an answer" in why
    why, _ = gd.check_match([g], [{**d, "cents": 4000}], set())
    assert "less than the gifts" in why and "$10.00" in why
    why, _ = gd.check_match([_g(1, "2026-03-01", 10000, "online")], [{**d, "cents": 8000}], set())
    assert why and "less than the gifts" in why                       # over the 10% a platform keeps


# ─── Writing, undoing, verifying ─────────────────────────────────────

def test_chief_matches_what_is_clear_once_and_only_once(db):
    got = gd.match_clear(BIZ, OWNER, year=2026)
    assert len(got["matched"]) == 3 and got["batch_id"]
    kinds = sorted(m["kind"] for m in got["matched"])
    assert kinds == ["online", "plate", "transfer"]
    assert {_dep_row(db, t)["money_kind"] for t in ("d_plate", "d_sub", "d_app")} == {"gifts"}
    assert _dep_row(db, "d_sub")["gift_match_fee"] == 4.95 and _dep_row(db, "d_other")["money_kind"] is None
    (fee,) = db.t["business_expenses"]
    assert (fee["amount"], fee["category"], fee["subcategory"]) == (4.95, "operating", gd.FEE_LABEL)
    assert len(db.t["gift_deposit_items"]) == 3 + 2 + 1 + 3          # 6 gifts, 3 deposits
    again = gd.match_clear(BIZ, OWNER, year=2026)
    assert again["matched"] == [] and len(db.t["gift_deposit_matches"]) == 3
    st = gd.status(BIZ, year=2026)
    assert st["problems"] == [] and st["proposals"] == [] and st["totals"]["matched"] == 850.0


def test_a_person_matches_exactly_what_they_name_and_never_twice(db):
    m = gd.match_named(BIZ, OWNER, [G(1), G(2), G(3)], ["d_plate"], note="Sunday's plate")
    assert m["made_by"] == "person" and m["gifts_cents"] == 65000
    with pytest.raises(HTTPException) as e:
        gd.match_named(BIZ, OWNER, [G(1)], ["d_app"])
    assert e.value.status_code == 409 and "already matched" in e.value.detail
    with pytest.raises(HTTPException) as e:
        gd.match_named(BIZ, OWNER, [G(6)], ["d_plate"])
    assert "already matched" in e.value.detail
    with pytest.raises(HTTPException) as e:
        gd.match_named(BIZ, OWNER, [G(7)], ["d_other"])                 # a card gift
    assert e.value.status_code == 422


def test_a_deposit_answered_meanwhile_or_a_closed_month_leaves_nothing(db, monkeypatch):
    real = sb_clients.sb_patch_as_service
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body, **kw: [] if "plaid_transactions" in path and "is.null" in path
                        else real(path, body, **kw))
    with pytest.raises(HTTPException) as e:
        gd.match_named(BIZ, OWNER, [G(4), G(5)], ["d_sub"])
    assert e.value.status_code == 409
    assert db.t["gift_deposit_matches"] == [] and db.t["business_expenses"] == []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", real)
    import period_lock
    monkeypatch.setattr(period_lock, "locked_period",
                        lambda biz, day: {"period_start": "2026-03-01", "period_end": "2026-03-31"})
    with pytest.raises(HTTPException) as e:
        gd.match_named(BIZ, OWNER, [G(6)], ["d_app"])
    assert "closed month" in e.value.detail and db.t["gift_deposit_matches"] == []


def test_unmatching_puts_it_all_back(db):
    got = gd.match_clear(BIZ, OWNER, year=2026)
    done = gd.unmatch(BIZ, [m["id"] for m in got["matched"]])
    assert done["unmatched"] == 3
    assert {_dep_row(db, t)["money_kind"] for t in ("d_plate", "d_sub", "d_app")} == {None}
    assert _dep_row(db, "d_sub")["gift_match_fee"] == 0 and db.t["business_expenses"] == []
    assert len(gd.status(BIZ, year=2026)["proposals"]) == 3        # ready again


def test_a_batch_that_fails_partway_keeps_what_it_made_and_its_undo(db, monkeypatch):
    real = gd.write_match
    calls = []

    def flaky(*a, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise gd.Unavailable("plaid_transactions")
        return real(*a, **kw)
    monkeypatch.setattr(gd, "write_match", flaky)
    got = _run(gd.handle_match_giving_deposits, {"year": 2026})
    assert not got.get("failed") and got["summary"]["count"] == 2 and got["batch_id"]
    assert "couldn't be saved just now" in got["result"]


def test_verify_reads_a_matchs_own_gifts_wherever_they_fall(db):
    # A person matched a gift from well before its deposit: not "gone".
    db.t["invoices"].append(_gift(9, "2026-01-20", 75, "other", giver="Lee"))
    db.t["plaid_transactions"].append(_dep("d_late", "2026-03-05", 75, "Cash App Love City"))
    gd.match_named(BIZ, OWNER, [G(9)], ["d_late"], note="the owner said so")
    st = gd.status(BIZ, start="2026-03-01", end="2026-03-31")
    assert st["problems"] == [] and any(m["note"] == "the owner said so" for m in st["matched"])


def test_a_deposit_a_payout_just_claimed_is_never_marked_gifts(db):
    _dep_row(db, "d_app")["reconciled_to_payout_id"] = "po_1"
    with pytest.raises(HTTPException):
        gd.write_match(BIZ, [{"id": G(6), "kind": "transfer", "cents": 5000, "date": "2026-03-01", "giver": "Pat"}],
                       [{"id": "d_app", "cents": 5000, "date": "2026-03-02"}], fee=0, made_by="person", user_id=OWNER)
    assert db.t["gift_deposit_matches"] == [] and _dep_row(db, "d_app")["money_kind"] is None


def test_verify_catches_what_changed_after_a_match(db):
    gd.match_clear(BIZ, OWNER, year=2026)
    next(i for i in db.t["invoices"] if i["id"] == G(1))["total"] = 450        # a gift edited after
    _dep_row(db, "d_app")["money_kind"] = "income"                             # a deposit re-answered
    db.t["business_expenses"].clear()                                          # the fee row deleted
    probs = gd.status(BIZ, year=2026)["problems"]
    said = " ".join(p for x in probs for p in x["problems"])
    assert "changed from $400.00 to $450.00" in said
    assert "was given another answer" in said
    assert "fee's expense row is missing" in said


# ─── The books ───────────────────────────────────────────────────────

def _paid(entries):
    return [e for e in entries if e["source_type"] == "invoice_payment"][0]


def test_a_churchs_non_card_gift_waits_in_gifts_to_deposit_only_where_the_match_is_on():
    gift = {"id": "i1", "total": 50, "status": "paid", "paid_at": "2026-03-01T12:00:00Z", "is_gift": True,
            "payment_method": "cash"}
    pay = _paid(gl_engine.desired_for_invoice(gift, "church", gifts_wait=True))
    assert {(l["code"], l["debit"]) for l in pay["lines"] if l["debit"]} == {("1160", 50)}
    # Switched off for this church: as before, so 1160 never fills where nothing clears it.
    off = _paid(gl_engine.desired_for_invoice(gift, "church"))
    assert {(l["code"], l["debit"]) for l in off["lines"] if l["debit"]} == {("1000", 50)}
    card = _paid(gl_engine.desired_for_invoice({**gift, "payment_method": "stripe"}, "church", gifts_wait=True))
    assert any(l["code"] == "1150" and l["debit"] for l in card["lines"])
    coach = _paid(gl_engine.desired_for_invoice({**gift, "is_gift": False}, "coach", gifts_wait=True))
    assert any(l["code"] == "1000" and l["debit"] for l in coach["lines"])
    assert "1160" in {c[0] for c in gl_engine._coa_for("church")}
    specs = gl_engine.generate_entries({"invoices": [gift], "expenses": [], "bills": [], "plaid": [],
                                        "business_type": "church", "gifts_wait": True, "cash_on_hand": 0})
    assert any(l["code"] == "1160" for s in specs for l in s["lines"])


def test_the_ledger_asks_the_switch_definitely_or_leaves_the_rows_queued(db, monkeypatch):
    monkeypatch.setenv("GIVING_DEPOSITS", "on")
    assert gd.ledger_gifts_wait(BIZ) is True
    monkeypatch.setenv("GIVING_DEPOSITS", "off")
    assert gd.ledger_gifts_wait(BIZ) is False
    monkeypatch.setenv("GIVING_DEPOSITS", "owner")
    db.t["businesses"] = [{"id": BIZ, "owner_id": cos.PLATFORM_OWNER_ID}]
    assert gd.ledger_gifts_wait(BIZ) is True
    db.t["businesses"] = [{"id": BIZ, "owner_id": STRANGER}]
    assert gd.ledger_gifts_wait(BIZ) is False
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: None)
    with pytest.raises(gd.Unavailable):                 # can't tell: the ledger leaves the row queued
        gd.ledger_gifts_wait(BIZ)


def test_a_matched_deposit_clears_the_gifts_with_its_fee_and_is_never_income(monkeypatch):
    t = {"transaction_id": "d1", "amount": -145.05, "date": "2026-03-03", "money_kind": "gifts",
         "gift_match_fee": 4.95, "pending": False, "excluded_from_books": False}
    (e,) = gl_engine.desired_for_plaid(t)
    lines = {(l["code"], l["debit"], l["credit"]) for l in e["lines"]}
    assert lines == {("1000", 150.0, 0), ("1160", 0, 150.0)}
    assert not bank_money.is_income(t) and not bank_money.needs_category(t)


def test_the_screen_never_sets_or_undoes_gifts_on_a_bank_row(db, monkeypatch):
    import period_lock
    monkeypatch.setattr(plaid_router, "_require_money_writer_for_tx", lambda tid, user: {"business_id": BIZ})
    monkeypatch.setattr(period_lock, "guard", lambda *a, **k: None)
    monkeypatch.setattr(bank_money, "state", lambda: True)
    user = AuthedUser(id=OWNER, email="x@y.z", role="authenticated")
    with pytest.raises(HTTPException) as e:
        plaid_router.update_transaction("d_app", plaid_router.TxPatchBody(money_kind="gifts"), user)
    assert e.value.status_code == 400
    _dep_row(db, "d_app")["money_kind"] = "gifts"
    with pytest.raises(HTTPException) as e:
        plaid_router.update_transaction("d_app", plaid_router.TxPatchBody(money_kind="income"), user)
    assert e.value.status_code == 409 and "Unmatch it" in e.value.detail


# ─── Routes and Chief ────────────────────────────────────────────────

def _client(user_id):
    app = FastAPI()
    app.include_router(gd.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id=user_id, email="x@y.z", role="authenticated")
    return TestClient(app)


def test_readers_read_the_owner_matches_off_is_a_404(db, monkeypatch):
    got = _client(READER).get("/giving-deposits", params={"business_id": BIZ, "year": 2026})
    assert got.status_code == 200 and got.json()["can_change"] is False and len(got.json()["proposals"]) == 3
    assert _client(READER).post("/giving-deposits/match", json={"business_id": BIZ, "clear": True}).status_code == 403
    made = _client(OWNER).post("/giving-deposits/match", json={"business_id": BIZ, "gift_ids": [G(6)],
                                                              "deposit_ids": ["d_app"]})
    assert made.status_code == 200, made.text
    mid = made.json()["match"]["id"]
    assert _client(OWNER).delete(f"/giving-deposits/{mid}", params={"business_id": BIZ}).status_code == 200
    monkeypatch.setenv("GIVING_DEPOSITS", "off")
    assert _client(OWNER).get("/giving-deposits", params={"business_id": BIZ}).status_code == 404


def test_chief_verifies_matches_the_clear_ones_and_one_undo_takes_them_back(db):
    seen = _run(gd.handle_giving_deposits, {"year": 2026}, who=READER)
    assert not seen.get("failed") and "3 clear matches ready" in seen["result"]
    done = _run(gd.handle_match_giving_deposits, {"year": 2026})
    assert not done.get("failed") and done["display"] == "table" and len(done["match_ids"]) == 3
    assert "kept by the giving platform" in done["result"]
    inv = action_inverse.build_inverse("match_giving_deposits", {}, done)
    assert inv == {"type": "unmatch_giving_deposits", "batch_id": done["batch_id"]}
    back = _run(gd.handle_unmatch_giving_deposits, inv)
    assert "Unmatched 3" in back["result"] and db.t["gift_deposit_matches"] == []
    assert _run(gd.handle_match_giving_deposits, {}, who=READER)["failed"]
    assert _run(gd.handle_giving_deposits, {}, who=STRANGER)["failed"]


def test_chief_matches_exactly_what_the_owner_says(db):
    got = _run(gd.handle_match_giving_deposits, {"items": [
        {"gift_ids": [G(1), G(2), G(3)], "deposit_ids": ["d_plate"], "note": "Monday's deposit is Sunday's plate"},
        {"gift_ids": [G(6)], "deposit_ids": ["d_plate"]}]})
    assert got["summary"]["count"] == 1 and "already matched" in got["result"]
    m = db.t["gift_deposit_matches"][0]
    assert m["made_by"] == "person" and m["batch_id"] == got["batch_id"]


def test_the_verbs_are_wired():
    import chief_tool_loop
    assert cos.ACTION_HANDLERS["match_giving_deposits"] is gd.handle_match_giving_deposits
    assert action_registry.REGISTRY["match_giving_deposits"]["chief_only"] is True
    assert "giving_deposits" in {t["name"] for t in chief_tool_loop.read_tool_definitions()}
    import chief_prompt
    src = open(chief_prompt.__file__, encoding="utf-8").read().replace("{{", "{")
    assert all(f'"type":"{v}"' in src for v in ("match_giving_deposits", "unmatch_giving_deposits"))
