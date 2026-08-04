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


# ─── The public provider ─────────────────────────────────────────────

def test_opentimestamps_is_independent_and_local_is_not():
    """The whole point of the provider seam. `local` records the root
    inside the system being questioned; OTS puts it at calendar servers
    we do not run, on its way into Bitcoin."""
    assert la.is_independent("opentimestamps") is True
    assert la.is_independent("local") is False


def test_it_submits_to_more_than_one_calendar():
    """One unreachable server must not cost a practice its anchor. The
    proof is valid if any single calendar honours it."""
    assert len(la.OpenTimestampsProvider.CALENDARS) >= 3


def test_a_non_hex_root_is_refused_before_any_network_call():
    ref, err = la.OpenTimestampsProvider().anchor("not-a-digest")
    assert ref is None and "hex" in err


def test_every_calendar_failing_yields_no_receipt():
    """The existing discipline, now with a real provider behind it: an
    anchor row asserts a proof exists, so a failed publish must return
    an error rather than a reference."""
    class AllDown(la.OpenTimestampsProvider):
        CALENDARS = ("https://127.0.0.1:1",)
    ref, err = AllDown().anchor("aa" * 32)
    assert ref is None and err


def test_one_reachable_calendar_is_enough(monkeypatch):
    """Redundancy has to actually degrade gracefully, not all-or-nothing."""
    import opentimestamps.core.timestamp as ots_ts
    from opentimestamps.core.notary import PendingAttestation
    from opentimestamps.core.serialize import BytesSerializationContext

    digest = bytes.fromhex("bb" * 32)
    good = ots_ts.Timestamp(digest)
    # A timestamp with no attestation cannot be serialized at all — the
    # calendar always returns one, so the fixture must too.
    good.attestations.add(PendingAttestation("https://up.example"))
    ctx = BytesSerializationContext()
    good.serialize(ctx)
    payload = ctx.getbytes()

    calls = {"n": 0}

    def flaky(calendar, d, timeout=15.0):
        calls["n"] += 1
        if "down" in calendar:
            raise OSError("unreachable")
        return payload

    class Mixed(la.OpenTimestampsProvider):
        CALENDARS = ("https://down.example", "https://up.example")
    monkeypatch.setattr(Mixed, "_submit", staticmethod(flaky))
    ref, err = Mixed().anchor("bb" * 32)
    assert calls["n"] == 2, "it must try every calendar, not stop at the first failure"
    assert err is None and ref, "one healthy calendar should still produce a proof"


# ─── Proof state, read from the stored receipt ───────────────────────

def test_status_of_no_proof_is_none_not_an_error():
    assert la.proof_status(None)["state"] == "none"
    assert la.proof_status("")["state"] == "none"


def test_unreadable_proof_says_so_rather_than_claiming_confirmation():
    """Failing toward 'unreadable' matters: the alternative is a corrupt
    blob quietly reporting confirmed=False in a way indistinguishable
    from an honest pending proof."""
    st = la.proof_status("!!!not-base64!!!")
    assert st["state"] == "unreadable"
    assert st["confirmed"] is False


def test_a_fresh_proof_is_submitted_not_confirmed():
    """THE honesty test. Bitcoin aggregation takes hours, so a brand new
    anchor is at the calendars and NOT yet in a block. Reporting those
    two states as one would let 'submitted' borrow the credibility of
    'confirmed'."""
    import opentimestamps.core.timestamp as ots_ts
    from opentimestamps.core.op import OpSHA256
    from opentimestamps.core.notary import PendingAttestation
    from opentimestamps.core.serialize import BytesSerializationContext
    import base64

    digest = bytes.fromhex("cc" * 32)
    ts = ots_ts.Timestamp(digest)
    ts.attestations.add(PendingAttestation("https://example.calendar"))
    ctx = BytesSerializationContext()
    ots_ts.DetachedTimestampFile(OpSHA256(), ts).serialize(ctx)
    st = la.proof_status(base64.b64encode(ctx.getbytes()).decode())

    assert st["state"] == "submitted"
    assert st["confirmed"] is False
    assert st["bitcoin_block"] is None
    assert st["digest"] == "cc" * 32


def test_a_bitcoin_attestation_reads_as_confirmed():
    import opentimestamps.core.timestamp as ots_ts
    from opentimestamps.core.op import OpSHA256
    from opentimestamps.core.notary import BitcoinBlockHeaderAttestation
    from opentimestamps.core.serialize import BytesSerializationContext
    import base64

    digest = bytes.fromhex("dd" * 32)
    ts = ots_ts.Timestamp(digest)
    ts.attestations.add(BitcoinBlockHeaderAttestation(800000))
    ctx = BytesSerializationContext()
    ots_ts.DetachedTimestampFile(OpSHA256(), ts).serialize(ctx)
    st = la.proof_status(base64.b64encode(ctx.getbytes()).decode())

    assert st["state"] == "confirmed"
    assert st["confirmed"] is True
    assert st["bitcoin_block"] == 800000


def test_upgrades_are_never_written_back():
    """The receipt is append-only and must stay that way. proof_status
    recomputes the current state instead, which is why the table never
    needs a mutable proof column."""
    src = (_here.parent / "ledger_anchor.py").read_text(encoding="utf-8")
    body = src.split("def proof_status(")[1].split("\n_PROVIDERS")[0]
    assert "sb_post_as_service" not in body
    assert "sb_patch_as_service" not in body


def test_the_proof_file_has_its_own_route():
    """An auditor verifies with the public `ots` client, against Bitcoin,
    using nothing we wrote. A proof only our code can check is worth
    very little."""
    src = (_here.parent / "audit_log.py").read_text(encoding="utf-8")
    assert '@router.get("/anchor.ots")' in src
    body = src.split("def download_ots(")[1].split("\n@router")[0]
    assert "ledger_unlock.require_unlock(" in body
    assert "application/octet-stream" in body
