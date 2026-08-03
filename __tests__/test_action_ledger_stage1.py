"""Action Ledger Stage 1 — capture.

The database now owns the guarantees the application used to merely
promise: append-only, per-tenant sequencing, and a tombstone on the one
sanctioned removal path. These tests cover the Python half — the SQL
half is pinned by the migration's own VERIFY block and was proven
against production on 2026-08-03 (UPDATE and DELETE both raise even for
service_role, which bypasses RLS).
"""
from __future__ import annotations

import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import audit_log  # noqa: E402


# ─── The sixth field + field five ────────────────────────────────────

def test_record_carries_authorized_by_and_subject_refs(monkeypatch):
    sent = {}
    monkeypatch.setattr(audit_log.sb_clients, "sb_post_as_service",
                        lambda path, row, prefer=None: sent.update(row) or [row])
    audit_log.record("b1", actor_type="chief", verb="create_invoice",
                     authorized_by="scheduled:C:recurring",
                     subject_refs=[{"type": "invoice", "id": "inv_1"},
                                   {"type": "contact", "id": "c_9"}])
    assert sent["authorized_by"] == "scheduled:C:recurring"
    assert sent["subject_refs"] == [{"type": "invoice", "id": "inv_1"},
                                    {"type": "contact", "id": "c_9"}]


def test_subject_refs_shape_is_enforced(monkeypatch):
    """Field 5 has to stay queryable — vague refs are the failure the
    spec calls out, so malformed entries are dropped, not stored."""
    sent = {}
    monkeypatch.setattr(audit_log.sb_clients, "sb_post_as_service",
                        lambda path, row, prefer=None: sent.update(row) or [row])
    audit_log.record("b1", actor_type="user", verb="x",
                     subject_refs=["not-a-dict", {"type": "invoice"},
                                   {"id": "orphan"}, {"type": "c", "id": "ok"}])
    assert sent["subject_refs"] == [{"type": "c", "id": "ok"}]


def test_target_falls_back_into_subject_refs(monkeypatch):
    """The 13 existing call sites pass target_type/target_id. They keep
    working AND land in the queryable array without being rewritten."""
    sent = {}
    monkeypatch.setattr(audit_log.sb_clients, "sb_post_as_service",
                        lambda path, row, prefer=None: sent.update(row) or [row])
    audit_log.record("b1", actor_type="user", verb="x",
                     target_type="invoice", target_id="inv_7")
    assert sent["subject_refs"] == [{"type": "invoice", "id": "inv_7"}]


def test_python_never_sets_sequence_or_hashes(monkeypatch):
    """Sequence and the chain are assigned by the DB trigger under a
    per-tenant advisory lock. A Python writer setting them would fork
    the chain under concurrency — the whole reason hashing moved into
    Postgres."""
    sent = {}
    monkeypatch.setattr(audit_log.sb_clients, "sb_post_as_service",
                        lambda path, row, prefer=None: sent.update(row) or [row])
    audit_log.record("b1", actor_type="chief", verb="x")
    for forbidden in ("sequence", "prev_hash", "row_hash"):
        assert forbidden not in sent


# ─── The controlled vocabulary ───────────────────────────────────────

def test_vocabulary_covers_every_chief_verb():
    """The drift pin: the ledger's vocabulary must contain every verb
    Chief can actually dispatch. This is what makes verb_registered
    meaningful instead of decorative."""
    from chief_of_staff import ACTION_HANDLERS
    vocab = audit_log.vocabulary()
    missing = sorted(set(ACTION_HANDLERS) - set(vocab))
    assert not missing, f"verbs Chief can run but the ledger doesn't know: {missing}"


def test_vocabulary_namespaces_non_chief_sources():
    vocab = audit_log.vocabulary()
    assert vocab["create_invoice"]["namespace"] == "chief"
    assert vocab["create_invoice"]["reversibility"] == "C"
    assert vocab["db:invoices_update"]["namespace"] == "db"
    assert any(v.startswith("webhook:") for v in vocab)
    assert "ledger:erasure" in vocab


