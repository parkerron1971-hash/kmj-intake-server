"""Phase F.2 v1 — Plaid categorization + reconciliation + router smoke tests.

Focused on the pure-Python logic that lives in our process. Plaid SDK
calls + Stripe live calls are out of scope here (covered manually +
in dev-server smoke).
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from plaid_categorization import (
    BUCKET_TAX, BUCKET_OWNER_PAY, BUCKET_OPERATING,
    BUCKET_SAVINGS, BUCKET_OTHER, ALL_BUCKETS,
    map_plaid_to_bucket, is_income_category,
)
from plaid_reconciliation import (
    _amounts_match, try_match_transaction,
    DATE_TOLERANCE_DAYS, AMOUNT_TOLERANCE_CENTS,
)


# ─── Categorization ──────────────────────────────────────────────────


def test_buckets_constant_matches_check_constraint():
    """ALL_BUCKETS must be exactly the migration's CHECK list. Drift
    here means business_category writes will 400 in prod."""
    assert set(ALL_BUCKETS) == {"tax", "owner_pay", "operating", "savings", "other"}


def test_tax_payment_maps_to_tax_bucket():
    assert map_plaid_to_bucket(
        "GOVERNMENT_AND_NON_PROFIT",
        "GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT",
    ) == BUCKET_TAX


def test_savings_transfer_maps_to_savings():
    assert map_plaid_to_bucket(
        "TRANSFER_OUT", "TRANSFER_OUT_SAVINGS",
    ) == BUCKET_SAVINGS


def test_retirement_transfer_maps_to_savings():
    assert map_plaid_to_bucket(
        "TRANSFER_OUT", "TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS",
    ) == BUCKET_SAVINGS


def test_owner_withdrawal_maps_to_owner_pay():
    assert map_plaid_to_bucket(
        "TRANSFER_OUT", "TRANSFER_OUT_WITHDRAWAL",
    ) == BUCKET_OWNER_PAY


def test_general_merchandise_maps_to_operating():
    assert map_plaid_to_bucket("GENERAL_MERCHANDISE", None) == BUCKET_OPERATING


def test_travel_maps_to_operating():
    assert map_plaid_to_bucket("TRAVEL", None) == BUCKET_OPERATING


def test_loan_payment_maps_to_operating():
    assert map_plaid_to_bucket(
        "LOAN_PAYMENTS", "LOAN_PAYMENTS_MORTGAGE_PAYMENT",
    ) == BUCKET_OPERATING


def test_bank_fees_map_to_operating():
    assert map_plaid_to_bucket("BANK_FEES", None) == BUCKET_OPERATING
    assert map_plaid_to_bucket(
        "BANK_FEES", "BANK_FEES_OVERDRAFT_FEES",
    ) == BUCKET_OPERATING


def test_unknown_category_falls_back_to_other():
    assert map_plaid_to_bucket("PURPLE_MARTIANS", "X_Y_Z") == BUCKET_OTHER
    assert map_plaid_to_bucket(None, None) == BUCKET_OTHER


def test_case_insensitive_lookup():
    assert map_plaid_to_bucket("general_merchandise", None) == BUCKET_OPERATING
    assert map_plaid_to_bucket(
        "transfer_out", "transfer_out_savings",
    ) == BUCKET_SAVINGS


def test_income_categories_flagged_correctly():
    assert is_income_category("INCOME", None) is True
    assert is_income_category("INCOME", "INCOME_WAGES") is True
    assert is_income_category("TRANSFER_IN", None) is True
    assert is_income_category(
        "GOVERNMENT_AND_NON_PROFIT", "GOVERNMENT_AND_NON_PROFIT_TAX_REFUND",
    ) is True
    # Outflows are NOT income.
    assert is_income_category("GENERAL_MERCHANDISE", None) is False
    assert is_income_category("BANK_FEES", "BANK_FEES_ATM_FEES") is False
    assert is_income_category(None, None) is False


# ─── Reconciliation: amount matching ─────────────────────────────────


def test_amounts_match_exact_cents():
    # plaid amount in dollars, payout in cents.
    assert _amounts_match(-127.43, 12743) is True
    assert _amounts_match(127.43, 12743) is True  # abs() either side


def test_amounts_match_one_cent_tolerance():
    # ±1 cent absorbs Plaid float-rounding edge.
    assert _amounts_match(-127.43, 12744) is True
    assert _amounts_match(-127.43, 12742) is True


def test_amounts_match_rejects_two_cent_drift():
    assert _amounts_match(-127.43, 12745) is False


def test_amounts_match_rejects_wrong_amount():
    assert _amounts_match(-127.43, 50000) is False


def test_tolerance_constants_sane():
    # Sanity: ±2 day window, ±1 cent amount. If these change someone
    # bumped them deliberately or accidentally — fail loudly so the
    # change shows up in code review.
    assert DATE_TOLERANCE_DAYS == 2
    assert AMOUNT_TOLERANCE_CENTS == 1


# ─── Reconciliation: try_match_transaction guards ────────────────────


def test_try_match_skips_pending():
    """Pending transactions must not be reconciled — their amount /
    date can change before settlement."""
    tx = {
        "transaction_id": "tx1",
        "business_id": "biz1",
        "amount": -100.0,
        "date": "2026-06-01",
        "pending": True,
        "reconciliation_status": "unmatched",
    }
    assert try_match_transaction(tx) is None


def test_try_match_skips_already_matched():
    """auto_matched, manual_matched, ignored all skip."""
    for status in ("auto_matched", "manual_matched", "ignored"):
        tx = {
            "transaction_id": "tx1",
            "business_id": "biz1",
            "amount": -100.0,
            "date": "2026-06-01",
            "pending": False,
            "reconciliation_status": status,
        }
        assert try_match_transaction(tx) is None


def test_try_match_skips_missing_business():
    tx = {"transaction_id": "tx1", "amount": -100.0, "date": "2026-06-01"}
    assert try_match_transaction(tx) is None


def test_try_match_outflow_matches_outbound_transfer(monkeypatch):
    """Positive amount = outflow in Plaid sign. Since F.1, outflows match
    against PAID outbound contractor transfers (±2d/±1c) and set
    reconciled_to_transfer_id; with no candidate transfers, no match."""
    import sb_clients
    tx = {
        "transaction_id": "tx1",
        "business_id": "biz1",
        "amount": 100.0,  # outflow (in Plaid sign)
        "date": "2026-06-01",
        "pending": False,
        "reconciliation_status": "unmatched",
    }
    # No candidate transfers → no match.
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [])
    assert try_match_transaction(tx) is None
    # A paid transfer with matching amount in the window → auto-match.
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: (
        [{"stripe_transfer_id": "tr_1", "amount": 100.0}]
        if "outbound_transfers" in path else []))
    patch = try_match_transaction(tx)
    assert patch == {"reconciled_to_transfer_id": "tr_1",
                     "reconciliation_status": "auto_matched"}


# ─── Router shape (registration + auth gating) ──────────────────────


def test_plaid_router_registered():
    """All v1 endpoints exist on the router."""
    from plaid_router import router
    paths = {(r.path, tuple(sorted(r.methods or set())))
             for r in router.routes if hasattr(r, "path")}
    expected = [
        ("/plaid/link-token",       ("POST",)),
        ("/plaid/exchange",         ("POST",)),
        ("/plaid/sync",             ("POST",)),
        ("/plaid/webhook",          ("POST",)),
        ("/plaid/items",            ("GET",)),
        ("/plaid/accounts",         ("GET",)),
        ("/plaid/transactions",     ("GET",)),
        ("/plaid/summary",          ("GET",)),
        ("/plaid/category-rules",   ("GET",)),
        ("/plaid/category-rules",   ("POST",)),
    ]
    for path_method in expected:
        assert path_method in paths, f"missing route: {path_method}"


def test_create_link_token_requires_owner(monkeypatch):
    """Non-owner gets 403 before any Plaid call fires."""
    import asyncio
    from fastapi import HTTPException
    import sb_clients
    from plaid_router import create_link_token, LinkTokenBody

    monkeypatch.setattr(
        sb_clients, "sb_get_as_service",
        lambda path: [{"id": "biz1", "name": "Foo", "owner_id": "other"}],
    )

    class _U:
        id = "not-owner"

    body = LinkTokenBody(business_id="biz1")
    with pytest.raises(HTTPException) as exc:
        create_link_token(body, user=_U())
    assert exc.value.status_code == 403


def test_client_name_brands_as_business():
    """Plaid Link's client_name must reflect the active business so the
    onboarding reads "connect to Royal Barbers", not the platform."""
    from plaid_router import _client_name_for, _PLATFORM_CLIENT_NAME

    assert _client_name_for({"name": "Royal Barbers"}) == "Royal Barbers"
    assert _client_name_for({"name": "KMJ Creative Solutions"}) == "KMJ Creative Solutions"
    # Whitespace-only / missing / None fall back to the platform name.
    assert _client_name_for({"name": "   "}) == _PLATFORM_CLIENT_NAME
    assert _client_name_for({}) == _PLATFORM_CLIENT_NAME
    assert _client_name_for(None) == _PLATFORM_CLIENT_NAME


def test_included_account_ids_filters(monkeypatch):
    """_included_account_ids returns only the account ids PostgREST hands
    back for the included+not-removed query, dropping empty ids."""
    import sb_clients
    from plaid_router import _included_account_ids

    captured = {}

    def _fake_get(path):
        captured["path"] = path
        return [{"account_id": "acc_a"}, {"account_id": "acc_b"}, {"account_id": None}]

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _fake_get)
    ids = _included_account_ids("biz1")
    assert ids == ["acc_a", "acc_b"]
    # Must constrain on both the include flag and the soft-delete marker.
    assert "included_in_bookkeeping=eq.true" in captured["path"]
    assert "deleted_at=is.null" in captured["path"]


def test_account_in_clause_shape():
    from plaid_router import _account_in_clause
    assert _account_in_clause(["a", "b", "c"]) == "account_id=in.(a,b,c)"


def test_remove_account_requires_owner(monkeypatch):
    """Non-owner cannot soft-remove someone else's account."""
    from fastapi import HTTPException
    import sb_clients
    from plaid_router import remove_account

    # account lookup returns a row owned by 'other'; owner check then 403s.
    monkeypatch.setattr(
        sb_clients, "sb_get_as_service",
        lambda path: (
            [{"account_id": "acc1", "business_id": "biz1", "item_id": "it1", "deleted_at": None}]
            if path.startswith("/plaid_accounts")
            else [{"id": "biz1", "name": "Foo", "owner_id": "other"}]
        ),
    )
    monkeypatch.setattr(
        sb_clients, "sb_patch_as_service",
        lambda path, body: pytest.fail("must not write on non-owner"),
    )

    class _U:
        id = "not-owner"

    with pytest.raises(HTTPException) as exc:
        remove_account("acc1", user=_U())
    assert exc.value.status_code == 403


