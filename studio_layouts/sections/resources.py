"""Shared resources / lead-magnets section renderer."""
from __future__ import annotations

from typing import Any, Dict, List

from studio_design_system import DesignSystem, _pick_contrast_text
from studio_layouts.shared import safe_html


_TYPE_ICONS = {
    "pdf": "PDF",
    "video": "Video",
    "audio": "Audio",
    "link": "Link",
    "doc": "Doc",
}


def render(
    design_system: DesignSystem,
    items: List[Dict[str, Any]],
    section_config: Dict[str, Any],
    bundle: Dict[str, Any],
) -> str:
    """items: list of {title, description, link, type}.
    type: 'pdf' | 'video' | 'audio' | 'link' | 'doc'.
    """
    if not items or not section_config.get("enabled", False):
        return ""

    accent = design_system["palette_accent"]
    text = design_system["palette_text"]
    surface = design_system["palette_surface"]
    surface_text = _pick_contrast_text(surface, dark_color=text)
    display_font = design_system["font_display"]

    cards: List[str] = []
    for item in items[:8]:
        title = safe_html(item.get("title", "Resource"))
        desc = safe_html(item.get("description", ""))
        link = safe_html(item.get("link", "#"))
        rtype = (item.get("type") or "link").lower()
        type_label = _TYPE_ICONS.get(rtype, "Link")
        desc_html = (
            f'<div style="font-size:0.9rem;color:color-mix(in srgb,{surface_text} 75%,transparent);line-height:1.5;">{desc}</div>'
            if desc else ''
        )
        cards.append(f"""
<a href="{link}" target="_blank" rel="noopener" style="display:block;padding:24px;background:{surface};color:{surface_text};border-radius:6px;border:1px solid color-mix(in srgb,{text} 10%,transparent);text-decoration:none;transition:transform 0.2s ease;">
  <div style="font-family:'{display_font}',Georgia,serif;font-size:0.7rem;letter-spacing:0.18em;text-transform:uppercase;color:{accent};margin-bottom:0.75rem;">{type_label}</div>
  <div style="font-weight:600;font-size:1.1rem;margin-bottom:0.5rem;color:{surface_text};">{title}</div>
  {desc_html}
  <div style="margin-top:1rem;font-size:0.85rem;color:{accent};font-weight:500;">Download &rarr;</div>
</a>""")

    if not cards:
        return ""

    heading = safe_html(section_config.get("heading") or "Free Resources")
    subtext = safe_html(section_config.get("subtext") or "")
    subtext_html = (
        f'<p style="font-size:1.1rem;color:color-mix(in srgb,{text} 70%,transparent);margin:0 0 3rem;max-width:600px;">{subtext}</p>'
        if subtext else ''
    )
    return f"""
<section style="max-width:1200px;margin:0 auto;padding:96px 48px;">
  <h2 style="font-family:'{display_font}',Georgia,serif;font-size:2rem;margin:0 0 1rem;color:{text};">
    {heading}
  </h2>
  {subtext_html}
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;">
    {''.join(cards)}
  </div>
</section>
"""
