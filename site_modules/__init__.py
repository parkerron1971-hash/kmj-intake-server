"""
site_modules — Arc 26 PR2 — the deterministic section module library.

The composer (site_composer.py) picks modules + variants + copy; these
renderers produce the HTML. Hand-built once, responsive by construction,
real CTAs, stable override targets, existing slot names — the LLM can
choose them but cannot break them.

Registry contract:
    MODULES[module_id] = {"variants": tuple, "render": fn, "fields": tuple}
    render(variant, content, ctx) -> (html, css); empty html = skip
    section (e.g. offerings/testimonials with no real rows — nothing is
    ever invented to fill a gap).
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from . import hero, about, offerings, testimonials, gallery, cta_band, contact_footer, store
from ._base import page_shell

MODULES: Dict[str, Dict[str, Any]] = {
    "hero": {
        "variants": hero.VARIANTS,
        "render": hero.render,
        "fields": ("eyebrow", "headline", "subheadline", "cta_label"),
    },
    "about": {
        "variants": about.VARIANTS,
        "render": about.render,
        "fields": ("eyebrow", "headline", "body", "pull_quote"),
    },
    "offerings": {
        "variants": offerings.VARIANTS,
        "render": offerings.render,
        "fields": ("eyebrow", "headline", "intro"),
    },
    "testimonials": {
        "variants": testimonials.VARIANTS,
        "render": testimonials.render,
        "fields": ("eyebrow", "headline"),
    },
    "gallery": {
        "variants": gallery.VARIANTS,
        "render": gallery.render,
        "fields": ("eyebrow", "headline"),
    },
    "cta": {
        "variants": cta_band.VARIANTS,
        "render": cta_band.render,
        "fields": ("headline", "subheadline", "cta_label"),
    },
    "store": {
        "variants": store.VARIANTS,
        "render": store.render,
        "fields": ("eyebrow", "headline", "intro", "cta_label"),
    },
    "contact": {
        "variants": contact_footer.VARIANTS,
        "render": contact_footer.render,
        "fields": ("headline", "note", "cta_label"),
    },
}


def render_page(sections: List[Dict[str, Any]], ctx: Dict[str, Any],
                title: str) -> str:
    """sections = [{module, variant, content}] → full HTML document.
    Unknown modules/variants soft-fail to defaults; CSS is emitted once
    per module id regardless of how often it appears."""
    body_parts: List[str] = []
    css_parts: List[str] = []
    seen_css = set()
    for sec in sections:
        mid = sec.get("module")
        spec = MODULES.get(mid)
        if not spec:
            continue
        variant = sec.get("variant")
        if variant not in spec["variants"]:
            variant = spec["variants"][0]
        html, css = spec["render"](variant, sec.get("content") or {}, ctx)
        if not html:
            continue
        body_parts.append(html)
        key = f"{mid}:{variant}"
        if css and key not in seen_css:
            seen_css.add(key)
            css_parts.append(css)
    return page_shell(ctx["dna"], title, "\n".join(body_parts), "\n".join(css_parts))
