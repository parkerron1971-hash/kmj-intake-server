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
               contact_footer, store, showcase, header, statband,
               interstitial, faq, process)
from ._base import (page_shell, build_page_meta, rule_break_treatment,
                    diamond_field, is_brut)

_TAG_RE = _re.compile(r"<[^>]+>")


def _mark_silence_target(body_parts: List[str], rendered_ids: List[str]) -> None:
    """Arc 6 hard_silence rule-break: the EMPTIEST rendered section (least
    visible text; hero and contact excluded — the break never lands on the
    entry or the exit) gets class sx-rb-target so the doubled-whitespace /
    no-ornament CSS (base_css) has a single deterministic home. In place."""
    best_i, best_len = -1, None
    for i, (mid, html) in enumerate(zip(rendered_ids, body_parts)):
        # Interstitials (Site Arc 10 ceremony seams) are chrome-like:
        # they are near-empty by design and never carry the rule-break.
        if mid in ("hero", "contact", "interstitial"):
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

# Quality-floor arc 7 — TRUE RHYTHM: sections eligible to carry the deep
# AUTHORITY band (the old navy chapter-break). Hero and contact never (the
# entry and the exit keep their own grounds); the accent bands (cta/
# statband) are already the gold punctuation; store keeps product photos
# on their native ground.
_AUTHORITY_CANDIDATES = ("about", "offerings", "gallery", "testimonials",
                         "showcase")


def _mark_authority_band(body_parts: List[str], rendered_ids: List[str],
                         ctx: Dict[str, Any]) -> None:
    """Mark ONE mid-page section as the authority band (class
    sxm-authority; CSS in _base._QUALITY_CSS re-inks everything inside
    via custom-property overrides). The pick is deterministic: the middle
    eligible section (≈ the 3rd/4th section of a typical page). A section
    already carrying the hard_silence rule-break target is skipped — the
    silence move owns that section's ground. Floating diamonds ride along
    (skipped for the brut identity and when there are none). In place."""
    idxs = [i for i, mid in enumerate(rendered_ids)
            if mid in _AUTHORITY_CANDIDATES
            and "sx-rb-target" not in body_parts[i]]
    if not idxs:
        return
    target = idxs[len(idxs) // 2]
    part = body_parts[target]
    marked, n = _re.subn(r'(<section\b[^>]*class=")', r"\1sxm-authority ",
                         part, count=1)
    if not n:  # a section tag without a class attribute
        marked, n = _re.subn(r"<section\b", '<section class="sxm-authority"',
                             part, count=1)
    if not n:
        return
    diamonds = diamond_field(ctx.get("dna") or {}, 2)
    if diamonds:
        marked = _re.sub(r"(<section\b[^>]*>)",
                         lambda m: m.group(1) + diamonds, marked, count=1)
    body_parts[target] = marked


# Site Arc 10 "wow" — sections that carry a GHOST CHAPTER NUMERAL (the
# sub-perceptual depth layer from exemplars e5/e6: huge display digits
# at ~5% ink in a section corner). Hero and contact never (entry/exit);
# interstitials are the seams between chapters, not chapters.
_GHOST_NUMERAL_IDS = ("about", "offerings", "gallery", "testimonials",
                      "showcase", "store")


def _mark_after_seam(body_parts: List[str], rendered_ids: List[str]) -> None:
    """Site Arc 11b — dead-band fix: a section that directly follows an
    interstitial gets class sxm-after-seam (base CSS trims its top
    padding ~45%) so the seam's own breathing room and the section pad
    don't stack into a void. Interstitials never abut each other (the
    ceremony pass inserts at distinct spec gaps), so only section
    modules ever follow a seam. In place."""
    for i in range(1, len(body_parts)):
        if rendered_ids[i - 1] != "interstitial" or rendered_ids[i] == "interstitial":
            continue
        part = body_parts[i]
        marked, n = _re.subn(r'(<section\b[^>]*class=")', r"\1sxm-after-seam ",
                             part, count=1)
        if not n:  # a section tag without a class attribute
            marked, n = _re.subn(r"<section\b",
                                 '<section class="sxm-after-seam"',
                                 part, count=1)
        if n:
            body_parts[i] = marked


def _inject_ghost_numerals(body_parts: List[str], rendered_ids: List[str],
                           ctx: Dict[str, Any]) -> None:
    """Stamp each major section with its chapter numeral (01, 02, …) —
    shell-owned ornament (CSS in _base._WOW_CSS), injected right after
    the section's opening tag; corners alternate. Skipped for the brut
    identity (their language is color-blocks, not ornament) and when
    fewer than two chapters exist (a lone '01' is noise). Site Arc 11b:
    a section directly after a STATEMENT interstitial skips its numeral
    (the title-card bar already provides the pause — a ghost digit
    floating beside it read as debris on the live page); numbering
    stays contiguous across the skip. In place."""
    if is_brut(ctx.get("dna") or {}):
        return
    idxs = [i for i, mid in enumerate(rendered_ids)
            if mid in _GHOST_NUMERAL_IDS
            and not (i > 0 and rendered_ids[i - 1] == "interstitial"
                     and "sxm-int-statement" in body_parts[i - 1])]
    if len(idxs) < 2:
        return
    for n, i in enumerate(idxs, start=1):
        part = body_parts[i]
        side = " sxm-gn-left" if n % 2 == 0 else ""
        numeral = (f'<span class="sxm-ghostnum{side}" '
                   f'aria-hidden="true">{n:02d}</span>')
        marked, cnt = _re.subn(r'(<section\b[^>]*class=")',
                               r"\1sxm-ghostnum-host ", part, count=1)
        if not cnt:  # a section tag without a class attribute
            marked, cnt = _re.subn(
                r"<section\b", '<section class="sxm-ghostnum-host"',
                part, count=1)
        if not cnt:
            continue
        marked = _re.sub(r"(<section\b[^>]*>)",
                         lambda m: m.group(1) + numeral, marked, count=1)
        body_parts[i] = marked


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
        # statement_1..3 = the accent boards (Kevin's ruling 2026-07-22):
        # short craft-manifesto lines mounted between the photos.
        "fields": ("eyebrow", "headline",
                   "statement_1", "statement_2", "statement_3"),
    },
    "faq": {
        "variants": faq.VARIANTS,
        "render": faq.render,
        "fields": ("eyebrow", "headline"),
    },
    "process": {
        "variants": process.VARIANTS,
        "render": process.render,
        "fields": ("eyebrow", "headline", "intro"),
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
    # Site Arc 10 — the ceremony seams. INTERNAL: never offered to the
    # composer LLM (site_composer._module_menu skips internal entries);
    # placed only by the deterministic ceremony pass. May appear more
    # than once per page (sanitize_spec exempts it from module dedupe).
    "interstitial": {
        "variants": interstitial.VARIANTS,
        "render": interstitial.render,
        "fields": ("text", "words"),
        "internal": True,
    },
}


