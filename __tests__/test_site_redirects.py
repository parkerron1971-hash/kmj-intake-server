"""A hand-built site's old addresses answer with a 301 to their new page.

The promises, all through the real app (routers and middleware in their
real order; only the database and the page renderers are stubbed):
- on the platform subdomain and on a custom domain, an old path in the
  site's manual_redirects gets a 301 to one of its own pages;
- a redirect only answers where the site would otherwise 404: a page, a
  hosted door (/give, /sermons/<id>) or an unknown path behave as before;
- composed sites ignore redirects entirely, and a stored target that would
  leave the site is never followed;
- /live, an authenticated API route ahead of the site catch-all, redirects
  only for an unauthenticated GET on a practitioner host whose hand-built
  site maps it. API hosts, the platform host, signed-in calls, calls that
  name a business, other sites and every failure reach the API as before.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import public_site  # noqa: E402

SUBDOMAIN = {"host": "church.mysolutionist.app"}
CUSTOM_DOMAIN = {"host": "kmj-intake-server-production.up.railway.app", "x-original-host": "church.example"}
HOSTS = {"subdomain": SUBDOMAIN, "custom-domain": CUSTOM_DOMAIN}

REDIRECTS = {
    "/what-we-believe": "/beliefs",
    "/prayer-request": "/connect#prayer",
    "/volunteer": "/connect?interest=serve#connect-card",
    "/media": "/sermons",
    "/media/*": "/sermons",
    "/live": "/watch",
}


@pytest.fixture(scope="module")
def app():
    import kmj_intake_automation
    return kmj_intake_automation.app


@pytest.fixture
def site(monkeypatch):
    """One site row, hand-built by default, plus a log of database reads."""
    import no_card_trial
    pages = {pid: f"<html><head></head><body>{pid.upper()} PAGE</body></html>"
             for pid in ("visit", "beliefs", "sermons", "connect", "watch")}
    row = {"slug": "church", "business_id": "biz-1", "html_content": "<html>HOME</html>",
           "site_config": {"html_source": "manual", "site_pages": ["home", *pages],
                           "generated_pages": pages, "custom_domain": "church.example",
                           "manual_redirects": dict(REDIRECTS)}}
    reads = []

    async def fake_sb(client, path):
        reads.append(path)
        if path.startswith("/business_sites?"):
            return [row]
        return []

    async def visible(*args, **kwargs):
        return False

    async def augment(client, biz, slug, html, **kwargs):
        return html

    async def missing(*args, **kwargs):
        return public_site.HTMLResponse("BRANDED 404", status_code=404)

    def hosted(name):
        async def handler(*args, **kwargs):
            return public_site.HTMLResponse(f"HOSTED {name}")
        return handler

    monkeypatch.setattr(public_site, "_sb", fake_sb)
    monkeypatch.setattr(public_site, "_check_rate", lambda *a, **k: True)
    monkeypatch.setattr(public_site, "_augment_html", augment)
    monkeypatch.setattr(public_site, "_render_not_found", missing)
    monkeypatch.setattr(no_card_trial, "site_hidden", visible)
    for name in ("give", "sermons", "events", "booking"):
        handler = "_serve_booking_page" if name == "booking" else f"_serve_{name}_page"
        monkeypatch.setattr(public_site, handler, hosted(name))
    row["reads"] = reads
    return row


def _client(app):
    from fastapi.testclient import TestClient
    return TestClient(app, follow_redirects=False)


@pytest.mark.parametrize("hosts", HOSTS.values(), ids=HOSTS.keys())
@pytest.mark.parametrize("old,new", [
    ("/what-we-believe", "/beliefs"),
    ("/What-We-Believe/", "/beliefs"),
    ("/prayer-request", "/connect#prayer"),
    ("/volunteer", "/connect?interest=serve#connect-card"),
    ("/media/", "/sermons"),
    ("/media/page/2/", "/sermons"),
    ("/media/5np8j7s/love-city-experience-11-00am-10-11-26", "/sermons"),
])
def test_an_old_address_gets_a_301_to_its_new_page(app, site, hosts, old, new):
    r = _client(app).get(old, headers=hosts)
    assert (r.status_code, r.headers.get("location")) == (301, new), r.text[:200]
    # A wrong entry can be fixed: browsers revalidate rather than keep it forever.
    assert "max-age=0" in r.headers.get("cache-control", "")


@pytest.mark.parametrize("hosts", HOSTS.values(), ids=HOSTS.keys())
def test_a_page_a_hosted_door_or_an_unknown_path_is_never_redirected(app, site, hosts):
    # Entries site_sync would refuse, written straight into the row.
    site["site_config"]["manual_redirects"].update(
        {"/visit": "/connect", "/give": "/visit", "/sermons/*": "/visit"})
    client = _client(app)
    assert client.get("/visit", headers=hosts).text == "<html><head></head><body>VISIT PAGE</body></html>"
    assert client.get("/give", headers=hosts).text == "HOSTED give"
    assert client.get("/sermons", headers=hosts).text.startswith("<html><head></head><body>SERMONS PAGE")
    assert client.get("/sermons/b25fcb29-0837-4f7c-9d9a-2bfbcaf0bdee", headers=hosts).text == "HOSTED sermons"
    assert client.get("/my-love-nation", headers=hosts).status_code == 404


@pytest.mark.parametrize("hosts", HOSTS.values(), ids=HOSTS.keys())
def test_a_composed_site_ignores_redirects(app, site, hosts):
    site["site_config"]["html_source"] = "module-composer"
    client = _client(app)
    r = client.get("/what-we-believe", headers=hosts)
    assert (r.status_code, r.text) == (404, "BRANDED 404")
    assert client.get("/live", headers=hosts).status_code == 401


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example", "/\\evil.example",
                                    "/connect?next=https://evil.example", "javascript:alert(1)"])
def test_a_stored_target_that_would_leave_the_site_is_never_followed(app, site, target):
    site["site_config"]["manual_redirects"]["/old"] = target
    assert _client(app).get("/old", headers=SUBDOMAIN).status_code == 404


@pytest.mark.parametrize("hosts", HOSTS.values(), ids=HOSTS.keys())
@pytest.mark.parametrize("method,path", [("GET", "/live"), ("GET", "/live/"), ("HEAD", "/live")])
def test_an_old_live_link_on_a_hand_built_site_goes_to_its_watch_page(app, site, hosts, method, path):
    r = _client(app).request(method, path, headers=hosts)
    assert (r.status_code, r.headers.get("location")) == (301, "/watch")


def _reaches_the_live_api(r):
    return r.status_code in (401, 422) and r.headers.get("location") is None


@pytest.mark.parametrize("hosts", HOSTS.values(), ids=HOSTS.keys())
def test_a_signed_in_or_business_scoped_live_call_always_reaches_the_api(app, site, hosts):
    client = _client(app)
    signed_in = client.get("/live", headers={**hosts, "authorization": "Bearer not-a-jwt"})
    assert _reaches_the_live_api(signed_in) and "Invalid token" in signed_in.text
    scoped = client.get("/live?business_id=009e9a2c-3e81-4bfc-a92a-205a8806aa99", headers=hosts)
    assert _reaches_the_live_api(scoped) and "Missing Bearer token" in scoped.text
    assert site["reads"] == []          # the redirect layer never looked


@pytest.mark.parametrize("host", ["kmj-intake-server-production.up.railway.app", "localhost",
                                  "mysolutionist.app", "www.mysolutionist.app"])
def test_live_on_the_api_and_platform_hosts_is_never_touched(app, site, host):
    r = _client(app).get("/live", headers={"host": host})
    assert _reaches_the_live_api(r) and "Missing Bearer token" in r.text
    assert site["reads"] == []


def test_live_on_a_hand_built_site_that_doesnt_map_it_still_reaches_the_api(app, site):
    del site["site_config"]["manual_redirects"]["/live"]
    r = _client(app).get("/live", headers=SUBDOMAIN)
    assert _reaches_the_live_api(r) and "Missing Bearer token" in r.text


def test_a_failed_lookup_lets_live_through_to_the_api(app, site, monkeypatch):
    async def broken(client, path):
        raise RuntimeError("database down")
    monkeypatch.setattr(public_site, "_sb", broken)
    r = _client(app).get("/live", headers=SUBDOMAIN)
    assert _reaches_the_live_api(r) and "Missing Bearer token" in r.text


def test_other_live_routes_are_untouched(app, site):
    r = _client(app).post("/live/start", headers=SUBDOMAIN, json={})
    assert r.status_code in (401, 422) and r.headers.get("location") is None
    assert site["reads"] == []


def test_the_redirect_layer_runs_before_routing():
    """It must sit in the app's middleware stack: GET /live never reaches
    the site catch-all, so a route could not do this."""
    import kmj_intake_automation
    assert any(m.cls is public_site.LegacyApiPathRedirect
               for m in kmj_intake_automation.app.user_middleware)


@pytest.mark.parametrize("hosts", [{"host": "kmj-creative-solutions.mysolutionist.app"},
                                   {"host": "kmj-intake-server-production.up.railway.app",
                                    "x-original-host": "kmjcreate.com"}], ids=["subdomain", "custom-domain"])
def test_kmj_serves_exactly_as_before(app, site, hosts, monkeypatch):
    """KMJ's real build, installed by site_sync, declares no redirects: its
    pages serve, an unknown path is its 404, and /live reaches the API."""
    import sb_clients
    import site_sync
    monkeypatch.setenv("SITE_CHECK", "off")
    monkeypatch.setenv("SITE_ADOPT", "off")
    kmj = next(m for m in site_sync.discover() if m.SLUG == "kmj-creative-solutions")
    row = {"id": "row-1", "slug": kmj.SLUG, "business_id": kmj.BUSINESS_ID,
           "site_config": {"custom_domain": "kmjcreate.com"}}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [row])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body: row.update(body))
    assert site_sync.sync_site(kmj) == "installed"
    assert "manual_redirects" not in row["site_config"]
    site.clear()
    site.update(row, reads=[])
    client = _client(app)
    for path in ("/", "/about", "/services", "/contact"):
        r = client.get(path, headers=hosts)
        assert r.status_code == 200 and r.headers.get("x-solutionist-source") == "manual-site", path
    assert client.get("/what-we-believe", headers=hosts).status_code == 404
    r = client.get("/live", headers=hosts)
    assert _reaches_the_live_api(r) and "Missing Bearer token" in r.text
