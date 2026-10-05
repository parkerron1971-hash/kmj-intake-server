"""Post for Me connect (part 1 of practitioner posting).

  1. Tokens never leave post_for_me: every account is cut to display fields.
  2. The sign-in link binds the RIGHT business (external_id) and asks for
     posting + feeds; Instagram uses Instagram login.
  3. Pilot gate: no key, or a business not on the pilot list, can't connect.
  4. The handshake: start mints a ticket for this business; the popup route
     only follows a valid ticket; the return page names nothing and logs
     parameter names only.
  5. Sync: adds new accounts, refuses one another business holds, and marks
     an account gone only when Post for Me says so — not when it was just
     relabelled to another business's refused sign-in.
  6. Disconnect only reaches this business's own connection.
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import oauth_connect_ticket  # noqa: E402
import post_for_me as pfm  # noqa: E402
import social_connect_router as scr  # noqa: E402

BIZ, OTHER = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
SESSION = SimpleNamespace(user=SimpleNamespace(id="user-1"))
RAW = {"id": "spc_1", "platform": "instagram", "username": "freshcutz", "user_id": "ig_9",
       "profile_photo_url": "https://cdn.test/p.jpg", "status": "connected", "external_id": BIZ,
       "access_token": "IGQ_SECRET", "refresh_token": "REFRESH_SECRET",
       "access_token_expires_at": "2026-12-01", "refresh_token_expires_at": "2027-01-01",
       "metadata": {"raw": "provider stuff"}}


@pytest.fixture(autouse=True)
def pilot(monkeypatch):
    monkeypatch.setenv("POST_FOR_ME_API_KEY", "pfm_test_key")
    monkeypatch.setenv("POST_FOR_ME_PILOT_BUSINESSES", f" {BIZ} ,")
    monkeypatch.setenv("OAUTH_CONNECT_TICKET_SECRET", "test-ticket-secret")


def run(coro):
    return asyncio.run(coro)


# ─── 1. tokens never leave ────────────────────────────────────────────

def test_public_account_drops_every_token():
    out = pfm.public_account(RAW)
    assert set(out) == {"id", "platform", "username", "user_id", "profile_photo_url",
                        "status", "external_id"}
    flat = repr(out)
    assert "SECRET" not in flat and "metadata" not in flat


def test_listing_strips_tokens(monkeypatch):
    async def fake(method, path, **kw):
        return {"data": [RAW]}
    monkeypatch.setattr(pfm, "_request", fake)
    accts = run(pfm.accounts_for(BIZ))
    assert accts and "SECRET" not in repr(accts)
    assert "SECRET" not in repr(run(pfm.accounts_by_ids(["spc_1"])))


def test_a_failed_call_logs_status_only(monkeypatch, caplog):
    import httpx

    def handler(request):
        return httpx.Response(400, json={"echo": "IGQ_SECRET"})
    orig = httpx.AsyncClient
    monkeypatch.setattr(pfm.httpx, "AsyncClient",
                        lambda **kw: orig(transport=httpx.MockTransport(handler), **kw))
    with caplog.at_level(logging.WARNING, logger="post_for_me"):
        with pytest.raises(pfm.PostForMeError) as e:
            run(pfm.accounts_for(BIZ))
    assert e.value.status == 400
    assert "IGQ_SECRET" not in caplog.text and "pfm_test_key" not in caplog.text


# ─── 2. the sign-in link ──────────────────────────────────────────────

def _capture(monkeypatch, url="https://www.instagram.com/oauth/authorize?x=1"):
    seen = {}

    async def fake(method, path, **kw):
        seen.update(method=method, path=path, **kw)
        return {"url": url, "platform": "instagram"}
    monkeypatch.setattr(pfm, "_request", fake)
    return seen


def test_auth_url_binds_this_business_and_asks_posts_and_feeds(monkeypatch):
    seen = _capture(monkeypatch)
    url = run(pfm.auth_url("instagram", BIZ))
    assert url.startswith("https://")
    body = seen["json"]
    assert seen["path"] == "/social-accounts/auth-url"
    assert body["external_id"] == BIZ
    assert body["permissions"] == ["posts", "feeds"]
    assert body["platform_data"] == {"instagram": {"connection_type": "instagram"}}
    assert "redirect_url_override" not in body       # Quickstart refuses it


def test_linkedin_is_an_organization_connection(monkeypatch):
    seen = _capture(monkeypatch)
    run(pfm.auth_url("linkedin", BIZ))
    assert seen["json"]["platform_data"] == {"linkedin": {"connection_type": "organization"}}


def test_unknown_network_and_non_https_answers_are_refused(monkeypatch):
    with pytest.raises(pfm.PostForMeError):
        run(pfm.auth_url("myspace", BIZ))
    _capture(monkeypatch, url="javascript:alert(1)")
    with pytest.raises(pfm.PostForMeError):
        run(pfm.auth_url("instagram", BIZ))


# ─── 3. the pilot gate ────────────────────────────────────────────────

def test_pilot_gate(monkeypatch):
    assert pfm.allowed_for(BIZ)
    assert not pfm.allowed_for(OTHER)
    monkeypatch.setenv("POST_FOR_ME_API_KEY", "")
    assert not pfm.allowed_for(BIZ)


def test_start_refuses_outside_the_pilot_and_bad_networks():
    with pytest.raises(HTTPException) as e:
        run(scr.postforme_connect_start(OTHER, "instagram", biz={}, session=SESSION))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        run(scr.postforme_connect_start(BIZ, "myspace", biz={}, session=SESSION))
    assert e.value.status_code == 400


# ─── 4. the handshake ─────────────────────────────────────────────────

def test_start_hands_back_a_ticket_for_this_business():
    out = run(scr.postforme_connect_start(BIZ, "Instagram", biz={}, session=SESSION))
    q = parse_qs(urlparse(out["authorize_url"]).query)
    assert out["authorize_url"].startswith("/connect/postforme?")
    assert q["platform"] == ["instagram"]
    assert oauth_connect_ticket.verify(q["ticket"][0])[0] == BIZ


def test_popup_follows_only_a_valid_ticket(monkeypatch):
    calls = []

    async def fake_auth(platform, external_id):
        calls.append((platform, external_id))
        return "https://www.instagram.com/oauth/authorize?x=1"
    monkeypatch.setattr(pfm, "auth_url", fake_auth)
    bad = run(scr.postforme_connect(ticket="forged", platform="instagram"))
    assert bad.status_code == 400 and calls == []
    ticket = oauth_connect_ticket.mint(BIZ, "user-1")
    ok = run(scr.postforme_connect(ticket=ticket, platform="instagram"))
    assert ok.status_code == 302 and ok.headers["location"].startswith("https://www.instagram.com/")
    assert calls == [("instagram", BIZ)]


def test_return_page_tells_the_app_and_logs_names_only(caplog):
    req = SimpleNamespace(query_params={"isSuccess": "true", "accountIds": "spc_SECRETID"})
    with caplog.at_level(logging.INFO, logger="social_connect"):
        page = run(scr.postforme_connect_done(req))
    html = page.body.decode()
    assert "solutionist-social-connected" in html and "Connected" in html
    assert "spc_SECRETID" not in caplog.text and "accountIds" in caplog.text
    failed = run(scr.postforme_connect_done(SimpleNamespace(query_params={"error": "access_denied"})))
    assert "Not connected" in failed.body.decode()


# ─── 5 & 6. sync and disconnect over a fake table ─────────────────────

class FakeTable:
    def __init__(self):
        self.rows = []
        self.n = 0

    def _match(self, row, path):
        q = path.split("?", 1)[1] if "?" in path else ""
        for part in q.split("&"):
            if "=" not in part:
                continue
            col, val = part.split("=", 1)
            if col in ("select", "order", "limit", "on_conflict"):
                continue
            if val.startswith("eq.") and str(row.get(col)) != val[3:]:
                return False
        return True

    def get(self, path):
        assert path.startswith("/social_connections")
        return [dict(r) for r in self.rows if self._match(r, path)]

    def post(self, path, body, prefer=None):
        for r in self.rows:
            if (r["provider"], r["provider_account_id"]) == (body["provider"], body["provider_account_id"]):
                r.update(body)
                return []
        self.n += 1
        self.rows.append({"id": f"row{self.n}", "connected_at": "now", **body})
        return []

    def patch(self, path, body):
        for r in self.rows:
            if self._match(r, path):
                r.update(body)


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(scr.sb_clients, "sb_get_as_service", t.get)
    monkeypatch.setattr(scr.sb_clients, "sb_post_as_service", t.post)
    monkeypatch.setattr(scr.sb_clients, "sb_patch_as_service", t.patch)
    return t


def _pfm(monkeypatch, listed, by_id=None):
    async def accounts_for(ext):
        return [pfm.public_account(a) for a in listed]

    async def accounts_by_ids(ids):
        return [pfm.public_account(a) for a in (by_id or []) if a["id"] in ids]
    monkeypatch.setattr(pfm, "accounts_for", accounts_for)
    monkeypatch.setattr(pfm, "accounts_by_ids", accounts_by_ids)


def test_sync_adds_a_new_account_without_tokens(table, monkeypatch):
    _pfm(monkeypatch, [RAW])
    out = run(scr.sync_connections(BIZ, biz={}, session=SESSION))
    assert out["added"] == [{"platform": "instagram", "username": "freshcutz"}]
    assert table.rows[0]["business_id"] == BIZ and table.rows[0]["status"] == "connected"
    assert "SECRET" not in repr(table.rows)


def test_an_account_another_business_holds_is_refused_not_moved(table, monkeypatch):
    table.rows.append({"id": "r0", "business_id": OTHER, "provider": "post_for_me",
                       "platform": "instagram", "provider_account_id": "spc_1",
                       "status": "connected", "connected_at": "then"})
    _pfm(monkeypatch, [RAW])
    out = run(scr.sync_connections(BIZ, biz={}, session=SESSION))
    assert out["conflicts"] == [{"platform": "instagram", "username": "freshcutz"}]
    assert table.rows[0]["business_id"] == OTHER


def test_relabelled_account_stays_connected_for_its_holder(table, monkeypatch):
    # BIZ holds spc_1; someone else's refused sign-in relabelled it at Post
    # for Me, so it no longer lists under BIZ — but it is still connected.
    table.rows.append({"id": "r0", "business_id": BIZ, "provider": "post_for_me",
                       "platform": "instagram", "provider_account_id": "spc_1",
                       "status": "connected", "connected_at": "then"})
    _pfm(monkeypatch, [], by_id=[dict(RAW, external_id=OTHER)])
    run(scr.sync_connections(BIZ, biz={}, session=SESSION))
    assert table.rows[0]["status"] == "connected"


def test_an_account_post_for_me_dropped_is_marked_disconnected(table, monkeypatch):
    table.rows.append({"id": "r0", "business_id": BIZ, "provider": "post_for_me",
                       "platform": "instagram", "provider_account_id": "spc_1",
                       "status": "connected", "connected_at": "then"})
    _pfm(monkeypatch, [], by_id=[dict(RAW, status="disconnected")])
    run(scr.sync_connections(BIZ, biz={}, session=SESSION))
    assert table.rows[0]["status"] == "disconnected"


def test_disconnect_only_reaches_this_business(table, monkeypatch):
    table.rows.append({"id": "r9", "business_id": OTHER, "provider": "post_for_me",
                       "platform": "instagram", "provider_account_id": "spc_9",
                       "status": "connected", "connected_at": "then"})
    called = []

    async def fake_disconnect(acct):
        called.append(acct)
    monkeypatch.setattr(pfm, "disconnect", fake_disconnect)
    with pytest.raises(HTTPException) as e:
        run(scr.disconnect_connection(BIZ, "r9", biz={}))
    assert e.value.status_code == 404 and called == []
    table.rows.append({"id": "r1", "business_id": BIZ, "provider": "post_for_me",
                       "platform": "instagram", "provider_account_id": "spc_1",
                       "status": "connected", "connected_at": "then"})
    run(scr.disconnect_connection(BIZ, "r1", biz={}))
    assert called == ["spc_1"] and table.rows[1]["status"] == "disconnected"


def test_connections_list_says_whether_posting_is_on(table):
    assert run(scr.list_connections(BIZ, biz={}))["enabled"] is True
    off = run(scr.list_connections(OTHER, biz={}))
    assert off["enabled"] is False and off["platforms"] == []


# ─── 7. only networks switched on in our Post for Me project ──────────

def test_default_networks_are_the_ones_switched_on(monkeypatch):
    monkeypatch.delenv("POST_FOR_ME_PLATFORMS", raising=False)
    assert pfm.enabled_platforms() == ("instagram", "facebook", "tiktok", "x", "youtube")
    monkeypatch.setenv("POST_FOR_ME_PLATFORMS", "threads, Instagram, myspace")
    assert pfm.enabled_platforms() == ("instagram", "threads")


def test_a_network_that_is_off_is_never_offered_or_started(monkeypatch, table):
    monkeypatch.delenv("POST_FOR_ME_PLATFORMS", raising=False)
    assert "linkedin" not in run(scr.list_connections(BIZ, biz={}))["platforms"]
    with pytest.raises(HTTPException) as e:
        run(scr.postforme_connect_start(BIZ, "linkedin", biz={}, session=SESSION))
    assert e.value.status_code == 400


def test_post_for_me_404_reads_as_switched_off(monkeypatch):
    async def not_enabled(platform, external_id):
        raise pfm.PostForMeError("Post for Me answered 404.", 404)
    monkeypatch.setattr(pfm, "auth_url", not_enabled)
    ticket = oauth_connect_ticket.mint(BIZ, "user-1")
    page = run(scr.postforme_connect(ticket=ticket, platform="tiktok"))
    assert "switched on" in page.body.decode()


def test_connect_lines_actually_print():
    # Root logs at WARNING in production; the module loggers carry their own.
    import logging as _l
    for name in ("social_connect", "post_for_me"):
        lg = _l.getLogger(name)
        assert lg.handlers and lg.level == _l.INFO, name
