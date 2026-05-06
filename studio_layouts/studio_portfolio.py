"""Studio Portfolio layout — split hero, marquee ticker, masonry portfolio,
portrait service cards. Creative brand led by proof.

Vocabulary affinity: creative-artist, expressive-vibrancy, rising-entrepreneur,
editorial.
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


def _bespoke_gallery(design_system, items, section_config, bundle, vocab_id=None):
    """Pass 3.6: bespoke studio-portfolio gallery — true masonry via
    column-fill so portfolio pieces have varied heights, photo-first
    treatment, minimal captions overlaid on hover."""
    if not items:
        return ""
    text = design_system["palette_text"]
    accent = design_system["palette_accent"]
    display_font = design_system["font_display"]

    pieces = []
    for item in items[:18]:
        url = safe_html(item.get("image_url", ""))
        caption = safe_html(item.get("caption", ""))
        if not url:
            continue
        caption_overlay = (
            f'<figcaption style="position:absolute;left:0;right:0;bottom:0;padding:14px 16px;background:linear-gradient(to top,rgba(0,0,0,0.55),transparent);color:#fff;font-size:0.8rem;letter-spacing:0.05em;">{caption}</figcaption>'
            if caption else ''
        )
        pieces.append(f"""
<figure class="hover-lift reveal" style="break-inside:avoid;margin:0 0 16px;position:relative;border-radius:6px;overflow:hidden;">
  <img src="{url}" alt="{caption}" style="width:100%;display:block;border-radius:6px;" loading="lazy">
  {caption_overlay}
</figure>""")

    if not pieces:
        return ""
    heading = safe_html(section_config.get("heading") or "Selected work")
    return f"""
<section style="max-width:1300px;margin:0 auto;padding:80px 32px;">
  <h2 style="font-family:'{display_font}',Georgia,serif;font-size:2rem;margin:0 0 2rem;color:{text};">
    {heading}
  </h2>
  <div style="column-count:3;column-gap:16px;">
    {''.join(pieces)}
  </div>
  <style>
    @media (max-width: 900px) {{ section > div[style*="column-count:3"] {{ column-count: 2; }} }}
    @media (max-width: 600px) {{ section > div[style*="column-count:3"] {{ column-count: 1; }} }}
  </style>
