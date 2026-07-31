"""
test_chief_expense_actions.py — the expense verbs (S10 gap-close).

What actually needs proving:

  1. CATEGORY VALIDATION — the 5-bucket vocabulary is a DB CHECK
     constraint and feeds the Allocator; an unknown category must be
     rejected with the valid list, obvious spellings must normalize,
     and a missing category takes the UI form's own default (operating).
  2. LOCKED PERIODS — a delete (or edit, or backdated create) into a
     CLOSED accounting period is refused, and the DB call never fires.
  3. GL SHAPE PARITY — the row log_expense inserts must produce the same
     journal entries through gl_engine.desired_for_expense as a
     UI-created row: balanced lines, the right expense code per bucket,
     vendor in the memo. Field names asserted against the ACTUAL insert
     payload, not a copy of it.
  4. The house contract — result + label on every path, failures via
     "failed": True.
"""
import asyncio

import chief_expense_actions as cea
import chief_of_staff as cos
import gl_engine
from plaid_categorization import ALL_BUCKETS


def _biz():
    return {"id": "biz-1", "owner_id": "user-1", "name": "Test Biz",
            "type": "coach", "settings": {}}


def _unlock(monkeypatch):
    monkeypatch.setattr(cea.period_lock, "locked_period", lambda b, d: None)


_PERIOD = {"id": "p1", "period_type": "month", "status": "closed",
           "period_start": "2026-06-01", "period_end": "2026-06-30"}


def _lock_all(monkeypatch):
    monkeypatch.setattr(cea.period_lock, "locked_period", lambda b, d: dict(_PERIOD))


def _capture_post(monkeypatch, calls):
    def fake_post(path, body, prefer="return=representation"):
        calls.append((path, body))
        return [{**body, "id": "exp-1"}]
    monkeypatch.setattr(cea.sb_clients, "sb_post_as_service", fake_post)


# ─────────────────────────────────────────────────────────────────────
# log_expense — category validation
# ─────────────────────────────────────────────────────────────────────

def test_unknown_category_is_rejected_with_the_valid_list(monkeypatch):
    calls = []
    _capture_post(monkeypatch, calls)
    _unlock(monkeypatch)
    r = asyncio.run(cea.handle_log_expense(None, _biz(), {
        "amount": 40, "category": "groceries"}))
    assert cos._action_failed(r)
    assert r.get("label")
    for bucket in ALL_BUCKETS:
        assert bucket in r["result"], f"rejection must list '{bucket}'"
    assert not calls, "a rejected category must not insert anything"


def test_category_spellings_normalize(monkeypatch):
    calls = []
    _capture_post(monkeypatch, calls)
    _unlock(monkeypatch)
    for raw, want in (("Owner Pay", "owner_pay"), ("taxes", "tax"),
                      ("SAVINGS", "savings"), ("operating", "operating")):
        calls.clear()
        r = asyncio.run(cea.handle_log_expense(None, _biz(), {
            "amount": 10, "category": raw}))
        assert not cos._action_failed(r), f"{raw} should be accepted"
        assert calls[0][1]["category"] == want


def test_missing_category_defaults_to_operating_like_the_ui_form(monkeypatch):
    calls = []
    _capture_post(monkeypatch, calls)
    _unlock(monkeypatch)
    r = asyncio.run(cea.handle_log_expense(None, _biz(), {"amount": 25}))
    assert not cos._action_failed(r)
    assert calls[0][1]["category"] == "operating"
    assert "Operating" in r["result"]     # the default is SAID, not hidden


def test_amount_must_be_a_positive_number(monkeypatch):
    calls = []
    _capture_post(monkeypatch, calls)
    _unlock(monkeypatch)
    for bad in (None, "abc", 0, -5):
        r = asyncio.run(cea.handle_log_expense(None, _biz(), {"amount": bad}))
        assert cos._action_failed(r)
        assert isinstance(r.get("result"), str) and r.get("label")
    assert not calls


def test_bad_date_is_rejected_not_guessed(monkeypatch):
    calls = []
    _capture_post(monkeypatch, calls)
    _unlock(monkeypatch)
    r = asyncio.run(cea.handle_log_expense(None, _biz(), {
        "amount": 10, "date": "yesterday"}))
    assert cos._action_failed(r)
    assert "YYYY-MM-DD" in r["result"]
    assert not calls


# ─────────────────────────────────────────────────────────────────────
# Locked accounting periods
# ─────────────────────────────────────────────────────────────────────

def test_delete_refuses_inside_a_locked_period(monkeypatch):
    _lock_all(monkeypatch)
    monkeypatch.setattr(cea.sb_clients, "sb_get_as_service", lambda p: [
        {"id": "exp-1", "business_id": "biz-1", "amount": 45,
         "category": "operating", "vendor": "Shell", "date": "2026-06-15"}])
    deleted = []
    monkeypatch.setattr(cea.sb_clients, "sb_delete_as_service",
                        lambda p: deleted.append(p) or True)

    r = asyncio.run(cea.handle_delete_expense(None, _biz(), {"expense_id": "exp-1"}))
    assert cos._action_failed(r)
    assert r.get("label")
    assert "closed" in r["result"].lower()
    assert "2026-06-01" in r["result"]        # names the period
    assert not deleted, "the DELETE must never fire on a locked date"


