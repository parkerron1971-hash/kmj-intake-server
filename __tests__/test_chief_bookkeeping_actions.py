"""P0.2 — Chief bookkeeping verbs.

Thin wrappers over chief_bookkeeping, so these tests defend the WRAPPER
contract, not the accounting logic (that is test_phaseg_chief_bookkeeping's
job):
  • result + label on every return (a missing key blanks the app),
  • HTTPExceptions from the engine are contained, not propagated into the
    chat turn,
  • ambiguity over financial records is a question, never a guess,
  • a rejection carrying a correction reaches the learning-signal path,
  • no bulk-approve verb exists.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_bookkeeping_actions as cba

BIZ = {"id": "biz1"}

LINKED = {"linked": True, "unmatched": 2, "unmatched_total": 140.0, "uncategorized": 7}


def _no_analyzers(monkeypatch):
    import chief_bookkeeping as cb
    for name in ("analyze_unmatched", "analyze_uncategorized",
                 "analyze_period_close", "analyze_gl"):
        monkeypatch.setattr(cb, name, lambda b, **kw: [])


# ─── review_books ─────────────────────────────────────────────────────

def test_review_books_reports_state(monkeypatch):
    import chief_bookkeeping as cb
    monkeypatch.setattr(cb, "bookkeeping_counts", lambda b: LINKED)
    _no_analyzers(monkeypatch)
    monkeypatch.setattr(cb, "list_proposals", lambda b, status=None: [{"id": "p1"}])

    out = cba._review_books_sync(BIZ, {})
    assert out["result"] and out["label"]
    assert "2 unmatched" in out["result"]
    assert "7 uncategorized" in out["result"]


def test_review_books_without_a_linked_bank_says_so(monkeypatch):
    import chief_bookkeeping as cb
    monkeypatch.setattr(cb, "bookkeeping_counts", lambda b: {"linked": False})
    out = cba._review_books_sync(BIZ, {})
    assert "no bank account is linked" in out["result"]
    assert out["label"]


def test_review_books_honors_scope(monkeypatch):
    import chief_bookkeeping as cb
    monkeypatch.setattr(cb, "bookkeeping_counts", lambda b: LINKED)
    monkeypatch.setattr(cb, "list_proposals", lambda b, status=None: [])
    called = []
    monkeypatch.setattr(cb, "analyze_uncategorized",
                        lambda b, **kw: called.append("uncat") or [])
    monkeypatch.setattr(cb, "analyze_unmatched",
                        lambda b, **kw: pytest.fail("out-of-scope analyzer ran"))
    monkeypatch.setattr(cb, "analyze_period_close",
                        lambda b, **kw: pytest.fail("out-of-scope analyzer ran"))
    monkeypatch.setattr(cb, "analyze_gl",
                        lambda b, **kw: pytest.fail("out-of-scope analyzer ran"))

    out = cba._review_books_sync(BIZ, {"scope": "uncategorized"})
    assert called == ["uncat"]
    assert out["result"]


def test_review_books_rejects_an_unknown_scope(monkeypatch):
    import chief_bookkeeping as cb
    monkeypatch.setattr(cb, "bookkeeping_counts", lambda b: LINKED)
    out = cba._review_books_sync(BIZ, {"scope": "nonsense"})
    assert "don't have a check called" in out["result"]


def test_one_failing_analyzer_does_not_lose_the_others(monkeypatch):
    import chief_bookkeeping as cb
    monkeypatch.setattr(cb, "bookkeeping_counts", lambda b: LINKED)
    monkeypatch.setattr(cb, "list_proposals", lambda b, status=None: [])
    monkeypatch.setattr(cb, "analyze_unmatched",
                        lambda b, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(cb, "analyze_uncategorized", lambda b, **kw: [{"id": "p1"}])
    monkeypatch.setattr(cb, "analyze_period_close", lambda b, **kw: [])
    monkeypatch.setattr(cb, "analyze_gl", lambda b, **kw: [])

    out = cba._review_books_sync(BIZ, {})
    assert out["new_proposals"] == 1


# ─── listing ──────────────────────────────────────────────────────────

def test_list_summarizes_and_caps(monkeypatch):
    import chief_bookkeeping as cb
    rows = [{"id": f"p{i}", "proposal_type": "propose_categorize",
             "proposed": {"business_category": "operating"}} for i in range(9)]
    monkeypatch.setattr(cb, "list_proposals", lambda b, status=None: rows)

    out = cba._list_proposals_sync(BIZ, {})
    assert out["total"] == 9
    assert len(out["proposals"]) == cba._NAME_LIMIT
    assert "categorize as operating" in out["proposals"][0]["summary"]


def test_list_empty_is_not_an_error(monkeypatch):
    import chief_bookkeeping as cb
    monkeypatch.setattr(cb, "list_proposals", lambda b, status=None: [])
    out = cba._list_proposals_sync(BIZ, {})
    assert out["result"] == "no pending proposals"
    assert out["label"]


def test_describe_degrades_on_an_unexpected_payload():
    """`proposed` shape varies by type — a missing key must read, not raise."""
    assert cba._describe({"proposal_type": "propose_categorize", "proposed": {}})
    assert cba._describe({})


# ─── approve ──────────────────────────────────────────────────────────

def test_approve_applies_and_names_what_it_did(monkeypatch):
    import chief_bookkeeping as cb
    p = {"id": "p1", "proposal_type": "propose_categorize",
         "proposed": {"business_category": "operating"}}
    monkeypatch.setattr(cb, "_get_proposal", lambda b, i: p)
    monkeypatch.setattr(cb, "approve_proposal",
                        lambda b, i, approved_by="": {"executed": "propose_categorize"})

    out = cba._approve_sync(BIZ, {"proposal_id": "p1"})
    assert "categorize as operating" in out["result"]
    assert out["label"] and out["proposal_id"] == "p1"


def test_approve_contains_engine_exceptions(monkeypatch):
    """approve_proposal raises HTTPException on a bad id. Uncontained, that
    500s the whole chat turn instead of failing one action card."""
    import chief_bookkeeping as cb
    from fastapi import HTTPException
    monkeypatch.setattr(cb, "_get_proposal", lambda b, i: {"id": "p1", "proposed": {}})
    monkeypatch.setattr(cb, "approve_proposal",
                        lambda b, i, approved_by="": (_ for _ in ()).throw(
                            HTTPException(404, "proposal not found")))

    out = cba._approve_sync(BIZ, {"proposal_id": "nope"})
    assert out["type"] == "approve_bookkeeping_proposal"
    assert out["result"] and out["label"]


def test_approve_is_idempotent(monkeypatch):
    import chief_bookkeeping as cb
    monkeypatch.setattr(cb, "_get_proposal", lambda b, i: {"id": "p1", "proposed": {}})
    monkeypatch.setattr(cb, "approve_proposal",
                        lambda b, i, approved_by="": {"already": "approved"})
    out = cba._approve_sync(BIZ, {"proposal_id": "p1"})
    assert "already approved" in out["result"]


def test_approve_asks_which_when_several_are_pending(monkeypatch):
    """Over financial records, 'approve it' with four open is ambiguous."""
    import chief_bookkeeping as cb
    rows = [{"id": f"p{i}", "proposal_type": "propose_categorize",
             "proposed": {"business_category": "operating"}} for i in range(4)]
    monkeypatch.setattr(cb, "list_proposals", lambda b, status=None: rows)
    monkeypatch.setattr(cb, "approve_proposal",
                        lambda *a, **k: pytest.fail("must not guess which proposal"))

    out = cba._approve_sync(BIZ, {})
    assert "which one" in out["result"].lower()


def test_approve_resolves_the_only_pending_one(monkeypatch):
    import chief_bookkeeping as cb
    p = {"id": "solo", "proposal_type": "propose_exclude", "proposed": {}}
    monkeypatch.setattr(cb, "list_proposals", lambda b, status=None: [p])
    monkeypatch.setattr(cb, "approve_proposal",
                        lambda b, i, approved_by="": {"executed": "propose_exclude"})
    out = cba._approve_sync(BIZ, {})
    assert out["proposal_id"] == "solo"


def test_approve_with_nothing_pending(monkeypatch):
    import chief_bookkeeping as cb
    monkeypatch.setattr(cb, "list_proposals", lambda b, status=None: [])
    out = cba._approve_sync(BIZ, {})
    assert "no proposals waiting" in out["result"].lower()


# ─── reject ───────────────────────────────────────────────────────────

def test_reject_with_a_correction_reaches_the_learning_path(monkeypatch):
    import chief_bookkeeping as cb
    monkeypatch.setattr(cb, "_get_proposal", lambda b, i: {
        "id": "p1", "proposal_type": "propose_categorize", "proposed": {}})
    seen = {}
    monkeypatch.setattr(cb, "reject_proposal",
                        lambda b, i, override=None, override_reason=None:
                        seen.update(override=override, reason=override_reason))

    out = cba._reject_sync(BIZ, {
        "proposal_id": "p1", "reason": "personal expense",
        "override": {"business_category": "personal"}})

    assert seen["override"] == {"business_category": "personal"}
    assert seen["reason"] == "personal expense"
    assert "noted for next time" in out["result"]


def test_bare_rejection_says_nothing_about_learning(monkeypatch):
    import chief_bookkeeping as cb
    monkeypatch.setattr(cb, "_get_proposal", lambda b, i: {"id": "p1", "proposed": {}})
    monkeypatch.setattr(cb, "reject_proposal",
                        lambda b, i, override=None, override_reason=None: None)
    out = cba._reject_sync(BIZ, {"proposal_id": "p1"})
    assert out["result"] == "rejected"


# ─── wiring ───────────────────────────────────────────────────────────

def test_verbs_registered_documented_and_async():
    import inspect

    import chief_of_staff as cos
    src = pathlib.Path(cos.__file__).read_text(encoding="utf-8")
    for verb in ("review_books", "list_bookkeeping_proposals",
                 "approve_bookkeeping_proposal", "reject_bookkeeping_proposal"):
        assert verb in cos.ACTION_HANDLERS, f"{verb} not registered"
        assert inspect.iscoroutinefunction(cos.ACTION_HANDLERS[verb])
        assert f'"type":"{verb}"' in src, f"{verb} missing from the action catalog"


def test_there_is_no_bulk_approve():
    """Deliberate omission — 'approve everything' over financial records is the
    action a practitioner cannot un-see."""
    import chief_of_staff as cos
    assert "approve_all_bookkeeping" not in cos.ACTION_HANDLERS
    assert not any(k.startswith("bulk_") and "book" in k for k in cos.ACTION_HANDLERS)
