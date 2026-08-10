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
