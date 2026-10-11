"""The auditor is given the proof that does not require trusting us.

The portal already proved the chain agrees with itself: our hashes match
our rows, and altering one breaks every record after it. That is a real
check and it is NOT evidence against us — anybody rewriting history
would recompute the hashes too and produce exactly the same green
result.

The anchors are the part that survives that objection. Each published a
merkle root to a public network at a time we did not control, so a root
that still matches could not have been written afterwards. Until now the
auditor could not see them at all: the one artefact that answers "why
should I believe you" existed and was not on the page.
"""
from __future__ import annotations

import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import audit_log
import auditor_portal

RENDER = inspect.getsource(auditor_portal._render)
SUMMARY = inspect.getsource(audit_log._anchor_summary)


def _code(src: str) -> str:
    """Executable code only — no comments, no docstrings.

    Assertions about what the CODE does have to read code. The first
    version of this file matched its own explanatory prose: the sentence
    "the same reason verify_anchor() is separate from proof_status()"
    contains the very string one test asserted was absent, so it failed
    against a correct implementation. The second version stripped `#`
    comments and still lost, because the offending text was in a
    DOCSTRING.

    ast.unparse discards both by construction — which is why this is the
    version that works, rather than a third guess at a regex.
    """
    import ast
    import textwrap
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


class TestTheReportCarriesTheAnchors:
    def test_verification_includes_them(self):
        assert '"anchors": _anchor_summary(biz)' in inspect.getsource(
            audit_log.verification_report)

    def test_the_summary_gives_an_address_not_a_verdict(self):
        """It returns the URL and the root — the things an auditor can
        act on — rather than only our own yes/no."""
        assert "verify_url" in SUMMARY
        assert "merkle_root" in SUMMARY

    def test_it_does_NOT_call_the_network(self):
        """This runs inside a page load an auditor is waiting on. A slow
        mirror node must not read as a slow ledger — the same reason
        verify_anchor() is separate from proof_status()."""
        code = _code(SUMMARY)
        assert "verify_on_chain(" not in code
        assert "verify_anchor(" not in code

    def test_a_failure_degrades_to_empty_not_to_an_exception(self):
        """The verification page must still render. Losing the anchor
        block is a smaller harm than losing the whole report."""
        assert "except Exception" in SUMMARY
        assert "return []" in SUMMARY


class TestThePageSaysTheHonestThing:
    def test_it_renders_an_anchor_section(self):
        assert "an_html" in RENDER
        assert "Independent proof" in RENDER

    def test_absence_is_stated_rather_than_omitted(self):
        """No anchors must not render as a blank space. A missing proof
        that looks like no section at all lets a reader assume there was
        nothing to prove."""
        assert "No fingerprint of these records has been published" in RENDER

    def test_it_admits_what_the_internal_check_is_worth(self):
        """The sentence that makes the rest honest: our own verification
        is a check we run on our own data."""
        low = RENDER.lower()
        assert "not proof against us" in low or "should not take our word" in low

    def test_independence_is_only_claimed_when_the_receipt_earns_it(self):
        """A testnet proof looks identical to a real one and disappears
        when the network resets. Calling it independent would be the
        single worst thing this feature could say."""
        assert 'a.get("independent")' in RENDER
        assert "NOT on a durable public network" in RENDER

    def test_the_auditor_gets_a_link_they_can_follow(self):
        assert "check it yourself" in RENDER
        assert "rel='noopener nofollow'" in RENDER

    def test_every_value_is_escaped(self):
        """The anchor block interpolates provider-supplied strings into
        HTML. This page is shown to an outside party holding a link.

        Checked against the WHOLE unparsed function, not a slice of it:
        a fragment cut between two markers is not valid Python on its
        own, and the previous version died on an IndentationError rather
        than on anything it meant to assert.
        """
        code = _code(RENDER)

        # Escaping at ASSIGNMENT is as good as escaping at the
        # interpolation, and this file does the former: `root` and
        # `where` already hold _e()-wrapped values by the time they reach
        # the f-string. An earlier version of this test asserted the
        # interpolations themselves were absent and failed against
        # correct code — it was enforcing a style, not a property.
        #
        # What actually matters is that nothing reaches HTML without
        # passing through _e() at some point.
        for name in ("root = _e(", "_e(cov.get('first_sequence'))"):
            assert name in code, f"value not escaped at assignment: {name}"

        # And the ones interpolated directly are wrapped in place.
        for direct in ("_e(str(a.get('anchored_at'))[:16])", "_e(url)"):
            assert direct in code, f"unescaped interpolation: {direct}"


class TestItDidNotBreakWhatWasThere:
    def test_the_chain_verdict_still_renders(self):
        for word in ("Unaltered", "Broken", "Not verifiable"):
            assert word in RENDER

    def test_erasures_still_render_beside_it(self):
        assert "{er_html}{an_html}" in RENDER or "er_html" in RENDER


