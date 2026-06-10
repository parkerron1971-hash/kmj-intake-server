"""Phase G v1.5 — LLM-in-loop Chief (mocked Claude; trust pipeline intact)."""
from __future__ import annotations

import asyncio
import json
import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import chief_bookkeeping as cb  # noqa: E402
import chief_llm  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": "biz1", "type": "lawyer", "owner_id": "owner"})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("CHIEF_LLM", raising=False)
    return fb


def _tx(fb, tid, amount, *, merchant="Mystery Vendor", cat=None, primary=None):
    fb.rows("plaid_transactions").append({
        "transaction_id": tid, "business_id": "biz1", "account_id": "a1",
        "amount": amount, "date": "2026-06-05", "pending": False,
        "excluded_from_books": False, "name": merchant, "merchant_name": merchant,
        "business_category": cat, "business_subcategory": None,
        "plaid_category_primary": primary, "plaid_category_detail": None,
        "reconciliation_status": "unmatched", "reconciled_to_payout_id": None,
    })


def _acct(fb):
    fb.rows("plaid_accounts").append({
        "account_id": "a1", "business_id": "biz1", "type": "depository",
        "included_in_bookkeeping": True, "deleted_at": None, "last_balance": 0})


def test_voice_fragment_per_archetype():
    law = chief_llm.voice_fragment("lawyer")
    assert "formal" in law.lower()
    coach = chief_llm.voice_fragment("coach")
    assert "warm" in coach.lower()
    np_ = chief_llm.voice_fragment("nonprofit")
    assert "donor" in np_.lower() or "steward" in np_.lower()


def test_llm_kill_switch(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CHIEF_LLM", "off")
    assert chief_llm.llm_enabled() is False
    monkeypatch.delenv("CHIEF_LLM", raising=False)
    assert chief_llm.llm_enabled() is True
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert chief_llm.llm_enabled() is False


def test_parse_json_tolerant():
    assert chief_llm._parse_json('{"a": 1}') == {"a": 1}
    assert chief_llm._parse_json('```json\n[{"b": 2}]\n```') == [{"b": 2}]
    assert chief_llm._parse_json('Sure! {"a": 1} hope that helps') == {"a": 1}
    assert chief_llm._parse_json("no json here") is None
    assert chief_llm._parse_json(None) is None


def test_suppressed_categorizations_and_deterministic_loop(fake):
    fb = fake
    for _ in range(2):
        cb.capture_learning_signal("biz1", "propose_categorize",
                                   {"business_category": "savings"},
                                   {"business_category": "operating"}, "never savings")
    assert chief_llm.suppressed_categorizations("biz1") == {"savings"}
    # Deterministic analyzer now skips the suppressed bucket.
    _acct(fb)
    _tx(fb, "t1", 80.0, primary="TRANSFER_OUT_SAVINGS")  # maps → savings
    import plaid_categorization as pc
    if pc.map_plaid_to_bucket("TRANSFER_OUT_SAVINGS", None) == "savings":
        created = cb.analyze_uncategorized("biz1")
        assert created == []


def test_learning_digest_compact(fake):
    cb.capture_learning_signal("biz1", "propose_categorize",
                               {"business_category": "other"},
                               {"business_category": "operating"}, "software is operating")
    lines = chief_llm.learning_digest("biz1")
    assert lines and len(lines) <= 6
    assert any("other → operating" in l for l in lines)


def test_analyze_hard_batches_one_call_and_inserts_proposals(fake, monkeypatch):
    fb = fake
    _acct(fb)
    _tx(fb, "t1", 49.0, merchant="Adobe")          # no plaid category → hard case
    _tx(fb, "t2", 1200.0, merchant="Unknown LLC")  # hard case
    _tx(fb, "t3", -50.0, merchant="Deposit")       # inflow → not a candidate
    calls = []

    async def fake_call(business_id, system, user, *, max_tokens, endpoint):
        calls.append({"system": system, "user": user, "endpoint": endpoint})
        return json.dumps([
            {"transaction_id": "t1", "business_category": "operating",
             "business_subcategory": "software", "confidence": 0.95,
             "reasoning": "Adobe is design software."},
            {"transaction_id": "t2", "business_category": "not_a_bucket",
             "confidence": 0.9, "reasoning": "bad"},
            {"transaction_id": "ghost", "business_category": "operating",
             "confidence": 0.9, "reasoning": "hallucinated id"},
        ])
    monkeypatch.setattr(chief_llm, "_call_claude", fake_call)
    out = asyncio.run(chief_llm.analyze_hard("biz1", "lawyer"))
    assert len(calls) == 1                                   # ONE batched call
    assert out["candidates"] == 2
    assert len(out["created"]) == 1                          # invalid bucket + ghost id dropped
    prop = out["created"][0]
    assert prop["proposal_type"] == "propose_categorize"
    assert prop["confidence"] <= 0.75                        # LLM cap
    assert prop["reasoning"].startswith("Chief (AI):")
    assert prop["status"] == "pending"                       # trust pipeline: nothing acted
    # The transaction itself is untouched until approval.
    tx = [t for t in fb.rows("plaid_transactions") if t["transaction_id"] == "t1"][0]
    assert tx["business_category"] is None


def test_ask_transaction_answer_and_proposal(fake, monkeypatch):
    fb = fake
    _acct(fb)
    _tx(fb, "t1", 49.0, merchant="Adobe")

    async def fake_call(business_id, system, user, *, max_tokens, endpoint):
        assert "Voice:" in system                            # archetype voice present
        assert "TRANSACTION:" in user
        return json.dumps({"answer": "This looks like your design software subscription.",
                           "proposal": {"business_category": "operating",
                                        "business_subcategory": "software",
                                        "confidence": 0.9, "reasoning": "Adobe → software."}})
    monkeypatch.setattr(chief_llm, "_call_claude", fake_call)
    out = asyncio.run(chief_llm.ask_transaction("biz1", "lawyer", "t1", "what is this?"))
    assert out["llm"] == "ok" and "design software" in out["answer"]
    assert out["suggestion"]["business_category"] == "operating"
    assert out["suggestion"]["confidence"] <= 0.75
    # Inline suggestion only — NO parallel pending proposal from the drawer.
    assert fb.rows("chief_bookkeeping_proposals") == []


def test_ask_transaction_disabled_graceful(fake, monkeypatch):
    monkeypatch.setenv("CHIEF_LLM", "off")
    out = asyncio.run(chief_llm.ask_transaction("biz1", "lawyer", "t1", None))
    assert out["ok"] is True and out["llm"] == "disabled"


def test_approve_captures_learning_signal(fake):
    fb = fake
    _acct(fb)
    _tx(fb, "t1", 49.0, merchant="Adobe")
    row = cb._insert_proposal("biz1", "propose_categorize",
                              plaid_transaction_id="t1",
                              proposed={"plaid_transaction_id": "t1",
                                        "business_category": "operating",
                                        "business_subcategory": None},
                              confidence=0.7, reasoning="r")
    cb.approve_proposal("biz1", row["id"], approved_by="kevin")
    signals = fb.rows("chief_learning_signals")
    assert len(signals) == 1 and signals[0]["override_reason"] == "approved"
    tx = [t for t in fb.rows("plaid_transactions") if t["transaction_id"] == "t1"][0]
    assert tx["business_category"] == "operating"            # proposal executed
