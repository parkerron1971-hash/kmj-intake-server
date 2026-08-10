"""What people agreed to, and proof of the exact words.

A consent record that stores a version NUMBER proves nothing. Version 1
is whatever the file says version 1 is today, and files change. Storing
the SHA-256 of the bytes someone accepted makes the claim checkable
years later: re-hash the archived text and compare. If the text was
edited afterwards the hashes diverge and the record says so, instead of
quietly agreeing with the new wording.

Same reason the action ledger hashes its rows. A promise you can
silently rewrite is not evidence.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import ai_disclosure as d

# Pinned on 2026-08-10. These are the hashes of the text that has been
# SHOWN to people. Changing a shipped version's wording breaks this on
# purpose: add a version instead, because everyone who accepted v1
# accepted the old words and no edit can reach back and change that.
PINNED = {
    "practitioner": "c0f937a8eb4fdc1c34990e55a015ce1a",
    "client":       "f34b97993fa15b53d983d99c8985ee97",
}


class TestTheDocuments:
    @pytest.mark.parametrize("audience", ["practitioner", "client"])
    def test_a_current_version_exists(self, audience):
        doc = d.current(audience)
        assert doc and doc["text"].strip()
        assert doc["hash"] and len(doc["hash"]) == 64

    @pytest.mark.parametrize("audience,prefix", sorted(PINNED.items()))
    def test_shipped_text_has_not_been_edited(self, audience, prefix):
        assert d.current(audience)["hash"].startswith(prefix), (
            f"the {audience} disclosure text changed. If that is intended, "
            f"ADD a version — do not edit one people have already accepted.")

    def test_line_endings_do_not_change_the_hash(self):
        """A file checked out on Windows must hash the same as the one a
        record was written from, or every consent looks tampered with on
        the wrong machine."""
        assert d.text_hash("a\r\nb") == d.text_hash("a\nb")

    def test_the_client_notice_is_short_enough_to_be_read(self):
        """It is read on a phone, mid-conversation, by somebody who did
        not come here for a policy. Length is a feature."""
        assert len(d.current("client")["text"]) < 700

    def test_the_client_notice_says_it_is_not_a_person(self):
        # Whitespace-collapsed: the text is hard-wrapped, so "not by a
        # person" spans a newline. The first version of this test
        # searched the raw string and failed against correct copy.
        t = " ".join(d.current("client")["text"].lower().split())
        assert "ai" in t and "not by a person" in t
        assert "human" in t, "it must say how to reach one"

    def test_the_practitioner_notice_states_the_limits_not_just_the_powers(self):
        t = " ".join(d.current("practitioner")["text"].lower().split())
        assert "never does on its own" in t
        assert "wrong" in t, "an AI disclosure that omits fallibility is marketing"


class TestStalenessIsDetected:
    def test_the_current_version_and_hash_pass(self):
        cur = d.current("practitioner")
        assert d.is_current("practitioner", cur["version"], cur["hash"]) is True

    def test_an_old_version_fails(self):
        assert d.is_current("practitioner", "0", None) is False

    def test_A_MATCHING_VERSION_WITH_A_STALE_HASH_FAILS(self):
        """The whole point. If the text changed underneath someone, their
        acceptance is stale even though the number still matches — and
        returning True here is the failure this module exists to prevent."""
        cur = d.current("practitioner")
        assert d.is_current("practitioner", cur["version"], "0" * 64) is False

    def test_a_missing_hash_still_passes_on_version(self):
        """Records written before hashes existed are not retroactively
        invalid — absent evidence is not contrary evidence."""
        cur = d.current("practitioner")
        assert d.is_current("practitioner", cur["version"], None) is True


class TestTheEndpoints:
    def test_the_client_disclosure_is_public(self):
        """Somebody texting a salon has no account and never will. A
        disclosure you must log in to read is not a disclosure."""
        import consent_router
        for r in consent_router.router.routes:
            if getattr(r, "path", "") == "/consent/disclosure/{audience}":
                names = [dep.call.__name__ for dep in r.dependant.dependencies
                         if getattr(dep, "call", None)]
                assert "require_user" not in names
                return
        pytest.fail("disclosure route not found")

    def test_accepting_requires_access_to_the_business(self):
        import inspect
        import consent_router
        src = inspect.getsource(consent_router.accept)
        assert "assert_access" in src

    def test_the_hash_comes_from_US_not_the_caller(self):
        """A caller that could post its own hash could manufacture a
        record of agreeing to text nobody was ever shown."""
        import inspect
        import consent_router
        src = inspect.getsource(consent_router.accept)
        assert 'doc["hash"]' in src
        assert "body.hash" not in src

    def test_a_lost_write_is_not_reported_as_success(self):
        """sb_clients returns None on 4xx/5xx without raising. Reporting
        success over a lost consent record is the one outcome this
        endpoint must never produce."""
        import inspect
        import consent_router
        src = inspect.getsource(consent_router.accept)
        assert "if not written:" in src
        assert "raise HTTPException(502" in src

    def test_a_superseded_version_cannot_be_accepted(self):
        import inspect
        import consent_router
        assert "superseded" in inspect.getsource(consent_router.accept)

    def test_status_distinguishes_never_from_stale(self):
        """"You never agreed" and "what you agreed to was replaced" are
        different conversations to have with someone."""
        import inspect
        import consent_router
        src = inspect.getsource(consent_router.status)
        assert "never_accepted" in src
        assert "text_changed_since_acceptance" in src
        assert "version_superseded" in src
