"""
test_empty_lists_are_answers.py — "nothing yet" is an answer when the read came back complete (2026-09-26).

For a business that signed up today, most of what is true is "nothing yet".
The prompt said "(none in the loaded sample; check data availability)" under
QUEUE, PROJECTS and OPEN INVOICES whether the read had come back empty or
never come back, and the answer check reviewed a bare [] under "Incomplete
lists cannot prove totals or absence". "You have no open invoices yet" could
come back as "couldn't verify". The calendar was fixed first (#1034,
test_empty_calendar_is_an_answer.py); this is the same design for every list
a new business sees.

A read that succeeded and came back under its limit is every matching row:
the prompt says so plainly and the answer check may cite it for "none". A
failed read still says to check, never "none", and a claim of absence that
cites it is refused whatever the reviewer made of it.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as chief
import chief_truth as truth
from __tests__.test_gather_context_wave2 import gather  # noqa: F401  (fixture)

CHECK = "(none in the loaded sample; check data availability)"


def _is_list_read(path):
    return (path.startswith(('/sessions?', '/invoices?', '/products?', '/offerings?'))
            or (path.startswith('/agent_queue?') and 'status=eq.draft' in path)
            or (path.startswith('/module_entries?') and 'custom_modules.slug=eq.projects' in path))


def _lists_return(monkeypatch, value):
    """Every list a new business sees comes back as `value` ([] = an empty
    read, None = a failed one); everything else is the fixture's."""
    original = chief._sb

    async def rows(client, method, path, body=None):
        if _is_list_read(path):
            return value
        return await original(client, method, path, body)
    monkeypatch.setattr(chief, '_sb', rows)


def _section(prompt, heading_start):
    """The lines under the heading that starts with `heading_start`."""
    after = prompt.split("\n" + heading_start, 1)[1]
    return after.split("\n", 1)[1].split("\n\n", 1)[0]


# ── The prompt ────────────────────────────────────────────────────────

def test_a_new_business_hears_nothing_yet(gather, monkeypatch):
    _lists_return(monkeypatch, [])
    _, ctx = gather(query_text=None)
    for name in ("queue", "sessions", "projects", "open_invoices", "products", "offerings"):
        assert ctx[f"{name}_complete"] is True, name
    assert set(ctx["context_quality"]["complete_lists"]) >= {
        "queue", "sessions", "projects", "open_invoices", "invoice_summary", "products", "offerings"}

    prompt = chief._format_context_for_prompt(ctx)
    assert "(nothing waiting for review)" in _section(prompt, "QUEUE (")
    assert "this list is complete" in prompt.split("\nQUEUE (", 1)[1].split("\n", 1)[0]
    assert "(no projects yet: this list is complete)" in _section(prompt, "PROJECTS (")
    assert "(no open invoices: this list is complete)" in _section(prompt, "OPEN INVOICES — TOTALS")
    assert "(no open invoices: this list is complete)" in _section(prompt, "OPEN INVOICES (")
    assert "(no products or services yet: this catalog is complete)" in _section(
        prompt, "PRODUCTS / SERVICES CATALOG")
    # The calendar keeps the words #1034 gave it.
    assert "(nothing booked in this window" in _section(prompt, chief.SESSIONS_HEADING)
    assert CHECK not in prompt
    assert '"complete_lists"' in prompt.split("DATA QUALITY:", 1)[1].split("\n", 1)[0]


def test_a_failed_read_still_says_to_check(gather, monkeypatch):
    _lists_return(monkeypatch, None)
    _, ctx = gather(query_text=None)
    for name in ("queue", "sessions", "projects", "open_invoices", "products", "offerings"):
        assert ctx[f"{name}_complete"] is False, name
    assert ctx["context_quality"]["complete_lists"] == []

    prompt = chief._format_context_for_prompt(ctx)
    for heading in ("QUEUE (", chief.SESSIONS_HEADING, "PROJECTS (", "OPEN INVOICES — TOTALS",
                    "OPEN INVOICES (", "PRODUCTS / SERVICES CATALOG"):
        assert CHECK in _section(prompt, heading), heading
    # The totals block said "(no open invoices)" on a failed read.
    assert "(no open invoices" not in prompt
    assert "no products" not in prompt and "nothing waiting" not in prompt
    assert "sample, not a total" in prompt and "loaded itemized sample" in prompt


def test_a_full_page_is_not_called_complete(gather, monkeypatch):
    original = chief._sb

    async def rows(client, method, path, body=None):
        if path.startswith('/agent_queue?') and 'status=eq.draft' in path:
            return [{"id": f"q{i}", "agent": "nurture", "action_type": "email"} for i in range(10)]
        return await original(client, method, path, body)
    monkeypatch.setattr(chief, '_sb', rows)
    _, ctx = gather(query_text=None)
    assert ctx["queue_complete"] is False
    assert "queue" not in ctx["context_quality"]["complete_lists"]
    assert "(10 loaded draft rows; sample, not a total)" in chief._format_context_for_prompt(ctx)