def test_reconcile_skips_when_no_included_accounts(monkeypatch):
    """With every account excluded/removed, reconciliation is a no-op."""
    import sb_clients
    import plaid_reconciliation

    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [])
    monkeypatch.setattr(
        sb_clients, "sb_patch_as_service",
        lambda path, body: pytest.fail("must not patch when nothing included"),
    )
    assert plaid_reconciliation.reconcile_business("biz1") == (0, 0)


def test_bucket_clause_handles_uncategorized():
    """5-bucket multi-select with the synthetic 'uncategorized' must build a
    PostgREST predicate spanning NULL + named buckets."""
    from plaid_router import _bucket_clause

    assert _bucket_clause(["operating", "tax"]) == "business_category=in.(operating,tax)"
    assert _bucket_clause(["uncategorized"]) == "business_category=is.null"
    assert _bucket_clause(["uncategorized", "tax"]) == \
        "or=(business_category.is.null,business_category.in.(tax))"
    # Unknown bucket names are dropped.
    assert _bucket_clause(["bogus"]) is None


def test_sanitize_search_strips_grammar_chars():
    from plaid_router import _sanitize_search
    # Parens/commas/stars/dots that would break or=()/ilike are removed.
    assert _sanitize_search("Stripe") == "Stripe"
    assert _sanitize_search("coffee shop") == "coffee%20shop"
    assert _sanitize_search("a,b)(c*.") == "abc"


