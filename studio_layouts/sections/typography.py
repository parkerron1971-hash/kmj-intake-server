"""Pass 3.7 — typography richness helpers.

Pull quotes, drop caps, eyebrow text, accent labels. Each is a small
helper layouts can call where the layout's character supports it.
The drop-cap function consults studio_decoration.get_vocab_accent_set()
to skip the treatment when the vocabulary's accent set says
`drop_cap_style: 'none'` (e.g. minimalist).
"""
from __future__ import annotations

from typing import Optional

from studio_decoration import get_vocab_accent_set
from studio_design_system import DesignSystem
from studio_layouts.shared import safe_html


def render_pull_quote(text: str, design_system: DesignSystem, vocab_id: Optional[str] = None) -> str:
    """Render a large pull-out quote. Inserted between paragraphs.
    Empty string when text is falsy."""
    if not text:
        return ""
    accent = design_system["palette_accent"]
    text_color = design_system["palette_text"]
    display = design_system["font_display"]
    return f"""
<blockquote class="reveal" style="border-left:4px solid {accent};padding:1.5rem 2rem;margin:2rem 0;font-family:'{display}',Georgia,serif;font-size:clamp(1.4rem,2.5vw,1.8rem);font-style:italic;line-height:1.4;color:{text_color};">
  {safe_html(text)}
</blockquote>
"""


def render_drop_cap_paragraph(paragraph: str, design_system: DesignSystem, vocab_id: Optional[str] = None) -> str:
    """First letter is dropped to capital. Vocabularies with
    `drop_cap_style: 'none'` (minimalist, rising-entrepreneur, etc.) get
    a plain paragraph instead. Empty input → empty string."""
    if not paragraph:
        return ""
    if len(paragraph) < 2:
        return f'<p>{safe_html(paragraph)}</p>'

    accent_set = get_vocab_accent_set(vocab_id)
    if accent_set.get("drop_cap_style") == "none":
        return f'<p>{safe_html(paragraph)}</p>'

    first = safe_html(paragraph[0])
    rest = safe_html(paragraph[1:])
    accent = design_system["palette_accent"]
    display = design_system["font_display"]

    return (
        f'<p style="font-size:1.05rem;line-height:1.7;">'
        f'<span style="float:left;font-family:\'{display}\',Georgia,serif;font-size:4.5rem;line-height:0.8;padding:0.4rem 0.5rem 0 0;color:{accent};font-weight:bold;">{first}</span>'
        f'{rest}</p>'
    )


def render_eyebrow(text: str, design_system: DesignSystem, vocab_id: Optional[str] = None) -> str:
    """Small label above headings. Standard typographic pattern."""
    if not text:
        return ""
    accent = design_system["palette_accent"]
    body = design_system["font_body"]
    return (
        f'<div style="font-family:\'{body}\',sans-serif;font-size:0.75rem;'
        f'letter-spacing:0.3em;text-transform:uppercase;color:{accent};'
        f'margin-bottom:0.75rem;">{safe_html(text)}</div>'
    )


def render_label(text: str, design_system: DesignSystem, vocab_id: Optional[str] = None) -> str:
    """Small all-caps inline label for emphasizing a category."""
    if not text:
        return ""
    accent = design_system["palette_accent"]
    body = design_system["font_body"]
    return (
        f'<span style="font-family:\'{body}\',sans-serif;font-size:0.85rem;'
        f'letter-spacing:0.15em;text-transform:uppercase;font-weight:600;'
        f'color:{accent};">{safe_html(text)}</span>'
    )
