"""Split archetype — hero split + content sections.
Most reliable archetype, default for service businesses.
Hero is two-column (text left, image/quote right). Sections follow rhythm.
"""
from __future__ import annotations
from studio_archetypes._shared import (
    safe, base_html_shell, base_styles,
    render_motion_modules_styles, render_motion_modules_scripts,
    render_marquee_inline, render_statement_inline,
)


def render_styles(context: dict) -> str:
    return base_styles(context) + render_motion_modules_styles(context) + """
.split-page { max-width: 100%; }
.split-hero {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 4rem;
  padding: clamp(3rem, 8vh, 6rem) clamp(1.5rem, 6vw, 5rem);
  min-height: min(80vh, 720px);
  align-items: center;
  position: relative;
}
.split-hero-text h1 { margin-bottom: 1.5rem; }
.split-hero-text .tension {
  font-family: var(--font-display);
  font-style: italic;
  font-size: clamp(1.05rem, 1.5vw, 1.3rem);
  color: var(--text);
  opacity: 0.85;
  margin-bottom: 2rem;
  border-left: 2px solid var(--accent);
  padding-left: 1.2rem;
  max-width: 50ch;
}
.split-hero-aside {
  font-family: var(--font-display);
  font-size: clamp(1.4rem, 2.2vw, 2rem);
  font-style: italic;
  color: var(--accent);
  line-height: 1.5;
  border-left: 1px solid var(--accent);
  padding-left: 2rem;
  opacity: 0.92;
}
.split-section {
  padding: clamp(3rem, 8vh, 5rem) clamp(1.5rem, 6vw, 5rem);
  max-width: 1280px;
  margin: 0 auto;
}
.split-section-soft {
  padding-top: clamp(2rem, 4vh, 3rem);
  padding-bottom: clamp(2rem, 4vh, 3rem);
}
.split-section h2 { margin-bottom: 1rem; }
.split-section .section-lead { font-size: 1.1rem; max-width: 60ch; margin-bottom: 2rem; opacity: 0.9; }
.split-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1.5rem;
  margin-top: 2rem;
}
.split-card {
  background: var(--bg2);
  padding: 2rem;
  border: 1px solid color-mix(in srgb, var(--accent) 12%, transparent);
}
.split-card h3 { margin-bottom: 0.6rem; }
.split-card p { margin: 0; opacity: 0.9; }
.split-card-price {
  display: inline-block;
  margin-top: 1rem;
  font-family: var(--font-accent);
  font-weight: 600;
  color: var(--accent);
  letter-spacing: 0.05em;
}
.split-about {
  display: grid;
  grid-template-columns: 1fr 1.5fr;
  gap: 3rem;
  align-items: start;
}
.split-about-no-photo {
  display: block;
  max-width: 720px;
}
.split-about-photo {
  width: 100%;
  aspect-ratio: 3/4;
  background: var(--bg2) center/cover no-repeat;
  border: 1px solid color-mix(in srgb, var(--accent) 18%, transparent);
}
.split-footer {
  padding: 3rem clamp(1.5rem, 6vw, 5rem) 2rem;
  border-top: 1px solid color-mix(in srgb, var(--accent) 14%, transparent);
  font-size: 0.85rem;
  opacity: 0.7;
  text-align: center;
}
@media (max-width: 768px) {
  .split-hero, .split-about { grid-template-columns: 1fr; gap: 2rem; }
  .split-hero { min-height: auto; padding: 3rem 1.5rem; }
  .split-hero-aside { border-left: none; padding-left: 0; border-top: 1px solid var(--accent); padding-top: 1.5rem; margin-top: 1rem; }
}
"""


def render(context: dict) -> str:
    business_name = safe(context.get("business_name", ""))
    tagline = safe(context.get("tagline", ""))
    tension = safe(context.get("tension_statement", ""))
    philosophy = safe(context.get("philosophy", ""))
    about_me = safe(context.get("about_me") or "")
    practitioner_name = safe(context.get("practitioner_name") or "")

    hero = f"""
<section class="split-hero">
  <div class="split-hero-text">
    <span class="eyebrow">{safe(context.get('industry', 'Practice'))}</span>
    <h1>{business_name}</h1>
    {f'<p class="tension">{tension}</p>' if tension else ''}
    {f'<p>{tagline}</p>' if tagline else ''}
    <a href="#contact" class="cta-button">Begin a Conversation</a>
  </div>
  <aside class="split-hero-aside">
    {philosophy or tagline or business_name}
  </aside>
</section>
"""

    marquee = render_marquee_inline(context)
    statement = render_statement_inline(context, 0)

    # About section: only render when bio passed the synthesis threshold.
    # _compose_about_me_blob returns None when input is too thin, so a missing
    # about_me means "hide this section" rather than "show placeholder text."
    about = ""
    if about_me:
        photo_url = context.get("practitioner_photo_url") or ""
        if photo_url:
            photo_html = (
                f'<div class="split-about-photo" '
                f'style="background-image:url({safe(photo_url)})"></div>'
            )
            grid_class = "split-about"
        else:
            photo_html = ""
            grid_class = "split-about-no-photo"
        about = f"""
<section class="split-section">
  <span class="eyebrow">About</span>
  <h2>{practitioner_name or 'About'}</h2>
  <div class="{grid_class}">
    {photo_html}
    <div>
      <p>{about_me}</p>
    </div>
  </div>
</section>
"""

    products_html = ""
    products = context.get("products") or []
    if products:
        cards = ""
        for p in products[:8]:
            if not isinstance(p, dict):
                continue
            name = safe(p.get("name", ""))
            desc = safe(p.get("description") or "")
            price = p.get("price")
            price_str = f'<span class="split-card-price">${price}</span>' if price else ""
            cards += f"""
<div class="split-card">
  <h3>{name}</h3>
  {f'<p>{desc}</p>' if desc else ''}
  {price_str}
</div>
"""
        if cards:
            products_html = f"""
<section class="split-section">
  <span class="eyebrow">Offerings</span>
  <h2>What's Available</h2>
  <div class="split-grid">
    {cards}
  </div>
</section>
"""
    else:
        # Soft fallback when the catalog is empty — render a brief
        # "currently accepting conversations" block so the page doesn't
        # leave a void where offerings would go.
        contact_email = context.get("contact_email") or ""
        if contact_email:
            contact_line = (
                f'Reach out: <a href="mailto:{safe(contact_email)}">'
                f'{safe(contact_email)}</a>.'
            )
        else:
            contact_line = "Use the form below to begin."
        products_html = f"""
<section class="split-section split-section-soft">
  <span class="eyebrow">Inquiries</span>
  <h2>Currently Accepting Conversations</h2>
  <p>This practice works through invitation and conversation. {contact_line}</p>
</section>
"""

    footer = f"""
<footer class="split-footer">
  <p>&copy; 2026 {business_name}. All rights reserved.</p>
</footer>
"""

    body = f"""
<div class="split-page">
  {hero}
  {marquee}
  {statement}
  {about}
  {products_html}
  {footer}
</div>
"""

    custom_styles = render_styles(context)
    scripts = render_motion_modules_scripts(context)
    return base_html_shell(context, body, custom_styles, scripts)
