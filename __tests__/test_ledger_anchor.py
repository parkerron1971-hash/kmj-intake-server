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
    """A row in ledger_anchors asserts a proof exists. Writing one when
    publication failed would make the table lie in the one direction it
    must not.

    The failure IS now written — to its own table — so this asserts
    against the path rather than against "nothing was posted at all".
    Both halves matter: no receipt, and no silence either.
    """
    class Broken(la.AnchorProvider):
        name = "broken"
        is_independent = True

        def anchor(self, root):
            return None, "network unreachable"

    # Registering into the module-level registry is global state. Without
    # the restore below it leaks into every later test — which is exactly
    # how test_all_three_providers_are_registered started failing.
    _saved = dict(la._PROVIDERS)
    la.register_provider(Broken())
    posted = []
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service",
                        lambda p: [] if "ledger_anchors" in p
                        else [{"sequence": 1, "row_hash": _h(1)}])
    monkeypatch.setattr(la.sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: posted.append((p, b)))
    try:
        out = la.anchor_business("b1", provider_name="broken")
    finally:
        la._PROVIDERS.clear()
        la._PROVIDERS.update(_saved)
    assert out["ok"] is False and out["anchored"] is False
    assert not [p for p, _ in posted if "/ledger_anchors" in p], \
        "no receipt may be written when publishing failed"
    assert [p for p, _ in posted if "/ledger_anchor_failures" in p], \
        "a failed publish must be recorded somewhere, or it is invisible"


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

def test_status_of_no_proof_is_never_an_error():
    """A local anchor legitimately has no reference — that is what
    `local` MEANS — while an OpenTimestamps anchor missing its proof is
    a different situation entirely. Since the dispatch went per-provider
    the two stopped being the same answer, and keeping them apart is
    more useful than the old shared "none".
    """
    assert la.proof_status(None, "local")["state"] == "local"
    assert la.proof_status("", "local")["state"] == "local"
    assert la.proof_status(None, "opentimestamps")["state"] == "none"
    assert all(la.proof_status(r, p)["confirmed"] is False
               for r in (None, "") for p in ("local", "opentimestamps", "hedera"))


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


# ─── Hedera, the second adapter ──────────────────────────────────────

def test_testnet_is_never_treated_as_evidence(monkeypatch):
    """THE decision that matters most in this adapter. Hedera's testnet
    is periodically WIPED. A proof there looks identical to a real one
    and then vanishes, so calling it independent would produce the worst
    outcome this feature can have: a practice believing it holds
    evidence that has quietly ceased to exist.
    """
    h = la.HederaProvider()
    monkeypatch.setenv("HEDERA_NETWORK", "testnet")
    assert h.is_independent is False
    assert la.is_independent("hedera") is False
    monkeypatch.setenv("HEDERA_NETWORK", "mainnet")
    assert h.is_independent is True
    assert la.is_independent("hedera") is True


def test_an_unset_network_does_not_default_to_evidence(monkeypatch):
    """Absent config must land on the harmless side."""
    monkeypatch.delenv("HEDERA_NETWORK", raising=False)
    assert la.HederaProvider().is_independent is False


def test_a_testnet_receipt_stays_testnet_after_switching_to_mainnet(monkeypatch):
    """`independent` is read from the receipt's OWN network, not the one
    configured now. Otherwise flipping an env var would silently promote
    every old testnet proof into 'evidence'."""
    import json as _j
    monkeypatch.setenv("HEDERA_NETWORK", "mainnet")
    ref = _j.dumps({"network": "testnet", "topic": "0.0.5", "sequence": "1"})
    st = la.proof_status(ref, "hedera")
    assert st["state"] == "testnet"
    assert st["confirmed"] is False


def test_missing_credentials_refuse_by_name(monkeypatch):
    """A half-configured provider must say exactly what is absent and
    write no receipt, rather than anchoring nowhere in silence."""
    for v in ("HEDERA_ACCOUNT_ID", "HEDERA_PRIVATE_KEY", "HEDERA_TOPIC_ID"):
        monkeypatch.delenv(v, raising=False)
    ref, err = la.HederaProvider().anchor("aa" * 32)
    assert ref is None
    for v in ("HEDERA_ACCOUNT_ID", "HEDERA_PRIVATE_KEY", "HEDERA_TOPIC_ID"):
        assert v in err, "the error must name what is missing"


