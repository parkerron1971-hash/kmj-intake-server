"""An anchor is checked against the network, not against our own receipt.

HederaProvider.status() reports `confirmed` from the receipt WE wrote:
network == "mainnet" and nothing else. That is a self-attestation. It is
a fair one as far as it goes — Hedera reaches consensus before submit
returns — but it cannot tell a real anchor from a receipt that was
corrupted, truncated, hand-edited, or written by a submit that quietly
did something else. The class docstring already tells an auditor to curl
the mirror node; verify_on_chain does it ourselves instead of only
recommending it.

The distinction these tests exist for is THREE outcomes, not two:

    True   the mirror returned our message and it equals our root
    False  the mirror ANSWERED AND CONTRADICTS US — nothing there, or a
           different root. This is the alarm.
    None   we could not reach the mirror. UNKNOWN.

Collapsing None into False would turn a flaky DNS lookup into "your
audit trail is fake". Collapsing it into True would be worse.
"""
from __future__ import annotations

import base64
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import ledger_anchor

ROOT = "a" * 64
REF = json.dumps({"network": "mainnet", "topic": "0.0.123",
                  "sequence": 7, "root": ROOT}, sort_keys=True)


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._p = payload or {}

    def json(self):
        return self._p


def _mirror(monkeypatch, resp):
    import httpx
    monkeypatch.setattr(httpx, "get", lambda url, **kw: resp)


def _msg(text):
    return {"message": base64.b64encode(text.encode()).decode(),
            "consensus_timestamp": "1770000000.000000001"}


class TestItAgreesWithTheNetwork:
    def test_a_matching_message_verifies(self, monkeypatch):
        _mirror(monkeypatch, _Resp(200, _msg(ROOT)))
        out = ledger_anchor.HederaProvider().verify_on_chain(REF)
        assert out["verified"] is True
        assert "consensus_timestamp" in out


class TestItContradictsUsLoudly:
    def test_a_missing_message_is_FALSE_not_unknown(self, monkeypatch):
        """404 means the mirror looked and there is nothing there. That
        is the alarm this whole feature exists to be able to raise."""
        _mirror(monkeypatch, _Resp(404))
        out = ledger_anchor.HederaProvider().verify_on_chain(REF)
        assert out["verified"] is False
        assert "no message" in out["detail"]

    def test_a_different_root_is_FALSE(self, monkeypatch):
        _mirror(monkeypatch, _Resp(200, _msg("b" * 64)))
        out = ledger_anchor.HederaProvider().verify_on_chain(REF)
        assert out["verified"] is False
        assert "does NOT match" in out["detail"]
        # The prefixes let a human see WHICH is wrong without dumping
        # a full hash into a log line.
        assert out["published_prefix"] != out["claimed_prefix"]

    def test_an_unreadable_receipt_is_FALSE(self):
        """Our own record being corrupt is a real finding, not an
        unknown — we are the ones who wrote it."""
        out = ledger_anchor.HederaProvider().verify_on_chain("not json")
        assert out["verified"] is False


class TestUnreachableIsNotDisproven:
    def test_a_network_error_is_UNKNOWN(self, monkeypatch):
        import httpx

        def _boom(url, **kw):
            raise httpx.ConnectError("dns")
        monkeypatch.setattr(httpx, "get", _boom)
        out = ledger_anchor.HederaProvider().verify_on_chain(REF)
        assert out["verified"] is None, (
            "an unreachable mirror must never read as a failed proof")

    def test_a_5xx_is_UNKNOWN(self, monkeypatch):
        _mirror(monkeypatch, _Resp(503))
        assert ledger_anchor.HederaProvider().verify_on_chain(REF)["verified"] is None

    def test_a_receipt_missing_fields_is_UNKNOWN(self):
        ref = json.dumps({"network": "mainnet", "topic": "0.0.1"})
        out = ledger_anchor.HederaProvider().verify_on_chain(ref)
        assert out["verified"] is None

    def test_testnet_has_no_mirror_configured_case(self):
        """A network we have no mirror for cannot be checked — unknown,
        not a failure. Testnet IS in MIRRORS, so this asserts the shape
        via an invented network rather than pretending testnet is absent."""
        ref = json.dumps({"network": "sandbox", "topic": "0.0.1",
                          "sequence": 1, "root": ROOT})
        assert ledger_anchor.HederaProvider().verify_on_chain(ref)["verified"] is None


class TestTheModuleEntryPoint:
    def test_it_is_separate_from_proof_status(self):
        """status() is cheap and local and runs on health surfaces;
        verification makes a live third-party call. Folding them together
        would put a network round-trip behind a dashboard refresh and make
        a slow mirror look like a degraded ledger."""
        import inspect
        assert "verify_on_chain" not in inspect.getsource(ledger_anchor.proof_status)

    def test_a_provider_without_verification_is_unknown(self, monkeypatch):
        out = ledger_anchor.verify_anchor("{}", provider="local")
        assert out["verified"] is None
        assert out["provider"] == "local"

    def test_it_never_raises(self, monkeypatch):
        def _explode(*a, **k):
            raise RuntimeError("kaboom")
        monkeypatch.setattr(ledger_anchor.HederaProvider, "verify_on_chain", _explode)
        out = ledger_anchor.verify_anchor(REF, provider="hedera")
        assert out["verified"] is None


class TestTheSequenceLessPath:
    """No sequence is the COMMON case, not the edge case.

    anchor() only records `sequence` when the SDK receipt happens to
    expose topic_sequence_number / topicSequenceNumber. It does not — so
    every anchor written to date carries network/topic/root/
    transaction_id and no sequence. Checked against production: 5 of 5,
    then 8 of 8 once the scan path existed.

    A verifier that required a sequence would have reported every real
    anchor as unverifiable, and it would have looked like the ANCHORS
    were broken rather than the verifier.
    """

    NOSEQ = json.dumps({"network": "mainnet", "topic": "0.0.123", "root": ROOT},
                       sort_keys=True)

    def test_it_finds_the_root_by_scanning_the_topic(self, monkeypatch):
        _mirror(monkeypatch, _Resp(200, {"messages": [
            {"message": base64.b64encode(b"someone elses root").decode(),
             "sequence_number": 4},
            {"message": base64.b64encode(ROOT.encode()).decode(),
             "sequence_number": 5, "consensus_timestamp": "1.2"},
        ]}))
        out = ledger_anchor.HederaProvider().verify_on_chain(self.NOSEQ)
        assert out["verified"] is True
        assert out["sequence"] == 5

    def test_absence_from_the_scan_is_false_but_says_it_was_BOUNDED(self):
        """"Not in the last 100" is a weaker claim than "not present",
        and the difference matters to whoever reads it. Saying only
        "false" would overstate what was actually checked."""
        import httpx
        import pytest as _pytest

        class _M:
            status_code = 200

            def json(self):
                return {"messages": [
                    {"message": base64.b64encode(b"other").decode(),
                     "sequence_number": 1}]}

        with _pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx, "get", lambda url, **kw: _M())
            out = ledger_anchor.HederaProvider().verify_on_chain(self.NOSEQ)
        assert out["verified"] is False
        assert "not among the last" in out["detail"]
        assert out["searched"] == 1

    def test_a_receipt_without_even_a_root_is_still_unknown(self):
        ref = json.dumps({"network": "mainnet", "topic": "0.0.1"})
        assert ledger_anchor.HederaProvider().verify_on_chain(ref)["verified"] is None