def test_sync_is_idempotent_and_never_raises(monkeypatch):
    calls = []
    monkeypatch.setattr(audit_log.sb_clients, "sb_post_as_service",
                        lambda path, rows, prefer=None: calls.append((path, rows)))
    n = audit_log.sync_action_types()
    assert n > 150
    assert "on_conflict=verb" in calls[0][0]

    def _boom(*a, **kw):
        raise RuntimeError("supabase down")
    monkeypatch.setattr(audit_log.sb_clients, "sb_post_as_service", _boom)
    assert audit_log.sync_action_types() == 0     # degrades, never raises


# ─── Erasure: the one sanctioned removal path ────────────────────────

def test_erasure_routes_through_the_tombstone_rpc():
    """A plain DELETE on audit_log raises at the database. Erasure must
    go through the RPC that writes a tombstone first — and the ledger
    must be erased LAST, because deleting the business row cascades into
    audit_log and that cascade is refused while rows remain."""
    import account_lifecycle as al
    src = pathlib.Path(_here.parent / "account_lifecycle.py").read_text(encoding="utf-8")
    assert "rpc/ledger_erase_business" in src
    body = src.split("async def _delete_table_rows(")[1].split("\n\n\n")[0]
    assert 'table == "audit_log"' in body, "audit_log must not take the plain DELETE path"
    assert al.BUSINESS_CHILD_TABLES[-1] == "audit_log", \
        "the ledger is erased last so the business-row cascade has nothing to refuse"


# ─── Stage 1b: coverage ──────────────────────────────────────────────

def test_workflow_dispatcher_audits_and_refuses_bulk():
    """The last ACTION_HANDLERS dispatcher that ran with no record at
    all. A workflow step is unattended by definition, so bulk is refused
    the same way it is on the scheduler."""
    src = pathlib.Path(_here.parent / "workflow_engine.py").read_text(encoding="utf-8")
    body = src.split("Fall back to Chief's existing action verbs")[1][:2600]
    assert "audit_log.record(" in body, "workflow dispatch must leave a ledger row"
    # Stage 3 moved the bulk rule into the shared evaluator so scheduler,
    # workflow and notification paths cannot drift apart.
    assert "policy_engine" in body, "bulk/vertical rules come from the engine"
    assert 'source="workflow"' in body
    assert "authorized_by=authorized_by" in body


def test_audit_read_hides_the_db_tier_by_default(monkeypatch):
    """Two tiers, one table: db_trigger rows double up with the
    application row for the same action, so History reads the intent
    tier — but a proof must be able to ask for everything."""
    seen = {}

    def _get(q):
        seen["q"] = q
        return []
    monkeypatch.setattr(audit_log.sb_clients, "sb_get_as_service",
                        lambda q: [{"id": "b1", "owner_id": "u1"}]
                        if q.startswith("/businesses") else _get(q))
    monkeypatch.setattr("business_users_router.require_role",
                        lambda b, u, r: "owner")
    u = type("U", (), {"id": "u1", "email": "u@x.com"})()

    out = audit_log.read_audit("b1", user=u)
    assert "source=not.eq.db_trigger" in seen["q"]
    assert out["tier"] == "application"

    out = audit_log.read_audit("b1", include_db=True, user=u)
    assert "source=not.eq.db_trigger" not in seen["q"]
    assert out["tier"] == "all"


def test_namespaced_verbs_survive_the_filter(monkeypatch):
    """db:/rules:/webhook: verbs contain a colon — the old sanitizer
    stripped it and would have silently matched nothing."""
    seen = {}
    monkeypatch.setattr(audit_log.sb_clients, "sb_get_as_service",
                        lambda q: [{"id": "b1", "owner_id": "u1"}]
                        if q.startswith("/businesses") else seen.update(q=q) or [])
    monkeypatch.setattr("business_users_router.require_role",
                        lambda b, u, r: "owner")
    u = type("U", (), {"id": "u1", "email": "u@x.com"})()
    audit_log.read_audit("b1", verb="db:contacts_update", user=u)
    assert "verb=eq.db:contacts_update" in seen["q"]


# ─── Stage 2: the hash chain ─────────────────────────────────────────

