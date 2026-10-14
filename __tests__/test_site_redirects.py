"""A hand-built site's old addresses answer with a 301 to their new page.

The promises, all through the real app (routers and middleware in their
real order; only the database and the page renderers are stubbed). The
stubbed database holds several sites and answers each lookup by its slug
or custom domain, so a test can tell one site from another:
- on the platform subdomain and on a custom domain, an old path in the
  site's manual_redirects gets a 301 to one of its own pages, keeping the
  visitor's own query string (the map's values win on a clash);
- a redirect only answers where the site would otherwise 404: a page, a
  hosted door (/give, /sermons/<id>) or an unknown path behave as before;
- one site's map never answers on another site, an unknown host, or a
  composed site, and a stored target that would leave the site is never
  followed;
- /live is the authenticated live-stream API, ahead of every site route,
  and is never redirected, whatever the row or the X-Original-Host says.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import public_site  # noqa: E402

RAILWAY = "kmj-intake-server-production.up.railway.app"


def subdomain(slug):
    return {"host": f"{slug}.mysolutionist.app"}


def custom_domain(domain):
    # How the Cloudflare Worker forwards a custom domain's request.
    return {"host": RAILWAY, "x-original-host": domain}


CHURCH = {"subdomain": subdomain("church"), "custom-domain": custom_domain("church.example")}
NEIGHBOR = {"subdomain": subdomain("neighbor"), "custom-domain": custom_domain("neighbor.example")}

REDIRECTS = {
    "/what-we-believe": "/beliefs",
    "/prayer-request": "/connect#prayer",
    "/volunteer": "/connect?interest=serve#connect-card",
    "/media": "/sermons",
    "/media/*": "/sermons",
}


def _row(slug, domain, page_ids, redirects, source="manual"):
    pages = {pid: f"<html><head></head><body>{slug.upper()} {pid.upper()} PAGE</body></html>"
             for pid in page_ids}
    return {"slug": slug, "business_id": f"biz-{slug}", "html_content": f"<html>{slug.upper()} HOME</html>",
            "site_config": {"html_source": source, "site_pages": ["home", *pages],
                            "generated_pages": pages, "custom_domain": domain,
                            "manual_redirects": dict(redirects)}}


@pytest.fixture(scope="module")
def app():
    import kmj_intake_automation
    return kmj_intake_automation.app


@pytest.fixture
def db(monkeypatch):
    """Two hand-built sites with their own maps, and a log of site reads.
    A lookup returns only the row its slug or custom domain names."""
    import no_card_trial
    state = SimpleNamespace(reads=[], rows={
        "church": _row("church", "church.example",
                       ("visit", "beliefs", "sermons", "connect", "watch"), REDIRECTS),
        "neighbor": _row("neighbor", "neighbor.example", ("visit", "shop"),
                         {"/old-news": "/visit", "/what-we-believe": "/shop"}),
    })

    async def fake_sb(client, path):
        state.reads.append(path)
        if not path.startswith("/business_sites?"):
            return []
        params = dict(p.split("=", 1) for p in path.split("?", 1)[1].split("&") if "=" in p)
        if "slug" in params:
            want = ("slug", unquote(params["slug"]).removeprefix("eq."))
        elif "site_config->>custom_domain" in params:
            want = ("domain", unquote(params["site_config->>custom_domain"]).removeprefix("eq."))
        else:
            return []           # academy lookups: no academies here
        return [row for row in state.rows.values()
                if (row["slug"] if want[0] == "slug" else row["site_config"]["custom_domain"]) == want[1]]

    async def visible(*args, **kwargs):
        return False

    async def augment(client, biz, slug, html, **kwargs):
        return html

    async def missing(client, slug, *args, **kwargs):
        return public_site.HTMLResponse(f"{slug.upper()} 404", status_code=404)

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
    return state


def _client(app):
    from fastapi.testclient import TestClient
    return TestClient(app, follow_redirects=False)


def _moved(r):
    return r.status_code, r.headers.get("location")


@pytest.mark.parametrize("hosts", CHURCH.values(), ids=CHURCH.keys())
@pytest.mark.parametrize("old,new", [
    ("/what-we-believe", "/beliefs"),
    ("/What-We-Believe/", "/beliefs"),
    ("/prayer-request", "/connect#prayer"),
    ("/volunteer", "/connect?interest=serve#connect-card"),
    ("/media/", "/sermons"),
    ("/media/page/2/", "/sermons"),
    ("/media/5np8j7s/love-city-experience-11-00am-10-11-26", "/sermons"),
])
def test_an_old_address_gets_a_301_to_its_new_page(app, db, hosts, old, new):
    r = _client(app).get(old, headers=hosts)
    assert _moved(r) == (301, new), r.text[:200]
    # A wrong entry can be fixed: browsers revalidate rather than keep it forever.
    assert "max-age=0" in r.headers.get("cache-control", "")


@pytest.mark.parametrize("hosts", CHURCH.values(), ids=CHURCH.keys())
@pytest.mark.parametrize("old,new", [
    # A campaign link still counts after the move.
    ("/what-we-believe?utm_source=facebook&utm_medium=social&utm_campaign=fall",
     "/beliefs?utm_source=facebook&utm_medium=social&utm_campaign=fall"),
    ("/media/5np8j7s/sermon?fbclid=IwAR0abc", "/sermons?fbclid=IwAR0abc"),
    ("/prayer-request?utm_source=bulletin", "/connect?utm_source=bulletin#prayer"),
    # Both name a parameter: the map's value wins, the visitor's others stay.
    ("/volunteer?interest=youth&utm_source=email",
     "/connect?interest=serve&utm_source=email#connect-card"),
    # The visitor's query can't change where the redirect goes.
    ("/what-we-believe?next=//evil.example", "/beliefs?next=%2F%2Fevil.example"),
])
def test_a_redirect_keeps_the_visitors_query(app, db, hosts, old, new):
    assert _moved(_client(app).get(old, headers=hosts)) == (301, new)


@pytest.mark.parametrize("hosts", CHURCH.values(), ids=CHURCH.keys())
def test_a_page_a_hosted_door_or_an_unknown_path_is_never_redirected(app, db, hosts):
    # Entries site_sync would refuse, written straight into the row.
    db.rows["church"]["site_config"]["manual_redirects"].update(
        {"/visit": "/connect", "/give": "/visit", "/sermons/*": "/visit"})
    client = _client(app)
    assert client.get("/visit", headers=hosts).text == "<html><head></head><body>CHURCH VISIT PAGE</body></html>"
    assert client.get("/give", headers=hosts).text == "HOSTED give"
    assert client.get("/sermons", headers=hosts).text.startswith("<html><head></head><body>CHURCH SERMONS PAGE")
    assert client.get("/sermons/b25fcb29-0837-4f7c-9d9a-2bfbcaf0bdee", headers=hosts).text == "HOSTED sermons"
    r = client.get("/my-love-nation", headers=hosts)
    assert (r.status_code, r.text) == (404, "CHURCH 404")


@pytest.mark.parametrize("site", ["church", "neighbor"])
@pytest.mark.parametrize("kind", ["subdomain", "custom-domain"])
def test_each_site_answers_only_its_own_old_addresses(app, db, site, kind):
    """Both sites map /what-we-believe, to different pages, and each map has
    a path the other lacks: every host gets its own site's answer."""
    hosts = (CHURCH if site == "church" else NEIGHBOR)[kind]
    client = _client(app)
    own = {"church": "/beliefs", "neighbor": "/shop"}[site]
    assert _moved(client.get("/what-we-believe", headers=hosts)) == (301, own)
    others_only = {"church": "/old-news", "neighbor": "/prayer-request"}[site]
    r = client.get(others_only, headers=hosts)
    assert (r.status_code, r.text, r.headers.get("location")) == (404, f"{site.upper()} 404", None)


