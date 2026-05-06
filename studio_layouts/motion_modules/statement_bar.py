"""Statement bar: full-width quote band between sections."""
from studio_layouts.shared import safe_html


def render_styles(design_system) -> str:
    accent = design_system.get('palette_accent', '#C9A84C')
    text = design_system.get('palette_text', '#F5F5F5')
    bg = design_system.get('palette_surface', '#1a1a1a')
    return f"""
<style>
.statement-bar {{
  padding: 1.6rem clamp(1.5rem, 5vw, 2.5rem);
  background: color-mix(in srgb, {accent} 4%, {bg});
  border-top: 1px solid color-mix(in srgb, {accent} 25%, transparent);
  border-bottom: 1px solid color-mix(in srgb, {accent} 25%, transparent);
  text-align: center;
}}
.statement-bar p {{
  font-family: var(--font-display, Georgia, serif);
  font-size: clamp(1.05rem, 2vw, 1.4rem);
  letter-spacing: 0.02em;
  color: {text};
  margin: 0 auto;
  font-style: italic;
  max-width: 800px;
}}
</style>
"""


def render_inline(quote: str) -> str:
    if not quote:
        return ""
    return f"""
<section class="statement-bar">
  <p>{safe_html(quote)}</p>
</section>
"""
