"""Editorial Scroll archetype — single-column reading experience.
Best for narrative-driven brands, scholar-educators, story-led work.
Page reads like a thoughtful essay. Generous lead-in, sustained typography.
"""
from __future__ import annotations
from studio_archetypes._shared import (
    safe, base_html_shell, base_styles,
    render_motion_modules_styles, render_motion_modules_scripts,
    render_marquee_inline, render_statement_inline,
)


def render_styles(context: dict) -> str:
    return base_styles(context) + render_motion_modules_styles(context) + """
.editorial-page {
  max-width: 760px;
  margin: 0 auto;
  padding: clamp(3rem, 8vh, 6rem) clamp(1.5rem, 5vw, 3rem);
}
.editorial-hero {
  text-align: left;
  margin-bottom: 5rem;
}
.editorial-hero .eyebrow { margin-bottom: 1rem; }
.editorial-hero h1 {
  font-size: clamp(2.5rem, 5vw, 4.5rem);
  margin-bottom: 1.5rem;
}
.editorial-hero .lead {
  font-family: var(--font-display);
  font-style: italic;
  font-size: clamp(1.2rem, 1.8vw, 1.5rem);
  line-height: 1.5;
  color: var(--text);
  opacity: 0.92;
  max-width: 55ch;
  margin-bottom: 2rem;
}
.editorial-section {
  margin-bottom: 4rem;
}
.editorial-section h2 {
  margin-bottom: 1.2rem;
  border-bottom: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
  padding-bottom: 0.5rem;
}
.editorial-section p {
  font-size: 1.05rem;
  line-height: 1.8;
  margin-bottom: 1.2em;
}
.editorial-pullquote {
  font-family: var(--font-display);
  font-style: italic;
  font-size: clamp(1.4rem, 2.4vw, 2rem);
  line-height: 1.4;
  color: var(--accent);
  border-left: 3px solid var(--accent);
  padding: 0.5rem 0 0.5rem 1.5rem;
  margin: 2.5rem 0;
}
.editorial-product {
  border-top: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
  padding: 1.5rem 0;
}
.editorial-product:last-child { border-bottom: 1px solid color-mix(in srgb, var(--accent) 25%, transparent); }
.editorial-product-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 1rem;
}
.editorial-product h3 { font-size: 1.3rem; margin: 0; }
.editorial-product .price {
  font-family: var(--font-accent);
  color: var(--accent);
  font-weight: 600;
}
.editorial-product p { margin: 0.6rem 0 0; opacity: 0.85; font-size: 0.95rem; }
.editorial-cta {
  text-align: center;
  margin: 4rem 0 2rem;
  padding-top: 3rem;
  border-top: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
}
.editorial-footer {
  text-align: center;
  padding: 2rem 0;
  font-size: 0.85rem;
  opacity: 0.6;
}
"""


def render(context: dict) -> str:
    business_name = safe(context.get("business_name", ""))
    tagline = safe(context.get("tagline", ""))
    tension = safe(context.get("tension_statement", ""))
    philosophy = safe(context.get("philosophy", ""))
    about_me = safe(context.get("about_me") or "")
    practitioner_name = safe(context.get("practitioner_name") or "")
    industry = safe(context.get("industry", ""))

    hero = f"""
<section class="editorial-hero">
  <span class="eyebrow">{industry or 'A Practice'}</span>
  <h1>{business_name}</h1>
  {f'<p class="lead">{tagline}</p>' if tagline else ''}
</section>
"""

    tension_block = f'<blockquote class="editorial-pullquote">{tension}</blockquote>' if tension else ""

    philosophy_block = ""
    if philosophy:
        philosophy_block = f"""
<section class="editorial-section">
  <h2>Philosophy</h2>
  <p>{philosophy}</p>
</section>
"""

    about_block = ""
    if about_me:
        about_block = f"""
<section class="editorial-section">
  <h2>{practitioner_name or 'About'}</h2>
  <p>{about_me}</p>
</section>
"""

    marquee = render_marquee_inline(context)
    statement = render_statement_inline(context, 0)

    products_html = ""
    products = context.get("products") or []
    if products:
        items = ""
        for p in products[:8]:
            if not isinstance(p, dict):
                continue
            name = safe(p.get("name", ""))
            desc = safe(p.get("description") or "")
            price = p.get("price")
            price_str = f'<span class="price">${price}</span>' if price else ""
            items += f"""
<div class="editorial-product">
  <div class="editorial-product-row">
    <h3>{name}</h3>
    {price_str}
  </div>
  {f'<p>{desc}</p>' if desc else ''}
</div>
"""
        if items:
            products_html = f"""
<section class="editorial-section">
  <h2>What's Offered</h2>
  {items}
</section>
"""

    cta = f"""
<div class="editorial-cta">
  <a href="#contact" class="cta-button">Begin a Conversation</a>
</div>
"""

    footer = f"""
<footer class="editorial-footer">
  &copy; 2026 {business_name}
</footer>
"""

    body = f"""
<div class="editorial-page">
  {hero}
  {tension_block}
  {philosophy_block}
  {about_block}
  {marquee}
  {statement}
  {products_html}
  {cta}
  {footer}
</div>
"""

    custom_styles = render_styles(context)
    scripts = render_motion_modules_scripts(context)
    return base_html_shell(context, body, custom_styles, scripts)