def render_page(sections: List[Dict[str, Any]], ctx: Dict[str, Any],
                title: str, fragment_markers: bool = False) -> str:
    """sections = [{module, variant, content}] → full HTML document.
    Unknown modules/variants soft-fail to defaults; CSS is emitted once
    per module id regardless of how often it appears.

    The header/nav is STRUCTURAL chrome (Arc 1 'Wear the Brand'): it is
    not in MODULES (never LLM-choosable) and always renders first, built
    from the sections that actually produced HTML.

    fragment_markers (Arc 8 "The Atelier"): wrap each rendered section
    in <!--sx:{module}:{i}--> … <!--/sx:{module}:{i}--> comments so the
    bespoke-section engine (atelier.py) can replace individual sections
    post-assembly. Default OFF — the emitted document is byte-identical
    to before when the atelier is disabled."""
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
        if fragment_markers:
            i = len(body_parts)
            html = f"<!--sx:{mid}:{i}-->{html}<!--/sx:{mid}:{i}-->"
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
    # Quality-floor arc 7 — the authority band lands AFTER silence marking
    # (it never claims the silence target's ground).
    _mark_authority_band(body_parts, rendered_ids, ctx)
    # Site Arc 11b — sections directly after a ceremony seam trim their
    # top padding (dead-band fix; the class never collides with the marks).
    _mark_after_seam(body_parts, rendered_ids)
    # Site Arc 10 — ghost chapter numerals land last (they read the final
    # section set; the classes they add never collide with the marks above).
    _inject_ghost_numerals(body_parts, rendered_ids, ctx)
    header_html, header_css = header.render_header(rendered_ids, ctx)
    body_parts.insert(0, header_html)
    css_parts.insert(0, header_css)
    # Phase 3: Stage-C motion tokens shaped by the authored motion
    # spec land as CSS custom properties (+ hover-mode body class via
    # design token consumers). Absent spec/tokens -> defaults that
    # match today's values, so nothing shifts.
    try:
        from design_specs import motion_css_vars
        css_parts.insert(0, motion_css_vars(ctx.get("motion_tokens"),
                                            ctx.get("motion_spec")))
    except Exception:
        pass
    # Design audit P3: the Stage-C rhythm scale finally reaches the
    # page (it was computed per compose and consumed by nothing in
    # the render path). Custom blocks space on these steps (D5).
    try:
        _rb = int((ctx.get("rhythm_scale") or {}).get("base_px") or 0)
        if _rb:
            css_parts.insert(0, (":root { --sx-rhythm-base: %dpx; "
                                 "--sx-rhythm-half: %dpx; "
                                 "--sx-rhythm-quarter: %dpx; }"
                                 % (_rb, _rb // 2, _rb // 4)))
    except Exception:
        pass
    # THE AUTHORSHIP PASS (2026-07-22, instinct arc piece 1): with the
    # whole body assembled, the model art-directs the page as ONE work —
    # a sanitized page-wide CSS layer appended LAST so the author's voice
    # wins cascade ties against the templates. Fail-open: any failure and
    # the page ships exactly as before this pass existed.
    _body_html = "\n".join(body_parts)
    try:
        import art_direction
        _ad_layer = art_direction.author_layer(
            ctx, _body_html, str(ctx.get("business_id") or ""))
        if _ad_layer:
            css_parts.append("/* — art direction (authored) — */\n" + _ad_layer)
            ctx["_art_direction_chars"] = len(_ad_layer)
    except Exception:
        pass
    return page_shell(ctx["dna"], title, _body_html, "\n".join(css_parts),
                      design=ctx.get("design"), meta=build_page_meta(ctx))
