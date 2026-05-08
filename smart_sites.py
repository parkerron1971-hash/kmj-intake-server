"""smart_sites.py — Pass 3: Smart Sites v1.

Structured render of public site pages. Reads the canonical brand bundle
from brand_engine.get_bundle() + a structured site_config from
business_sites.site_config and composes HTML on every visit.

Architecture:
  - Three vibe families (warm, formal, bold) provide the structural design.
  - Eight archetype touches (coach, consultant, financial_educator,
    creative, fitness_wellness, course_creator, service_provider, custom)
    add archetype-specific patterns.
  - Bundle is the single source of truth — Smart Sites never writes to it.
  - render_smart_site_page() is the canonical entry point.

Backwards compatibility: this module is opt-in via
site_config.use_smart_sites. The legacy public_site.py handlers fall
through to existing rendering when the flag is false. All Smart Sites
calls in handlers are wrapped in try/except so a rendering bug NEVER
breaks legacy.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

# Reuse brand_engine helpers — single source of truth for bundle and
# disclaimer phrasing. We do NOT import from public_site (that would be
# a circular import; public_site imports smart_sites).
from brand_engine import (
    DISCLAIMER_PHRASES,
    VIBE_FAMILY_MAP,
    _sb_get,
    _sb_patch,
    get_bundle,
)

VIBE_FAMILIES = ("warm", "formal", "bold")

# Mirror brand_engine.VIBE_FAMILY_MAP for clarity at the call site.
BRAND_VOICE_TO_VIBE = dict(VIBE_FAMILY_MAP)

ARCHETYPE_TOUCHES = (
    "coach",
    "consultant",
    "financial_educator",
    "creative",
    "fitness_wellness",
    "course_creator",
    "service_provider",
    "custom",
)

DEFAULT_SITE_CONFIG: Dict[str, Any] = {
    "use_smart_sites": False,
    "vibe_family_override": None,
    "vocabulary_override": None,  # Pass 3.5 Session 3
    "layout_id": None,             # Pass 3.5 Session 3
    "sections": {
        "hero": {
            "enabled": True,
            "headline": None,
            "subheadline": None,
            "cta_label": None,
            "cta_link": None,
        },
        "about": {"enabled": True, "text": None},
        "services": {"enabled": True},
        # Pass 3.6 — four new section types. All default disabled so
        # existing sites do NOT suddenly grow new content from this
        # deploy. Users opt in via the MySite editor.
        "testimonials": {
            "enabled": False,
            "heading": "What clients say",
            "items": [],
        },
        "gallery": {
            "enabled": False,
            "heading": "Gallery",
            "items": [],
        },
        "resources": {
            "enabled": False,
            "heading": "Free Resources",
            "subtext": None,
            "items": [],
        },
        "contact": {
            "enabled": False,
            "heading": "Get in touch",
            "subtext": None,
            "email": None,
            "phone": None,
            "address": None,
            "show_form": True,
        },
    },
    "footer_extra_text": None,
    "custom_domain": None,
}


# ─────────────────────────────────────────────────────────────
# Config + dispatch
# ─────────────────────────────────────────────────────────────


def get_site_config(business_id: str) -> Dict[str, Any]:
    """Read business_sites.site_config and merge with defaults."""
    rows = _sb_get(
        f"/business_sites?business_id=eq.{business_id}&select=site_config&limit=1"
    ) or []
    raw = (rows[0].get("site_config") if rows else None) or {}
    return _merge_with_defaults(raw)


def _merge_with_defaults(raw: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {**DEFAULT_SITE_CONFIG, "sections": {}}
    for k, v in DEFAULT_SITE_CONFIG["sections"].items():
        merged["sections"][k] = dict(v)
    for k, v in raw.items():
        if k == "sections" and isinstance(v, dict):
            for sk, sv in v.items():
                base = merged["sections"].get(sk) or {}
                merged["sections"][sk] = {**base, **(sv if isinstance(sv, dict) else {})}
        else:
            merged[k] = v
    return merged


def resolve_layout_and_vocabulary(
    business_id: str,
    site_config: Dict[str, Any],
):
    """Pass 3.5 Session 3: resolve which Studio layout + vocabulary triple
    to render with.

    Reads business_profiles + voice_profile + brand_kit, runs vocabulary
    detection (or honors site_config.vocabulary_override), picks layout
    from vocab affinity (or honors site_config.layout_id), composes the
    DesignSystem.

    Returns a tuple:
        (layout_id, primary_vocab_id, composite, design_system, business_data,
         business_profile, detected_matches)

    Any element may be None if a step failed; the caller is responsible
    for falling through to legacy rendering when layout_id or
    design_system is None.
    """
    try:
        from studio_data import LAYOUTS, VOCAB_LAYOUT_MAP, VOCABULARIES
        from studio_composite import build_composite
        from studio_design_system import build_design_system
        from studio_vocab_detect import detect_vocabularies, detect_vocabulary_triple
    except Exception:
        return None, None, None, None, None, None, []

    biz_rows = _sb_get(f"/businesses?id=eq.{business_id}&select=*&limit=1") or []
    business_data = biz_rows[0] if biz_rows else {}
    voice_profile = business_data.get("voice_profile") or {}
    brand_kit = (business_data.get("settings") or {}).get("brand_kit") or {}

    profile_rows = _sb_get(f"/business_profiles?business_id=eq.{business_id}&select=*&limit=1") or []
    business_profile = profile_rows[0] if profile_rows else {}

    # ─── Step 1: vocabulary resolution ──────────────────────────
    detected_matches = []
    try:
        detected_matches = detect_vocabularies(
            business_data, business_profile, voice_profile, brand_kit
        )
    except Exception:
        detected_matches = []

    vocab_override = site_config.get("vocabulary_override")
    primary_vocab_id: Optional[str] = None
    secondary_id: Optional[str] = None
    aesthetic_id: Optional[str] = None

    if vocab_override and vocab_override in VOCABULARIES:
        primary_vocab_id = vocab_override
        primary_section = VOCABULARIES[primary_vocab_id]["section"]
        # Pick secondary from a different section, aesthetic from aesthetic-movement
        for m in detected_matches:
            v = m["vocabulary"]
            if v["id"] == primary_vocab_id:
                continue
            if secondary_id is None and v["section"] != primary_section:
                secondary_id = v["id"]
            if aesthetic_id is None and v["section"] == "aesthetic-movement" and v["id"] != primary_vocab_id:
                aesthetic_id = v["id"]
        # Fallback: any non-primary match becomes secondary if still empty
        if secondary_id is None:
            for m in detected_matches:
                if m["vocabulary"]["id"] != primary_vocab_id:
                    secondary_id = m["vocabulary"]["id"]
                    break
    else:
        # No override — use detection's full triple
        if detected_matches:
            try:
                primary_vocab_id, secondary_id, aesthetic_id = detect_vocabulary_triple(
                    business_data, business_profile, voice_profile, brand_kit
                )
            except Exception:
                primary_vocab_id = secondary_id = aesthetic_id = None

    if not primary_vocab_id:
        return None, None, None, None, business_data, business_profile, detected_matches

    # ─── Step 2: build composite + design system ─────────────────
    try:
        composite = build_composite(primary_vocab_id, secondary_id, aesthetic_id)
        design_system = build_design_system(
            composite,
            business_name=business_data.get("name") or "Welcome",
            tagline=business_data.get("tagline") or (brand_kit.get("tagline") if isinstance(brand_kit, dict) else None),
        )
    except Exception:
        return None, primary_vocab_id, None, None, business_data, business_profile, detected_matches

    # ─── Step 3: layout resolution ──────────────────────────────
    layout_override = site_config.get("layout_id")
    if layout_override and layout_override in LAYOUTS:
        layout_id = layout_override
    else:
        affinity = VOCAB_LAYOUT_MAP.get(primary_vocab_id, [])
        layout_id = affinity[0] if affinity else None

    return (
        layout_id,
        primary_vocab_id,
        composite,
        design_system,
        business_data,
        business_profile,
        detected_matches,
    )


def resolve_vibe_family(bundle: Dict[str, Any], site_config: Dict[str, Any]) -> str:
    """Override > bundle.design.vibe_family > brand_voice mapping > 'warm'."""
    override = site_config.get("vibe_family_override")
    if override in VIBE_FAMILIES:
        return override
    bundle_vibe = (bundle.get("design") or {}).get("vibe_family")
    if bundle_vibe in VIBE_FAMILIES:
        return bundle_vibe
    bv = (bundle.get("voice") or {}).get("brand_voice")
    return BRAND_VOICE_TO_VIBE.get(bv, "warm")


# ─────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────


def _safe_html(text: Optional[str], default: str = "") -> str:
    if not text:
        return default
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _color(bundle: Dict[str, Any], key: str, fallback: str = "#1a1a1a") -> str:
    return (bundle.get("design") or {}).get(key) or fallback


def _font(bundle: Dict[str, Any], key: str, fallback: str = "Inter") -> str:
    return (bundle.get("design") or {}).get(key) or fallback


def _disclaimer_phrase(key: str) -> str:
    return DISCLAIMER_PHRASES.get(key, "")


def _render_disclaimers(bundle: Dict[str, Any]) -> str:
    keys = (bundle.get("legal") or {}).get("required_disclaimers") or []
    items = [_disclaimer_phrase(k) for k in keys if _disclaimer_phrase(k)]
    return " ".join(items) if items else ""


def _build_head_meta(business_id: str) -> str:
    """Wrap public_site._brand_head_meta_tags. Defensive against import errors."""
    try:
        from public_site import _brand_head_meta_tags
        return _brand_head_meta_tags(business_id) or ""
    except Exception:
        return ""


def _font_url_segment(name: str) -> str:
    """URL-safe font-family name for Google Fonts query string."""
    return name.replace(" ", "+")


# ─────────────────────────────────────────────────────────────
# VIBE FAMILY: warm
# ─────────────────────────────────────────────────────────────


def _warm_head_styles(bundle: Dict[str, Any]) -> str:
    primary = _color(bundle, "primary_color", "#7a5535")
    accent = _color(bundle, "accent_color", "#d4af37")
    bg = _color(bundle, "background_color", "#fdfcfa")
    text = _color(bundle, "text_color", "#2d2a26")
    h_font = _font(bundle, "font_heading", "Cormorant Garamond")
    b_font = _font(bundle, "font_body", "Inter")
    return f"""