# ─── Behaviour: a Bitcoin-confirmed anchor reads as confirmed ──────────
#
# The bug these pin: _anchor_summary read only the .ots bytes stored at
# submission, which never learn about their own Bitcoin confirmation.
# The confirmation lives in ledger_anchor_upgrades. So every auditor was
# told a confirmed anchor was "NOT on a durable public network".

_ROW = {"id": "a1", "first_sequence": 1, "last_sequence": 9, "row_count": 9,
        "merkle_root": "ab" * 32, "provider": "opentimestamps",
        "provider_ref": "STORED", "anchored_at": "2026-08-04T12:00:00Z"}


def _summary(monkeypatch, upgrades, status_by_ref):
    import ledger_anchor
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [dict(_ROW)])
    monkeypatch.setattr(ledger_anchor, "upgrades_for", lambda ids: upgrades)
    monkeypatch.setattr(ledger_anchor, "proof_status",
                        lambda ref, provider=None: status_by_ref[ref])
    return audit_log._anchor_summary("biz-1")


class TestTheUpgradeCacheIsRead:
    def test_confirmed_via_the_cache_is_independent_with_its_block(self, monkeypatch):
        out = _summary(
            monkeypatch,
            {"a1": {"anchor_id": "a1", "upgraded_ref": "UPGRADED",
                    "bitcoin_block": 961016, "confirmed": True}},
            {"STORED": {"state": "submitted", "confirmed": False, "bitcoin_block": None},
             "UPGRADED": {"state": "confirmed", "confirmed": True, "bitcoin_block": 961016}})
        a = out[0]
        assert a["independent"] is True
        assert a["state"] == "confirmed"
        assert a["bitcoin_block"] == 961016
        assert a["explorer_url"] == "https://mempool.space/block/961016"

    def test_the_cache_flag_is_the_fallback_when_bytes_cannot_be_parsed(self, monkeypatch):
        out = _summary(
            monkeypatch,
            {"a1": {"anchor_id": "a1", "upgraded_ref": "UPGRADED",
                    "bitcoin_block": 961016, "confirmed": True}},
            {"UPGRADED": {"state": "unreadable", "confirmed": False, "bitcoin_block": None}})
        assert out[0]["independent"] is True
        assert out[0]["bitcoin_block"] == 961016

    def test_waiting_for_a_block_stays_honest(self, monkeypatch):
        out = _summary(
            monkeypatch, {},
            {"STORED": {"state": "submitted", "confirmed": False, "bitcoin_block": None}})
        a = out[0]
        assert a["independent"] is False
        assert a["state"] == "submitted"
        assert a["explorer_url"] is None

    def test_a_failed_cache_read_degrades_to_the_stored_bytes(self, monkeypatch):
        import ledger_anchor
        import sb_clients
        monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [dict(_ROW)])

        def boom(ids):
            raise RuntimeError("cache down")
        monkeypatch.setattr(ledger_anchor, "upgrades_for", boom)
        monkeypatch.setattr(ledger_anchor, "proof_status",
                            lambda ref, provider=None: {"state": "submitted",
                                                        "confirmed": False})
        out = audit_log._anchor_summary("biz-1")
        assert out and out[0]["independent"] is False


def _page(anchor):
    return auditor_portal._render({
        "verification": {"hashed": 9, "intact": True, "checked": 9,
                         "first_sequence": 1, "last_sequence": 9,
                         "anchors": [anchor]},
        "entries": []})


class TestThePageStatesEachStateAsAFact:
    BASE = {"anchored_at": "2026-08-04T12:00:00Z", "merkle_root": "ab" * 32,
            "covers": {"first_sequence": 1, "last_sequence": 9, "rows": 9},
            "verify_url": None}

    def test_confirmed_names_the_block_and_links_it(self):
        html = _page({**self.BASE, "independent": True, "state": "confirmed",
                      "bitcoin_block": 961016,
                      "explorer_url": "https://mempool.space/block/961016"})
        assert "confirmed in block 961016" in html
        assert "https://mempool.space/block/961016" in html
        assert "ots verify" in html
        assert "NOT on a durable public network" not in html

    def test_waiting_says_waiting(self):
        html = _page({**self.BASE, "independent": False, "state": "submitted"})
        assert "waiting for its block" in html
        assert "NOT yet on a durable public network" in html

    def test_local_still_says_not_durable(self):
        html = _page({**self.BASE, "independent": False, "state": "local"})
        assert "recorded, but NOT on a durable public network" in html

    def test_hedera_mainnet_keeps_its_mirror_link(self):
        html = _page({**self.BASE, "independent": True, "state": "confirmed",
                      "verify_url": "https://mainnet.mirrornode.hedera.com/api/v1/topics/0.0.1/messages"})
        assert "published to a public network" in html
        assert "check it yourself" in html
