"""L3 — read-only ledger links for an outside reviewer.

A practice gets audited; the auditor is not a Solutionist customer and
never will be. This is the credential the OWNER mints, hands over, and
revokes when the review ends.

The shape is mcp_tokens', deliberately: the signature proves
authenticity, the table provides revocation. A stateless HMAC link
(store_files' downloads) would be wrong here — an audit link must be
revocable the instant a review ends.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import pathlib
import time

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

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


def _forge(secret_val: str, payload: dict) -> str:
    import auditor_links as al
    p = al._b64url_encode(json.dumps(payload, separators=(",", ":"),
                                     sort_keys=True).encode())
    sig = hmac.new(secret_val.encode(), p.encode(), hashlib.sha256).digest()
    return f"{p}.{al._b64url_encode(sig)}"


# ─── The credential itself ───────────────────────────────────────────

def test_mint_returns_plaintext_once_and_stores_only_a_hash(secret, fake):
    import auditor_links as al
    token, row = al.mint("b1", label="Baker & Co, 2026 review",
                         created_by="owner@x.com")
    assert token.count(".") == 1
    stored = fake.rows("auditor_links")[0]
    assert stored["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in json.dumps(stored), "the plaintext must never be stored"
    assert stored["label"] == "Baker & Co, 2026 review"
    assert stored["scopes"] == ["ledger:read"]


def test_forged_and_expired_links_are_refused(secret):
    import auditor_links as al
    now = int(time.time())
    base = {"biz": "b1", "jti": "j1", "scp": ["ledger:read"], "iat": now}
    assert al.verify(_forge("unit-test-secret", {**base, "exp": now + 60}))
    assert al.verify(_forge("WRONG-SECRET", {**base, "exp": now + 60})) is None
    assert al.verify(_forge("unit-test-secret", {**base, "exp": now - 1})) is None
    assert al.verify("not-a-token") is None
    assert al.verify("") is None


def test_scope_cannot_be_widened_by_editing_the_url(secret):
    """The scope rides inside the signed payload, so a reviewer cannot
    hand themselves write access by editing the link."""
    import auditor_links as al
    now = int(time.time())
    forged = _forge("unit-test-secret", {
        "biz": "b1", "jti": "j1", "scp": ["ledger:write"],
        "iat": now, "exp": now + 60})
    assert al.verify(forged) is None


def test_window_rides_inside_the_signature(secret, fake):
    """"The 2026 review" must not be able to wander into other years by
    editing a query string."""
    import auditor_links as al
    token, _ = al.mint("b1", window_start="2026-01-01T00:00:00Z",
                       window_end="2026-12-31T23:59:59Z")
    claims = al.verify(token)
    assert claims["ws"].startswith("2026-01-01")
    assert claims["we"].startswith("2026-12-31")


def test_revocation_fails_closed(secret, fake, monkeypatch):
    """An unknown row, a null result or a lookup error all mean revoked.
    On an external credential, "the check broke so access was granted"
    is the failure you least want."""
    import auditor_links as al
    assert al.is_revoked("") is True
    assert al.is_revoked("never-existed") is True

    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda q: (_ for _ in ()).throw(RuntimeError("db down")))
    assert al.is_revoked("j1") is True


def test_revoke_is_scoped_to_the_business(secret, fake):
    """A guessed jti from another tenant must not revoke anything."""
    import auditor_links as al
    _, row = al.mint("b1", label="x")
    al.revoke("b1", row["jti"])
    assert fake.rows("auditor_links")[0].get("revoked_at")


def test_resolve_refuses_a_revoked_link(secret, fake):
    import auditor_links as al
    token, row = al.mint("b1", label="x")
    assert al.resolve(token) is not None
    al.revoke("b1", row["jti"])
    assert al.resolve(token) is None


def test_list_never_exposes_the_hash(secret, fake):
    import auditor_links as al
    al.mint("b1", label="x")
    src = pathlib.Path(_here.parent / "auditor_links.py").read_text(encoding="utf-8")
    body = src.split("def list_links(")[1].split("def revoke(")[0]
    assert "token_hash" not in body.split("&select=")[1].split('"')[0]


def test_no_secret_configured_fails_loudly(monkeypatch):
    """Never mint something unverifiable because an env var is missing."""
    import auditor_links as al
    for env in al._SECRET_ENVS:
        monkeypatch.delenv(env, raising=False)
    with pytest.raises(RuntimeError):
        al._secret()


# ─── The public door ─────────────────────────────────────────────────

def test_minting_is_owner_only(secret, fake):
    """A credential that can mint credentials is a privilege-escalation
    ladder — the mint door is deliberately narrower than the read door."""
    import auditor_portal as ap
    u = type("U", (), {"id": "member1", "email": "m@x.com"})()
    with pytest.raises(HTTPException) as e:
        ap._require_owner("b1", u)
    assert e.value.status_code == 403
    owner = type("U", (), {"id": "owner1", "email": "o@x.com"})()
    assert ap._require_owner("b1", owner)["id"] == "b1"


def test_public_routes_are_rate_limited_before_verification():
    """Cheap pre-gate against a scripted token search, and every failure
    returns the SAME 404 — expired, revoked, forged and simply wrong
    must be indistinguishable from outside."""
    src = pathlib.Path(_here.parent / "auditor_portal.py").read_text(encoding="utf-8")
    body = src.split("def _resolve_or_404(")[1].split("def _load(")[0]
    assert "allow_strict" in body
    assert body.index("allow_strict") < body.index("auditor_links.resolve")
    assert body.count("404") >= 1 and "link not found" in body


def test_token_bearing_page_sets_the_security_headers():
    """The token is in the URL: no caching, no framing, and no Referer
    leak to any external asset."""
    src = pathlib.Path(_here.parent / "auditor_portal.py").read_text(encoding="utf-8")
    for h in ("X-Frame-Options", "frame-ancestors 'none'",
              "Referrer-Policy", "no-referrer", "no-store"):
        assert h in src


def test_auditor_view_is_itself_recorded():
    """Who looked, and when, is part of the record."""
    src = pathlib.Path(_here.parent / "auditor_portal.py").read_text(encoding="utf-8")
    body = src.split("def _load(")[1].split("@router.get")[0]
    assert "ledger:viewed_by_auditor" in body
    assert "audit_log.record(" in body


def test_public_page_reads_through_the_shared_select():
    """The widest audience must not get a wider column list. The page
    renders whatever ledger_report/ledger_entries return — it does not
    build its own query, so payload/result can never leak here."""
    src = pathlib.Path(_here.parent / "auditor_portal.py").read_text(encoding="utf-8")
    assert "ledger_report.build(" in src
    assert "/audit_log?" not in src, "the portal must not query the ledger directly"
    assert "payload" not in src.split("def _render(")[1]


def test_router_is_registered_above_the_catch_all():
    """public_site defines `/{path:path}`; registered after it,
    /public/audit/... would be swallowed."""
    src = pathlib.Path(_here.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert src.index("auditor_portal_router") < src.index("app.include_router(public_site_router)")


def test_rendered_page_escapes_business_content(secret):
    """Business names and verbs are user-controlled and land in HTML."""
    import auditor_portal as ap
    data = {
        "business_name": "<script>alert(1)</script>", "generated_at": "2026-08-03T00:00:00Z",
        "range": {}, "entry_count": 1,
        "entries": [{"sequence": 1, "created_at": "2026-08-03T10:00:00Z",
                     "actor_id": "<img src=x onerror=1>", "verb": "create_task",
                     "ok": True, "authorized_by": "chat", "subject_refs": []}],
        "verification": {"intact": True, "checked": 1, "hashed": 1,
                         "first_sequence": 1, "last_sequence": 1,
                         "unverifiable_rows": 0, "gaps": [], "erasures": []},
    }
    html_out = ap._render(data)
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;" in html_out
    assert "onerror=1" not in html_out or "&lt;img" in html_out


def test_page_reports_rather_than_reassures(secret):
    import auditor_portal as ap
    base = {"business_name": "T", "generated_at": "2026-08-03T00:00:00Z",
            "range": {}, "entry_count": 0, "entries": []}
    nothing = ap._render({**base, "verification": {
        "intact": True, "checked": 9, "hashed": 0, "first_sequence": 1,
        "last_sequence": 9, "unverifiable_rows": 9, "gaps": [], "erasures": []}})
    assert "Not verifiable" in nothing
    assert "nothing can be proven" in nothing
    broken = ap._render({**base, "verification": {
        "intact": False, "checked": 9, "hashed": 9, "broken_at": 4,
        "reason": "row contents do not match row_hash", "first_sequence": 1,
        "last_sequence": 9, "unverifiable_rows": 0, "gaps": [], "erasures": []}})
    assert "Broken" in broken and "#4" in broken
    for page in (nothing, broken):
        assert "nothing unusual" not in page.lower()
