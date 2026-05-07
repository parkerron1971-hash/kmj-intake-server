"""Shared utilities for all archetype renderers."""
from __future__ import annotations
import html as html_module
import sys


def safe(text) -> str:
    """HTML-escape text. Tolerant of None."""
    if text is None:
        return ""
    return html_module.escape(str(text))


def google_fonts_url(typography: dict) -> str:
    """Build Google Fonts import URL from typography spec."""
    families = []
    seen = set()
    for slot in ("display", "body", "accent"):
        slot_val = (typography or {}).get(slot) or {}
        font = slot_val.get("name")
        if font and font not in seen:
            families.append(font)
            seen.add(font)
    if not families:
        families.append("Inter")
    parts = []
    for family in families:
        parts.append(f"family={family.replace(' ', '+')}:wght@300;400;500;600;700")
    return "https://fonts.googleapis.com/css2?" + "&".join(parts) + "&display=swap"


def base_html_shell(context: dict, body: str, custom_styles: str, scripts: str = "") -> str:
    """Wrap body in HTML5 doctype + head with Google Fonts + custom styles."""
    title = safe(context.get("business_name", ""))
    if context.get("concept_name"):
        title = f"{title} — {safe(context['concept_name'])}"
    fonts_url = google_fonts_url(context.get("typography") or {})

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{fonts_url}" rel="stylesheet">
<style>{custom_styles}</style>
</head>
<body>
{body}
{scripts}
</body>
</html>"""


def render_motion_modules_styles(context: dict) -> str:
    """Output CSS for any motion modules enabled by scheme."""
    parts = []
    palette = context.get("palette") or {}
    pseudo_ds_full = {
        "palette_accent": palette.get("accent", "#c9a84c"),
        "palette_text": palette.get("text", "#f4f4f4"),
        "palette_surface": palette.get("background", "#0a0a0a"),
    }
    try:
        if context.get("enable_ghost_numbers"):
            from studio_layouts.motion_modules.ghost_numbers import render_styles as gn
            parts.append(gn())
        if context.get("enable_marquee_strips"):
            from studio_layouts.motion_modules.marquee_strip import render_styles as ms
            parts.append(ms(pseudo_ds_full))
        if context.get("enable_magnetic_buttons"):
            from studio_layouts.motion_modules.magnetic_button import render_styles as mb
            parts.append(mb())
        if context.get("enable_statement_bars"):
            from studio_layouts.motion_modules.statement_bar import render_styles as sb
            parts.append(sb(pseudo_ds_full))
    except Exception as e:
        print(f"[archetypes._shared] motion module styles failed: {e}", file=sys.stderr)
    return "\n".join(parts)


def render_motion_modules_scripts(context: dict) -> str:
    """Output JS for any motion modules enabled by scheme."""
    parts = []
    try:
        if context.get("enable_ghost_numbers"):
            from studio_layouts.motion_modules.ghost_numbers import render_script as gn_s
            parts.append(gn_s())
        if context.get("enable_magnetic_buttons"):
            from studio_layouts.motion_modules.magnetic_button import render_script as mb_s
            parts.append(mb_s())
    except Exception as e:
        print(f"[archetypes._shared] motion module scripts failed: {e}", file=sys.stderr)
    return "\n".join(parts)


def render_marquee_inline(context: dict) -> str:
    if not context.get("enable_marquee_strips") or not context.get("marquee_text"):
        return ""
    try:
        from studio_layouts.motion_modules.marquee_strip import render_inline
        return render_inline(context["marquee_text"])
    except Exception:
        return ""


def render_statement_inline(context: dict, index: int = 0) -> str:
    quotes = context.get("statement_bar_quotes") or []
    if not context.get("enable_statement_bars") or not quotes or index >= len(quotes):
        return ""
    try:
        from studio_layouts.motion_modules.statement_bar import render_inline
        return render_inline(quotes[index])
    except Exception:
        return ""


def base_styles(context: dict) -> str:
    """CSS variables + reset + universal styles all archetypes share."""
    palette = context.get("palette") or {}
    typography = context.get("typography") or {}
    display_font = (typography.get("display") or {}).get("name", "Inter")
    body_font = (typography.get("body") or {}).get("name", "Inter")
    accent_font = (typography.get("accent") or {}).get("name", "Inter")

    bg = palette.get("background", "#0a0a0a")
    bg2 = palette.get("secondary", "#13131a")
    text = palette.get("text", "#f4f4f4")
    accent = palette.get("accent", "#c9a84c")
    primary = palette.get("primary", accent)
    highlight = palette.get("highlight", text)

    return f"""
*, *::before, *::after {{ box-sizing: border-box; }}
html, body {{
  margin: 0;
  padding: 0;
  background: {bg};
  color: {text};
  font-family: '{body_font}', -apple-system, sans-serif;
  font-size: 16px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}}
:root {{
  --bg: {bg};
  --bg2: {bg2};
  --text: {text};
  --accent: {accent};
  --primary: {primary};
  --highlight: {highlight};
  --font-display: '{display_font}', Georgia, serif;
  --font-body: '{body_font}', sans-serif;
  --font-accent: '{accent_font}', sans-serif;
}}
h1, h2, h3, h4 {{ font-family: var(--font-display); margin: 0; line-height: 1.15; }}
h1 {{ font-size: clamp(2.5rem, 6vw, 5rem); letter-spacing: -0.02em; font-weight: 700; }}
h2 {{ font-size: clamp(1.8rem, 4vw, 3rem); letter-spacing: -0.01em; font-weight: 600; }}
h3 {{ font-size: clamp(1.3rem, 2.5vw, 2rem); font-weight: 600; }}
p {{ margin: 0 0 1.2em 0; max-width: 65ch; }}
a {{ color: {accent}; text-decoration: none; }}
.eyebrow {{
  font-family: var(--font-accent);
  font-size: 0.78rem;
  letter-spacing: 0.24em;
  text-transform: uppercase;
  color: {accent};
  font-weight: 500;
  margin-bottom: 0.6rem;
  display: inline-block;
}}
.cta-button {{
  display: inline-block;
  padding: 0.95rem 1.7rem;
  background: {accent};
  color: {bg};
  font-family: var(--font-accent);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-size: 0.85rem;
  border: none;
  cursor: pointer;
  transition: transform 0.2s ease;
}}
.cta-button:hover {{ transform: translateY(-2px); }}
.section-divider {{
  height: 1px;
  background: linear-gradient(to right, transparent, {accent} 20%, {accent} 80%, transparent);
  margin: 2rem 0;
  opacity: 0.3;
}}
@media (max-width: 768px) {{
  body {{ font-size: 15px; }}
}}
"""
