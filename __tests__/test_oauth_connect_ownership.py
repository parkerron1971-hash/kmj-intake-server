"""Starting an OAuth connect requires proving you own the business.

/connect/meta and /connect/quickbooks signed business_id into the OAuth
state and asked nothing else. A signed state proves the state came from
our server; it says nothing about who is holding it. So anyone could
open the connect URL with a stranger's business_id, authorise with their
OWN Facebook or Intuit account, and have their Pages or their
QuickBooks realm bound to that tenant.

Both are browser redirects opened with window.open, so they cannot carry
a bearer token — the check moves to an authenticated /start endpoint
that mints a short-lived ticket.
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import oauth_connect_ticket as tk


BIZ = "11111111-2222-3333-4444-555555555555"
USER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("OAUTH_CONNECT_TICKET_SECRET", "test-secret-not-real")


class TestTicket:
    def test_roundtrip(self):
        biz, user = tk.verify(tk.mint(BIZ, USER))
        assert biz == BIZ
        assert user == USER

    def test_tampered_body_rejected(self):
        t = tk.mint(BIZ, USER)
        body, sig = t.split(".", 1)
        forged = tk.mint("99999999-9999-9999-9999-999999999999", USER).split(".", 1)[0]
        assert tk.verify(f"{forged}.{sig}") == (None, None)

    def test_tampered_signature_rejected(self):
        body, _sig = tk.mint(BIZ, USER).split(".", 1)
        assert tk.verify(f"{body}.{'0' * 64}") == (None, None)

    def test_expired_rejected(self, monkeypatch):
        t = tk.mint(BIZ, USER)
        monkeypatch.setattr(tk.time, "time", lambda: time.time() + 3600)
        assert tk.verify(t) == (None, None)

    def test_a_different_secret_cannot_forge(self, monkeypatch):
        t = tk.mint(BIZ, USER)
        monkeypatch.setenv("OAUTH_CONNECT_TICKET_SECRET", "someone-elses-secret")
        assert tk.verify(t) == (None, None)

    @pytest.mark.parametrize("junk", ["", "   ", "no-dot", ".", "a.b",
                                      "....", "x" * 200])
    def test_malformed_never_raises(self, junk):
        assert tk.verify(junk) == (None, None)

    def test_verify_reveals_nothing_about_which_check_failed(self):
        """Same shape for expiry, tamper and garbage — a prober learns
        only that the ticket was not good."""
        body, _ = tk.mint(BIZ, USER).split(".", 1)
        assert tk.verify(f"{body}.{'0' * 64}") == tk.verify("garbage")


class TestLegacyEscapeHatch:
    def test_defaults_open_so_the_frontend_keeps_working(self, monkeypatch):
        """Backend ships before the frontend; flipping this on day one
        would break Connect for every practitioner mid-arc."""
        monkeypatch.delenv("OAUTH_ALLOW_UNVERIFIED_CONNECT", raising=False)
        assert tk.legacy_business_id_allowed() is True

    def test_zero_closes_it(self, monkeypatch):
        monkeypatch.setenv("OAUTH_ALLOW_UNVERIFIED_CONNECT", "0")
        assert tk.legacy_business_id_allowed() is False

    @pytest.mark.parametrize("value", ["1", "yes", "true", ""])
    def test_anything_else_leaves_it_open(self, monkeypatch, value):
        """Fails toward WORKING, not toward secure — deliberately, and
        only until the frontend ships. The inverse of every other
        default in this arc, which is why it is temporary."""
        monkeypatch.setenv("OAUTH_ALLOW_UNVERIFIED_CONNECT", value)
        assert tk.legacy_business_id_allowed() is True


class TestEndpointsAreWired:
    def test_both_start_endpoints_exist_and_are_authenticated(self):
        import meta_oauth
        import quickbooks_router

        found = {}
        for mod, attr, path in (
            (meta_oauth, "router", "/connect/meta/start"),
            (quickbooks_router, "connect_router", "/connect/quickbooks/start"),
        ):
            for r in getattr(mod, attr).routes:
                if getattr(r, "path", "") == path:
                    found[path] = r
        assert set(found) == {"/connect/meta/start", "/connect/quickbooks/start"}

        for path, route in found.items():
            names = [d.call.__name__ for d in route.dependant.dependencies
                     if getattr(d, "call", None)]
            assert "require_user" in names, f"{path} is not authenticated"

    def test_the_redirects_stay_unauthenticated(self):
        """They must remain open — a browser redirect cannot send a
        bearer token, which is the whole reason for the ticket."""
        import meta_oauth

        for r in meta_oauth.router.routes:
            if getattr(r, "path", "") == "/connect/meta":
                names = [d.call.__name__ for d in r.dependant.dependencies
                         if getattr(d, "call", None)]
                assert "require_user" not in names
                return
        pytest.fail("/connect/meta route not found")
