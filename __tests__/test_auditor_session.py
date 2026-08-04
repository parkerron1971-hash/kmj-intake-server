"""Getting the auditor's credential out of the URL.

The minted link has to carry its token in the path — it arrives by
email and a link has nowhere else to put one. What it does not have to
do is STAY there. The entry route trades the token for a scoped cookie
and redirects to a bare URL, so what lands in browser history, in a
bookmark, in a screenshot or on a shared screen grants nothing.

The tests that matter here are the ones about what the exchange must
NOT weaken: a session cannot be replayed as a link, cannot outlive the
link that made it, cannot see a wider window than it, and cannot
survive a revocation.
"""
from __future__ import annotations

import pathlib
import sys
import time

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

from test_i2_gl_sync import FakeSB  # noqa: E402


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setenv("AUDITOR_LINK_SECRET", "unit-test-secret")


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    fb.rows("businesses").append({
        "id": "b1", "name": "Test Practice", "owner_id": "owner1",
        "settings": {}, "type": "therapist"})
    return fb


@pytest.fixture
def minted(secret, fake):
    """A live link and the context it resolves to."""
    import auditor_links as al
    token, row = al.mint("b1", label="review", ttl_seconds=3600,
                         window_start="2026-01-01T00:00:00Z",
                         window_end="2026-06-30T00:00:00Z")
    return token, al.resolve(token)


# ─── The exchange ────────────────────────────────────────────────────

def test_a_session_carries_the_same_business_and_window(minted):
    import auditor_links as al
    _token, ctx = minted
    value, max_age = al.mint_session(ctx)
    out = al.resolve_session(value)
    assert out["business_id"] == "b1"
    assert out["jti"] == ctx["jti"]
    assert out["window_start"] == "2026-01-01T00:00:00Z"
    assert out["window_end"] == "2026-06-30T00:00:00Z"
    assert 0 < max_age <= al.SESSION_TTL_SECONDS


def test_a_session_never_outlives_its_link(secret, fake):
    """A 12-hour session minted from a link with 5 minutes left would
    hand out 12 hours of access the practice never granted."""
    import auditor_links as al
    token, _row = al.mint("b1", ttl_seconds=300)
    ctx = al.resolve(token)
    _value, max_age = al.mint_session(ctx)
    assert max_age <= 300


def test_an_expired_link_mints_no_session(secret, fake):
    import auditor_links as al
    ctx = {"business_id": "b1", "jti": "j1", "exp": int(time.time()) - 1}
    value, max_age = al.mint_session(ctx)
    assert value == "" and max_age == 0


def test_an_expired_session_is_refused(secret, fake, monkeypatch):
    import auditor_links as al
    token, _row = al.mint("b1", ttl_seconds=3600)
    ctx = al.resolve(token)
    value, _ = al.mint_session(ctx)
    assert al.resolve_session(value) is not None
    monkeypatch.setattr(time, "time", lambda: 1e12)
    assert al.resolve_session(value) is None


# ─── What the exchange must not weaken ───────────────────────────────

def test_a_session_cannot_be_used_as_a_link(minted):
    """THE test. Sessions and links are signed with the SAME key, so
    without a distinct HMAC domain a cookie would verify as a link and
    a link as a cookie — one credential type silently becoming the
    other, with the session's longer reach handed to whoever holds
    either."""
    import auditor_links as al
    _token, ctx = minted
    value, _ = al.mint_session(ctx)
    assert al.verify(value) is None, "a session must not verify as a link"


def test_a_link_cannot_be_used_as_a_session(minted):
    import auditor_links as al
    token, _ctx = minted
    assert al.resolve_session(token) is None, \
        "a link must not verify as a session"


