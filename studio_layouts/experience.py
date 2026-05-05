"""Experience layout — immersive cinematic. Full-screen sections, one idea
per section, dramatic typography, scroll-driven feel.

Vocabulary affinity: futurist-tech, cultural-fusion, maximalist,
street-culture, creative-artist.
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
.exp-fullscreen {{
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px 32px;
  text-align: center;
  position: relative;
}}
.exp-hero {{
  background: radial-gradient(ellipse at center, color-mix(in srgb, {accent} 25%, {bg}), {bg} 70%);
}}
.exp-section-alt {{
  background: color-mix(in srgb, {accent} 8%, {bg});
}}
.exp-tagline {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.85rem;
  letter-spacing: 0.5em;
  text-transform: uppercase;
  color: {accent};
  margin-bottom: 2rem;
}}
.exp-headline {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(3rem, 10vw, 8rem);
  line-height: 0.95;
  font-weight: 800;
  margin: 0 0 1.5rem;
  letter-spacing: -0.03em;
  color: {on_bg};
  max-width: 1100px;
}}
.exp-subhead {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.3rem;
  line-height: 1.5;
  max-width: 640px;
  color: color-mix(in srgb, {on_bg} 75%, transparent);
}}
.exp-cta {{
  display: inline-block;
  margin-top: 3rem;
  padding: 1.2rem 3.2rem;
  background: {accent};
  color: {on_accent};
  text-decoration: none;
  font-weight: 700;
  font-size: 0.95rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  font-family: '{body_font}', sans-serif;
  border-radius: 4px;
}}
.exp-statement {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(2rem, 5vw, 3.5rem);
  line-height: 1.3;
  font-weight: 600;
  max-width: 880px;
  color: {on_bg};
  margin: 0;
}}
.exp-services-cinema {{
  display: grid;
  grid-template-columns: 1fr;
  gap: 0;
}}
.exp-service-row {{
  min-height: 60vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 32px;
  text-align: center;
  border-top: 1px solid color-mix(in srgb, {on_bg} 10%, transparent);
}}
.exp-service-row:nth-child(even) {{
  background: color-mix(in srgb, {accent} 5%, {bg});
}}
.exp-service-row h3 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(1.8rem, 4vw, 2.8rem);
  margin: 0 0 1rem;
  color: {on_bg};
  font-weight: 700;
}}
.exp-service-row p {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.1rem;
  line-height: 1.6;
  max-width: 600px;
  color: color-mix(in srgb, {on_bg} 75%, transparent);
}}
.exp-price {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.6rem;
  color: {accent};
  font-weight: 700;
  margin-top: 1rem;
}}
@media (max-width: 768px) {{
  .exp-fullscreen {{ padding: 48px 20px; min-height: 80vh; }}
  .exp-service-row {{ padding: 60px 24px; min-height: 50vh; }}
}}
</style>
"""

    hero_config = sections_config.get("hero") or {}
    headline = safe_html(hero_config.get("headline")) or safe_html(business_name)
    subheadline = safe_html(hero_config.get("subheadline")) or safe_html(business_data.get("tagline") or "")
    cta_label = safe_html(hero_config.get("cta_label")) or "Enter"
    cta_link = safe_html(hero_config.get("cta_link")) or "#contact"
    badge = render_in_the_clear_badge(bundle, design_system)

    sub_html = f'<p class="exp-subhead">{subheadline}</p>' if subheadline else ""
    badge_html = f'<div style="margin-bottom:1.5rem;">{badge}</div>' if badge else ""
    hero_html = f"""
<section class="exp-fullscreen exp-hero">
  {badge_html}
  <div class="exp-tagline">{safe_html(business_data.get("type", "")).replace("_", " ").upper()}</div>
  <h1 class="exp-headline">{headline}</h1>
  {sub_html}
  <a href="{cta_link}" class="exp-cta">{cta_label}</a>
</section>
"""

    before_about = render_archetype_touch(archetype, "before_about", design_system, bundle)

    about_html = ""
    about_config = sections_config.get("about") or {}
    if about_config.get("enabled", True):
        about_text = safe_html(about_config.get("text")) or safe_html(business_data.get("elevator_pitch") or "")
        if about_text:
            about_html = f"""
<section class="exp-fullscreen exp-section-alt">
  <p class="exp-statement">{about_text}</p>
</section>
"""

    services_html = ""
    services_config = sections_config.get("services") or {}
    if services_config.get("enabled", True) and products:
        rows = []
        for p in products[:4]:
            name = safe_html(p.get("name", "Service"))
            desc = safe_html(p.get("description") or "")
            price = p.get("price")
            try:
                price_label = f"${float(price):,.0f}" if price else ""
            except (TypeError, ValueError):
                price_label = ""
            desc_html = f"<p>{desc}</p>" if desc else ""
            price_html = f'<div class="exp-price">{price_label}</div>' if price_label else ""
            rows.append(f'<div class="exp-service-row"><h3>{name}</h3>{desc_html}{price_html}</div>')
        services_html = f'<div class="exp-services-cinema">{"".join(rows)}</div>'

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
