"""Reading a vendor's site server-side, without opening a hole.

THE SECURITY HALF IS THE POINT. A vendor's "website" is a field a user
typed, and fetching it from our server is server-side request forgery
unless every hop is checked. `http://169.254.169.254/` is a cloud
metadata endpoint; `http://localhost:5432` is a database. These tests
assert the guard runs BEFORE any socket is opened — a check that happens
after the fetch is not a check.

THE HONESTY HALF. A homepage is a marketing page. Measured on the first
real vendor a practitioner saved here, annieinc.com's front page carried
no ordering signals at all while its application page carried two. A
reader that stopped at the homepage would have said "nothing here" about
a supplier that plainly has a trade route — an empty state that lies,
about the exact question being asked.
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import site_preview as sp


# ─── SSRF: refused, and refused before the socket ────────────────────

BLOCKED = [
    ("http://169.254.169.254/latest/meta-data/", "cloud metadata by IP"),
    ("http://127.0.0.1:8000/", "loopback"),
    ("https://10.0.0.5/", "private range"),
    ("http://192.168.1.1/admin", "private range"),
    ("http://[::1]/", "loopback v6"),
    ("file:///etc/passwd", "not http"),
    ("ftp://example.com/x", "not http"),
    ("http://example.com:8080/", "non-standard port"),
    ("http://localhost/", "localhost"),
    ("", "empty"),
    ("not a url", "unparseable"),
]


@pytest.mark.parametrize("url,label", BLOCKED)
def test_dangerous_urls_never_reach_the_network(url, label, monkeypatch):
    """The guard has to run first. A refusal that happens after the
    request has gone out has already leaked whatever it was going to."""
    def _boom(*a, **kw):
        pytest.fail(f"opened a connection for a blocked URL ({label}): {url}")

    monkeypatch.setattr(sp, "_fetch_capped", _boom)
    out = sp.preview(url, use_cache=False)
    assert out["ok"] is False
    assert out.get("error")


def test_a_refusal_is_not_cached_as_an_answer(monkeypatch):
    """A hostname that failed to resolve this minute may be fine in ten,
    and a blocked one is cheap to re-check. Caching the refusal would
    make a transient failure permanent."""
    monkeypatch.setattr(sp, "_fetch_capped",
                        lambda *a, **kw: pytest.fail("should not fetch"))
    sp.preview("http://127.0.0.1/", use_cache=False)
    assert not any("127.0.0.1" in k for k in sp._CACHE)


def test_a_plain_domain_is_upgraded_to_https(monkeypatch):
    seen = {}

    def _fake(client, url, want="html"):
        seen["url"] = url
        return url, "<html><title>x</title></html>"

    monkeypatch.setattr(sp, "_fetch_capped", _fake)
    monkeypatch.setattr(sp, "guard_url", lambda u, **kw: None)
    sp.preview("example.com", use_cache=False)
    assert seen["url"].startswith("https://")


# ─── Extraction is pure and offline ──────────────────────────────────

PAGE = """
<html><head>
  <title>  Northwind   Supply </title>
  <meta name="description" content="Blank apparel for the trade.">
</head><body>
  <script>var x = "wholesale minimum order";</script>
  <a href="/pages/wholesale">Wholesale</a>
  <a href="/pages/about">About us</a>
  <a href="https://elsewhere.example/trade">Trade partners</a>
  <p>We welcome WHOLESALE enquiries. Minimum order is 24 units.</p>
  <p>We accept a purchase order on Net 30 terms.</p>
  <a href="mailto:orders@northwind.com">Email us</a>
  <a href="tel:+1 555 010 9999">Call</a>
  <img src="logo@2x.png">
  <p>Press kit: our logo file is logo@2x.png and the banner is hero@3x.jpg.</p>
</body></html>
"""


def test_the_signals_come_out_with_the_phrase_that_found_them():
    got = sp.extract(PAGE, "https://northwind.com/")
    keys = {s["key"] for s in got["signals"]}
    assert {"wholesale", "minimum", "purchase_order", "terms"} <= keys
    # Every finding says WHY, so the UI can report what the page said
    # rather than assert a capability the vendor never agreed to.
    assert all(s["phrase"] for s in got["signals"])


def test_script_contents_do_not_count_as_signals():
    """Otherwise a tracking script mentioning "wholesale" makes every
    site on it look like a trade supplier."""
    only_script = ('<html><body><script>var t = "wholesale purchase order '
                   'minimum order net 30";</script></body></html>')
    assert sp.extract(only_script, "https://x.com/")["signals"] == []


def test_contacts_are_found_and_image_names_are_not_emails():
    """Sites print filenames in visible copy — press kits, docs, alt
    text. `logo@2x.png` matches the shape of an address exactly, and
    offering it as a supplier's contact is worse than offering none."""
    got = sp.extract(PAGE, "https://northwind.com/")
    assert "orders@northwind.com" in got["emails"]
    assert not any(e.endswith((".png", ".jpg")) for e in got["emails"]), got["emails"]
    assert got["phones"] and "555" in got["phones"][0]


