"""Clean Launch layout — single focused message, minimal elements,
maximum white space. Conversion through clarity.

Vocabulary affinity: minimalist, universal-premium, rising-entrepreneur,
futurist-tech, asian-excellence.
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

    bg = design_system["palette_bg"]
    accent = design_system["palette_accent"]
    text = design_system["palette_text"]
    on_accent = _pick_accent_contrast(accent)
    on_bg = _pick_contrast_text(bg, dark_color=text)
    display_font = design_system["font_display"]
    body_font = design_system["font_body"]

    layout_css = f"""
<style>
.cl-hero {{
  min-height: 80vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 96px 48px;
  text-align: center;
}}
.cl-headline {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(2.4rem, 5vw, 4rem);
  line-height: 1.1;
  font-weight: 600;
  margin: 0 0 1.5rem;
  max-width: 720px;
  color: {on_bg};
}}
.cl-subhead {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.15rem;
  line-height: 1.6;
  max-width: 540px;
  margin: 0 0 3rem;
  color: color-mix(in srgb, {on_bg} 70%, transparent);
}}
.cl-cta {{
  display: inline-block;
  padding: 1rem 2.4rem;
  background: {accent};
  color: {on_accent};
  text-decoration: none;
  font-weight: 600;
  font-family: '{body_font}', sans-serif;
  border-radius: 4px;
}}
.cl-divider {{
  width: 40px;
  height: 1px;
  background: {accent};
  margin: 3rem auto;
}}
.cl-section {{
  max-width: 640px;
  margin: 0 auto;
  padding: 80px 48px;
  text-align: center;
}}
.cl-section h2 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.8rem;
  font-weight: 600;
  margin: 0 0 1.25rem;
  color: {on_bg};
}}
.cl-section p {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.05rem;
  line-height: 1.7;
  color: color-mix(in srgb, {on_bg} 75%, transparent);
}}
.cl-services-list {{
  list-style: none;
  padding: 0;
  margin: 2rem 0 0;
  font-family: '{body_font}', sans-serif;
  font-size: 1rem;
  line-height: 2;
  color: color-mix(in srgb, {on_bg} 80%, transparent);
}}
.cl-services-list li {{
  border-bottom: 1px solid color-mix(in srgb, {on_bg} 10%, transparent);
  padding: 16px 0;
}}
.cl-services-list .name {{ font-weight: 600; color: {on_bg}; }}
.cl-services-list .price {{ float: right; color: {accent}; font-weight: 600; }}
@media (max-width: 768px) {{
  .cl-hero {{ padding: 64px 24px; min-height: 70vh; }}
  .cl-section {{ padding: 56px 24px; }}
}}
</style>
"""

    hero_config = sections_config.get("hero") or {}
    headline = safe_html(hero_config.get("headline")) or safe_html(business_data.get("tagline") or business_name)
    subheadline = safe_html(hero_config.get("subheadline")) or safe_html(business_data.get("elevator_pitch") or "")
    cta_label = safe_html(hero_config.get("cta_label")) or "Get started"
    cta_link = safe_html(hero_config.get("cta_link")) or "#contact"
    badge = render_in_the_clear_badge(bundle, design_system)

    sub_html = f'<p class="cl-subhead">{subheadline}</p>' if subheadline else ""
    badge_html = f'<div style="margin-bottom:1rem;">{badge}</div>' if badge else ""
    hero_html = f"""
<section class="cl-hero reveal">
  {badge_html}
  <h1 class="cl-headline">{headline}</h1>
  {sub_html}
  <a href="{cta_link}" class="cl-cta">{cta_label}</a>
</section>
"""

    before_about = render_archetype_touch(archetype, "before_about", design_system, bundle)

    services_html = ""
    services_config = sections_config.get("services") or {}
    if services_config.get("enabled", True) and products:
        items = []
        for p in products[:6]:
            name = safe_html(p.get("name", "Service"))
            price = p.get("price")
            try:
                price_label = f"${float(price):,.0f}" if price else ""
            except (TypeError, ValueError):
                price_label = ""
            price_html = f'<span class="price">{price_label}</span>' if price_label else ""
            cta_html = render_stripe_button(p, design_system)
            cta_inline = f' &middot; {cta_html}' if cta_html else ''
            items.append(f'<li><span class="name">{name}</span>{price_html}{cta_inline}</li>')
        services_html = f"""
<div class="cl-divider"></div>
<section class="cl-section reveal">
  <h2>Offerings</h2>
  <ul class="cl-services-list">{''.join(items)}</ul>
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
{before_about}
{services_html}
{section_break}
{after_services}
{appendix_html}
{footer_html}
{render_motion_script()}
</body>
</html>"""
