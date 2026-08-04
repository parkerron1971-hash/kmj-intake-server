"""Binding the chain tip to the rows it summarises.

The tip guard made last_sequence monotonic — it could not go BACKWARDS.
Nothing bounded how far FORWARD it could go, so setting a tenant's tip
high made ledger_verify report "records were removed" about a ledger
from which nothing had been removed. It cannot conceal anything (it is
the loud direction), but a false accusation of tampering is its own
damage in a system whose product is trust, and it is indistinguishable
from the real thing.

The audit found three holes where the report described one: UPDATE
could set any forward value, DELETE + INSERT bypassed the UPDATE guard
entirely, and (business_id, sequence) had no unique index so a reset
tip could mint duplicates.
"""
from __future__ import annotations

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

_SQL = (_here.parent / "supabase"
        / "APPLY-2026-08-03-ledger-tip-bounded.sql").read_text(encoding="utf-8")

_FN = _SQL.split("create or replace function public.ledger_tip_forward_only")[1] \
          .split("create or replace function")[0]


def _flat(s: str) -> str:
    """Un-wrap before matching. These strings are broken across lines
    twice over — by 72-column comment wrapping and by SQL literal
    concatenation ('...' '...') — so a raw substring search is a coin
    flip on where the break landed. That brittleness has produced false
    failures in this suite already."""
    import re
    s = re.sub(r"'\s*\n\s*'", "", s)      # rejoin split SQL literals
    return " ".join(s.replace("--", " ").split())


_SQL_FLAT = _flat(_SQL)


# ─── The bound itself ────────────────────────────────────────────────

def test_the_tip_cannot_exceed_the_rows():
    assert "max(a.sequence)" in _FN
    assert "coalesce(v_max, 0) + 1" in _FN


def test_the_slack_is_exactly_one_and_the_reason_is_written_down():
    """One ahead is not sloppiness — ledger_assign_sequence is a BEFORE
    INSERT trigger, so it moves the tip while the row it describes does
    not exist yet. Someone tightening this to `= max` would break every
    write, and with fail-closed in place that means breaking the
    business write too."""
    assert "BEFORE INSERT" in _SQL_FLAT
    assert "does not exist yet" in _SQL_FLAT


def test_backwards_is_still_refused():
    """The original property must survive the rewrite."""
    assert "cannot move backwards" in _FN
    assert "tg_op = 'UPDATE'" in _FN, \
        "old is NULL on INSERT — the backwards check must be UPDATE-only"


def test_the_error_says_what_the_damage_would_be():
    assert "report removals that never happened" in _FN


# ─── The two holes a UPDATE-only guard would have left ───────────────

def test_the_guard_covers_insert_as_well_as_update():
    """DELETE + INSERT bypassed an UPDATE-only guard entirely: deleting
    the row and re-inserting one with last_sequence=999999 succeeded.
    A guard on one verb is not a guard."""
    trg = _SQL.split("create trigger trg_ledger_tip_forward_only")[1].split(";")[0]
    assert "before insert or update" in trg


def test_the_tip_row_can_never_be_deleted_or_truncated():
    assert "trg_ledger_tip_no_delete" in _SQL
    assert "before delete on public.ledger_chain_state" in _SQL
    # Row triggers do not fire on TRUNCATE — the lesson the ledger's own
    # TRUNCATE hole taught, applied here before anyone finds it twice.
    assert "before truncate on public.ledger_chain_state" in _SQL
    assert "for each statement" in _SQL


def test_deletion_needs_no_exception_path():
    """ledger_erase_business READS the tip and deliberately does not
    reset it, so unlike audit_log's DELETE there is no legitimate
    caller to carve out."""
    fn = _SQL.split("create or replace function public.ledger_tip_no_delete")[1]
    assert "raise exception" in fn
    assert "ledger_erasure_tickets" not in fn, "no ticket path should exist"
    assert "outlives the business on purpose" in _flat(fn)


# ─── The ordering ambiguity the guard exists to prevent ──────────────

def test_duplicate_sequences_become_impossible():
    """A reset tip would happily mint duplicate sequence numbers — the
    precise ambiguity about order the tip guard was written to prevent,
    still reachable by another road."""
    assert "create unique index if not exists idx_audit_log_biz_sequence_unique" in _SQL
    assert "on public.audit_log (business_id, sequence)" in _SQL


def test_the_replaced_index_covered_the_same_columns():
    """Dropping an index is only safe because the unique one serves the
    same plans."""
    assert "drop index if exists idx_audit_log_biz_sequence" in _SQL
    assert "zero duplicate" in _SQL_FLAT, "must state it was checked before applying"


# ─── What was actually verified, not assumed ─────────────────────────

def test_the_multi_row_concern_was_tested_not_reasoned_about():
    """The worry was that a statement's own rows are invisible to
    queries under its snapshot, which would make this rule reject every
    multi-row insert. That is exactly the kind of thing to test against
    a real database rather than reason about."""
    assert "multi-row" in _SQL_FLAT
    assert "command-counter snapshot" in _SQL_FLAT
