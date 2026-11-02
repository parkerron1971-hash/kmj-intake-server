# __tests__/test_bank_data_reader_access.py
#
# Seat-access arc follow-up — bank-data reads join the financial-read
# tier (#337 covered gl/periods/contractors/campaigns/reports; plaid +
# bills were the two routers left owner-only, which made an accountant
# who could read the P&L unable to open the transactions behind it).
#
# Pins, both directions:
#   * _require_reader admits owner / accountant / team seat, 403s strangers
#   * every plaid GET goes through the reader gate; every write still
#     goes through _require_owner (linking and unlinking a bank) or
#     _require_money_writer (the owner, or a church's Admin: the
#     bookkeeping writes, 2026-11-01), never the reader gate (source sweep
#     with a hard floor)

import pathlib
import re
from unittest import mock

import pytest
from fastapi import HTTPException

import plaid_router
import bills_router


_BIZ = [{"id": "biz-1", "name": "Clean Quick", "owner_id": "owner-1"}]


class _U:
    def __init__(self, uid):
        self.id = uid


def test_reader_admits_owner_accountant_and_seat():
    with mock.patch.object(plaid_router.sb_clients, "sb_get_as_service", return_value=list(_BIZ)):
        assert plaid_router._require_reader("biz-1", _U("owner-1"))["id"] == "biz-1"

    with mock.patch.object(plaid_router.sb_clients, "sb_get_as_service", return_value=list(_BIZ)), \
         mock.patch("business_collaborators_router.is_active_accountant", return_value=True):
        assert plaid_router._require_reader("biz-1", _U("cpa-9"))["id"] == "biz-1"

    with mock.patch.object(plaid_router.sb_clients, "sb_get_as_service", return_value=list(_BIZ)), \
         mock.patch("business_collaborators_router.is_active_accountant", return_value=False), \
         mock.patch("business_users_router.require_role", return_value="viewer"):
        assert plaid_router._require_reader("biz-1", _U("staff-2"))["id"] == "biz-1"


def test_reader_403s_strangers():
    def deny(*a, **k):
        raise HTTPException(403, "requires viewer access or above")

    with mock.patch.object(plaid_router.sb_clients, "sb_get_as_service", return_value=list(_BIZ)), \
         mock.patch("business_collaborators_router.is_active_accountant", return_value=False), \
         mock.patch("business_users_router.require_role", side_effect=deny):
        with pytest.raises(HTTPException) as exc:
            plaid_router._require_reader("biz-1", _U("nobody"))
    assert exc.value.status_code == 403


def _fn_bodies(module) -> dict:
    src = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"\n(?:async )?def (\w+)\(.*?(?=\n@router|\n(?:async )?def |\Z)", src, re.S):
        out[m.group(1)] = m.group(0)
    return out


def test_plaid_reads_are_reader_gated_and_writes_stay_owner():
    bodies = _fn_bodies(plaid_router)

    reads = ["list_items", "list_accounts", "list_transactions", "get_transaction",
             "cash_flow_summary", "list_rules", "reconciliation_summary",
             "reconciliation_matches", "reconciliation_unmatched",
             "reconciliation_suggestions", "reconciliation_export"]
    for fn in reads:
        assert "_require_reader" in bodies[fn], f"{fn} is not reader-gated"

    owner_only = ["create_link_token", "exchange_public_token", "relink", "unlink",
                  "update_account", "remove_account"]
    for fn in owner_only:
        assert "_require_owner" in bodies[fn], f"{fn} lost its owner gate"
        assert "_require_money_writer" not in bodies[fn], f"{fn} opened past the owner"
        assert "_require_reader(" not in bodies[fn], f"{fn} opened to readers"

    money_writes = ["sync_business", "update_transaction", "bulk_categorize", "bulk_exclude",
                    "upsert_rule", "delete_rule", "reconciliation_match", "reconciliation_unmatch",
                    "reconciliation_ignore", "reconciliation_run"]
    for fn in money_writes:
        assert "_require_money_writer" in bodies[fn], f"{fn} lost its writer gate"
        assert "_require_reader(" not in bodies[fn], f"{fn} opened to readers"

    # Hard floor: the reader gate covers at least the 11 reads above, so
    # a refactor can't quietly revert them.
    src = pathlib.Path(plaid_router.__file__).read_text(encoding="utf-8")
    assert src.count("_require_reader(biz, user)") >= 10


def test_bills_list_is_reader_gated_and_writes_stay_owner():
    bodies = _fn_bodies(bills_router)
    assert "_reader(biz, user)" in bodies["list_bills"]
    # Every write takes _writer: the owner, or a church's Admin (2026-11-01).
    for fn in ("create_bill", "update_bill", "mark_paid", "delete_bill"):
        assert "_writer(" in bodies[fn] or "_writer_for_bill(" in bodies[fn], f"{fn} lost its gate"
        assert "_reader(" not in bodies[fn], f"{fn} opened to readers"
