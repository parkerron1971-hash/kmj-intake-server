"""Authority layout — trust signals + structured grid + numbered sections.

Vocabulary affinity: scholar-educator, established-authority,
sovereign-authority, activist-advocate, universal-premium.
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

    # Pass 3.7b — hero gradient + corner ornaments (framed layout)
    try:
        from studio_decoration import get_gradient_for_section, render_decorative_corners
        hero_gradient = get_gradient_for_section(vocab_id, design_system, "hero")
    except Exception:
        hero_gradient = design_system.get("palette_bg") or "#fafaf8"
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
.auth-hero {{
  position: relative;
  text-align: center;
  padding: 96px 48px 64px;
  background: {hero_gradient};
  border-bottom: 1px solid color-mix(in srgb, {on_bg} 12%, transparent);
}}
.auth-headline {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(2.2rem, 5vw, 3.6rem);
  font-weight: 700;
  line-height: 1.15;
  margin: 0 auto 1.5rem;
  max-width: 880px;
  color: {on_bg};
}}
.auth-subhead {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.1rem;
  line-height: 1.6;
  max-width: 640px;
  margin: 0 auto 2rem;
  color: color-mix(in srgb, {on_bg} 75%, transparent);
}}
.auth-cta {{
  display: inline-block;
  padding: 1rem 2.4rem;
  background: {accent};
  color: {on_accent};
  text-decoration: none;
  font-weight: 600;
  font-family: '{body_font}', sans-serif;
  border-radius: 4px;
}}
.auth-credentials {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 32px;
  max-width: 1100px;
  margin: 0 auto;
  padding: 48px;
  border-bottom: 1px solid color-mix(in srgb, {on_bg} 12%, transparent);
}}
.auth-credential {{
  text-align: center;
  font-family: '{body_font}', sans-serif;
}}
.auth-credential .num {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 2.4rem;
  font-weight: 700;
  color: {accent};
  display: block;
}}
.auth-credential .label {{
  font-size: 0.8rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: color-mix(in srgb, {on_bg} 60%, transparent);
  margin-top: 0.3rem;
}}
.auth-section {{
  max-width: 1100px;
  margin: 0 auto;
  padding: 80px 48px;
}}
.auth-section-num {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 0.85rem;
  letter-spacing: 0.4em;
  color: {accent};
  margin-bottom: 1rem;
}}
.auth-section h2 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 2.2rem;
  font-weight: 700;
  margin: 0 0 1.5rem;
  color: {on_bg};
}}
.auth-about-body {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.05rem;
  line-height: 1.8;
  max-width: 760px;
  color: color-mix(in srgb, {on_bg} 82%, transparent);
}}
.auth-services-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 24px;
  margin-top: 2rem;
}}
.auth-service-card {{
  padding: 28px;
  border: 1px solid color-mix(in srgb, {on_bg} 14%, transparent);
  border-radius: 6px;
  background: color-mix(in srgb, {bg} 95%, white);
}}
.auth-service-card h3 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.25rem;
  margin: 0 0 0.75rem;
  color: {on_bg};
}}
.auth-service-card p {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.95rem;
  line-height: 1.6;
  color: color-mix(in srgb, {on_bg} 75%, transparent);
}}
.auth-price {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.4rem;
  color: {accent};
  font-weight: 700;
  margin-top: 1rem;
}}
@media (max-width: 768px) {{
  .auth-hero {{ padding: 64px 24px 48px; }}
  .auth-credentials {{ grid-template-columns: 1fr; gap: 24px; padding: 32px 24px; }}
  .auth-section {{ padding: 64px 24px; }}
}}
</style>
"""

    hero_config = sections_config.get("hero") or {}
    headline = safe_html(hero_config.get("headline")) or safe_html(business_name)
    subheadline = safe_html(hero_config.get("subheadline")) or safe_html(business_data.get("tagline") or "")
    cta_label = safe_html(hero_config.get("cta_label")) or "Schedule a consultation"
    cta_link = safe_html(hero_config.get("cta_link")) or "#contact"
    badge = render_in_the_clear_badge(bundle, design_system)

    sub_html = f'<p class="auth-subhead">{subheadline}</p>' if subheadline else ""
    badge_html = f'<div style="margin-bottom:1rem;">{badge}</div>' if badge else ""
    hero_html = f"""
<section class="auth-hero reveal">
  {hero_corners}
  {badge_html}
  <h1 class="auth-headline">{headline}</h1>
  {sub_html}
  <a href="{cta_link}" class="auth-cta">{cta_label}</a>
</section>
<section class="auth-credentials reveal">
  <div class="auth-credential"><span class="num">10+</span><div class="label">Years experience</div></div>
  <div class="auth-credential"><span class="num">200+</span><div class="label">Engagements delivered</div></div>
  <div class="auth-credential"><span class="num">98%</span><div class="label">Client satisfaction</div></div>
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
<section class="auth-section reveal">
  <div class="auth-section-num">01 / About</div>
  <h2>About {safe_html((bundle.get("practitioner") or {}).get("display_name") or "the team")}</h2>
  <div class="auth-about-body">{about_para_html}</div>
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
            price_html = f'<div class="auth-price">{price_label}</div>' if price_label else ""
            cta_html = render_stripe_button(p, design_system)
            cards.append(f'<div class="auth-service-card"><h3>{name}</h3>{desc_html}{price_html}{cta_html}</div>')
        services_html = f"""
<section class="auth-section reveal">
  <div class="auth-section-num">02 / Services</div>
  <h2>Engagements</h2>
  <div class="auth-services-grid">{''.join(cards)}</div>
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
