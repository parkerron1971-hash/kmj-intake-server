"""delete_contact — the guard that stops Chief erasing a client's history.

`contacts` has no soft-delete column (the status CHECK allows only
lead/active/inactive/churned/vip) and no deleted_at, so the handler issues a
real DELETE. Thirteen tables point at contacts.id: `sessions` and
`academy_enrollments` are ON DELETE CASCADE and are DESTROYED with the row;
eight more are SET NULL and survive pointing at nobody; `orders` and
`campaign_sends` have no FK at all; `sms_messages` is NO ACTION and makes the
database refuse outright.

Which meant "delete John Smith", typed into a chat box, could erase an entire
appointment history and unattribute the revenue attached to it — with no
confirmation step, while the app's own Delete button has had a modal all along.

What these tests defend:
  • a contact with ANY attached record is NOT deleted,
  • the refusal says what would have been lost, and reads as a decision
    rather than an error,
  • a clean contact still deletes (the guard is not a ban),
  • there is no override parameter — a model that retries with confirm/force
    must not get through,
  • the probe never blocks on a table that errors or doesn't exist.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import asyncio

import pytest

import chief_of_staff as cos

BIZ = {"id": "biz1", "name": "Test Co"}
CONTACT = {"id": "c1", "name": "Sarah Chen"}


def _run(coro):
    return asyncio.run(coro)


def _patch_sb(monkeypatch, dependents: dict, *, explode: set = frozenset()):
    """Fake _sb. `dependents` maps table name → row count. Any table in
    `explode` raises, standing in for 'not present in this environment'."""
    calls = []

    async def _fake(client, method, path, body=None):
        calls.append((method, path))
        if method == "GET" and path.startswith("/contacts?id=eq."):
            return [CONTACT]
        if method == "GET":
            table = path.lstrip("/").split("?", 1)[0]
            if table in explode:
                raise RuntimeError("relation does not exist")
            return [{"id": f"{table}-{i}"} for i in range(dependents.get(table, 0))]
        return []

    monkeypatch.setattr(cos, "_sb", _fake)
    return calls


def _delete(contact_id="c1", **extra):
    return _run(cos.handle_delete_contact(
        None, BIZ, {"type": "delete_contact", "contact_id": contact_id, **extra}))


# ─── the guard ────────────────────────────────────────────────────────

def test_contact_with_sessions_is_not_deleted():
    """The CASCADE case — the one that silently destroyed appointment history."""
    with pytest.MonkeyPatch.context() as mp:
        calls = _patch_sb(mp, {"sessions": 4})
        out = _delete()
    assert not any(m == "DELETE" for m, _ in calls), "the contact must survive"
    assert "4 sessions" in out["result"]
    assert "erase" in out["result"].lower()


def test_contact_with_only_orphaning_records_is_not_deleted():
    """SET NULL rows are not destroyed, but the practitioner still loses the
    link between an invoice and the person who owes it."""
    with pytest.MonkeyPatch.context() as mp:
        calls = _patch_sb(mp, {"invoices": 2})
        out = _delete()
    assert not any(m == "DELETE" for m, _ in calls)
    assert "2 invoices" in out["result"]
    assert "nobody attached" in out["result"].lower()
    assert "erase" not in out["result"].lower(), (
        "SET NULL rows are not erased — the message must not claim they are")


def test_refusal_names_everything_attached():
    with pytest.MonkeyPatch.context() as mp:
        _patch_sb(mp, {"sessions": 3, "invoices": 2, "orders": 1})
        out = _delete()
    for fragment in ("3 sessions", "2 invoices", "1 order"):
        assert fragment in out["result"], f"missing {fragment!r} in: {out['result']}"


def test_single_record_reads_as_singular():
    with pytest.MonkeyPatch.context() as mp:
        _patch_sb(mp, {"sessions": 1})
        out = _delete()
    assert "1 session" in out["result"] and "1 sessions" not in out["result"]


def test_large_counts_are_capped_not_paged():
    with pytest.MonkeyPatch.context() as mp:
        _patch_sb(mp, {"sessions": 500})
        out = _delete()
    assert f"{cos._DEP_PROBE_LIMIT - 1}+ sessions" in out["result"]


# ─── the guard is not a ban ──────────────────────────────────────────

def test_clean_contact_still_deletes():
    """A typo or a duplicate with no history is exactly what this verb is for."""
    with pytest.MonkeyPatch.context() as mp:
        calls = _patch_sb(mp, {})
        out = _delete()
    assert any(m == "DELETE" for m, _ in calls), "a clean contact should delete"
    assert out["result"] == "deleted"


# ─── no override ─────────────────────────────────────────────────────

@pytest.mark.parametrize("override", [
    {"confirm": True}, {"force": True}, {"confirmed": "yes"},
    {"cascade": True}, {"i_am_sure": True},
])
def test_no_parameter_can_talk_past_the_guard(override):
    """Deliberately no bypass flag: an override is something the model can set
    on a retry after reading the refusal, and destroying a client's records
    should require a human to mean it. The app's Delete button — which has a
    confirmation dialog — is that path."""
    with pytest.MonkeyPatch.context() as mp:
        calls = _patch_sb(mp, {"sessions": 2}, )
        out = _delete(**override)
    assert not any(m == "DELETE" for m, _ in calls), (
        f"{override} must not reach the delete")
    assert "sessions" in out["result"]


# ─── robustness ──────────────────────────────────────────────────────

def test_a_missing_table_does_not_block_the_check():
    """A table absent in some environment is skipped, and the remaining
    evidence still refuses. Under-reporting can shorten the explanation; it
    can never turn a refusal into a delete."""
    with pytest.MonkeyPatch.context() as mp:
        calls = _patch_sb(mp, {"sessions": 2},
                          explode={"orders", "academy_enrollments"})
        out = _delete()
    assert not any(m == "DELETE" for m, _ in calls)
    assert "2 sessions" in out["result"]


def test_probe_covers_both_cascade_tables():
    """sessions and academy_enrollments are the two ON DELETE CASCADE tables —
    the ones where rows are destroyed rather than orphaned. If either drops out
    of the probe list, the worst case stops being detected."""
    probed = {t for t, *_ in cos._CONTACT_DEPENDENTS}
    assert {"sessions", "academy_enrollments"} <= probed


# ─── the action-card contract ────────────────────────────────────────

def test_refusal_carries_result_and_label():
    """A missing result or label blanks the app (the toLowerCase crash class).
    A refusal is still a returned action and must honor the same contract."""
    with pytest.MonkeyPatch.context() as mp:
        _patch_sb(mp, {"sessions": 1})
        out = _delete()
    assert out["result"] and out["label"]
    assert out["type"] == "delete_contact"


def test_refusal_offers_the_thing_they_probably_wanted():
    """Declining without an alternative is a dead end. Chief can already do
    update_contact_status, so the refusal points there."""
    with pytest.MonkeyPatch.context() as mp:
        _patch_sb(mp, {"sessions": 1})
        out = _delete()
    lowered = out["result"].lower()
    assert "inactive" in lowered or "churned" in lowered


def test_refusal_is_not_phrased_as_a_failure():
    """It reads as a decision Chief made and can explain, not a malfunction."""
    with pytest.MonkeyPatch.context() as mp:
        _patch_sb(mp, {"sessions": 1})
        out = _delete()
    lowered = out["result"].lower()
    for word in ("error", "failed", "couldn't complete", "try again"):
        assert word not in lowered, f"refusal reads as an error ({word!r})"
