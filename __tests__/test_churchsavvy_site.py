"""ChurchSavvy's own website (churchsavvy_site.py).

What these pin:
  • churchsavvy.app answers with ChurchSavvy's pages — the home page, pricing
    and how it works with Solutionist — through public_site's host rule,
    never the platform's marketing site or a church's site;
  • an unknown path there is a real 404, and robots.txt / sitemap.xml list
    only its own pages;
  • the pages before the domain is ours open on the platform's hosts only,
    never on a church's custom domain;
  • the logo files are served by name and a crafted name can't leave the
    folder;
  • Start and Sign in go to ChurchSavvy's app, Start opening Create account.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import churchsavvy_site
import public_site


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://system.mysolutionist.app")
    monkeypatch.delenv("CHURCHSAVVY_SIGNIN_URL", raising=False)
    app = FastAPI()
    app.include_router(churchsavvy_site.router)
    app.include_router(public_site.router)
    return TestClient(app)


def _cs(client, path):
    return client.get(path, headers={"Host": "churchsavvy.app"})


def test_its_own_domain_answers_with_its_own_pages(client):
    home = _cs(client, "/")
    assert home.status_code == 200
    assert '<h1 id="hero-h" class="h1">Every service, <span class="grad">ready.</span></h1>' in home.text
    assert "<title>ChurchSavvy · Every service, ready.</title>" in home.text
    assert '<link rel="canonical" href="https://churchsavvy.app/">' in home.text
    assert "The Solutionist System" not in home.text, "never the platform's marketing site"
    for path, words in (("/pricing", "One price per church."), ("/solutionist", "Solutionist runs the rest of the week")):
        r = _cs(client, path)
        assert r.status_code == 200 and words in r.text, path
    # The tagline is "Every service, ready." (Kevin, 10/25): the Sunday one is gone everywhere.
    for path in ("/", "/pricing", "/solutionist"):
        assert "Every Sunday" not in _cs(client, path).text, path
    assert _cs(client, "/www-only").status_code == 404
    assert client.get("/", headers={"Host": "www.churchsavvy.app"}).status_code == 200


def test_robots_and_sitemap_are_its_own(client):
    robots = _cs(client, "/robots.txt")
    assert robots.status_code == 200 and "Sitemap: https://churchsavvy.app/sitemap.xml" in robots.text
    sm = _cs(client, "/sitemap.xml")
    assert sm.status_code == 200
    assert "https://churchsavvy.app/pricing" in sm.text and "mysolutionist" not in sm.text


def test_start_and_sign_in_go_to_its_app(client):
    import re
    for path in ("/", "/pricing", "/solutionist"):
        html = _cs(client, path).text
        starts = re.findall(r'<a class="btn[^"]*" href="([^"]+)">Start your church', html)
        assert starts, path
        assert all(h.startswith("https://system.mysolutionist.app/churchsavvy?signup=1") for h in starts), (path, starts)
        assert 'href="https://system.mysolutionist.app/churchsavvy">Sign in' in html, path
    assert "plan=both" in _cs(client, "/pricing").text


def test_the_plans_start_the_right_sign_up(client):
    """The app reads ?plan= and keeps it through sign-up, so the values are exact."""
    for path in ("/", "/pricing"):
        html = _cs(client, path).text
        plans = set(re.findall(r'href="https://system\.mysolutionist\.app/churchsavvy\?signup=1&amp;plan=([a-z]+)"', html))
        assert plans == {"churchsavvy", "planning", "both"}, (path, plans)


def test_the_home_page_is_the_church_the_booth_and_whats_in_it(client):
    html = _cs(client, "/").text
    assert "{{" not in html, "every token is filled"
    assert '<svg class="iso"' in html and 'class="stg-back"' in html and 'class="stg-front"' in html
    # The order: what it is, then the booth to try, then what's in it, then the teams.
    at = [html.index(f'id="{s}"') for s in ("hero-h", "product", "try", "inside", "planning", "screens", "pricing")]
    assert at == sorted(at)
    assert 'id="cs-try"' in html and 'data-act="show"' in html
    script = html[html.rindex("<script>"):]
    # What a visitor types goes on the screens as text, never as markup.
    for risky in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert risky not in script, risky
    assert "textContent" in script
    # The booth's Scripture is the KJV, and it says so when it doesn't carry a verse.
    assert "For God so loved the world, that he gave his only begotten Son" in script
    assert "every verse of the KJV and the WEB is there" in script
    # The phone menu and the chord chart in "Bring what you already have" are
    # different things: the menu's class once hid the chart on every screen.
    assert 'class="menu-sheet" id="sheet"' in html and ".sheet{display:none}" not in html
    # Made-up names only: the sample church is "Your Church".
    assert "Riverbend" not in html and "Love City" not in html


def test_the_pages_before_the_domain_open_on_the_platform_only(client):
    r = client.get("/churchsavvy/site", headers={"Host": "mysolutionist.app"})
    assert r.status_code == 200 and 'href="/churchsavvy/site/pricing"' in r.text
    assert client.get("/churchsavvy/site/pricing", headers={"Host": "mysolutionist.app"}).status_code == 200
    # A church's own domain never shows them.
    assert client.get("/churchsavvy/site", headers={"Host": "lovecitychurch.org"}).status_code == 404
    assert client.get("/churchsavvy/site/pricing", headers={"Host": "grace.mysolutionist.app"}).status_code == 404


def test_logo_files_by_name_only(client):
    r = client.get("/churchsavvy-assets/logo-mark.webp")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    # The share picture the pages name is one the folder serves (its name
    # changes with its words: the files are cached as never changing).
    share = re.search(r'<meta property="og:image" content="[^"]*(/churchsavvy-assets/[^"]+)">', _cs(client, "/").text)
    assert share and client.get(share.group(1)).headers["content-type"] == "image/png"
    for bad in ("..%2Fchurchsavvy_site.py", "logo-mark.svg", "nope.png", ".hidden.png"):
        assert client.get(f"/churchsavvy-assets/{bad}").status_code == 404, bad
    assert _cs(client, "/favicon.ico").status_code == 200


def test_only_pictures_leave_the_folder(client, tmp_path, monkeypatch):
    """A file in the folder that isn't one of its pictures is never served."""
    (tmp_path / "notes.txt").write_text("not for the public")
    (tmp_path / "mark.webp").write_bytes(b"RIFF0000WEBP")
    monkeypatch.setattr(churchsavvy_site, "_ASSETS", tmp_path)
    assert client.get("/churchsavvy-assets/notes.txt").status_code == 404
    assert client.get("/churchsavvy-assets/mark.webp").status_code == 200


def test_every_page_it_links_to_exists(client):
    import re
    for path in ("/", "/pricing", "/solutionist"):
        html = _cs(client, path).text
        for href in set(re.findall(r'href="(/[^"#?]*)', html)):
            assert _cs(client, href).status_code == 200, f"{path} links to {href}"
