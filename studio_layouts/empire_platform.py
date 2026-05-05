"""Empire Platform layout — identity-words hero, founder-intro split,
alternating full-width breaks per offering. One identity, many dimensions.

Vocabulary affinity: faith-ministry, legacy-builder, sovereign-authority,
established-authority, activist-advocate.
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
    surface = design_system["palette_surface"]
    on_accent = _pick_accent_contrast(accent)
    on_bg = _pick_contrast_text(bg, dark_color=text)
    display_font = design_system["font_display"]
    body_font = design_system["font_body"]

    layout_css = f"""
<style>
.emp-hero {{
  position: relative;
  min-height: 80vh;
  padding: 96px 32px 64px;
  background:
    linear-gradient(135deg, {bg} 0%, color-mix(in srgb, {accent} 18%, {bg}) 100%);
  display: flex;
  flex-direction: column;
  justify-content: center;
  text-align: center;
}}
.emp-identity-words {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.85rem;
  letter-spacing: 0.45em;
  text-transform: uppercase;
  color: {accent};
  margin-bottom: 2.5rem;
}}
.emp-identity-words .sep {{ margin: 0 12px; opacity: 0.5; }}
.emp-headline {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(2.6rem, 7vw, 5rem);
  line-height: 1;
  font-weight: 800;
  margin: 0 auto 1.5rem;
  max-width: 900px;
  color: {on_bg};
  text-transform: uppercase;
  letter-spacing: -0.01em;
}}
.emp-subhead {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.15rem;
  line-height: 1.6;
  max-width: 600px;
  margin: 0 auto;
  color: color-mix(in srgb, {on_bg} 75%, transparent);
}}
.emp-cta {{
  display: inline-block;
  margin-top: 2.5rem;
  padding: 1.1rem 2.8rem;
  background: {accent};
  color: {on_accent};
  text-decoration: none;
  font-weight: 700;
  font-size: 0.9rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  font-family: '{body_font}', sans-serif;
  border-radius: 4px;
}}
.emp-founder {{
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 64px;
  align-items: center;
  max-width: 1200px;
  margin: 0 auto;
  padding: 96px 48px;
}}
.emp-founder-text h2 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 2.2rem;
  margin: 0 0 1.5rem;
  color: {on_bg};
  font-weight: 700;
}}
.emp-founder-text p {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.05rem;
  line-height: 1.7;
  color: color-mix(in srgb, {on_bg} 80%, transparent);
}}
.emp-founder-portrait {{
  aspect-ratio: 3/4;
  background: linear-gradient(180deg, color-mix(in srgb, {accent} 22%, transparent), {surface});
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: '{display_font}', Georgia, serif;
  font-size: 6rem;
  color: color-mix(in srgb, {on_bg} 30%, transparent);
  border-radius: 4px;
}}
.emp-offering {{
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 0;
  background: color-mix(in srgb, {accent} 6%, {bg});
}}
.emp-offering.alt {{
  grid-template-columns: 1fr 1.2fr;
  background: {bg};
}}
.emp-offering-content {{
  padding: 96px 48px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}}
