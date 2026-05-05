"""Story Arc layout — narrative journey: problem -> journey -> solution -> invitation.
Alternating section backgrounds create visual rhythm.

Vocabulary affinity: reinvention, rising-entrepreneur, wellness-healing,
faith-ministry, organic-natural.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from studio_composite import CompositeDirection
from studio_design_system import DesignSystem, _pick_accent_contrast, _pick_contrast_text
from studio_layouts.shared import (
    render_appendix_sections, render_archetype_touch, render_footer,
    render_head, render_in_the_clear_badge, render_stripe_button, safe_html,
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
    display_font = design_system["font_display"]
    body_font = design_system["font_body"]

    layout_css = f"""
<style>
.story-section {{
  padding: 96px 32px;
}}
.story-section-inner {{
  max-width: 760px;
  margin: 0 auto;
}}
.story-section-alt {{
  background: color-mix(in srgb, {accent} 6%, {bg});
}}
.story-eyebrow {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.7rem;
  letter-spacing: 0.4em;
  text-transform: uppercase;
  color: {accent};
  margin-bottom: 1.2rem;
}}
.story-headline {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(2rem, 5vw, 3.6rem);
  line-height: 1.15;
  font-weight: 700;
  margin: 0 0 1.5rem;
  color: {on_bg};
}}
.story-body {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.15rem;
  line-height: 1.75;
  color: color-mix(in srgb, {on_bg} 80%, transparent);
}}
.story-body p {{ margin: 0 0 1.2rem; }}
.story-cta {{
  display: inline-block;
  margin-top: 2rem;
  padding: 1rem 2.4rem;
  background: {accent};
  color: {on_accent};
  text-decoration: none;
  font-weight: 600;
  border-radius: 999px;
  font-family: '{body_font}', sans-serif;
}}
.story-services {{
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
  margin-top: 2rem;
}}
.story-service-row {{
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: baseline;
  gap: 24px;
  padding: 24px 0;
  border-bottom: 1px solid color-mix(in srgb, {on_bg} 10%, transparent);
}}
.story-service-row h3 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.3rem;
  margin: 0 0 0.4rem;
  color: {on_bg};
}}
.story-service-row p {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.95rem;
  margin: 0;
  color: color-mix(in srgb, {on_bg} 70%, transparent);
}}
.story-price {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.4rem;
  color: {accent};
  font-weight: 700;
}}
@media (max-width: 768px) {{
  .story-section {{ padding: 64px 24px; }}
  .story-service-row {{ grid-template-columns: 1fr; }}
}}
</style>
"""

    hero_config = sections_config.get("hero") or {}
    headline = safe_html(hero_config.get("headline")) or f"What if there was another way?"
    subheadline = safe_html(hero_config.get("subheadline")) or safe_html(business_data.get("tagline") or "")
    cta_label = safe_html(hero_config.get("cta_label")) or "Begin here"
    cta_link = safe_html(hero_config.get("cta_link")) or "#contact"
    badge = render_in_the_clear_badge(bundle, design_system)

    sub_html = f'<p class="story-body"><p>{subheadline}</p></p>' if subheadline else ""
    badge_html = f'<div style="margin-bottom:1rem;">{badge}</div>' if badge else ""

    hero_html = f"""
<section class="story-section">
  <div class="story-section-inner">
    {badge_html}
    <div class="story-eyebrow">The Question</div>
    <h1 class="story-headline">{headline}</h1>
    {sub_html}
  </div>
</section>
"""

    before_about = render_archetype_touch(archetype, "before_about", design_system, bundle)

    practitioner = safe_html((bundle.get("practitioner") or {}).get("display_name") or "the team")
    about_text = safe_html((sections_config.get("about") or {}).get("text")) or safe_html(business_data.get("elevator_pitch") or "")
    about_html = f"""
<section class="story-section story-section-alt">
  <div class="story-section-inner">
    <div class="story-eyebrow">The Journey</div>
    <h2 class="story-headline">How {practitioner} got here</h2>
    <div class="story-body"><p>{about_text}</p></div>
  </div>
</section>
""" if about_text and (sections_config.get("about") or {}).get("enabled", True) else ""

    services_html = ""
    if (sections_config.get("services") or {}).get("enabled", True) and products:
        rows = []
        for p in products[:6]:
            name = safe_html(p.get("name", "Service"))
            desc = safe_html(p.get("description") or "")
            price = p.get("price")
            try:
                price_label = f"${float(price):,.0f}" if price else ""
            except (TypeError, ValueError):
                price_label = ""
            desc_html = f"<p>{desc}</p>" if desc else ""
            price_html = f'<div class="story-price">{price_label}</div>' if price_label else ""
            cta_html = render_stripe_button(p, design_system)
            rows.append(f'<div class="story-service-row"><div><h3>{name}</h3>{desc_html}{cta_html}</div>{price_html}</div>')
        services_html = f"""
<section class="story-section">
  <div class="story-section-inner">
    <div class="story-eyebrow">The Solution</div>
    <h2 class="story-headline">Here's how I help</h2>
    <div class="story-services">{''.join(rows)}</div>
  </div>
</section>
"""

    after_services = render_archetype_touch(archetype, "after_services", design_system, bundle)
    appendix_html = render_appendix_sections(
        design_system, business_data.get("id", "") or "", sections_config, bundle,
    )

    invitation_html = f"""
<section class="story-section story-section-alt">
  <div class="story-section-inner" style="text-align:center;">
    <div class="story-eyebrow">The Invitation</div>
    <h2 class="story-headline">Take the first step.</h2>
    <a href="{cta_link}" class="story-cta">{cta_label}</a>
  </div>
</section>
"""

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
{appendix_html}
{invitation_html}
{footer_html}
</body>
</html>"""