def test_a_partially_configured_provider_still_refuses(monkeypatch):
    monkeypatch.setenv("HEDERA_ACCOUNT_ID", "0.0.1234")
    monkeypatch.delenv("HEDERA_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("HEDERA_TOPIC_ID", raising=False)
    ref, err = la.HederaProvider().anchor("aa" * 32)
    assert ref is None and "HEDERA_PRIVATE_KEY" in err


def test_a_mainnet_receipt_hands_the_auditor_a_public_url(monkeypatch):
    """The verification story: an auditor curls a public mirror node and
    compares the message to the root. No account, no SDK, nothing of
    ours involved."""
    import json as _j
    ref = _j.dumps({"network": "mainnet", "topic": "0.0.777", "sequence": "42"})
    st = la.proof_status(ref, "hedera")
    assert st["confirmed"] is True
    assert st["verify_url"] == (
        "https://mainnet-public.mirrornode.hedera.com/api/v1/topics/0.0.777/messages")
    assert "solutionist" not in (st["verify_url"] or "")


def test_hedera_has_no_pending_state():
    """Consensus is reached before the call returns — that is the whole
    speed advantage over Bitcoin, and why there is nothing to poll."""
    import json as _j
    st = la.proof_status(_j.dumps({"network": "mainnet", "topic": "0.0.1"}), "hedera")
    assert st["pending_at"] == []
    assert st["state"] == "confirmed"


def test_a_corrupt_hedera_receipt_is_unreadable_not_confirmed():
    for junk in ("not-json", "{}", '{"network":"mainnet"}'):
        st = la.proof_status(junk, "hedera")
        assert st["confirmed"] is False, f"{junk} must not read as confirmed"


# ─── The seam holds all three ────────────────────────────────────────

def test_each_provider_reads_its_own_receipt_format():
    """A .ots blob and a Hedera transaction reference share nothing
    structurally. Dispatching by provider rather than sniffing the blob
    is what stops a parser guessing — and guessing here means claiming a
    proof that is not there."""
    for name in ("local", "opentimestamps", "hedera"):
        assert hasattr(la._PROVIDERS[name], "status")
    import json as _j
    hedera_ref = _j.dumps({"network": "mainnet", "topic": "0.0.1"})
    # Each blob is nonsense to the other provider, and neither claims a proof.
    assert la.proof_status(hedera_ref, "opentimestamps")["confirmed"] is False
    assert la.proof_status("AE9wZW5UaW1lc3RhbXBz", "hedera")["confirmed"] is False


def test_all_three_providers_are_registered():
    assert set(la._PROVIDERS) == {"local", "opentimestamps", "hedera"}


def test_only_the_local_provider_claims_nothing():
    """Independence is a property of the provider, so no surface has to
    compare strings to work out what a receipt is worth."""
    assert la.is_independent("local") is False
    assert la.is_independent("opentimestamps") is True
    assert la.is_independent("nonsense-provider") is False


# ─── Two networks, independently ─────────────────────────────────────
#
# The reason for running two providers is not that either is likely to
# be discredited. It is that a gap cannot be repaired: you cannot anchor
# last month at last month's timestamp. So the tests that matter are the
# ones about a provider failing WITHOUT taking the other down, and about
# a provider that was down covering its own gap afterwards.

_SQL2 = (_here.parent / "supabase"
         / "APPLY-2026-08-07-anchor-multi-provider.sql").read_text(encoding="utf-8")


@pytest.fixture
def registry():
    """_PROVIDERS is module-level global state; leaking a fake into it
    breaks unrelated tests later in the file."""
    saved = dict(la._PROVIDERS)
    yield
    la._PROVIDERS.clear()
    la._PROVIDERS.update(saved)


class _FakeDB:
    """Just enough PostgREST to exercise per-provider windows."""

    def __init__(self, sequences):
        self.audit = [{"sequence": i, "row_hash": _h(i)} for i in sequences]
        self.anchors = []
        self.failures = []
        self.posts = []

    def add_rows(self, sequences):
        self.audit += [{"sequence": i, "row_hash": _h(i)} for i in sequences]

    def get(self, path):
        import re
        if "/ledger_anchors" in path:
            rows = self.anchors
            m = re.search(r"provider=eq\.([^&]+)", path)
            if m:
                rows = [r for r in rows if r["provider"] == m.group(1)]
            rows = sorted(rows, key=lambda r: r["last_sequence"], reverse=True)
            lim = re.search(r"limit=(\d+)", path)
            return rows[:int(lim.group(1))] if lim else rows
        if "/ledger_anchor_failures" in path:
            return list(self.failures)
        if "/audit_log" in path:
            m = re.search(r"sequence=gt\.(\d+)", path)
            after = int(m.group(1)) if m else 0
            return [r for r in self.audit if r["sequence"] > after]
        return []

    def post(self, path, body, prefer=None):
        self.posts.append((path, body))
        if "/ledger_anchors" in path:
            self.anchors.append(dict(body))
        elif "/ledger_anchor_failures" in path:
            self.failures.append(dict(body))
        return [body]

    def receipts(self):
        return [b for p, b in self.posts if "/ledger_anchors" in p]


class _Down(la.AnchorProvider):
    name = "down"
    is_independent = True

    def anchor(self, root):
        return None, "network unreachable"


class _Up(la.AnchorProvider):
    name = "up"
    is_independent = True

    def __init__(self):
        self.roots = []

    def anchor(self, root):
        self.roots.append(root)
        return "ref-" + root[:8], None


def _wire(monkeypatch, db):
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(la.sb_clients, "sb_post_as_service", db.post)


def test_the_plural_env_var_configures_both(monkeypatch):
    monkeypatch.setenv("LEDGER_ANCHOR_PROVIDERS", "hedera,opentimestamps")
    assert la.configured_providers() == ["hedera", "opentimestamps"]


def test_the_old_singular_var_still_means_what_it_meant(monkeypatch):
    """A deployment nobody has updated must keep its current behaviour
    rather than quietly gaining a second network."""
    monkeypatch.delenv("LEDGER_ANCHOR_PROVIDERS", raising=False)
    monkeypatch.setenv("LEDGER_ANCHOR_PROVIDER", "opentimestamps")
    assert la.configured_providers() == ["opentimestamps"]


def test_nothing_configured_lands_on_local(monkeypatch):
    for v in ("LEDGER_ANCHOR_PROVIDERS", "LEDGER_ANCHOR_PROVIDER"):
        monkeypatch.delenv(v, raising=False)
    assert la.configured_providers() == ["local"]


def test_whitespace_and_repeats_do_not_double_anchor(monkeypatch):
    """A doubled name would publish twice and collide on the per-provider
    unique index — a config typo becoming an error."""
    monkeypatch.setenv("LEDGER_ANCHOR_PROVIDERS", " hedera , hedera ,, ")
    assert la.configured_providers() == ["hedera"]


def test_one_provider_failing_does_not_stop_the_other(monkeypatch, registry):
    """THE test for the whole arc. If this passes, an outage on one
    network costs that network's anchor and nothing else."""
    db = _FakeDB([1, 2, 3])
    _wire(monkeypatch, db)
    la.register_provider(_Down())
    up = _Up()
    la.register_provider(up)

    out = la.anchor_business("b1", provider_name="down,up")

    assert out["anchored"] is True, "the healthy network must still publish"
    assert out["published_to"] == ["up"]
    assert out["failed_providers"] == ["down"]
    assert len(up.roots) == 1, "the healthy provider was actually called"
    assert len(db.receipts()) == 1, "exactly one receipt - for the one that worked"
    assert db.receipts()[0]["provider"] == "up"


def test_the_order_of_failure_does_not_matter(monkeypatch, registry):
    """Failing FIRST must not abort the loop before the healthy provider
    is reached - the obvious way to get this wrong."""
    db = _FakeDB([1, 2])
    _wire(monkeypatch, db)
    la.register_provider(_Down())
    la.register_provider(_Up())
    for order in ("down,up", "up,down"):
        db.anchors.clear()
        db.posts.clear()
        out = la.anchor_business("b1", provider_name=order)
        assert out["published_to"] == ["up"], f"order {order} lost the anchor"


def test_a_provider_that_raises_does_not_take_the_other_with_it(
        monkeypatch, registry):
    """An adapter that breaks its own contract is a bug in the adapter,
    not a reason to lose the other network's proof."""
    class Explodes(la.AnchorProvider):
        name = "explodes"
        is_independent = True

        def anchor(self, root):
            raise RuntimeError("boom")

    db = _FakeDB([1, 2])
    _wire(monkeypatch, db)
    la.register_provider(Explodes())
    la.register_provider(_Up())
    out = la.anchor_business("b1", provider_name="explodes,up")
    assert out["published_to"] == ["up"]
    assert out["failed_providers"] == ["explodes"]
    assert any("boom" in str(f.get("error")) for f in db.failures)


def test_a_failed_provider_catches_up_its_own_gap(monkeypatch, registry):
    """WITHOUT per-provider windows this is where redundancy quietly
    dies. The window would be "everything since the newest anchor by
    ANYBODY", so the provider that failed on rows 1-3 would start its
    next run at 4 and never come back for the gap - a permanent hole
    that nothing would ever report.
    """
    db = _FakeDB([1, 2, 3])
    _wire(monkeypatch, db)
    down, up = _Down(), _Up()
    la.register_provider(down)
    la.register_provider(up)

    la.anchor_business("b1", provider_name="down,up")     # up: [1,3]; down fails
    assert up.roots, "first run should have published on the healthy network"

    # The failing network recovers, and new rows have landed meanwhile.
    db.add_rows([4, 5])
    la._PROVIDERS["down"] = type("Recovered", (_Up,), {"name": "down"})()
    out = la.anchor_business("b1", provider_name="down,up")

    per = {p["provider"]: p for p in out["providers"]}
    assert per["up"]["first_sequence"] == 4, "healthy provider resumes after its own anchor"
    assert per["down"]["first_sequence"] == 1, "recovered provider must cover its gap"
    assert per["down"]["last_sequence"] == 5


def test_a_failure_never_lands_in_the_receipt_table(monkeypatch, registry):
    """The invariant the whole design rests on: a row in ledger_anchors
    asserts a proof exists."""
    db = _FakeDB([1, 2])
    _wire(monkeypatch, db)
    la.register_provider(_Down())
    la.anchor_business("b1", provider_name="down")
    assert db.receipts() == []
    assert len(db.failures) == 1
    assert db.failures[0]["provider"] == "down"
    assert "unreachable" in db.failures[0]["error"]
    # The window it was trying to cover, so the gap is legible later.
    assert db.failures[0]["first_sequence"] == 1
    assert db.failures[0]["last_sequence"] == 2


def test_an_unknown_provider_does_not_silently_anchor_locally(
        monkeypatch, registry):
    """get_provider() falls back to `local`, which is fine as a single
    deliberate choice and dangerous as one entry in a list: the
    deployment would believe it published to two networks while one of
    them recorded nothing anywhere."""
    db = _FakeDB([1])
    _wire(monkeypatch, db)
    out = la.anchor_business("b1", provider_name="hedra")   # typo on purpose
    assert out["anchored"] is False
    assert db.receipts() == [], "a typo must not become a local anchor"
    assert "not a registered anchor provider" in db.failures[0]["error"]


def test_a_local_anchor_never_fronts_a_run_that_reached_a_real_network(
        monkeypatch, registry):
    """The flattened keys are what existing callers read. They must point
    at evidence when evidence exists."""
    db = _FakeDB([1, 2])
    _wire(monkeypatch, db)
    la.register_provider(_Up())
    out = la.anchor_business("b1", provider_name="local,up")
    assert set(out["published_to"]) == {"local", "up"}
    assert out["provider"] == "up", "the independent receipt is the face of the run"
    assert out["independent"] is True


def test_nothing_new_is_still_a_no_op_for_every_provider(monkeypatch, registry):
    db = _FakeDB([1])
    _wire(monkeypatch, db)
    la.register_provider(_Up())
    la.anchor_business("b1", provider_name="up")
    before = len(db.receipts())
    out = la.anchor_business("b1", provider_name="up")
    assert len(db.receipts()) == before, "re-running must not duplicate a receipt"
    assert out["anchored"] is False and "nothing new" in out["reason"]


# ─── The schema those windows depend on ──────────────────────────────

def test_the_unique_key_now_includes_the_provider():
    """Two providers anchoring one window is redundancy, not duplication.
    Without provider in the key the second one hits a constraint
    violation and the redundancy silently never happens."""
    flat = " ".join(_SQL2.split())
    assert ("on public.ledger_anchors (business_id, provider, "
            "first_sequence, last_sequence)") in flat


def test_failures_have_their_own_table():
    assert "create table if not exists public.ledger_anchor_failures" in _SQL2
    assert ("revoke all on public.ledger_anchor_failures from anon, authenticated"
            in _SQL2)


def test_the_failures_table_does_not_touch_the_receipt_table():
    """No status column, no soft-delete flag, nothing that would let a
    failure be represented as a receipt."""
    assert "alter table public.ledger_anchors add" not in _SQL2.lower()


def test_the_ots_route_cannot_hand_back_a_hedera_receipt():
    """A Hedera receipt is JSON, not a .ots file. Unfiltered, this route
    would base64-decode one and serve the garbage as a proof file -
    which is worse than a 404."""
    src = (_here.parent / "audit_log.py").read_text(encoding="utf-8")
    body = src.split("def download_ots(")[1].split("\n@router")[0]
    assert "provider=eq.opentimestamps" in body


def test_health_reports_each_provider_separately(monkeypatch):
    """One aggregate verdict would hide the case that matters most: one
    network fine, the other dead."""
    monkeypatch.setenv("LEDGER_ANCHOR_PROVIDERS", "hedera,opentimestamps")
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service", lambda p: [])
    out = la.anchor_health()
    assert [p["provider"] for p in out["providers"]] == ["hedera", "opentimestamps"]
    assert all(p["verdict"] == "never" for p in out["providers"])


def test_health_survives_the_failures_table_not_existing(monkeypatch):
    """Before the migration runs the table is absent, and the honest
    answer is 'I cannot see failures', not a 500 on the operator's
    dashboard."""
    def boom(path):
        if "ledger_anchor_failures" in path:
            raise RuntimeError("relation ledger_anchor_failures does not exist")
        return []
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service", boom)
    out = la.anchor_health()
    assert out["total_failures"] == 0


def test_health_queries_use_the_Z_timestamp_form(monkeypatch):
    """isoformat() gives '+00:00', whose '+' becomes a space in a query
    string - the filter then matches nothing and a health check reports
    'no failures' precisely when it has gone blind."""
    seen = []
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service",
                        lambda p: seen.append(p) or [])
    la.anchor_health()
    stamped = [p for p in seen if "gte." in p]
    assert stamped, "the window filters should be present"
    assert all("Z" in p and "+00:00" not in p for p in stamped)


