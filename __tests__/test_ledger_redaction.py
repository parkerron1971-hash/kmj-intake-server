"""Honouring one person's erasure request without destroying a practice's
record.

The db-trigger tier copies row contents into audit_log.payload, so a
therapist's client sits inside a table that refuses deletion. The only
removal path erased the whole practice — meaning a single client's
request could not be honoured at all unless the practice destroyed its
own audit trail.

The resolution: the FACT of an action is the audit trail; the CONTENTS
of the records it touched are the personal data. Only the second goes.
"""
from __future__ import annotations

import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from test_i2_gl_sync import FakeSB  # noqa: E402

_SQL = (_here.parent / "supabase" / "APPLY-2026-08-03-ledger-redaction.sql"
        ).read_text(encoding="utf-8")


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    fb.rows("businesses").append({
        "id": "b1", "name": "Practice", "owner_id": "owner1",
        "settings": {}, "type": "therapist"})
    return fb


# ─── The guard: redaction must not become an edit hatch ──────────────

def test_only_contents_may_change():
    """Redaction is the first and only permitted UPDATE to this table.
    Without a column-level check it would be a way to rewrite a verb, an
    actor, or an outcome — the exact tampering the ledger exists to
    prevent."""
    assert "to_jsonb(old) - 'payload' - 'result' - 'redacted_at'" in _SQL
    assert "is distinct from" in _SQL
    assert "every other column" in _SQL


def test_redaction_may_only_empty_never_write():
    assert "new.payload <> '{}'::jsonb or new.result <> '{}'::jsonb" in _SQL
    assert "never write them" in _SQL


def test_update_requires_a_ticket():
    """A bare UPDATE still raises. Only the RPC — which records what it
    is doing first — issues the permit."""
    assert "ledger_redaction_tickets" in _SQL
    assert "rows are never updated" in _SQL


def test_a_redacted_row_must_say_when():
    assert "new.redacted_at is null" in _SQL


# ─── The chain survives, and says so ─────────────────────────────────

def test_row_hash_is_never_recomputed():
    """The load-bearing decision. Recomputing would force a rewrite of
    every later row (their prev_hash points at this one) — which is
    indistinguishable from tampering. Leaving it means the chain still
    links, AND the removed content stays committed to: anyone holding a
    copy can prove it hashed to the recorded value."""
    redact = _SQL.split("create or replace function public.ledger_redact_subject")[1]
    update = redact.split("update public.audit_log")[1].split(";")[0]
    assert "row_hash" not in update, "redaction must not touch row_hash"
    assert "payload = '{}'::jsonb" in update and "result  = '{}'::jsonb" in update


def test_verification_declares_redactions_rather_than_calling_them_broken():
    verify = _SQL.split("create or replace function public.ledger_verify")[1]
    assert "v_redacted := v_redacted + 1" in verify
    assert "DECLARED absence" in verify
    # Linkage is still checked for redacted rows — only the recompute is
    # skipped, because the contents are legitimately gone.
    assert "prev_hash does not match the preceding row" in verify
    assert "redacted       bigint," in _SQL, "the count must reach the caller"


def test_the_fact_of_the_action_survives():
    """Everything that makes the row an audit record is untouched."""
    redact = _SQL.split("create or replace function public.ledger_redact_subject")[1]
    update = redact.split("update public.audit_log")[1].split("where")[0]
    for kept in ("verb", "actor_id", "sequence", "authorized_by", "created_at"):
        assert kept not in update, f"{kept} must survive a redaction"


# ─── Finding the subject ─────────────────────────────────────────────

def test_matches_both_subject_refs_and_the_legacy_target_columns():
    fn = _SQL.split("create or replace function public.ledger_redact_subject")[1]
    assert "subject_refs @>" in fn        # GIN-indexed array
    assert "target_type = p_subject_type" in fn   # older single-target rows


def test_a_request_with_no_matches_is_still_recorded():
    """"We looked and there was nothing" is a meaningful answer to give
    a data subject."""
    fn = _SQL.split("create or replace function public.ledger_redact_subject")[1]
    head = fn.split("if coalesce(v_count, 0) = 0 then")[1].split("return 0;")[0]
    assert "insert into public.ledger_redactions" in head


# ─── The endpoint ────────────────────────────────────────────────────

def test_redaction_is_owner_only(fake):
    """The practice's legal obligation, and the one operation that can
    empty rows in an append-only table."""
    import auditor_portal as ap
    body = ap.RedactBody(business_id="b1", subject_type="contacts",
                         subject_id="c1")
    with pytest.raises(HTTPException) as e:
        ap.redact_subject(body, type("U", (), {"id": "member1", "email": "m@x.com"})())
    assert e.value.status_code == 403


def test_missing_subject_is_refused(fake):
    import auditor_portal as ap
    owner = type("U", (), {"id": "owner1", "email": "o@x.com"})()
    with pytest.raises(HTTPException) as e:
        ap.redact_subject(
            ap.RedactBody(business_id="b1", subject_type="", subject_id="c1"), owner)
    assert e.value.status_code == 400


def test_a_failed_redaction_says_nothing_changed(fake, monkeypatch):
    """Never report a completed erasure that did not happen — the data
    subject is relying on the answer."""
    import auditor_portal as ap
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: None)
    owner = type("U", (), {"id": "owner1", "email": "o@x.com"})()
    with pytest.raises(HTTPException) as e:
        ap.redact_subject(
            ap.RedactBody(business_id="b1", subject_type="contacts",
                          subject_id="c1"), owner)
    assert e.value.status_code == 503
    assert "Nothing was changed" in str(e.value.detail)


def test_the_redaction_itself_is_recorded():
    src = pathlib.Path(_here.parent / "auditor_portal.py").read_text(encoding="utf-8")
    body = src.split("def redact_subject(")[1].split("# ─── The public read")[0]
    assert 'verb="ledger:redacted"' in body
    assert "_require_owner(" in body
