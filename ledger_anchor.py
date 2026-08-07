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
import json
import logging
import os
from datetime import datetime, timedelta, timezone
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

    def status(self, provider_ref: Optional[str]) -> Dict[str, Any]:
        """What does this receipt currently prove?

        Each provider reads its OWN receipt format. OpenTimestamps
        stores a binary .ots; Hedera stores a transaction reference.
        A single parser that tried to understand both would end up
        guessing, and guessing wrong here means reporting a proof that
        is not there.
        """
        return {"state": "none", "confirmed": False}


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

    def status(self, provider_ref: Optional[str]) -> Dict[str, Any]:
        return {"state": "local", "confirmed": False}


class OpenTimestampsProvider(AnchorProvider):
    """Publishes the root to Bitcoin, via the OpenTimestamps calendars.

    WHY THIS AND NOT A PAID LEDGER. It needs no account, no credentials
    and no fees, so nothing about turning it on is a commercial
    decision. More importantly the output is a standard `.ots` file: an
    auditor verifies it with the public `ots verify` tool against the
    Bitcoin blockchain, not with anything we wrote. A proof that only
    our own code can check is not much of a proof.

    TWO HONEST STATES, AND THEY ARE NOT THE SAME THING.

      submitted  the root is at independent calendar servers, which
                 have committed to including it. It has left our
                 control — real, and weaker than the next line.
      confirmed  the calendars' commitment is in a Bitcoin block. Now
                 the root is provably older than that block, and no
                 party including us can backdate it.

    Bitcoin aggregation takes hours, so `submitted` is the normal state
    for a while and the surfaces have to say which one they mean rather
    than rounding both to "anchored".

    REDUNDANCY ON PURPOSE. The root goes to several calendars. One
    unreachable server must not cost a practice its anchor, and the
    proof is valid if any single calendar honours it.
    """
    name = "opentimestamps"
    is_independent = True

    CALENDARS = (
        "https://a.pool.opentimestamps.org",
        "https://b.pool.opentimestamps.org",
        "https://finney.calendar.eternitywall.com",
    )

    def anchor(self, root: str) -> Tuple[Optional[str], Optional[str]]:
        import base64
        try:
            from opentimestamps.core.timestamp import Timestamp, DetachedTimestampFile
            from opentimestamps.core.op import OpSHA256
            from opentimestamps.core.serialize import (
                BytesSerializationContext, BytesDeserializationContext)
        except ImportError:
            return None, "the opentimestamps package is not installed"

        try:
            digest = bytes.fromhex(root)
        except ValueError:
            return None, "the root is not a hex digest"

        ts = Timestamp(digest)
        merged = 0
        errors = []
        for cal in self.CALENDARS:
            try:
                body = self._submit(cal, digest)
                ts.merge(Timestamp.deserialize(
                    BytesDeserializationContext(body), digest))
                merged += 1
            except Exception as e:                      # one server down is survivable
                errors.append(f"{cal}: {type(e).__name__}")
        if not merged:
            # No calendar took it, so nothing was published. Returning an
            # error means no receipt is written — a row here would assert
            # a proof that does not exist.
            return None, "no calendar accepted the fingerprint (" + "; ".join(errors) + ")"

        out = BytesSerializationContext()
        DetachedTimestampFile(OpSHA256(), ts).serialize(out)
        return base64.b64encode(out.getbytes()).decode("ascii"), None


    def status(self, provider_ref: Optional[str]) -> Dict[str, Any]:
        """Read a stored .ots and say what it currently proves.

        UPGRADES ARE NOT PERSISTED, DELIBERATELY. ledger_anchors is
        append-only, so the stored receipt can never be rewritten — and
        it does not need to be. A pending proof carries everything
        required to fetch the Bitcoin attestation later, so the upgrade
        is recomputed when someone asks rather than stored. The receipt
        stays immutable and the answer stays current, which is the
        combination that would otherwise be in tension.
        """
        out: Dict[str, Any] = {"state": "none", "confirmed": False,
                               "pending_at": [], "bitcoin_block": None}
        if not provider_ref:
            return out
        import base64
        try:
            from opentimestamps.core.timestamp import DetachedTimestampFile
            from opentimestamps.core.serialize import BytesDeserializationContext
            from opentimestamps.core.notary import (
                BitcoinBlockHeaderAttestation, PendingAttestation)
        except ImportError:
            return {**out, "state": "unreadable",
                    "reason": "the opentimestamps package is not installed"}
        try:
            raw = base64.b64decode(provider_ref)
            det = DetachedTimestampFile.deserialize(BytesDeserializationContext(raw))
        except Exception:
            return {**out, "state": "unreadable",
                    "reason": "the stored proof could not be parsed"}

        for _msg, att in det.timestamp.all_attestations():
            if isinstance(att, BitcoinBlockHeaderAttestation):
                out["confirmed"] = True
                out["bitcoin_block"] = int(att.height)
            elif isinstance(att, PendingAttestation):
                try:
                    out["pending_at"].append(
                        att.uri.decode() if isinstance(att.uri, bytes) else str(att.uri))
                except Exception:
                    pass
        out["state"] = ("confirmed" if out["confirmed"]
                        else "submitted" if out["pending_at"] else "unknown")
        out["digest"] = det.file_digest.hex()
        return out

    def upgrade(self, provider_ref: Optional[str]
                ) -> Tuple[Optional[str], Optional[int], Optional[str]]:
        """Ask the calendars for the Bitcoin attestation. -> (ref, block, error)

        THE MISSING HALF. A stored .ots is written at submission time,
        when its only attestation is "pending at a calendar". The
        Bitcoin attestation arrives hours later and lives AT THE
        CALENDAR — it never appears in bytes we already hold. Without
        this call a proof stays `submitted` forever no matter how long
        ago Bitcoin confirmed it, and the distinction between the two
        states, which is the whole reason there are two, is wasted.

        The result is a strict superset of the original: same digest,
        same path, plus the block header attestation. So every existing
        reader can be handed the upgraded blob in place of the stored
        one with no special handling.
        """
        import base64
        try:
            from opentimestamps.calendar import RemoteCalendar
            from opentimestamps.core.notary import (
                BitcoinBlockHeaderAttestation, PendingAttestation)
            from opentimestamps.core.serialize import (
                BytesDeserializationContext, BytesSerializationContext)
            from opentimestamps.core.timestamp import DetachedTimestampFile
        except ImportError:
            return None, None, "the opentimestamps package is not installed"
        if not provider_ref:
            return None, None, "no proof to upgrade"
        try:
            det = DetachedTimestampFile.deserialize(
                BytesDeserializationContext(base64.b64decode(provider_ref)))
        except Exception:
            return None, None, "the stored proof could not be parsed"

        errors: List[str] = []

        def walk(ts) -> None:
            # Snapshots, because merging mutates both collections while
            # we are walking them.
            for sub in list(ts.ops.values()):
                walk(sub)
            for att in list(ts.attestations):
                if not isinstance(att, PendingAttestation):
                    continue
                uri = (att.uri.decode() if isinstance(att.uri, bytes)
                       else str(att.uri))
                try:
                    ts.merge(RemoteCalendar(uri).get_timestamp(ts.msg))
                except Exception as e:
                    # One calendar being unreachable is survivable —
                    # any single one of them can complete the proof.
                    errors.append(f"{uri}: {type(e).__name__}")

        try:
            walk(det.timestamp)
        except Exception as e:
            return None, None, f"upgrade walk failed: {type(e).__name__}: {str(e)[:100]}"

        blocks = [int(a.height) for _m, a in det.timestamp.all_attestations()
                  if isinstance(a, BitcoinBlockHeaderAttestation)]
        if not blocks:
            # NOT an error state in the usual sense — aggregation takes
            # hours, so "not yet" is the expected answer for a fresh
            # anchor and the caller must not treat it as a failure.
            detail = ("; ".join(errors)) if errors else ""
            return None, None, ("not yet aggregated into a bitcoin block"
                                + (f" ({detail})" if detail else ""))

        out = BytesSerializationContext()
        det.serialize(out)
        # The EARLIEST block: the proof establishes existence before that
        # block, and a later attestation would overstate its own age.
        return base64.b64encode(out.getbytes()).decode("ascii"), min(blocks), None

    @staticmethod
    def _submit(calendar: str, digest: bytes, timeout: float = 15.0) -> bytes:
        import urllib.request
        req = urllib.request.Request(
            calendar.rstrip("/") + "/digest", data=digest,
            headers={"Accept": "application/vnd.opentimestamps.v1",
                     "Content-Type": "application/x-www-form-urlencoded",
                     "User-Agent": "solutionist-ledger/1.0"})
        return urllib.request.urlopen(req, timeout=timeout).read()


