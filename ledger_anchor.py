"""Stage 5 — anchoring. A fingerprint of the ledger, publishable.

THE GAP. A private hash chain proves internal consistency: alter one row
and every later row's hash breaks. What it cannot answer is the
skeptic's question — "you control the database, so you could have
rebuilt the whole chain." True, and irrelevant for a salon. Material
when the ledger is offered as evidence.

Publishing one root to somewhere neither we nor the practitioner
controls closes it. After that, everything in the window is frozen: to
alter a row you would have to change a number that is already public
somewhere you cannot reach.

WHAT IS PUBLISHED IS A HASH OF HASHES. No verb, no client, no amount,
and nothing reversible out of it. Proof of non-alteration and nothing
else — that constraint is the reason this is safe to offer at all.

WHY NO PROOF PATH IS STORED. Rows are immutable and totally ordered per
tenant, and Stage 2 froze the leaf bytes in ledger_canonical_v1. So the
tree is RECOMPUTABLE from stored rows whenever a proof is asked for.
The spec called the proof path the one thing painful to retrofit;
freezing the canonical form is what closed it, and this module never
persists a tree.

HONESTY ABOUT `local`. The default provider records the root HERE. That
proves nothing a skeptic must accept — it is the same trust boundary
the chain already lives inside. It is a staging step, not evidence, and
every surface reporting it has to say so in those words. Real proof
begins the moment a provider publishes the root somewhere independent.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import sb_clients

logger = logging.getLogger("ledger_anchor")

# The tree shape is FROZEN under this name, exactly as the canonical
# serialization is. A different shape gets a different name rather than
# silently reinterpreting roots that were already published.
ALGORITHM = "merkle_sha256_v1"

# Domain separation. Without distinct prefixes for leaves and internal
# nodes, a Merkle tree admits a second-preimage attack: an attacker can
# present an internal node as though it were a leaf and produce a valid
# path for data that was never in the tree. One byte prevents it, and
# leaving it out is the classic way to build a proof system that proves
# the wrong thing.
_LEAF = b"\x00"
_NODE = b"\x01"

MAX_WINDOW_ROWS = 10_000


def _h(*parts: bytes) -> str:
    d = hashlib.sha256()
    for p in parts:
        d.update(p)
    return d.hexdigest()


def leaf_hash(row_hash: str) -> str:
    """One ledger row's leaf.

    The leaf is derived from `row_hash`, which Stage 2 already computed
    over the canonical form plus the previous row's hash. So a leaf is
    reproducible from a stored row with no re-serialization here — and
    this module never needs to know the shape of a ledger row at all.
    """
    return _h(_LEAF, bytes.fromhex(row_hash))


def _pair(left: str, right: str) -> str:
    return _h(_NODE, bytes.fromhex(left), bytes.fromhex(right))


def merkle_root(row_hashes: List[str]) -> str:
    """Deterministic root over rows already ordered by sequence.

    ODD LEVELS PROMOTE, they do not duplicate. Duplicating the last node
    (Bitcoin's shape) makes a tree of N and a tree of N+1-where-the-last-
    is-a-copy produce the same root, which is a real ambiguity in a
    system whose whole claim is "this is exactly what happened".
    Promotion has no such collision.
    """
    if not row_hashes:
        raise ValueError("cannot anchor an empty window")
    level = [leaf_hash(h) for h in row_hashes]
    while len(level) > 1:
        nxt: List[str] = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(_pair(level[i], level[i + 1]))
        if len(level) % 2 == 1:
            nxt.append(level[-1])          # promote, never duplicate
        level = nxt
    return level[0]


def merkle_proof(row_hashes: List[str], index: int) -> List[Dict[str, str]]:
    """The sibling path for one row, as [{side, hash}, …].

    Recomputed on demand from the same ordered rows the root was built
    from. `side` says whether the sibling sits left or right, which is
    what lets a verifier who has never seen our code rebuild the root in
    the right order.
    """
    if not row_hashes:
        raise ValueError("no rows")
    if not 0 <= index < len(row_hashes):
        raise IndexError("row is not inside this window")
    level = [leaf_hash(h) for h in row_hashes]
    idx = index
    path: List[Dict[str, str]] = []
    while len(level) > 1:
        nxt: List[str] = []
        for i in range(0, len(level) - 1, 2):
            if i == idx:
                path.append({"side": "right", "hash": level[i + 1]})
            elif i + 1 == idx:
                path.append({"side": "left", "hash": level[i]})
            nxt.append(_pair(level[i], level[i + 1]))
        if len(level) % 2 == 1:
            nxt.append(level[-1])
            if idx == len(level) - 1:
                idx = len(nxt) - 1          # promoted: no sibling this level
                level = nxt
                continue
        idx //= 2
        level = nxt
    return path


def verify_proof(row_hash: str, path: List[Dict[str, str]], root: str) -> bool:
    """Rebuild the root from one leaf and its siblings.

    Deliberately standalone and dependency-free: this is the routine an
    auditor's own engineer should be able to reimplement from the
    published description in an afternoon. If they cannot, the proof is
    not really a proof.
    """
    try:
        cur = leaf_hash(row_hash)
        for step in path:
            sib = str(step.get("hash") or "")
            if step.get("side") == "left":
                cur = _pair(sib, cur)
            else:
                cur = _pair(cur, sib)
        return cur == root
    except Exception:
        return False


# ─── The provider seam ───────────────────────────────────────────────

class AnchorProvider:
    """`anchor(root) -> (provider_ref, error)`.

    Same discipline as payments_core: a seam, so the public network is
    an adapter rather than a hard-wired dependency. An adapter returns a
    reference a third party can look up, or an error — never a silent
    success, because an anchor that did not publish is worse than no
    anchor at all. It would put a receipt in the table asserting a
    proof that does not exist.
    """
    name = "abstract"

    def anchor(self, root: str) -> Tuple[Optional[str], Optional[str]]:
        raise NotImplementedError


class LocalProvider(AnchorProvider):
    """Records the root with us and publishes nothing.

    This is a staging step, NOT evidence. It sits inside exactly the
    trust boundary the skeptic is questioning, so it adds nothing a
    skeptic must accept. Its only real use is that the batching, the
    root and the proof path all become exercisable before anyone spends
    money on a network — and switching to a real provider then changes
    a config value, not a design.

    Every surface that reports a local anchor must say it is not
    independently published. `is_independent` exists so that is a
    property of the provider rather than a string comparison scattered
    through the UI.
    """
    name = "local"
    is_independent = False

    def anchor(self, root: str) -> Tuple[Optional[str], Optional[str]]:
        return None, None


_PROVIDERS: Dict[str, AnchorProvider] = {"local": LocalProvider()}


def register_provider(p: AnchorProvider) -> None:
    _PROVIDERS[p.name] = p


def get_provider(name: Optional[str] = None) -> AnchorProvider:
    key = (name or os.environ.get("LEDGER_ANCHOR_PROVIDER") or "local").strip()
    return _PROVIDERS.get(key, _PROVIDERS["local"])


def is_independent(provider_name: str) -> bool:
    """Did this anchor actually leave our control?

    Unknown providers answer False — the refusing answer, consistent
    with every other accessor in this system. Claiming independence we
    cannot demonstrate is the one lie this feature must never tell.
    """
    p = _PROVIDERS.get((provider_name or "").strip())
    return bool(getattr(p, "is_independent", False)) if p else False


# ─── Batching ────────────────────────────────────────────────────────

def _rows_after(business_id: str, after_sequence: int,
                limit: int = MAX_WINDOW_ROWS) -> List[Dict[str, Any]]:
    """Hashed rows only, in sequence order.

    Rows with no `row_hash` predate the chain and cannot be anchored —
    there is nothing to commit to. Skipping them silently would leave a
    hole in the window; excluding them by query keeps first/last
    sequence honest about what the root actually covers.
    """
    return sb_clients.sb_get_as_service(
        f"/audit_log?business_id=eq.{business_id}"
        f"&sequence=gt.{int(after_sequence)}"
        f"&row_hash=not.is.null"
        f"&select=sequence,row_hash&order=sequence.asc&limit={int(limit)}") or []


def last_anchor(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/ledger_anchors?business_id=eq.{business_id}"
        f"&select=id,first_sequence,last_sequence,merkle_root,provider,"
        f"provider_ref,anchored_at,row_count,algorithm"
        f"&order=last_sequence.desc&limit=1") or []
    return rows[0] if rows else None


def anchor_business(business_id: str, *, provider_name: Optional[str] = None
                    ) -> Dict[str, Any]:
    """Anchor everything hashed since this tenant's last anchor.

    Deterministic by construction: the window is "every hashed row after
    the previous anchor's last_sequence", and rows are immutable, so the
    same window always yields the same root. Re-running when nothing new
    has landed is a no-op rather than a duplicate receipt.
    """
    prev = last_anchor(business_id)
    after = int(prev["last_sequence"]) if prev else 0
    rows = _rows_after(business_id, after)
    if not rows:
        return {"ok": True, "anchored": False,
                "reason": "nothing new to anchor since the last one"}

    hashes = [str(r["row_hash"]) for r in rows]
    root = merkle_root(hashes)
    provider = get_provider(provider_name)

    ref, err = provider.anchor(root)
    if err:
        # No receipt on a failed publish. A row here asserts a proof
        # exists; writing one when publication failed would make the
        # table lie in the one direction it must not.
        logger.warning("[anchor] %s failed to publish: %s", provider.name, err)
        return {"ok": False, "anchored": False, "error": err}

    saved = sb_clients.sb_post_as_service("/ledger_anchors", {
        "business_id": str(business_id),
        "first_sequence": int(rows[0]["sequence"]),
        "last_sequence": int(rows[-1]["sequence"]),
        "row_count": len(rows),
        "merkle_root": root,
        "algorithm": ALGORITHM,
        "provider": provider.name,
        "provider_ref": ref,
    }, prefer="return=representation")
    if not saved:
        return {"ok": False, "anchored": False,
                "error": "the anchor could not be saved"}

    return {"ok": True, "anchored": True, "merkle_root": root,
            "first_sequence": int(rows[0]["sequence"]),
            "last_sequence": int(rows[-1]["sequence"]),
            "row_count": len(rows), "provider": provider.name,
            "provider_ref": ref,
            "independent": is_independent(provider.name)}


def proof_for(business_id: str, sequence: int) -> Dict[str, Any]:
    """The proof that one row sits under a published root.

    Returns everything a verifier needs and nothing they must trust us
    for: the leaf's own row_hash, the sibling path, the root, and the
    public reference to check it against.
    """
    anchors = sb_clients.sb_get_as_service(
        f"/ledger_anchors?business_id=eq.{business_id}"
        f"&first_sequence=lte.{int(sequence)}&last_sequence=gte.{int(sequence)}"
        f"&select=first_sequence,last_sequence,merkle_root,provider,"
        f"provider_ref,anchored_at,algorithm&limit=1") or []
    if not anchors:
        return {"ok": False,
                "reason": "this record is not covered by an anchor yet"}
    a = anchors[0]

    rows = sb_clients.sb_get_as_service(
        f"/audit_log?business_id=eq.{business_id}"
        f"&sequence=gte.{int(a['first_sequence'])}"
        f"&sequence=lte.{int(a['last_sequence'])}"
        f"&row_hash=not.is.null"
        f"&select=sequence,row_hash&order=sequence.asc"
        f"&limit={MAX_WINDOW_ROWS}") or []
    hashes = [str(r["row_hash"]) for r in rows]
    try:
        idx = next(i for i, r in enumerate(rows)
                   if int(r["sequence"]) == int(sequence))
    except StopIteration:
        return {"ok": False, "reason": "that record is not in the anchored window"}

    recomputed = merkle_root(hashes)
    path = merkle_proof(hashes, idx)
    return {
        "ok": True,
        "sequence": int(sequence),
        "row_hash": hashes[idx],
        "path": path,
        "merkle_root": a["merkle_root"],
        # If these disagree, the rows under the anchor have changed
        # since it was taken. Reported, never repaired: a proof endpoint
        # that quietly re-roots is not a proof endpoint.
        "root_matches": recomputed == a["merkle_root"],
        "algorithm": a.get("algorithm") or ALGORITHM,
        "provider": a.get("provider"),
        "provider_ref": a.get("provider_ref"),
        "anchored_at": a.get("anchored_at"),
        "independent": is_independent(a.get("provider") or ""),
        "window": {"first_sequence": a["first_sequence"],
                   "last_sequence": a["last_sequence"]},
    }
