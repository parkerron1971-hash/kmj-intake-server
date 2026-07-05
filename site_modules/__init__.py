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

import re as _re
from typing import Any, Dict, List, Tuple

from . import (hero, about, offerings, testimonials, gallery, cta_band,
               contact_footer, store, showcase, header, statband)
from ._base import page_shell, build_page_meta, rule_break_treatment

_TAG_RE = _re.compile(r"<[^>]+>")


def _mark_silence_target(body_parts: List[str], rendered_ids: List[str]) -> None:
    """Arc 6 hard_silence rule-break: the EMPTIEST rendered section (least
    visible text; hero and contact excluded — the break never lands on the
    entry or the exit) gets class sx-rb-target so the doubled-whitespace /
    no-ornament CSS (base_css) has a single deterministic home. In place."""
    best_i, best_len = -1, None
    for i, (mid, html) in enumerate(zip(rendered_ids, body_parts)):
        if mid in ("hero", "contact"):
            continue
        text_len = len(" ".join(_TAG_RE.sub(" ", html).split()))
        if best_len is None or text_len < best_len:
            best_i, best_len = i, text_len
    if best_i < 0:
        return
    part = body_parts[best_i]
    marked, n = _re.subn(r'(<section\b[^>]*class=")', r"\1sx-rb-target ",
                         part, count=1)
    if not n:  # a section tag without a class attribute
        marked, n = _re.subn(r"<section\b", '<section class="sx-rb-target"',
                             part, count=1)
    if n:
        body_parts[best_i] = marked

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
    "statband": {
        "variants": statband.VARIANTS,
        "render": statband.render,
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
    "showcase": {
        "variants": showcase.VARIANTS,
        "render": showcase.render,
        "fields": ("eyebrow", "headline", "intro"),
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
    per module id regardless of how often it appears.

    The header/nav is STRUCTURAL chrome (Arc 1 'Wear the Brand'): it is
    not in MODULES (never LLM-choosable) and always renders first, built
    from the sections that actually produced HTML."""
    body_parts: List[str] = []
    css_parts: List[str] = []
    seen_css = set()
    rendered_ids: List[str] = []
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
        rendered_ids.append(mid)
        key = f"{mid}:{variant}"
        if css and key not in seen_css:
            seen_css.add(key)
            css_parts.append(css)
    # Arc 6 — hard_silence rule-break needs a target section; mark the
    # emptiest one BEFORE the header is prepended (indexes align with
    # rendered_ids).
    if rule_break_treatment(ctx.get("design")) == "hard_silence":
        _mark_silence_target(body_parts, rendered_ids)
    header_html, header_css = header.render_header(rendered_ids, ctx)
    body_parts.insert(0, header_html)
    css_parts.insert(0, header_css)
    return page_shell(ctx["dna"], title, "\n".join(body_parts), "\n".join(css_parts),
                      design=ctx.get("design"), meta=build_page_meta(ctx))
