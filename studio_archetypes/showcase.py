"""Showcase archetype — portfolio-first, large images, visual brands.
Best for designers, photographers, artists. Hero is image-driven.
"""
from __future__ import annotations
from studio_archetypes._shared import (
    safe, base_html_shell, base_styles,
    render_motion_modules_styles, render_motion_modules_scripts,
    render_marquee_inline, render_statement_inline,
)


def render_styles(context: dict) -> str:
    return base_styles(context) + render_motion_modules_styles(context) + """
.showcase-page { max-width: 100%; }
.showcase-hero {
  min-height: min(70vh, 640px);
  background: linear-gradient(135deg, var(--bg) 0%, var(--bg2) 100%);
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding: clamp(3rem, 6vh, 5rem) clamp(1.5rem, 6vw, 5rem);
  position: relative;
}
.showcase-hero h1 {
  font-size: clamp(3rem, 9vw, 7rem);
  letter-spacing: -0.04em;
  line-height: 1;
  margin-bottom: 1rem;
}
.showcase-hero .tagline {
  font-size: clamp(1.1rem, 1.6vw, 1.4rem);
  max-width: 45ch;
  opacity: 0.85;
}
.showcase-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 0.5rem;
  padding: 3rem clamp(1.5rem, 4vw, 3rem);
}
.showcase-card {
  position: relative;
  aspect-ratio: 4/5;
  background: var(--bg2);
  border: 1px solid color-mix(in srgb, var(--accent) 12%, transparent);
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding: 1.5rem;
  overflow: hidden;
}
.showcase-card-meta {
  font-family: var(--font-accent);
  font-size: 0.75rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 0.5rem;
}
.showcase-card h3 {
  font-size: 1.5rem;
  margin: 0;
}
.showcase-section {
  padding: clamp(3rem, 6vh, 5rem) clamp(1.5rem, 6vw, 5rem);
  max-width: 980px;
  margin: 0 auto;
}
.showcase-section h2 { margin-bottom: 1.2rem; }
.showcase-footer {
  padding: 3rem clamp(1.5rem, 6vw, 5rem);
  border-top: 1px solid color-mix(in srgb, var(--accent) 14%, transparent);
  text-align: center;
  font-size: 0.85rem;
  opacity: 0.7;
}
@media (max-width: 768px) {
  .showcase-hero { min-height: 50vh; padding: 2rem 1.5rem; }
  .showcase-grid { grid-template-columns: 1fr; padding: 2rem 1.5rem; }
}
"""


def render(context: dict) -> str:
    business_name = safe(context.get("business_name", ""))
    tagline = safe(context.get("tagline", ""))
    tension = safe(context.get("tension_statement", ""))

    hero = f"""
<section class="showcase-hero">
  <span class="eyebrow">{safe(context.get('industry', 'Studio'))}</span>
  <h1>{business_name}</h1>
  {f'<p class="tagline">{tagline or tension}</p>' if (tagline or tension) else ''}
</section>
"""

    marquee = render_marquee_inline(context)

    cards_html = ""
    products = context.get("products") or []
    gallery = context.get("gallery_images") or []
    items_to_show = products[:6] if products else gallery[:6]
    if items_to_show:
        cards = ""
        for i, item in enumerate(items_to_show):
            if isinstance(item, dict):
                name = safe(item.get("name") or item.get("title") or f"Project {i+1}")
                meta = str(i + 1).zfill(2)
            else:
                name = f"Project {i+1}"
                meta = str(i + 1).zfill(2)
            cards += f"""
<div class="showcase-card">
  <span class="showcase-card-meta">{meta}</span>
  <h3>{name}</h3>
</div>
"""
        cards_html = f'<section class="showcase-grid">{cards}</section>'

    statement = render_statement_inline(context, 0)

    philosophy = safe(context.get("philosophy", ""))
    philosophy_block = ""
    if philosophy:
        philosophy_block = f"""
<section class="showcase-section">
  <span class="eyebrow">Approach</span>
  <h2>Philosophy</h2>
  <p>{philosophy}</p>
</section>
"""

    footer = f"""
<footer class="showcase-footer">&copy; 2026 {business_name}</footer>
"""

    body = f"""
<div class="showcase-page">
  {hero}
  {marquee}
  {cards_html}
  {statement}
  {philosophy_block}
  {footer}
</div>
"""

    custom_styles = render_styles(context)
    scripts = render_motion_modules_scripts(context)
    return base_html_shell(context, body, custom_styles, scripts)
