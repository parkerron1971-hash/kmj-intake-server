"""
test_trust_hardening.py — S11: the trust layer's four audit findings.

1. AUDIT COVERAGE — HistoryPanel promises "every action taken in this
   business"; before this arc only the chat loop wrote audit rows. The
   scheduler and the trusted-autonomy sweep now write them too, with
   the ok/failed TRUTH (a failed handler that audits as ok=true is
   worse than no audit row).

2. SEAT VISIBILITY — GET /audit was owner-only, so an invited seat saw
   an empty History panel. Member+ reads now, same require_role ladder
   as every other router.

3. UNDO BREADTH — two new inverses (add_testimonial, create_offering)
   round-trip create→undo→verify-gone against a fake store; the
   write_off_time both-maps contradiction is resolved (see
   test_action_inverse.py for the map-level pins).

4. EXPORT/DELETE DRIFT — BUSINESS_CHILD_TABLES had drifted from the
   live schema; the known-missing tables are pinned present, the
   deliberate exclusions pinned absent, and child-before-parent order
   pinned for the FK pairs that matter.
"""
from __future__ import annotations

import asyncio
import sys
import pathlib
from unittest import mock

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def _user(uid: str):
    return type("U", (), {"id": uid, "email": f"{uid}@x.com"})()


# ═════════════════════════════════════════════════════════════════════
# 1a. Scheduler → audit log (ok AND failed outcomes)
# ═════════════════════════════════════════════════════════════════════

def _run_scheduler_row(monkeypatch, handler):
    """Execute one scheduled row with everything else faked; return the
    audit_log.record calls."""
    import chief_scheduler
    import chief_of_staff
    import audit_log
    import sb_clients

    audit_calls = []
    monkeypatch.setattr(
        audit_log, "record",
        lambda biz, **kw: audit_calls.append((biz, kw)) or True)

    monkeypatch.setattr(
        sb_clients, "sb_get_as_service",
        lambda path: ([{"id": "b1", "name": "B", "type": "coach",
                        "settings": {}, "owner_id": "o1"}]
                      if path.startswith("/businesses") else []))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: [])

    async def _quiet_notify(biz, row, ok, detail):
        return None
    monkeypatch.setattr(chief_scheduler, "_notify_outcome", _quiet_notify)

    monkeypatch.setitem(chief_of_staff.ACTION_HANDLERS, "_s11_stub", handler)
    # Ledger Stage 0: the scheduler now consults action_registry and fails
    # closed on an unclassified verb. In production that can't happen —
    # the drift test pins REGISTRY's keys to ACTION_HANDLERS' — but this
    # stub is synthetic, so register it too. These tests are about audit
    # plumbing; the gate itself is covered in test_ledger_stage0_gates.
    import action_registry
    monkeypatch.setitem(action_registry.REGISTRY, "_s11_stub",
                        {"effect": "write", "reversibility": "A",
                         "why": "test stub"})

    row = {"id": "r1", "business_id": "b1", "label": "Nightly stub",
           "action": {"type": "_s11_stub"}, "recurrence": "",
           "run_at": "2026-07-31T09:00:00Z"}
    asyncio.run(chief_scheduler._execute_row(row))
    return audit_calls


def test_scheduler_success_writes_an_ok_audit_row(monkeypatch):
    async def handler(client, biz, action):
        return {"result": "done", "label": "Stub ran"}
    calls = _run_scheduler_row(monkeypatch, handler)
    assert len(calls) == 1
    biz, kw = calls[0]
    assert biz == "b1"
    assert kw["verb"] == "_s11_stub"
    assert kw["ok"] is True
    assert kw["error"] is None
    assert kw["actor_type"] == "system"       # table CHECK constraint
    assert kw["actor_id"] == "scheduler"      # real identity rides actor_id
    assert kw["source"] == "scheduler"
    assert kw["payload"]["scheduled_action_id"] == "r1"