# ─── Seeing the Bitcoin confirmation ─────────────────────────────────
#
# A stored .ots is written at SUBMISSION time, when its only attestation
# is "pending at a calendar". The Bitcoin attestation arrives hours later
# and lives at the calendar — it never appears in bytes we already hold.
# Reading only the stored blob reported `submitted` forever, and the
# 2026-08-04 anchor proved it: confirmed in Bitcoin block 961016 while
# the app still called it submitted.
#
# That mattered because submitted-vs-confirmed is the whole reason there
# are two states.

_SQL3 = (_here.parent / "supabase"
         / "APPLY-2026-08-07-anchor-upgrades.sql").read_text(encoding="utf-8")


def _ots_blob(attestation):
    """A serialized .ots carrying one attestation."""
    import base64
    import opentimestamps.core.timestamp as ots_ts
    from opentimestamps.core.op import OpSHA256
    from opentimestamps.core.serialize import BytesSerializationContext
    digest = bytes.fromhex("ab" * 32)
    ts = ots_ts.Timestamp(digest)
    ts.attestations.add(attestation)
    ctx = BytesSerializationContext()
    ots_ts.DetachedTimestampFile(OpSHA256(), ts).serialize(ctx)
    return base64.b64encode(ctx.getbytes()).decode()


def test_an_already_confirmed_proof_needs_no_calendar(monkeypatch):
    """If the stored bytes already carry a Bitcoin attestation, the
    upgrade must return it without touching the network."""
    from opentimestamps.core.notary import BitcoinBlockHeaderAttestation
    blob = _ots_blob(BitcoinBlockHeaderAttestation(961016))
    ref, block, err = la.OpenTimestampsProvider().upgrade(blob)
    assert err is None
    assert block == 961016
    assert ref, "an upgraded proof must still be returned"


