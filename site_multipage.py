"""
site_multipage.py — real multi-page sites on the Module Composer.

The composer builds ONE flagship home page (all the DRO / atelier / quality-
gate machinery). This adds the secondary pages — About / Services / Contact —
as clean deterministic pages that SHARE the home's design (the same
ctx["dna"] / DRO), rendered through the exact same module renderers via
site_modules.render_page. A shared nav (page links + active state + a mobile
hamburger drawer) is threaded through ctx["page_nav"], so every page —
including the home — carries it.

ADDITIVE + FLAG-GATED: only runs when a site opts into multi-page
(site_config.site_type == "multi-page"). The flagship single-page path is
untouched; a multi-page site simply gains generated_pages{page_id: html} and
a page-aware header.

Modules self-drop when they have no real data (offerings/testimonials/faq
render '' when empty), so a thin business still gets clean secondary pages.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import site_modules
import studio_page_types

logger = logging.getLogger("site_multipage")

# Home is composed by the flagship pipeline; these are rendered here.
SECONDARY_PAGES = ("about", "services", "contact")


def is_multi_page(site_config: Optional[Dict[str, Any]]) -> bool:
    return str((site_config or {}).get("site_type") or "").strip().lower() == "multi-page"


def public_base(slug: str) -> str:
    """The INTERNAL preview base. Used by the preview rewrite in
    public_site — never for anything a visitor is sent to."""
    return f"/public/site/{slug}"


def build_page_nav(slug: str, current: str) -> Dict[str, Any]:
    """Nav data for the header: one entry per page, root-relative, with
    an active flag for `current`.

    2026-08-13 site-builder audit: these hrefs were built from the
    /public/site/{slug} preview base, so the site's OWN nav walked
    visitors onto the internal preview URL. Three things followed, all
    on the real site:

      - a practitioner on the custom domain they paid for got
        theirdomain.com/public/site/acme/about in the address bar
      - the preview path has no offline check (deliberately — it is the
        editor's own view), so taking a site down left every secondary
        page still serving to anyone with the link
      - that handler never passes page_path to _inject_canonical, so
        every secondary page declared itself canonical to the HOME page,
        telling Google the site is one page with three duplicates

    The clean routes (/about, /services, /contact) were built and already
    work on both the subdomain and custom domains; only the nav never
    moved onto them.

    Root-relative rather than absolute, so the same stored HTML stays
    correct on the subdomain today and on a custom domain added
    tomorrow, without a rebuild.
    """
    pages: List[Dict[str, Any]] = []
    for pid in studio_page_types.default_page_set():
        pt = studio_page_types.get_page_type(pid) or {}
        href = "/" if pid == "home" else f"/{pid}"
        pages.append({"id": pid, "name": pt.get("name") or pid.title(),
                      "href": href, "active": (pid == current)})
    return {"pages": pages, "current": current}


def _title_hero(page_id: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """A compact page-title hero for a secondary page (real data only)."""
    biz = ctx.get("business") or {}
    b = (ctx.get("bundle") or {}).get("business") or {}
    name = biz.get("name") or "Welcome"
    tagline = str(b.get("tagline") or "").strip()
    by_page = {
        "about":    ("About", f"The story behind {name}", tagline),
        "services": ("Services", "Ways to work together", tagline),
        "contact":  ("Contact", "Let's talk", tagline or "Reach out — we'll get back to you."),
    }
    eyebrow, headline, sub = by_page.get(page_id, (page_id.title(), name, tagline))
    # variant soft-fails to the module default if unknown — safe.
    return {"module": "hero", "variant": "statement",
            "content": {"eyebrow": eyebrow, "headline": headline,
                        "subheadline": sub, "cta_label": ""}}


def page_spec(page_id: str, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per-page section spec from the REAL module registry. Contact always
    closes the page. Empty modules self-drop."""
    hero = _title_hero(page_id, ctx)
    contact = {"module": "contact", "variant": "standard",
               "content": {"headline": "Get in touch"}}
    if page_id == "about":
        return [hero,
                {"module": "about", "variant": "narrative", "content": {"headline": "The practice"}},
                {"module": "statband", "variant": "row", "content": {}},
                {"module": "testimonials", "variant": "spotlight", "content": {}},
                {"module": "cta", "variant": "band", "content": {"headline": "Ready when you are."}},
                contact]
    if page_id == "services":
        return [hero,
                {"module": "offerings", "variant": "cards", "content": {"headline": "Ways to work together"}},
                {"module": "showcase", "variant": "grid", "content": {}},
                {"module": "faq", "variant": "ledger", "content": {"headline": "Good to know"}},
                {"module": "cta", "variant": "band", "content": {"headline": "Let's begin."}},
                contact]
    if page_id == "contact":
        return [hero,
                {"module": "faq", "variant": "ledger", "content": {"headline": "Good to know"}},
                contact]
    return [hero, contact]


def build_secondary_pages(ctx: Dict[str, Any], slug: str, title: str) -> Dict[str, str]:
    """Render About/Services/Contact sharing ctx's design. Returns
    {page_id: html}. Best-effort per page — a page that errors is skipped,
    never blocks the others or the home page."""
    out: Dict[str, str] = {}
    for pid in SECONDARY_PAGES:
        try:
            ctx["page_nav"] = build_page_nav(slug, pid)
            html = site_modules.render_page(page_spec(pid, ctx), ctx, title)
            if html and html.strip():
                out[pid] = html
        except Exception as e:
            logger.warning(f"[multipage] page '{pid}' render failed: {e}")
    return out