def test_scheduler_failure_writes_the_failed_truth(monkeypatch):
    async def handler(client, biz, action):
        return {"result": "Failed: no contact", "label": "no contact",
                "failed": True}
    calls = _run_scheduler_row(monkeypatch, handler)
    assert len(calls) == 1
    _, kw = calls[0]
    assert kw["ok"] is False
    assert kw["error"]  # the failure reason travels


def test_scheduler_honors_the_failed_seam_even_with_polite_text(monkeypatch):
    """PR #345's machine-readable seam: "failed": True marks failure even
    when the visible copy stays friendly (no 'Failed:' prefix)."""
    async def handler(client, biz, action):
        return {"result": "I held that one for review", "label": "held",
                "failed": True}
    calls = _run_scheduler_row(monkeypatch, handler)
    assert calls[0][1]["ok"] is False


def test_scheduler_handler_crash_audits_as_failed(monkeypatch):
    async def handler(client, biz, action):
        raise RuntimeError("boom")
    calls = _run_scheduler_row(monkeypatch, handler)
    _, kw = calls[0]
    assert kw["ok"] is False
    assert "boom" in (kw["error"] or "")


def test_scheduler_audit_failure_never_blocks_the_run(monkeypatch):
    """Fail-soft: an audit-write explosion is logged, not raised."""
    import chief_scheduler
    import chief_of_staff
    import audit_log
    import sb_clients

    monkeypatch.setattr(audit_log, "record",
                        mock.Mock(side_effect=RuntimeError("audit down")))
    monkeypatch.setattr(
        sb_clients, "sb_get_as_service",
        lambda path: ([{"id": "b1", "name": "B", "type": "coach",
                        "settings": {}, "owner_id": "o1"}]
                      if path.startswith("/businesses") else []))
    patches = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: patches.append((p, b)) or [])

    async def _quiet_notify(biz, row, ok, detail):
        return None
    monkeypatch.setattr(chief_scheduler, "_notify_outcome", _quiet_notify)

    async def handler(client, biz, action):
        return {"result": "done", "label": "ran"}
    monkeypatch.setitem(chief_of_staff.ACTION_HANDLERS, "_s11_stub", handler)

    asyncio.run(chief_scheduler._execute_row(
        {"id": "r1", "business_id": "b1", "action": {"type": "_s11_stub"},
         "recurrence": "", "run_at": "2026-07-31T09:00:00Z"}))
    # The row still completed (status patched) despite the audit failure.
    assert any("chief_scheduled_actions" in p for p, _ in patches)


# ═════════════════════════════════════════════════════════════════════
# 1b. Trusted sweep → audit log (per executed proposal, failures too)
# ═════════════════════════════════════════════════════════════════════

def _run_sweep(monkeypatch, execute):
    import rules_router
    import rules_engine
    import audit_log
    import sb_clients

    audit_calls = []
    monkeypatch.setattr(
        audit_log, "record",
        lambda biz, **kw: audit_calls.append((biz, kw)) or True)

    def fake_get(path):
        if path.startswith("/businesses"):
            return [{"id": "b1", "name": "B", "owner_id": "o1",
                     "settings": {"autopilot":
                                  {"trusted_proposal_types": ["propose_task"]}}}]
        if "/chief_proposals" in path and "status=eq.pending" in path:
            return [{"id": "p1", "business_id": "b1",
                     "proposal_type": "propose_task",
                     "proposed": {"title": "Follow up with Jane"},
                     "status": "pending"}]
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake_get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: [])
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: [])
    monkeypatch.setattr(rules_engine, "business_paused", lambda biz_row: False)
    monkeypatch.setattr(
        rules_router, "_trust_stats",
        lambda biz: {"propose_task": {"approved": 20, "rejected": 0,
                                      "pending": 0, "resolved": 20,
                                      "approval_ratio": 1.0,
                                      "graduation_candidate": True}})
    monkeypatch.setattr(rules_router, "_capture_signal",
                        lambda *a, **k: None)
    monkeypatch.setattr(rules_router, "_execute_proposal", execute)

    rules_router._run_trusted_sweep_sync()
    return audit_calls


