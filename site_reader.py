"""
site_reader.py — the vendor's actual page, inside the system (2026-08-21).

WHY THIS EXISTS AFTER I ARGUED AGAINST IT
  The first answer was "you can't embed an arbitrary site, most refuse to
  be framed". That is true of an IFRAME POINTED AT THEIR SERVER, and it
  is not the only way to put a page on screen. X-Frame-Options tells a
  BROWSER not to frame a URL; it says nothing about a page we already
  fetched server-side and re-render ourselves.

  So: fetch it on the server (we already do), strip everything that can
  execute or phone home, rewrite what is left so it still looks like
  their page, and hand it to a fully sandboxed iframe as srcdoc. The
  practitioner sees the actual page without leaving, and without their
  browser ever talking to the vendor.

WHAT THIS IS AND IS NOT
  It is a READER VIEW: the page's real words, headings, lists and images,
  inert. It is not a browser. Scripts do not run, forms do not submit,
  logins do not work, and a single-page app that renders itself in
  JavaScript will come through nearly empty — which is why the "open
  their site" link never goes away and why an empty read says so.

THE SANITISER IS THE WHOLE FILE
  We are taking HTML written by a stranger and putting it inside our
  product. Two layers, because one is a single mistake away from an XSS
  in an authenticated app:

    1. HERE: script, style, iframe, object, embed, form, link, meta and
       every on* attribute are removed. javascript:/data:/vbscript: URLs
       are dropped. This runs before the markup ever leaves the server.
    2. THERE: the client renders it in <iframe sandbox srcdoc> with NO
       allow-scripts and NO allow-same-origin, so even markup that got
       past layer one executes nothing and can reach nothing.

  Belt and braces on purpose. Layer 2 alone would be sound in a current
  browser, and layer 1 alone would be sound if the sanitiser is perfect.
  Sanitisers are not perfect.

  Images are kept but their src is rewritten to absolute, and the whole
  frame is loaded with a referrer policy that stops the vendor learning
  which practitioner is looking. Nothing is proxied: we are not becoming
  a CDN for somebody else's photographs.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import httpx

from reference_analyzer import guard_url, _fetch_capped

logger = logging.getLogger("site_reader")

_TIMEOUT = 8.0
# A reader view is a page of words. Past this it is a document dump, and
# the browser has to lay all of it out inside a dialog.
_MAX_CHARS = 220_000

# Elements that execute, navigate, submit, or fetch. `link` and `meta`
# go too: a stylesheet link is a request to their server from our page,
# and a meta refresh is a navigation.
_KILL_TAGS = ("script", "style", "iframe", "object", "embed", "applet",
              "form", "input", "button", "select", "textarea", "link",
              "meta", "base", "noscript", "svg", "canvas", "audio", "video")

_KILL_BLOCK_RE = re.compile(
    r"<(%s)\b[^>]*>.*?</\1\s*>" % "|".join(_KILL_TAGS), re.I | re.S)
_KILL_SELF_RE = re.compile(
    r"<(%s)\b[^>]*/?>" % "|".join(_KILL_TAGS), re.I)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# Any on* handler, quoted or bare.
_ON_ATTR_RE = re.compile(
    r"""\son[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", re.I)
_STYLE_ATTR_RE = re.compile(
    r"""\sstyle\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", re.I)
_DANGEROUS_URL_RE = re.compile(
    r"""\s(href|src|srcset|action|formaction|data|poster)\s*=\s*"""
    r"""(?:"\s*(?:javascript|data|vbscript|file):[^"]*"|"""
    r"""'\s*(?:javascript|data|vbscript|file):[^']*')""", re.I)
_HREF_RE = re.compile(r"""(\s(?:href|src))\s*=\s*(["'])([^"']*)\2""", re.I)
_SRCSET_RE = re.compile(r"""\ssrcset\s*=\s*(["'])([^"']*)\1""", re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _absolutise(html_doc: str, base_url: str) -> str:
    """Make every remaining href/src absolute against the page it came
    from, so images still resolve and links still point somewhere real
    once the markup is detached from its origin."""
    def _fix(m: re.Match) -> str:
        attr, quote, val = m.group(1), m.group(2), m.group(3).strip()
        if not val or val.startswith(("#", "mailto:", "tel:")):
            return m.group(0)
        try:
            return f'{attr}={quote}{urljoin(base_url, val)}{quote}'
        except Exception:
            return m.group(0)
    out = _HREF_RE.sub(_fix, html_doc)
    # srcset is a comma-separated list; a half-rewritten one renders
    # nothing, so it is simpler and safer to drop it and let src carry
    # the image.
    return _SRCSET_RE.sub(" ", out)


def sanitize(html_doc: str, base_url: str) -> str:
    """Strip everything that can execute, submit, or fetch on its own.

    Order matters: paired blocks first (so a <script>…</script> body goes
    with its tags rather than being left as loose text), then self-closing
    and unpaired forms of the same tags, then attributes.
    """
    out = _COMMENT_RE.sub(" ", html_doc)
    body = _BODY_RE.search(out)
    if body:
        out = body.group(1)

    # The block killer removes each element WITH ITS BODY, which is the
    # part nothing else in this chain does — the final escape pass below
    # neutralises tags but would leave a script's source sitting in the
    # page as visible text.
    #
    # Run twice as cheap insurance against a leftover unpaired tag after
    # the first sweep. Measured honestly: no payload was found that gets
    # past one pass AND past the escape below, so this is redundancy
    # rather than a specific fix. Kept because it costs a scan of a
    # string we already hold, on markup a stranger wrote.
    for _ in range(2):
        out = _KILL_BLOCK_RE.sub(" ", out)
    out = _KILL_SELF_RE.sub(" ", out)

    out = _ON_ATTR_RE.sub(" ", out)
    out = _STYLE_ATTR_RE.sub(" ", out)
    out = _DANGEROUS_URL_RE.sub(" ", out)
    out = _absolutise(out, base_url)

    # Anything still claiming to be a script tag after all that is a
    # parser trick, not content.
    out = re.sub(r"</?(script|iframe|object|embed|form)\b", "&lt;", out, flags=re.I)
    return out[:_MAX_CHARS]


def _looks_empty(sanitised: str) -> bool:
    """A JavaScript-rendered app comes through as a shell. Saying "this
    page needs a real browser" is a true answer; showing a blank white
    box and letting somebody conclude the vendor has no website is not."""
    text = re.sub(r"\s+", " ", _TAG_RE.sub(" ", sanitised)).strip()
    return len(text) < 200


def read(url: str) -> Dict[str, Any]:
    """Fetch and sanitise one page for in-app display. Never raises."""
    raw = (url or "").strip()
    if raw and "//" not in raw:
        raw = "https://" + raw

    out: Dict[str, Any] = {"url": raw, "ok": False}
    err = guard_url(raw)
    if err:
        out["error"] = err
        return out

    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
            final_url, body = _fetch_capped(client, raw, want="html")
    except ValueError as e:
        out["error"] = str(e)
        return out
    except Exception as e:
        out["error"] = f"could not reach the site ({type(e).__name__})"
        return out

    title = ""
    m = _TITLE_RE.search(body)
    if m:
        title = re.sub(r"\s+", " ", _TAG_RE.sub(" ", m.group(1))).strip()[:160]

    cleaned = sanitize(body, final_url)
    return {
        "ok": True,
        "url": raw,
        "final_url": final_url,
        "title": title,
        "html": cleaned,
        # The client shows the "open the real site" route more prominently
        # when this is true, rather than pretending the read worked.
        "looks_empty": _looks_empty(cleaned),
        "truncated": len(cleaned) >= _MAX_CHARS,
    }