def test_update_refuses_when_row_date_is_locked(monkeypatch):
    _lock_all(monkeypatch)
    monkeypatch.setattr(cea.sb_clients, "sb_get_as_service", lambda p: [
        {"id": "exp-1", "business_id": "biz-1", "amount": 45,
         "category": "operating", "date": "2026-06-15"}])
    patched = []
    monkeypatch.setattr(cea.sb_clients, "sb_patch_as_service",
                        lambda p, b: patched.append((p, b)) or [{}])

    r = asyncio.run(cea.handle_update_expense(None, _biz(), {
        "expense_id": "exp-1", "amount": 54}))
    assert cos._action_failed(r)
    assert "closed" in r["result"].lower()
    assert not patched


def test_log_expense_refuses_a_backdated_locked_date(monkeypatch):
    _lock_all(monkeypatch)
    calls = []
    _capture_post(monkeypatch, calls)
    r = asyncio.run(cea.handle_log_expense(None, _biz(), {
        "amount": 10, "date": "2026-06-15"}))
    assert cos._action_failed(r)
    assert "closed" in r["result"].lower()
    assert not calls


def test_delete_succeeds_outside_locked_periods(monkeypatch):
    _unlock(monkeypatch)
    monkeypatch.setattr(cea.sb_clients, "sb_get_as_service", lambda p: [
        {"id": "exp-1", "business_id": "biz-1", "amount": 45,
         "category": "operating", "vendor": "Shell", "date": "2026-07-15"}])
    deleted = []
    monkeypatch.setattr(cea.sb_clients, "sb_delete_as_service",
                        lambda p: deleted.append(p) or True)

    r = asyncio.run(cea.handle_delete_expense(None, _biz(), {"expense_id": "exp-1"}))
    assert not cos._action_failed(r)
    assert "$45.00" in r["result"] and "Shell" in r["result"]
    assert len(deleted) == 1
    # scoped delete — the URL carries BOTH the id and the business
    assert "id=eq.exp-1" in deleted[0] and "business_id=eq.biz-1" in deleted[0]


# ─────────────────────────────────────────────────────────────────────
# GL shape parity — the row Chief writes is the row the ledger expects
# ─────────────────────────────────────────────────────────────────────

def test_logged_expense_flows_to_gl_like_a_ui_row(monkeypatch):
    """Feed the ACTUAL insert payload through desired_for_expense — the
    same generator the gl_sync_queue trigger path runs — and require a
    balanced entry with the right code, vendor and subcategory."""
    calls = []
    _capture_post(monkeypatch, calls)
    _unlock(monkeypatch)
    r = asyncio.run(cea.handle_log_expense(None, _biz(), {
        "amount": 45, "category": "operating", "vendor": "Shell",
        "subcategory": "fuel", "note": "gas", "date": "2026-07-30"}))
    assert not cos._action_failed(r)

    row = {**calls[0][1], "id": "exp-1"}
    specs = gl_engine.desired_for_expense(row)
    assert len(specs) == 1
    spec = specs[0]
    assert spec["source_type"] == "expense"
    assert spec["entry_date"] == "2026-07-30"
    lines = spec["lines"]
    assert round(sum(l["debit"] for l in lines), 2) == \
           round(sum(l["credit"] for l in lines), 2) == 45.0
    debit = next(l for l in lines if l["debit"])
    credit = next(l for l in lines if l["credit"])
    assert debit["code"] == gl_engine._BUCKET_TO_EXPENSE["operating"]
    assert credit["code"] == "1000"
    assert debit["vendor"] == "Shell"
    assert debit["subcategory"] == "fuel"
    assert "Shell" in debit["memo"]


def test_insert_shape_matches_the_ui_and_the_gl_fetch(monkeypatch):
    """Two parity checks on field NAMES: nothing outside the UI shape
    (+vendor, which the GL reads), and every column the GL's live-sync
    fetch selects is one we can populate."""
    calls = []
    _capture_post(monkeypatch, calls)
    _unlock(monkeypatch)
    asyncio.run(cea.handle_log_expense(None, _biz(), {
        "amount": 45, "category": "tax", "vendor": "IRS",
        "subcategory": "q3", "note": "estimated payment"}))
    payload = calls[0][1]
    ui_shape = {"business_id", "amount", "category", "subcategory",
                "description", "date", "vendor"}
    assert set(payload) <= ui_shape, f"unexpected columns: {set(payload) - ui_shape}"
    # the live-sync fetch for business_expenses selects these:
    gl_select = gl_engine._SOURCE_FETCH["business_expenses"]
    for col in ("amount", "category", "subcategory", "vendor", "date"):
        assert col in gl_select and col in payload