def test_trusted_sweep_audits_each_executed_proposal(monkeypatch):
    calls = _run_sweep(monkeypatch, lambda biz, p: {"ok": True})
    assert len(calls) == 1
    biz, kw = calls[0]
    assert biz == "b1"
    assert kw["actor_type"] == "system"
    assert kw["actor_id"] == "trust-track"
    assert kw["verb"] == "propose_task"
    assert kw["ok"] is True
    assert kw["payload"]["proposal_id"] == "p1"


def test_trusted_sweep_audits_failures_too(monkeypatch):
    def explode(biz, p):
        raise RuntimeError("smtp down")
    calls = _run_sweep(monkeypatch, explode)
    assert len(calls) == 1
    _, kw = calls[0]
    assert kw["ok"] is False
    assert "smtp down" in (kw["error"] or "")
    assert kw["actor_id"] == "trust-track"


# ═════════════════════════════════════════════════════════════════════
# 2. GET /audit — member+ via the seat ladder
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture
def audit_biz(monkeypatch):
    import sb_clients

    def fake_get(path):
        if path.startswith("/businesses?id=eq.b1"):
            return [{"id": "b1", "owner_id": "owner1"}]
        if path.startswith("/businesses"):
            return []
        if path.startswith("/business_users"):
            for uid, role in (("m1", "member"), ("v1", "viewer"),
                              ("a1", "admin")):
                if f"user_id=eq.{uid}" in path:
                    return [{"role": role}]
            return []
        if path.startswith("/audit_log"):
            return [{"id": "e1", "actor_type": "system",
                     "actor_id": "scheduler", "verb": "send_report",
                     "ok": True, "error": None, "summary": "sent",
                     "source": "scheduler",
                     "created_at": "2026-07-31T09:00:00Z",
                     "target_type": None, "target_id": None}]
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake_get)


def test_audit_owner_still_reads(audit_biz):
    import audit_log
    out = audit_log.read_audit(biz="b1", user=_user("owner1"))
    assert out["ok"] is True and out["count"] == 1


def test_audit_member_seat_reads_now(audit_biz):
    """The empty-rooms fix: a working seat sees the same history."""
    import audit_log
    out = audit_log.read_audit(biz="b1", user=_user("m1"))
    assert out["ok"] is True and out["count"] == 1


def test_audit_admin_seat_reads(audit_biz):
    import audit_log
    out = audit_log.read_audit(biz="b1", user=_user("a1"))
    assert out["ok"] is True


def test_audit_viewer_can_read_history(audit_biz):
    """The member floor was DELIBERATELY lowered to viewer (2026-08-03).

    It created a dead end: the sidebar shows every team seat a History
    leaf, so a viewer clicking it met a 403. History is a trust surface
    — a seat that can see the business should be able to see what
    happened to it. Safe because the query selects no payload/result,
    so record CONTENTS are still not exposed by the wider audience.
    Outsiders are still refused — see the test below, which is the
    regression that actually matters.
    """
    import audit_log
    assert audit_log.read_audit(biz="b1", user=_user("v1"))["ok"] is True


def test_audit_outsider_is_refused(audit_biz):
    import audit_log
    with pytest.raises(HTTPException) as e:
        audit_log.read_audit(biz="b1", user=_user("stranger"))
    assert e.value.status_code == 403


def test_audit_unknown_business_404s(audit_biz):
    import audit_log
    with pytest.raises(HTTPException) as e:
        audit_log.read_audit(biz="nope", user=_user("owner1"))
    assert e.value.status_code == 404


# ═════════════════════════════════════════════════════════════════════
# 3. New inverses — full create → undo → verify-gone round trips
# ═════════════════════════════════════════════════════════════════════

