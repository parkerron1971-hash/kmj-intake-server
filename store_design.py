"""
store_design.py — store-page design inheritance (2026-08-01).

The hosted store used to render from the brand kit alone — functional,
visually generic, and a stranger to the business's composed site. This
module resolves the SAME design DNA the site pipeline renders from, in
priority order:

  1. composed-site tokens — business_sites.site_config carries the
     compose's forensics: design_rationale_id → design_rationales.dro
     (the brain's palette/typography/whitespace decisions) and
     language {key} (Mural / Monograph / Ledger). We rebuild the DNA
     exactly the way site_composer does: build_brand_dna → apply DRO
     palette → temperature → style → owner ground (owner beats model,
     same precedence). A dark-editorial site gets a dark-editorial
     store by construction.
  2. brand kit — build_brand_dna from the business row's brand_kit
     (nested colors/font_pair shape mirrored from
     brand_engine._compose_design — the flat-fields-only read was a
     silent kit miss).
  3. tasteful neutral default — build_brand_dna's own vibe defaults.

Everything fails open: any exception in resolution returns the
brand-kit DNA (or the neutral default), never a 500 on a buyer page.

Read-only. One extra DB fetch (the DRO row) and only when the composed
site actually stored a rationale id.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import brand_dna

logger = logging.getLogger("store_design")


# ─── Vertical softening (trivial by design) ───────────────────────────
# A ministry's store must not scream "SHOP". Only the store NOUN moves;
# anything deeper belongs to the terminology arc.
_STORE_NOUNS: Dict[str, str] = {
    "ministry": "Resources",
    "nonprofit": "Resources",
    "course_creator": "Courses & Materials",
}

_CATEGORY_HEADINGS: Dict[str, str] = {
    "product": "Products",
    "course": "Courses",
    "package": "Packages",
}


def store_noun(business_type: Optional[str]) -> str:
    return _STORE_NOUNS.get((business_type or "").strip().lower(), "Store")


def category_heading(category: str, business_type: Optional[str]) -> str:
    bt = (business_type or "").strip().lower()
    if category == "package":
        # coach/coaching call every offering a Package already — a
        # "Packages" heading over packages reads fine everywhere.
        return _CATEGORY_HEADINGS["package"]
    if category == "course" and bt == "ministry":
        return "Studies & Courses"
    return _CATEGORY_HEADINGS.get(category, category.title() + "s")


# ─── Bundle-lite (mirrors brand_engine._compose_design's shape) ───────

def _bundle_lite(biz: Dict[str, Any]) -> Dict[str, Any]:
    """Brand bundle from the business row we already hold — no extra
    fetch, works offline/in tests. Reads BOTH brand-kit shapes: nested
    colors{}/font_pair{} (Brand Studio) and the legacy flat fields."""
    settings = biz.get("settings") or {}
    kit = settings.get("brand_kit") or {}
    colors = kit.get("colors") if isinstance(kit.get("colors"), dict) else {}
    font_pair = kit.get("font_pair") if isinstance(kit.get("font_pair"), dict) else {}
    design: Dict[str, Any] = {
        "primary_color": colors.get("primary") or kit.get("primary_color"),
        "secondary_color": colors.get("secondary") or kit.get("secondary_color"),
        "accent_color": colors.get("accent") or kit.get("accent_color"),
        "background_color": colors.get("background") or kit.get("background_color"),
        "text_color": colors.get("text") or kit.get("text_color"),
        "font_heading": font_pair.get("heading") or kit.get("font_heading"),
        "font_body": font_pair.get("body") or kit.get("font_body"),
        "fonts_owner_set": bool(font_pair.get("heading") or kit.get("font_heading")),
        "fonts_locked": bool(kit.get("fonts_locked")),
    }
    tone_words = kit.get("tone_words") or []
    site_prefs = settings.get("site_prefs") if isinstance(settings.get("site_prefs"), dict) else {}
    feel = [str(w).strip() for w in (site_prefs.get("feel_words") or [])
            if str(w or "").strip()]
    if isinstance(tone_words, list):
        tone_words = tone_words + feel
    else:
        tone_words = [str(tone_words)] + feel
    return {
        "design": design,
        "voice": {"tone_words": tone_words},
        "business": {"settings": settings, "type": biz.get("type")},
    }


def _color_prefs(biz: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """site_prefs.colors, with the composer's word→seed interpretation
    (so 'navy and gold' steers the store the way it steered the site)."""
    settings = biz.get("settings") or {}
    site_prefs = settings.get("site_prefs") if isinstance(settings.get("site_prefs"), dict) else {}
    prefs = site_prefs.get("colors")
    if not isinstance(prefs, dict):
        return None
    if not prefs.get("love") and prefs.get("words"):
        seeds = brand_dna.interpret_color_words(prefs["words"])
        if seeds:
            prefs = {**prefs, "love": seeds}
    return prefs


def _fetch_dro_decisions(dro_id: Any) -> Dict[str, Any]:
    if not dro_id:
        return {}
    try:
        import sb_clients
        rows = sb_clients.sb_get_as_service(
            f"/design_rationales?id=eq.{dro_id}&select=dro&limit=1") or []
        if rows:
            return dict(((rows[0].get("dro") or {}).get("decisions")) or {})
    except Exception as e:
        logger.warning(f"[store_design] DRO fetch failed (fail-open): {e}")
    return {}


def _fonts_pinned(design: Dict[str, Any], site_prefs: Dict[str, Any]) -> bool:
    """Mirror of site_composer._apply_dro_design's pin logic: a pin needs
    OWNER INTENT — kit fonts + (non-generic display OR fonts_locked), or
    the explicit type_personality='brand_fonts' choice."""
    owner_fonts = bool(design.get("fonts_owner_set"))
    if (owner_fonts and not design.get("fonts_locked")
            and brand_dna.is_generic_display(design.get("font_heading"))):
        owner_fonts = False
    tp = str(site_prefs.get("type_personality") or "").strip().lower()
    if tp == "brand_fonts" and design.get("fonts_owner_set"):
        owner_fonts = True
    return owner_fonts


def resolve(site: Optional[Dict[str, Any]],
            biz: Dict[str, Any]) -> Dict[str, Any]:
    """The store page's design context:

      dna          — the full brand_dna token set (css_variables-ready)
      language_key — the composed site's design language (or None)
      source       — 'composed_site' | 'brand_kit' | 'default'
      site_url     — the live main-site URL to link back to (or '')
      tagline      — one-liner for the header (brand kit / booking page)

    NEVER raises."""
    settings = biz.get("settings") or {}
    kit = settings.get("brand_kit") or {}
    site_prefs = settings.get("site_prefs") if isinstance(settings.get("site_prefs"), dict) else {}
    cfg = (site or {}).get("site_config")
    cfg = cfg if isinstance(cfg, dict) else {}
    composed = bool(cfg) and (site or {}).get("status") == "published"

    # ── DNA ──
    try:
        bundle = _bundle_lite(biz)
        prefs = _color_prefs(biz)
        dna = brand_dna.build_brand_dna(str(biz.get("id") or "x"), bundle,
                                        color_prefs=prefs)
        direction = (prefs or {}).get("direction")
        if direction:
            dna = brand_dna.apply_owner_ground(dna, direction)
        source = "brand_kit" if (kit or site_prefs) else "default"
        if composed:
            decisions = _fetch_dro_decisions(cfg.get("design_rationale_id"))
            if decisions:
                dna = brand_dna.apply_dro_palette(dna, decisions.get("palette"))
                dna = brand_dna.apply_dro_temperature(
                    dna, (decisions.get("palette") or {}).get("temperature"))
                tp = str(site_prefs.get("type_personality") or "").strip().lower()
                vocab_evidence = " ".join(str(v or "") for v in (
                    cfg.get("vocabulary_override"),
                    (cfg.get("build_inputs") or {}).get("vocab_id")
                    if isinstance(cfg.get("build_inputs"), dict) else "",
                ))
                dna = brand_dna.apply_dro_style(
                    dna, decisions,
                    owner_pairings=brand_dna.TYPE_PERSONALITY_PAIRINGS.get(tp),
                    fonts_pinned=_fonts_pinned(bundle["design"], site_prefs),
                    extra_direction_evidence=vocab_evidence)
                # Owner ground beats the DRO's base — same precedence as
                # site_composer.
                if direction:
                    dna = brand_dna.apply_owner_ground(dna, direction)
                source = "composed_site"
            elif cfg.get("language") or cfg.get("html_source"):
                # Composed without a stored rationale: the kit DNA is
                # what the compose itself built from — still the site's.
                source = "composed_site"
    except Exception as e:
        logger.warning(f"[store_design] DNA resolution failed (fail-open): {e}")
        dna = brand_dna.build_brand_dna(str(biz.get("id") or "x"), {
            "design": {}, "voice": {}, "business": {"settings": {}}})
        source = "default"

    # ── Language (craft accents ride the store CSS) ──
    language_key = None
    lang = cfg.get("language")
    if composed and isinstance(lang, dict):
        key = str(lang.get("key") or "").strip().lower()
        if key in ("mural", "monograph", "ledger"):
            language_key = key

    # ── Main-site link ──
    site_url = ""
    if composed:
        domain = str(cfg.get("custom_domain") or "").strip()
        if domain and cfg.get("custom_domain_status") == "verified":
            site_url = f"https://{domain}"
        elif (site or {}).get("slug"):
            site_url = f"https://{site['slug']}.mysolutionist.app"

    # ── Tagline ──
    tagline = (str(kit.get("tagline") or "").strip()
               or str(((settings.get("booking_page") or {}).get("tagline"))
                      or "").strip())

    return {"dna": dna, "language_key": language_key, "source": source,
            "site_url": site_url, "tagline": tagline}
