# __tests__/test_quickbooks_bridge.py
#
# Rails Arc 1a — the QuickBooks bridge's mapping layer. Pins:
#   1. the IIF export resolves account names through coa_external_mappings
#      (mapped name out, our name as fallback, one ACCNT row per external
#      name even when two codes map to it)
#   2. the /quickbooks routes exist and are auth-dependent

from unittest import mock

import accountant_export


_ACCOUNTS = [
    {"code": "1000", "name": "Cash", "type": "asset"},
    {"code": "5100", "name": "Contractors", "type": "expense"},
    {"code": "5200", "name": "Software", "type": "expense"},
]

_JES = [
    {"id": "je1", "entry_date": "2026-03-05", "description": "Pay contractor",
     "source_type": "bill", "is_reversal": False},
]

_LINES = [
    {"journal_entry_id": "je1", "account_code": "5100", "debit": 250, "credit": 0, "memo": ""},
    {"journal_entry_id": "je1", "account_code": "1000", "debit": 0, "credit": 250, "memo": ""},
]


def _fake_sb_get(path: str):
    if path.startswith("/chart_of_accounts"):
        return _ACCOUNTS
    if path.startswith("/journal_entries"):
        return _JES
    if path.startswith("/ledger_entries"):
        return _LINES
    if path.startswith("/coa_external_mappings"):
        return [
            {"account_code": "5100", "external_name": "Subcontractor Expense",
             "external_id": None, "external_type": None},
        ]
    return []


def test_iif_uses_mapped_names_and_falls_back():
    with mock.patch.object(accountant_export.sb_clients, "sb_get_as_service", _fake_sb_get):
        iif = accountant_export.build_iif("biz-1", 2026)

    # Mapped: 5100 exports under the accountant's name, ours is absent.
    assert "Subcontractor Expense" in iif
    assert "Contractors" not in iif
    # Unmapped: falls back to our names.
    assert "ACCNT\tCash\tBANK" in iif
    assert "ACCNT\tSoftware\tEXP" in iif
    # Transaction lines resolve through the same mapping.
    assert "TRNS\tGENERAL JOURNAL\t03/05/2026\tSubcontractor Expense\t250.00" in iif
    assert "SPL\tGENERAL JOURNAL\t03/05/2026\tCash\t-250.00" in iif


def test_iif_defines_each_external_account_once():
    def both_mapped(path: str):
        if path.startswith("/coa_external_mappings"):
            return [
                {"account_code": "5100", "external_name": "Operating Costs",
                 "external_id": None, "external_type": None},
                {"account_code": "5200", "external_name": "Operating Costs",
                 "external_id": None, "external_type": None},
            ]
        return _fake_sb_get(path)

    with mock.patch.object(accountant_export.sb_clients, "sb_get_as_service", both_mapped):
        iif = accountant_export.build_iif("biz-1", 2026)

    accnt_rows = [l for l in iif.splitlines()
                  if l.startswith("ACCNT\t") and "Operating Costs" in l]
    assert len(accnt_rows) == 1


_QBO_LIST = [
    {"id": "35", "name": "Checking", "type": "Bank"},
    {"id": "77", "name": "Contract Labor", "type": "Expense"},
    {"id": "80", "name": "Advertising & Marketing", "type": "Expense"},
    {"id": "45", "name": "Sales", "type": "Income"},
    {"id": "90", "name": "Software", "type": "Expense"},
]


def test_suggest_exact_name_wins():
    from quickbooks_router import suggest_qbo_match

    s = suggest_qbo_match({"code": "5200", "name": "Software", "type": "expense"}, _QBO_LIST)
    assert s and s["external_id"] == "90" and s["confidence"] == 1.0


def test_suggest_knows_qbo_vocabulary():
    from quickbooks_router import suggest_qbo_match

    cash = suggest_qbo_match({"code": "1000", "name": "Cash", "type": "asset"}, _QBO_LIST)
    assert cash and cash["external_name"] == "Checking"

    sub = suggest_qbo_match({"code": "5100", "name": "Contractors", "type": "expense"}, _QBO_LIST)
    assert sub and sub["external_name"] == "Contract Labor"

    mkt = suggest_qbo_match({"code": "5300", "name": "Marketing", "type": "expense"}, _QBO_LIST)
    assert mkt and mkt["external_name"] == "Advertising & Marketing"


