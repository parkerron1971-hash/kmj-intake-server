"""Movement layout — mission statement front & center, full-bleed accent
hero, action-oriented language, prominent join/signup CTA.

Vocabulary affinity: activist-advocate, faith-ministry, street-culture,
warm-community.
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
.mvm-hero {{
  background: {accent};
  color: {on_accent};
  padding: 96px 32px;
  text-align: center;
}}
.mvm-hero-inner {{ max-width: 920px; margin: 0 auto; }}
.mvm-statement {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(2.4rem, 7vw, 5rem);
  line-height: 1.05;
  font-weight: 800;
  margin: 0 0 1.5rem;
  text-transform: uppercase;
  letter-spacing: -0.01em;
}}
.mvm-tagline {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.15rem;
  line-height: 1.5;
  margin: 0 0 2.5rem;
  opacity: 0.85;
}}
.mvm-cta {{
  display: inline-block;
  padding: 1.2rem 3rem;
  background: {bg};
  color: {on_bg};
  text-decoration: none;
  font-weight: 700;
  font-size: 0.95rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  border: 2px solid {bg};
  font-family: '{body_font}', sans-serif;
}}
.mvm-impact {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  max-width: 1100px;
  margin: 0 auto;
  padding: 64px 32px;
}}
.mvm-stat {{
  text-align: center;
  font-family: '{body_font}', sans-serif;
}}
.mvm-stat .num {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 3rem;
  font-weight: 800;
  color: {accent};
  line-height: 1;
}}
.mvm-stat .label {{
  font-size: 0.85rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: color-mix(in srgb, {on_bg} 60%, transparent);
  margin-top: 0.6rem;
}}
.mvm-section {{ max-width: 960px; margin: 0 auto; padding: 80px 32px; }}
.mvm-section h2 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 2.4rem;
  font-weight: 800;
  margin: 0 0 1.5rem;
  color: {on_bg};
  text-transform: uppercase;
}}
.mvm-section p {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.1rem;
  line-height: 1.7;
  color: color-mix(in srgb, {on_bg} 80%, transparent);
}}
.mvm-services-list {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 24px;
  margin-top: 2rem;
}}
.mvm-service-card {{
  padding: 28px;
  border: 2px solid {on_bg};
  background: {bg};
}}
.mvm-service-card h3 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.3rem;
  margin: 0 0 0.6rem;
  color: {on_bg};
  text-transform: uppercase;
}}
.mvm-service-card p {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.95rem;
  line-height: 1.6;
}}
@media (max-width: 768px) {{
  .mvm-hero {{ padding: 64px 24px; }}
  .mvm-impact {{ grid-template-columns: 1fr; padding: 48px 24px; }}
  .mvm-section {{ padding: 56px 24px; }}
}}
</style>
"""

    hero_config = sections_config.get("hero") or {}
    statement = safe_html(hero_config.get("headline")) or safe_html(business_data.get("tagline") or business_name)
    tagline = safe_html(hero_config.get("subheadline")) or ""
    cta_label = safe_html(hero_config.get("cta_label")) or "Join the movement"
    cta_link = safe_html(hero_config.get("cta_link")) or "#join"
    badge = render_in_the_clear_badge(bundle, design_system)

    badge_html = f'<div style="margin-bottom:1.5rem;">{badge}</div>' if badge else ""
    tagline_html = f'<p class="mvm-tagline">{tagline}</p>' if tagline else ""
    hero_html = f"""
<section class="mvm-hero">
  <div class="mvm-hero-inner">
    {badge_html}
    <h1 class="mvm-statement">{statement}</h1>
    {tagline_html}
    <a href="{cta_link}" class="mvm-cta">{cta_label}</a>
  </div>
</section>
<section class="mvm-impact">
  <div class="mvm-stat"><div class="num">10K+</div><div class="label">People reached</div></div>
  <div class="mvm-stat"><div class="num">50+</div><div class="label">Communities served</div></div>
  <div class="mvm-stat"><div class="num">100%</div><div class="label">Mission-driven</div></div>
</section>
"""

    before_about = render_archetype_touch(archetype, "before_about", design_system, bundle)

    about_html = ""
    about_config = sections_config.get("about") or {}
    if about_config.get("enabled", True):
        about_text = safe_html(about_config.get("text")) or safe_html(business_data.get("elevator_pitch") or "")
        if about_text:
            about_html = f"""
<section class="mvm-section">
  <h2>Why we exist</h2>
  <p>{about_text}</p>
</section>
"""

    services_html = ""
    services_config = sections_config.get("services") or {}
    if services_config.get("enabled", True) and products:
        cards = []
        for p in products[:6]:
            name = safe_html(p.get("name", "Way to engage"))
            desc = safe_html(p.get("description") or "")
            desc_html = f"<p>{desc}</p>" if desc else ""
            cards.append(f'<div class="mvm-service-card"><h3>{name}</h3>{desc_html}</div>')
        services_html = f"""
<section class="mvm-section">
  <h2>How you can join</h2>
  <div class="mvm-services-list">{''.join(cards)}</div>
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
