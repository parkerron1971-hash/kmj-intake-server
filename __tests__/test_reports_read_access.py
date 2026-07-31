# __tests__/test_reports_read_access.py
#
# Rails Arc 5 — the financial read surface. Pins:
#   * _owner_or_reader admits owner / active accountant / any active
#     team seat, and 403s strangers
#   * the four owner-only holdouts (budget writes, outward sends, and
#     the TIN-decrypting draft PDF) still require the owner
#   * every report GET goes through the reader gate (source sweep)

import pathlib
import re
from unittest import mock

import pytest
from fastapi import HTTPException

import reports_router


_BIZ_ROW = [{"id": "biz-1", "name": "Clean Quick", "owner_id": "owner-1", "settings": {}}]


class _U:
    def __init__(self, uid):
        self.id = uid
        self.email = f"{uid}@x.test"


def _with_business(fn):
    return mock.patch.object(reports_router.sb_clients, "sb_get_as_service",
                             return_value=list(_BIZ_ROW))


def test_owner_passes():
    with _with_business(None):
        row = reports_router._owner_or_reader("biz-1", _U("owner-1"))
    assert row["id"] == "biz-1"


def test_active_accountant_passes():
    with _with_business(None), \
         mock.patch("business_collaborators_router.is_active_accountant", return_value=True):
        row = reports_router._owner_or_reader("biz-1", _U("cpa-9"))
    assert row["id"] == "biz-1"


def test_team_viewer_passes():
    with _with_business(None), \
         mock.patch("business_collaborators_router.is_active_accountant", return_value=False), \
         mock.patch("business_users_router.role_of", return_value="viewer"):
        row = reports_router._owner_or_reader("biz-1", _U("staff-2"))
    assert row["id"] == "biz-1"


def test_stranger_is_403():
    with _with_business(None), \
         mock.patch("business_collaborators_router.is_active_accountant", return_value=False), \
         mock.patch("business_users_router.role_of", return_value=None):
        with pytest.raises(HTTPException) as exc:
            reports_router._owner_or_reader("biz-1", _U("nobody"))
    assert exc.value.status_code == 403


def _source():
    return (pathlib.Path(reports_router.__file__)).read_text(encoding="utf-8")


def _fn_body(src: str, name: str) -> str:
    m = re.search(rf"\ndef {name}\(.*?(?=\n@router|\ndef |\Z)", src, re.S)
    assert m, f"function {name} not found"
    return m.group(0)


def test_writes_carry_their_matrix_ranks():
    """7/31 seat-access matrix (Kevin-approved) supersedes the Arc 5
    owner-only holdouts: budgets + customer statements are MEMBER work,
    the accountant package send escalates to MANAGER — and the
    TIN-decrypting 1099 draft stays OWNER ONLY, forever."""
    src = _source()
    body = _fn_body(src, "draft_1099_pdf")
    assert "_owner(biz, user)" in body, "1099 draft lost its owner gate"
    assert "require_role" not in body, "the TIN surface must never open to seats"
    body = _fn_body(src, "put_budgets")
    assert 'require_role(biz, str(user.id), "member")' in body
    for fn, rank in (("accountant_send", "manager"),
                     ("customer_statement_send", "member")):
        body = re.search(rf"\nasync def {fn}\(.*?(?=\n@router|\ndef |\nasync def |\Z)",
                         src, re.S).group(0)
        assert f'require_role(biz, str(user.id), "{rank}")' in body, \
            f"{fn} must gate at {rank}"


def test_report_reads_go_through_the_reader_gate():
    src = _source()
    n = src.count("_owner_or_reader(biz, user)")
    # 24 report GETs swapped in Arc 5 — a hard floor so a refactor that
    # quietly reverts reads to owner-only fails here.
    assert n >= 20, f"expected >=20 reader-gated endpoints, found {n}"
