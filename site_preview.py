"""
site_preview.py — read a vendor's site and answer the question the
practitioner actually has (2026-08-21).

WHY THIS AND NOT AN EMBEDDED BROWSER
  A practitioner clicking a sourcing result does not want to READ a
  supplier's homepage. They want to know four things: is this a real
  trade supplier, do they take a purchase order, what is their minimum,
  and how do I reach a human. So this fetches the page on the server and
  returns those answers, rather than putting a website inside the app.

  It is also the only version that works. An iframe of an arbitrary
  vendor is refused by most commercial sites (X-Frame-Options /
  frame-ancestors), and the alternative — streaming a real browser from
  our own infrastructure — means owning a browser farm and routing every
  page a practitioner looks at through us. For "does this vendor take
  POs", that is an absurd amount of machinery.

WHAT IT IS HONEST ABOUT
  Everything here is WHAT THEIR SITE SAYS, on the day it was read. It is
  not a fact about the vendor and the surface must not present it as one.
  A site that says "wholesale enquiries welcome" has said exactly that
  and nothing more — it has not agreed to sell to anybody. So every
  finding carries the phrase it was found by and the page it came from,
  and `read_at` is part of the payload rather than decoration.

WHY THE EXTRACTION IS DETERMINISTIC
  No model call. A regex pass over the markup is free, instant, and
  cannot invent a minimum order that was never on the page — which is the
  failure that matters here, because the number would be used to plan a
  purchase. A model read is a fine thing to offer as a deliberate,
  charged action later; it is the wrong default for a panel that opens
  when somebody clicks a row.

SSRF: THE GUARD IS BORROWED ON PURPOSE
  A vendor's "website" is a field a user typed. Fetching it server-side
  is a server-side request forgery hole unless every hop is checked —
  `http://169.254.169.254/` is a cloud metadata endpoint, and
  `http://localhost:5432` is a database.

  reference_analyzer already solved this properly: scheme and port
  allow-lists, raw-IP hosts refused, DNS resolved and checked against
  private/loopback/link-local/reserved ranges, EVERY redirect hop
  re-guarded, content-type enforced and the body read capped. Importing
  its private `_fetch_capped` is slightly impolite. Writing a second
  SSRF guard would be considerably worse than impolite, and the second
  one is always the one that is wrong.
"""
from __future__ import annotations

import html as _html
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import httpx

from reference_analyzer import guard_url, _fetch_capped

logger = logging.getLogger("site_preview")

_TIMEOUT = 8.0
_HIT_TTL = 6 * 3600.0
_CACHE_MAX = 500
_CACHE: Dict[str, Any] = {}
_CACHE_AT: Dict[str, float] = {}

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.I | re.S)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META_DESC_RE = re.compile(
    r"""<meta[^>]+name\s*=\s*["']description["'][^>]*content\s*=\s*["']([^"']*)["']""",
    re.I)
_META_DESC_ALT_RE = re.compile(
    r"""<meta[^>]+content\s*=\s*["']([^"']*)["'][^>]*name\s*=\s*["']description["']""",
    re.I)
