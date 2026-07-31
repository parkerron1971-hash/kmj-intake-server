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


def test_quickbooks_routes_exist_and_require_auth():
    from quickbooks_router import router
    from auth_supabase import require_user

    by_path = {}
    for r in router.routes:
        by_path.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "GET" in by_path.get("/quickbooks/mappings", set())
    assert "PUT" in by_path.get("/quickbooks/mappings", set())

    for r in router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"
