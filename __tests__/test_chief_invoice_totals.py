"""
test_chief_invoice_totals.py — the invoice arithmetic is done once, in code (2026-09-23).

Kevin typed "Which of my invoices are overdue right now, and who owes me
the most?" and waited 46 s for "No action ran in this request … try
again?". The log, five times that evening: `claim number has no evidence
:: $115 combined …`, `… 95 days overdue`, `claim number 265 is not in the
quote :: Five invoices are overdue right now, totaling $265`, and a
recovery that counted "Six". The rows held amounts and due dates; the
answer did sums, counts and date math no evidence contained.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos
import chief_truth as truth

KMJ = [  # KMJ's real open invoices on 2026-09-24
    {"number": "INV-2026-010", "client": "Kevin McCloud", "total": 5.0, "status": "sent", "due_date": "2026-06-20"},
    {"number": "INV-2026-008", "client": "Kevin McCloud", "total": 5.0, "status": "sent", "due_date": "2026-06-20"},
    {"number": "INV-2026-009", "client": "Kevin McCloud", "total": 5.0, "status": "sent", "due_date": "2026-06-20"},
    {"number": "INV-2026-007", "client": "Monica Walton", "total": 150.0, "status": "sent", "due_date": "2026-07-15"},
    {"number": "INV-2026-012", "client": "Kevin McCloud", "total": 100.0, "status": "sent", "due_date": "2026-09-01"},
    {"number": "INV-2026-013", "client": "Demetrio Dockery", "total": 55.0, "status": "draft", "due_date": "2026-10-02"},
    {"number": "INV-2026-014", "client": "Jessica McCloud", "total": 10.0, "status": "sent", "due_date": "2026-10-02"},
]


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(cos, "_invoice_today", lambda: dt.date(2026, 9, 24))
    rows = cos._with_days_overdue([dict(r) for r in KMJ])
    return {"open_invoices": rows, "invoice_summary": cos._invoice_summary_lines(rows)}


def test_the_totals_match_the_dashboard(ctx):
    lines = ctx["invoice_summary"]
    assert lines[0].startswith("As of 2026-09-24: 5 invoices overdue, $265.00 in total")
    assert "Sent and unpaid: 6 invoices, $275.00" in lines[1]
    # Who owes the most: Monica's one invoice, not Kevin's four small ones.
    owes = [l for l in lines if " owes " in l]
    assert owes[0].startswith("Monica Walton owes $150.00")
    assert owes[1].startswith("Kevin McCloud owes $115.00 across 4 invoices")


def test_a_draft_is_never_overdue(ctx):
    draft = next(r for r in ctx["open_invoices"] if r["status"] == "draft")
    assert draft["days_overdue"] == 0
    assert next(r for r in ctx["open_invoices"] if r["number"] == "INV-2026-010")["days_overdue"] == 96


def test_the_summary_reaches_the_answer_check(ctx):
    sources = truth.evidence_for_review(ctx, "", [])
    assert "context:invoice_summary" in sources
    claim = "Five invoices are overdue right now, totaling $265"
    quote = "5 invoices overdue, $265.00 in total"
    review = json.dumps({"verdict": "supported", "claims": [
        {"text": claim, "kind": "fact", "source_id": "context:invoice_summary", "quote": quote}]})
    verdict, cited, reason = truth.assess_review(review, claim + ".", sources)
    assert verdict == "supported", reason


def test_the_summary_survives_a_full_context(ctx):
    fat = {k: "x" * 10000 for k in ("blueprint_block", "playbook_block", "brand_block",
                                     "voice_block", "foundation_block", "practitioner_block")}
    sources = truth.evidence_for_review({**fat, **ctx}, "", [])
    assert "context:invoice_summary" in sources and "context:open_invoices" in sources


def test_the_prompt_tells_chief_to_quote_the_totals(ctx):
    import inspect
    src = inspect.getsource(cos)
    assert "OPEN INVOICES — TOTALS" in src and "never add them up yourself" in src


def test_no_invoices_no_summary():
    assert cos._invoice_summary_lines([]) == []


def test_a_withheld_answer_after_opening_a_page_says_what_was_left_out():
    import asyncio
    from unittest.mock import AsyncMock
    nav = {"type": "navigate", "result": "opened", "label": "Opened BUILD → strategy-track"}
    reviewer = AsyncMock(return_value=json.dumps({"verdict": "unsupported", "claims": [
        {"text": "96 days", "kind": "fact", "source_id": "", "quote": "", "gap": "no source"}]}))
    out, meta = asyncio.run(truth.finalize_reply(
        None, "Price it at $450. Your three test invoices are 96 days late.", ctx={},
        view_detail="", taken=[nav], message="help me price the intensive",
        business_id="biz", reviewer=reviewer))
    assert out.startswith("Opened BUILD → strategy-track")
    assert "left the rest of my answer out" in out and "try again" not in out