def test_title_and_description_are_tidied():
    got = sp.extract(PAGE, "https://northwind.com/")
    assert got["title"] == "Northwind Supply"
    assert got["description"] == "Blank apparel for the trade."


def test_relative_links_are_resolved_against_the_page():
    got = sp.extract(PAGE, "https://northwind.com/")
    urls = [l["url"] for l in got["links"]]
    assert "https://northwind.com/pages/wholesale" in urls


# ─── The second hop ──────────────────────────────────────────────────

def test_a_thin_homepage_makes_us_look_further(monkeypatch):
    """The annieinc.com case: nothing on the front page, everything on
    the wholesale page."""
    # The anchor TEXT deliberately carries no signal phrase — otherwise
    # the homepage answers the question by itself and the hop correctly
    # never happens. The href is what marks it as worth following.
    HOME = ('<html><title>Annie</title><body>'
            '<a href="/pages/wholesale-application">Learn more</a>'
            '</body></html>')
    DEEP = ('<html><title>Apply</title><body>We offer wholesale pricing. '
            'Account application below. <a href="mailto:inquiry@annie.com">'
            'Email</a></body></html>')
    fetched = []

    def _fake(client, url, want="html"):
        fetched.append(url)
        return url, (DEEP if "wholesale-application" in url else HOME)

    monkeypatch.setattr(sp, "_fetch_capped", _fake)
    monkeypatch.setattr(sp, "guard_url", lambda u, **kw: None)

    out = sp.preview("https://annie.com/", use_cache=False)
    keys = {s["key"] for s in out["signals"]}
    assert "wholesale" in keys and "apply" in keys
    assert out.get("also_read")
    # The address on the wholesale page is the one worth having.
    assert "inquiry@annie.com" in out["emails"]
    # And every finding says which page it came from.
    assert all(s.get("source") for s in out["signals"])


def test_a_homepage_that_already_answered_is_not_re_crawled(monkeypatch):
    RICH = ('<html><title>N</title><body>Wholesale pricing available. '
            'Account application here. Minimum order 24.</body></html>')
    fetched = []

    def _fake(client, url, want="html"):
        fetched.append(url)
        return url, RICH

    monkeypatch.setattr(sp, "_fetch_capped", _fake)
    monkeypatch.setattr(sp, "guard_url", lambda u, **kw: None)
    sp.preview("https://n.com/", use_cache=False)
    assert len(fetched) == 1, "spent extra fetches on a page that already answered"


def test_the_second_hop_never_leaves_the_vendors_own_site(monkeypatch):
    """A link labelled 'trade' pointing at somebody else's domain is not
    evidence about THIS vendor."""
    HOME = ('<html><title>N</title><body>'
            '<a href="https://elsewhere.example/wholesale">Wholesale</a>'
            '</body></html>')
    fetched = []

    def _fake(client, url, want="html"):
        fetched.append(url)
        return url, HOME

    monkeypatch.setattr(sp, "_fetch_capped", _fake)
    monkeypatch.setattr(sp, "guard_url", lambda u, **kw: None)
    sp.preview("https://n.com/", use_cache=False)
    assert not any("elsewhere.example" in u for u in fetched)


def test_the_extra_hops_are_capped(monkeypatch):
    HOME = '<html><title>N</title><body>nothing useful</body></html>'
    fetched = []

    def _fake(client, url, want="html"):
        fetched.append(url)
        return url, HOME

    monkeypatch.setattr(sp, "_fetch_capped", _fake)
    monkeypatch.setattr(sp, "guard_url", lambda u, **kw: None)
    sp.preview("https://n.com/", use_cache=False)
    assert len(fetched) <= 1 + sp._MAX_HOPS


# ─── Honest failure ──────────────────────────────────────────────────

def test_an_unreadable_site_says_so_rather_than_reporting_no_signals(monkeypatch):
    """"We could not read it" and "they have no trade route" are
    different answers about a company somebody may be about to order
    from."""
    def _boom(client, url, want="html"):
        raise ValueError("HTTP 403")

    monkeypatch.setattr(sp, "_fetch_capped", _boom)
    monkeypatch.setattr(sp, "guard_url", lambda u, **kw: None)
    out = sp.preview("https://n.com/", use_cache=False)
    assert out["ok"] is False
    assert "403" in out["error"]
    assert "signals" not in out


# ─── The sentence ────────────────────────────────────────────────────

def test_the_summary_describes_the_PAGE_not_the_vendor():
    """'They take purchase orders' is a claim about a company. 'Their
    site mentions purchase orders' is a fact about a page."""
    s = sp.summarise([{"key": "purchase_order", "label": "", "phrase": "po"}])
    assert s.startswith("Their site mentions")
    assert "purchase orders" in s


def test_no_signals_means_no_sentence():
    assert sp.summarise([]) == ""


def test_several_signals_read_as_a_list():
    s = sp.summarise([{"key": "wholesale", "label": "", "phrase": "w"},
                      {"key": "minimum", "label": "", "phrase": "m"},
                      {"key": "terms", "label": "", "phrase": "t"}])
    assert " and " in s and s.count(",") >= 1
