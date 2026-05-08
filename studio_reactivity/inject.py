"""Orchestrates injection of the Pass 3.8e reactivity layer into HTML.

Composes micro-interactions + scroll behaviors + strand-aware gradients
into a CSS block (injected before </head>) and a JS block (injected
before </body>). Every step is wrapped in try/except so a single module
failure can never prevent the page from rendering.
"""
from __future__ import annotations
from typing import Optional
import sys


def render_reactivity_styles(brief: Optional[dict]) -> str:
    """Combine reactivity styles: micro-interactions + scroll behaviors +
    strand-specific gradients (only if a brief is supplied).
    """
    parts = []

    try:
        from studio_reactivity.micro_interactions import render_styles as mi_styles
        parts.append(mi_styles())
    except Exception as e:
        print(f"[reactivity] micro_interactions styles failed: {e}", file=sys.stderr)

    try:
        from studio_reactivity.scroll_behaviors import render_styles as sb_styles
        parts.append(sb_styles())
    except Exception as e:
        print(f"[reactivity] scroll_behaviors styles failed: {e}", file=sys.stderr)

    try:
        from studio_reactivity.strand_gradients import (
            render_styles_for_strand,
            parse_dominant_strand,
            parse_palette_from_brief,
        )
        if brief:
            strand = parse_dominant_strand(brief)
            palette = parse_palette_from_brief(brief)
            if strand and palette:
                parts.append(render_styles_for_strand(strand, palette))
    except Exception as e:
        print(f"[reactivity] strand_gradients failed: {e}", file=sys.stderr)

    # Pass 3.8g — Solutionist motion (film grain, shimmer, pulse glow,
    # signature reveal timing, accent-word styling). Behind the
    # SOLUTIONIST_QUALITY_ENABLED kill switch so we can disable the
    # entire layer with a config flip.
    try:
        from studio_config import SOLUTIONIST_QUALITY_ENABLED
        if SOLUTIONIST_QUALITY_ENABLED:
            from studio_reactivity.solutionist_motion import render_solutionist_styles
            parts.append(render_solutionist_styles())
    except Exception as e:
        print(f"[reactivity] solutionist_motion failed: {e}", file=sys.stderr)

    return "\n".join(p for p in parts if p)


def render_reactivity_scripts() -> str:
    """Combine reactivity JS — currently just scroll_behaviors."""
    parts = []
    try:
        from studio_reactivity.scroll_behaviors import render_script as sb_script
        parts.append(sb_script())
    except Exception as e:
        print(f"[reactivity] scroll_behaviors script failed: {e}", file=sys.stderr)
    return "\n".join(p for p in parts if p)


def inject_reactivity(html: str, brief: Optional[dict]) -> str:
    """Inject reactivity layer into HTML.

    - Styles inserted just before </head>
    - Scripts inserted just before </body>
    - Try/except wrapped: any failure returns the original html unchanged.
    """
    if not html or not isinstance(html, str):
        return html

    try:
        styles = render_reactivity_styles(brief)
        scripts = render_reactivity_scripts()

        if styles:
            if "</head>" in html:
                html = html.replace("</head>", f"{styles}\n</head>", 1)
            elif "</HEAD>" in html:
                html = html.replace("</HEAD>", f"{styles}\n</HEAD>", 1)

        if scripts:
            if "</body>" in html:
                html = html.replace("</body>", f"{scripts}\n</body>", 1)
            elif "</BODY>" in html:
                html = html.replace("</BODY>", f"{scripts}\n</BODY>", 1)
    except Exception as e:
        print(f"[reactivity] inject_reactivity failed: {e}", file=sys.stderr)
        return html

    return html
