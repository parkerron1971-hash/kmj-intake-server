"""Pass 3.8g — Solutionist Quality measurable rules + prompt block + validator.

Encodes the visual quality ceiling from the Solutionist Design System
document into three things:

  1. Constants (HARD_RULES, SOLUTIONIST_COMPONENTS, SOLUTIONIST_ANIMATIONS)
     — referenced when other modules need to know "what is the canonical
     section padding?" without re-deriving from prose.
  2. get_quality_rules_block_for_prompt() — the directive paragraph
     embedded in the Builder prompt. This is what actually makes Builder
     output Solutionist-grade.
  3. validate_solutionist_quality(html) — heuristic post-build check
     against measurable rules (border-radius, padding, headings, white
     usage, italic accent words). Returns (ok, warnings) the same shape
     as Pass 3.8f's validate_quality so build_html can append the lists.
"""
from __future__ import annotations

import re
from typing import List, Tuple


# ─── HARD_RULES ───────────────────────────────────────────────────────
# The canonical numeric ceilings. Other modules read from here so a
# change here propagates everywhere.
HARD_RULES = {
    "section_padding_min": 80,
    "section_padding_ideal": 120,
    "card_border_radius_min": 20,
    "card_border_radius_ideal": 28,
    "button_pill_radius": 999,
    "heading_weight_min": 700,
    "heading_weight_ideal": 900,
    "warm_white_bg": "#F8F6F1",
    "warm_white_text_on_dark": "#F4F0E8",
    "easing_curve": "cubic-bezier(0.16, 1, 0.3, 1)",
    "animation_duration": "0.9s",
    "italic_accent_word_rule": True,
    "gold_accent_line_before_heading": True,
    "film_grain_overlay": True,
    "scroll_reveals_on_sections": True,
}


# ─── Component spec — used by primitives when producing patterns ──────
SOLUTIONIST_COMPONENTS = {
    "buttons": {
        "primary_cta": {
            "shape": "pill",
            "radius": "999px",
            "padding": "20px 48px",
            "font_weight": 800,
            "font_size": "13px",
            "letter_spacing": "3px",
            "text_transform": "uppercase",
            "shimmer_animation": True,
            "hover_lift": "-3px",
            "transition": "0.4s cubic-bezier(0.16, 1, 0.3, 1)",
        },
        "secondary": {
            "shape": "pill",
            "radius": "999px",
            "padding": "18px 44px",
            "font_weight": 800,
            "transition": "0.4s cubic-bezier(0.16, 1, 0.3, 1)",
        },
    },
    "cards": {
        "standard": {
            "border_radius": "28px",
            "padding": "48px 40px",
            "padding_mobile": "28px 22px",
            "hover_lift": "-8px",
            "hover_shadow": "0 40px 80px rgba(0,0,0,0.15)",
            "transition": "0.5s cubic-bezier(0.16, 1, 0.3, 1)",
        },
        "dark_variant": {
            "border_radius": "28px",
            "gold_top_line_on_hover": True,
            "background": "rgba(255,255,255,0.02)",
            "border": "1px solid rgba(255,255,255,0.04)",
        },
    },
    "headings": {
        "h1_hero": {
            "scale": "clamp(3.7rem, 9vw, 5.4rem)",
            "weight": 900,
            "letter_spacing": "-2.4px",
            "italic_accent_word": True,
        },
        "h2_section": {
            "scale": "clamp(2.4rem, 5vw, 3.5rem)",
            "weight": 800,
            "letter_spacing": "-1.6px",
            "italic_accent_word": True,
        },
        "eyebrow": {
            "size": "12px",
            "weight": 700,
            "letter_spacing": "4-5px",
            "text_transform": "uppercase",
            "preceded_by_gold_line": True,
        },
    },
    "spacing": {
        "section_padding_desktop": "120-140px top/bottom, 48px sides",
        "section_padding_mobile": "80px top/bottom, 20px sides",
        "card_gap": "28px",
        "max_width_content": "1100px",
        "max_width_text": "800-900px",
    },
}


# ─── Animation specs — what the reactivity layer injects ──────────────
SOLUTIONIST_ANIMATIONS = {
    "scroll_reveal": {
        "selector": "[data-reveal], section, article",
        "distance": "48px",
        "duration": "0.9s",
        "easing": "cubic-bezier(0.16, 1, 0.3, 1)",
        "threshold": 0.1,
        "stagger": "0.1s",
        "trigger_once": True,
    },
    "shimmer_on_cta": {
        "selector": ".cta-button, [data-cta], button.primary, .btn-primary",
        "duration": "2.5s",
        "iteration": "infinite",
    },
    "floating_diamonds": {
        "applies_to_strands": ["luxury", "dark", "corporate"],
        "duration": "5-7s",
        "opacity": "0.04 fill or 0.08 border",
        "size_range": "40-200px",
    },
    "film_grain": {
        "opacity": 0.018,
        "duration": "8s",
        "always_on": True,
    },
    "pulse_glow": {
        "selector": "[data-headshot-frame]",
        "duration": "4s",
    },
}