</section>
"""


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
.sp-hero {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  min-height: 70vh;
  gap: 0;
}}
.sp-hero-text {{
  padding: 64px 48px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  background: {bg};
}}
.sp-hero-visual {{
  background: linear-gradient(135deg, color-mix(in srgb, {accent} 25%, {surface}), color-mix(in srgb, {surface} 50%, {bg}));
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: '{display_font}', Georgia, serif;
  font-size: 6rem;
  color: color-mix(in srgb, {on_bg} 30%, transparent);
}}
.sp-headline {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(2.4rem, 5vw, 4rem);
  line-height: 1.05;
  font-weight: 700;
  margin: 0 0 1.5rem;
  color: {on_bg};
}}
.sp-subhead {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.1rem;
  line-height: 1.6;
  margin: 0 0 2rem;
  color: color-mix(in srgb, {on_bg} 75%, transparent);
}}
.sp-cta-row {{ display: flex; gap: 12px; flex-wrap: wrap; }}
.sp-cta-primary, .sp-cta-secondary {{
  display: inline-block;
  padding: 0.9rem 2rem;
  text-decoration: none;
  font-weight: 600;
  font-family: '{body_font}', sans-serif;
  border-radius: 4px;
}}
.sp-cta-primary {{ background: {accent}; color: {on_accent}; }}
.sp-cta-secondary {{ background: transparent; color: {on_bg}; border: 1px solid {on_bg}; }}
.sp-marquee {{
  background: {accent};
  color: {on_accent};
  padding: 16px 0;
  overflow: hidden;
  white-space: nowrap;
  font-family: '{body_font}', sans-serif;
  font-size: 0.9rem;
  letter-spacing: 0.3em;
  text-transform: uppercase;
}}
.sp-marquee-track {{ display: inline-block; padding-right: 32px; }}
.sp-section {{ max-width: 1300px; margin: 0 auto; padding: 80px 32px; }}
.sp-section h2 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 2.2rem;
  margin: 0 0 2rem;
  color: {on_bg};
  font-weight: 700;
}}
.sp-portfolio-grid {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}}
.sp-portfolio-tile {{
  aspect-ratio: 4/3;
  background: linear-gradient(135deg, color-mix(in srgb, {accent} 18%, {surface}), {bg});
  display: flex;
  align-items: flex-end;
  padding: 20px;
  font-family: '{body_font}', sans-serif;
  color: {on_bg};
  font-weight: 600;
  text-decoration: none;
  border-radius: 6px;
}}
.sp-services-portrait {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}}
.sp-portrait-card {{
  aspect-ratio: 3/4;
  background: linear-gradient(180deg, color-mix(in srgb, {accent} 22%, {bg}) 50%, {bg} 100%);
  padding: 20px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  border-radius: 8px;
  font-family: '{body_font}', sans-serif;
  color: {on_bg};
  text-decoration: none;
}}
.sp-portrait-card h3 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.2rem;
  margin: 0 0 0.4rem;
  color: {on_bg};
}}
.sp-portrait-card p {{
  font-size: 0.85rem;
  margin: 0;
  color: color-mix(in srgb, {on_bg} 70%, transparent);
}}
.sp-price {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.1rem;
  color: {accent};
  font-weight: 700;
  margin-top: 0.5rem;
}}
@media (max-width: 768px) {{
  .sp-hero {{ grid-template-columns: 1fr; min-height: auto; }}
  .sp-hero-visual {{ aspect-ratio: 16/9; font-size: 4rem; }}
  .sp-hero-text {{ padding: 48px 24px; }}
  .sp-section {{ padding: 56px 20px; }}
  .sp-portfolio-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .sp-services-portrait {{ grid-template-columns: 1fr 1fr; }}
}}
</style>
"""

    hero_config = sections_config.get("hero") or {}
    headline = safe_html(hero_config.get("headline")) or safe_html(business_name)
    subheadline = safe_html(hero_config.get("subheadline")) or safe_html(business_data.get("tagline") or "")
    cta_label = safe_html(hero_config.get("cta_label")) or "View work"
    cta_link = safe_html(hero_config.get("cta_link")) or "#work"
    badge = render_in_the_clear_badge(bundle, design_system)
    initial = (business_name[:2] or "•").upper()

    sub_html = f'<p class="sp-subhead">{subheadline}</p>' if subheadline else ""
    badge_html = f'<div style="margin-bottom:1rem;">{badge}</div>' if badge else ""

    # Marquee keywords
    archetype_tokens = (business_data.get("type") or "studio").replace("_", " ")
    keywords = " · ".join([archetype_tokens.upper(), "DESIGN", "STRATEGY", "BRAND", "CRAFT"]) + " · "
    marquee_track = (keywords * 4)

    hero_html = f"""
<section class="sp-hero reveal">
  <div class="sp-hero-text">
    {badge_html}
    <h1 class="sp-headline">{headline}</h1>
    {sub_html}
    <div class="sp-cta-row">
      <a href="{cta_link}" class="sp-cta-primary">{cta_label}</a>
      <a href="#contact" class="sp-cta-secondary">Contact</a>
    </div>
  </div>
  <div class="sp-hero-visual">{initial}</div>
</section>
<div class="sp-marquee"><div class="sp-marquee-track">{marquee_track}</div></div>
"""

    before_about = render_archetype_touch(archetype, "before_about", design_system, bundle)

    portfolio_html = ""
    if (sections_config.get("services") or {}).get("enabled", True) and products:
        tiles = []
        for p in products[:9]:
            name = safe_html(p.get("name", "Work"))
            tiles.append(f'<a href="#work" class="sp-portfolio-tile">{name}</a>')
        portfolio_html = f"""
<section class="sp-section reveal" id="work">
  <h2>Selected work</h2>
  <div class="sp-portfolio-grid">{''.join(tiles)}</div>
</section>
"""

    services_html = ""
    if (sections_config.get("services") or {}).get("enabled", True) and products:
        portraits = []
        for p in products[:6]:
            name = safe_html(p.get("name", "Service"))
            desc = safe_html(p.get("description") or "")
            price = p.get("price")
            try:
                price_label = f"${float(price):,.0f}" if price else ""
            except (TypeError, ValueError):
                price_label = ""
            price_html = f'<div class="sp-price">{price_label}</div>' if price_label else ""
            desc_html = f"<p>{desc}</p>" if desc else ""
            cta_html = render_stripe_button(p, design_system)
            portraits.append(f'<a href="#contact" class="sp-portrait-card"><h3>{name}</h3>{desc_html}{price_html}{cta_html}</a>')
        services_html = f"""
<section class="sp-section reveal">
  <h2>Services</h2>
  <div class="sp-services-portrait">{''.join(portraits)}</div>
</section>
"""

    about_html = ""
    about_config = sections_config.get("about") or {}
    if about_config.get("enabled", True):
        about_text = safe_html(about_config.get("text")) or safe_html(business_data.get("elevator_pitch") or "")
        if about_text:
            about_html = f"""
<section class="sp-section reveal" style="max-width:760px;">
  <h2>Studio</h2>
  <p style="font-family:'{body_font}',sans-serif;font-size:1.1rem;line-height:1.7;color:color-mix(in srgb,{on_bg} 78%,transparent);">{about_text}</p>
</section>
"""

    after_services = render_archetype_touch(archetype, "after_services", design_system, bundle)
    appendix_html = render_appendix_sections(
        design_system, business_data.get("id", "") or "", sections_config, bundle,
        bespoke_gallery=_bespoke_gallery,
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
{portfolio_html}
{services_html}
{about_html}
{after_services}
{appendix_html}
{footer_html}
{render_motion_script()}
</body>
</html>"""
