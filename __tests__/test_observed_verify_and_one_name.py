"""Two things a real send this morning showed.

1. A domain Resend verified on its own (records pasted, Verify never
   pressed) stayed `pending` in settings, so the identity seam kept
   sending as the platform while the screen said Verified. /status now
   records an observed verification.
2. The seeded templates end with "{closing_line}\\n{practitioner_name}";
   the signature starts with the same name. The send read the name
   twice. One name is enough.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import email_domains_router as edr  # noqa: E402
import email_layout as L  # noqa: E402
import email_sender  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


PENDING = {"domain": "studiok.com", "from_local_part": "hello", "from_name": "Sarah",
           "resend_domain_id": "dom_1", "status": "pending", "records": [], "verified_at": None}


def _u(uid):
    return type("U", (), {"id": uid, "email": None})()


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": "b1", "owner_id": "owner1", "name": "Studio K",
                                  "settings": {"email_domain": dict(PENDING)}})
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    return fb


def _live(monkeypatch, status):
    async def _resend(method, path, json_body=None):
        return {"id": "dom_1", "status": status, "records": []}
    monkeypatch.setattr(edr, "_resend", _resend)


def test_status_records_a_verification_the_provider_reached_on_its_own(fake, monkeypatch):
    _live(monkeypatch, "verified")
    email_sender._IDENTITY_CACHE["id:b1"] = (0, {"stale": True})
    out = asyncio.run(edr.domain_status("b1", _u("owner1")))
    cfg = fake.rows("businesses")[0]["settings"]["email_domain"]
    assert out["live_status"] == "verified" and out["status"] == "verified"
    assert cfg["status"] == "verified" and cfg["verified_at"]
    assert "id:b1" not in email_sender._IDENTITY_CACHE       # next send picks the new identity
    # and the identity seam agrees from here on
    email_addr, _ = email_sender.resolve_from_address(fake.rows("businesses")[0],
                                                       default_email="noreply@mysolutionist.app")
    assert email_addr == "hello@studiok.com"


def test_status_writes_nothing_while_still_pending(fake, monkeypatch):
    _live(monkeypatch, "pending")
    before = dict(fake.rows("businesses")[0]["settings"]["email_domain"])
    asyncio.run(edr.domain_status("b1", _u("owner1")))
    assert fake.rows("businesses")[0]["settings"]["email_domain"] == before


def test_status_keeps_the_original_verified_at(fake, monkeypatch):
    fake.rows("businesses")[0]["settings"]["email_domain"] = {**PENDING, "verified_at": "2026-08-01T00:00:00+00:00"}
    _live(monkeypatch, "verified")
    asyncio.run(edr.domain_status("b1", _u("owner1")))
    assert fake.rows("businesses")[0]["settings"]["email_domain"]["verified_at"] == "2026-08-01T00:00:00+00:00"


SIG = {"name": "Kevin McCloud", "business": "KMJ Creative Solutions", "phone": "555-0100"}
SETTINGS = {"email_templates": {"signature": SIG, "global_rules": {"closing_line": "Best,"}}}


def test_seeded_template_ending_does_not_double_the_name():
    body = "Hi Jordan,\n\nThanks for connecting.\n\nBest,\nKevin McCloud"   # {closing_line}\n{practitioner_name}
    out = L.compose_trailers(body, SETTINGS)
    assert out.count("Kevin McCloud") == 1
    assert out == "Hi Jordan,\n\nThanks for connecting.\n\nBest,\nKevin McCloud\nKMJ Creative Solutions\n555-0100"


def test_a_body_that_mentions_the_name_elsewhere_is_untouched():
    body = "Kevin McCloud asked me to send this.\n\nThanks!"
    out = L.compose_trailers(body, SETTINGS)
    assert out.startswith("Kevin McCloud asked me to send this.")
    assert out.count("Kevin McCloud") == 2


def test_chief_composer_matches_the_layout_composer():
    import chief_of_staff as cos
    body = "Hello,\n\nBest,\nKevin McCloud"
    biz = {"id": "b1", "name": "KMJ", "settings": SETTINGS}
    assert cos._compose_body_with_signature(body, biz) == L.compose_trailers(body, SETTINGS)
