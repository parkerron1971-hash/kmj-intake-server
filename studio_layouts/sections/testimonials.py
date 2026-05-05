"""Shared testimonials section renderer.

Vocabulary-aware: adapts color/typography to design_system. Layouts can
override with their own bespoke renderer (e.g. community_hub).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from studio_design_system import DesignSystem, _pick_contrast_text
from studio_layouts.shared import safe_html


def render(
    design_system: DesignSystem,
    items: List[Dict[str, Any]],
    section_config: Dict[str, Any],
    bundle: Dict[str, Any],
    vocab_id: Optional[str] = None,
) -> str:
    """items: list of {quote, author, role, date}.
    Pass 3.7: vocab_id added for future decoration hooks (currently
    unused in shared renderer; bespoke overrides may use it)."""
    if not items or not section_config.get("enabled", False):
        return ""

    accent = design_system["palette_accent"]
    text = design_system["palette_text"]
    surface = design_system["palette_surface"]
    surface_text = _pick_contrast_text(surface, dark_color=text)
    display_font = design_system["font_display"]

    cards: List[str] = []
    for item in items[:6]:
        quote = safe_html(item.get("quote", ""))
        author = safe_html(item.get("author", ""))
        role = safe_html(item.get("role", ""))
        if not quote:
            continue
        role_html = (
            f'<div style="font-size:0.85rem;color:color-mix(in srgb,{surface_text} 70%,transparent);margin-top:0.25rem;">{role}</div>'
            if role else ''
        )
        cards.append(f"""
<div class="hover-lift reveal" style="padding:32px;background:{surface};color:{surface_text};border-radius:8px;border:1px solid color-mix(in srgb,{text} 12%,transparent);">
  <div style="font-family:'{display_font}',Georgia,serif;font-size:2.5rem;color:{accent};line-height:1;margin-bottom:1rem;">&ldquo;</div>
  <p style="font-size:1.05rem;line-height:1.6;color:{surface_text};margin:0 0 1.5rem;">{quote}</p>
  <div style="font-weight:600;color:{surface_text};">{author}</div>
  {role_html}
</div>""")

    if not cards:
        return ""

    heading = safe_html(section_config.get("heading") or "What clients say")
    return f"""
<section style="max-width:1200px;margin:0 auto;padding:96px 48px;">
  <h2 style="font-family:'{display_font}',Georgia,serif;font-size:2rem;margin:0 0 3rem;color:{text};text-align:center;">
    {heading}
  </h2>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px;">
    {''.join(cards)}
  </div>
</section>
"""