def test_a_pending_proof_with_dead_calendars_is_not_an_error_state(monkeypatch):
    """Aggregation takes hours, so 'not yet' is the EXPECTED answer for a
    fresh anchor. Treating it as a failure would fill the failure
    surfaces with noise and train the operator to ignore them."""
    from opentimestamps.core.notary import PendingAttestation
    blob = _ots_blob(PendingAttestation("https://127.0.0.1:1"))
    ref, block, err = la.OpenTimestampsProvider().upgrade(blob)
    assert ref is None and block is None
    assert "not yet" in err


def test_a_corrupt_proof_does_not_claim_a_block():
    ref, block, err = la.OpenTimestampsProvider().upgrade("!!!not-base64!!!")
    assert ref is None and block is None and err


def test_no_proof_is_refused_rather_than_crashing():
    ref, block, err = la.OpenTimestampsProvider().upgrade(None)
    assert ref is None and err


def test_the_earliest_block_wins():
    """The proof establishes existence BEFORE its block. Reporting a
    later attestation would overstate how old the record is provably
    is — the one direction this system must never round."""
    import base64
    import opentimestamps.core.timestamp as ots_ts
    from opentimestamps.core.op import OpSHA256
    from opentimestamps.core.notary import BitcoinBlockHeaderAttestation
    from opentimestamps.core.serialize import BytesSerializationContext
    ts = ots_ts.Timestamp(bytes.fromhex("cd" * 32))
    ts.attestations.add(BitcoinBlockHeaderAttestation(900000))
    ts.attestations.add(BitcoinBlockHeaderAttestation(961016))
    ctx = BytesSerializationContext()
    ots_ts.DetachedTimestampFile(OpSHA256(), ts).serialize(ctx)
    _ref, block, err = la.OpenTimestampsProvider().upgrade(
        base64.b64encode(ctx.getbytes()).decode())
    assert err is None and block == 900000