def test_canonical_serialization_is_frozen_and_versioned():
    """Stage 5's Merkle proofs recompute from stored rows, so the byte
    recipe cannot change silently. It is versioned, and the version is
    hashed INTO the material so a v2 can never collide with a v1."""
    sql = pathlib.Path(
        _here.parent / "supabase" / "APPLY-2026-08-03-ledger-hash-chain.sql"
    ).read_text(encoding="utf-8")
    assert "ledger_canonical_v1" in sql
    assert "'v1'," in sql, "the version must be inside the hashed material"
    assert "FROZEN" in sql
    # Every field that a tamperer would want to change must be covered.
    for field in ("business_id", "created_at", "sequence", "actor_type",
                  "actor_id", "verb", "ok", "summary", "authorized_by",
                  "subject_refs", "payload", "result"):
        assert f"r.{field}" in sql, f"{field} is not covered by the hash"


def test_chain_is_built_under_a_per_tenant_lock():
    """The reason hashing lives in Postgres: read-the-tip-then-insert in
    the application forks the chain when two writers race."""
    sql = pathlib.Path(
        _here.parent / "supabase" / "APPLY-2026-08-03-ledger-hash-chain.sql"
    ).read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in sql
    assert "for update" in sql.lower()
    assert "sha256" in sql


