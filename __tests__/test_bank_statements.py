"""
test_bank_statements.py — the months before the bank feed, from the bank's
own statements.

Kevin, 2026-10-31: "how about we upload all the statements that is missing so
they can be added into the system itself ... build a scanner or ability to
upload?"

Pins:
  * reading: a bank CSV (signed amounts with a running balance, newest first;
    debit and credit columns; a heading above the header), an OFX download,
    a PDF read by Claude into parts; a spreadsheet or a CSV with no amounts
    is refused, never guessed
  * the check: opening + in - out = closing to the cent, and a PDF's own
    totals agree; one balance or none is "not checked", never "balanced"
  * each row against the books: new, already in, maybe in, in the feed
    (matched to the feed's row, a day or two apart; or missing from it)
  * adding: the kept rows only, in Plaid's sign, tagged with the statement;
    a statement that doesn't add up only when the owner says so; a failed
    write leaves nothing behind
  * removing: not while a row is on a fund or a housing allowance
  * coverage: the days of the year before the feed nothing covers, and
    whether each statement opens where the one before it closed
  * who may: readers see the coverage, the owner alone reads and adds; off
    is a 404; a failed read is a 503
  * Chief: bank_history names the feed start, the statements, what's missing
"""
from __future__ import annotations

import asyncio
import io
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

import bank_statements as bs  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import plaid_router  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
OWNER = "00000000-0000-4000-8000-000000000001"
READER = "00000000-0000-4000-8000-000000000002"
STRANGER = "00000000-0000-4000-8000-000000000009"


def _tx(tid, on, amount, name="ONLINE TRANSFER", **kw):
    return {"transaction_id": tid, "business_id": BIZ, "account_id": "acc_books", "date": on, "name": name,
            "merchant_name": None, "amount": amount, "pending": False, "statement_import_id": None, **kw}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        businesses=[{"id": BIZ, "owner_id": OWNER, "name": "Love City", "type": "church"}],
        plaid_accounts=[
            {"account_id": "acc_books", "business_id": BIZ, "name": "Business Checking", "mask": "4417",
             "included_in_bookkeeping": True, "deleted_at": None},
            {"account_id": "acc_personal", "business_id": BIZ, "name": "Personal", "mask": "0001",
             "included_in_bookkeeping": False, "deleted_at": None}],
        # The feed, oldest first (the fake ignores order): Plaid's sign, money out positive.
        plaid_transactions=[
            _tx("tx_first", "2026-07-17", 12, name="MONTHLY SERVICE FEE"),
            _tx("tx_jul", "2026-07-20", 2500),
            _tx("tx_dep", "2026-07-21", -1800, name="DEPOSIT")],
        bank_statement_imports=[], business_fund_items=[], minister_housing_entries=[])
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("BANK_STATEMENTS", "on")
    import plaid_reconciliation
    monkeypatch.setattr(plaid_reconciliation, "reconcile_business", lambda *a, **k: (0, 0))

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
    return fake


def _client(user_id):
    app = FastAPI()
    app.include_router(bs.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id=user_id, email="x@y.z", role="authenticated")
    return TestClient(app)


def _run(handler, action, who=OWNER):
    token = cos._TURN_USER_ID.set(who)
    try:
        return asyncio.run(handler(None, {"id": BIZ, "owner_id": OWNER}, action))
    finally:
        cos._TURN_USER_ID.reset(token)


# July, as the statement prints it (money in positive): it runs into the feed.
JULY = [
    {"date": "2026-07-02", "description": "REMOTE DEPOSIT", "amount": 1200},
    {"date": "2026-07-10", "description": "Check 1001", "amount": -300},
    {"date": "2026-07-15", "description": "ONLINE TRANSFER TO SAVINGS", "amount": -2500},
    {"date": "2026-07-16", "description": "SERVICE FEE", "amount": -12},       # the feed has it on the 17th
    {"date": "2026-07-20", "description": "ONLINE TRANSFER", "amount": -2500},
    {"date": "2026-07-21", "description": "DEPOSIT", "amount": 1800},
    {"date": "2026-07-25", "description": "Check 1002", "amount": -40},         # the feed doesn't have it
]
JULY_BALANCES = {"opening": 5000, "closing": 2648}


