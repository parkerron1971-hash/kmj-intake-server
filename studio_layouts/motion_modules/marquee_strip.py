"""Marquee strip: scrolling text band between sections."""
from studio_layouts.shared import safe_html


def render_styles(design_system) -> str:
    """CSS for marquee. Include once per page."""
    accent = design_system.get('palette_accent', '#C9A84C')
    return f"""
<style>
.marquee-strip {{
  display: flex;
  overflow: hidden;
  white-space: nowrap;
  border-top: 1px solid {accent};
  border-bottom: 1px solid {accent};
  padding: 0.7rem 0;
  background: color-mix(in srgb, {accent} 4%, transparent);
}}
.marquee-track {{
  display: inline-flex;
  animation: marquee-scroll 28s linear infinite;
  font-family: var(--font-accent, sans-serif);
  font-size: 0.78rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: {accent};
  font-weight: 500;
  padding-left: 2rem;
}}
@keyframes marquee-scroll {{
  from {{ transform: translateX(0); }}
  to {{ transform: translateX(-50%); }}
}}
@media (prefers-reduced-motion: reduce) {{
  .marquee-track {{ animation: none; }}
}}
</style>
"""


def render_inline(text: str) -> str:
    """Render a marquee strip with the given dot-separated keywords."""
    if not text:
        return ""
    safe = safe_html(text)
    duplicated = f"{safe} • {safe}"
    return f"""
<div class="marquee-strip" aria-hidden="true">
  <div class="marquee-track">{duplicated}</div>
</div>
"""
