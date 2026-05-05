"""Shared gallery section renderer."""
from __future__ import annotations

from typing import Any, Dict, List

from studio_design_system import DesignSystem
from studio_layouts.shared import safe_html


def render(
    design_system: DesignSystem,
    items: List[Dict[str, Any]],
    section_config: Dict[str, Any],
    bundle: Dict[str, Any],
) -> str:
    """items: list of {image_url, caption, order}."""
    if not items or not section_config.get("enabled", False):
        return ""

    text = design_system["palette_text"]
    display_font = design_system["font_display"]

    images: List[str] = []
    for item in items[:12]:
        url = safe_html(item.get("image_url", ""))
        caption = safe_html(item.get("caption", ""))
        if not url:
            continue
        caption_html = (
            f'<figcaption style="font-size:0.85rem;color:color-mix(in srgb,{text} 70%,transparent);margin-top:0.5rem;">{caption}</figcaption>'
            if caption else ''
        )
        images.append(f"""
<figure style="margin:0;">
  <img src="{url}" alt="{caption}" style="width:100%;height:280px;object-fit:cover;border-radius:4px;display:block;" loading="lazy">
  {caption_html}
</figure>""")

    if not images:
        return ""

    heading = safe_html(section_config.get("heading") or "Gallery")
    return f"""
<section style="max-width:1200px;margin:0 auto;padding:96px 48px;">
  <h2 style="font-family:'{display_font}',Georgia,serif;font-size:2rem;margin:0 0 3rem;color:{text};">
    {heading}
  </h2>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:24px;">
    {''.join(images)}
  </div>
</section>
"""