def test_a_complete_list_longer_than_the_page_is_not_called_complete():
    """Projects and invoices show their first 25: 30 read in full are
    still a sample on the page."""
    projects = [{"id": f"p{i}", "title": f"P{i}", "status": "active"} for i in range(30)]
    ctx = _bare_ctx(projects=projects, projects_complete=True)
    prompt = chief._format_context_for_prompt(ctx)
    assert "PROJECTS (loaded sample; use list_projects for additional records):" in prompt
    few = chief._format_context_for_prompt(_bare_ctx(projects=projects[:3], projects_complete=True))
    assert "PROJECTS (every project on file; this list is complete):" in few


def test_the_limits_are_the_reads():
    src = pathlib.Path(chief.__file__).read_text(encoding="utf-8")
    for name in chief._LIST_LIMITS:
        assert f"limit={{_LIST_LIMITS['{name}']}}" in src, name


# ── The answer check ──────────────────────────────────────────────────

def _review(claim, sid, quote):
    return json.dumps({"verdict": "supported", "claims": [
        {"text": claim, "kind": "fact", "source_id": sid, "quote": quote}]})


def test_an_empty_complete_list_proves_none():
    ctx = {"open_invoices": [], "invoice_summary": [], "open_invoices_complete": True,
           "queue": [], "queue_complete": True,
           "context_quality": {"retrieved_at": "2026-09-26T10:00:00+00:00", "unavailable": [],
                               "lists_are_samples": True,
                               "complete_lists": ["queue", "open_invoices", "invoice_summary"]}}
    sources = truth.evidence_for_review(ctx, "", [])
    inv = sources["context:open_invoices"]
    assert inv["complete"] is True and "unread" not in inv
    assert json.loads(inv["text"]) == {"rows": [], "complete": chief.EMPTY_COMPLETE["open_invoices"]}
    assert sources["context:invoice_summary"]["complete"] is True
    assert chief.EMPTY_COMPLETE["queue"] in sources["context:queue"]["text"]
    assert "complete_lists" in sources["context:context_quality"]["text"]

    draft = "You have no open invoices yet."
    verdict, cited, reason = truth.assess_review(
        _review(draft, "context:open_invoices", "no open invoices: this list is complete"), draft, sources)
    assert verdict == "supported", reason


def test_a_failed_read_cannot_prove_none():
    ctx = {"open_invoices": [], "invoice_summary": [], "open_invoices_complete": False}
    sources = truth.evidence_for_review(ctx, "", [])
    inv = sources["context:open_invoices"]
    assert inv["complete"] is False and inv["unread"] is True
    assert json.loads(inv["text"]) == {"rows": [], "unavailable": truth.UNREAD_NOTE}

    for draft in ("You have no open invoices yet.", "You don't have any open invoices.",
                  "You have 0 open invoices."):
        verdict, _, reason = truth.assess_review(
            _review(draft, "context:open_invoices", '"rows": []'), draft, sources)
        assert verdict == "unsupported" and reason.startswith("a failed read cited as absence"), draft

    # Saying the read failed is true, and cites the same record.
    honest = "I couldn't read your invoices just now, so the open count is unknown."
    verdict, _, reason = truth.assess_review(
        _review(honest, "context:open_invoices", truth.UNREAD_NOTE), honest, sources)
    assert verdict == "supported", reason


def test_a_failed_calendar_keeps_its_heading():
    sources = truth.evidence_for_review({"sessions": [], "sessions_complete": False}, "", [])
    assert json.loads(sources["context:sessions"]["text"]) == {
        "heading": chief.SESSIONS_HEADING, "rows": [], "unavailable": truth.UNREAD_NOTE}
    whole = truth.evidence_for_review({"sessions": [], "sessions_complete": True}, "", [])
    assert json.loads(whole["context:sessions"]["text"]) == {
        "heading": chief.SESSIONS_HEADING, "rows": [], "complete": chief.EMPTY_COMPLETE["sessions"]}


def test_a_context_without_the_marks_is_unchanged():
    """Older callers and fixtures that never set <list>_complete: an empty
    list is neither none nor failed, exactly as before."""
    sources = truth.evidence_for_review({"open_invoices": [], "queue": []}, "", [])
    assert sources["context:open_invoices"]["text"] == "[]"
    assert sources["context:open_invoices"]["complete"] is False
    assert "unread" not in sources["context:open_invoices"]


def test_the_rules_say_it():
    assert "complete_lists" in truth.REVIEW_SYSTEM and '"complete": true' in truth.REVIEW_SYSTEM
    assert "say plainly\n  there are none yet" in truth.AUTHOR_RULES


def _bare_ctx(**extra):
    return {
        "business": {"id": "biz-1", "name": "Biz", "type": "coach", "settings": {}},
        "contacts_total": 0, "contacts_by_status": {}, "avg_health": 0, "at_risk": [],
        "queue": [], "sessions": [], "insights": [], "modules": [], "module_counts": {},
        "events": [], "memories": [], "notifications": [], "recent_queue_24h": [],
        "projects": [], "products": [], "contacts_lookup": [], "site": None,
        "strategy_track": None, "business_track": None, "email_replies": [],
        "sms_messages": [], "open_invoices": [], **extra,
    }
