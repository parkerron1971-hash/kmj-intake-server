"""Immersive archetype — atmospheric backgrounds throughout, cinematic pacing.
Best for premium experiential brands, dark/cinematic aesthetics.
Each section feels like a film scene with deep gradients.
"""
from __future__ import annotations
from studio_archetypes._shared import (
    safe, base_html_shell, base_styles,
    render_motion_modules_styles, render_motion_modules_scripts,
    render_marquee_inline, render_statement_inline,
)


def render_styles(context: dict) -> str:
    palette = context.get("palette") or {}
    bg = palette.get("background", "#0a0a0a")
    accent = palette.get("accent", "#c9a84c")
    return base_styles(context) + render_motion_modules_styles(context) + f"""
.immersive-page {{ max-width: 100%; }}
.immersive-section {{
  min-height: 70vh;
  padding: clamp(4rem, 10vh, 8rem) clamp(1.5rem, 6vw, 5rem);
  display: flex;
  flex-direction: column;
  justify-content: center;
  position: relative;
}}
.immersive-section.scene-1 {{
  background: radial-gradient(ellipse at top right, color-mix(in srgb, {accent} 8%, {bg}), {bg} 70%);
}}
.immersive-section.scene-2 {{
  background: linear-gradient(180deg, {bg}, color-mix(in srgb, {accent} 4%, {bg}));
}}
.immersive-section.scene-3 {{
  background: radial-gradient(ellipse at bottom left, color-mix(in srgb, {accent} 6%, {bg}), {bg});
}}
.immersive-section.scene-4 {{
  background: linear-gradient(135deg, {bg}, color-mix(in srgb, {accent} 5%, {bg}));
}}
.immersive-section h1 {{
  font-size: clamp(3rem, 8vw, 6rem);
  letter-spacing: -0.03em;
  line-height: 1;
  margin-bottom: 1.5rem;
}}
.immersive-section .lead {{
  font-family: var(--font-display);
  font-style: italic;
  font-size: clamp(1.2rem, 1.8vw, 1.6rem);
  max-width: 50ch;
  opacity: 0.92;
  margin-bottom: 2rem;
}}
.immersive-section h2 {{ margin-bottom: 1.2rem; }}
.immersive-section p {{ font-size: 1.1rem; line-height: 1.8; max-width: 60ch; }}
.immersive-products {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 2rem;
  margin-top: 2rem;
}}
.immersive-product {{
  padding: 2rem;
  background: color-mix(in srgb, {accent} 4%, transparent);
  border: 1px solid color-mix(in srgb, {accent} 18%, transparent);
}}
.immersive-product h3 {{ margin-bottom: 0.5rem; }}
.immersive-product .price {{
  display: inline-block; margin-top: 1rem;
  font-family: var(--font-accent); color: {accent};
  font-weight: 600; letter-spacing: 0.05em;
}}
.immersive-footer {{
  padding: 3rem clamp(1.5rem, 6vw, 5rem);
  text-align: center;
  font-size: 0.85rem;
  opacity: 0.7;
}}
"""


def render(context: dict) -> str:
    business_name = safe(context.get("business_name", ""))
    tagline = safe(context.get("tagline", ""))
    tension = safe(context.get("tension_statement", ""))
    philosophy = safe(context.get("philosophy", ""))
    about_me = safe(context.get("about_me") or "")

    scene1 = f"""
<section class="immersive-section scene-1">
  <span class="eyebrow">{safe(context.get('industry', 'Practice'))}</span>
  <h1>{business_name}</h1>
  {f'<p class="lead">{tagline or tension}</p>' if (tagline or tension) else ''}
  <div><a href="#contact" class="cta-button">Begin</a></div>
</section>
"""

    scene2 = ""
    if tension or philosophy:
        scene2 = f"""
<section class="immersive-section scene-2">
  <span class="eyebrow">Philosophy</span>
  <h2>The Approach</h2>
  {f'<p>{tension}</p>' if tension else ''}
  {f'<p>{philosophy}</p>' if philosophy else ''}
</section>
"""

    scene3 = ""
    if about_me:
        scene3 = f"""
<section class="immersive-section scene-3">
  <span class="eyebrow">About</span>
  <h2>{safe(context.get('practitioner_name') or 'About')}</h2>
  <p>{about_me}</p>
</section>
"""

    scene4 = ""
    products = context.get("products") or []
    if products:
        cards = ""
        for p in products[:6]:
            if not isinstance(p, dict):
                continue
            name = safe(p.get("name", ""))
            desc = safe(p.get("description") or "")
            price = p.get("price")
            price_str = f'<span class="price">${price}</span>' if price else ""
            cards += f"""
<div class="immersive-product">
  <h3>{name}</h3>
  {f'<p>{desc}</p>' if desc else ''}
  {price_str}
</div>
"""
        if cards:
            scene4 = f"""
<section class="immersive-section scene-4">
  <span class="eyebrow">Offerings</span>
  <h2>What's Available</h2>
  <div class="immersive-products">{cards}</div>
</section>
"""

    marquee = render_marquee_inline(context)
    statement = render_statement_inline(context, 0)

    footer = f"""
<footer class="immersive-footer">&copy; 2026 {business_name}</footer>
"""

    body = f"""
<div class="immersive-page">
  {scene1}
  {marquee}
  {scene2}
  {statement}
  {scene3}
  {scene4}
  {footer}
</div>
"""

    custom_styles = render_styles(context)
    scripts = render_motion_modules_scripts(context)
    return base_html_shell(context, body, custom_styles, scripts)