def proof_status(provider_ref: Optional[str],
                 provider: Optional[str] = None) -> Dict[str, Any]:
    """Ask the PROVIDER what its own receipt proves.

    Dispatching by provider rather than sniffing the blob is what lets
    two very different receipt formats coexist — a binary .ots and a
    Hedera transaction reference share nothing structurally, and a
    parser that guessed between them would eventually guess wrong in
    the direction of claiming a proof that is not there.
    """
    out = {"state": "none", "confirmed": False, "pending_at": [],
           "bitcoin_block": None}
    if not provider_ref and (provider or "local") == "local":
        return {**out, "state": "local"}
    p = _PROVIDERS.get((provider or "opentimestamps").strip())
    if not p:
        return {**out, "state": "unknown"}
    try:
        return {**out, **p.status(provider_ref)}
    except Exception:
        return {**out, "state": "unreadable"}


class HederaProvider(AnchorProvider):
    """Publishes the root as a Hedera Consensus Service message.

    WHY BOTH THIS AND OPENTIMESTAMPS. They fail and succeed
    differently, and an anchor is worth having in more than one place:

      speed     Hedera finalises in seconds. Bitcoin aggregation takes
                hours, so an OTS anchor spends most of its first day
                merely `submitted`. If a practice needs to say "proven"
                the same afternoon, this is the one that can.
      audience  "Recorded on a network governed by Google, IBM and
                Boeing" reads differently to a nervous practitioner
                than "Bitcoin" does. Same mathematics, different room.
      purpose   HCS exists to timestamp and order messages. OTS is a
                clever use of Bitcoin; this is the intended use of
                Hedera.

    TESTNET IS NOT EVIDENCE, and this is the decision that matters
    most here. Hedera's testnet is periodically WIPED. A proof there
    looks identical to a real one and disappears without warning, so
    `is_independent` is False on any network but mainnet. Getting that
    backwards would produce the single worst outcome this whole feature
    can have: a practice believing it holds evidence that has quietly
    ceased to exist.

    WHAT AN AUDITOR DOES WITH IT. The receipt names a network, a topic
    and a sequence number. They fetch the message from a PUBLIC mirror
    node over plain HTTP and compare its contents to the root. No
    account, no SDK, no cooperation from us.
    """
    name = "hedera"

    MIRRORS = {
        "mainnet": "https://mainnet-public.mirrornode.hedera.com",
        "testnet": "https://testnet.mirrornode.hedera.com",
    }

    @staticmethod
    def _network() -> str:
        return (os.environ.get("HEDERA_NETWORK") or "testnet").strip().lower()

    @property
    def is_independent(self) -> bool:
        # Only mainnet is durable. Testnet resets take the proof with them.
        return self._network() == "mainnet"

    @staticmethod
    def _config() -> Tuple[Optional[Dict[str, str]], Optional[str]]:
        acct = (os.environ.get("HEDERA_ACCOUNT_ID") or "").strip()
        key = (os.environ.get("HEDERA_PRIVATE_KEY") or "").strip()
        topic = (os.environ.get("HEDERA_TOPIC_ID") or "").strip()
        missing = [n for n, v in (("HEDERA_ACCOUNT_ID", acct),
                                  ("HEDERA_PRIVATE_KEY", key),
                                  ("HEDERA_TOPIC_ID", topic)) if not v]
        if missing:
            # Fail rather than fall back. anchor_business() writes no
            # receipt on an error, so a half-configured provider stays
            # silent instead of quietly anchoring nowhere.
            return None, "hedera is not configured: missing " + ", ".join(missing)
        return {"account": acct, "key": key, "topic": topic}, None

    def anchor(self, root: str) -> Tuple[Optional[str], Optional[str]]:
        cfg, err = self._config()
        if err:
            return None, err
        try:
            from hiero_sdk_python import (
                Client, Network, AccountId, PrivateKey, TopicId,
                TopicMessageSubmitTransaction)
        except ImportError:
            return None, "the hiero-sdk-python package is not installed"

        net = self._network()
        try:
            client = Client(Network(network=net))
            client.set_operator(AccountId.from_string(cfg["account"]),
                                PrivateKey.from_string(cfg["key"]))
            receipt = (TopicMessageSubmitTransaction()
                       .set_topic_id(TopicId.from_string(cfg["topic"]))
                       .set_message(root)
                       .execute(client))
        except Exception as e:
            return None, f"hedera submit failed: {type(e).__name__}: {str(e)[:120]}"

        ref = {"network": net, "topic": cfg["topic"], "root": root}
        for attr, label in (("topic_sequence_number", "sequence"),
                            ("topicSequenceNumber", "sequence"),
                            ("transaction_id", "transaction_id"),
                            ("transactionId", "transaction_id")):
            v = getattr(receipt, attr, None)
            if v is not None and label not in ref:
                ref[label] = str(v)
        return json.dumps(ref, separators=(",", ":"), sort_keys=True), None

    def status(self, provider_ref: Optional[str]) -> Dict[str, Any]:
        """Hedera reaches consensus before the call returns, so a stored
        receipt is already final — there is no pending state to poll,
        which is the whole speed advantage over Bitcoin.

        `independent` still depends on the network the receipt names,
        NOT on the one configured now. A testnet proof stays a testnet
        proof after someone switches the env var to mainnet.
        """
        out: Dict[str, Any] = {"state": "none", "confirmed": False,
                               "pending_at": [], "bitcoin_block": None}
        if not provider_ref:
            return out
        try:
            ref = json.loads(provider_ref)
            net = str(ref.get("network") or "")
            topic = str(ref.get("topic") or "")
        except Exception:
            return {**out, "state": "unreadable"}
        if not topic:
            return {**out, "state": "unreadable"}

        durable = net == "mainnet"
        mirror = self.MIRRORS.get(net)
        return {
            **out,
            "state": "confirmed" if durable else "testnet",
            "confirmed": durable,
            "network": net,
            "topic": topic,
            "sequence": ref.get("sequence"),
            "transaction_id": ref.get("transaction_id"),
            # The address an auditor curls. Nothing here is ours.
            "verify_url": (f"{mirror}/api/v1/topics/{topic}/messages"
                           if mirror else None),
            "durable": durable,
        }


