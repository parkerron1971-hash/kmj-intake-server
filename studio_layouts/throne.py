"""Throne layout — dark commanding authority. Gold accents, rectangular
geometry, generous vertical padding, all-caps section labels.

Vocabulary affinity: sovereign-authority, universal-premium, legacy-builder,
diaspora-modern, established-authority.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from studio_composite import CompositeDirection
from studio_design_system import DesignSystem, _pick_accent_contrast, _pick_contrast_text
from studio_layouts.shared import (
    render_appendix_sections, render_archetype_touch, render_footer,
    render_head, render_in_the_clear_badge, render_stripe_button, safe_html, render_motion_script,
)
from studio_decoration import render_decoration_for


def render(
    business_data: Dict[str, Any],
    design_system: DesignSystem,
    composite: CompositeDirection,
    sections_config: Dict[str, Any],
    bundle: Dict[str, Any],
    head_meta_extra: str = "",
    products: Optional[List[Dict[str, Any]]] = None,
) -> str:
    products = products or []
    business_name = business_data.get("name") or "Welcome"
    archetype = business_data.get("type") or "custom"
    vocab_id = ((composite or {}).get("primary_vocabulary") or {}).get("id")
    section_break = render_decoration_for(vocab_id, design_system, "section_break")

    # Pass 3.7b — vocab-eyebrow text (letter-spacing: 0.3em)
    try:
        from studio_layouts.sections.typography import render_eyebrow
        eyebrow_html = render_eyebrow(safe_html(business_data.get("type", "")).replace("_", " ").upper() or "STUDIO", design_system, vocab_id)
    except Exception:
        eyebrow_html = ""

    # Pass 3.7b — hero gradient + corner ornaments
    try:
        from studio_decoration import get_gradient_for_section, render_decorative_corners
        hero_gradient = get_gradient_for_section(vocab_id, design_system, "hero")
    except Exception:
        hero_gradient = design_system.get("palette_bg") or "#0f0f1a"
    try:
        hero_corners = render_decorative_corners(vocab_id, design_system)
    except Exception:
        hero_corners = ""

    bg = design_system["palette_bg"]
    accent = design_system["palette_accent"]
    text = design_system["palette_text"]
    on_accent = _pick_accent_contrast(accent)
    on_bg = _pick_contrast_text(bg, dark_color=text)
    display_font = design_system["font_display"]
    body_font = design_system["font_body"]

    layout_css = f"""
