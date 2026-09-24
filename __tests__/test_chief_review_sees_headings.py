"""
test_chief_review_sees_headings.py — the answer check reads a list under the same heading Chief did (2026-09-24).

Chief's prompt shows the calendar as "UPCOMING SESSIONS (next 7 days):". The
answer check got the bare list, `[]`. "Nothing on the calendar in the next
7 days — your UPCOMING SESSIONS list is empty" was withheld as "claim number
has no evidence" (the 7), and the repair told the owner Chief had no access
to their calendar. The headings that carry figures are now shared constants,
used by the prompt and by the evidence.
"""
from __future__ import annotations

import inspect
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos
import chief_truth as truth


def test_the_prompt_and_the_evidence_share_the_headings():
    src = inspect.getsource(cos._format_context_for_prompt)
    assert "{SESSIONS_HEADING}:" in src and "{AT_RISK_HEADING}:" in src
    assert "next 7 days" in cos.SESSIONS_HEADING and "30+ days quiet" in cos.AT_RISK_HEADING


def test_an_empty_calendar_is_reviewed_under_its_window():
    ev = truth.evidence_for_review({"sessions": [], "at_risk": []}, "", [])
    assert json.loads(ev["context:sessions"]["text"]) == {"heading": cos.SESSIONS_HEADING, "rows": []}
    assert json.loads(ev["context:at_risk"]["text"]) == {"heading": cos.AT_RISK_HEADING, "rows": []}


def test_the_withheld_answer_now_checks_out():
    draft = "Nothing on the calendar in the next 7 days — your UPCOMING SESSIONS list is empty."
    sources = truth.evidence_for_review({"sessions": []}, "", [])
    raw = json.dumps({"verdict": "supported", "claims": [
        {"text": "Nothing on the calendar in the next 7 days", "kind": "fact",
         "source_id": "context:sessions", "quote": "UPCOMING SESSIONS (next 7 days)\", \"rows\": []"},
        {"text": "your UPCOMING SESSIONS list is empty", "kind": "fact",
         "source_id": "context:sessions", "quote": "\"rows\": []"}]})
    verdict, cited, reason = truth.assess_review(raw, draft, sources)
    assert verdict == "supported", reason


def test_each_appointment_is_still_its_own_record():
    sessions = [{"title": "Intake", "scheduled_for": "2026-09-25T15:00:00+00:00", "contacts": {"name": "Tasha"}},
                {"title": "Review", "scheduled_for": "2026-09-26T18:00:00+00:00", "contacts": {"name": "Maria"}}]
    ev = truth.evidence_for_review({"sessions": sessions}, "", [])
    items = truth._record_items(ev["context:sessions"]["text"])
    tasha = [i for i in items if "Tasha" in i]
    assert len(tasha) == 1 and "Maria" not in tasha[0]
    assert any(cos.SESSIONS_HEADING in i for i in items)


def test_other_lists_are_unchanged():
    ev = truth.evidence_for_review({"open_invoices": [{"n": 1}]}, "", [])
    assert json.loads(ev["context:open_invoices"]["text"]) == [{"n": 1}]
