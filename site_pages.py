# site_pages.py
# ─────────────────────────────────────────────────────────────────────
# PAGES THAT MATCH (2026-10-01, the concept-layer plan, step 6).
#
# Two problems, one module:
#
# 1. A builder_v2 home page is one generous document, but a multi-page
#    site's About / Services / Contact were rendered from module
#    templates with fixed copy ("Ways to work together") and a different
#    design. A visitor clicking "About" left the site they were on.
#    slice_pages() cuts those pages out of the builder's own home
#    document instead: the same head, header, footer and scripts, with
#    the sections that belong to each page. Free (no model call), and it
#    stays current, because it runs from the served home every time the
#    home is refreshed.
#
#    Sliced pages are deliberately STILL: the builder's reveal gating
#    (`.js .reveal{opacity:0}`) is switched off on them, so a script that
#    expects an element living only on the home page can never leave a
#    section invisible.
#
# 2. Kevin's ruling: a WORLD concept lives on ONE OFFER PAGE by default
#    (a course, a cohort, a launch). offer_path() names that page from the
#    blueprint's concept sheet; offer_line() tells the home page's author
#    where to link it; builder_v2 builds the page itself.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("site_pages")

SECONDARY = ("about", "services", "contact")
PAGE_NAMES = {"about": "About", "services": "Services", "contact": "Contact",
              "offer": "Offer"}

# Paths the platform already serves; an offer page never takes one.
RESERVED_PATHS = {"", "about", "services", "contact", "book", "store", "events",
                  "give", "news", "thank-you", "start", "public", "data", "sites",
                  "robots.txt", "sitemap.xml", "favicon.ico", "api", "admin"}

_PAGE_HINTS = {
    "about": re.compile(r"about|story|team|chairs?|founder|meet|bio|philosoph|"
                        r"values|testimon|review|proof|press|people|professor|"
                        r"mission|who-we|our-?story", re.IGNORECASE),
    "services": re.compile(r"service|offering|price|pricing|menu|board|work|"
                           r"portfolio|gallery|package|class|process|how|faq|"
                           r"tuition|curriculum|program|course|rates|treatment",
                           re.IGNORECASE),
    "contact": re.compile(r"contact|book|visit|find|location|hours|form|reach|"
                          r"map|inquir|enquir|get-in-touch", re.IGNORECASE),
}

_SECTION_OPEN_RE = re.compile(r"<section\b[^>]*>", re.IGNORECASE)
_SECTION_TAG_RE = re.compile(r"</?section\b", re.IGNORECASE)


def is_builder_page(html: str) -> bool:
    """A page authored by builder_v2 carries its override stamps."""
    return bool(html) and 'data-override-target="v2/' in html


def top_sections(html: str) -> List[Tuple[int, int]]:
    """(start, end) of every top-level <section> element, nesting-aware."""
    spans: List[Tuple[int, int]] = []
    pos = 0
    while True:
        m = _SECTION_OPEN_RE.search(html, pos)
        if not m:
            break
        depth, cur = 1, m.end()
        while depth and cur < len(html):
            n = _SECTION_TAG_RE.search(html, cur)
            if not n:
                cur = len(html)
                break
            depth += -1 if html[n.start() + 1] == "/" else 1
            cur = n.end()
            if depth == 0:
                close = html.find(">", cur)
                cur = close + 1 if close >= 0 else cur
        spans.append((m.start(), cur))
        pos = cur
    return spans


def _section_pages(section: str) -> List[str]:
    """Which secondary pages a section belongs to: the builder's own
    data-sx-page tag when present, else the section's id, classes and
    first heading read against plain keyword lists."""
    open_tag = _SECTION_OPEN_RE.match(section).group(0)
    tag = re.search(r'data-sx-page\s*=\s*["\']([^"\']+)', open_tag)
    if tag:
        return [p for p in re.split(r"[\s,]+", tag.group(1).lower()) if p in SECONDARY]
    ident = " ".join(re.findall(r'(?:id|class)\s*=\s*["\']([^"\']+)', open_tag))
    head = re.search(r"<h[1-3]\b[^>]*>(.*?)</h[1-3]>", section, re.IGNORECASE | re.DOTALL)
    heading = re.sub(r"<[^>]+>", " ", head.group(1)) if head else ""
    if re.search(r"\bhero\b", ident, re.IGNORECASE):
        return []
    has_form = bool(re.search(r"<form\b", section, re.IGNORECASE))
    pages = [p for p, rx in _PAGE_HINTS.items() if rx.search(ident)]
    if not pages:
        pages = [p for p, rx in _PAGE_HINTS.items() if rx.search(heading)]
    if has_form and "contact" not in pages:
        pages.append("contact")
    return pages