_MAILTO_RE = re.compile(r"""mailto:([^"'?>\s]+)""", re.I)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_TEL_RE = re.compile(r"""tel:([+0-9()\-.\s]{7,})""", re.I)
_ANCHOR_RE = re.compile(
    r"""<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)


# ─── What we look for, and what finding it actually means ────────────
#
# Phrased as signals rather than a vendor taxonomy: the question is never
# "what kind of company is this", it is "is there a trade route in here".
# Each entry carries the sentence the UI shows, so a finding is always
# reported as something their page said.

_SIGNALS: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("wholesale", "Mentions wholesale or trade sales",
     ("wholesale", "trade account", "trade programme", "trade program",
      "trade pricing", "reseller", "distributor", "b2b", "bulk order",
      "trade enquiries", "trade inquiries")),
    ("purchase_order", "Mentions purchase orders",
     ("purchase order", "purchase orders", "po number", "p.o. number",
      "submit a po", "we accept po")),
    ("terms", "Mentions payment terms",
     ("net 30", "net 60", "net 15", "payment terms", "credit terms",
      "credit account", "invoice terms")),
    ("minimum", "Mentions a minimum order",
     ("minimum order", "minimum purchase", "moq", "order minimum",
      "minimum quantity")),
    ("apply", "Has an account application",
     ("apply for an account", "open an account", "account application",
      "become a stockist", "become a retailer", "apply to sell",
      "wholesale application", "dealer application")),
    ("portal", "Has a trade login or ordering portal",
     ("wholesale login", "trade login", "dealer login", "b2b portal",
      "customer portal", "order portal", "stockist login")),
]

# Links worth surfacing: the page that answers the question directly.
_LINK_HINTS = ("wholesale", "trade", "b2b", "reseller", "dealer", "stockist",
               "bulk", "contact", "account", "order")

# A homepage is a marketing page. Measured on the first real vendor a
# practitioner saved here: annieinc.com's homepage carried NO ordering
# signals at all, while /pages/wholesale carried both "wholesale" and an
# account application. Reading only the front page would have reported
# "nothing here" about a supplier that plainly has a trade route — an
# empty state that lies, about the exact question being asked.
#
# So: follow at most _MAX_HOPS more pages. Links the site itself offers
# come first, because a link is evidence the page exists; the fixed list
# is the fallback for sites whose nav is built in JavaScript.
_MAX_HOPS = 2
_TRADE_PATHS = (
    "/pages/wholesale", "/wholesale", "/pages/trade", "/trade",
    "/pages/wholesale-application", "/pages/become-a-stockist",
    "/b2b", "/trade-accounts", "/pages/contact", "/contact",
)


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    at = _CACHE_AT.get(key)
    if at is None or (time.time() - at) > _HIT_TTL:
        _CACHE.pop(key, None)
        _CACHE_AT.pop(key, None)
        return None
    return _CACHE.get(key)


def _cache_put(key: str, value: Dict[str, Any]) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        for k, _ in sorted(_CACHE_AT.items(), key=lambda kv: kv[1])[: _CACHE_MAX // 4]:
            _CACHE.pop(k, None)
            _CACHE_AT.pop(k, None)
    _CACHE[key] = value
    _CACHE_AT[key] = time.time()


def _text_of(html_doc: str) -> str:
    body = _SCRIPT_RE.sub(" ", html_doc)
    body = _TAG_RE.sub(" ", body)
    return re.sub(r"\s+", " ", _html.unescape(body))


def _first(pattern: re.Pattern, s: str) -> str:
    m = pattern.search(s)
    return _html.unescape((m.group(1) if m else "")).strip()


def extract(html_doc: str, base_url: str) -> Dict[str, Any]:
    """Pull the answers out of the markup. Pure — no network, no clock."""
    text = _text_of(html_doc)
    low = text.lower()

    title = re.sub(r"\s+", " ", _first(_TITLE_RE, html_doc))[:160]
    desc = (_first(_META_DESC_RE, html_doc)
            or _first(_META_DESC_ALT_RE, html_doc))[:300]

    # Addresses: mailto links first — they are deliberate — then anything
    # written in the page body.
    emails: List[str] = []
    for m in _MAILTO_RE.findall(html_doc):
        e = _html.unescape(m).strip().lower()
        if _EMAIL_RE.fullmatch(e) and e not in emails:
            emails.append(e)
    for e in _EMAIL_RE.findall(text):
        e = e.strip().lower()
        # Image filenames and tracking pixels turn up here constantly.
        if e.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
            continue
        if e not in emails:
            emails.append(e)

    phones = []
    for p in _TEL_RE.findall(html_doc):
        p = re.sub(r"\s+", " ", p).strip()
        if p and p not in phones:
            phones.append(p)

    found: List[Dict[str, str]] = []
    for key, label, needles in _SIGNALS:
        for n in needles:
            if n in low:
                # The phrase is carried so the UI can say WHY it thinks
                # so, instead of asserting a capability.
                found.append({"key": key, "label": label, "phrase": n})
                break

    links: List[Dict[str, str]] = []
    seen_href = set()
    for href, inner in _ANCHOR_RE.findall(html_doc):
        label = re.sub(r"\s+", " ", _html.unescape(_TAG_RE.sub(" ", inner))).strip()
        blob = f"{href} {label}".lower()
        if not any(h in blob for h in _LINK_HINTS):
            continue
        try:
            full = urljoin(base_url, _html.unescape(href).strip())
        except Exception:
            continue
        if not full.lower().startswith(("http://", "https://")):
            continue
        key = full.split("#")[0].rstrip("/").lower()
        if key in seen_href:
            continue
        seen_href.add(key)
        links.append({"url": full, "label": (label or full)[:80]})
        if len(links) >= 8:
            break

    return {
        "title": title,
        "description": desc,
        "emails": emails[:5],
        "phones": phones[:3],
        "signals": found,
        "links": links,
    }


def preview(url: str, *, use_cache: bool = True) -> Dict[str, Any]:
    """Fetch a vendor's page and summarise what it says about ordering.

    Never raises. A site that is down, slow, or refuses us is reported as
    exactly that — "we could not read it" is a true answer, and an
    unreadable site is not the same thing as a vendor with no trade route.
    """
    raw = (url or "").strip()
    if raw and "//" not in raw:
        raw = "https://" + raw
    if use_cache:
        hit = _cache_get(raw.lower())
        if hit is not None:
            return {**hit, "cached": True}

    out: Dict[str, Any] = {"url": raw, "ok": False, "read_at": time.time()}

    err = guard_url(raw)
    if err:
        # Refusals are not cached: a hostname that failed to resolve this
        # minute may be fine in ten, and a blocked one is cheap to re-check.
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

    first = extract(body, final_url)
    out.update({"ok": True, "final_url": final_url, **first})
    for sig in out["signals"]:
        sig["source"] = final_url

    # Only go further when the front page did not answer the question.
    # A homepage that already mentions wholesale AND an application has
    # told us what we came for.
    if len({s["key"] for s in out["signals"]}) < 2:
        _follow(final_url, first, out)

    _cache_put(raw.lower(), out)
    return out


def _candidate_pages(base_url: str, first: Dict[str, Any]) -> List[str]:
    """Pages worth a second look, best first."""
    seen, cands = set(), []
    for link in first.get("links", []):
        u = link.get("url") or ""
        blob = f"{u} {link.get('label','')}".lower()
        # Contact pages rarely carry trade terms; the trade words do.
        if not any(h in blob for h in ("wholesale", "trade", "b2b", "reseller",
                                       "dealer", "stockist")):
            continue
        # Never wander off the vendor's own site.
        if urlsplit(u).netloc.lower() != urlsplit(base_url).netloc.lower():
            continue
        k = u.split("#")[0].rstrip("/").lower()
        if k not in seen:
            seen.add(k)
            cands.append(u)
    root = f"{urlsplit(base_url).scheme}://{urlsplit(base_url).netloc}"
    for path in _TRADE_PATHS:
        u = root + path
        k = u.rstrip("/").lower()
        if k not in seen:
            seen.add(k)
            cands.append(u)
    return cands


def _follow(base_url: str, first: Dict[str, Any], out: Dict[str, Any]) -> None:
    """Read up to _MAX_HOPS more of the vendor's own pages and merge what
    they say. Every hop goes back through the same guarded fetch, so a
    redirect off the site is refused exactly as it is on the first one."""
    have = {s["key"] for s in out["signals"]}
    read: List[str] = []
    hops = 0
    for url in _candidate_pages(base_url, first):
        if hops >= _MAX_HOPS:
            break
        if guard_url(url):
            continue
        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
                final, body = _fetch_capped(client, url, want="html")
        except Exception:
            # A 404 here is the normal case — the fixed list is guesses.
            continue
        hops += 1
        read.append(final)
        more = extract(body, final)
        for sig in more.get("signals", []):
            if sig["key"] not in have:
                have.add(sig["key"])
                out["signals"].append({**sig, "source": final})
        # An address on the wholesale page is the one you want.
        for e in more.get("emails", []):
            if e not in out["emails"]:
                out["emails"].append(e)
        for p in more.get("phones", []):
            if p not in out["phones"]:
                out["phones"].append(p)
    if read:
        out["also_read"] = read


def summarise(found: List[Dict[str, str]]) -> str:
    """One plain sentence for the panel header, or an honest blank.

    Deliberately says what the PAGE mentions. "They take purchase orders"
    would be a claim about the vendor; "their site mentions purchase
    orders" is a fact about the page, and only one of those is true.
    """
    if not found:
        return ""
    labels = []
    for key in ("wholesale", "purchase_order", "terms", "minimum", "apply", "portal"):
        for f in found:
            if f["key"] == key:
                labels.append({
                    "wholesale": "wholesale or trade sales",
                    "purchase_order": "purchase orders",
                    "terms": "payment terms",
                    "minimum": "a minimum order",
                    "apply": "an account application",
                    "portal": "a trade login",
                }[key])
                break
    if not labels:
        return ""
    if len(labels) == 1:
        return f"Their site mentions {labels[0]}."
    return ("Their site mentions " + ", ".join(labels[:-1])
            + f" and {labels[-1]}.")
