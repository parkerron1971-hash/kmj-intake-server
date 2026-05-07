"""Minimal Single archetype — extremely condensed, 3-4 sections only.
Best for radical minimalist brands, single-message positioning.
"""
from __future__ import annotations
from studio_archetypes._shared import (
    safe, base_html_shell, base_styles,
    render_motion_modules_styles, render_motion_modules_scripts,
)


def render_styles(context: dict) -> str:
    return base_styles(context) + render_motion_modules_styles(context) + """
.minimal-page {
  max-width: 720px;
  margin: 0 auto;
  padding: clamp(4rem, 12vh, 8rem) clamp(1.5rem, 5vw, 3rem);
}
.minimal-hero {
  margin-bottom: 6rem;
}
.minimal-hero .eyebrow { margin-bottom: 1.5rem; }
.minimal-hero h1 {
  font-size: clamp(2.5rem, 5vw, 4rem);
  margin-bottom: 1.5rem;
  letter-spacing: -0.02em;
}
.minimal-hero p {
  font-size: 1.15rem;
  line-height: 1.7;
  max-width: 50ch;
  opacity: 0.85;
}
.minimal-section {
  margin-bottom: 5rem;
  padding-top: 3rem;
  border-top: 1px solid color-mix(in srgb, var(--accent) 20%, transparent);
}
.minimal-section h2 {
  font-size: clamp(1.4rem, 2.5vw, 1.8rem);
  margin-bottom: 1rem;
}
.minimal-section p {
  font-size: 1rem;
  line-height: 1.7;
  margin-bottom: 1em;
}
.minimal-product {
  padding: 1rem 0;
  border-bottom: 1px solid color-mix(in srgb, var(--accent) 12%, transparent);
}
.minimal-product:last-child { border-bottom: none; }
.minimal-product-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.minimal-product h3 { font-size: 1.1rem; margin: 0; font-family: var(--font-body); font-weight: 500; }
.minimal-product .price {
  font-family: var(--font-accent);
  color: var(--accent);
  font-weight: 600;
  font-size: 0.9rem;
}
.minimal-footer {
  text-align: left;
  padding-top: 4rem;
  font-size: 0.8rem;
  opacity: 0.5;
}
"""


def render(context: dict) -> str:
    business_name = safe(context.get("business_name", ""))
    tagline = safe(context.get("tagline", ""))
    tension = safe(context.get("tension_statement", ""))
    about_me = safe(context.get("about_me") or "")

    hero = f"""
<section class="minimal-hero">
  <span class="eyebrow">{safe(context.get('industry', ''))}</span>
  <h1>{business_name}</h1>
  {f'<p>{tagline or tension}</p>' if (tagline or tension) else ''}
</section>
"""

    about_block = ""
    if about_me:
        # First sentence only, for radical minimalism.
        first_para = about_me.split(".")[0].strip() + "."
        about_block = f"""
<section class="minimal-section">
  <h2>About</h2>
  <p>{first_para}</p>
</section>
"""

    products_html = ""
    products = context.get("products") or []
    if products:
        items = ""
        for p in products[:4]:
            if not isinstance(p, dict):
                continue
            name = safe(p.get("name", ""))
            price = p.get("price")
            price_str = f'<span class="price">${price}</span>' if price else ""
            items += f"""
<div class="minimal-product">
  <div class="minimal-product-row">
    <h3>{name}</h3>
    {price_str}
  </div>
</div>
"""
        if items:
            products_html = f"""
<section class="minimal-section">
  <h2>Offerings</h2>
  {items}
</section>
"""

    cta = f"""
<section class="minimal-section">
  <a href="#contact" class="cta-button">Begin</a>
</section>
"""

    footer = f"""
<footer class="minimal-footer">&copy; 2026 {business_name}</footer>
"""

    body = f"""
<div class="minimal-page">
  {hero}
  {about_block}
  {products_html}
  {cta}
  {footer}
</div>
"""

    custom_styles = render_styles(context)
    scripts = render_motion_modules_scripts(context)
    return base_html_shell(context, body, custom_styles, scripts)