class _FakeStore:
    """Just enough PostgREST for the handlers under test: one businesses
    row (settings jsonb) and an offerings table."""

    def __init__(self):
        self.settings = {}
        self.offerings = []
        self._next = 1

    async def sb(self, client, method, path, body=None):
        if path.startswith("/businesses"):
            if method == "GET":
                return [{"id": "b1", "settings": self.settings}]
            if method == "PATCH":
                self.settings = (body or {}).get("settings", self.settings)
                return [{"id": "b1"}]
        if path.startswith("/offerings"):
            if method == "GET":
                # slug-existence probe during create
                return [o for o in self.offerings
                        if f"slug=eq.{o['slug']}" in path]
            if method == "POST":
                row = {"id": f"off-{self._next}", **(body or {})}
                self._next += 1
                self.offerings.append(row)
                return [row]
            if method == "PATCH":
                for o in self.offerings:
                    if f"id=eq.{o['id']}" in path:
                        o.update(body or {})
                        return [o]
                return []
        return []


@pytest.fixture
def cos(monkeypatch):
    import chief_of_staff
    store = _FakeStore()
    monkeypatch.setattr(chief_of_staff, "_sb", store.sb)
    monkeypatch.setattr(chief_of_staff, "_refresh_composed_site_bg",
                        lambda biz_id: None)
    return chief_of_staff, store


def _dispatch(cos_mod, action):
    handler = cos_mod.ACTION_HANDLERS[action["type"]]
    return asyncio.run(handler(None, {"id": "b1", "owner_id": "o1",
                                      "settings": {}}, action))


def test_add_testimonial_round_trips_to_gone(cos):
    import action_inverse as ai
    cos_mod, store = cos

    res = _dispatch(cos_mod, {"type": "add_testimonial",
                              "quote": "Changed my business.",
                              "name": "Marcus"})
    assert res.get("failed") is not True
    assert len(store.settings["website_content"]["testimonials"]) == 1

    inv = ai.build_inverse("add_testimonial",
                           {"quote": "Changed my business.", "name": "Marcus"},
                           res)
    assert inv["type"] == "remove_testimonial"
    assert inv["testimonial_id"] == res["testimonial_id"]

    undo = _dispatch(cos_mod, inv)
    assert undo.get("failed") is not True
    assert store.settings["website_content"]["testimonials"] == []  # GONE


def test_create_offering_round_trips_to_archived(cos):
    import action_inverse as ai
    cos_mod, store = cos

    res = _dispatch(cos_mod, {"type": "create_offering",
                              "name": "Starter Kit", "category": "product"})
    assert res.get("failed") is not True
    assert store.offerings[0]["is_active"] is True

    inv = ai.build_inverse("create_offering",
                           {"name": "Starter Kit", "category": "product"}, res)
    assert inv["type"] == "archive_offering"
    assert inv["offering_id"] == res["offering_id"]

    undo = _dispatch(cos_mod, inv)
    assert undo.get("failed") is not True
    # The codebase's own delete for offerings IS the archive.
    assert store.offerings[0]["is_active"] is False


def test_new_inverses_refuse_without_the_created_id():
    """Same discipline as create_module_entry: reversible only from what
    the create actually produced."""
    import action_inverse as ai
    assert ai.build_inverse("add_testimonial", {"quote": "x", "name": "y"},
                            {}) is None
    assert ai.build_inverse("create_offering", {"name": "x"}, {}) is None


def test_create_contact_refusal_names_the_containment_law():
    """delete_contact is class C (hard delete) and undo never reaches
    class C — so create_contact stays refused, WITH a real sentence."""
    import action_inverse as ai
    assert ai.can_undo("create_contact") is False
    assert ai.why_not("create_contact")
    assert "create_contact" in ai.NOT_UNDOABLE_REASON


@pytest.mark.parametrize("verb", [
    "create_task", "create_goal", "create_note", "save_note",
    "log_time", "save_email_template",
])
def test_reviewed_creates_are_refused_with_reasons(verb):
    """Every class-A create the S11 audit reviewed and refused carries an
    honest, specific reason — never the generic shrug."""
    import action_inverse as ai
    assert ai.can_undo(verb) is False
    assert verb in ai.NOT_UNDOABLE_REASON
    assert len(ai.why_not(verb)) > 20


# ═════════════════════════════════════════════════════════════════════
# 4. BUSINESS_CHILD_TABLES — drift check against the known schema
# ═════════════════════════════════════════════════════════════════════

