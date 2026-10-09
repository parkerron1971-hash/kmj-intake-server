"""
test_chief_queue_total.py — Chief and the answer check know how many drafts are waiting (2026-10-08).

A salon owner asked "What steps do I need to do next?" three times and got
"No action ran in this request. I couldn't verify my proposed answer" every
time. Her Approvals held 40 check-in drafts. Chief's queue read stops at 10
rows, so its answer said "Review the 10 check-in drafts waiting in Approvals";
the answer check found no 10 in any record, rightly, and held the whole answer
back. The prompt now carries the exact count of drafts waiting, and the
answer check reads its record of the queue under that same heading, so "40
drafts" quotes its evidence and "10 drafts" still has none.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as chief
import chief_prompt
import chief_truth as truth
import onboarding_welcome
from __tests__.test_gather_context_wave2 import gather  # noqa: F401  (fixture)

NAMES = ("Kendrick Armstrong", "Sheryl Coleman", "Ashley Jordan", "Joy Cooper", "Shijuan Kelly",
         "Maya", "Alicia Smith", "Fedisa", "LaToya Wright", "Tiyanna Williams")
# Her real rows' shape: no figures but the ids and the day they were drafted.
ROWS = [{"id": f"7f3c{i}e2a-9b1d-4c6e-a1f0-{i}d4e5f6a7b8c", "agent": "nurture",
         "action_type": "check_in", "subject": f"Checking in, {name}", "priority": "medium",
         "contact_id": f"c{i}a8e1f2-3b4c-4d5e-8f9a-0b1c2d3e4f5a",
         "created_at": "2026-09-30T11:03:04.485789+00:00"} for i, name in enumerate(NAMES)]
WHOLE = "QUEUE (40 drafts waiting for review in all; the rows below are only the first few, not all of them)"


# ── The total ─────────────────────────────────────────────────────────

def test_a_page_under_the_limit_is_its_own_total():
    assert chief._queue_total(ROWS[:4], ROWS[:4], None, None) == 4
    assert chief._queue_total([], [], None, None) == 0


def test_a_full_page_takes_the_exact_count():
    assert chief._queue_total(ROWS, ROWS, 40, 0) == 40


def test_the_welcome_note_is_not_counted():
    page = ROWS[:9] + [{"agent": onboarding_welcome.AGENT, "ai_reasoning": onboarding_welcome.REASONING}]
    assert chief._queue_total(page, ROWS[:9], 41, 1) == 40


def test_without_a_count_a_full_page_has_no_total():
    assert chief._queue_total(ROWS, ROWS, None, 0) is None
    assert chief._queue_total(ROWS, ROWS, 40, None) is None
    assert chief._queue_total(None, [], 40, 0) == 40


def test_the_total_never_says_fewer_than_the_rows_shown():
    # A draft approved between the two reads.
    assert chief._queue_total(ROWS, ROWS, 9, 0) == 10


def test_the_welcome_count_matches_the_row_exactly():
    path = chief._queue_count_path("biz-1", welcome=True)
    assert "status=eq.draft" in path and "agent=eq.system" in path
    # Percent-encoded and unquoted: PostgREST keeps the quotes of a plain eq.
    assert "ai_reasoning=eq.Standard%20welcome%20message" in path and '"' not in path
    assert "agent=" not in chief._queue_count_path("biz-1")


# ── The heading ───────────────────────────────────────────────────────

def test_a_known_total_is_in_the_heading():
    ctx = {"queue": ROWS, "queue_total": 40, "queue_complete": False}
    assert chief.queue_heading_line(ctx) == WHOLE
    # The sample's size is not: it was the wrong figure.
    assert "10" not in chief.queue_count_heading(ctx)


def test_a_complete_list_keeps_its_words():
    ctx = {"queue": ROWS[:3], "queue_total": 3, "queue_complete": True}
    assert chief.queue_heading_line(ctx) == "QUEUE (3 drafts waiting for review; this list is complete)"
    ctx = {"queue": ROWS[:1], "queue_total": 1, "queue_complete": True}
    assert chief.queue_heading_line(ctx) == "QUEUE (1 draft waiting for review; this list is complete)"


def test_a_full_page_that_is_every_draft_is_complete():
    ctx = {"queue": ROWS, "queue_total": 10, "queue_complete": False}
    assert chief.queue_heading_line(ctx) == "QUEUE (10 drafts waiting for review; this list is complete)"


def test_an_unknown_total_stays_a_sample():
    ctx = {"queue": ROWS, "queue_total": None, "queue_complete": False}
    assert chief.queue_count_heading(ctx) is None
    assert chief.queue_heading_line(ctx) == "QUEUE (10 loaded draft rows; sample, not a total)"


# ── The context ───────────────────────────────────────────────────────

def _drafts_waiting(monkeypatch, total, welcome=0):
    original = chief._sb

    async def rows(client, method, path, body=None):
        if path.startswith('/agent_queue?') and 'status=eq.draft' in path:
            return [dict(r) for r in ROWS]
        return await original(client, method, path, body)

    async def count(client, path, *, allow_service_fallback=False):
        if path.startswith('/agent_queue?') and 'status=eq.draft' in path:
            return welcome if 'ai_reasoning=eq.' in path else total
        return None
    monkeypatch.setattr(chief, '_sb', rows)
    monkeypatch.setattr(chief.sb_clients, 'sb_count_as_current_context', count)


def test_the_prompt_says_how_many_are_waiting(gather, monkeypatch):
    _drafts_waiting(monkeypatch, 41, welcome=1)
    _, ctx = gather(query_text=None)
    assert ctx["queue_total"] == 40 and ctx["queue_complete"] is False
    prompt = chief._format_context_for_prompt(ctx)
    assert "\n" + WHOLE + ":\n" in prompt
    assert "10 loaded draft rows" not in prompt


def test_a_failed_count_leaves_the_sample_as_it_was(gather, monkeypatch):
    _drafts_waiting(monkeypatch, None)
    _, ctx = gather(query_text=None)
    assert ctx["queue_total"] is None
    assert "(10 loaded draft rows; sample, not a total)" in chief._format_context_for_prompt(ctx)


def test_the_greeting_counts_every_draft():
    ctx = {"queue": ROWS, "queue_total": 40}
    assert "40 waiting for your review." in chief_prompt._build_daily_priorities({}, ctx)
    assert "10 waiting for your review." in chief_prompt._build_daily_priorities({}, {"queue": ROWS})


# ── The answer check ──────────────────────────────────────────────────

def _evidence(total, complete=False):
    ctx = {"queue": ROWS, "queue_total": total, "queue_complete": complete}
    return truth.evidence_for_review(ctx, "", [])


def test_the_check_reads_the_queue_under_its_count():
    record = json.loads(_evidence(40)["context:queue"]["text"])
    assert record["heading"] == WHOLE and len(record["rows"]) == 10


def test_an_unknown_count_gives_the_check_no_heading():
    assert json.loads(_evidence(None)["context:queue"]["text"]) == ROWS


def _review(claim, quote):
    return json.dumps({"verdict": "supported", "claims": [
        {"text": claim, "kind": "fact", "source_id": "context:queue", "quote": quote}]})


def test_the_whole_count_now_checks_out():
    draft = "Review the 40 check-in drafts waiting in Approvals."
    raw = _review("the 40 check-in drafts waiting in Approvals", "40 drafts waiting for review in all")
    verdict, cited, reason = truth.assess_review(raw, draft, _evidence(40))
    assert verdict == "supported", reason
    assert cited == ["context:queue"]


def test_the_sample_size_still_has_no_evidence():
    draft = "Review the 10 check-in drafts waiting in Approvals."
    raw = _review("the 10 check-in drafts waiting in Approvals", "40 drafts waiting for review in all")
    verdict, _, reason = truth.assess_review(raw, draft, _evidence(40))
    assert verdict == "unsupported" and "10" in reason