_PROVIDERS: Dict[str, AnchorProvider] = {
    "local": LocalProvider(),
    "opentimestamps": OpenTimestampsProvider(),
    "hedera": HederaProvider(),
}


def register_provider(p: AnchorProvider) -> None:
    _PROVIDERS[p.name] = p


def get_provider(name: Optional[str] = None) -> AnchorProvider:
    key = (name or os.environ.get("LEDGER_ANCHOR_PROVIDER") or "local").strip()
    return _PROVIDERS.get(key, _PROVIDERS["local"])


# ─── Cadence ─────────────────────────────────────────────────────────
#
# WHAT SILENCE MEANS DEPENDS ON WHETHER ANYTHING IS DRIVING THIS.
# When anchoring was owner-triggered only, a provider going quiet meant
# "nobody asked" and calling that a fault would have been crying wolf.
# With the sweep running, the same silence means something IS wrong,
# because the schedule should have published. So staleness is derived
# from the interval rather than being a fixed constant — the health
# surface stays honest across both worlds instead of hard-coding the
# assumption that was true on the day it was written.

DEFAULT_INTERVAL_HOURS = 6
UNSCHEDULED_STALE_HOURS = 48


def schedule_enabled() -> bool:
    """Kill switch: LEDGER_ANCHOR_SCHEDULE=off."""
    return (os.environ.get("LEDGER_ANCHOR_SCHEDULE") or "on").strip().lower() != "off"