# The audit's known-missing list, plus the newer per-business tables.
_MUST_BE_LISTED = [
    "time_entries", "customer_ledger", "campaigns", "campaign_sends",
    "business_expenses", "chart_of_accounts", "audit_log",
    "chief_undo_log", "journal_entries", "ledger_entries",
    "gl_sync_queue", "gl_divergence_alarms", "accounting_periods",
    "period_edit_overrides", "quickbooks_connections",
    "quickbooks_pushed_entries", "chief_scheduled_actions",
    "sms_consents", "chief_notifications", "practitioner_rules",
    "rule_runs", "contractors", "outbound_transfers", "esign_documents",
    "restricted_module_entries", "restricted_module_access_log",
    "business_users", "agent_runs", "mcp_tokens",
]

# Deliberately NOT business children — listed here so a future "just add
# everything" sweep trips this test and has to read the reasons.
_MUST_NOT_BE_LISTED = [
    "stripe_webhook_events",   # platform-global, no business_id
    "site_events",             # anonymous marketing traffic, no business_id
    "vertical_knowledge",      # Feed 2: k-anonymous BY DESIGN
    "email_suppressions",      # recipient-keyed deliverability protection
    "entity_groups",           # owner-keyed, no business_id column
    "scheduler_lease", "fx_rates", "waitlist",
]


def test_known_missing_tables_are_now_listed():
    from account_lifecycle import BUSINESS_CHILD_TABLES
    missing = [t for t in _MUST_BE_LISTED if t not in BUSINESS_CHILD_TABLES]
    assert not missing, f"drifted again — absent from BUSINESS_CHILD_TABLES: {missing}"


def test_platform_tables_stay_out():
    from account_lifecycle import BUSINESS_CHILD_TABLES
    wrong = [t for t in _MUST_NOT_BE_LISTED if t in BUSINESS_CHILD_TABLES]
    assert not wrong, f"platform/user-keyed tables crept in: {wrong}"


def test_no_duplicate_tables():
    from account_lifecycle import BUSINESS_CHILD_TABLES
    dupes = {t for t in BUSINESS_CHILD_TABLES
             if BUSINESS_CHILD_TABLES.count(t) > 1}
    assert not dupes, f"duplicates: {dupes}"


@pytest.mark.parametrize("child,parent", [
    ("customer_ledger", "contacts"),
    ("customer_ledger", "invoices"),
    ("customer_ledger", "offerings"),
    ("time_entries", "contacts"),
    ("campaign_sends", "campaigns"),
    ("campaign_sends", "contacts"),
    ("rule_runs", "practitioner_rules"),
    ("gl_sync_queue", "journal_entries"),
    ("period_edit_overrides", "accounting_periods"),
    ("coa_external_mappings", "chart_of_accounts"),
    ("outbound_transfers", "contractors"),
    ("academy_lessons", "academy_courses"),
    ("sms_messages", "contacts"),
])
def test_children_delete_before_their_parents(child, parent):
    """FK safety: a child that cites a parent must be swept first, or a
    NO-ACTION constraint 409s the deletion mid-walk."""
    from account_lifecycle import BUSINESS_CHILD_TABLES as T
    assert T.index(child) < T.index(parent), f"{child} must precede {parent}"


def test_contacts_anchors_the_fk_walk_and_the_ledger_closes_it():
    """Two different orderings, both load-bearing.

    contacts still anchors the FOREIGN-KEY walk — everything that cites
    it must be deleted first. audit_log then follows as the final entry
    for a different reason entirely: it is append-only at the database,
    so deleting the business row cascades into it and that cascade is
    REFUSED while rows remain. The ledger is therefore erased last (via
    the tombstone-writing RPC), leaving the smallest possible window in
    which a late writer could re-block the cascade.
    """
    from account_lifecycle import BUSINESS_CHILD_TABLES as T
    assert T[-1] == "audit_log"
    assert T[-2] == "contacts"
    assert T.index("contacts") > T.index("invoices")
    assert T.index("contacts") > T.index("sessions")