def test_an_upgraded_proof_reads_as_confirmed():
    """The point of the whole cache: proof_status on the upgraded bytes
    must finally say confirmed, where the stored bytes never could."""
    from opentimestamps.core.notary import (BitcoinBlockHeaderAttestation,
                                            PendingAttestation)
    pending = _ots_blob(PendingAttestation("https://a.example"))
    assert la.proof_status(pending, "opentimestamps")["state"] == "submitted"
    upgraded = _ots_blob(BitcoinBlockHeaderAttestation(961016))
    st = la.proof_status(upgraded, "opentimestamps")
    assert st["state"] == "confirmed"
    assert st["confirmed"] is True
    assert st["bitcoin_block"] == 961016


# ─── The cache ───────────────────────────────────────────────────────

class _UpDB:
    def __init__(self, anchors, upgrades=None):
        self.anchors = anchors
        self.upgrades = upgrades or []
        self.posts = []

    def get(self, path):
        if "/ledger_anchor_upgrades" in path:
            rows = self.upgrades
            if "confirmed=is.true" in path:
                rows = [r for r in rows if r.get("confirmed")]
            return list(rows)
        if "/ledger_anchors" in path:
            return list(self.anchors)
        return []

    def post(self, path, body, prefer=None):
        self.posts.append((path, body, prefer))
        return [body]