def schedule_interval_hours() -> float:
    """How often the sweep runs. Six hours by default.

    The tradeoff is exposure, not money: a record is not provable until
    it is anchored, so the interval is the longest a new row can sit
    unprovable. Hedera costs ~$0.0001 an anchor, so cost does not argue
    for a longer gap — but the OpenTimestamps calendars are free public
    infrastructure, and hammering them per-tenant per-hour would be rude
    for a gain nobody would notice.
    """
    try:
        v = float(os.environ.get("LEDGER_ANCHOR_INTERVAL_HOURS")
                  or DEFAULT_INTERVAL_HOURS)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_HOURS
    return v if v > 0 else DEFAULT_INTERVAL_HOURS


def stale_after_hours() -> float:
    """When silence becomes a finding rather than a fact."""
    if not schedule_enabled():
        return UNSCHEDULED_STALE_HOURS
    # Two missed runs. One missed run is a blip — a redeploy, a
    # leadership handover — and flagging it would train the operator to
    # ignore the page, which is the failure mode this whole surface is
    # trying to avoid. The floor keeps a very tight interval from making
    # every ordinary gap look like an outage.
    return max(2 * schedule_interval_hours(), 6)


def configured_providers(explicit: Optional[str] = None) -> List[str]:
    """Every network this deployment publishes to, in order.

    WHY A LIST AND NOT A CHOICE. Running one provider means a month of
    silent breakage is a month with no proof, and a gap cannot be
    repaired later — you cannot anchor last month at last month's
    timestamp. Two independent providers turn "no evidence" into "one
    of the two still has it", which is the only failure mode that
    actually matters here.

    `LEDGER_ANCHOR_PROVIDERS` is the plural form. The old singular
    `LEDGER_ANCHOR_PROVIDER` still works and still means exactly what it
    meant, so a deployment that has not been updated keeps its current
    behaviour instead of quietly gaining a second network.
    """
    raw = (explicit
           or os.environ.get("LEDGER_ANCHOR_PROVIDERS")
           or os.environ.get("LEDGER_ANCHOR_PROVIDER")
           or "local")
    out: List[str] = []
    for part in str(raw).split(","):
        name = part.strip()
        # Dedupe: a doubled name would anchor twice and collide on the
        # per-provider unique index, turning a config typo into an error.
        if name and name not in out:
            out.append(name)
    return out or ["local"]


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