def test_bulk_categorize_validates_bucket(monkeypatch):
    """Invalid bucket → 400 before any write."""
    from fastapi import HTTPException
    import sb_clients
    from plaid_router import bulk_categorize, BulkCategorizeBody

    monkeypatch.setattr(
        sb_clients, "sb_get_as_service",
        lambda path: [{"id": "biz1", "name": "Foo", "owner_id": "owner"}],
    )
    monkeypatch.setattr(
        sb_clients, "sb_patch_as_service",
        lambda path, body: pytest.fail("must not patch on invalid bucket"),
    )

    class _U:
        id = "owner"

    body = BulkCategorizeBody(business_id="biz1", transaction_ids=["t1"], business_category="bogus")
    with pytest.raises(HTTPException) as exc:
        bulk_categorize(body, user=_U())
    assert exc.value.status_code == 400


def test_bulk_categorize_counts_updated_rows(monkeypatch):
    """Updated count reflects the representation returned by the single
    atomic PATCH."""
    import sb_clients
    from plaid_router import bulk_categorize, BulkCategorizeBody

    captured = {}

    def _fake_patch(path, body):
        captured["path"] = path
        return [{"transaction_id": "t1"}, {"transaction_id": "t2"}]

    monkeypatch.setattr(
        sb_clients, "sb_get_as_service",
        lambda path: [{"id": "biz1", "name": "Foo", "owner_id": "owner"}],
    )
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", _fake_patch)

    class _U:
        id = "owner"

    body = BulkCategorizeBody(business_id="biz1", transaction_ids=["t1", "t2"], business_category="operating")
    out = bulk_categorize(body, user=_U())
    assert out == {"ok": True, "updated": 2}
    # Single request scoped to business + the id set (atomic).
    assert "transaction_id=in.(t1,t2)" in captured["path"]
    assert "business_id=eq.biz1" in captured["path"]