.emp-offering.alt .emp-offering-content {{ order: 2; }}
.emp-offering h3 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(1.8rem, 3.5vw, 2.6rem);
  margin: 0 0 1rem;
  color: {on_bg};
  font-weight: 700;
}}
.emp-offering p {{
  font-family: '{body_font}', sans-serif;
  font-size: 1rem;
  line-height: 1.7;
  color: color-mix(in srgb, {on_bg} 80%, transparent);
}}
.emp-offering-cta {{
  display: inline-block;
  margin-top: 1.5rem;
  padding: 0.85rem 2rem;
  background: {accent};
  color: {on_accent};
  text-decoration: none;
  font-weight: 600;
  font-size: 0.85rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  font-family: '{body_font}', sans-serif;
  border-radius: 3px;
  align-self: flex-start;
}}
.emp-offering-visual {{
  background: linear-gradient(135deg, color-mix(in srgb, {accent} 25%, {surface}), color-mix(in srgb, {surface} 50%, {bg}));
  min-height: 360px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: '{display_font}', Georgia, serif;
  font-size: 5rem;
  color: color-mix(in srgb, {on_bg} 30%, transparent);
}}
.emp-price {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.4rem;
  color: {accent};
  font-weight: 700;
  margin-top: 1rem;
}}
@media (max-width: 768px) {{
  .emp-hero {{ padding: 64px 20px; min-height: 60vh; }}
  .emp-founder, .emp-offering, .emp-offering.alt {{ grid-template-columns: 1fr; padding: 0; gap: 0; }}
  .emp-founder {{ padding: 64px 24px; }}
  .emp-offering-content {{ padding: 56px 24px; order: 1 !important; }}
  .emp-offering-visual {{ min-height: 240px; }}
}}
</style>
"""

    hero_config = sections_config.get("hero") or {}
    headline = safe_html(hero_config.get("headline")) or safe_html(business_data.get("tagline") or business_name)
    subheadline = safe_html(hero_config.get("subheadline")) or ""
    cta_label = safe_html(hero_config.get("cta_label")) or "Begin"
    cta_link = safe_html(hero_config.get("cta_link")) or "#contact"
    badge = render_in_the_clear_badge(bundle, design_system)

    # Identity words — derive from business type + a few signal hints
    voice_personality = ((bundle.get("voice") or {}).get("personality") or "")
    identity_words = []
    if archetype:
        identity_words.append(archetype.replace("_", " ").upper())
    if voice_personality:
        identity_words.append(voice_personality.split(",")[0].strip().upper()[:18])
    identity_words += ["VISION", "VOICE", "LEGACY"]
    identity_words = identity_words[:5]
    identity_html = '<span class="sep">|</span>'.join(f"<span>{safe_html(w)}</span>" for w in identity_words)

    sub_html = f'<p class="emp-subhead">{subheadline}</p>' if subheadline else ""
    badge_html = f'<div style="margin-bottom:1.5rem;">{badge}</div>' if badge else ""
    hero_html = f"""
<section class="emp-hero reveal">
  {badge_html}
  <div class="emp-identity-words">{identity_html}</div>
  <h1 class="emp-headline">{headline}</h1>
  {sub_html}
  <div><a href="{cta_link}" class="emp-cta">{cta_label}</a></div>
</section>
"""

    practitioner = safe_html((bundle.get("practitioner") or {}).get("display_name") or "the founder")
    initial = (practitioner[:2] or "•").upper()
    founder_html = ""
    about_config = sections_config.get("about") or {}
    if about_config.get("enabled", True):
        about_text = safe_html(about_config.get("text")) or safe_html(business_data.get("elevator_pitch") or "")
        if about_text:
            founder_html = f"""
<section class="emp-founder reveal">
  <div class="emp-founder-text">
    <h2>About {practitioner}</h2>
    <p>{about_text}</p>
  </div>
  <div class="emp-founder-portrait">{initial}</div>
</section>
"""

    before_about = render_archetype_touch(archetype, "before_about", design_system, bundle)

    offerings_html = ""
    services_config = sections_config.get("services") or {}
    if services_config.get("enabled", True) and products:
        rows = []
        for i, p in enumerate(products[:6]):
            name = safe_html(p.get("name", "Offering"))
            desc = safe_html(p.get("description") or "")
            price = p.get("price")
            try:
                price_label = f"${float(price):,.0f}" if price else ""
            except (TypeError, ValueError):
                price_label = ""
            desc_html = f"<p>{desc}</p>" if desc else ""
            price_html = f'<div class="emp-price">{price_label}</div>' if price_label else ""
            klass = "emp-offering" + (" alt" if i % 2 else "")
            visual_letter = name[:1].upper() if name else "•"
            stripe_html = render_stripe_button(p, design_system)
            rows.append(f"""
<section class="{klass}">
  <div class="emp-offering-content">
    <h3>{name}</h3>
    {desc_html}
    {price_html}
    <a href="#contact" class="emp-offering-cta">Learn more</a>
    {stripe_html}
  </div>
  <div class="emp-offering-visual">{visual_letter}</div>
</section>
""")
        offerings_html = "".join(rows)

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
{founder_html}
{offerings_html}
{after_services}
{appendix_html}
{footer_html}
{render_motion_script()}
</body>
</html>"""