def test_suggest_never_crosses_account_classes():
    from quickbooks_router import suggest_qbo_match

    # An income account must never be suggested an Expense match even
    # when the names are identical.
    s = suggest_qbo_match({"code": "4000", "name": "Software", "type": "income"},
                          [{"id": "90", "name": "Software", "type": "Expense"}])
    assert s is None


def test_suggest_stays_quiet_below_confidence():
    from quickbooks_router import suggest_qbo_match

    s = suggest_qbo_match({"code": "3900", "name": "Zebra Fund", "type": "expense"}, _QBO_LIST)
    assert s is None


def test_activity_aggregation():
    from quickbooks_router import _activity_by_code

    a = _activity_by_code([
        {"account_code": "1000", "debit": 100, "credit": 0},
        {"account_code": "1000", "debit": 0, "credit": 40},
        {"account_code": "5100", "debit": 250, "credit": 0},
    ])
    assert a["1000"] == {"entries": 2, "volume": 140.0}
    assert a["5100"] == {"entries": 1, "volume": 250.0}


def test_quickbooks_routes_exist_and_require_auth():
    from quickbooks_router import router, connect_router
    from auth_supabase import require_user

    by_path = {}
    for r in router.routes:
        by_path.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "GET" in by_path.get("/quickbooks/mappings", set())
    assert "PUT" in by_path.get("/quickbooks/mappings", set())
    assert "GET" in by_path.get("/quickbooks/status", set())
    assert "DELETE" in by_path.get("/quickbooks/disconnect", set())
    assert "POST" in by_path.get("/quickbooks/sync-accounts", set())
    assert "POST" in by_path.get("/quickbooks/push", set())

    # Everything under /quickbooks is authed. The OAuth entry/callback
    # (connect_router) are browser redirects — unauthenticated by
    # design, protected by the signed state instead.
    for r in router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"

    connect_paths = {r.path for r in connect_router.routes}
    assert "/connect/quickbooks" in connect_paths
    assert "/connect/quickbooks/callback" in connect_paths


def test_oauth_state_round_trips_and_rejects_tampering():
    from quickbooks_router import _make_state, _verify_state

    with mock.patch.dict("os.environ", {"QB_CLIENT_SECRET": "test-secret"}):
        state = _make_state("biz-123")
        assert _verify_state(state) == "biz-123"
        assert _verify_state(state + "x") is None
        body, sig = state.split(".", 1)
        assert _verify_state(f"{body}0.{sig}") is None
        assert _verify_state("") is None


def test_qbo_journal_payload_shape_and_docnumber_cap():
    from quickbooks_router import _build_qbo_journal, DOCNUMBER_MAX

    je = {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
          "entry_date": "2026-03-05", "description": "Pay contractor"}
    lines = [
        {"account_code": "5100", "debit": 250, "credit": 0, "memo": "labor"},
        {"account_code": "1000", "debit": 0, "credit": 250, "memo": ""},
    ]
    payload = _build_qbo_journal(je, lines, {"5100": "77", "1000": "35"})

    assert payload["TxnDate"] == "2026-03-05"
    assert len(payload["DocNumber"]) <= DOCNUMBER_MAX
    assert payload["DocNumber"].startswith("SOL-")
    debit, credit = payload["Line"]
    assert debit["Amount"] == 250 and credit["Amount"] == 250
    assert debit["JournalEntryLineDetail"]["PostingType"] == "Debit"
    assert credit["JournalEntryLineDetail"]["PostingType"] == "Credit"
    assert debit["JournalEntryLineDetail"]["AccountRef"]["value"] == "77"
    assert credit["JournalEntryLineDetail"]["AccountRef"]["value"] == "35"


def test_qbo_journal_refuses_unmapped_accounts_by_name():
    import pytest
    from quickbooks_router import _build_qbo_journal

    je = {"id": "je1", "entry_date": "2026-03-05", "description": ""}
    lines = [
        {"account_code": "5100", "debit": 250, "credit": 0, "memo": ""},
        {"account_code": "1000", "debit": 0, "credit": 250, "memo": ""},
    ]
    with pytest.raises(ValueError) as exc:
        _build_qbo_journal(je, lines, {"5100": "77"})  # 1000 unmapped
    assert "1000" in str(exc.value)