def _july(**kw):
    return {"business_id": BIZ, "account_id": "acc_books", "file_name": "July 2026.pdf", "kind": "pdf",
            "period_start": "2026-07-01", "period_end": "2026-07-31", "rows": [dict(r) for r in JULY],
            **JULY_BALANCES, **kw}


# ─── Reading ─────────────────────────────────────────────────────────

CHASE = (b"Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n"
         b"DEBIT,02/03/2026,CHECK 1001,-300.00,CHECK_PAID,4900.00,1001\n"
         b"CREDIT,02/02/2026,REMOTE ONLINE DEPOSIT,1200.00,DEPOSIT,5200.00,\n"
         b"DEBIT,02/01/2026,MONTHLY SERVICE FEE,-12.00,FEE_TRANSACTION,4000.00,\n")


def test_a_bank_csv_with_a_running_balance_reads_oldest_first_and_checks():
    (part,) = bs.parse_csv(CHASE)
    assert [r["date"] for r in part["rows"]] == ["2026-02-01", "2026-02-02", "2026-02-03"]
    assert [r["amount"] for r in part["rows"]] == [-12, 1200, -300]
    assert part["rows"][2]["description"] == "CHECK 1001"                   # the check number isn't said twice
    assert (part["opening"], part["closing"]) == (4012, 4900)
    assert bs.check(part["rows"], part["opening"], part["closing"])["state"] == "balanced"
    assert (part["period_start"], part["period_end"]) == ("2026-02-01", "2026-02-03")


def test_debit_and_credit_columns_under_a_heading_line():
    raw = (b"Account: Business Checking ending 4417\n\n"
           b"Date,Description,Memo,Debit,Credit\n"
           b'01/05/2026,TITHE.LY PAYOUT,,,"$1,234.50"\n'
           b"01/06/2026,AMAZON,office paper,(45.10),\n"
           b"Total,,,45.10,1234.50\n")
    (part,) = bs.parse_csv(raw)
    assert [(r["amount"], r["description"]) for r in part["rows"]] == [
        (1234.5, "TITHE.LY PAYOUT"), (-45.1, "AMAZON · office paper")]
    assert part["unread_lines"] == 1 and part["opening"] is None
    assert bs.check(part["rows"])["state"] == "no_balances"


def test_a_csv_with_no_amounts_or_a_spreadsheet_is_refused():
    with pytest.raises(HTTPException) as e:
        bs.parse_csv(b"Name,Email\nKevin,k@example.com\n")
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        bs.kind_of("statement.xlsx", b"PK\x03\x04rest")
    assert e.value.status_code == 415
    assert bs.kind_of("x.QFX", b"OFXHEADER:100") == "ofx" and bs.kind_of("s", b"%PDF-1.7") == "pdf"


