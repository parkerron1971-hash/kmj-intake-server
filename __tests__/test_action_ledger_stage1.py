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
