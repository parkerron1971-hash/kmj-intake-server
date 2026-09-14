"""
test_business_sites_server_owned.py — the site row is the server's (2026-09-14).

business_sites has RLS on with one policy: anon may read a published
site. There is none for a signed-in practitioner. Routes under
business_access bind the practitioner's JWT, so brand_engine's helpers
read the site row back empty and had their patches refused silently —
the slot manifest showed nothing populated, set-site-type said "site not
found", a reroll could not save. Those helpers now read and write
business_sites as the server; every other table keeps the bound token.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import brand_engine
import sb_clients


def _bind(monkeypatch, calls):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: calls.append(("service", "GET", path)) or [{"id": "s1"}])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body: calls.append(("service", "PATCH", path)) or [{"id": "s1"}])
    monkeypatch.setattr(sb_clients, "sb_get_as_user", lambda path, jwt: calls.append(("user", "GET", path)) or [])
    monkeypatch.setattr(sb_clients, "sb_patch_as_user", lambda path, body, jwt: calls.append(("user", "PATCH", path)) or None)
    return sb_clients.set_user_jwt("header.payload.signature")


def test_business_sites_is_read_and_written_as_the_server_even_with_a_token_bound(monkeypatch):
    calls = []
    token = _bind(monkeypatch, calls)
    try:
        rows = brand_engine._sb_get("/business_sites?business_id=eq.b1&select=id,site_config&limit=1")
        out = brand_engine._sb_patch("/business_sites?id=eq.s1", {"site_config": {"site_type": "salon"}})
    finally:
        sb_clients._user_jwt_ctx.reset(token)
    assert rows == [{"id": "s1"}] and out == [{"id": "s1"}]
    assert calls == [("service", "GET", "/business_sites?business_id=eq.b1&select=id,site_config&limit=1"),
                     ("service", "PATCH", "/business_sites?id=eq.s1")]


def test_every_other_table_still_uses_the_bound_token(monkeypatch):
    calls = []
    token = _bind(monkeypatch, calls)
    try:
        brand_engine._sb_get("/businesses?id=eq.b1&limit=1")
        brand_engine._sb_patch("/business_profiles?business_id=eq.b1", {"tagline": "x"})
    finally:
        sb_clients._user_jwt_ctx.reset(token)
    assert [w for w, _, _ in calls] == ["user", "user"]


def test_slot_storage_and_site_type_go_through_the_same_helpers():
    src = pathlib.Path(brand_engine.__file__).parent
    slot = (src / "agents" / "slot_system" / "slot_storage.py").read_text(encoding="utf-8")
    site = (src / "public_site.py").read_text(encoding="utf-8")
    assert "from brand_engine import _sb_get as be_get" in slot
    assert "from brand_engine import _sb_patch as be_patch" in slot
    assert "from brand_engine import _sb_get as be_get, _sb_patch as be_patch" in site
