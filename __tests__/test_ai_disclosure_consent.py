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


CHURCH_PINNED = "b4d71bd1664fdf48da6a02197a4323f9"


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


class TestAChurchsOwnWords:
    """Kevin, 2026-11-06. A church read about clients and invoices. Its
    notice is its own document with its own hash; the business text and
    every acceptance of it are untouched."""

    def _church(self):
        return " ".join(d.current("practitioner", church=True)["text"].lower().split())

    def test_a_church_has_its_own_version_and_a_business_keeps_v1(self):
        assert d.current("practitioner", church=True)["version"] == "church-1"
        assert d.current("practitioner")["version"] == "1"
        assert d.current("practitioner", church=True)["hash"] != d.current("practitioner")["hash"]

    def test_a_churchs_text_is_pinned(self):
        assert d.current("practitioner", church=True)["hash"].startswith(CHURCH_PINNED), (
            "the church's disclosure text changed. ADD a version instead.")

    @pytest.mark.parametrize("word", ["client", "business", "invoice", "customer", "regulated"])
    def test_a_churchs_text_has_no_business_words(self, word):
        assert word not in self._church()

    def test_it_still_states_the_limits(self):
        t = self._church()
        assert "never does on its own" in t and "wrong" in t

    def test_it_promises_only_what_the_code_does(self):
        """A church isn't a regulated field, and bulk work runs when a person
        asks, so neither V1 line is promised here."""
        import policy_engine
        assert not policy_engine.is_regulated({"type": "church"})
        assert "regulated" not in self._church()
        assert "confirming the list" not in self._church()
        assert "unless someone asked it to" in self._church()

    def test_someone_who_accepted_the_business_text_sees_the_churchs_once(self):
        v1 = d.current("practitioner")
        assert d.is_current("practitioner", v1["version"], v1["hash"], church=True) is False
        c = d.current("practitioner", church=True)
        assert d.is_current("practitioner", c["version"], c["hash"], church=True) is True

    def test_a_business_is_never_held_to_the_churchs_text(self):
        v1 = d.current("practitioner")
        assert d.is_current("practitioner", v1["version"], v1["hash"]) is True

    def test_both_versions_stay_readable_for_the_record(self):
        assert d.get("practitioner", "1")["text"].startswith("How AI works")
        assert d.get("practitioner", "church-1")["text"].startswith("How AI works")


class TestAChurchThroughTheEndpoints:
    BIZ = "11111111-1111-1111-1111-111111111111"

    @pytest.fixture
    def env(self, monkeypatch):
        import business_access
        import consent_router as cr
        import sb_clients
        rows = {"type": "church", "records": [], "writes": []}

        def get(path):
            if path.startswith("/businesses"):
                return [{"type": rows["type"]}]
            if path.startswith("/consent_records"):
                return rows["records"]
            return []

        def post(path, body, prefer=None):
            rows["writes"].append(body)
            return [{"id": "r1"}]

        monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
        monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
        monkeypatch.setattr(business_access, "assert_access", lambda *a, **k: None)
        return cr, rows

    class _User:
        id = "u1"

    class _Req:
        headers = {}

    def test_status_names_the_churchs_version(self, env):
        cr, rows = env
        out = cr.status(self.BIZ, "practitioner", self._User())
        assert out["current"] is False and out["required_version"] == "church-1"

    def test_a_past_acceptance_of_the_business_text_is_superseded(self, env):
        cr, rows = env
        v1 = d.current("practitioner")
        rows["records"] = [{"version": "1", "text_hash": v1["hash"], "accepted_at": "2026-10-01"}]
        out = cr.status(self.BIZ, "practitioner", self._User())
        assert out["current"] is False and out["reason"] == "version_superseded"

    def test_the_public_route_serves_the_named_version(self, env):
        cr, _ = env
        assert cr.disclosure("practitioner", "church-1")["version"] == "church-1"
        assert cr.disclosure("practitioner")["version"] == "1"

    def test_accepting_records_the_hash_of_the_churchs_words(self, env):
        cr, rows = env
        cr.accept(cr.AcceptBody(business_id=self.BIZ, version="church-1"), self._Req(), self._User())
        assert rows["writes"][0]["version"] == "church-1"
        assert rows["writes"][0]["text_hash"] == d.current("practitioner", church=True)["hash"]

    def test_a_church_cant_accept_the_business_text(self, env):
        """An old tab showed the business words. The record has to hash what
        was shown, so that acceptance is refused, not filed as the church's."""
        from fastapi import HTTPException
        cr, rows = env
        with pytest.raises(HTTPException) as e:
            cr.accept(cr.AcceptBody(business_id=self.BIZ), self._Req(), self._User())
        assert e.value.status_code == 409 and rows["writes"] == []

    def test_a_business_is_unchanged(self, env):
        cr, rows = env
        rows["type"] = "barber"
        assert cr.status(self.BIZ, "practitioner", self._User())["required_version"] == "1"
        cr.accept(cr.AcceptBody(business_id=self.BIZ), self._Req(), self._User())
        assert rows["writes"][0]["version"] == "1"


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
