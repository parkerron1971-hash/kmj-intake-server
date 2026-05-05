"""Magazine layout — full-bleed editorial, large typography, asymmetric grid.

This is the REFERENCE layout. The other 11 layouts adopt this module's
render() signature exactly and follow the same composition pattern:
  1. layout_css block tailored to this layout's character
  2. hero section (layout-specific structure)
  3. archetype touch (before_about position)
  4. about section
  5. services / products section
  6. archetype touch (after_services position)
  7. footer (shared)

Vocabulary affinity: editorial, expressive-vibrancy, diaspora-modern,
universal-premium, creative-artist.

Section order from layoutLibrary.ts:
  ['nav', 'hero-full-bleed', 'statement-section', 'services-editorial',
   'image-feature', 'testimonial-pull-quote', 'cta-full-width', 'footer']
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from studio_composite import CompositeDirection
from studio_design_system import DesignSystem, _pick_accent_contrast
from studio_layouts.shared import (
    render_archetype_touch,
    render_footer,
    render_head,
    render_in_the_clear_badge,
    safe_html,
)


def render(
    business_data: Dict[str, Any],
    design_system: DesignSystem,
    composite: CompositeDirection,
    sections_config: Dict[str, Any],
    bundle: Dict[str, Any],
    head_meta_extra: str = "",
    products: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Render a complete magazine-layout HTML page.

    Args:
        business_data: dict with at least 'name', plus optional 'type',
            'tagline', 'elevator_pitch'
        design_system: from studio_design_system.build_design_system
        composite: from studio_composite.build_composite
        sections_config: { hero: {...}, about: {...}, services: {...}, ...}
        bundle: brand_engine bundle (for legal.in_the_clear, footer.*)
        head_meta_extra: optional extra <head> HTML (favicon/social card)
        products: list of product dicts for the services section
    """
    products = products or []
    business_name = business_data.get("name") or "Welcome"
    archetype = business_data.get("type") or "custom"

    # ─── Tokens for f-string interpolation ──────────────────────────
    palette_bg = design_system["palette_bg"]
    palette_accent = design_system["palette_accent"]
    palette_text = design_system["palette_text"]
    palette_muted = design_system["palette_muted"]
    text_on_accent = _pick_accent_contrast(palette_accent)
    display_font = design_system["font_display"]
    body_font = design_system["font_body"]

    # ─── Layout-specific CSS ────────────────────────────────────────
    layout_css = f"""
<style>
.mag-hero {{
  min-height: 80vh;
  display: grid;
  grid-template-columns: 1fr 1fr;
  align-items: end;
  padding: 48px 64px 80px;
  position: relative;
  overflow: hidden;
}}
.mag-hero::before {{
  content: "";
  position: absolute;
  top: 0; right: 0;
  width: 60%; height: 100%;
  background: linear-gradient(135deg, color-mix(in srgb, {palette_accent} 30%, transparent), transparent);
  z-index: 0;
}}
.mag-hero-content {{ position: relative; z-index: 1; max-width: 700px; }}
.mag-eyebrow {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.75rem;
  letter-spacing: 0.3em;
  text-transform: uppercase;
  color: {palette_accent};
  margin-bottom: 1.5rem;
}}
.mag-headline {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(3rem, 8vw, 6.5rem);
  line-height: 0.95;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin: 0 0 1.5rem;
  color: {palette_text};
}}
.mag-subhead {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.25rem;
  max-width: 540px;
  line-height: 1.6;
  color: color-mix(in srgb, {palette_text} 75%, transparent);
}}
.mag-cta {{
  display: inline-block;
  margin-top: 2rem;
  padding: 1rem 2.5rem;
  background: {palette_accent};
  color: {text_on_accent};
  text-decoration: none;
  font-weight: 600;
  letter-spacing: 0.05em;
  border-radius: 0;
  font-family: '{body_font}', sans-serif;
}}
.mag-section {{
  max-width: 1200px;
  margin: 0 auto;
  padding: 96px 48px;
}}
.mag-about {{
  display: grid;
  grid-template-columns: 1fr 1.5fr;
  gap: 64px;
  align-items: start;
}}
.mag-about-label {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.7rem;
  letter-spacing: 0.3em;
  text-transform: uppercase;
  color: {palette_accent};
  border-top: 2px solid {palette_accent};
  padding-top: 1rem;
}}
.mag-about-body {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.15rem;
  line-height: 1.7;
  color: {palette_text};
}}
.mag-services-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 32px;
  margin-top: 3rem;
}}
.mag-service-card {{
  border: 1px solid color-mix(in srgb, {palette_text} 12%, transparent);
  padding: 32px;
  position: relative;
  background: color-mix(in srgb, {palette_bg} 92%, white);
}}
.mag-service-card h3 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.5rem;
  margin: 0 0 1rem;
  color: {palette_text};
}}
.mag-service-card p {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.95rem;
  line-height: 1.6;
  color: color-mix(in srgb, {palette_text} 75%, transparent);
}}
.mag-price {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 2rem;
  color: {palette_accent};
  margin-top: 1.5rem;
  font-weight: 700;
}}
@media (max-width: 768px) {{
  .mag-hero {{ grid-template-columns: 1fr; padding: 32px 24px 64px; min-height: 60vh; }}
  .mag-section {{ padding: 64px 24px; }}
  .mag-about {{ grid-template-columns: 1fr; gap: 24px; }}
  .mag-services-grid {{ grid-template-columns: 1fr; gap: 16px; }}
}}
</style>
"""

    # ─── Hero ───────────────────────────────────────────────────────
    hero_config = sections_config.get("hero") or {}
    headline = safe_html(hero_config.get("headline")) or safe_html(business_name)
    subheadline = safe_html(hero_config.get("subheadline")) or safe_html(
        business_data.get("tagline") or ""
    )
    cta_label = safe_html(hero_config.get("cta_label")) or "Get in touch"
    cta_link = safe_html(hero_config.get("cta_link")) or "#contact"
    badge = render_in_the_clear_badge(bundle, design_system)
    eyebrow_text = safe_html(business_data.get("type", "")).replace("_", " ").title() or "Studio"

    sub_html = f'<p class="mag-subhead">{subheadline}</p>' if subheadline else ""
    badge_html = f'<div style="margin-bottom:1rem;">{badge}</div>' if badge else ""
    hero_html = f"""
<section class="mag-hero">
  <div class="mag-hero-content">
    {badge_html}
    <div class="mag-eyebrow">{eyebrow_text}</div>
    <h1 class="mag-headline">{headline}</h1>
    {sub_html}
    <a href="{cta_link}" class="mag-cta">{cta_label}</a>
  </div>
</section>
"""

    # ─── Archetype touch (before about) ─────────────────────────────
    before_about = render_archetype_touch(archetype, "before_about", design_system, bundle)

    # ─── About ──────────────────────────────────────────────────────
    about_html = ""
    about_config = sections_config.get("about") or {}
    if about_config.get("enabled", True):
        about_text = safe_html(about_config.get("text")) or safe_html(
            business_data.get("elevator_pitch") or ""
        )
        if about_text:
            about_html = f"""
<section class="mag-section mag-about">
  <div>
    <div class="mag-about-label">About</div>
  </div>
  <div class="mag-about-body">
    <p>{about_text}</p>
  </div>
</section>
"""

    # ─── Services ───────────────────────────────────────────────────
    services_html = ""
    services_config = sections_config.get("services") or {}
    if services_config.get("enabled", True) and products:
        cards = []
        for p in products[:6]:
            name = safe_html(p.get("name", "Service"))
            desc = safe_html(p.get("description") or "")
            price = p.get("price")
            try:
                price_label = f"${float(price):,.0f}" if price else ""
            except (TypeError, ValueError):
                price_label = ""
            desc_html = f"<p>{desc}</p>" if desc else ""
            price_html = f'<div class="mag-price">{price_label}</div>' if price_label else ""
            cards.append(
                f'<div class="mag-service-card"><h3>{name}</h3>{desc_html}{price_html}</div>'
            )
        services_html = f"""
<section class="mag-section">
  <div class="mag-about-label">Services</div>
  <div class="mag-services-grid">{''.join(cards)}</div>
</section>
"""

    # ─── Archetype touch (after services) ───────────────────────────
    after_services = render_archetype_touch(archetype, "after_services", design_system, bundle)

    # ─── Footer ─────────────────────────────────────────────────────
    footer_html = render_footer(
        business_data, bundle, design_system,
        sections_config.get("footer_extra_text"),
    )

    # ─── Compose ────────────────────────────────────────────────────
    head = render_head(business_name, design_system, head_meta_extra)
    return f"""<!DOCTYPE html>
<html lang="en">
{head}
{layout_css}
<body style="background:{palette_bg};color:{palette_text};margin:0;">
{hero_html}
{before_about}
{about_html}
{services_html}
{after_services}
{footer_html}
</body>
</html>"""