# ─── Prompt block ─────────────────────────────────────────────────────

_PROMPT_BLOCK = """
═══════════════════════════════════════
SOLUTIONIST QUALITY RULES — NON-NEGOTIABLE
═══════════════════════════════════════

These are the measurable design rules that distinguish Solutionist-quality
output from generic web design. Every output MUST satisfy these.

# TYPOGRAPHY
- Hero h1: clamp(3.7rem, 9vw, 5.4rem), font-weight 900, letter-spacing -2.4px
- Section h2: clamp(2.4rem, 5vw, 3.5rem), font-weight 800, letter-spacing -1.6px
- Body weight: 300-400 (light, readable)
- Eyebrow labels: 12px, weight 700-800, letter-spacing 4-5px, uppercase
- Button text: 12-13px, weight 800, letter-spacing 2.5-3px, uppercase
- ITALIC ACCENT WORD RULE: Every h2 must contain ONE word/phrase wrapped in
  <em class="accent-word"> styled with the accent color and lighter weight
  (400-500). The accent word is the emotional core of the heading.
  Examples:
    <h2>Choose your <em class="accent-word">path</em></h2>
    <h2>Not a seminar. <em class="accent-word">A transformation.</em></h2>
    <h2>How it <em class="accent-word">works</em></h2>

# SPACING
- Section padding: 120-140px top/bottom on desktop, 80px on mobile (NEVER less than 80px on desktop)
- Section side padding: 48px desktop, 20px mobile
- Card padding: 48px 40px desktop, 28px 22px mobile
- Card gap in grids: 28px

# CORNERS
- Buttons: border-radius 999px (full pill)
- Cards: border-radius 28px (NEVER 4-12px — that's "generic web design" territory)
- Image frames: 28px or higher
- Form inputs: 16px (slightly less than cards, feels right for interactive)

# COLORS
- Background warm white: #F8F6F1 (NOT pure #FFFFFF)
- Text on dark: #F4F0E8 (warm off-white, NOT pure white)
- Gold/accent appears WITH INTENT — for CTAs, accent words, accent lines, hover states. Never used for body text.
- Sections alternate between dark and light (visual rhythm)

# REQUIRED ELEMENTS
- Every section h2 is preceded by:
  1. A 3px-tall gold accent line (48px wide, gradient from gold to gold-light)
  2. An eyebrow label (uppercase, letter-spaced, smaller than heading)
- Every section has scroll-triggered reveal (handled by reactivity layer — just
  structure HTML for it: use <section> tags or add data-reveal attribute)
- Every primary CTA has shimmer animation (handled by reactivity layer; give
  it class="cta-button" so the layer finds it)
- Body has film grain overlay (handled by reactivity layer)

# ANIMATIONS (will be injected by reactivity layer — design HTML to support them)
- Scroll reveals trigger on data-reveal attribute or <section>/<article> tags
- Hover lifts on cards (-8px translateY)
- Hover lifts on buttons (-3px translateY)
- Custom easing curve everywhere: cubic-bezier(0.16, 1, 0.3, 1)
- Reveal duration: 0.9s (longer than typical, feels intentional)

# VISUAL DEPTH (every page must have these layers)
- Film grain overlay (subtle, will be injected)
- Radial gradient glow on hero (use strand-aware gradients)
- Floating decorative shapes in dark sections (diamonds for luxury/corporate/dark strands)
- Layered cards with hover state transformations
- Pulse glow on hero imagery frame (data-headshot-frame attribute on hero photo wrapper)

# COMPOSITION RULES
- Hero is split-screen when photo available (text 1.1fr / image 0.9fr)
- Sections alternate dark/light backgrounds for rhythm
- Stat bands and CTA bands are full-bleed accent color (gold) — bold punctuation between sections
- Three-column grids for offerings/pathways (responsive to single column on mobile)
- Two-column for About (text + image)

# WHAT NEVER APPEARS
- border-radius below 16px on any visible element
- Pure white #FFFFFF backgrounds
- Pure white #FFFFFF text on dark
- font-weight 600 or below on h1/h2
- Section padding below 80px
- Centered "Welcome to [Business]" hero copy
- Generic CTA copy: "Get Started", "Learn More", "Click Here"
- Stock service icons (clocks, checkmarks, gears as decorative elements)
- Section labels: "What Clients Say", "Why Choose Us", "Our Process"
- Any element using cornflowerblue, lightblue, hotpink, or other generic web colors

These rules are how the Solutionist System produces premium output.
"""