def test_every_bucket_maps_to_a_real_expense_code():
    for bucket in ALL_BUCKETS:
        specs = gl_engine.desired_for_expense({
            "id": "x", "amount": 10, "category": bucket, "date": "2026-07-01"})
        assert specs, f"bucket {bucket} produced no GL entry"
        debit = next(l for l in specs[0]["lines"] if l["debit"])
        assert debit["code"], f"bucket {bucket} has no expense account code"


# ─────────────────────────────────────────────────────────────────────
# list / update — contract and filters
# ─────────────────────────────────────────────────────────────────────

def test_list_expenses_totals_and_filters(monkeypatch):
    seen = []

    def fake_get(path):
        seen.append(path)
        return [
            {"id": "e1", "amount": 30, "category": "operating",
             "vendor": "Shell", "date": "2026-07-30"},
            {"id": "e2", "amount": 12.5, "category": "operating",
             "description": "parking", "date": "2026-07-29"},
        ]
    monkeypatch.setattr(cea.sb_clients, "sb_get_as_service", fake_get)

    r = asyncio.run(cea.handle_list_expenses(None, _biz(), {
        "month": "2026-07", "category": "operating"}))
    assert not cos._action_failed(r)
    assert "$42.50" in r["result"]
    assert "Shell" in r["result"]
    assert r.get("label")
    q = seen[0]
    assert "date=gte.2026-07-01" in q and "date=lt.2026-08-01" in q
    assert "category=eq.operating" in q
    assert "business_id=eq.biz-1" in q


def test_list_expenses_rejects_bad_month_and_category(monkeypatch):
    monkeypatch.setattr(cea.sb_clients, "sb_get_as_service", lambda p: [])
    r = asyncio.run(cea.handle_list_expenses(None, _biz(), {"month": "July"}))
    assert cos._action_failed(r) and r.get("label")
    r = asyncio.run(cea.handle_list_expenses(None, _biz(), {"category": "misc"}))
    assert cos._action_failed(r) and r.get("label")


def test_list_expenses_empty_state(monkeypatch):
    monkeypatch.setattr(cea.sb_clients, "sb_get_as_service", lambda p: [])
    r = asyncio.run(cea.handle_list_expenses(None, _biz(), {}))
    assert not cos._action_failed(r)
    assert isinstance(r.get("result"), str) and r.get("label")


def test_update_expense_validates_and_patches(monkeypatch):
    _unlock(monkeypatch)
    monkeypatch.setattr(cea.sb_clients, "sb_get_as_service", lambda p: [
        {"id": "exp-1", "business_id": "biz-1", "amount": 45,
         "category": "operating", "vendor": "Shell", "date": "2026-07-15"}])
    patched = []
    monkeypatch.setattr(cea.sb_clients, "sb_patch_as_service",
                        lambda p, b: patched.append((p, b)) or [{"id": "exp-1"}])

    r = asyncio.run(cea.handle_update_expense(None, _biz(), {
        "expense_id": "exp-1", "amount": 54, "category": "Owner Pay"}))
    assert not cos._action_failed(r)
    assert r.get("label")
    path, body = patched[0]
    assert "id=eq.exp-1" in path and "business_id=eq.biz-1" in path
    assert body["amount"] == 54.0
    assert body["category"] == "owner_pay"


def test_update_expense_rejects_unknown_category_before_patching(monkeypatch):
    _unlock(monkeypatch)
    monkeypatch.setattr(cea.sb_clients, "sb_get_as_service", lambda p: [
        {"id": "exp-1", "business_id": "biz-1", "amount": 45,
         "category": "operating", "date": "2026-07-15"}])
    patched = []
    monkeypatch.setattr(cea.sb_clients, "sb_patch_as_service",
                        lambda p, b: patched.append((p, b)) or [{}])
    r = asyncio.run(cea.handle_update_expense(None, _biz(), {
        "expense_id": "exp-1", "category": "fun"}))
    assert cos._action_failed(r)
    assert not patched


def test_update_and_delete_require_an_id(monkeypatch):
    for handler, verb in ((cea.handle_update_expense, "update_expense"),
                          (cea.handle_delete_expense, "delete_expense")):
        r = asyncio.run(handler(None, _biz(), {}))
        assert cos._action_failed(r)
        assert r["type"] == verb
        assert "list_expenses" in r["result"]   # tells them how to find it
        assert r.get("label")


# ─────────────────────────────────────────────────────────────────────
# Registry classification
# ─────────────────────────────────────────────────────────────────────

def test_expense_verbs_are_classified_as_specified():
    import action_registry as reg
    assert reg.reversibility("log_expense") == "A"
    assert reg.effect("list_expenses") == reg.READ
    assert not reg.is_sensitive("list_expenses")
    assert reg.reversibility("update_expense") == "C"
    assert reg.reversibility("delete_expense") == "C"
    assert not reg.is_bulk("update_expense")
    assert not reg.is_bulk("delete_expense")
