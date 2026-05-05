"""Celebration layout — colorful, joyful, layered. Vibrant gradients,
bright cards, decorative section dividers.

Vocabulary affinity: expressive-vibrancy, warm-community, organic-natural,
maximalist, cultural-fusion.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from studio_composite import CompositeDirection
from studio_design_system import DesignSystem, _pick_accent_contrast, _pick_contrast_text
from studio_layouts.shared import (
    render_archetype_touch, render_footer, render_head,
    render_in_the_clear_badge, safe_html,
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
    products = products or []
    business_name = business_data.get("name") or "Welcome"
    archetype = business_data.get("type") or "custom"

    bg = design_system["palette_bg"]
    accent = design_system["palette_accent"]
    text = design_system["palette_text"]
    surface = design_system["palette_surface"]
    on_accent = _pick_accent_contrast(accent)
    on_bg = _pick_contrast_text(bg, dark_color=text)
    on_surface = _pick_contrast_text(surface, dark_color=text)
    display_font = design_system["font_display"]
    body_font = design_system["font_body"]

    layout_css = f"""
<style>
.cel-hero {{
  padding: 96px 32px;
  text-align: center;
  background:
    radial-gradient(circle at 20% 30%, color-mix(in srgb, {accent} 30%, transparent), transparent 50%),
    radial-gradient(circle at 80% 70%, color-mix(in srgb, {surface} 30%, transparent), transparent 50%),
    {bg};
}}
.cel-headline {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(2.6rem, 7vw, 5rem);
  line-height: 1.05;
  font-weight: 800;
  margin: 0 0 1.5rem;
  color: {on_bg};
  max-width: 920px;
  margin-left: auto;
  margin-right: auto;
}}
.cel-subhead {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.2rem;
  line-height: 1.6;
  max-width: 600px;
  margin: 0 auto 2.5rem;
  color: color-mix(in srgb, {on_bg} 80%, transparent);
}}
.cel-cta {{
  display: inline-block;
  padding: 1.1rem 2.8rem;
  background: linear-gradient(135deg, {accent}, color-mix(in srgb, {accent} 70%, {surface}));
  color: {on_accent};
  text-decoration: none;
  font-weight: 700;
  font-family: '{body_font}', sans-serif;
  border-radius: 999px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12);
}}
.cel-section {{
  max-width: 1100px;
  margin: 0 auto;
  padding: 80px 32px;
}}
.cel-section h2 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 2.4rem;
  font-weight: 800;
  margin: 0 0 1.5rem;
  text-align: center;
  color: {on_bg};
}}
.cel-divider {{
  height: 4px;
  background: linear-gradient(90deg, transparent, {accent}, {surface}, {accent}, transparent);
  margin: 0;
}}
.cel-services-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 24px;
  margin-top: 2rem;
}}
.cel-service-card {{
  padding: 32px;
  background: linear-gradient(135deg, color-mix(in srgb, {accent} 12%, white), color-mix(in srgb, {surface} 12%, white));
  border-radius: 20px;
  color: #1A1A1A;
  transition: transform 0.2s ease;
}}
.cel-service-card:hover {{ transform: translateY(-6px) rotate(-0.5deg); }}
.cel-service-card h3 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.4rem;
  margin: 0 0 0.75rem;
  color: #1A1A1A;
}}
.cel-service-card p {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.95rem;
  line-height: 1.6;
  color: rgba(0,0,0,0.7);
}}
.cel-price {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.4rem;
  color: {accent};
  font-weight: 800;
  margin-top: 1rem;
}}
.cel-about {{ text-align: center; }}
.cel-about p {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.15rem;
  line-height: 1.7;
  max-width: 700px;
  margin: 0 auto;
  color: color-mix(in srgb, {on_bg} 80%, transparent);
}}
@media (max-width: 768px) {{
  .cel-hero {{ padding: 64px 20px; }}
  .cel-section {{ padding: 56px 20px; }}
}}
</style>
"""

    hero_config = sections_config.get("hero") or {}
    headline = safe_html(hero_config.get("headline")) or safe_html(business_name)
    subheadline = safe_html(hero_config.get("subheadline")) or safe_html(business_data.get("tagline") or "")
    cta_label = safe_html(hero_config.get("cta_label")) or "Come celebrate"
    cta_link = safe_html(hero_config.get("cta_link")) or "#contact"
    badge = render_in_the_clear_badge(bundle, design_system)

    sub_html = f'<p class="cel-subhead">{subheadline}</p>' if subheadline else ""
    badge_html = f'<div style="margin-bottom:1.5rem;">{badge}</div>' if badge else ""
    hero_html = f"""
<section class="cel-hero">
  {badge_html}
  <h1 class="cel-headline">{headline}</h1>
  {sub_html}
  <a href="{cta_link}" class="cel-cta">{cta_label}</a>
</section>
<div class="cel-divider"></div>
"""

    before_about = render_archetype_touch(archetype, "before_about", design_system, bundle)

    about_html = ""
    about_config = sections_config.get("about") or {}
    if about_config.get("enabled", True):
        about_text = safe_html(about_config.get("text")) or safe_html(business_data.get("elevator_pitch") or "")
        if about_text:
            about_html = f"""
<section class="cel-section cel-about">
  <h2>What we're about</h2>
  <p>{about_text}</p>
</section>
<div class="cel-divider"></div>
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
            price_html = f'<div class="cel-price">{price_label}</div>' if price_label else ""
            cards.append(f'<div class="cel-service-card"><h3>{name}</h3>{desc_html}{price_html}</div>')
        services_html = f"""
<section class="cel-section">
  <h2>Join us</h2>
  <div class="cel-services-grid">{''.join(cards)}</div>
</section>
"""

    after_services = render_archetype_touch(archetype, "after_services", design_system, bundle)
    footer_html = render_footer(business_data, bundle, design_system, sections_config.get("footer_extra_text"))
    head = render_head(business_name, design_system, head_meta_extra)
    return f"""<!DOCTYPE html>
<html lang="en">
{head}
{layout_css}
<body style="background:{bg};color:{on_bg};margin:0;">
{hero_html}
{before_about}
{about_html}
{services_html}
{after_services}
{footer_html}
</body>
</html>"""