def test_a_confirmed_anchor_is_never_re_fetched(monkeypatch):
    """Bitcoin confirmations do not un-happen. Re-asking the calendars
    for a proof already in a block is pure waste, and at scale it is the
    difference between a polite client and a rude one."""
    db = _UpDB(
        anchors=[{"id": "a1", "business_id": "b1", "provider_ref": "x"}],
        upgrades=[{"anchor_id": "a1", "confirmed": True, "bitcoin_block": 961016}])
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(la.sb_clients, "sb_post_as_service", db.post)
    called = []
    monkeypatch.setattr(la._PROVIDERS["opentimestamps"], "upgrade",
                        lambda ref: called.append(ref) or (None, None, "not yet"))
    out = la.upgrade_pending()
    assert called == [], "an already-confirmed proof must not be re-fetched"
    assert out["checked"] == 0


def test_a_confirmation_is_cached_with_its_block(monkeypatch):
    db = _UpDB(anchors=[{"id": "a1", "business_id": "b1", "provider_ref": "x"}])
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(la.sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(la._PROVIDERS["opentimestamps"], "upgrade",
                        lambda ref: ("upgraded-bytes", 961016, None))
    out = la.upgrade_pending()
    assert out["confirmed"] == 1
    body = db.posts[0][1]
    assert body["confirmed"] is True
    assert body["bitcoin_block"] == 961016
    assert body["upgraded_ref"] == "upgraded-bytes"
    # Upsert, not insert: one row per receipt, refreshed in place.
    assert "merge-duplicates" in (db.posts[0][2] or "")


def test_still_aggregating_is_recorded_as_pending_not_as_an_error(monkeypatch):
    db = _UpDB(anchors=[{"id": "a1", "business_id": "b1", "provider_ref": "x"}])
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(la.sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(la._PROVIDERS["opentimestamps"], "upgrade",
                        lambda ref: (None, None, "not yet aggregated into a bitcoin block"))
    out = la.upgrade_pending()
    assert out["pending"] == 1 and out["errored"] == 0
    assert db.posts[0][1]["confirmed"] is False


def test_one_broken_proof_does_not_stop_the_batch(monkeypatch):
    db = _UpDB(anchors=[{"id": "a1", "business_id": "b1", "provider_ref": "x"},
                        {"id": "a2", "business_id": "b1", "provider_ref": "y"}])
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(la.sb_clients, "sb_post_as_service", db.post)

    def boom(ref):
        if ref == "x":
            raise RuntimeError("calendar exploded")
        return ("bytes", 961016, None)

    monkeypatch.setattr(la._PROVIDERS["opentimestamps"], "upgrade", boom)
    out = la.upgrade_pending()
    assert out["checked"] == 2 and out["confirmed"] == 1


def test_upgrades_for_returns_nothing_when_asked_for_nothing(monkeypatch):
    """An empty id list must not become `in.()`, which is a syntax error
    PostgREST answers with a 400 — and _safe_get would swallow it into a
    silent empty, hiding every upgrade on the page."""
    seen = []
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service",
                        lambda p: seen.append(p) or [])
    assert la.upgrades_for([]) == {}
    assert la.upgrades_for([None]) == {}
    assert seen == [], "no query should be issued at all"


# ─── The surfaces ────────────────────────────────────────────────────

def test_the_anchor_list_consults_the_upgrade_cache():
    """This is where the bug was VISIBLE: the list read the stored bytes
    and reported submitted forever."""
    src = (_here.parent / "audit_log.py").read_text(encoding="utf-8")
    body = src.split("def list_anchors(")[1].split("\n@router")[0]
    assert "upgrades_for" in body
    assert "upgraded_ref" in body


def test_the_ots_download_serves_the_upgraded_proof():
    """A submission-time .ots makes the auditor's client go and fetch the
    attestation itself; the upgraded one verifies against a block header
    with nobody's servers involved."""
    src = (_here.parent / "audit_log.py").read_text(encoding="utf-8")
    body = src.split("def download_ots(")[1].split("\n@router")[0]
    assert "upgraded_ref" in body


def test_the_upgrade_job_is_registered_on_its_own_clock():
    """Folding it into the anchoring sweep would tie confirmation to
    ledger activity, so a quiet practice's proofs would stay submitted
    indefinitely — the exact bug, reintroduced by the back door."""
    src = (_here.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'id="ledger_anchor_upgrade"' in src
    assert 'g("ledger_anchor_upgrade"' in src
    body = src.split('id="ledger_anchor_upgrade"')[1].split("except Exception")[0]
    assert "next_run_time" in body, "an interval job needs an explicit first run"


# ─── The cache table ─────────────────────────────────────────────────

def test_the_upgrade_cache_is_deliberately_mutable():
    """ledger_anchors is append-only because it is evidence. This is a
    cache of derived, refetchable data, so it carries no append-only
    trigger — and the file has to say why, or someone will 'fix' it."""
    assert "create table if not exists public.ledger_anchor_upgrades" in _SQL3
    assert "before update or delete on public.ledger_anchor_upgrades" not in _SQL3
    flat = " ".join(_SQL3.replace("--", " ").split())
    assert "DERIVED" in flat or "derived" in flat


def test_the_upgrade_cache_never_touches_the_receipt_table():
    assert "alter table public.ledger_anchors" not in _SQL3.lower()


def test_the_upgrade_cache_is_locked_to_anon_and_authenticated():
    assert ("revoke all on public.ledger_anchor_upgrades from anon, authenticated"
            in _SQL3)