@pytest.mark.parametrize("hosts", [subdomain("nobody"), custom_domain("nobody.example"), {"host": "nobody.example"}],
                         ids=["subdomain", "custom-domain", "direct-host"])
def test_an_unknown_host_never_redirects(app, db, hosts):
    r = _client(app).get("/what-we-believe", headers=hosts)
    assert r.status_code == 404 and r.headers.get("location") is None


@pytest.mark.parametrize("hosts", CHURCH.values(), ids=CHURCH.keys())
def test_a_composed_site_ignores_redirects(app, db, hosts):
    db.rows["church"]["site_config"]["html_source"] = "module-composer"
    r = _client(app).get("/what-we-believe", headers=hosts)
    assert (r.status_code, r.text, r.headers.get("location")) == (404, "CHURCH 404", None)


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example", "/\\evil.example",
                                    "/connect?next=https://evil.example", "javascript:alert(1)"])
def test_a_stored_target_that_would_leave_the_site_is_never_followed(app, db, target):
    db.rows["church"]["site_config"]["manual_redirects"]["/old"] = target
    r = _client(app).get("/old", headers=CHURCH["subdomain"])
    assert (r.status_code, r.headers.get("location")) == (404, None)


def _reaches_the_live_api(r):
    return (r.status_code in (401, 422) and r.headers.get("location") is None
            and "Missing Bearer token" in r.text)


