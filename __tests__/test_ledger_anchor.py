"""Stage 5 — anchoring.

A private hash chain proves internal consistency. It cannot answer the
skeptic's question: "you control the database, so you could have rebuilt
the whole chain." Publishing one root somewhere independent closes that,
because altering a row afterwards means changing a number already public
somewhere you cannot reach.

The tests that matter here are the ones a proof system fails quietly:
domain separation, the odd-level rule, and never claiming independence
that was not earned.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import ledger_anchor as la  # noqa: E402

_SQL = (_here.parent / "supabase"
        / "APPLY-2026-08-04-ledger-anchors.sql").read_text(encoding="utf-8")


def _h(n: int) -> str:
    return hashlib.sha256(str(n).encode()).hexdigest()


def _rows(n: int):
    return [_h(i) for i in range(n)]


# ─── The root ────────────────────────────────────────────────────────

def test_the_root_is_deterministic():
    """Same rows, same root — every time, in any process. Without this
    nothing else here means anything."""
    assert la.merkle_root(_rows(7)) == la.merkle_root(_rows(7))


def test_changing_any_row_changes_the_root():
    base = la.merkle_root(_rows(8))
    for i in range(8):
        rows = _rows(8)
        rows[i] = _h(999)
        assert la.merkle_root(rows) != base, f"row {i} did not move the root"


def test_reordering_changes_the_root():
    rows = _rows(6)
    swapped = rows[:]
    swapped[2], swapped[3] = swapped[3], swapped[2]
    assert la.merkle_root(swapped) != la.merkle_root(rows)


def test_an_empty_window_is_refused():
    with pytest.raises(ValueError):
        la.merkle_root([])


def test_leaves_and_nodes_are_domain_separated():
    """THE test. Without distinct prefixes a Merkle tree admits a
    second-preimage attack: an internal node can be presented as a leaf,
    producing a valid path for data that was never in the tree. One byte
    prevents it, and leaving it out is the classic way to build a proof
    system that proves the wrong thing.

    A two-leaf root must therefore NOT equal the plain hash of its two
    children — which is exactly what it would equal without separation.
    """
    a, b = _h(1), _h(2)
    naive = hashlib.sha256(bytes.fromhex(a) + bytes.fromhex(b)).hexdigest()
    assert la.merkle_root([a, b]) != naive
    # And a leaf is not its own row_hash, for the same reason.
    assert la.leaf_hash(a) != a


def test_odd_levels_promote_rather_than_duplicate():
    """Duplicating the last node (Bitcoin's shape) makes a tree of N and
    a tree of N+1 whose last row is a copy produce the SAME root. In a
    system whose claim is "this is exactly what happened", two different
    histories sharing a root is a real ambiguity. Promotion has no such
    collision."""
    three = _rows(3)
    four_with_dup = three + [three[-1]]
    assert la.merkle_root(three) != la.merkle_root(four_with_dup)


def test_the_algorithm_name_travels_with_the_receipt():
    """A future tree shape gets a new name rather than silently
    reinterpreting roots that were already published."""
    assert la.ALGORITHM == "merkle_sha256_v1"
    assert "algorithm" in _SQL and "merkle_sha256_v1" in _SQL


# ─── The proof ───────────────────────────────────────────────────────

@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 8, 9, 17])
def test_every_row_can_prove_itself(n):
    """Including the awkward sizes — odd counts and the promoted tail
    are where a hand-rolled Merkle implementation goes wrong."""
    rows = _rows(n)
    root = la.merkle_root(rows)
    for i in range(n):
        path = la.merkle_proof(rows, i)
        assert la.verify_proof(rows[i], path, root), f"n={n} row={i} failed"


def test_a_proof_for_the_wrong_row_fails():
    rows = _rows(8)
    root = la.merkle_root(rows)
    path = la.merkle_proof(rows, 3)
    assert la.verify_proof(rows[4], path, root) is False


def test_a_tampered_path_fails():
    rows = _rows(8)
    root = la.merkle_root(rows)
    path = la.merkle_proof(rows, 2)
    path[0]["hash"] = _h(4242)
    assert la.verify_proof(rows[2], path, root) is False


def test_a_flipped_side_fails():
    """`side` is what lets a verifier rebuild in the right order — if it
    were ignored the proof would accept mirrored trees."""
    rows = _rows(8)
    root = la.merkle_root(rows)
    path = la.merkle_proof(rows, 5)
    for step in path:
        step["side"] = "left" if step["side"] == "right" else "right"
    assert la.verify_proof(rows[5], path, root) is False


def test_verify_never_raises_on_junk():
    assert la.verify_proof("nothex", [{"side": "left", "hash": "zz"}], "x") is False
    assert la.verify_proof(_h(1), [{}], "x") is False


def test_a_row_outside_the_window_is_refused():
    with pytest.raises(IndexError):
        la.merkle_proof(_rows(4), 9)


# ─── Honesty about the provider ──────────────────────────────────────

def test_local_is_not_independent():
    """It sits inside exactly the trust boundary the skeptic is
    questioning. Reporting it as proof would be the one lie this feature
    must never tell."""
    assert la.LocalProvider().is_independent is False
    assert la.is_independent("local") is False


def test_an_unknown_provider_is_not_independent():
    """The refusing answer, consistent with every other accessor in this
    system."""
    assert la.is_independent("hedera-someday") is False
    assert la.is_independent("") is False


def test_a_failed_publish_writes_no_receipt(monkeypatch):
    """A row here asserts a proof exists. Writing one when publication
    failed would make the table lie in the one direction it must not."""
    class Broken(la.AnchorProvider):
        name = "broken"
        is_independent = True

        def anchor(self, root):
            return None, "network unreachable"

    la.register_provider(Broken())
    posted = []
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service",
                        lambda p: [] if "ledger_anchors" in p
                        else [{"sequence": 1, "row_hash": _h(1)}])
    monkeypatch.setattr(la.sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: posted.append(b))
    out = la.anchor_business("b1", provider_name="broken")
    assert out["ok"] is False and out["anchored"] is False
    assert posted == [], "no receipt may be written when publishing failed"


def test_nothing_new_is_a_no_op_not_a_duplicate(monkeypatch):
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service",
                        lambda p: [{"last_sequence": 9}] if "ledger_anchors" in p else [])
    out = la.anchor_business("b1")
    assert out["anchored"] is False and "nothing new" in out["reason"]


def test_only_hashed_rows_are_anchored(monkeypatch):
    """Pre-chain rows carry no hash — there is nothing to commit to.
    Excluding them by query rather than skipping them keeps first/last
    sequence honest about what the root actually covers."""
    seen = {}
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service",
                        lambda p: seen.setdefault("q", p) and [] or [])
    la._rows_after("b1", 0)
    assert "row_hash=not.is.null" in seen["q"]


# ─── The receipt table ───────────────────────────────────────────────

def test_anchors_are_append_only():
    assert "before update or delete on public.ledger_anchors" in _SQL
    assert "before truncate on public.ledger_anchors" in _SQL
    assert "for each statement" in _SQL


def test_the_receipt_outlives_an_erased_tenant():
    """Same reason ledger_chain_state has no FK: erasure must not
    destroy the evidence that the erasure was declared."""
    assert "No FK to businesses" in _SQL
    assert "references public.businesses" not in _SQL.lower()


def test_one_anchor_per_window():
    assert "idx_ledger_anchors_window" in _SQL
    assert "unique index" in _SQL


def test_the_table_is_locked_to_anon_and_authenticated():
    assert "revoke all on public.ledger_anchors from anon, authenticated" in _SQL


def test_the_doc_says_local_proves_nothing():
    flat = " ".join(_SQL.replace("--", " ").split())
    assert "NOT published anywhere independent" in flat