def test_verify_endpoint_reports_rather_than_reassures(monkeypatch):
    """The portal rule applies to the API too: report the state, do not
    summarise it into a claim. Pre-chain rows must never be counted as
    intact."""
    calls = {}

    def _get(q):
        if q.startswith("/businesses"):
            return [{"id": "b1", "owner_id": "u1"}]
        if q.startswith("/ledger_tombstones"):
            return [{"erased_at": "2026-08-03", "rows_erased": 3,
                     "first_sequence": 1, "last_sequence": 3,
                     "reason": "gdpr_erasure"}]
        if "row_hash=is.null" in q:
            return [{"id": "old1"}, {"id": "old2"}]
        return []
    monkeypatch.setattr(audit_log.sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(audit_log.sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: calls.update(path=p) or
                        [{"intact": False, "checked": 9, "broken_at": 4,
                          "reason": "row contents do not match row_hash - this row was altered",
                          "gaps": [3]}])
    monkeypatch.setattr("business_users_router.require_role",
                        lambda b, u, r: "owner")
    u = type("U", (), {"id": "u1", "email": "u@x.com"})()

    out = audit_log.verify_chain("b1", user=u)
    assert calls["path"] == "/rpc/ledger_verify"   # the DB owns the recipe
    assert out["intact"] is False
    assert out["broken_at"] == 4
    assert out["gaps"] == [3]
    assert out["erasures"][0]["rows_erased"] == 3  # the gap is explained
    assert out["unverifiable_rows"] == 2
    assert out["note"], "pre-chain rows must be declared, not glossed over"


def test_verify_never_claims_intact_with_nothing_hashed():
    """The honesty guard, found by running the verifier against
    production: every real chain reported intact while carrying zero
    hashes, because rows predating Stage 2 are skipped. A tamper-
    evidence check that says "verified" when it verified nothing is
    worse than no check at all."""
    sql = pathlib.Path(
        _here.parent / "supabase" / "APPLY-2026-08-03-ledger-hash-chain.sql"
    ).read_text(encoding="utf-8")
    assert "if v_hashed = 0 then" in sql
    assert "nothing to verify" in sql
    # and the count travels to the caller so a UI can say so too
    assert "hashed         bigint," in sql
    py = pathlib.Path(_here.parent / "audit_log.py").read_text(encoding="utf-8")
    assert '"hashed": report.get("hashed", 0)' in py


# ─── Ledger access: the two dead ends ────────────────────────────────

def test_viewer_seat_can_read_history(monkeypatch):
    """The sidebar showed every team seat a History leaf while the
    endpoint demanded member+ — a clickable thing that dead-ended in a
    403. History is a trust surface, not an owner secret."""
    seen = {}
    monkeypatch.setattr(audit_log.sb_clients, "sb_get_as_service",
                        lambda q: [{"id": "b1", "owner_id": "someone-else"}]
                        if q.startswith("/businesses") else seen.update(q=q) or [])
    called = {}
    monkeypatch.setattr("business_users_router.require_role",
                        lambda b, u, r: called.update(min_role=r) or "viewer")
    monkeypatch.setattr("business_collaborators_router.is_active_accountant",
                        lambda b, u: False)
    u = type("U", (), {"id": "v1", "email": "v@x.com"})()
    out = audit_log.read_audit("b1", user=u)
    assert out["ok"] is True
    assert called["min_role"] == "viewer"


def test_accountant_collaborator_can_read_history(monkeypatch):
    """The single audience most likely to be handed an audit trail could
    not open it: accountants live in business_collaborators, not
    business_users, so require_role refused them outright."""
    monkeypatch.setattr(audit_log.sb_clients, "sb_get_as_service",
                        lambda q: [{"id": "b1", "owner_id": "someone-else"}]
                        if q.startswith("/businesses") else [])

    def _boom(b, u, r):
        raise AssertionError("an accountant must not fall through to require_role")
    monkeypatch.setattr("business_users_router.require_role", _boom)
    monkeypatch.setattr("business_collaborators_router.is_active_accountant",
                        lambda b, u: True)
    u = type("U", (), {"id": "cpa1", "email": "cpa@x.com"})()
    assert audit_log.read_audit("b1", user=u)["ok"] is True


def test_ledger_read_never_returns_row_contents():
    """Widening the audience is only safe because the query selects no
    payload/result — the db-trigger tier's before/after record contents
    stay out of it. Anything exposing contents must re-gate."""
    src = pathlib.Path(_here.parent / "audit_log.py").read_text(encoding="utf-8")
    body = src.split("def read_audit(")[1].split("@router.get(\"/verify\")")[0]
    select = body.split("&select=")[1].split('"')[0]
    assert "payload" not in select
    assert "result" not in select


def test_accountant_nav_includes_history():
    fe = pathlib.Path(
        r"C:\Users\kmccl\solutionist-studio\solutionist-studio\src\core"
        r"\components\SolutionistSidebar.tsx")
    if not fe.exists():
        return
    src = fe.read_text(encoding="utf-8")
    keep = src.split("const keep = new Set([")[1].split("])")[0]
    assert "'history'" in keep, "accountants must be able to reach the ledger"


# ─── The exportable artifact ─────────────────────────────────────────

def test_export_never_widens_the_column_list():
    """The export is the widest audience the ledger has — it leaves the
    building entirely. It must read through the SAME select list, so a
    column can't be widened for one surface and forgotten on another."""
    src = pathlib.Path(_here.parent / "audit_log.py").read_text(encoding="utf-8")
    assert "LEDGER_SELECT" in src
    sel = src.split("LEDGER_SELECT = (")[1].split(")")[0]
    assert "payload" not in sel and "result" not in sel
    # And the export goes through ledger_entries(), not its own query.
    rep = pathlib.Path(_here.parent / "ledger_report.py").read_text(encoding="utf-8")
    assert "audit_log.ledger_entries(" in rep
    assert "/audit_log?" not in rep, "the report must not build its own query"


def test_report_verdict_never_reassures():
    import ledger_report as lr
    nothing = lr._verdict_line({"hashed": 0, "checked": 11, "intact": True})
    assert "cannot be proven" in nothing or "nothing here can be proven" in nothing
    broken = lr._verdict_line({"hashed": 5, "intact": False, "broken_at": 4,
                               "reason": "row contents do not match row_hash"})
    assert "#4" in broken
    intact = lr._verdict_line({"hashed": 5, "checked": 5, "intact": True})
    assert "5" in intact
    for line in (nothing, broken, intact):
        low = line.lower()
        assert "everything" not in low and "all good" not in low
        assert "nothing unusual" not in low


def test_csv_carries_the_chain_state_and_the_erasures():
    import ledger_report as lr
    data = {
        "business_name": "T", "generated_at": "2026-08-03T00:00:00Z", "range": {},
        "verification": {"intact": False, "checked": 5, "hashed": 5, "broken_at": 4,
                         "first_sequence": 1, "last_sequence": 5,
                         "unverifiable_rows": 0, "gaps": [3],
                         "erasures": [{"erased_at": "2026-08-03", "rows_erased": 2,
                                       "first_sequence": 2, "last_sequence": 3,
                                       "reason": "gdpr_erasure"}]},
        "entries": [{"sequence": 1, "created_at": "x", "actor_id": "chief",
                     "verb": "create_task", "ok": True,
                     "authorized_by": "chat:owner:A", "subject_refs": []}],
        "entry_count": 1}
    text = lr.to_csv(data)
    assert "Carrying a fingerprint" in text
    assert "Erasures on record" in text and "gdpr_erasure" in text
    assert "Permitted by" in text          # field 6 travels with the artifact
    assert "Sequence gaps after" in text


def test_pdf_renders_or_degrades_to_csv():
    """reportlab is a real dependency but every caller guards ImportError
    and falls back to CSV — the floor is that the artifact always exists."""
    import ledger_report as lr
    data = {"business_name": "T", "generated_at": "2026-08-03T00:00:00Z",
            "range": {}, "entry_count": 0, "entries": [],
            "verification": {"intact": True, "checked": 2, "hashed": 2,
                             "first_sequence": 1, "last_sequence": 2,
                             "unverifiable_rows": 0, "gaps": [], "erasures": []}}
    try:
        out = lr.to_pdf(data, {"settings": {}}, generated_by="t")
        assert out[:4] == b"%PDF"
    except ImportError:
        pass
    src = pathlib.Path(_here.parent / "audit_log.py").read_text(encoding="utf-8")
    body = src.split("def export_ledger(")[1].split("@router.get")[0]
    assert "except ImportError" in body and "format=csv" in body


def test_truncated_table_says_so():
    """A truncated table must never be mistaken for a complete one —
    and the remedy it offers has to be real. The first version told
    readers to "export CSV for the complete range" while the CSV was
    capped at the same 500 rows: the document asserted the opposite of
    the truth about itself."""
    rep = pathlib.Path(_here.parent / "ledger_report.py").read_text(encoding="utf-8")
    assert "must never" in rep
    assert "total_in_range" in rep, "the report must count what it did not show"
    assert "narrow the date" in rep, "the remedy must actually work"
    assert "Export CSV for the complete range" not in rep


def test_failed_actions_keep_their_message_but_never_their_payload():
    """The leak the security review found, and the line it sits on.

    A half-failed handler returns a DICT — {"ok": False, "contact":
    {...}} — and str()-ing that into `error` put contact PII into a
    column that travels to an external auditor's CSV. But a STRING
    result is the handler's own failure message, which the practitioner
    needs. Keep the message; never stringify the structure."""
    import audit_log as al
    assert al._error_text({"result": "error: recipient suppressed"})         == "error: recipient suppressed"
    leaky = {"label": "Send invoice",
             "result": {"ok": False, "contact": {"email": "jane@private.com",
                                                 "phone": "555-0100"}}}
    out = al._error_text(leaky)
    assert "jane@private.com" not in out and "555-0100" not in out
    assert out == "failed: Send invoice"
    assert al._error_text({}) == "action failed with no error message"


def test_chain_tip_is_guarded_and_locked_down():
    """Found by accident during the final audit: a test statement ran
    `update ledger_chain_state set last_row_hash='forged'` and it
    SUCCEEDED. The rows themselves held (their triggers refused), and
    the tip was rebuilt from the rows — which is the reassuring half:
    audit_log is authoritative, chain_state is only its cache.

    But a BACKWARDS sequence would reuse a number that already exists,
    and a duplicated sequence makes the ledger ambiguous about order —
    which is most of what a ledger is for. A forged hash is
    self-detecting on the next walk; a reused sequence is not."""
    sql = pathlib.Path(
        _here.parent / "supabase" / "APPLY-2026-08-03-ledger-tip-guard.sql"
    ).read_text(encoding="utf-8")
    assert "new.last_sequence < old.last_sequence" in sql
    assert "before update on public.ledger_chain_state" in sql
    # And the guard tables lock down consistently (whitespace-tolerant:
    # the statements are column-aligned in the file).
    flat = " ".join(sql.split())
    for t in ("ledger_chain_state", "ledger_tombstones"):
        assert f"revoke all on public.{t} from anon, authenticated" in flat
    # last_row_hash stays writable on purpose — the legitimate repair
    # path needs it, and a wrong hash reports itself.
    assert "NOT locked" in sql