def test_it_is_the_hmac_DOMAIN_that_separates_them_not_the_field_shape(secret):
    """The two tests above would pass even with no domain separation at
    all — a session payload has no `scp` so verify() rejects it on shape,
    and a link payload has no `typ` so resolve_session does the same.
    Passing for the wrong reason is how this suite has been fooled
    before, so: forge ONE payload that satisfies BOTH shapes and confirm
    that the signature domain is the thing still holding.
    """
    import auditor_links as al
    import hashlib
    import hmac
    import json
    now = int(time.time())
    claims = {"typ": "sess", "biz": "b1", "jti": "j1",
              "scp": [al.SCOPE_LEDGER_READ], "iat": now, "exp": now + 3600}
    p = al._b64url_encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    link_sig = al._b64url_encode(
        hmac.new(al._secret(), p.encode(), hashlib.sha256).digest())

    # Sanity: this payload really is a valid LINK, so the only variable
    # left below is which key-domain signed it.
    assert al.verify(f"{p}.{link_sig}") is not None
    assert al.resolve_session(f"{p}.{link_sig}") is None
    assert al.verify(f"{p}.{al._session_sig(p)}") is None


def test_revoking_the_link_kills_the_session(minted, fake):
    """Otherwise 'revoke' would mean 'revoke in twelve hours' — the
    cookie would keep working after the practice pulled access, which is
    the whole reason this is not a plain stateless signed value."""
    import auditor_links as al
    _token, ctx = minted
    value, _ = al.mint_session(ctx)
    assert al.resolve_session(value) is not None
    al.revoke("b1", ctx["jti"])
    assert al.resolve_session(value) is None


def test_a_session_fails_closed_when_revocation_cannot_be_checked(minted, monkeypatch):
    import auditor_links as al
    import sb_clients
    _token, ctx = minted
    value, _ = al.mint_session(ctx)

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", boom)
    assert al.resolve_session(value) is None


def test_a_tampered_session_is_refused(minted):
    """Widening the window by editing the cookie must not work — that is
    why the window rides inside the signature and not only in the row."""
    import auditor_links as al
    import json
    _token, ctx = minted
    value, _ = al.mint_session(ctx)
    payload_b64, sig = value.split(".", 1)
    claims = json.loads(al._b64url_decode(payload_b64))
    claims.pop("ws", None)
    claims.pop("we", None)
    forged = al._b64url_encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    assert al.resolve_session(f"{forged}.{sig}") is None


def test_a_session_for_another_tenant_cannot_be_forged(minted):
    import auditor_links as al
    import json
    _token, ctx = minted
    value, _ = al.mint_session(ctx)
    payload_b64, sig = value.split(".", 1)
    claims = json.loads(al._b64url_decode(payload_b64))
    claims["biz"] = "b2"
    forged = al._b64url_encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    assert al.resolve_session(f"{forged}.{sig}") is None


# ─── The routes ──────────────────────────────────────────────────────

_SRC = (_here.parent / "auditor_portal.py").read_text(encoding="utf-8")


def test_the_entry_route_renders_nothing_and_redirects():
    """The one route that sees the token must not have a page body: no
    body means no asset load, no referrer, nothing cached under a
    token-bearing URL."""
    body = _SRC.split("def auditor_entry(")[1].split("\ndef ")[0]
    assert "RedirectResponse" in body
    assert "status_code=303" in body
    assert "_render" not in body, "the entry route must not render the ledger"
    assert '"/public/audit/view"' in body, "it redirects to the bare URL"


def test_the_cookie_is_locked_down():
    body = _SRC.split("def auditor_entry(")[1].split("\ndef ")[0]
    assert "httponly=True" in body
    assert "secure=True" in body
    assert 'samesite="lax"' in body
    assert 'path="/public/audit"' in body, \
        "the cookie must not ride along with any other endpoint"


def test_no_route_still_takes_the_token_in_a_path_beyond_entry():
    """The old /public/audit/{token}/export would have put the
    credential straight back into a URL the auditor clicks."""
    assert '"/public/audit/{token}/export"' not in _SRC
    assert _SRC.count('@router.get("/public/audit/{token}")') == 1


def test_the_view_route_is_registered_before_the_token_route():
    """FastAPI matches in registration order. Registered the other way
    round, `{token}` swallows the literal 'view' and the page 404s on
    every visit."""
    assert _SRC.index('@router.get("/public/audit/view")') < \
        _SRC.index('@router.get("/public/audit/{token}")')


def test_the_export_buttons_carry_no_token():
    page = _SRC.split("def _render(")[1]
    assert "/public/audit/view/export?format=csv" in page
    assert "{_e(token)}" not in page


