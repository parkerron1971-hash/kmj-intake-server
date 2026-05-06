"""Community Hub layout — warm people-forward. Soft gradients, rounded
cards, generous whitespace, pill-shaped CTAs.

Vocabulary affinity: warm-community, faith-ministry, wellness-healing,
scholar-educator, rising-entrepreneur.
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


def _bespoke_testimonials(design_system, items, section_config, bundle, vocab_id=None):
    """Pass 3.6: bespoke community-hub testimonials — warm, photo-placeholder
    avatar circles, larger quote treatment, 'Voices from our community' framing.
    Pass 3.7: vocab_id accepted (currently unused — bespoke has its own
    warm character)."""
    if not items:
        return ""
    accent = design_system["palette_accent"]
    text = design_system["palette_text"]
    surface = design_system["palette_surface"]
    surface_text = _pick_contrast_text(surface, dark_color=text)
    display_font = design_system["font_display"]

    cards = []
    for item in items[:6]:
        quote = safe_html(item.get("quote", ""))
        author = safe_html(item.get("author", ""))
        role = safe_html(item.get("role", ""))
        if not quote:
            continue
        initials = ""
        if author:
            initials = "".join(p[0].upper() for p in author.split()[:2] if p)
        role_html = (
            f'<div style="font-size:0.85rem;color:color-mix(in srgb,{surface_text} 70%,transparent);">{role}</div>'
            if role else ''
        )
        cards.append(f"""
<div class="hover-lift reveal" style="padding:36px;background:color-mix(in srgb,{surface} 70%,white);color:{surface_text};border-radius:24px;border:1px solid color-mix(in srgb,{accent} 22%,transparent);box-shadow:0 4px 20px rgba(0,0,0,0.04);">
  <p style="font-family:'{display_font}',Georgia,serif;font-size:1.2rem;line-height:1.5;margin:0 0 1.5rem;color:{surface_text};">&ldquo;{quote}&rdquo;</p>
  <div style="display:flex;align-items:center;gap:12px;">
    <div style="width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,{accent},color-mix(in srgb,{accent} 60%,{surface}));display:flex;align-items:center;justify-content:center;color:#fff;font-weight:600;font-size:0.95rem;">{initials or '&bull;'}</div>
    <div>
      <div style="font-weight:600;color:{surface_text};">{author}</div>
      {role_html}
    </div>
  </div>
</div>""")

    if not cards:
        return ""
    heading = safe_html(section_config.get("heading") or "Voices from our community")
    return f"""
