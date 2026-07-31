"""
test_briefing_verticals.py — the briefing's vertical sections come from
real queries, and the two isolation walls actually hold.

What matters most here, in order:

  1. The THERAPIST wall — the practice-review branch reads scheduling and
     billing tables ONLY. The test records EVERY query the branch makes
     (both the async sb path and the sync sb_clients path, so a read
     added either way is caught) and asserts each one against
     THERAPIST_ALLOWED_TABLES. Adding a table to the branch without
     adding it to the frozenset fails this suite; adding it to the
     frozenset is a reviewable diff on a constant whose docstring names
     the HIPAA posture.
  2. The MINISTRY wall — the community branch never names
     restricted_module_entries (giving). Same recording discipline.
  3. Honest degradation — a lawyer with no work_pipeline modules gets
     sections == [], i.e. the generic briefing, never fabricated zeros.

Assertions follow the discipline written down in test_vertical_autopilot:
assert on the DATA DICTS the branch returns, not on accessors that
default their way into passing (a fallback accessor can never fail).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import pytest

import briefing_verticals as bv


def _iso_in(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


def _ts_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


class RecordingSB:
    """A fake of growth_engine's async _sb. Dispatch is by path predicate;
    every call is recorded so tests can assert on WHICH tables were read,
    not just on what came back."""

    def __init__(self, routes: List[Tuple]):
        # routes: list of (predicate(path) -> bool, rows)
        self.routes = routes
        self.calls: List[Tuple[str, str]] = []

    async def __call__(self, client, method: str, path: str, body=None):
        self.calls.append((method, path))
        if method != "GET":
            return []
        for pred, rows in self.routes:
            if pred(path):
                return rows
        return []

    def tables_touched(self) -> set:
        return {p.split("?", 1)[0].lstrip("/") for _, p in self.calls}


def _no_service_reads(monkeypatch):
    """Fail LOUDLY if a branch under test reaches for the sync
    service-role client — those reads would bypass the recorder."""
    import sb_clients

    def _boom(*a, **k):
        raise AssertionError(
            "branch used sb_clients service-role directly — reads must go "
            "through the recorded sb callable in this test")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _boom)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", _boom)


def _zero_unbilled(monkeypatch):
    import billable_time
    monkeypatch.setattr(
        billable_time, "unbilled_summary",
        lambda biz_id, contact_id=None: {"entries": 0, "minutes": 0,
                                         "hours": "0m", "amount": 0.0,
                                         "unpriced_entries": 0})


def _no_expiring(monkeypatch):
    import customer_balances
    monkeypatch.setattr(customer_balances, "expiring_soon",
                        lambda biz_id, within_days=30: [])


# ─── lawyer: deadline extraction from a work_pipeline module ─────────

MATTER_MODULE = {
    "id": "mod-matters", "name": "Matters", "slug": "matters",
    "archetype_params": {
        "stage_field": "stage", "title_field": "title",
        "date_field": "deadline",
        "stages": [
            {"id": "intake", "label": "Intake"},
            {"id": "active", "label": "Active"},
            {"id": "closed", "label": "Closed", "done": True},
        ],
    },
}


def _matter_entries() -> List[Dict[str, Any]]:
    return [
        # In range: 5 and 10 days out.
        {"id": "e1", "updated_at": _ts_ago(1),
         "data": {"title": "Smith filing", "stage": "active",
                  "deadline": _iso_in(5)}},
        {"id": "e2", "updated_at": _ts_ago(2),
         "data": {"title": "Rivera discovery", "stage": "intake",
                  "deadline": _iso_in(10)}},
        # OUT of range: 30 days out — must not count as approaching.
        {"id": "e3", "updated_at": _ts_ago(3),
         "data": {"title": "Chan appeal", "stage": "active",
                  "deadline": _iso_in(30)}},
        # Done stage: a closed matter's date is nobody's deadline.
        {"id": "e4", "updated_at": _ts_ago(1),
         "data": {"title": "Old matter", "stage": "closed",
                  "deadline": _iso_in(3)}},
        # Past due.
        {"id": "e5", "updated_at": _ts_ago(40),
         "data": {"title": "Estate of Doe", "stage": "active",
                  "deadline": _iso_in(-2)}},
    ]


def _lawyer_sb() -> RecordingSB:
    return RecordingSB([
        (lambda p: p.startswith("/custom_modules") and "work_pipeline" in p,
         [MATTER_MODULE]),
        (lambda p: p.startswith("/module_entries"), _matter_entries()),
        (lambda p: p.startswith("/customer_balances"), []),
        (lambda p: p.startswith("/contacts"), []),
    ])


def test_lawyer_deadlines_in_and_out_of_range(monkeypatch):
    _zero_unbilled(monkeypatch)
    sb = _lawyer_sb()
    out = asyncio.run(bv.gather(sb, None, {"id": "b1", "type": "lawyer"}))

    assert out["vertical"] == "lawyer"
    matters = [s for s in out["sections"] if s["key"] == "matters"]
    assert len(matters) == 1
    scan = matters[0]["data"]

    # The dict, not an accessor: exactly the two in-window titles.
    assert [d["title"] for d in scan["deadlines"]] == \
        ["Smith filing", "Rivera discovery"]
    assert scan["deadlines_7d"] == 1                       # only Smith
    assert [d["title"] for d in scan["overdue"]] == ["Estate of Doe"]
    # Done-stage entry is not open work; 30-day one is open but not near.
    assert scan["open_count"] == 4
    assert "Old matter" not in str(scan["deadlines"]) + str(scan["overdue"])
    # The stale scan caught the 40-day-idle matter.
    assert [s["title"] for s in scan["stale"]] == ["Estate of Doe"]


def test_lawyer_alias_resolves_to_the_same_branch(monkeypatch):
    _zero_unbilled(monkeypatch)
    out = asyncio.run(bv.gather(_lawyer_sb(), None,
                                {"id": "b1", "type": "attorney"}))
    assert out["vertical"] == "lawyer"
    assert any(s["key"] == "matters" for s in out["sections"])


def test_lawyer_unbilled_time_comes_from_billable_time(monkeypatch):
    import billable_time
    monkeypatch.setattr(
        billable_time, "unbilled_summary",
        lambda biz_id, contact_id=None: {"entries": 3, "minutes": 270,
                                         "hours": "4h 30m", "amount": 900.0,
                                         "unpriced_entries": 1})
    out = asyncio.run(bv.gather(_lawyer_sb(), None,
                                {"id": "b1", "type": "lawyer"}))
    ub = [s for s in out["sections"] if s["key"] == "unbilled_time"]
    assert len(ub) == 1
    assert ub[0]["data"]["entries"] == 3
    assert ub[0]["data"]["amount"] == 900.0
    assert "time_entries" in ub[0]["tables"]


# ─── degradation: no modules → generic briefing, not empty sections ──

def test_lawyer_with_no_pipeline_modules_degrades_to_generic(monkeypatch):
    _zero_unbilled(monkeypatch)
    sb = RecordingSB([])  # every read returns []
    out = asyncio.run(bv.gather(sb, None, {"id": "b1", "type": "lawyer"}))
    assert out["sections"] == []
    assert out["tables_read"] == []
    # Nothing to render — the briefing body gains no vertical block.
    assert bv.format_markdown(out) == ""
    assert bv.format_for_ai(out) == ""


def test_generic_verticals_have_no_branch_at_all():
    async def _explode(*a, **k):          # pragma: no cover
        raise AssertionError("generic vertical must not query anything")
    for t in ("service_provider", "custom", "", None):
        out = asyncio.run(bv.gather(_explode, None, {"id": "b1", "type": t}))
        assert out["sections"] == []


# ─── therapist: the table allowlist is enforced, not aspirational ────

def _therapist_sb() -> RecordingSB:
    sessions = [{"id": f"s{i}", "status": "completed"} for i in range(3)]
    sessions.append({"id": "sc", "status": "cancelled"})
    return RecordingSB([
        (lambda p: p.startswith("/sessions") and "status=eq.scheduled" in p,
         [{"id": "u1"}, {"id": "u2"}]),
        (lambda p: p.startswith("/sessions"), sessions),
        (lambda p: p.startswith("/invoices"),
         [{"id": "i1", "total": 120.0, "due_date": _iso_in(-3)},
          {"id": "i2", "total": 80.0, "due_date": _iso_in(10)}]),
    ])


def test_therapist_branch_reads_only_allowlisted_tables(monkeypatch):
    """THE wall. Every query the branch issued must resolve to a table in
    THERAPIST_ALLOWED_TABLES — someone adding a /contacts or
    /module_entries read to this branch turns this test red."""
    _no_service_reads(monkeypatch)
    sb = _therapist_sb()
    out = asyncio.run(bv.gather(sb, None, {"id": "b1", "type": "therapist"}))

    # Non-vacuous: the branch really ran and really queried.
    assert out["sections"], "therapist branch produced no sections — " \
        "the allowlist assertion below would be vacuous"
    assert sb.calls, "no queries recorded"

    touched = sb.tables_touched()
    assert touched, "recorder saw nothing"
    forbidden = touched - bv.THERAPIST_ALLOWED_TABLES
    assert not forbidden, (
        f"therapist branch read tables outside the scheduling/billing "
        f"allowlist: {sorted(forbidden)}. The platform's HIPAA posture "
        f"(vertical_registry.py, vertical_scope.py) forbids this.")
    # And it used both halves of its remit.
    assert touched == {"sessions", "invoices"}


def test_therapist_allowlist_is_exactly_scheduling_and_billing():
    """Pin the constant itself: widening it is a deliberate, visible act."""
    assert bv.THERAPIST_ALLOWED_TABLES == frozenset({"sessions", "invoices"})


def test_therapist_numbers_and_no_clinical_language(monkeypatch):
    _no_service_reads(monkeypatch)
    out = asyncio.run(bv.gather(_therapist_sb(), None,
                                {"id": "b1", "type": "counselor"}))
    assert out["vertical"] == "therapist"
    data = out["sections"][0]["data"]
    assert data["sessions_this_week"] == 4      # 3 completed + 1 cancelled
    assert data["cancelled_this_week"] == 1
    assert data["sessions_upcoming_7d"] == 2
    assert data["unpaid_invoices"] == 2
    assert data["unpaid_total"] == 200.0
    assert data["unpaid_overdue"] == 1

    rendered = bv.format_markdown(out).lower()
    for word in ("progress", "note", "diagnos", "treatment", "clinical"):
        # "clinical" appears ONLY in the explicit "never clinical content"
        # disclaimer line — allow that exact usage, nothing else.
        if word == "clinical":
            assert rendered.count("clinical") == 1
            assert "never clinical content" in rendered
        else:
            assert word not in rendered, f"clinical language leaked: {word}"
    # The report states which tables the branch reads.
    assert "sessions, invoices" in rendered


def test_therapist_with_empty_practice_degrades_to_generic(monkeypatch):
    _no_service_reads(monkeypatch)
    out = asyncio.run(bv.gather(RecordingSB([]), None,
                                {"id": "b1", "type": "therapist"}))
    assert out["sections"] == []


def test_therapist_briefing_actions_are_suppressed():
    """The action phase drafts client outreach; the therapist autopilot
    job promises 'never client outreach'. The suppression returns before
    any query — client=None proves no I/O happened."""
    import growth_engine
    assert bv.outreach_restricted("therapist") is True
    assert bv.outreach_restricted("lmft") is True
    assert bv.outreach_restricted("coach") is False

    res = asyncio.run(growth_engine._generate_briefing_actions(
        None, {"id": "b1", "type": "therapy"}))
    assert res == {"actions": [], "total_created": 0, "total_skipped": 0,
                   "pending_proposals_count": 0, "outreach_suppressed": True}


# ─── ministry / nonprofit: giving stays behind the locked door ───────

ROSTER_MODULE = {
    "id": "mod-roster", "name": "Sunday Services", "slug": "services",
    "archetype_params": {
        "title_field": "title", "date_field": "date",
        "signups_field": "signups",
        "roles": [
            {"id": "greeter", "label": "Greeter", "needed": 2},
            {"id": "nursery", "label": "Nursery", "needed": 1},
        ],
    },
}


def _ministry_sb() -> RecordingSB:
    entries = [
        {"id": "ev1", "updated_at": _ts_ago(1),
         "data": {"title": "Sunday Service", "date": _iso_in(5),
                  "signups": [
                      {"name": "Ana", "role": "greeter", "status": "yes"},
                      {"name": "Ben", "role": "nursery", "status": "yes"},
                  ]}},
        # Out of window — three weeks away.
        {"id": "ev2", "updated_at": _ts_ago(1),
         "data": {"title": "Fall Picnic", "date": _iso_in(21),
                  "signups": []}},
    ]
    return RecordingSB([
        (lambda p: p.startswith("/custom_modules") and "event_roster" in p,
         [ROSTER_MODULE]),
        (lambda p: p.startswith("/module_entries"), entries),
        (lambda p: p.startswith("/contacts"), [{"id": "c1"}, {"id": "c2"}]),
    ])


def test_ministry_roster_gaps_and_contact_growth(monkeypatch):
    _no_service_reads(monkeypatch)
    sb = _ministry_sb()
    out = asyncio.run(bv.gather(sb, None, {"id": "b1", "type": "church"}))
    assert out["vertical"] == "ministry"

    gaps = [s for s in out["sections"] if s["key"] == "roster_gaps"]
    assert len(gaps) == 1
    occasions = gaps[0]["data"]["occasions"]
    # Only the in-window occasion, and only the under-filled role:
    # greeter needs 2, has 1; nursery needs 1, has 1 (filled → absent).
    assert [o["title"] for o in occasions] == ["Sunday Service"]
    assert occasions[0]["unfilled"] == ["Greeter needs 1 more"]

    growth = [s for s in out["sections"] if s["key"] == "community_growth"]
    assert growth and growth[0]["data"]["new_this_week"] == 2


def test_ministry_branch_never_touches_restricted_entries(monkeypatch):
    """The pastoral-care wall: giving lives in restricted_module_entries
    behind audited owner-only endpoints. The community branch must never
    name that table — in any query, via either client."""
    _no_service_reads(monkeypatch)
    sb = _ministry_sb()
    out = asyncio.run(bv.gather(sb, None, {"id": "b1", "type": "nonprofit"}))
    assert sb.calls, "no queries recorded — assertion would be vacuous"
    assert out["sections"], "branch produced nothing — assertion would be vacuous"
    for method, path in sb.calls:
        assert bv.RESTRICTED_TABLE not in path, (
            f"community branch touched the restricted giving table: "
            f"{method} {path}")
    assert bv.RESTRICTED_TABLE == "restricted_module_entries"


# ─── package verticals: the view is read, the sweep is not duplicated ─

def test_coach_balance_expiry_reads_the_service_layer(monkeypatch):
    """expiring_soon (customer_balances' own reader) supplies the grants;
    the balances come from the customer_balances VIEW via sb. The section
    SUMMARIZES — no notification writes (the sweep owns those)."""
    import customer_balances
    grants = [{"id": "g1", "contact_id": "c1", "kind": "package",
               "unit": "session", "delta": 4.0,
               "expires_at": _iso_in(12) + "T00:00:00Z", "reason": "6-pack"}]
    seen = {}

    def fake_expiring(biz_id, within_days=30):
        seen["args"] = (biz_id, within_days)
        return grants
    monkeypatch.setattr(customer_balances, "expiring_soon", fake_expiring)

    sb = RecordingSB([
        (lambda p: p.startswith("/customer_balances"),
         [{"contact_id": "c1", "unit": "session", "balance": 4},
          {"contact_id": "c2", "unit": "session", "balance": 1},
          {"contact_id": "c3", "unit": "session", "balance": 0}]),
        (lambda p: p.startswith("/contacts"),
         [{"id": "c1", "name": "Sarah"}, {"id": "c2", "name": "Marcus"}]),
    ])
    out = asyncio.run(bv.gather(sb, None, {"id": "b9", "type": "coach"}))

    assert seen["args"] == ("b9", 30)     # the briefing's WIDER window
    bal = [s for s in out["sections"] if s["key"] == "package_balances"]
    assert len(bal) == 1
    # Zero balances excluded; lowest first.
    assert [b["balance"] for b in bal[0]["data"]["balances"]] == [1.0, 4.0]
    assert bal[0]["data"]["low_count"] == 1          # Marcus, 1 session left

    exp = [s for s in out["sections"] if s["key"] == "expiring_balances"]
    assert len(exp) == 1
    assert exp[0]["data"]["grants"][0]["contact_id"] == "c1"
    assert exp[0]["data"]["grants"][0]["delta"] == 4.0

    # The view was read through sb; NOTHING was written anywhere.
    assert "customer_balances" in sb.tables_touched()
    assert all(m == "GET" for m, _ in sb.calls)


def test_contractor_estimate_followups(monkeypatch):
    jobs_module = {
        "id": "mod-jobs", "name": "Jobs", "slug": "jobs",
        "archetype_params": {
            "stage_field": "stage", "title_field": "title",
            "date_field": "start_date", "value_field": "value",
            "stages": [
                {"id": "estimate", "label": "Estimate sent"},
                {"id": "scheduled", "label": "Scheduled"},
                {"id": "done", "label": "Done", "done": True},
            ],
        },
    }
    entries = [
        {"id": "j1", "updated_at": _ts_ago(12),
         "data": {"title": "Deck rebuild", "stage": "estimate", "value": 4200}},
        {"id": "j2", "updated_at": _ts_ago(2),   # too fresh to nag about
         "data": {"title": "Fence repair", "stage": "estimate", "value": 900}},
        {"id": "j3", "updated_at": _ts_ago(1),
         "data": {"title": "Kitchen reno", "stage": "scheduled",
                  "value": 18000, "start_date": _iso_in(6)}},
    ]
    sb = RecordingSB([
        (lambda p: p.startswith("/custom_modules") and "work_pipeline" in p,
         [jobs_module]),
        (lambda p: p.startswith("/module_entries"), entries),
    ])
    out = asyncio.run(bv.gather(sb, None, {"id": "b1", "type": "plumber"}))
    assert out["vertical"] == "contractor"
    jobs = [s for s in out["sections"] if s["key"] == "jobs"]
    assert len(jobs) == 1
    scan = jobs[0]["data"]
    assert [e["title"] for e in scan["estimates_waiting"]] == ["Deck rebuild"]
    assert scan["by_stage"] == {"Estimate sent": 2, "Scheduled": 1}
    assert scan["open_value"] == 23100.0
    assert [d["title"] for d in scan["deadlines"]] == ["Kitchen reno"]


# ─── a broken branch degrades, never detonates the briefing ──────────

def test_branch_failure_degrades_to_generic(monkeypatch):
    async def _sb_boom(client, method, path, body=None):
        raise RuntimeError("supabase down")
    out = asyncio.run(bv.gather(_sb_boom, None, {"id": "b1", "type": "lawyer"}))
    assert out == {"vertical": "lawyer", "sections": [], "tables_read": []}


# ─── the wiring into growth_engine's prompt payload ──────────────────

def test_briefing_data_block_carries_the_vertical_sections():
    import growth_engine
    stats = {
        "window_start": "2026-07-24T00:00:00Z",
        "window_end": "2026-07-31T00:00:00Z",
        "new_contacts": [], "new_contact_count": 0,
        "at_risk": [], "thriving": [],
        "event_counts": {}, "total_events": 0,
        "payment_event_count": 0, "payment_sum": 0.0,
        "drafts_by_agent": {}, "pending_items": [],
        "sessions_completed_count": 0, "sessions_upcoming_count": 0,
        "sessions_upcoming": [],
        "vertical": {"vertical": "lawyer", "tables_read": ["module_entries"],
                     "sections": [{"key": "matters",
                                   "heading": "Matters & deadlines — Matters",
                                   "lines": ["3 deadlines in the next 14 days"],
                                   "tables": ["module_entries"], "data": {}}]},
    }
    block = growth_engine._format_briefing_data_for_ai(stats)
    assert "VERTICAL SECTIONS (lawyer)" in block
    assert "3 deadlines in the next 14 days" in block
    assert "never compute, extrapolate or invent" in block

    # And the generic case adds nothing.
    stats["vertical"] = {"vertical": "custom", "sections": [],
                         "tables_read": []}
    assert "VERTICAL SECTIONS" not in growth_engine._format_briefing_data_for_ai(stats)
