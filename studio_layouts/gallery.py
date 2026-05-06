"""Gallery layout — image-first masonry. Minimal text, work as hero.

Vocabulary affinity: creative-artist, street-culture, expressive-vibrancy,
maximalist.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from studio_composite import CompositeDirection
from studio_design_system import DesignSystem, _pick_accent_contrast, _pick_contrast_text
from studio_layouts.shared import (
    render_appendix_sections, render_archetype_touch, render_footer,
    render_head, render_in_the_clear_badge, render_stripe_button, safe_html, render_motion_script,
    render_decoration_head, render_decoration_scripts, render_scheme_after_hero,
)
from studio_decoration import render_decoration_for


def _bespoke_gallery(design_system, items, section_config, bundle, vocab_id=None):
    """Pass 3.6: bespoke gallery-layout gallery — full-bleed edge-to-edge
    images with hover overlays. Even more image-first than the
    studio-portfolio bespoke version."""
    if not items:
        return ""
    accent = design_system["palette_accent"]
    text = design_system["palette_text"]
    display_font = design_system["font_display"]

    tiles = []
    for item in items[:16]:
        url = safe_html(item.get("image_url", ""))
        caption = safe_html(item.get("caption", ""))
        if not url:
            continue
        caption_html = (
            f'<div style="position:absolute;inset:auto 0 0 0;padding:18px 20px;background:linear-gradient(to top,rgba(0,0,0,0.7),transparent 70%);color:#fff;opacity:0;transition:opacity 0.2s ease;">{caption}</div>'
            if caption else ''
        )
        tiles.append(f"""
<a href="{url}" target="_blank" rel="noopener" style="position:relative;overflow:hidden;display:block;text-decoration:none;" onmouseover="this.querySelector('div')?.style.setProperty('opacity','1')" onmouseout="this.querySelector('div')?.style.setProperty('opacity','0')">
  <img src="{url}" alt="{caption}" style="width:100%;height:100%;object-fit:cover;display:block;aspect-ratio:1/1;" loading="lazy">
  {caption_html}
</a>""")

    if not tiles:
        return ""
    heading = safe_html(section_config.get("heading") or "Work")
    return f"""
<section style="padding:64px 0 0;">
  <h2 style="font-family:'{display_font}',Georgia,serif;font-size:2rem;margin:0 32px 2rem;color:{text};">
    {heading}
  </h2>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:0;">
    {''.join(tiles)}
  </div>
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
    scheme: Optional[Dict[str, Any]] = None,
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
<section class="gal-hero reveal">
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
            cta_html = render_stripe_button(p, design_system)
            tiles.append(f'<a href="#work-{i}" class="{tile_class}" id="work"><h3>{name}</h3>{desc_html}{price_html}{cta_html}</a>')
        services_html = f"""
<section class="gal-grid-section reveal">
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
{render_decoration_head(design_system, scheme)}
<body style="background:{bg};color:{on_bg};margin:0;">
{render_scheme_after_hero(design_system, scheme)}
{hero_html}
{services_html}
<div style="max-width:1100px;margin:0 auto;padding:24px 24px 0;text-align:center;">{eyebrow_html}</div>
{before_about}
{about_html}
{after_services}
{appendix_html}
{footer_html}
{render_decoration_scripts(scheme)}
{render_motion_script()}
</body>
</html>"""