def last_anchor(business_id: str,
                provider: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """This tenant's most recent receipt, optionally for ONE provider.

    THE PROVIDER FILTER IS WHAT MAKES REDUNDANCY REAL. Without it the
    window would be "everything since the newest anchor by anybody", so
    a provider that failed on rows 1-100 while the other succeeded would
    start its next run at 101 and never come back for the gap. Its
    outage would be permanent and invisible.

    Scoped per provider, each network anchors everything since ITS OWN
    last success — so a provider that was down for a day covers the
    missed rows on the next run, by itself, with no repair step.
    """
    q = (f"/ledger_anchors?business_id=eq.{business_id}"
         f"&select=id,first_sequence,last_sequence,merkle_root,provider,"
         f"provider_ref,anchored_at,row_count,algorithm")
    if provider:
        q += f"&provider=eq.{provider}"
    rows = sb_clients.sb_get_as_service(
        q + "&order=last_sequence.desc&limit=1") or []
    return rows[0] if rows else None


def record_failure(business_id: str, provider: str, error: str, *,
                   merkle_root: Optional[str] = None,
                   first_sequence: Optional[int] = None,
                   last_sequence: Optional[int] = None,
                   row_count: Optional[int] = None) -> None:
    """Write down that a provider did not publish.

    WHY THIS IS NOT A ROW IN ledger_anchors. A row there asserts a proof
    exists. Recording failures in the same table — even behind a status
    column — would make the receipt table lie in the one direction it
    must never lie. Diagnostics live somewhere else on purpose.

    WHY IT EXISTS. Redundancy is worthless if nobody notices a provider
    has gone quiet. Before this, a failed publish was a log line, which
    in practice meant invisible: a network could stop working for a
    month with nothing anywhere to say so.

    Never raises. Telemetry that can break the operation it observes is
    worse than no telemetry — a failure to record a failure must not
    also cost the OTHER provider its anchor.
    """
    try:
        sb_clients.sb_post_as_service("/ledger_anchor_failures", {
            "business_id": str(business_id),
            "provider": str(provider),
            "merkle_root": merkle_root,
            "first_sequence": first_sequence,
            "last_sequence": last_sequence,
            "row_count": row_count,
            # Bounded here rather than in the column: this is read by a
            # human deciding whether to go fix something, and a provider
            # that returns a wall of text should not fill the table.
            "error": str(error)[:500],
        })
    except Exception:
        logger.warning("[anchor] could not record the failure for %s", provider)


def _anchor_one(business_id: str, name: str) -> Dict[str, Any]:
    """Anchor this tenant's outstanding rows to ONE provider.

    Deterministic by construction: the window is "every hashed row after
    THIS provider's previous anchor", and rows are immutable, so the
    same window always yields the same root. Re-running when nothing new
    has landed is a no-op rather than a duplicate receipt.
    """
    out: Dict[str, Any] = {"provider": name, "ok": False, "anchored": False}
    provider = _PROVIDERS.get((name or "").strip())
    if provider is None:
        # A misspelt provider must NOT quietly fall back to `local`.
        # get_provider() does exactly that, which is tolerable when it is
        # a deliberate single choice and dangerous when it is one entry
        # in a list: the deployment would believe it was publishing to
        # two networks while one of them recorded nothing anywhere.
        err = f"'{name}' is not a registered anchor provider"
        logger.warning("[anchor] %s", err)
        record_failure(business_id, name, err)
        return {**out, "error": err}

    prev = last_anchor(business_id, provider.name)
    after = int(prev["last_sequence"]) if prev else 0
    rows = _rows_after(business_id, after)
    if not rows:
        return {**out, "ok": True,
                "reason": "nothing new to anchor since the last one"}

    hashes = [str(r["row_hash"]) for r in rows]
    first, last = int(rows[0]["sequence"]), int(rows[-1]["sequence"])
    window = {"first_sequence": first, "last_sequence": last,
              "row_count": len(rows)}
    root = merkle_root(hashes)

    try:
        ref, err = provider.anchor(root)
    except Exception as e:
        # An adapter that raises instead of returning an error is a bug
        # in the adapter, not a reason to lose the other provider's
        # anchor. Caught here so the contract "returns (ref, error)"
        # holds even when an adapter breaks it.
        ref, err = None, f"{type(e).__name__}: {str(e)[:120]}"

    if err:
        # No receipt on a failed publish. A row in ledger_anchors asserts
        # a proof exists; writing one when publication failed would make
        # the table lie in the one direction it must not. The failure is
        # recorded somewhere else so it is visible rather than silent.
        logger.warning("[anchor] %s failed to publish: %s", provider.name, err)
        record_failure(business_id, provider.name, err, merkle_root=root, **window)
        return {**out, "error": err, "merkle_root": root, **window}

    try:
        saved = sb_clients.sb_post_as_service("/ledger_anchors", {
            "business_id": str(business_id),
            "merkle_root": root,
            "algorithm": ALGORITHM,
            "provider": provider.name,
            "provider_ref": ref,
            **window,
        }, prefer="return=representation")
    except Exception as e:
        saved, err = None, f"{type(e).__name__}: {str(e)[:120]}"

    if not saved:
        # PUBLISHED BUT UNRECORDED — the uncomfortable case, and the
        # reason it gets recorded loudly. The root is already on the
        # network; only our receipt is missing. The next run recomputes
        # the same window and publishes again, which costs a fraction of
        # a cent and is far better than the alternative of writing a
        # receipt we are not sure of.
        err = err or "the anchor could not be saved"
        record_failure(business_id, provider.name,
                       f"published but the receipt could not be saved: {err}",
                       merkle_root=root, **window)
        return {**out, "error": err, "merkle_root": root, **window}

    return {**out, "ok": True, "anchored": True, "merkle_root": root,
            "provider_ref": ref, "independent": is_independent(provider.name),
            **window}


def anchor_business(business_id: str, *, provider_name: Optional[str] = None
                    ) -> Dict[str, Any]:
    """Anchor to every configured provider, independently.

    INDEPENDENTLY IS THE WHOLE CONTRACT. If one network is unreachable
    the other must still publish, because the point of running two is
    that a single outage never leaves a window with no proof at all. So
    every provider gets its own window, its own attempt and its own
    error, and nothing one of them does can abort the loop.
    """
    names = configured_providers(provider_name)
    results: List[Dict[str, Any]] = []
    for name in names:
        try:
            results.append(_anchor_one(business_id, name))
        except Exception as e:
            # The backstop. _anchor_one already handles the errors it can
            # foresee; this one exists so that an error it could not —
            # Supabase unreachable while reading the window, say — still
            # costs only this provider and not the other.
            err = f"{type(e).__name__}: {str(e)[:120]}"
            logger.warning("[anchor] %s raised: %s", name, err)
            record_failure(business_id, name, err)
            results.append({"provider": name, "ok": False,
                            "anchored": False, "error": err})

    anchored = [r for r in results if r.get("anchored")]
    failed = [r for r in results if r.get("error")]
    out: Dict[str, Any] = {
        "ok": not failed,
        "anchored": bool(anchored),
        "providers": results,
        "published_to": [r["provider"] for r in anchored],
        "failed_providers": [r["provider"] for r in failed],
        "independent": any(r.get("independent") for r in anchored),
    }
    # The flattened keys are what every existing caller reads. They point
    # at an INDEPENDENT receipt when there is one, so a `local` staging
    # anchor can never be the face of a run that also reached a real
    # network. `providers` carries the full per-network truth.
    best = next((r for r in anchored if r.get("independent")),
                anchored[0] if anchored else None)
    if best:
        for k in ("merkle_root", "first_sequence", "last_sequence",
                  "row_count", "provider", "provider_ref"):
            out[k] = best.get(k)
    elif failed:
        out["error"] = "; ".join(f"{r['provider']}: {r['error']}" for r in failed)
    else:
        out["reason"] = (results[0].get("reason") if results
                         else "nothing new to anchor since the last one")
    return out


def proof_for(business_id: str, sequence: int) -> Dict[str, Any]:
    """The proof that one row sits under a published root.

    ONE PROOF PER NETWORK. With two providers a record is normally
    covered twice, under two different windows and therefore two
    different roots — and each of those is a separate, independently
    checkable proof. Returning only the first would throw away exactly
    the redundancy the second network was added for, so every covering
    anchor is proved and they all come back in `proofs`.

    The flattened keys stay the shape every existing caller reads, and
    point at an INDEPENDENT proof whenever one exists: a `local` anchor
    must never be the face of a record that also has real evidence.
    """
    anchors = sb_clients.sb_get_as_service(
        f"/ledger_anchors?business_id=eq.{business_id}"
        f"&first_sequence=lte.{int(sequence)}&last_sequence=gte.{int(sequence)}"
        f"&select=id,first_sequence,last_sequence,merkle_root,provider,"
        f"provider_ref,anchored_at,algorithm&order=anchored_at.asc&limit=10") or []
    if not anchors:
        return {"ok": False,
                "reason": "this record is not covered by an anchor yet"}

    # Swap in the Bitcoin-upgraded proof where we have one. It is a
    # strict superset of the stored bytes, so everything downstream
    # behaves identically except that `confirmed` can finally be true.
    ups = upgrades_for([a.get("id") for a in anchors])
    for a in anchors:
        up = ups.get(str(a.get("id"))) or {}
        if up.get("upgraded_ref"):
            a["provider_ref"] = up["upgraded_ref"]
            a["bitcoin_block"] = up.get("bitcoin_block")

    proofs = [_proof_under(business_id, sequence, a) for a in anchors]
    usable = [p for p in proofs if p.get("ok")]
    best = next((p for p in usable if p.get("independent")),
                usable[0] if usable else proofs[0])
    return {**best,
            "proofs": proofs,
            "anchor_count": len(proofs),
            "independent_count": sum(1 for p in proofs if p.get("independent")),
            "providers": [p.get("provider") for p in proofs]}


def _proof_under(business_id: str, sequence: int,
                 a: Dict[str, Any]) -> Dict[str, Any]:
    """Prove one row under ONE anchor's window.

    Returns everything a verifier needs and nothing they must trust us
    for: the leaf's own row_hash, the sibling path, the root, and the
    public reference to check it against.
    """
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
        return {"ok": False, "provider": a.get("provider"),
                "reason": "that record is not in the anchored window"}

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


# ─── Health, for whoever has to keep this working ────────────────────
#
# Redundancy across two networks is worth nothing if nobody notices one
# of them has gone quiet. Everything below exists to answer one
# question an operator should never have to read logs for: is anchoring
# actually working, on each network, and if not, why not.

def _utc_z(dt: datetime) -> str:
    """PostgREST filters want the Z form, never `+00:00`.

    isoformat() yields '+00:00', and the '+' decodes to a space once the
    query string is parsed — so the filter matches nothing and the
    caller gets an empty list rather than an error. A silent empty is
    the worst possible failure for a health check, which would then
    report "no failures" precisely when it had lost the ability to see
    any.
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _safe_get(path: str) -> List[Dict[str, Any]]:
    """A health check must not 500 because the thing it inspects is broken.

    Most relevant before this arc's migration runs: ledger_anchor_failures
    does not exist yet, and the honest answer is "I cannot see failures",
    not a stack trace.
    """
    try:
        return sb_clients.sb_get_as_service(path) or []
    except Exception as e:
        logger.warning("[anchor-health] %s: %s", type(e).__name__, str(e)[:120])
        return []


def anchor_health(*, days: int = 7, recent: int = 25) -> Dict[str, Any]:
    """Per-provider anchoring health across every tenant.

    AGE IS A FACT, NOT AUTOMATICALLY A FAULT. Anchoring is owner-
    triggered today — nothing schedules it — so a provider can be
    perfectly healthy and still show a last success from weeks ago.
    `stale` therefore reports elapsed time and does not claim breakage;
    `failing` is the verdict that means something is actually wrong,
    and it is driven by a real error, not by silence.
    """
    now = datetime.now(timezone.utc)
    since = _utc_z(now - timedelta(days=int(days)))
    stale_hrs = stale_after_hours()

    wins = _safe_get(
        f"/ledger_anchors?anchored_at=gte.{since}"
        f"&select=business_id,provider,merkle_root,first_sequence,"
        f"last_sequence,row_count,anchored_at"
        f"&order=anchored_at.desc&limit=200")
    fails = _safe_get(
        f"/ledger_anchor_failures?failed_at=gte.{since}"
        f"&select=business_id,provider,error,merkle_root,first_sequence,"
        f"last_sequence,failed_at"
        f"&order=failed_at.desc&limit=200")

    # Names, so the panel reads as businesses rather than as uuids.
    ids = {str(r.get("business_id")) for r in (wins + fails) if r.get("business_id")}
    names: Dict[str, str] = {}
    if ids:
        for b in _safe_get("/businesses?id=in.(" + ",".join(sorted(ids)) +
                           ")&select=id,name&limit=200"):
            names[str(b.get("id"))] = b.get("name") or ""
    for r in wins + fails:
        r["business_name"] = names.get(str(r.get("business_id")), "")

    providers: List[Dict[str, Any]] = []
    for name in configured_providers():
        registered = name in _PROVIDERS
        last_ok = _safe_get(
            f"/ledger_anchors?provider=eq.{name}"
            f"&select=anchored_at,business_id,merkle_root,first_sequence,"
            f"last_sequence&order=anchored_at.desc&limit=1")
        last_bad = _safe_get(
            f"/ledger_anchor_failures?provider=eq.{name}"
            f"&select=failed_at,error,business_id&order=failed_at.desc&limit=1")
        ok_at = _parse_ts(last_ok[0]["anchored_at"]) if last_ok else None
        bad_at = _parse_ts(last_bad[0]["failed_at"]) if last_bad else None

        if not registered:
            # Configured but not a real adapter. Left as its own verdict
            # because it is a config error, not an outage, and the fix is
            # completely different.
            verdict = "unregistered"
        elif bad_at and (not ok_at or bad_at > ok_at):
            verdict = "failing"
        elif not ok_at:
            verdict = "never"
        elif now - ok_at > timedelta(hours=stale_hrs):
            verdict = "stale"
        else:
            verdict = "healthy"

        providers.append({
            "provider": name,
            "registered": registered,
            # Whether an anchor here is evidence at all. For hedera this
            # is false on testnet however healthy the plumbing looks.
            "independent": is_independent(name),
            "verdict": verdict,
            "last_success_at": last_ok[0]["anchored_at"] if last_ok else None,
            "hours_since_success": (round((now - ok_at).total_seconds() / 3600, 1)
                                    if ok_at else None),
            "last_failure_at": last_bad[0]["failed_at"] if last_bad else None,
            "last_error": (last_bad[0].get("error") if last_bad else None),
            "successes": sum(1 for r in wins if r.get("provider") == name),
            "failures": sum(1 for r in fails if r.get("provider") == name),
            "recent_successes": [r for r in wins
                                 if r.get("provider") == name][:recent],
            "recent_failures": [r for r in fails
                                if r.get("provider") == name][:recent],
        })

    return {
        "ok": not any(p["verdict"] in ("failing", "unregistered")
                      for p in providers),
        "providers": providers,
        "configured": configured_providers(),
        # False means this deployment publishes to nowhere a skeptic must
        # accept, whatever the verdicts above say.
        "any_independent": any(p["independent"] for p in providers),
        "window_days": int(days),
        "stale_after_hours": stale_hrs,
        # Whether anything is DRIVING anchoring. The surface needs this to
        # know what silence means: without it, "quiet" is just nobody
        # asking; with it, "quiet" is the schedule having failed to run.
        "scheduled": schedule_enabled(),
        "interval_hours": schedule_interval_hours(),
        "last_sweep": _last_sweep(),
        # How much of the OpenTimestamps half has actually reached
        # Bitcoin. Reported separately from the provider verdict because
        # they are different questions: a provider can be perfectly
        # healthy — every submission accepted — while none of its proofs
        # has been aggregated into a block yet.
        "bitcoin": _bitcoin_summary(),
        "total_successes": len(wins),
        "total_failures": len(fails),
        "generated_at": _utc_z(now),
    }


def _bitcoin_summary() -> Dict[str, Any]:
    """Confirmed vs still aggregating, across every OpenTimestamps proof."""
    ots = _safe_get("/ledger_anchors?provider=eq.opentimestamps"
                    "&select=id&limit=1000")
    ups = _safe_get("/ledger_anchor_upgrades?confirmed=is.true"
                    "&select=bitcoin_block&limit=1000")
    blocks = [int(u["bitcoin_block"]) for u in ups
              if u.get("bitcoin_block") is not None]
    return {
        "confirmed": len(ups),
        # "Awaiting" is the honest word: aggregation takes hours, so a
        # nonzero count here is normal and not a fault.
        "awaiting": max(0, len(ots) - len(ups)),
        "latest_block": max(blocks) if blocks else None,
        "last_upgrade": _last_upgrade(),
    }


def _last_upgrade() -> Optional[Dict[str, Any]]:
    try:
        import anchor_scheduler
        return anchor_scheduler.LAST_UPGRADE
    except Exception:
        return None


def _last_sweep() -> Optional[Dict[str, Any]]:
    """What the most recent scheduled sweep did, if one has run.

    Imported late so the scheduler can depend on this module without
    this module depending on the scheduler.
    """
    try:
        import anchor_scheduler
        return anchor_scheduler.LAST_SWEEP
    except Exception:
        return None


# ─── Bitcoin upgrades ────────────────────────────────────────────────
#
# A stored .ots is written at submission time and never learns about its
# own Bitcoin confirmation — the upgrade lives at the calendar. Left
# alone, every OpenTimestamps proof reports `submitted` forever, which
# throws away the distinction that is the entire reason there are two
# states. These read and refresh a cache of the upgraded proofs.
#
# Nothing here is evidence. Every row is derived and refetchable from
# public calendars by anyone, which is why the cache may be written over
# while ledger_anchors may not.

UPGRADE_SCAN_LIMIT = 500


def upgrades_for(anchor_ids: Any) -> Dict[str, Dict[str, Any]]:
    """Cached upgrades keyed by anchor id, for surfaces that list anchors."""
    ids = sorted({str(i) for i in (anchor_ids or []) if i})
    if not ids:
        return {}
    rows = _safe_get("/ledger_anchor_upgrades?anchor_id=in.(" + ",".join(ids)
                     + ")&select=anchor_id,upgraded_ref,bitcoin_block,confirmed"
                     + f"&limit={len(ids)}")
    return {str(r.get("anchor_id")): r for r in rows}


def upgrade_pending(limit: int = 25) -> Dict[str, Any]:
    """Fetch Bitcoin attestations for anchors that do not have one yet.

    Only OpenTimestamps has a pending state at all — Hedera reaches
    consensus before its submit call returns, so there is nothing to
    poll and nothing here touches it.

    "Not yet aggregated" is the EXPECTED answer for a fresh anchor, not
    a failure. It is recorded as a checked attempt so the row moves to
    the back of the queue, and retried on the next pass.
    """
    provider = _PROVIDERS.get("opentimestamps")
    if provider is None or not hasattr(provider, "upgrade"):
        return {"ok": False, "error": "no upgradable provider registered"}

    anchors = _safe_get(
        "/ledger_anchors?provider=eq.opentimestamps"
        "&select=id,business_id,provider,provider_ref,anchored_at"
        f"&order=anchored_at.asc&limit={UPGRADE_SCAN_LIMIT}")
    if not anchors:
        return {"ok": True, "checked": 0, "confirmed": 0, "pending": 0}

    settled = {str(r.get("anchor_id")) for r in _safe_get(
        "/ledger_anchor_upgrades?confirmed=is.true&select=anchor_id"
        f"&limit={UPGRADE_SCAN_LIMIT}")}
    todo = [a for a in anchors if str(a.get("id")) not in settled][:int(limit)]

    confirmed = pending = errored = 0
    for a in todo:
        try:
            ref, block, err = provider.upgrade(a.get("provider_ref"))
        except Exception as e:
            ref, block, err = None, None, f"{type(e).__name__}: {str(e)[:120]}"
        row: Dict[str, Any] = {
            "anchor_id": str(a.get("id")),
            "business_id": str(a.get("business_id")),
            "provider": "opentimestamps",
            "checked_at": _utc_z(datetime.now(timezone.utc)),
            "last_error": (str(err)[:300] if err else None),
        }
        if ref and block:
            confirmed += 1
            row.update({"upgraded_ref": ref, "bitcoin_block": int(block),
                        "confirmed": True,
                        "upgraded_at": _utc_z(datetime.now(timezone.utc))})
        elif err and "not yet" in err:
            pending += 1
            row["confirmed"] = False
        else:
            errored += 1
            row["confirmed"] = False
        try:
            # Upsert: one row per receipt, refreshed in place. Safe here
            # precisely because this table is a cache and not a claim.
            sb_clients.sb_post_as_service(
                "/ledger_anchor_upgrades", row,
                prefer="resolution=merge-duplicates,return=minimal")
        except Exception as e:
            logger.warning("[anchor-upgrade] could not cache %s: %s",
                           row["anchor_id"], e)

    out = {"ok": True, "checked": len(todo), "confirmed": confirmed,
           "pending": pending, "errored": errored,
           "outstanding": len([a for a in anchors
                               if str(a.get("id")) not in settled])}
    if todo:
        logger.info("[anchor-upgrade] %s", out)
    return out
