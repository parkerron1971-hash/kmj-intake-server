"""Gallery layout — image-first masonry. Minimal text, work as hero.

Vocabulary affinity: creative-artist, street-culture, expressive-vibrancy,
maximalist.
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
    on_accent = _pick_accent_contrast(accent)
    on_bg = _pick_contrast_text(bg, dark_color=text)
    display_font = design_system["font_display"]
    body_font = design_system["font_body"]

    layout_css = f"""
<style>
.gal-hero {{
  position: relative;
  height: 80vh;
  background: linear-gradient(135deg, {bg}, color-mix(in srgb, {accent} 30%, {bg}));
  display: flex;
  align-items: flex-end;
  padding: 64px;
}}
.gal-hero-text {{ position: relative; z-index: 1; max-width: 800px; }}
.gal-headline {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(2.5rem, 7vw, 5.5rem);
  line-height: 1;
  font-weight: 700;
  margin: 0 0 1rem;
  color: {on_bg};
}}
.gal-subhead {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.05rem;
  line-height: 1.6;
  max-width: 520px;
  color: color-mix(in srgb, {on_bg} 75%, transparent);
}}
.gal-grid-section {{
  padding: 64px 32px;
  max-width: 1400px;
  margin: 0 auto;
}}
.gal-masonry {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  grid-auto-rows: 280px;
  grid-auto-flow: dense;
  gap: 16px;
}}
.gal-tile {{
  background: linear-gradient(135deg, color-mix(in srgb, {accent} 15%, transparent), color-mix(in srgb, {accent} 30%, transparent));
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding: 24px;
  color: {on_bg};
  text-decoration: none;
  position: relative;
  overflow: hidden;
  transition: transform 0.3s ease;
}}
.gal-tile:hover {{ transform: scale(1.01); }}
.gal-tile-tall {{ grid-row: span 2; }}
.gal-tile-wide {{ grid-column: span 2; }}
.gal-tile h3 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.3rem;
  margin: 0 0 0.4rem;
  color: {on_bg};
}}
.gal-tile p {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.85rem;
  margin: 0;
  color: color-mix(in srgb, {on_bg} 70%, transparent);
}}
.gal-tile-price {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.4rem;
  font-weight: 700;
  color: {accent};
  margin-top: 0.5rem;
}}
.gal-about {{
  max-width: 720px;
  margin: 80px auto;
  padding: 0 32px;
  text-align: center;
}}
.gal-about p {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.1rem;
  line-height: 1.7;
  color: color-mix(in srgb, {on_bg} 80%, transparent);
}}
.gal-cta {{
  display: inline-block;
  margin-top: 1.5rem;
  padding: 0.9rem 2.4rem;
  background: {accent};
  color: {on_accent};
  text-decoration: none;
  font-weight: 600;
  font-family: '{body_font}', sans-serif;
  border-radius: 4px;
}}
@media (max-width: 768px) {{
  .gal-hero {{ padding: 32px 24px; height: 60vh; }}
  .gal-grid-section {{ padding: 48px 16px; }}
  .gal-masonry {{ grid-template-columns: 1fr; grid-auto-rows: 220px; }}
  .gal-tile-wide {{ grid-column: span 1; }}
}}
</style>
"""

    hero_config = sections_config.get("hero") or {}
    headline = safe_html(hero_config.get("headline")) or safe_html(business_name)
    subheadline = safe_html(hero_config.get("subheadline")) or safe_html(business_data.get("tagline") or "")
    cta_label = safe_html(hero_config.get("cta_label")) or "View work"
    cta_link = safe_html(hero_config.get("cta_link")) or "#work"
    badge = render_in_the_clear_badge(bundle, design_system)

    sub_html = f'<p class="gal-subhead">{subheadline}</p>' if subheadline else ""
    badge_html = f'<div style="margin-bottom:1.5rem;">{badge}</div>' if badge else ""
    hero_html = f"""
<section class="gal-hero">
  <div class="gal-hero-text">
    {badge_html}
    <h1 class="gal-headline">{headline}</h1>
    {sub_html}
  </div>
</section>
"""

    services_html = ""
    services_config = sections_config.get("services") or {}
    if services_config.get("enabled", True) and products:
        tiles = []
        for i, p in enumerate(products[:9]):
            name = safe_html(p.get("name", "Work"))
            desc = safe_html(p.get("description") or "")
            price = p.get("price")
            try:
                price_label = f"${float(price):,.0f}" if price else ""
            except (TypeError, ValueError):
                price_label = ""
            tile_class = "gal-tile"
            if i % 5 == 0:
                tile_class += " gal-tile-tall"
            elif i % 4 == 3:
                tile_class += " gal-tile-wide"
            price_html = f'<div class="gal-tile-price">{price_label}</div>' if price_label else ""
            desc_html = f"<p>{desc}</p>" if desc else ""
            tiles.append(f'<a href="#work-{i}" class="{tile_class}" id="work"><h3>{name}</h3>{desc_html}{price_html}</a>')
        services_html = f"""
<section class="gal-grid-section">
  <div class="gal-masonry">{''.join(tiles)}</div>
</section>
"""

    before_about = render_archetype_touch(archetype, "before_about", design_system, bundle)

    about_html = ""
    about_config = sections_config.get("about") or {}
    if about_config.get("enabled", True):
        about_text = safe_html(about_config.get("text")) or safe_html(business_data.get("elevator_pitch") or "")
        if about_text:
            about_html = f"""
<section class="gal-about">
  <p>{about_text}</p>
  <a href="{cta_link}" class="gal-cta">{cta_label}</a>
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
{services_html}
{before_about}
{about_html}
{after_services}
{footer_html}
</body>
</html>"""