def _ids(html: str) -> List[str]:
    return re.findall(r'\bid\s*=\s*["\']([^"\']+)["\']', html)


def _still(html: str) -> str:
    """Switch off the reveal gating so nothing waits on a script."""
    out = re.sub(r"document\.documentElement\.className\s*\+=\s*['\"]\s*js['\"]\s*;?", "", html)
    out = re.sub(r"document\.documentElement\.classList\.add\(\s*['\"]js['\"]\s*\)\s*;?", "", out)
    return out


def slice_pages(home_html: str, business_name: str = "") -> Dict[str, str]:
    """{about, services, contact: html} cut from a builder home page.
    A page with no section of its own is left out (the anchors that would
    have pointed at it point home). {} when the home has no <section>s."""
    try:
        spans = top_sections(home_html or "")
        if len(spans) < 2:
            return {}
        first, last = spans[0][0], spans[-1][1]
        head_part, tail_part = home_html[:first], home_html[last:]
        owner: Dict[str, str] = {}                 # element id → page it lives on
        assigned: List[Tuple[Tuple[int, int], List[str]]] = []
        for a, z in spans:
            pages = _section_pages(home_html[a:z])
            assigned.append(((a, z), pages))
            for i in _ids(home_html[a:z]):
                owner.setdefault(i, pages[0] if pages else "home")
        out: Dict[str, str] = {}
        for page in SECONDARY:
            kept = [home_html[a:z] for (a, z), pages in assigned if page in pages]
            if not kept:
                continue
            body = "\n".join(kept)
            if not re.search(r"<h1\b", body, re.IGNORECASE):
                title = PAGE_NAMES[page] + (f" · {business_name}" if business_name else "")
                body = ('<h1 class="sx-page-title" style="position:absolute;width:1px;'
                        'height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap">'
                        + title + "</h1>\n" + body)
            doc = _still(head_part + body + tail_part)
            here = set(_ids(doc))

            def _href(m: re.Match) -> str:
                target = m.group(2)
                if target in here or not target:
                    return m.group(0)
                lives = owner.get(target, "home")
                dest = "/" if lives in ("home", page) else f"/{lives}"
                return f'{m.group(1)}{dest}#{target}{m.group(3)}'
            doc = re.sub(r'(href\s*=\s*["\'])#([A-Za-z][\w:.-]*)(["\'])', _href, doc)
            name = PAGE_NAMES[page]
            doc = re.sub(r"<title>(.*?)</title>",
                         lambda m: f"<title>{name} · {m.group(1).strip()}</title>",
                         doc, count=1, flags=re.IGNORECASE | re.DOTALL)
            out[page] = doc
        return out
    except Exception as e:
        logger.warning(f"[pages] slice failed (module pages instead): {e}")
        return {}


# ─── the offer page (World on one offer page) ────────────────────────

def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:48].strip("-")


def offer_name(sheet: Dict[str, str]) -> str:
    """The offer's name from the sheet's SCOPE line ('offer (Saturday
    Shave Club)', 'offer: the six-week course'), or ''."""
    raw = str((sheet or {}).get("scope_raw") or (sheet or {}).get("scope_line") or "")
    m = re.search(r"offer\b[^A-Za-z0-9]*(?:page\b)?[^A-Za-z0-9]*(?:for\b)?\s*[(:\-—–]?\s*(.+)",
                  raw, re.IGNORECASE)
    name = (m.group(1) if m else "").strip(" ()[].:-—–\"'“”")
    return name[:80]


def offer_path(sheet: Dict[str, str]) -> str:
    """The offer page's public path: '/' + a slug of the offer's name, or
    '/offer'. Never a path the platform already serves."""
    slug = _slug(offer_name(sheet))
    if not slug or slug in RESERVED_PATHS:
        slug = f"offer-{slug}" if slug else "offer"
    return "/" + slug


def offer_line(path: str, name: str = "") -> str:
    """The home page author's instruction, for its REAL DATA block."""
    what = f" for {name}" if name else ""
    return ("THE OFFER PAGE (built separately; this page links to it): the offer "
            f"page{what} lives at {path}. Link it from the navigation and from the "
            f"offer's own moment on this page with href=\"{path}\".")


def check_offer_link(html: str, path: str) -> List[str]:
    """Soft: the home page must reach its offer page."""
    if not path:
        return []
    if re.search(r'href\s*=\s*["\']' + re.escape(path) + r'(?:[#?"\'])', html or ""):
        return []
    return [f"OFFER LINK MISSING: the offer page at {path} is not linked. Add "
            f"href=\"{path}\" in the navigation and on the offer's own moment."]
