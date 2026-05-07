"""Statement archetype — massive text hero, no image, manifesto register.
Best for brand statements, single-message positioning, high-conviction practices.
"""
from __future__ import annotations
from studio_archetypes._shared import (
    safe, base_html_shell, base_styles,
    render_motion_modules_styles, render_motion_modules_scripts,
    render_marquee_inline, render_statement_inline,
)


def render_styles(context: dict) -> str:
    return base_styles(context) + render_motion_modules_styles(context) + """
.statement-page { max-width: 100%; }
.statement-hero {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: clamp(3rem, 8vh, 5rem) clamp(1.5rem, 6vw, 5rem);
  position: relative;
}
.statement-hero h1 {
  font-size: clamp(3rem, 12vw, 10rem);
  line-height: 0.95;
  letter-spacing: -0.04em;
  font-weight: 700;
  margin-bottom: 2rem;
  max-width: 14ch;
}
.statement-hero .tension {
  font-family: var(--font-display);
  font-style: italic;
  font-size: clamp(1.3rem, 2vw, 1.8rem);
  max-width: 45ch;
  margin-bottom: 3rem;
  opacity: 0.9;
}
.statement-meta {
  display: flex;
  gap: 2rem;
  flex-wrap: wrap;
  font-family: var(--font-accent);
  font-size: 0.85rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--accent);
}
.statement-section {
  padding: clamp(4rem, 10vh, 7rem) clamp(1.5rem, 6vw, 5rem);
  max-width: 980px;
  margin: 0 auto;
}
.statement-section h2 {
  font-size: clamp(2rem, 5vw, 3.5rem);
  margin-bottom: 1.5rem;
}
.statement-section p {
  font-size: 1.15rem;
  line-height: 1.8;
}
.statement-cta {
  text-align: left;
  padding: clamp(3rem, 6vh, 5rem) clamp(1.5rem, 6vw, 5rem);
  border-top: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
}
.statement-footer {
  padding: 2rem clamp(1.5rem, 6vw, 5rem);
  font-size: 0.8rem;
  opacity: 0.6;
}
"""


def render(context: dict) -> str:
    business_name = safe(context.get("business_name", ""))
    tagline = safe(context.get("tagline", ""))
    tension = safe(context.get("tension_statement", ""))
    philosophy = safe(context.get("philosophy", ""))
    industry = safe(context.get("industry", ""))
    mood = safe(context.get("mood", ""))

    headline = tagline or business_name
    hero = f"""
<section class="statement-hero">
  <h1>{headline}</h1>
  {f'<p class="tension">{tension}</p>' if tension else ''}
  <div class="statement-meta">
    {f'<span>{industry}</span>' if industry else ''}
    {f'<span>{mood}</span>' if mood else ''}
    <span>{business_name}</span>
  </div>
</section>
"""

    marquee = render_marquee_inline(context)
    statement = render_statement_inline(context, 0)

    philosophy_block = ""
    if philosophy:
        philosophy_block = f"""
<section class="statement-section">
  <span class="eyebrow">Position</span>
  <h2>What This Is</h2>
  <p>{philosophy}</p>
</section>
"""

    cta = f"""
<div class="statement-cta">
  <a href="#contact" class="cta-button">Begin</a>
</div>
"""

    footer = f"""
<footer class="statement-footer">&copy; 2026 {business_name}</footer>
"""

    body = f"""
<div class="statement-page">
  {hero}
  {marquee}
  {statement}
  {philosophy_block}
  {cta}
  {footer}
</div>
"""

    custom_styles = render_styles(context)
    scripts = render_motion_modules_scripts(context)
    return base_html_shell(context, body, custom_styles, scripts)