def get_quality_rules_block_for_prompt() -> str:
    """Return the rules block to embed in the Builder prompt."""
    return _PROMPT_BLOCK


# ─── Post-build heuristic validator ───────────────────────────────────

_BANNED_GENERIC_COLORS = (
    "cornflowerblue",
    "lightblue",
    "hotpink",
    "lightcoral",
    "lightyellow",
    "powderblue",
)


def _count_h2_with_accent(html: str) -> Tuple[int, int]:
    """Returns (h2_total, h2_with_accent_or_em)."""
    h2_blocks = re.findall(r"<h2\b[^>]*>(.*?)</h2>", html, re.IGNORECASE | re.DOTALL)
    if not h2_blocks:
        return 0, 0
    with_accent = 0
    for inner in h2_blocks:
        lower = inner.lower()
        if "<em" in lower or "accent-word" in lower:
            with_accent += 1
    return len(h2_blocks), with_accent


def _check_section_padding_min(html: str) -> List[str]:
    """Look for section-level padding declarations under 60px."""
    issues: List[str] = []
    section_blocks = re.findall(
        r"(?:section|\.[\w-]*section[\w-]*)\s*\{[^}]*\}",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    for block in section_blocks:
        for n in re.findall(r"padding[^:]*:\s*(\d+)px", block):
            if 0 < int(n) < 60:
                issues.append(
                    f"Section padding {n}px detected — Solutionist Quality requires 80px minimum"
                )
                return issues  # one is enough; don't flood
    return issues


def _check_small_radii(html: str) -> List[str]:
    radius_matches = re.findall(r"border-radius:\s*(\d+)px", html, re.IGNORECASE)
    small = [int(r) for r in radius_matches if 0 < int(r) < 16]
    if len(small) > 3:
        return [
            f"Multiple small border-radius values (<16px): {len(small)} found — feels generic"
        ]
    return []


def _check_pure_white(html: str) -> List[str]:
    issues: List[str] = []
    lower = html.lower()
    if (
        "background: #fff" in lower
        or "background: #ffffff" in lower
        or "background-color: #fff" in lower
        or "background-color: #ffffff" in lower
    ):
        issues.append("Pure white #FFFFFF detected — use warm white #F8F6F1 instead")
    if (
        "color: #fff;" in lower
        or "color: #ffffff" in lower
    ):
        if "#f4f0e8" not in lower and "#f8f6f1" not in lower:
            issues.append(
                "Pure white text detected — use warm off-white #F4F0E8 on dark"
            )
    return issues


def _check_heading_weights(html: str) -> List[str]:
    weak = 0
    # Non-capturing group so findall returns the full block, not just "h1"/"h2".
    blocks = re.findall(
        r"(?:\bh1\b|\bh2\b)\s*\{[^}]*\}",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    for block in blocks:
        m = re.search(r"font-weight:\s*(\d+)", block)
        if m and int(m.group(1)) < HARD_RULES["heading_weight_min"]:
            weak += 1
    if weak > 0:
        return [
            f"{weak} heading rules have font-weight < {HARD_RULES['heading_weight_min']} — Solutionist Quality requires 800+"
        ]
    return []


def _check_banned_generic_colors(html: str) -> List[str]:
    lower = html.lower()
    found = [c for c in _BANNED_GENERIC_COLORS if c in lower]
    if found:
        return [f"Generic web colors used: {', '.join(found)}"]
    return []


def validate_solutionist_quality(html: str) -> Tuple[bool, List[str]]:
    """Heuristic post-build check. Returns (passes, warnings).

    Loose by design — false positives are tolerable because the build_html
    retry loop handles them. Aggressive heuristics would loop or stamp
    warnings on perfectly fine output.
    """
    warnings: List[str] = []
    if not html:
        return True, []

    h2_total, h2_with_accent = _count_h2_with_accent(html)
    if h2_total > 0 and h2_with_accent < h2_total * 0.5:
        warnings.append(
            f"Italic accent word missing from h2s: {h2_with_accent}/{h2_total} have <em>"
        )

    warnings.extend(_check_section_padding_min(html))
    warnings.extend(_check_small_radii(html))
    warnings.extend(_check_pure_white(html))
    warnings.extend(_check_heading_weights(html))
    warnings.extend(_check_banned_generic_colors(html))

    return len(warnings) == 0, warnings
