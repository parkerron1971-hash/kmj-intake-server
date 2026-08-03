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
    assert "is_bulk(action)" in body, "bulk must not run unattended"
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
