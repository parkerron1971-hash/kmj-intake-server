"""
test_chief_transactions.py — Chief searches the bank and the server adds up.

Kevin, 2026-10-30: asked Chief for the year's total "given to kmj paypal kmj
ministries kevin"; it had counts only and sent him to search the screen.
What this file holds down:

  1. THE SERVER ADDS UP EVERY MATCH, in and out apart, not the rows shown.
  2. PENDING AND EXCLUDED rows are reported, never counted or dropped.
  3. A FAILED READ IS NEVER $0, and past the cap the search refuses.
  4. THE WORDS can't reach the PostgREST grammar or the query string.
  5. WHO MAY: the Transactions screen's reader gate, as the person talking;
     nobody talking means no rows.
  6. CHIEF'S ALONE: sensitive, never on the agent surface, a lookup in the
     turn, kept to the money lane for a church login.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import HTTPException

import action_registry
import chief_of_staff as cos
import chief_transactions as ct


TODAY = date(2026, 10, 30)


def _tx(i, amount, name, *, status="unmatched", pending=False, excluded=False, day="2026-05-01"):
    return {"transaction_id": f"tx{i}", "date": day, "name": name, "merchant_name": None,
            "amount": amount, "pending": pending, "excluded_from_books": excluded,
            "reconciliation_status": status, "business_category": None}


def _args(**kw):
    args, why = ct.parse_args(kw, today=TODAY)
    assert args is not None, why
    return args


# ─── 1. The server adds up ───────────────────────────────────────────

def test_totals_cover_every_match_in_and_out_apart():
    rows = [_tx(i, -100.0, "PAYPAL TRANSFER KMJ MINISTRIES") for i in range(30)]
    rows += [_tx(100, 250.0, "ZELLE TO KEVIN", status="manual_matched")]
    out = ct.summarize(_args(words=["kmj", "kevin"]), ct.tally(rows, ["kmj", "kevin"]))
    t = out["totals"]
    assert t["total"] == {"count": 31, "money_in": 3000.0, "money_out": 250.0}
    assert t["unreconciled"]["count"] == 30 and t["reconciled"]["count"] == 1
    assert t["by_word"]["kmj"]["money_in"] == 3000.0
    assert t["by_word"]["kevin"]["money_out"] == 250.0
    assert len(out["rows"]) == ct.ROWS_SHOWN, "the card shows a sample"
    assert out["summary"]["count"] == 31, "the header counts every match"
    assert "$3,000.00 in and $250.00 out" in out["result"]
    assert "Showing the 25 most recent" in out["result"]


def test_a_row_is_shown_from_the_business_side():
    row = ct.display_row(_tx(1, -40.0, "PAYPAL *KMJMIN"))
    assert row["way"] == "In" and row["amount"] == 40.0 and row["status"] == "—"
    row = ct.display_row(_tx(2, 15.5, "KMJ CREATIVE", status="auto_matched"))
    assert row["way"] == "Out" and row["amount"] == -15.5 and row["status"] == "Yes"


def test_one_direction_puts_its_total_in_the_card_header():
    rows = [_tx(1, -10.0, "kmj"), _tx(2, -5.0, "kmj")]
    out = ct.summarize(_args(words=["kmj"], direction="in"), ct.tally(rows, ["kmj"]))
    assert out["summary"] == {"count": 2, "total": 15.0}
    assert " out" not in out["result"], "only the asked direction is spoken"
    both = ct.summarize(_args(words=["kmj"]), ct.tally(rows, ["kmj"]))
    assert "total" not in both["summary"], "in plus out is not a total"


def test_the_payload_is_a_card_the_app_already_draws():
    out = ct.summarize(_args(), ct.tally([_tx(1, -1.0, "x")], []))
    assert out["type"] == "show_view" and out["view"] == "transactions"
    assert isinstance(out["columns"], list) and out["rows"]
    assert out["label"] and out["result"]


# ─── 2. Pending and excluded ─────────────────────────────────────────

def test_pending_and_excluded_are_reported_not_counted():
    rows = [_tx(1, -100.0, "kmj"), _tx(2, -7.0, "kmj", pending=True), _tx(3, -9.0, "kmj", excluded=True)]
    out = ct.summarize(_args(words=["kmj"]), ct.tally(rows, ["kmj"]))
    assert out["totals"]["total"]["money_in"] == 100.0
    assert "1 still pending at the bank ($7.00 in" in out["result"]
    assert "1 excluded from the books ($9.00 in" in out["result"]


def test_nothing_matched_says_so_and_warns_against_invention():
    out = ct.summarize(_args(words=["nobody"]), ct.tally([], ["nobody"]))
    assert out["result"].startswith("No bank transactions matching 'nobody'")
    assert "never invent" in out["note_for_chief"]


# ─── 3. Failure is not zero ──────────────────────────────────────────

@pytest.fixture(autouse=True)
def switched_on(monkeypatch):
    monkeypatch.setenv("CHIEF_BANK_SEARCH", "on")


@pytest.fixture
def speaker(monkeypatch):
    token = cos._TURN_USER_ID.set("user-1")
    import plaid_router
    monkeypatch.setattr(plaid_router, "_require_reader", lambda biz, user: {"id": biz})
    yield
    cos._TURN_USER_ID.reset(token)


def _serve(monkeypatch, pages):
    """pages: {path prefix: list of responses, consumed in order}."""
    seen = []

    def fake(path, **kw):
        seen.append(path)
        for prefix, queue in pages.items():
            if path.startswith(prefix):
                return queue.pop(0) if queue else []
        raise AssertionError(path)
    monkeypatch.setattr(ct.sb_clients, "sb_get_as_service", fake)
    return seen


def test_a_failed_read_is_never_zero(monkeypatch, speaker):
    _serve(monkeypatch, {"/plaid_accounts": [[{"account_id": "a1"}]], "/plaid_transactions": [None]})
    out = ct.search("biz-1", {"words": ["kmj"]})
    assert out["failed"] and "not a $0 result" in out["result"]


def test_every_page_is_read_until_an_empty_one(monkeypatch, speaker):
    page = [_tx(i, -1.0, "kmj") for i in range(1000)]
    seen = _serve(monkeypatch, {"/plaid_accounts": [[{"account_id": "a1"}]],
                                "/plaid_transactions": [page, page[:3], []]})
    out = ct.search("biz-1", {"words": ["kmj"]})
    assert out["totals"]["total"]["count"] == 1003
    offsets = [p.rsplit("offset=", 1)[1] for p in seen if p.startswith("/plaid_transactions")]
    assert offsets == ["0", "1000", "1003"]


def test_past_the_cap_the_search_refuses(monkeypatch, speaker):
    monkeypatch.setattr(ct, "_ROW_CAP", 5)
    _serve(monkeypatch, {"/plaid_accounts": [[{"account_id": "a1"}]],
                         "/plaid_transactions": [[_tx(i, -1.0, "k") for i in range(6)]]})
    out = ct.search("biz-1", {})
    assert out["failed"] and "Narrow" in out["result"]


def test_no_account_in_the_books_is_not_zero(monkeypatch, speaker):
    _serve(monkeypatch, {"/plaid_accounts": [[]]})
    out = ct.search("biz-1", {})
    assert "No bank account is in the books" in out["result"]
    assert "do not report $0" in out["note_for_chief"]


# ─── 4. The words ────────────────────────────────────────────────────

def test_words_cannot_reach_the_query_grammar():
    words = ct.clean_words(["KMJ", "kmj", "pay(pal)", "a&business_id=eq.x", "o'neil", "*", "x,y.z"])
    # "_" is a LIKE wildcard, so it becomes a space.
    assert words == ["kmj", "paypal", "abusiness ideqx", "o'neil", "xyz"]
    path = ct.query_path("biz-1", ["a1"], _args(words=["kmj ministries"]))
    assert "name.ilike.*kmj%20ministries*" in path
    assert path.count("&business_id=") == 0 and path.count("?business_id=") == 1


def test_query_scopes_dates_direction_and_status():
    path = ct.query_path("biz-1", ["a1", "a2"], _args(direction="out", status="unreconciled",
                                                      date_from="2026-03-01"))
    for part in ("account_id=in.(a1,a2)", "date=gte.2026-03-01", "date=lte.2026-10-30",
                 "amount=gt.0", "reconciliation_status=eq.unmatched"):
        assert part in path


@pytest.mark.parametrize("bad", [{"direction": "sideways"}, {"status": "maybe"},
                                 {"date_from": "last spring"},
                                 {"date_from": "2026-05-01", "date_to": "2026-01-01"}])
def test_bad_arguments_are_refused_in_words(bad):
    args, why = ct.parse_args(bad, today=TODAY)
    assert args is None and why


def test_dates_default_to_the_year_so_far():
    args = _args()
    assert args["date_from"] == date(2026, 1, 1) and args["date_to"] == TODAY


# ─── 5. Who may ──────────────────────────────────────────────────────

def test_nobody_talking_means_no_rows(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no read without a person")
    monkeypatch.setattr(ct.sb_clients, "sb_get_as_service", boom)
    out = ct.search("biz-1", {})
    assert out["failed"] and "signed-in" in out["result"]


def test_the_screens_reader_gate_decides(monkeypatch):
    import plaid_router
    seen = {}

    def refuse(biz, user):
        seen["who"] = (biz, user.id)
        raise HTTPException(403, {"code": "area_locked", "message": "Giving & money is locked."})
    monkeypatch.setattr(plaid_router, "_require_reader", refuse)
    monkeypatch.setattr(ct.sb_clients, "sb_get_as_service",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("read before the gate")))
    token = cos._TURN_USER_ID.set("seat-7")
    try:
        out = ct.search("biz-1", {})
    finally:
        cos._TURN_USER_ID.reset(token)
    assert seen["who"] == ("biz-1", "seat-7")
    assert out["failed"] and out["result"] == "Giving & money is locked."


@pytest.mark.parametrize("value,owned,expected", [
    ("on", False, True), ("owner", True, True), ("owner", False, False), (None, True, True),
    (None, False, False), ("off", True, False), ("nonsense", True, False)])
def test_the_switch(monkeypatch, value, owned, expected):
    import member_asks
    if value is None:
        monkeypatch.delenv("CHIEF_BANK_SEARCH", raising=False)
    else:
        monkeypatch.setenv("CHIEF_BANK_SEARCH", value)
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: owned)
    assert ct.switched_on("biz-1") is expected


def test_switched_off_reads_nothing_and_says_where_to_look(monkeypatch, speaker):
    monkeypatch.setenv("CHIEF_BANK_SEARCH", "off")
    monkeypatch.setattr(ct.sb_clients, "sb_get_as_service",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("read while off")))
    out = ct.search("biz-1", {"words": ["kmj"]})
    assert out["failed"] and "Bookkeeping → Transactions" in out["result"]


# ─── 6. Chief's alone ────────────────────────────────────────────────

def test_bank_rows_never_reach_the_agent_surface():
    import mcp_server
    assert action_registry.effect("search_transactions") == action_registry.READ
    assert not action_registry.may_expose_to_agent("search_transactions")
    assert "search_transactions" not in mcp_server.exposed_tools()
    assert cos.ACTION_HANDLERS["search_transactions"] is ct.handle_search_transactions


def test_it_is_a_lookup_in_the_turn():
    import chief_tool_loop as ctl
    assert "search_transactions" in {t["name"] for t in ctl.read_tool_definitions()}


def test_a_church_login_outside_the_money_lane_is_refused():
    import chief_areas
    assert chief_areas.VERBS["search_transactions"] == chief_areas.MONEY


# ─── 7. Filed is not matched (2026-11-03) ────────────────────────────
# Kevin: why are the rows Chief filed "still under all transactions like we
# didn't do any transaction?" Chief read "Reconciled: No" off every row.

CHURCH_LINES = {"operating": "Ministry & operations", "owner_pay": "Pastor & staff pay", "tax": "Taxes",
                "savings": "Reserves", "other": "Other"}


def _filed(i, amount, name, cat, sub=None, kind=None, status="unmatched"):
    return {**_tx(i, amount, name, status=status), "business_category": cat,
            "business_subcategory": sub, "money_kind": kind}


def test_each_row_says_what_it_is_filed_under_in_the_churchs_words():
    assert ct.filed_as(_filed(1, 112.27, "Comcast", "operating", "Utilities"), CHURCH_LINES) ==         "Ministry & operations · Utilities"
    assert ct.filed_as(_filed(2, 296.0, "DTE ENERGY", "operating"), CHURCH_LINES) == "Ministry & operations"
    assert ct.filed_as(_filed(3, 61.17, "DTE Energy", "other")) == "Waiting"
    assert ct.filed_as(_filed(4, 61.17, "DTE Energy", None)) == "Waiting"
    assert ct.filed_as(_filed(5, -400.0, "City of Love Out SUBSPLASH", None, kind="gifts")) == "Gifts arriving"
    assert ct.filed_as(_filed(6, 50.0, "X", "operating")) == "Operating", "no names: the key, readable"


def test_a_filed_bill_with_nothing_to_match_shows_a_dash_not_no():
    row = ct.display_row(_filed(1, 112.27, "Comcast", "operating", "Utilities"), CHURCH_LINES)
    assert row["filed"] == "Ministry & operations · Utilities" and row["status"] == "—"
    assert ct.display_row(_filed(2, -5.0, "x", None, status="ignored"))["status"] == "Set aside"
    labels = [c["label"] for c in ct.COLUMNS]
    assert "Filed under" in labels and "Matched" in labels and "Reconciled" not in labels


def test_the_totals_count_filed_and_waiting_not_unreconciled():
    rows = [_filed(1, 112.27, "Comcast", "operating", "Utilities"),
            _filed(2, 296.0, "DTE ENERGY", "operating"),
            _filed(3, 61.17, "DTE Energy", "other")]
    out = ct.summarize(_args(), ct.tally(rows, []), CHURCH_LINES)
    assert out["totals"]["filed"]["count"] == 2 and out["totals"]["waiting"]["count"] == 1
    assert "Filed: 2. Still waiting for a category (in To review): 1 ($0.00 in and $61.17 out)" in out["result"]
    assert "Not reconciled" not in out["result"]
    assert "not a to-do list" in out["note_for_chief"]
    assert [r["filed"] for r in out["rows"]] == ["Ministry & operations · Utilities", "Ministry & operations", "Waiting"]


def test_status_waiting_and_filed_are_read_from_the_rows(monkeypatch, speaker):
    rows = [_filed(1, 112.27, "Comcast", "operating", "Utilities"), _filed(2, 61.17, "DTE Energy", "other")]
    for status, want in (("waiting", ["tx2"]), ("filed", ["tx1"])):
        seen = _serve(monkeypatch, {"/plaid_accounts": [[{"account_id": "a1"}]],
                                    "/plaid_transactions": [list(rows), []]})
        out = ct.search("biz-1", {"status": status})
        assert [r["id"] for r in out["rows"]] == want
        assert not any("reconciliation_status" in p.split("select=")[0] for p in seen if p.startswith("/plaid_transactions"))


def test_the_tool_explains_filed_and_matched():
    d = ct.TOOL["description"]
    assert "FILED" in d and "MATCHED" in d and "not a to-do list" in d
    assert ct.TOOL["input_schema"]["properties"]["status"]["enum"] == list(ct.STATUSES)
    assert "waiting" in ct.STATUSES and "filed" in ct.STATUSES

