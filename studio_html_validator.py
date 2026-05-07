"""HTML/CSS validation for Builder Agent output (Pass 3.8d).

Binary verdict: passes (ship it) or fails (fall back to 3.8c archetype).
Also handles motion-module injection for Pass 3.7c interactivity layers
(ghost numbers, magnetic buttons) into the LLM-produced shell.
"""
from __future__ import annotations
import re
import sys
from typing import List, Optional, Tuple


# Banned patterns — anything matching these is rejected. Keep these tight:
# the goal is to keep Builder output safe to serve directly to end users.
BANNED_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # No external scripts — the platform injects motion JS itself, the LLM
    # may not import third-party JS. Google Fonts CSS is allowed via <link>;
    # see the stylesheet rule below.
    (re.compile(r'<script[^>]*\ssrc=', re.IGNORECASE),
     "External script not allowed"),
    # Inline <script> blocks are also out — motion modules are the only JS
    # we run on Builder pages and they are injected post-validation.
    (re.compile(r'<script(?![^>]*\bsrc=)[^>]*>', re.IGNORECASE),
     "Inline <script> not allowed"),
    (re.compile(r'<iframe[^>]*\ssrc=', re.IGNORECASE),
     "Iframes not allowed"),
    # No inline JS event handlers
    (re.compile(r'\son(click|load|error|mouseover|submit|focus|blur|change|input)\s*=',
                re.IGNORECASE),
     "Inline event handlers not allowed"),
    # No data: URIs that could carry payloads (allow data: for inline SVG).
    (re.compile(r'\ssrc=["\']data:(?!image/svg)', re.IGNORECASE),
     "data: URIs only allowed for inline SVG"),
    # No external stylesheets except Google Fonts
    (re.compile(
        r'<link[^>]*\srel=["\']?stylesheet["\']?[^>]*\shref=["\']?'
        r'(?!https://fonts\.)',
        re.IGNORECASE),
     "External stylesheet not allowed (only Google Fonts)"),
    # No javascript: URIs
    (re.compile(r'\shref=["\']?\s*javascript:', re.IGNORECASE),
     "javascript: URIs not allowed"),
    # No expression() or @import in CSS
    (re.compile(r'expression\s*\(', re.IGNORECASE),
     "CSS expression() not allowed"),
    (re.compile(r'@import\s+url\s*\(', re.IGNORECASE),
     "CSS @import not allowed"),
]


def validate_html(html: str) -> Tuple[bool, List[str]]:
    """Validate Builder output. Returns (is_valid, error_messages)."""
    errors: List[str] = []

    if not html or not isinstance(html, str):
        return False, ["Output is empty or not a string"]

    html_stripped = html.strip()

    # Must start with DOCTYPE
    if not html_stripped.lower().startswith("<!doctype html"):
        errors.append("Must start with <!DOCTYPE html>")

    # Must contain html, head, body tags
    lower = html.lower()
    for tag in ("<html", "<head", "<body"):
        if tag not in lower:
            errors.append(f"Missing required tag: {tag}>")

    # Must have closing tags
    for tag in ("</html>", "</head>", "</body>"):
        if tag not in lower:
            errors.append(f"Missing closing tag: {tag}")

    # Tag balance check (basic)
    open_count = lower.count("<html")
    close_count = lower.count("</html>")
    if open_count != close_count:
        errors.append(
            f"<html> tag imbalance: {open_count} opens, {close_count} closes"
        )

    # Banned pattern check
    for pattern, message in BANNED_PATTERNS:
        if pattern.search(html):
            errors.append(f"Banned pattern: {message}")

    # Must have a <title>
    if not re.search(r"<title>[^<]+</title>", html, re.IGNORECASE):
        errors.append("Missing <title> tag")

    # Length sanity check
    if len(html) < 1000:
        errors.append(
            f"Output suspiciously short ({len(html)} chars) — likely incomplete"
        )
    if len(html) > 200000:
        errors.append(
            f"Output suspiciously long ({len(html)} chars) — possible corruption"
        )

    # Must contain a <style> block (we expect inline CSS, not external)
    if "<style" not in lower:
        errors.append("Missing <style> block — Builder must inline CSS")

    return len(errors) == 0, errors


def strip_markdown_fences(text: str) -> str:
    """Remove ``` markdown fences if the model wrapped its output."""
    if not text:
        return ""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Drop opening fence (with optional language tag)
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        # Drop closing fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def extract_html_from_response(raw: str) -> Optional[str]:
    """Extract HTML from a raw Builder response.

    Tolerates markdown fences and a small amount of preamble before the
    first DOCTYPE / <html>. Returns None if neither marker is found.
    """
    if not raw:
        return None

    cleaned = strip_markdown_fences(raw)
    lower = cleaned.lower()

    doctype_idx = lower.find("<!doctype html")
    if doctype_idx >= 0:
        return cleaned[doctype_idx:].strip()

    # Fallback: model may have skipped DOCTYPE.
    html_idx = lower.find("<html")
    if html_idx >= 0:
        return cleaned[html_idx:].strip()

    return None


def inject_motion_modules(html: str, scheme: Optional[dict]) -> str:
    """Inject Pass 3.7c motion module styles + scripts into Builder HTML.

    Adds CSS just before </head> and JS just before </body>. Only the JS-
    bearing modules (ghost_numbers, magnetic_button) are injected here:
    marquee_strip and statement_bar are inline-call modules that need a
    design-system arg and a bespoke render site, so the Builder is
    expected to author those itself if its brief mentions them.
    """
    if not html or not scheme:
        return html

    motion = scheme.get("motion_richness") or {}
    needs_ghost = bool(motion.get("enable_ghost_numbers"))
    needs_magnetic = bool(motion.get("enable_magnetic_buttons"))

    if not (needs_ghost or needs_magnetic):
        return html

    style_parts: List[str] = []
    script_parts: List[str] = []

    try:
        if needs_ghost:
            from studio_layouts.motion_modules.ghost_numbers import (
                render_styles as gn_styles, render_script as gn_script,
            )
            style_parts.append(gn_styles())
            script_parts.append(gn_script())
        if needs_magnetic:
            from studio_layouts.motion_modules.magnetic_button import (
                render_styles as mb_styles, render_script as mb_script,
            )
            style_parts.append(mb_styles())
            script_parts.append(mb_script())
    except Exception as e:
        print(f"[validator] motion injection failed: {e}", file=sys.stderr)
        return html

    # Inject styles before </head>. Try lowercase first (most common), then
    # uppercase as a defensive fallback.
    if style_parts:
        injected_style = "\n".join(p for p in style_parts if p)
        if "</head>" in html:
            html = html.replace("</head>", f"{injected_style}\n</head>", 1)
        elif "</HEAD>" in html:
            html = html.replace("</HEAD>", f"{injected_style}\n</HEAD>", 1)

    # Inject scripts before </body>
    if script_parts:
        injected_scripts = "\n".join(p for p in script_parts if p)
        if "</body>" in html:
            html = html.replace("</body>", f"{injected_scripts}\n</body>", 1)
        elif "</BODY>" in html:
            html = html.replace("</BODY>", f"{injected_scripts}\n</BODY>", 1)

    return html