<section style="max-width:1200px;margin:0 auto;padding:96px 48px;">
  <h2 style="font-family:'{display_font}',Georgia,serif;font-size:2.2rem;margin:0 0 0.75rem;color:{text};text-align:center;">
    {heading}
  </h2>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px;margin-top:3rem;">
    {''.join(cards)}
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
    on_surface = _pick_contrast_text(surface, dark_color=text)
    display_font = design_system["font_display"]
    body_font = design_system["font_body"]

    layout_css = f"""
<style>
.ch-hero {{
  display: grid;
  grid-template-columns: 1.1fr 1fr;
  align-items: center;
  gap: 64px;
  padding: 96px 64px;
  min-height: 70vh;
  background: linear-gradient(135deg, {bg} 0%, color-mix(in srgb, {accent} 12%, {bg}) 100%);
}}
.ch-headline {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(2.5rem, 5vw, 4rem);
  font-weight: 700;
  line-height: 1.1;
  margin: 0 0 1.5rem;
  color: {on_bg};
}}
.ch-subhead {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.2rem;
  line-height: 1.7;
  max-width: 540px;
  color: color-mix(in srgb, {on_bg} 78%, transparent);
}}
.ch-cta {{
  display: inline-block;
  margin-top: 2rem;
  padding: 1rem 2.5rem;
  background: {accent};
  color: {on_accent};
  text-decoration: none;
  font-weight: 600;
  border-radius: 999px;
  font-family: '{body_font}', sans-serif;
  transition: transform 0.2s ease;
}}
.ch-cta:hover {{ transform: translateY(-2px); }}
.ch-hero-visual {{
  aspect-ratio: 4/5;
  background: linear-gradient(135deg, color-mix(in srgb, {accent} 22%, transparent), color-mix(in srgb, {surface} 30%, transparent));
  border-radius: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: '{display_font}', Georgia, serif;
  font-size: 4rem;
  color: color-mix(in srgb, {on_bg} 30%, transparent);
}}
.ch-section {{
  max-width: 1100px;
  margin: 0 auto;
  padding: 80px 48px;
}}
.ch-section h2 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 2.4rem;
  font-weight: 700;
  color: {on_bg};
  margin: 0 0 1.5rem;
  text-align: center;
}}
.ch-about-body {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.15rem;
  line-height: 1.8;
  max-width: 720px;
  margin: 0 auto;
  text-align: center;
  color: color-mix(in srgb, {on_bg} 80%, transparent);
}}
.ch-services-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 24px;
  margin-top: 3rem;
}}
.ch-service-card {{
  padding: 32px;
  background: color-mix(in srgb, {surface} 14%, white);
  border-radius: 16px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.04);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  color: {on_surface};
}}
.ch-service-card:hover {{
  transform: translateY(-4px);
  box-shadow: 0 12px 32px rgba(0,0,0,0.08);
}}
.ch-service-card h3 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.4rem;
  margin: 0 0 0.75rem;
  color: {on_surface};
}}
.ch-service-card p {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.95rem;
  line-height: 1.6;
  color: color-mix(in srgb, {on_surface} 75%, transparent);
}}
.ch-price {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.5rem;
  color: {accent};
  font-weight: 700;
  margin-top: 1.25rem;
}}
@media (max-width: 768px) {{
  .ch-hero {{ grid-template-columns: 1fr; padding: 64px 24px; gap: 32px; }}
  .ch-section {{ padding: 64px 24px; }}
}}
</style>
"""

    hero_config = sections_config.get("hero") or {}
    headline = safe_html(hero_config.get("headline")) or f"Welcome to {safe_html(business_name)}"
    subheadline = safe_html(hero_config.get("subheadline")) or safe_html(business_data.get("tagline") or "")
    cta_label = safe_html(hero_config.get("cta_label")) or "Get to know us"
    cta_link = safe_html(hero_config.get("cta_link")) or "#contact"
    badge = render_in_the_clear_badge(bundle, design_system)
    initial = (business_name[:1] or "•").upper()

    sub_html = f'<p class="ch-subhead">{subheadline}</p>' if subheadline else ""
    badge_html = f'<div style="margin-bottom:1rem;">{badge}</div>' if badge else ""
    hero_html = f"""
<section class="ch-hero reveal">
  <div>
    {badge_html}
    <h1 class="ch-headline">{headline}</h1>
    {sub_html}
    <a href="{cta_link}" class="ch-cta">{cta_label}</a>
  </div>
  <div class="ch-hero-visual">{initial}</div>
</section>
"""

    before_about = render_archetype_touch(archetype, "before_about", design_system, bundle)

    about_html = ""
    about_config = sections_config.get("about") or {}
    if about_config.get("enabled", True):
        about_raw = (about_config.get("text") or "") or (business_data.get("elevator_pitch") or "")
        if about_raw:
            practitioner = safe_html((bundle.get("practitioner") or {}).get("display_name") or "the team")
            try:
                from studio_layouts.sections.typography import render_drop_cap_paragraph
                about_para_html = render_drop_cap_paragraph(about_raw, design_system, vocab_id)
            except Exception:
                about_para_html = f'<p>{safe_html(about_raw)}</p>'
            about_html = f"""
<section class="ch-section reveal">
  <h2>About {practitioner}</h2>
  <div class="ch-about-body">{about_para_html}</div>
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
            price_html = f'<div class="ch-price">{price_label}</div>' if price_label else ""
            cta_html = render_stripe_button(p, design_system)
            cards.append(f'<div class="ch-service-card"><h3>{name}</h3>{desc_html}{price_html}{cta_html}</div>')
        services_html = f"""
<section class="ch-section reveal">
  <h2>How we help</h2>
  <div class="ch-services-grid">{''.join(cards)}</div>
</section>
"""

    after_services = render_archetype_touch(archetype, "after_services", design_system, bundle)
    appendix_html = render_appendix_sections(
        design_system, business_data.get("id", "") or "", sections_config, bundle,
        bespoke_testimonials=_bespoke_testimonials,
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