def test_update_transaction_requires_owner(monkeypatch):
    from fastapi import HTTPException
    import sb_clients
    from plaid_router import update_transaction, TxPatchBody

    monkeypatch.setattr(
        sb_clients, "sb_get_as_service",
        lambda path: (
            [{"transaction_id": "t1", "business_id": "biz1"}]
            if path.startswith("/plaid_transactions")
            else [{"id": "biz1", "name": "Foo", "owner_id": "other"}]
        ),
    )
    monkeypatch.setattr(
        sb_clients, "sb_patch_as_service",
        lambda path, body: pytest.fail("must not write on non-owner"),
    )

    class _U:
        id = "not-owner"

    with pytest.raises(HTTPException) as exc:
        update_transaction("t1", TxPatchBody(excluded_from_books=True), user=_U())
    assert exc.value.status_code == 403


def test_recon_date_floor_mapping():
    from plaid_router import _recon_date_floor
    assert _recon_date_floor(None) is None
    assert _recon_date_floor("all") is None
    # mtd → first of month; ytd → Jan 1; rolling windows → a date string.
    assert _recon_date_floor("mtd").endswith("-01")
    assert _recon_date_floor("ytd").endswith("-01-01")
    assert len(_recon_date_floor("30d")) == 10
    assert _recon_date_floor("bogus") is None


def test_match_rejects_payout_bound_to_other_tx(monkeypatch):
    """Idempotency / corruption guard: matching a payout already linked to a
    DIFFERENT transaction returns 409 and writes nothing."""
    from fastapi import HTTPException
    import sb_clients
    from plaid_router import reconciliation_match, MatchBody

    def _fake_get(path):
        if path.startswith("/businesses"):
            return [{"id": "biz1", "name": "Foo", "owner_id": "owner"}]
        if "reconciled_to_payout_id=eq." in path:
            # payout already matched to a different deposit
            return [{"transaction_id": "OTHER_TX"}]
        if path.startswith("/plaid_transactions"):
            return [{"transaction_id": "t1", "business_id": "biz1"}]
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _fake_get)
    monkeypatch.setattr(
        sb_clients, "sb_patch_as_service",
        lambda path, body: pytest.fail("must not write when payout is taken"),
    )

    class _U:
        id = "owner"

    body = MatchBody(business_id="biz1", plaid_transaction_id="t1", stripe_payout_id="po_1")
    with pytest.raises(HTTPException) as exc:
        reconciliation_match(body, user=_U())
    assert exc.value.status_code == 409


def test_match_idempotent_for_same_pair(monkeypatch):
    """Re-matching the SAME pair is allowed (idempotent) and writes the link."""
    import sb_clients
    from plaid_router import reconciliation_match, MatchBody

    captured = {}

    def _fake_get(path):
        if path.startswith("/businesses"):
            return [{"id": "biz1", "name": "Foo", "owner_id": "owner"}]
        if "reconciled_to_payout_id=eq." in path:
            return [{"transaction_id": "t1"}]  # same tx → no conflict
        if path.startswith("/plaid_transactions"):
            return [{"transaction_id": "t1", "business_id": "biz1"}]
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _fake_get)
    monkeypatch.setattr(
        sb_clients, "sb_patch_as_service",
        lambda path, body: captured.update({"path": path, "body": body}),
    )

    class _U:
        id = "owner"

    body = MatchBody(business_id="biz1", plaid_transaction_id="t1", stripe_payout_id="po_1",
                     payout_amount=42.0, payout_date="2026-06-01")
    out = reconciliation_match(body, user=_U())
    assert out == {"ok": True}
    assert captured["body"]["reconciliation_status"] == "manual_matched"
    assert captured["body"]["reconciled_payout_amount"] == 42.0


def test_upsert_rule_validates_bucket_name(monkeypatch):
    """Invalid 5-bucket name → 400 before DB write."""
    from fastapi import HTTPException
    import sb_clients
    from plaid_router import upsert_rule, RuleBody

    monkeypatch.setattr(
        sb_clients, "sb_get_as_service",
        lambda path: [{"id": "biz1", "name": "Foo", "owner_id": "owner"}],
    )
    # Should not fire because validation rejects first.
    monkeypatch.setattr(
        sb_clients, "sb_post_as_service",
        lambda path, body: pytest.fail("must not insert on invalid bucket"),
    )

    class _U:
        id = "owner"

    body = RuleBody(
        business_id="biz1",
        merchant_name="Acme Coffee",
        business_category="nonsense",
    )
    with pytest.raises(HTTPException) as exc:
        upsert_rule(body, user=_U())
    assert exc.value.status_code == 400