@pytest.mark.parametrize("hosts", [
    CHURCH["subdomain"], CHURCH["custom-domain"], {"host": "church.example"},
    # Spoofed: the header names the church while the request is to the API
    # or platform host. Nothing on the site side looks at it for /live.
    {"host": RAILWAY, "x-original-host": "church.example"},
    {"host": "mysolutionist.app", "x-original-host": "church.example"},
    {"host": "www.mysolutionist.app", "x-original-host": "church.mysolutionist.app"},
    {"host": "localhost", "x-original-host": "church.example"},
], ids=["subdomain", "custom-domain", "direct-host", "spoofed-railway", "spoofed-platform",
        "spoofed-www", "spoofed-localhost"])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_live_always_reaches_the_api_even_when_a_row_maps_it(app, db, hosts, method):
    """GET /live is the live-stream API, ahead of the site catch-all. A
    request can't prove which host it came through without a Worker secret,
    so /live is never redirected: site_sync refuses to install it, and even
    an entry written straight into the row is never consulted."""
    db.rows["church"]["site_config"]["manual_redirects"]["/live"] = "/watch"
    r = _client(app).request(method, "/live", headers=hosts)
    assert r.headers.get("location") is None and r.status_code in (401, 405, 422)
    if method == "GET":
        assert _reaches_the_live_api(r)
    assert db.reads == []          # no site lookup happened at all


@pytest.mark.parametrize("hosts", [
    {"host": RAILWAY, "x-original-host": "nobody.example"},
    {"host": RAILWAY, "x-original-host": RAILWAY},
    {"host": "church.mysolutionist.app", "x-original-host": "nobody.example"},
], ids=["unknown-domain", "api-host", "site-host-to-unknown"])
def test_a_spoofed_original_host_that_names_no_site_never_redirects(app, db, hosts):
    r = _client(app).get("/what-we-believe", headers=hosts)
    assert r.status_code == 404 and r.headers.get("location") is None


def test_a_spoofed_original_host_can_only_get_that_sites_public_answer(app, db):
    """X-Original-Host picks which site answers (the Worker's own contract),
    so a spoofed one gets exactly what visiting that site gets: its 301 to a
    path on the site itself. A Location never names a host, so it can't be
    used to send a visitor anywhere else."""
    spoofed = {"host": "neighbor.mysolutionist.app", "x-original-host": "church.example"}
    direct = {"host": "church.example"}
    client = _client(app)
    for old in REDIRECTS:
        a, b = client.get(old.replace("/*", "/x"), headers=spoofed), client.get(old.replace("/*", "/x"), headers=direct)
        assert _moved(a) == _moved(b) and a.status_code == 301
        assert a.headers["location"].startswith("/") and not a.headers["location"].startswith("//")


@pytest.mark.parametrize("hosts", [{"host": "kmj-creative-solutions.mysolutionist.app"},
                                   custom_domain("kmjcreate.com")], ids=["subdomain", "custom-domain"])
def test_kmj_serves_exactly_as_before(app, db, hosts, monkeypatch):
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
    db.rows = {kmj.SLUG: row}
    client = _client(app)
    for path in ("/", "/about", "/services", "/contact"):
        r = client.get(path, headers=hosts)
        assert r.status_code == 200 and r.headers.get("x-solutionist-source") == "manual-site", path
    r = client.get("/what-we-believe?utm_source=x", headers=hosts)
    assert (r.status_code, r.headers.get("location")) == (404, None)
    assert _reaches_the_live_api(client.get("/live", headers=hosts))