<link href="https://fonts.googleapis.com/css2?family={_font_url_segment(h_font)}:wght@400;600;700&family={_font_url_segment(b_font)}:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;}}
body{{margin:0;background:{bg};color:{text};font-family:'{b_font}',-apple-system,BlinkMacSystemFont,sans-serif;line-height:1.65;}}
h1,h2,h3,h4{{font-family:'{h_font}',Georgia,serif;font-weight:600;letter-spacing:-0.01em;}}
h1{{font-size:clamp(2.5rem,5vw,4rem);line-height:1.1;margin:0 0 0.5em;}}
h2{{font-size:2rem;margin:1.5em 0 0.5em;}}
h3{{font-size:1.4rem;margin:1em 0 0.3em;}}
p{{margin:0 0 1em;}}
a{{color:{primary};text-decoration:none;}}
a:hover{{text-decoration:underline;}}
.btn{{display:inline-block;padding:14px 32px;background:{primary};color:#fff;border-radius:999px;font-weight:500;transition:opacity 0.2s ease;}}
.btn:hover{{opacity:0.9;text-decoration:none;}}
.section{{max-width:960px;margin:0 auto;padding:80px 24px;}}
.hero{{text-align:center;padding:120px 24px 80px;background:linear-gradient(180deg,{bg} 0%,color-mix(in srgb,{accent} 8%,{bg}) 100%);}}
.hero .subhead{{font-size:1.2rem;color:color-mix(in srgb,{text} 70%,transparent);max-width:600px;margin:0 auto 2em;}}
.itc-badge{{display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border-radius:999px;background:color-mix(in srgb,{accent} 18%,transparent);color:{primary};font-size:0.85rem;font-weight:500;margin-bottom:1em;}}
.footer{{background:color-mix(in srgb,{primary} 4%,{bg});padding:48px 24px;text-align:center;font-size:0.9rem;color:color-mix(in srgb,{text} 65%,transparent);}}
.footer .disclaimers{{max-width:700px;margin:1em auto;font-size:0.8rem;line-height:1.5;}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:24px;margin-top:2em;}}
.card{{padding:24px;border:1px solid color-mix(in srgb,{primary} 12%,transparent);border-radius:16px;background:color-mix(in srgb,{bg} 85%,white);}}
.archetype-box{{border-left:4px solid {primary};padding:18px 24px;background:color-mix(in srgb,{primary} 4%,transparent);border-radius:8px;font-size:0.95rem;}}
@media (max-width:640px){{.hero{{padding:80px 20px 60px;}}.section{{padding:60px 20px;}}}}
</style>
"""


def _warm_render_in_the_clear_badge(bundle: Dict[str, Any]) -> str:
    if not (bundle.get("legal") or {}).get("in_the_clear"):
        return ""
    return '<div class="itc-badge">✓ Verified Business</div>'


def _warm_render_hero(bundle: Dict[str, Any], hero_config: Dict[str, Any]) -> str:
    if not hero_config.get("enabled", True):
        return ""
    business_name = (bundle.get("business") or {}).get("name") or "Welcome"
    headline = _safe_html(hero_config.get("headline")) or _safe_html(business_name)
    subheadline = _safe_html(hero_config.get("subheadline")) or _safe_html(
        (bundle.get("business") or {}).get("tagline")
    )
    cta_label = _safe_html(hero_config.get("cta_label"), "Get in touch")
    cta_link = _safe_html(hero_config.get("cta_link"), "#contact")
    badge = _warm_render_in_the_clear_badge(bundle)
    sub = f'<p class="subhead">{subheadline}</p>' if subheadline else ''
    return f"""
<section class="hero">
  {badge}
  <h1>{headline}</h1>
  {sub}
  <a href="{cta_link}" class="btn">{cta_label}</a>
</section>
"""


def _warm_render_about(bundle: Dict[str, Any], about_config: Dict[str, Any]) -> str:
    if not about_config.get("enabled", True):
        return ""
    practitioner = _safe_html(
        (bundle.get("practitioner") or {}).get("display_name") or "the team"
    )
    text = _safe_html(about_config.get("text")) or _safe_html(
        (bundle.get("business") or {}).get("elevator_pitch")
    )
    if not text:
        return ""
    return f"""
<section class="section">
  <h2>About {practitioner}</h2>
  <p>{text}</p>
</section>
"""


def _warm_render_services(
    bundle: Dict[str, Any], products: List[Dict[str, Any]], services_config: Dict[str, Any]
) -> str:
    if not services_config.get("enabled", True) or not products:
        return ""
    primary = _color(bundle, "primary_color")
    cards: List[str] = []
    for p in products[:6]:
        name = _safe_html(p.get("name", "Service"))
        desc = _safe_html(p.get("description") or "")
        price = p.get("price")
        try:
            price_label = f"${float(price):,.0f}" if price else ""
        except (TypeError, ValueError):
            price_label = ""
        desc_html = f'<p>{desc}</p>' if desc else ''
        price_html = (
            f'<div style="font-size:1.4rem;font-weight:600;color:{primary};margin-top:1em;">{price_label}</div>'
            if price_label else ''
        )
        cards.append(f'<div class="card"><h3>{name}</h3>{desc_html}{price_html}</div>')
    return f"""
<section class="section">
  <h2>Services</h2>
  <div class="cards">{''.join(cards)}</div>
</section>
"""


def _warm_render_footer(bundle: Dict[str, Any], footer_extra: Optional[str]) -> str:
    copyright_line = _safe_html(
        (bundle.get("footer") or {}).get("copyright_line")
        or f"© {datetime.now().year} {(bundle.get('practitioner') or {}).get('display_name') or 'The Practitioner'}"
    )
    disclaimers = _render_disclaimers(bundle)
    contact_email = (bundle.get("footer") or {}).get("contact_email") or ""
    extra = _safe_html(footer_extra) if footer_extra else ""
    disc_html = f'<div class="disclaimers">{disclaimers}</div>' if disclaimers else ''
    contact_html = (
        f'<div style="margin-top:1em;"><a href="mailto:{contact_email}">{contact_email}</a></div>'
        if contact_email else ''
    )
    extra_html = f'<div class="disclaimers">{extra}</div>' if extra else ''
    return f"""
<footer class="footer">
  <div>{copyright_line}</div>
  {disc_html}
  {extra_html}
  {contact_html}
</footer>
"""


# ─────────────────────────────────────────────────────────────
# VIBE FAMILY: formal
# ─────────────────────────────────────────────────────────────


def _formal_head_styles(bundle: Dict[str, Any]) -> str:
    primary = _color(bundle, "primary_color", "#1a365d")
    accent = _color(bundle, "accent_color", "#2c5282")
    bg = _color(bundle, "background_color", "#ffffff")
    text = _color(bundle, "text_color", "#1a202c")
    h_font = _font(bundle, "font_heading", "Merriweather")
    b_font = _font(bundle, "font_body", "Source Sans 3")
    return f"""
<link href="https://fonts.googleapis.com/css2?family={_font_url_segment(h_font)}:wght@400;700;900&family={_font_url_segment(b_font)}:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;}}
body{{margin:0;background:{bg};color:{text};font-family:'{b_font}','Source Sans Pro',-apple-system,sans-serif;line-height:1.6;}}
h1,h2,h3,h4{{font-family:'{h_font}',Georgia,serif;font-weight:700;letter-spacing:0.01em;}}
h1{{font-size:clamp(2rem,4vw,3rem);line-height:1.2;margin:0 0 0.5em;}}
h2{{font-size:1.6rem;margin:1.5em 0 0.5em;}}
h3{{font-size:1.2rem;margin:1em 0 0.3em;}}
p{{margin:0 0 1em;}}
a{{color:{primary};text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px;}}
a:hover{{text-decoration-thickness:2px;}}
.btn{{display:inline-block;padding:12px 28px;background:{primary};color:#fff;border-radius:4px;font-weight:600;text-decoration:none;border:1px solid {primary};transition:background 0.2s ease;}}
.btn:hover{{background:{accent};text-decoration:none;}}
.section{{max-width:1080px;margin:0 auto;padding:64px 24px;}}
.hero{{padding:96px 24px 64px;border-bottom:1px solid color-mix(in srgb,{text} 12%,transparent);}}
.hero .subhead{{font-size:1.1rem;color:color-mix(in srgb,{text} 75%,transparent);max-width:680px;margin:0 0 1.5em;}}
.itc-badge{{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border:1px solid {primary};color:{primary};font-size:0.8rem;font-weight:600;margin-bottom:1em;text-transform:uppercase;letter-spacing:0.05em;}}
.footer{{background:color-mix(in srgb,{text} 4%,{bg});padding:48px 24px;font-size:0.85rem;color:color-mix(in srgb,{text} 70%,transparent);border-top:1px solid color-mix(in srgb,{text} 10%,transparent);}}
.footer .footer-inner{{max-width:1080px;margin:0 auto;}}
.footer .disclaimers{{margin:1em 0;font-size:0.78rem;line-height:1.6;}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:20px;margin-top:1.5em;}}
.card{{padding:24px;border:1px solid color-mix(in srgb,{text} 10%,transparent);border-radius:4px;background:{bg};}}
.archetype-box{{border:1px solid {primary};padding:20px 28px;background:color-mix(in srgb,{primary} 3%,transparent);border-radius:4px;font-size:0.95rem;line-height:1.6;}}
@media (max-width:640px){{.hero{{padding:64px 20px 48px;}}.section{{padding:48px 20px;}}}}
</style>
"""


def _formal_render_in_the_clear_badge(bundle: Dict[str, Any]) -> str:
    if not (bundle.get("legal") or {}).get("in_the_clear"):
        return ""
    return '<div class="itc-badge">Verified Business</div>'


def _formal_render_hero(bundle: Dict[str, Any], hero_config: Dict[str, Any]) -> str:
    if not hero_config.get("enabled", True):
        return ""
    business_name = (bundle.get("business") or {}).get("name") or "Welcome"
    headline = _safe_html(hero_config.get("headline")) or _safe_html(business_name)
    subheadline = _safe_html(hero_config.get("subheadline")) or _safe_html(
        (bundle.get("business") or {}).get("tagline")
    )
    cta_label = _safe_html(hero_config.get("cta_label"), "Schedule a consultation")
    cta_link = _safe_html(hero_config.get("cta_link"), "#contact")
    badge = _formal_render_in_the_clear_badge(bundle)
    sub = f'<p class="subhead">{subheadline}</p>' if subheadline else ''
    return f"""
<section class="hero section">
  {badge}
  <h1>{headline}</h1>
  {sub}
  <a href="{cta_link}" class="btn">{cta_label}</a>
</section>
"""


def _formal_render_about(bundle: Dict[str, Any], about_config: Dict[str, Any]) -> str:
    if not about_config.get("enabled", True):
        return ""
    pract = bundle.get("practitioner") or {}
    title = _safe_html(pract.get("preferred_title"))
    name = _safe_html(pract.get("display_name") or "the team")
    label = f"{title} {name}".strip() if title else name
    text = _safe_html(about_config.get("text")) or _safe_html(
        (bundle.get("business") or {}).get("elevator_pitch")
    )
    if not text:
        return ""
    return f"""
<section class="section">
  <h2>About {label}</h2>
  <p>{text}</p>
</section>
"""


def _formal_render_services(
    bundle: Dict[str, Any], products: List[Dict[str, Any]], services_config: Dict[str, Any]
) -> str:
    if not services_config.get("enabled", True) or not products:
        return ""
    primary = _color(bundle, "primary_color")
    cards: List[str] = []
    for p in products[:6]:
        name = _safe_html(p.get("name", "Service"))
        desc = _safe_html(p.get("description") or "")
        price = p.get("price")
        try:
            price_label = f"${float(price):,.0f}" if price else ""
        except (TypeError, ValueError):
            price_label = ""
        desc_html = f'<p>{desc}</p>' if desc else ''
        price_html = (
            f'<div style="font-size:1.2rem;font-weight:700;color:{primary};margin-top:1em;font-family:Georgia,serif;">{price_label}</div>'
            if price_label else ''
        )
        cards.append(f'<div class="card"><h3>{name}</h3>{desc_html}{price_html}</div>')
    return f"""
<section class="section">
  <h2>Services</h2>
  <div class="cards">{''.join(cards)}</div>
</section>
"""


def _formal_render_footer(bundle: Dict[str, Any], footer_extra: Optional[str]) -> str:
    copyright_line = _safe_html(
        (bundle.get("footer") or {}).get("copyright_line")
        or f"© {datetime.now().year} {(bundle.get('practitioner') or {}).get('display_name') or 'The Practitioner'}"
    )
    disclaimers = _render_disclaimers(bundle)
    state = ((bundle.get("legal") or {}).get("governing_state") or "")
    contact_email = (bundle.get("footer") or {}).get("contact_email") or ""
    extra = _safe_html(footer_extra) if footer_extra else ""
    state_html = f'<div>Governing law: {_safe_html(state)}.</div>' if state else ''
    disc_html = f'<div class="disclaimers">{disclaimers}</div>' if disclaimers else ''
    contact_html = (
        f'<div style="margin-top:1em;">Contact: <a href="mailto:{contact_email}">{contact_email}</a></div>'
        if contact_email else ''
    )
    extra_html = f'<div class="disclaimers">{extra}</div>' if extra else ''
    return f"""
<footer class="footer">
  <div class="footer-inner">
    <div>{copyright_line}</div>
    {state_html}
    {disc_html}
    {extra_html}
    {contact_html}
  </div>
</footer>
"""


# ─────────────────────────────────────────────────────────────
# VIBE FAMILY: bold
# ─────────────────────────────────────────────────────────────


def _bold_head_styles(bundle: Dict[str, Any]) -> str:
    primary = _color(bundle, "primary_color", "#0d0d12")
    accent = _color(bundle, "accent_color", "#ff5722")
    bg = _color(bundle, "background_color", "#0a0a0f")
    text = _color(bundle, "text_color", "#f5f4f0")
    h_font = _font(bundle, "font_heading", "Montserrat")
    b_font = _font(bundle, "font_body", "Inter")
    return f"""
<link href="https://fonts.googleapis.com/css2?family={_font_url_segment(h_font)}:wght@700;800;900&family={_font_url_segment(b_font)}:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;}}
body{{margin:0;background:{bg};color:{text};font-family:'{b_font}',-apple-system,sans-serif;line-height:1.55;}}
h1,h2,h3,h4{{font-family:'{h_font}',sans-serif;font-weight:800;letter-spacing:-0.02em;text-transform:none;}}
h1{{font-size:clamp(3rem,7vw,6rem);line-height:0.95;margin:0 0 0.4em;font-weight:900;text-transform:uppercase;}}
h2{{font-size:2.4rem;margin:1.5em 0 0.5em;text-transform:uppercase;}}
h3{{font-size:1.3rem;margin:1em 0 0.3em;font-weight:700;}}
p{{margin:0 0 1em;}}
a{{color:{accent};text-decoration:none;border-bottom:2px solid {accent};}}
a:hover{{background:{accent};color:{bg};}}
.btn{{display:inline-block;padding:18px 40px;background:{accent};color:{bg};border:3px solid {accent};font-weight:700;text-transform:uppercase;letter-spacing:0.08em;font-size:0.95rem;transition:all 0.2s ease;}}
.btn:hover{{background:transparent;color:{accent};border-bottom:3px solid {accent};}}
.section{{max-width:1200px;margin:0 auto;padding:120px 32px;}}
.hero{{padding:160px 32px 120px;background:{bg};border-bottom:6px solid {accent};}}
.hero .subhead{{font-size:1.3rem;color:color-mix(in srgb,{text} 80%,transparent);max-width:700px;margin:0 0 2.5em;font-weight:500;}}
.itc-badge{{display:inline-block;padding:8px 16px;background:{accent};color:{bg};font-size:0.75rem;font-weight:800;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:1.5em;}}
.footer{{background:{primary};padding:64px 32px;font-size:0.85rem;color:color-mix(in srgb,{text} 70%,transparent);border-top:6px solid {accent};}}
.footer-inner{{max-width:1200px;margin:0 auto;}}
.footer .disclaimers{{max-width:800px;margin:1.5em 0;font-size:0.78rem;line-height:1.6;}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:0;margin-top:3em;border-top:2px solid {accent};border-left:2px solid {accent};}}
.card{{padding:32px;border-right:2px solid {accent};border-bottom:2px solid {accent};background:color-mix(in srgb,{text} 4%,{bg});}}
.archetype-box{{border:3px solid {accent};padding:24px 32px;background:color-mix(in srgb,{accent} 8%,transparent);font-size:1rem;text-transform:none;font-weight:500;}}
@media (max-width:640px){{.hero{{padding:96px 20px 64px;}}.section{{padding:80px 20px;}}.cards{{grid-template-columns:1fr;}}}}
</style>
"""


def _bold_render_in_the_clear_badge(bundle: Dict[str, Any]) -> str:
    if not (bundle.get("legal") or {}).get("in_the_clear"):
        return ""
    return '<div class="itc-badge">✓ Verified</div>'


def _bold_render_hero(bundle: Dict[str, Any], hero_config: Dict[str, Any]) -> str:
    if not hero_config.get("enabled", True):
        return ""
    business_name = (bundle.get("business") or {}).get("name") or "Welcome"
    headline = _safe_html(hero_config.get("headline")) or _safe_html(business_name)
    subheadline = _safe_html(hero_config.get("subheadline")) or _safe_html(
        (bundle.get("business") or {}).get("tagline")
    )
    cta_label = _safe_html(hero_config.get("cta_label"), "Start Now")
    cta_link = _safe_html(hero_config.get("cta_link"), "#contact")
    badge = _bold_render_in_the_clear_badge(bundle)
    sub = f'<p class="subhead">{subheadline}</p>' if subheadline else ''
    return f"""
<section class="hero">
  {badge}
  <h1>{headline}</h1>
  {sub}
  <a href="{cta_link}" class="btn">{cta_label}</a>
</section>
"""


def _bold_render_about(bundle: Dict[str, Any], about_config: Dict[str, Any]) -> str:
    if not about_config.get("enabled", True):
        return ""
    pract = _safe_html(
        (bundle.get("practitioner") or {}).get("display_name") or "the team"
    )
    text = _safe_html(about_config.get("text")) or _safe_html(
        (bundle.get("business") or {}).get("elevator_pitch")
    )
    if not text:
        return ""
    return f"""
<section class="section">
  <h2>About {pract}</h2>
  <p style="font-size:1.15rem;max-width:760px;">{text}</p>
</section>
"""


def _bold_render_services(
    bundle: Dict[str, Any], products: List[Dict[str, Any]], services_config: Dict[str, Any]
) -> str:
    if not services_config.get("enabled", True) or not products:
        return ""
    accent = _color(bundle, "accent_color", "#ff5722")
    cards: List[str] = []
    for p in products[:6]:
        name = _safe_html(p.get("name", "Service"))
        desc = _safe_html(p.get("description") or "")
        price = p.get("price")
        try:
            price_label = f"${float(price):,.0f}" if price else ""
        except (TypeError, ValueError):
            price_label = ""
        desc_html = f'<p>{desc}</p>' if desc else ''
        price_html = (
            f'<div style="font-size:1.6rem;font-weight:900;color:{accent};margin-top:1em;">{price_label}</div>'
            if price_label else ''
        )
        cards.append(f'<div class="card"><h3>{name}</h3>{desc_html}{price_html}</div>')
    return f"""
<section class="section">
  <h2>Services</h2>
  <div class="cards">{''.join(cards)}</div>
</section>
"""


def _bold_render_footer(bundle: Dict[str, Any], footer_extra: Optional[str]) -> str:
    copyright_line = _safe_html(
        (bundle.get("footer") or {}).get("copyright_line")
        or f"© {datetime.now().year} {(bundle.get('practitioner') or {}).get('display_name') or 'The Practitioner'}"
    )
    disclaimers = _render_disclaimers(bundle)
    contact_email = (bundle.get("footer") or {}).get("contact_email") or ""
    extra = _safe_html(footer_extra) if footer_extra else ""
    disc_html = f'<div class="disclaimers">{disclaimers}</div>' if disclaimers else ''
    contact_html = (
        f'<div style="margin-top:1em;"><a href="mailto:{contact_email}">{contact_email}</a></div>'
        if contact_email else ''
    )
    extra_html = f'<div class="disclaimers">{extra}</div>' if extra else ''
    return f"""
<footer class="footer">
  <div class="footer-inner">
    <div style="text-transform:uppercase;letter-spacing:0.08em;font-weight:700;">{copyright_line}</div>
    {disc_html}
    {extra_html}
    {contact_html}
  </div>
</footer>
"""


# ─────────────────────────────────────────────────────────────
# Vibe dispatch
# ─────────────────────────────────────────────────────────────


VIBE_RENDERERS: Dict[str, Dict[str, Any]] = {
    "warm": {
        "head_styles": _warm_head_styles,
        "hero": _warm_render_hero,
        "about": _warm_render_about,
        "services": _warm_render_services,
        "footer": _warm_render_footer,
        "in_the_clear_badge": _warm_render_in_the_clear_badge,
    },
    "formal": {
        "head_styles": _formal_head_styles,
        "hero": _formal_render_hero,
        "about": _formal_render_about,
        "services": _formal_render_services,
        "footer": _formal_render_footer,
        "in_the_clear_badge": _formal_render_in_the_clear_badge,
    },
    "bold": {
        "head_styles": _bold_head_styles,
        "hero": _bold_render_hero,
        "about": _bold_render_about,
        "services": _bold_render_services,
        "footer": _bold_render_footer,
        "in_the_clear_badge": _bold_render_in_the_clear_badge,
    },
}


# ─────────────────────────────────────────────────────────────
# Archetype touches
# ─────────────────────────────────────────────────────────────


def _archetype_box(text: str) -> str:
    """Render a generic archetype callout in the active vibe via .archetype-box."""
    return f'<section class="section"><div class="archetype-box">{text}</div></section>'


def _render_financial_educator_warning(bundle: Dict[str, Any], vibe: str) -> str:
    return _archetype_box(
        "<strong>Educational content only.</strong> All material is for educational "
        "purposes only and does not constitute financial, investment, or tax advice. "
        "Past performance does not guarantee future results."
    )


def _render_fitness_liability_box(bundle: Dict[str, Any], vibe: str) -> str:
    return _archetype_box(
        "<strong>Health & safety.</strong> Participants assume all risk of physical "
        "injury. Consult your physician before beginning any program."
    )


def _render_coach_transformation_callout(bundle: Dict[str, Any], vibe: str) -> str:
    return _archetype_box(
        "<strong>Results vary.</strong> Coaching outcomes depend on the participant's "
        "engagement and effort. Outcomes are not guaranteed."
    )


def _render_consultant_case_study_callout(bundle: Dict[str, Any], vibe: str) -> str:
    return _archetype_box(
        "<strong>Engagements are bespoke.</strong> Scope and deliverables are defined "
        "in writing per engagement. Past client results do not guarantee future outcomes."
    )


def _render_creative_portfolio_callout(bundle: Dict[str, Any], vibe: str) -> str:
    return _archetype_box(
        "<strong>Portfolio rights.</strong> Provider retains the right to display work "
        "in portfolio unless otherwise agreed. Deliverables transfer to the client upon "
        "final payment."
    )


def _render_course_creator_curriculum_callout(bundle: Dict[str, Any], vibe: str) -> str:
    return _archetype_box(
        "<strong>Course access & terms.</strong> Course content may not be redistributed. "
        "Refund and access terms are stated in the enrollment agreement."
    )


def _render_service_provider_booking_cta(bundle: Dict[str, Any], vibe: str) -> str:
    slug = (bundle.get("business") or {}).get("slug")
    if slug:
        href = f"/public/booking/{slug}"
        return _archetype_box(
            f'<strong>Book with us.</strong> Choose a time that works for you. '
            f'<a href="{href}">View open slots →</a>'
        )
    return _archetype_box(
        "<strong>Book a service.</strong> Reach out to schedule your appointment."
    )


def _archetype_touches(archetype: str, vibe: str, bundle: Dict[str, Any]) -> Dict[str, str]:
    """Return HTML fragments to inject at named positions based on archetype."""
    touches = {"before_about": "", "after_services": "", "footer_addendum": ""}
    if archetype == "financial_educator":
        touches["before_about"] = _render_financial_educator_warning(bundle, vibe)
    elif archetype == "fitness_wellness":
        touches["after_services"] = _render_fitness_liability_box(bundle, vibe)
    elif archetype == "coach":
        touches["after_services"] = _render_coach_transformation_callout(bundle, vibe)
    elif archetype == "consultant":
        touches["after_services"] = _render_consultant_case_study_callout(bundle, vibe)
    elif archetype == "creative":
        touches["after_services"] = _render_creative_portfolio_callout(bundle, vibe)
    elif archetype == "course_creator":
        touches["after_services"] = _render_course_creator_curriculum_callout(bundle, vibe)
    elif archetype == "service_provider":
        touches["after_services"] = _render_service_provider_booking_cta(bundle, vibe)
    # custom: no touches — vibe family alone
    return touches


# ─────────────────────────────────────────────────────────────
# Page-type body renderers (non-home)
# ─────────────────────────────────────────────────────────────


def _render_thank_you_body(bundle: Dict[str, Any], vibe: str, opts: Dict[str, Any]) -> str:
    primary = _color(bundle, "primary_color")
    accent = _color(bundle, "accent_color", primary)
    business_name = _safe_html((bundle.get("business") or {}).get("name") or "")
    message = _safe_html(opts.get("message") or "Your message has been received. We'll be in touch soon.")
    home_link = (bundle.get("footer") or {}).get("site_url") or "/"
    return f"""
<section class="hero" style="text-align:center;">
  <div style="display:inline-flex;align-items:center;justify-content:center;width:84px;height:84px;border-radius:50%;background:color-mix(in srgb,{accent} 16%,transparent);border:2px solid {accent};margin-bottom:1.5rem;font-size:2rem;color:{accent};">✓</div>
  <h1>Thank you</h1>
  <p class="subhead">{message}</p>
  <a href="{home_link}" class="btn">Return to {business_name or 'home'}</a>
</section>
"""


def _render_link_page_body(bundle: Dict[str, Any], vibe: str, opts: Dict[str, Any]) -> str:
    business_name = _safe_html((bundle.get("business") or {}).get("name") or "")
    tagline = _safe_html((bundle.get("business") or {}).get("tagline") or "")
    links: List[Dict[str, Any]] = opts.get("links") or []
    items_html: List[str] = []
    for link in links[:12]:
        label = _safe_html(link.get("label") or link.get("title") or "")
        href = _safe_html(link.get("url") or link.get("href") or "#")
        if not label or href in ("", "#"):
            continue
        items_html.append(f'<a href="{href}" class="btn" style="display:block;margin-bottom:12px;text-align:center;">{label}</a>')
    body_links = "\n".join(items_html) or '<p style="text-align:center;">No links yet.</p>'
    sub = f'<p class="subhead">{tagline}</p>' if tagline else ''
    return f"""
<section class="hero" style="text-align:center;">
  <h1>{business_name}</h1>
  {sub}
</section>
<section class="section" style="max-width:520px;">
  {body_links}
</section>
"""


def _render_resources_page_body(bundle: Dict[str, Any], vibe: str, opts: Dict[str, Any]) -> str:
    resources: List[Dict[str, Any]] = opts.get("resources") or []
    cards: List[str] = []
    for r in resources[:24]:
        title = _safe_html(r.get("title") or r.get("name") or "Resource")
        desc = _safe_html(r.get("description") or "")
        href = _safe_html(r.get("url") or r.get("download_url") or "#")
        desc_html = f'<p>{desc}</p>' if desc else ''
        cards.append(
            f'<div class="card"><h3>{title}</h3>{desc_html}'
            f'<a href="{href}" class="btn" style="margin-top:0.75rem;">Download</a></div>'
        )
    grid = f'<div class="cards">{"".join(cards)}</div>' if cards else '<p>No resources available yet.</p>'
    return f"""
<section class="hero" style="text-align:center;">
  <h1>Resources</h1>
</section>
<section class="section">
  {grid}
</section>
"""


def _render_booking_page_body(bundle: Dict[str, Any], vibe: str, opts: Dict[str, Any]) -> str:
    business_name = _safe_html((bundle.get("business") or {}).get("name") or "")
    slug = _safe_html((bundle.get("business") or {}).get("slug") or "")
    form_id = _safe_html(opts.get("form_id") or "")
    return f"""
<section class="hero" style="text-align:center;">
  <h1>Book with {business_name}</h1>
  <p class="subhead">Pick a time that works for you and we'll confirm by email.</p>
</section>
<section class="section" style="max-width:560px;">
  <div id="booking-form" data-slug="{slug}" data-form="{form_id}" class="archetype-box">
    Booking widget — to load slots, the legacy booking handler is currently active.
    Smart Sites v2 will inline the slot-picker here.
  </div>
</section>
"""


# ─────────────────────────────────────────────────────────────
# Canonical entry points
# ─────────────────────────────────────────────────────────────


def _render_page(
    business_id: str,
    page_type: str,
    site_config: Dict[str, Any],
    opts: Dict[str, Any],
) -> str:
    bundle = get_bundle(business_id)
    vibe = resolve_vibe_family(bundle, site_config)
    archetype = (bundle.get("business") or {}).get("type") or "custom"
    renderers = VIBE_RENDERERS[vibe]
    touches = _archetype_touches(archetype, vibe, bundle)

    head_styles = renderers["head_styles"](bundle)
    business_name = _safe_html((bundle.get("business") or {}).get("name") or "Welcome")
    head_meta = _build_head_meta(business_id)

    sections_cfg = site_config.get("sections") or {}
    body_parts: List[str] = []

    if page_type == "home":
        if sections_cfg.get("hero", {}).get("enabled", True):
            body_parts.append(renderers["hero"](bundle, sections_cfg.get("hero", {})))
        if touches.get("before_about"):
            body_parts.append(touches["before_about"])
        if sections_cfg.get("about", {}).get("enabled", True):
            body_parts.append(renderers["about"](bundle, sections_cfg.get("about", {})))
        if sections_cfg.get("services", {}).get("enabled", True):
            products = opts.get("products") or []
            body_parts.append(renderers["services"](bundle, products, sections_cfg.get("services", {})))
        if touches.get("after_services"):
            body_parts.append(touches["after_services"])
        body_parts.append(renderers["footer"](bundle, site_config.get("footer_extra_text")))

    elif page_type == "thank_you":
        body_parts.append(_render_thank_you_body(bundle, vibe, opts))
        body_parts.append(renderers["footer"](bundle, site_config.get("footer_extra_text")))

    elif page_type == "link":
        body_parts.append(_render_link_page_body(bundle, vibe, opts))
        body_parts.append(renderers["footer"](bundle, site_config.get("footer_extra_text")))

    elif page_type == "resources":
        body_parts.append(_render_resources_page_body(bundle, vibe, opts))
        body_parts.append(renderers["footer"](bundle, site_config.get("footer_extra_text")))

    elif page_type == "booking":
        body_parts.append(_render_booking_page_body(bundle, vibe, opts))
        body_parts.append(renderers["footer"](bundle, site_config.get("footer_extra_text")))

    else:
        raise ValueError(f"Unknown page_type: {page_type}")

    body_html = "\n".join(p for p in body_parts if p)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{business_name}</title>
{head_meta}
{head_styles}
</head>
<body>
{body_html}
</body>
</html>"""


def _try_render_via_studio_layouts(
    business_id: str,
    site_config: Dict[str, Any],
    opts: Dict[str, Any],
) -> Optional[str]:
    """Pass 3.5 Session 3: attempt to render the home page via the new
    Studio layout system (23 vocabularies × 12 layouts). Returns the
    rendered HTML on success, None on ANY failure so the caller can
    fall through to the legacy 3-vibe-family path.

    NEVER raises. Logs warnings on internal failures.
    """
    import logging
    logger = logging.getLogger("smart_sites")
    try:
        layout_id, _vocab_id, composite, design_system, business_data, business_profile, _matches = (
            resolve_layout_and_vocabulary(business_id, site_config)
        )
        if not (layout_id and design_system and composite and business_data):
            return None

        from studio_layouts.dispatch import render_layout

        # Brand head meta tags (favicon / OG / Twitter Card) — defensive.
        head_meta_extra = ""
        try:
            from public_site import _brand_head_meta_tags
            head_meta_extra = _brand_head_meta_tags(business_id) or ""
        except Exception:
            pass

        bundle = get_bundle(business_id) or {}
        sections_config = site_config.get("sections") or {}
        products = opts.get("products") or []

        # Layouts read archetype from business_data["type"] for archetype
        # touches (financial_educator warning, fitness liability, etc.).
        # The raw `businesses.type` column doesn't always carry the
        # archetype the user picked in their business profile (e.g. ETS
        # has `businesses.type="coaching"` but `business_profiles.business_type="financial_educator"`).
        # Override here so the layout sees the canonical archetype.
        canonical_archetype = (
            (business_profile or {}).get("business_type")
            or (bundle.get("business") or {}).get("type")
            or business_data.get("type")
            or "custom"
        )
        business_data_for_render = dict(business_data)
        business_data_for_render["type"] = canonical_archetype

        # Pass 3.7c: pull the AI-generated decoration scheme (if any)
        # and apply its color/typography overrides to the design_system
        # before rendering. The scheme itself is also threaded through
        # so layouts can render motion modules conditionally. Without a
        # scheme, this is a no-op and Pass 3.7/3.7b deterministic
        # decoration applies as before.
        scheme = site_config.get("generated_decoration") if isinstance(site_config, dict) else None
        try:
            from studio_layouts.shared import apply_scheme_to_design_system
            design_system_for_render = apply_scheme_to_design_system(design_system, scheme)
        except Exception:
            design_system_for_render = design_system

        return render_layout(
            layout_id,
            business_data=business_data_for_render,
            design_system=design_system_for_render,
            composite=composite,
            sections_config=sections_config,
            bundle=bundle,
            head_meta_extra=head_meta_extra,
            products=products,
            scheme=scheme,
        )
    except Exception as e:
        logger.warning(
            f"[smart_sites] Studio layout render failed for {business_id}; "
            f"falling back to legacy 3-vibe rendering: {e}"
        )
        return None


def _try_serve_builder_html(
    business_id: str,
    site_config: Dict[str, Any],
) -> Optional[str]:
    """Pass 3.8d Layer 1 — serve persisted Builder-generated HTML if present.

    Returns the (motion-injected) HTML on hit, or None on miss / any error
    so the caller can fall through to layer 2.
    """
    import logging
    import sys
    logger = logging.getLogger("smart_sites")

    generated_html = site_config.get("generated_html")
    if not (
        generated_html
        and isinstance(generated_html, str)
        and len(generated_html) > 1000
    ):
        return None

    try:
        from studio_html_validator import inject_motion_modules
        scheme = site_config.get("generated_decoration")
        # Pass 3.8e — pass design_brief so the reactivity layer can render
        # strand-aware gradients on every page load (no regeneration needed).
        brief = site_config.get("design_brief")
        return inject_motion_modules(generated_html, scheme, brief)
    except Exception as e:
        logger.warning(
            f"[smart_sites] Builder HTML serve failed for {business_id}, "
            f"falling through: {e}"
        )
        print(
            f"[smart_sites] Builder HTML serve exception: {e}",
            file=sys.stderr,
        )
        return None


def _try_render_via_archetype(
    business_id: str,
    site_config: Dict[str, Any],
) -> Optional[str]:
    """Pass 3.8d Layer 2 — render via Pass 3.8c archetype renderer.

    Fires when a design_brief with a layoutArchetype exists but Builder
    output is unavailable. Returns rendered HTML or None on any failure.
    """
    import logging
    logger = logging.getLogger("smart_sites")

    brief = site_config.get("design_brief")
    if not (brief and brief.get("layoutArchetype")):
        return None

    try:
        from studio_render_context import build_context
        from studio_archetypes.dispatch import render_archetype

        biz_rows = _sb_get(
            f"/businesses?id=eq.{business_id}&select=*&limit=1"
        ) or []
        if not biz_rows:
            return None
        business_data = biz_rows[0]

        bundle = get_bundle(business_id) or {}
        scheme = site_config.get("generated_decoration")

        try:
            products = _sb_get(
                f"/products?business_id=eq.{business_id}"
                f"&status=eq.active&display_on_website=eq.true&select=*&limit=20"
            ) or []
            if not products:
                products = _sb_get(
                    f"/products?business_id=eq.{business_id}"
                    f"&status=eq.active&select=*&limit=20"
                ) or []
        except Exception:
            products = []

        try:
            testimonials = _sb_get(
                f"/testimonials?business_id=eq.{business_id}&select=*&limit=10"
            ) or []
        except Exception:
            testimonials = []

        context = build_context(
            business_id, business_data, bundle, brief, scheme,
            products, testimonials, [], [],
        )
        return render_archetype(brief["layoutArchetype"], context)
    except Exception as e:
        logger.warning(
            f"[smart_sites] Archetype render failed for {business_id}, "
            f"falling through: {e}"
        )
        return None


def _try_serve_multi_page(
    business_id: str, site_config: Dict[str, Any], path: str
) -> Optional[str]:
    """Pass 3.8g Layer 0 — serve a multi-page site if configured.

    Looks at site_config.site_type and site_config.generated_pages. When
    site_type == "multi-page" and the requested path resolves to a known
    page that has generated HTML, return that page's HTML with the
    reactivity layer injected. Returns None on any miss / failure so the
    caller falls through to the single-page chain.
    """
    import sys as _sys
    if site_config.get("site_type") != "multi-page":
        return None
    pages = site_config.get("generated_pages") or {}
    if not pages:
        return None
    try:
        from studio_page_types import slug_to_page_id
        page_id = slug_to_page_id(path or "/")
    except Exception as e:
        print(f"[smart_sites] slug_to_page_id failed: {e}", file=_sys.stderr)
        page_id = "home"

    page_html = pages.get(page_id) or pages.get("home")
    if not page_html or not isinstance(page_html, str) or len(page_html) < 200:
        return None

    try:
        from studio_html_validator import inject_motion_modules
        scheme = site_config.get("generated_decoration")
        brief = site_config.get("design_brief")
        return inject_motion_modules(page_html, scheme, brief)
    except Exception as e:
        print(
            f"[smart_sites] multi-page inject_motion_modules failed for "
            f"{business_id}/{page_id}: {e}",
            file=_sys.stderr,
        )
        # Last-ditch: return raw page_html so we don't break the live URL.
        return page_html


def render_smart_site_page(business_id: str, page_type: str, **opts: Any) -> str:
    """Render a Smart Sites page from bundle + persisted site_config.

    Fallback chain (home pages only — other page types stay on the legacy
    renderer until Session 4+):

    0. Pass 3.8g multi-page generated_pages[page_id] (with motion injection)
    1. Pass 3.8d Builder Agent generated_html (with motion injection)
    2. Pass 3.8c archetype renderer (when brief has layoutArchetype)
    3. Pass 3.7c / 3.5 Studio layout system (12 layouts × 23 vocabs)
    4. Legacy 3-vibe-family renderer — final safety net

    Each layer returns None on miss / failure and we fall through. A bug
    in any new layer must never break a live site; that's why the legacy
    renderer is the terminal fallback.

    Args:
      business_id: target business
      page_type: 'home' | 'thank_you' | 'link' | 'resources' | 'booking'
      opts: page-specific data (products, links, resources, etc.).
            New (3.8g): opts["path"] selects the multi-page route. Defaults
            to "/" so callers that don't pass a path still get the home page.
    """
    site_config = get_site_config(business_id)
    path = opts.get("path") or "/"

    if page_type == "home":
        # Layer 0: 3.8g multi-page route
        try:
            from studio_config import MULTI_PAGE_ENABLED
            if MULTI_PAGE_ENABLED:
                multi_html = _try_serve_multi_page(business_id, site_config, path)
                if multi_html:
                    return multi_html
        except Exception as e:
            import sys as _sys
            print(f"[smart_sites] multi-page layer crashed: {e}", file=_sys.stderr)
            # Fall through silently — multi-page failure must never break the site.

        # Layer 1: Builder Agent output
        builder_html = _try_serve_builder_html(business_id, site_config)
        if builder_html:
            return builder_html

        # Layer 2: 3.8c archetype renderer
        archetype_html = _try_render_via_archetype(business_id, site_config)
        if archetype_html:
            return archetype_html

        # Layer 3: existing 3.7c Studio layout system
        layout_html = _try_render_via_studio_layouts(business_id, site_config, opts)
        if layout_html:
            return layout_html

    # Layer 4: legacy 3-vibe-family rendering — terminal safety net.
    return _render_page(business_id, page_type, site_config, opts)


def render_full_site_html(business_id: str, path: str = "/") -> str:
    """Pass 3.8f.2 / 3.8g — render through the full fallback chain.

    Same fallback chain whether served as /preview or as a live URL:
    multi-page (3.8g) → Builder → archetype → Studio → legacy.

    For multi-page sites (site_config.site_type == "multi-page" and
    generated_pages populated) the `path` argument selects which page
    to render. For single-page sites the path is ignored.
    """
    try:
        products = _sb_get(
            f"/products?business_id=eq.{business_id}"
            f"&status=eq.active&display_on_website=eq.true&select=*&limit=20"
        ) or []
        if not products:
            products = _sb_get(
                f"/products?business_id=eq.{business_id}"
                f"&status=eq.active&select=*&limit=20"
            ) or []
    except Exception:
        products = []
    return render_smart_site_page(
        business_id, "home", products=products, path=path,
    )


def render_smart_site_preview(business_id: str, draft_config: Dict[str, Any]) -> str:
    """Render Smart Sites home from a DRAFT config (no persistence).
    Used by MySite.tsx live preview iframe.

    Pass 3.5 Session 3: tries the Studio layout system using the draft
    config's vocabulary_override / layout_id / sections. Falls through
    to legacy preview rendering on any exception.
    """
    merged = _merge_with_defaults(draft_config or {})
    products = _sb_get(
        f"/products?business_id=eq.{business_id}&is_active=eq.true&select=*&limit=6"
    ) or []

    layout_html = _try_render_via_studio_layouts(business_id, merged, {"products": products})
    if layout_html:
        return layout_html

    # Legacy preview path — safety net.
    return _render_page(business_id, "home", merged, {"products": products})


# ─────────────────────────────────────────────────────────────
# Persistence helpers (used by public_site.py endpoints)
# ─────────────────────────────────────────────────────────────


def save_smart_config(business_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    sites = _sb_get(
        f"/business_sites?business_id=eq.{business_id}&select=id,site_config&limit=1"
    ) or []
    if not sites:
        return {"ok": False, "error": "No business_sites row"}
    site_id = sites[0]["id"]
    current = sites[0].get("site_config") or {}
    new_config = {**current, **(body or {})}
    _sb_patch(f"/business_sites?id=eq.{site_id}", {"site_config": new_config})
    return {"ok": True, "site_config": new_config}


def enable_smart_sites(business_id: str) -> Dict[str, Any]:
    sites = _sb_get(
        f"/business_sites?business_id=eq.{business_id}&select=id,site_config&limit=1"
    ) or []
    if not sites:
        return {"ok": False, "error": "No business_sites row"}
    site_id = sites[0]["id"]
    current = sites[0].get("site_config") or {}

    if not current or not current.get("sections"):
        bundle = get_bundle(business_id)
        seeded: Dict[str, Any] = {
            "use_smart_sites": True,
            "vibe_family_override": current.get("vibe_family_override"),
            "sections": {
                "hero": {
                    "enabled": True,
                    "headline": None,
                    "subheadline": (bundle.get("business") or {}).get("tagline"),
                    "cta_label": None,
                    "cta_link": None,
                },
                "about": {
                    "enabled": True,
                    "text": (bundle.get("business") or {}).get("elevator_pitch"),
                },
                "services": {"enabled": True},
                "testimonials": {"enabled": False},
                "gallery": {"enabled": False},
                "resources": {"enabled": False},
            },
            "footer_extra_text": None,
            "custom_domain": current.get("custom_domain"),
        }
        new_config = {**current, **seeded}
    else:
        new_config = {**current, "use_smart_sites": True}

    _sb_patch(f"/business_sites?id=eq.{site_id}", {"site_config": new_config})
    return {"ok": True, "use_smart_sites": True, "site_config": new_config}


def disable_smart_sites(business_id: str) -> Dict[str, Any]:
    sites = _sb_get(
        f"/business_sites?business_id=eq.{business_id}&select=id,site_config&limit=1"
    ) or []
    if not sites:
        return {"ok": False, "error": "No business_sites row"}
    site_id = sites[0]["id"]
    current = sites[0].get("site_config") or {}
    new_config = {**current, "use_smart_sites": False}
    _sb_patch(f"/business_sites?id=eq.{site_id}", {"site_config": new_config})
    return {"ok": True, "use_smart_sites": False}
