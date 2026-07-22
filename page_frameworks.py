"""
page_frameworks.py — THE FRAMEWORKS ARC (2026-07-22, Kevin's go).

The composer assembled pages bottom-up, section by section — which is
how one build shipped the process story THREE times (rows + card grid +
ghost words) with no structural intent. A framework is a named page
architecture: the skeleton decision made ONCE, up front, the way a
designer picks a layout before touching type.

Style stays per-practitioner (DRO + art direction dress the skeleton);
structure stops being an accident:

  • each framework defines section ORDER, where the portrait lives,
    where the gallery sits, and the CTA budget;
  • every module id appears at most once (interstitials excepted, ≤2) —
    one representation per content type, by decree;
  • selection is a RUBRIC over real evidence (products, gallery photos,
    portrait, DRO language), not a lookup table — teach the rubric,
    not the cases.

Env: PAGE_FRAMEWORKS=off — kill switch (default on).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("page_frameworks")

# Every framework ranks all real modules; unlisted ids sort after ranked
# ones in their original relative order. `about_variant` is forced only
# when a portrait photo actually exists.
FRAMEWORKS: Dict[str, Dict[str, Any]] = {
    "portrait_consultant": {
        "label": "Portrait-led Consultant",
        "why": "a practice sold on a person — the portrait is the proof",
        "order": ["hero", "about", "offerings", "process", "testimonials",
                  "statband", "gallery", "faq", "cta", "contact"],
        "about_variant": "portrait",
    },
    "gallery_studio": {
        "label": "Gallery-first Studio",
        "why": "the work sells the work — imagery before explanation",
        "order": ["hero", "gallery", "about", "offerings", "showcase",
                  "testimonials", "process", "faq", "cta", "contact"],
        "about_variant": "portrait",
    },
    "storefront": {
        "label": "Storefront",
        "why": "products carry the page — browsing before biography",
        "order": ["hero", "store", "offerings", "about", "testimonials",
                  "gallery", "faq", "cta", "contact"],
        "about_variant": "narrative",
    },
    "editorial_monolith": {
        "label": "Editorial Monolith",
        "why": "one long-form argument — reads like an essay, not a brochure",
        "order": ["hero", "about", "process", "offerings", "testimonials",
                  "faq", "gallery", "cta", "contact"],
        "about_variant": "pull_quote",
    },
    "story_arc": {
        "label": "Story Arc",
        "why": "problem → guide → plan → call: the classic narrative spine",
        "order": ["hero", "about", "process", "offerings", "statband",
                  "testimonials", "gallery", "faq", "cta", "contact"],
        "about_variant": "narrative",
    },
}


def enabled() -> bool:
    return (os.environ.get("PAGE_FRAMEWORKS") or "on").strip().lower() != "off"


def _dro_text(dro: Optional[Dict[str, Any]]) -> str:
    d = (dro or {}).get("decisions") or (dro or {}) or {}
    bits: List[str] = []
    for path in (("typography", "display_personality"),
                 ("whitespace", "philosophy"), ("palette", "accent_strategy"),
                 ("hero_concept", "concept_statement")):
        cur: Any = d
        for k in path:
            cur = (cur or {}).get(k) if isinstance(cur, dict) else None
        if cur:
            bits.append(str(cur))
    return " ".join(bits).lower()


def select_framework(ctx: Dict[str, Any],
                     dro: Optional[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """Rubric over real evidence. Every branch states its reason."""
    products = ctx.get("products") or ctx.get("store_products") or []
    photos = ctx.get("gallery") or []
    prefs = ctx.get("site_prefs") if isinstance(ctx.get("site_prefs"), dict) else {}
    has_portrait = bool((ctx.get("intel") or {}).get("about_photo")
                        or ctx.get("about_photo")
                        or (ctx.get("brand_design") or {}).get("about_photo"))
    btype = str((ctx.get("business") or {}).get("type") or "").lower()
    text = _dro_text(dro)

    if len(products) >= 2:
        key = "storefront"
    elif len(photos) >= 4 and (prefs.get("wants_gallery") is not False):
        key = "gallery_studio"
    elif any(w in text for w in ("editorial", "literar", "essay", "monolith",
                                 "long-form", "luxur")):
        key = "editorial_monolith"
    elif has_portrait or any(w in btype for w in ("coach", "consult", "law",
                                                  "advisor", "therap")):
        key = "portrait_consultant"
    else:
        key = "story_arc"
    logger.info(f"[frameworks] selected {key} "
                f"(products={len(products)}, photos={len(photos)}, "
                f"portrait={has_portrait}, type={btype[:20]!r})")
    return key, FRAMEWORKS[key]


def apply_framework(spec: List[Dict[str, Any]], ctx: Dict[str, Any],
                    dro: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Conform the composed spec to the selected skeleton:
    dedupe → reorder → seat the portrait. Returns the spec unchanged
    when disabled or on any surprise (fail-open)."""
    if not enabled() or not isinstance(spec, list) or not spec:
        return spec
    try:
        key, fw = select_framework(ctx, dro)
        ctx["framework_key"] = key
        ctx["framework_label"] = fw["label"]

        # ONE representation per content type: first occurrence wins.
        # Interstitials are connective tissue — up to 2 survive.
        seen: Dict[str, int] = {}
        deduped: List[Dict[str, Any]] = []
        for s in spec:
            mid = str(s.get("module") or "")
            if mid == "interstitial":
                if seen.get(mid, 0) >= 2:
                    continue
                seen[mid] = seen.get(mid, 0) + 1
            elif mid in seen:
                logger.info(f"[frameworks] dropped duplicate '{mid}' section")
                continue
            else:
                seen[mid] = 1
            deduped.append(s)

        # Reorder by the framework's rank; unknown ids keep their
        # original relative position after the ranked ones. Stable sort
        # preserves interstitial adjacency within equal ranks.
        rank = {mid: i for i, mid in enumerate(fw["order"])}
        deduped.sort(key=lambda s: rank.get(str(s.get("module") or ""),
                                            len(rank) + 100))

        # Contact anchors the page; hero opens it (belt and suspenders —
        # both should already hold).
        deduped.sort(key=lambda s: 1 if s.get("module") == "contact" else 0)

        # Seat the portrait: only when a portrait photo actually exists
        # does the framework force its about variant.
        want_variant = fw.get("about_variant")
        if want_variant == "portrait":
            has_photo = bool((ctx.get("intel") or {}).get("about_photo")
                             or ctx.get("about_photo"))
            if not has_photo:
                want_variant = None
        if want_variant:
            for s in deduped:
                if s.get("module") == "about":
                    s["variant"] = want_variant
                    break
        return deduped
    except Exception as e:
        logger.warning(f"[frameworks] failed open: {type(e).__name__}: {e}")
        return spec
