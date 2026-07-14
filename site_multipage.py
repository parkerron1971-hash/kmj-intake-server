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
    return f"/public/site/{slug}"


def build_page_nav(slug: str, current: str) -> Dict[str, Any]:
    """Nav data for the header: one entry per page with an absolute href
    (from the /public/site/{slug} base) and an active flag for `current`."""
    base = public_base(slug)
    pages: List[Dict[str, Any]] = []
    for pid in studio_page_types.default_page_set():
        pt = studio_page_types.get_page_type(pid) or {}
        href = base if pid == "home" else f"{base}/{pid}"
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