<style>
.thrn-hero {{
  position: relative;
  min-height: 90vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 96px 32px;
  text-align: center;
  background: {hero_gradient};
  border-bottom: 1px solid color-mix(in srgb, {accent} 30%, transparent);
}}
.thrn-eyebrow {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.7rem;
  letter-spacing: 0.4em;
  text-transform: uppercase;
  color: {accent};
  margin-bottom: 2rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid {accent};
}}
.thrn-headline {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(2.5rem, 6vw, 5rem);
  font-weight: 800;
  line-height: 1.05;
  letter-spacing: -0.01em;
  margin: 0 0 1.5rem;
  color: {on_bg};
  max-width: 900px;
}}
.thrn-subhead {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.1rem;
  line-height: 1.6;
  max-width: 640px;
  color: color-mix(in srgb, {on_bg} 75%, transparent);
}}
.thrn-cta {{
  display: inline-block;
  margin-top: 3rem;
  padding: 1.1rem 3rem;
  background: {accent};
  color: {on_accent};
  text-decoration: none;
  font-weight: 700;
  font-size: 0.85rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  border-radius: 0;
  font-family: '{body_font}', sans-serif;
}}
.thrn-section {{
  max-width: 1100px;
  margin: 0 auto;
  padding: 128px 48px;
  background: {bg};
}}
.thrn-section-label {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.75rem;
  letter-spacing: 0.4em;
  text-transform: uppercase;
  color: {accent};
  margin-bottom: 2rem;
  border-bottom: 1px solid {accent};
  padding-bottom: 1rem;
  display: inline-block;
}}
.thrn-about-body {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.2rem;
  line-height: 1.8;
  max-width: 720px;
  color: color-mix(in srgb, {on_bg} 85%, transparent);
}}
.thrn-services-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 2px;
  background: color-mix(in srgb, {accent} 30%, transparent);
  border: 1px solid {accent};
  margin-top: 2rem;
}}
.thrn-service-card {{
  padding: 40px 32px;
  background: {bg};
  transition: background 0.3s ease;
}}
.thrn-service-card:hover {{
  background: color-mix(in srgb, {accent} 6%, {bg});
}}
.thrn-service-card h3 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.4rem;
  margin: 0 0 0.75rem;
  color: {on_bg};
  letter-spacing: 0.02em;
}}
.thrn-service-card p {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.95rem;
  line-height: 1.6;
  color: color-mix(in srgb, {on_bg} 70%, transparent);
}}
.thrn-price {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.6rem;
  color: {accent};
  margin-top: 1.5rem;
  font-weight: 700;
}}
@media (max-width: 768px) {{
  .thrn-hero {{ padding: 64px 24px; min-height: 70vh; }}
  .thrn-section {{ padding: 80px 24px; }}
  .thrn-services-grid {{ grid-template-columns: 1fr; }}
}}
</style>
"""

    hero_config = sections_config.get("hero") or {}
    headline = safe_html(hero_config.get("headline")) or safe_html(business_name)
    subheadline = safe_html(hero_config.get("subheadline")) or safe_html(business_data.get("tagline") or "")
    cta_label = safe_html(hero_config.get("cta_label")) or "Begin the conversation"
    cta_link = safe_html(hero_config.get("cta_link")) or "#contact"
    badge = render_in_the_clear_badge(bundle, design_system)
    eyebrow_text = safe_html(business_data.get("type", "")).replace("_", " ").upper() or "AUTHORITY"

    sub_html = f'<p class="thrn-subhead">{subheadline}</p>' if subheadline else ""
    badge_html = f'<div style="margin-bottom:1.5rem;">{badge}</div>' if badge else ""
    hero_html = f"""
<section class="thrn-hero reveal">
  {hero_corners}
  {badge_html}
  <div class="thrn-eyebrow">{eyebrow_text}</div>
  <h1 class="thrn-headline">{headline}</h1>
  {sub_html}
  <a href="{cta_link}" class="thrn-cta">{cta_label}</a>
</section>
"""

    before_about = render_archetype_touch(archetype, "before_about", design_system, bundle)

    about_html = ""
    about_config = sections_config.get("about") or {}
    if about_config.get("enabled", True):
        about_raw = (about_config.get("text") or "") or (business_data.get("elevator_pitch") or "")
        if about_raw:
            try:
                from studio_layouts.sections.typography import render_drop_cap_paragraph
                about_para_html = render_drop_cap_paragraph(about_raw, design_system, vocab_id)
            except Exception:
                about_para_html = f'<p>{safe_html(about_raw)}</p>'
            about_html = f"""
<section class="thrn-section reveal">
  <div class="thrn-section-label">About</div>
  <div class="thrn-about-body">{about_para_html}</div>
</section>
"""

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
            price_html = f'<div class="thrn-price">{price_label}</div>' if price_label else ""
            cta_html = render_stripe_button(p, design_system)
            cards.append(f'<div class="thrn-service-card"><h3>{name}</h3>{desc_html}{price_html}{cta_html}</div>')
        services_html = f"""
<section class="thrn-section reveal">
  <div class="thrn-section-label">Engagements</div>
  <div class="thrn-services-grid">{''.join(cards)}</div>
</section>
"""

    after_services = render_archetype_touch(archetype, "after_services", design_system, bundle)
    appendix_html = render_appendix_sections(
        design_system, business_data.get("id", "") or "", sections_config, bundle,
    )
    footer_html = render_footer(business_data, bundle, design_system, sections_config.get("footer_extra_text"))
    head = render_head(business_name, design_system, head_meta_extra)
    return f"""<!DOCTYPE html>
<html lang="en">
{head}
{layout_css}
<body style="background:{bg};color:{on_bg};margin:0;">
{hero_html}
<div style="max-width:1100px;margin:0 auto;padding:24px 24px 0;text-align:center;">{eyebrow_html}</div>
{before_about}
{about_html}
{services_html}
{section_break}
{after_services}
{appendix_html}
{footer_html}
{render_motion_script()}
</body>
</html>"""