def test_an_ended_session_says_the_link_still_works():
    """An expired cookie is not a revoked link, and telling the auditor
    'gone' would send them back to the practice for no reason."""
    import auditor_portal as ap
    page = ap._render_gone()
    assert "link" in page.lower()
    assert "still valid" in ap._SESSION_GONE
    assert "<script>" not in page
    # Mobile parity: this page is read on phones like every other.
    assert "width=device-width" in page


def test_the_view_route_re_checks_the_session_every_request():
    body = _SRC.split("def auditor_view(")[1].split("\ndef ")[0]
    assert "_session(request)" in body
    assert "410" in body


def test_the_session_path_keeps_both_rate_limit_budgets():
    """Every view appends an undeletable ledger row under a per-tenant
    advisory lock. Moving the credential to a cookie must not quietly
    drop the flood protection that guarded that."""
    body = _SRC.split("def _session(")[1].split("\n@router")[0]
    assert 'allow_strict("auditor_link"' in body
    assert 'allow_strict("auditor_link_jti"' in body


# ─── End to end, through the real routes ─────────────────────────────
#
# The tests above read the source. These drive it: the plumbing between
# a 303, a Set-Cookie and the next request is exactly the kind of thing
# that greps happily confirm while the browser sees something else.

@pytest.fixture
def client(secret, fake, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import auditor_portal as ap

    # _load is the ledger read; the rendering it feeds has its own
    # tests. What is under test here is the credential handoff.
    monkeypatch.setattr(ap, "_load", lambda ctx, limit=500: {
        "business_name": "Test Practice",
        "generated_at": "2026-08-03T00:00:00Z",
        "range": {}, "entry_count": 0, "entries": [],
        "verification": {"intact": True, "checked": 1, "hashed": 1,
                         "first_sequence": 1, "last_sequence": 1,
                         "unverifiable_rows": 0, "gaps": [], "erasures": []},
    })
    app = FastAPI()
    app.include_router(ap.router)
    # https, not http: the cookie is Secure, so over plain http the
    # client would accept it and then never send it back — and the test
    # would pass for the wrong reason.
    return TestClient(app, base_url="https://testserver")


def test_the_browser_never_lands_on_a_url_holding_the_token(client, secret, fake):
    import auditor_links as al
    token, _row = al.mint("b1", ttl_seconds=3600)

    r = client.get(f"/public/audit/{token}", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/public/audit/view"
    assert token not in r.headers["location"]
    assert not r.content.strip(), "the token-bearing URL must render no page"


def test_the_cookie_is_set_with_every_flag(client, secret, fake):
    import auditor_links as al
    token, _row = al.mint("b1", ttl_seconds=3600)
    r = client.get(f"/public/audit/{token}", follow_redirects=False)
    raw = r.headers["set-cookie"].lower()
    assert "httponly" in raw and "secure" in raw
    assert "samesite=lax" in raw
    assert "path=/public/audit" in raw
    assert token.lower() not in raw, "the cookie must not simply carry the token"


def test_the_whole_journey_works(client, secret, fake):
    """Follow the redirect the way a browser does and land on the page."""
    import auditor_links as al
    token, _row = al.mint("b1", ttl_seconds=3600)
    r = client.get(f"/public/audit/{token}")     # follows the 303
    assert r.status_code == 200
    assert "Action Ledger" in r.text
    assert str(r.url).endswith("/public/audit/view")
    assert token not in str(r.url)
    # And the session persists for the next request without the token.
    again = client.get("/public/audit/view")
    assert again.status_code == 200


def test_the_page_is_unreachable_without_the_exchange(client):
    r = client.get("/public/audit/view")
    assert r.status_code == 410
    assert "session has ended" in r.text.lower()


def test_export_is_reachable_only_through_the_session(client):
    r = client.get("/public/audit/view/export?format=csv")
    assert r.status_code == 410


def test_a_revoked_link_stops_the_live_session(client, secret, fake):
    """The cookie is already in the jar. Revocation has to reach it."""
    import auditor_links as al
    token, _row = al.mint("b1", ttl_seconds=3600)
    assert client.get(f"/public/audit/{token}").status_code == 200
    ctx = al.verify(token)
    al.revoke("b1", ctx["jti"])
    assert client.get("/public/audit/view").status_code == 410
