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


class TestTheLegacyPathIsGone:
    """The bare business_id parameter is deleted, not disabled.

    For one deploy both redirects also accepted `?business_id=`, behind
    OAUTH_ALLOW_UNVERIFIED_CONNECT, which defaulted OPEN so the backend
    could ship before the frontend. That default is itself the hazard:
    it fails toward working rather than toward secure, and it lives in
    an environment variable — so the hole reopens by being forgotten. A
    new Railway service, a restored config, a fresh region. The frontend
    sends tickets now (verified against production), so the parameter
    and the flag both go.
    """

    REDIRECTS = [("meta_oauth", "meta_connect"),
                 ("quickbooks_router", "qb_connect")]

    def test_the_escape_hatch_functions_no_longer_exist(self):
        assert not hasattr(tk, "legacy_business_id_allowed")
        assert not hasattr(tk, "warn_legacy")

    @pytest.mark.parametrize("mod_name,fn_name", REDIRECTS)
    def test_the_redirect_no_longer_accepts_a_business_id(self, mod_name, fn_name):
        """The load-bearing assertion of the arc.

        While the parameter exists, the hijack is still a well-formed
        call into the handler and the only thing refusing it is a
        branch. Once it is gone the request cannot be expressed at all:
        FastAPI drops the unknown query param and the handler is left
        holding no ticket.
        """
        import importlib
        import inspect
        mod = importlib.import_module(mod_name)
        params = inspect.signature(getattr(mod, fn_name)).parameters
        assert "business_id" not in params, (
            f"{mod_name}.{fn_name} still takes a bare business_id")
        assert "ticket" in params

    @pytest.mark.parametrize("mod_name,fn_name", REDIRECTS)
    def test_no_ticket_is_refused_rather_than_redirecting(self, mod_name, fn_name):
        import asyncio
        import importlib
        from fastapi import HTTPException
        mod = importlib.import_module(mod_name)
        with pytest.raises(HTTPException) as e:
            asyncio.run(getattr(mod, fn_name)())
        assert e.value.status_code == 400

    @pytest.mark.parametrize("mod_name,fn_name", REDIRECTS)
    def test_a_forged_ticket_is_refused(self, mod_name, fn_name):
        """Knowing the business id is no longer enough to build one —
        that is the whole difference between a ticket and a parameter."""
        import asyncio
        import importlib
        from fastapi import HTTPException
        mod = importlib.import_module(mod_name)
        body = tk.mint(BIZ, USER).split(".", 1)[0]
        with pytest.raises(HTTPException) as e:
            asyncio.run(getattr(mod, fn_name)(ticket=f"{body}.{'0' * 64}"))
        assert e.value.status_code == 400

    def test_a_valid_ticket_still_reaches_facebook(self, monkeypatch):
        """Guards the guard: a redirect that refused EVERYTHING would
        pass every assertion above while breaking Connect for everyone."""
        import asyncio
        from urllib.parse import parse_qs, urlparse

        import meta_oauth
        monkeypatch.setenv("META_APP_ID", "test-app-id")
        monkeypatch.setenv("META_REDIRECT_URI", "https://example.test/cb")
        monkeypatch.setenv("META_OAUTH_STATE_SECRET", "test-state-secret")
        resp = asyncio.run(meta_oauth.meta_connect(ticket=tk.mint(BIZ, USER)))
        assert resp.status_code == 302
        assert "facebook.com" in resp.headers["location"]
        # ...carrying the business the TICKET named, not one a caller chose
        state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
        assert meta_oauth._parse_state(state)["business_id"] == BIZ


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