OFX = b"""OFXHEADER:100
DATA:OFXSGML
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>USD
<BANKACCTFROM><BANKID>123<ACCTID>000123454417<ACCTTYPE>CHECKING</BANKACCTFROM>
<BANKTRANLIST><DTSTART>20260301<DTEND>20260331
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260302120000.000[-5:EST]<TRNAMT>1200.00<FITID>1<NAME>DEPOSIT</STMTTRN>
<STMTTRN><TRNTYPE>CHECK<DTPOSTED>20260310<TRNAMT>-300.00<FITID>2<CHECKNUM>1001<NAME>CHECK PAID</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260315<TRNAMT>-25.50<FITID>3<NAME>AT&amp;T<MEMO>PHONE BILL</STMTTRN>
</BANKTRANLIST><LEDGERBAL><BALAMT>4874.50<DTASOF>20260331</LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""


def test_an_ofx_download_reads_its_account_period_and_one_balance():
    (part,) = bs.parse_ofx(OFX)
    assert part["last4"] == "4417" and (part["period_start"], part["period_end"]) == ("2026-03-01", "2026-03-31")
    assert [r["amount"] for r in part["rows"]] == [1200, -300, -25.5]
    assert part["rows"][1]["description"] == "CHECK PAID · Check 1001"
    assert part["rows"][2]["description"] == "AT&T · PHONE BILL"
    assert part["closing"] == 4874.5 and part["opening"] is None
    assert bs.check(part["rows"], part["opening"], part["closing"])["state"] == "one_balance"


def test_money_as_banks_print_it():
    assert [bs._money(v) for v in ("$1,234.50", "(12.00)", "12.00-", "-12", "12.00 CR", "45.10DR", "", "n/a")] == [
        1234.5, -12, -12, -12, 12, -45.1, None, None]


def _fake_claude(monkeypatch, got, stop="tool_use"):
    import billing_limits
    import llm_call
    calls = []

    class Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"stop_reason": stop, "content": [{"type": "tool_use", "name": "statement", "input": got}]}

    async def apost(client, payload, **kw):
        calls.append((payload, kw))
        return Resp()
    monkeypatch.setattr(llm_call, "api_key", lambda: "k")
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(billing_limits, "require_units", lambda biz: None)
    monkeypatch.setattr(bs, "_pdf_ready", lambda raw: raw)
    return calls


def test_a_pdf_is_read_by_claude_into_one_part_per_account(monkeypatch):
    calls = _fake_claude(monkeypatch, {"bank": "Huntington", "accounts": [
        {"name": "Business Checking", "last4": "x4417", "period_start": "2026-07-01", "period_end": "2026-07-31",
         "opening_balance": 5000, "closing_balance": 2648, "total_deposits": 3000, "total_withdrawals": -5352,
         "transactions": JULY + [{"date": "July 9", "description": "unreadable", "amount": 5}]},
        {"name": "Savings", "last4": "9001", "period_start": "2026-07-01", "period_end": "2026-07-31",
         "transactions": [{"date": "2026-07-31", "description": "INTEREST", "amount": 0.42}]}]})
    bank, parts = asyncio.run(bs.read_pdf(BIZ, b"%PDF-1.7"))
    assert bank == "Huntington" and [p["last4"] for p in parts] == ["4417", "9001"]
    first = parts[0]
    assert len(first["rows"]) == len(JULY) and first["unread_lines"] == 1
    assert (first["statement_in"], first["statement_out"]) == (3000, 5352)     # printed totals, as positives
    ck = bs.check(first["rows"], first["opening"], first["closing"], first["statement_in"], first["statement_out"])
    assert ck["state"] == "balanced"
    payload, kw = calls[0]
    assert payload["tool_choice"] == {"type": "tool", "name": "statement"} and kw["business_id"] == BIZ
    assert payload["messages"][0]["content"][0]["source"]["media_type"] == "application/pdf"


def test_a_pdf_too_long_to_read_says_so(monkeypatch):
    _fake_claude(monkeypatch, {"accounts": []}, stop="max_tokens")
    with pytest.raises(HTTPException) as e:
        asyncio.run(bs.read_pdf(BIZ, b"%PDF-1.7"))
    assert e.value.status_code == 422 and "too long" in e.value.detail


def test_a_locked_pdf_is_refused_and_an_edit_lock_is_lifted():
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(72, 72)
    plain = io.BytesIO()
    w.write(plain)
    assert bs._pdf_ready(plain.getvalue()).startswith(b"%PDF")
    w.encrypt(user_password="", owner_password="bank", algorithm="AES-128")   # locked against editing only
    edit = io.BytesIO()
    w.write(edit)
    assert bs._pdf_ready(edit.getvalue()).startswith(b"%PDF")
    w2 = PdfWriter()
    w2.add_blank_page(72, 72)
    w2.encrypt(user_password="secret", algorithm="AES-128")
    locked = io.BytesIO()
    w2.write(locked)
    with pytest.raises(HTTPException) as e:
        bs._pdf_ready(locked.getvalue())
    assert e.value.status_code == 422 and "password" in e.value.detail


# ─── The check ───────────────────────────────────────────────────────

def test_the_check_is_to_the_cent_and_the_printed_totals_must_agree():
    assert bs.check(JULY, **JULY_BALANCES)["state"] == "balanced"
    off = bs.check(JULY, 5000, 2650)
    assert off["state"] == "off" and off["difference"] == -2
    totals = bs.check(JULY, 5000, 2648, statement_in=3000, statement_out=5300)
    assert totals["state"] == "off" and totals["totals_agree"] is False and totals["difference"] == 0
    assert bs.check(JULY, opening=5000)["state"] == "one_balance"


def test_the_same_row_gets_the_same_id_and_a_second_one_another():
    rows = [{"date": "2026-02-02", "description": "Coffee", "amount": -5},
            {"date": "2026-02-02", "description": "COFFEE ", "amount": -5}]
    a, b = bs.row_ids("acc_books", rows)
    assert a != b and a.startswith("stmt_") and bs.row_ids("acc_books", rows) == [a, b]
    assert bs.row_ids("acc_other", rows)[0] != a


# ─── Each row against the books ──────────────────────────────────────

def test_a_statement_that_runs_into_the_feed_is_matched_to_it(db):
    got = bs.review(BIZ, "acc_books", [dict(r) for r in JULY])
    states = [(r["date"], r["state"], (r["match"] or {}).get("transaction_id")) for r in got["rows"]]
    assert states == [
        ("2026-07-02", "new", None), ("2026-07-10", "new", None), ("2026-07-15", "new", None),
        ("2026-07-16", "in_feed", "tx_first"),             # a day apart: the feed's row, never a second one
        ("2026-07-20", "in_feed", "tx_jul"), ("2026-07-21", "in_feed", "tx_dep"),
        ("2026-07-25", "in_feed", None)]                   # the feed's days, but not in it: flagged
    assert got["feed_starts"] == "2026-07-17"
    assert got["counts"] == {"new": 3, "maybe": 0, "already": 0, "in_feed": 4, "feed_matched": 3, "feed_missing": 1}


# ─── Adding ──────────────────────────────────────────────────────────

def test_adding_puts_the_new_rows_in_the_books_in_plaids_sign(db):
    done = bs.add(BIZ, OWNER, _july())
    assert done["added"] == 3 and done["check"]["state"] == "balanced"
    (imp,) = db.t["bank_statement_imports"]
    assert (imp["period_start"], imp["period_end"], imp["check_state"], imp["rows_read"]) == (
        "2026-07-01", "2026-07-31", "balanced", 7)
    assert (imp["feed_rows"], imp["feed_missing"], imp["rows_added"]) == (4, 1, 3)
    mine = [t for t in db.t["plaid_transactions"] if t.get("statement_import_id") == imp["id"]]
    assert sorted((t["date"], t["amount"]) for t in mine) == [
        ("2026-07-02", -1200), ("2026-07-10", 300), ("2026-07-15", 2500)]
    assert all(t["transaction_id"].startswith("stmt_") and t["account_id"] == "acc_books"
               and t["pending"] is False and t["business_category"] == "other" for t in mine)
    # The feed starts where it did; the books now start in July.
    assert bs.feed_starts(BIZ, "acc_books") == "2026-07-17"
    with pytest.raises(HTTPException) as again:
        bs.add(BIZ, OWNER, _july())
    assert again.value.status_code == 422                 # all of it is in now
    assert [r["state"] for r in bs.review(BIZ, "acc_books", [dict(r) for r in JULY])["rows"]][:3] == ["already"] * 3


def test_a_row_the_owner_unticks_stays_out(db):
    body = _july()
    body["rows"][0]["keep"] = False
    assert bs.add(BIZ, OWNER, body)["added"] == 2


def test_the_same_day_and_amount_worded_another_way_is_left_to_the_owner(db):
    bs.add(BIZ, OWNER, _july())
    csv_july = [{"date": "2026-07-02", "description": "DEPOSIT REMOTE 778812", "amount": 1200},
                {"date": "2026-07-03", "description": "VENDOR", "amount": -80}]
    got = bs.review(BIZ, "acc_books", csv_july)
    assert [r["state"] for r in got["rows"]] == ["maybe", "new"]
    body = {"business_id": BIZ, "account_id": "acc_books", "rows": [dict(csv_july[0], keep=False), csv_july[1]]}
    assert bs.add(BIZ, OWNER, body)["added"] == 1


def test_a_statement_that_doesnt_add_up_waits_for_the_owner(db):
    with pytest.raises(HTTPException) as e:
        bs.add(BIZ, OWNER, _july(closing=2600))
    assert e.value.status_code == 409 and "$48.00" in e.value.detail
    assert db.t["bank_statement_imports"] == []
    done = bs.add(BIZ, OWNER, _july(closing=2600, accept_unbalanced=True))
    assert done["added"] == 3 and db.t["bank_statement_imports"][0]["check_state"] == "off"


def test_an_account_outside_the_books_or_a_bad_row_is_refused(db):
    for body in (_july(account_id="acc_personal"), _july(account_id="acc_nope")):
        with pytest.raises(HTTPException) as e:
            bs.add(BIZ, OWNER, body)
        assert e.value.status_code == 422
    bad = _july()
    bad["rows"][1]["date"] = "sometime"
    with pytest.raises(HTTPException) as e:
        bs.add(BIZ, OWNER, bad)
    assert e.value.status_code == 422 and "Row 2" in e.value.detail


def test_a_failed_write_leaves_nothing_behind(db, monkeypatch):
    real = sb_clients.sb_post_as_service
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, body, **kw: None if path.startswith("/plaid_transactions") else real(path, body, **kw))
    with pytest.raises(bs.Unavailable):
        bs.add(BIZ, OWNER, _july())
    assert db.t["bank_statement_imports"] == []
    assert all(not t.get("statement_import_id") for t in db.t["plaid_transactions"])


# ─── Removing ────────────────────────────────────────────────────────

def test_removing_takes_the_rows_out_unless_one_is_on_a_fund(db):
    done = bs.add(BIZ, OWNER, _july())
    imp = done["import"]["id"]
    one = next(t["transaction_id"] for t in db.t["plaid_transactions"] if t.get("statement_import_id") == imp)
    db.t["business_fund_items"].append({"id": "i1", "business_id": BIZ, "transaction_id": one})
    with pytest.raises(HTTPException) as e:
        bs.remove(BIZ, imp)
    assert e.value.status_code == 409 and "1 of this statement's rows is on a fund" in e.value.detail
    db.t["business_fund_items"].clear()
    db.t["minister_housing_entries"].append({"id": "h1", "business_id": BIZ, "source": "bank", "source_id": one})
    with pytest.raises(HTTPException):
        bs.remove(BIZ, imp)
    db.t["minister_housing_entries"].clear()
    assert bs.remove(BIZ, imp)["rows"] == 3
    assert db.t["bank_statement_imports"] == [] and len(db.t["plaid_transactions"]) == 3   # the feed, untouched
    with pytest.raises(HTTPException) as gone:
        bs.remove(BIZ, imp)
    assert gone.value.status_code == 404


# ─── Coverage ────────────────────────────────────────────────────────

def _feb_and_mar(db):
    feb = [{"date": "2026-02-01", "description": "FEE", "amount": -12}, {"date": "2026-02-02", "description": "DEP",
                                                                         "amount": 1200}]
    mar = [{"date": "2026-03-02", "description": "DEP", "amount": 800}]
    bs.add(BIZ, OWNER, {"business_id": BIZ, "account_id": "acc_books", "rows": feb, "opening": 4012, "closing": 5200,
                        "period_start": "2026-02-01", "period_end": "2026-02-28"})
    bs.add(BIZ, OWNER, {"business_id": BIZ, "account_id": "acc_books", "rows": mar, "opening": 5200, "closing": 6000,
                        "period_start": "2026-03-01", "period_end": "2026-03-31"})


def test_coverage_names_the_days_before_the_feed_nothing_covers(db):
    _feb_and_mar(db)
    (a,) = bs.coverage(BIZ, 2026)["accounts"]
    assert a["feed_starts"] == "2026-07-17" and a["mask"] == "4417"
    assert [(g["from"], g["to"]) for g in a["missing"]] == [("2026-01-01", "2026-01-31"), ("2026-04-01", "2026-07-16")]
    assert [i["joins_previous"] for i in a["imports"]] == [None, True]
    assert bs.coverage(BIZ, 2025)["accounts"][0]["missing"] == [{"from": "2025-01-01", "to": "2025-12-31", "days": 365}]


# ─── Who may ─────────────────────────────────────────────────────────

def test_readers_see_the_coverage_and_the_owner_alone_adds(db):
    got = _client(READER).get("/bank-statements", params={"business_id": BIZ, "year": 2026})
    assert got.status_code == 200 and got.json()["can_change"] is False
    assert _client(OWNER).get("/bank-statements", params={"business_id": BIZ}).json()["can_change"] is True
    assert _client(READER).post("/bank-statements", json=_july()).status_code == 403
    assert _client(STRANGER).get("/bank-statements", params={"business_id": BIZ}).status_code == 403
    assert _client(READER).post("/bank-statements/read", data={"business_id": BIZ},
                                files={"file": ("feb.csv", CHASE, "text/csv")}).status_code == 403


def test_the_owner_uploads_a_csv_and_adds_it(db):
    c = _client(OWNER)
    read = c.post("/bank-statements/read", data={"business_id": BIZ}, files={"file": ("feb.csv", CHASE, "text/csv")})
    assert read.status_code == 200, read.text
    got = read.json()
    assert got["kind"] == "csv" and got["account_id"] == "acc_books" and got["check"]["state"] == "balanced"
    assert [r["state"] for r in got["rows"]] == ["new"] * 3 and db.t["bank_statement_imports"] == []
    part = got["parts"][got["part"]]
    body = {"business_id": BIZ, "account_id": got["account_id"], "file_name": got["file_name"], "kind": got["kind"],
            "rows": part["rows"], "opening": part["opening"], "closing": part["closing"]}
    rechecked = c.post("/bank-statements/check", json=body)
    assert rechecked.status_code == 200 and rechecked.json()["counts"]["new"] == 3
    added = c.post("/bank-statements", json=body)
    assert added.status_code == 200 and added.json()["added"] == 3
    gone = c.delete(f"/bank-statements/{added.json()['import']['id']}", params={"business_id": BIZ})
    assert gone.status_code == 200 and db.t["bank_statement_imports"] == []


def test_off_is_a_404_and_a_failed_read_a_503(db, monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/bank_statement_imports") else db.get(path))
    assert _client(OWNER).get("/bank-statements", params={"business_id": BIZ}).status_code == 503
    monkeypatch.setenv("BANK_STATEMENTS", "off")
    assert _client(OWNER).get("/bank-statements", params={"business_id": BIZ}).status_code == 404


# ─── Chief ───────────────────────────────────────────────────────────

def test_chief_names_the_feed_the_statements_and_whats_missing(db):
    _feb_and_mar(db)
    got = _run(bs.handle_bank_history, {"year": 2026})
    assert not got.get("failed"), got
    text = got["result"]
    assert "Business Checking ending 4417: the bank feed starts Jul 17, 2026." in text
    assert "Feb 1, 2026 to Feb 28, 2026 (2 rows, adds up)" in text
    assert "Still missing from 2026: Jan 1, 2026 to Jan 31, 2026; Apr 1, 2026 to Jul 16, 2026." in text
    assert got["nav"]["txView"] == "statements"


def test_chief_never_reads_the_bank_history_for_a_stranger(db):
    got = _run(bs.handle_bank_history, {}, who=STRANGER)
    assert got["failed"] and "result" in got and "label" in got


def test_the_verb_is_wired():
    import action_registry
    import chief_tool_loop
    assert cos.ACTION_HANDLERS["bank_history"] is bs.handle_bank_history
    assert action_registry.REGISTRY["bank_history"]["chief_only"] is True
    assert "bank_history" in {t["name"] for t in chief_tool_loop.read_tool_definitions()}
    import chief_prompt
    assert '"type":"bank_history"' in chief_prompt.__dict__.get("CHIEF_ACTIONS", "") or \
        '"type":"bank_history"' in open(chief_prompt.__file__, encoding="utf-8").read().replace("{{", "{")
