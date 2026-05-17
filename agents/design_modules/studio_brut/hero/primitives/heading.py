"""Studio Brut heading primitive — large display sans/condensed with
emphasis via weight contrast, scale contrast, or color contrast.

Key DNA differences from Cathedral's heading primitive:

  - NO italic-emphasis-word as signature. The emphasis substring
    receives weight contrast (lighter or heavier than its neighbors)
    or scale contrast (visibly larger) or color contrast (signal vs
    text-primary). Which mode applies depends on typography treatment:

      typography=editorial → color contrast (signal-colored word
        inside text-primary heading) — closest Studio Brut analogue
        to a familiar editorial pattern, but NEVER italic
      typography=bold     → weight contrast (heavier word among
        heavy-but-lighter neighbors) — declarative
      typography=refined  → scale contrast (oversized word among
        smaller neighbors) — poster-graphic
      typography=playful  → combined: oversize + color (largest word
        AND signal-colored) — most graphic, most expressive

  - Default font stack: display sans (Druk / Bebas Neue / Space
    Grotesk / Archivo Black / Inter at extreme weights). NEVER
    Playfair. The CSS var --sb-display-stack defaults to a
    system-available stack but can be overridden by the brand kit
    or module-level CSS.

  - Baseline weight 800 (Cathedral uses 900). Studio Brut headings
    are still heavy but reserve the 900 step for the emphasis word
    or scale moments.

  - Tighter line-height than Cathedral (0.95 vs 1.05). Studio Brut
    is denser by design.

  - Heading can be oversized — emphasis_weight=heading_dominant
    drives clamp(3.5rem, 12vw, 11rem), markedly larger than
    Cathedral's clamp(3rem, 8vw, 6rem). Studio Brut leans into
    type-as-graphic.
"""
from __future__ import annotations

from html import escape

from ..types import Treatments


def _split_emphasis(heading: str, emphasis: str) -> tuple[str, str, str]:
    """Same fallback pattern as Cathedral's split — if emphasis isn't a
    substring of heading, italicize the first word so emphasis never
    silently disappears. Returns (before, match, after)."""
    if not emphasis or emphasis not in heading:
        parts = heading.split(maxsplit=1)
        if len(parts) == 2:
            first, rest = parts
            return ("", first, " " + rest)
        return ("", heading, "")
    idx = heading.find(emphasis)
    return (heading[:idx], emphasis, heading[idx + len(emphasis):])


# Emphasis mode per typography treatment. Drives which inline style
# variant gets attached to the emphasis <span>.
_EMPHASIS_MODE_BY_TYPOGRAPHY = {
    "editorial": "color",       # signal-colored word, otherwise standard
    "bold":      "weight",      # heavier word among heavy neighbors
    "refined":   "scale",       # oversized word among smaller neighbors
    "playful":   "scale_color", # combined: largest AND signal-colored
}


# color_depth treatment layers on top of EVERY emphasis mode — gradient
# text-fill, glow halos, etc. apply regardless of which typography
# mode is active. Defaults from color_depth_treatment_vars are
# conservative no-ops (transparent bg, border-box clip, etc.) so this
# block is safe to attach uniformly. Phase C audit surfaced that
# without these uniform overlays, color_depth=radial_glows / =gradient_
# accents would only fire when typography=playful — a real coupling bug.
_COLOR_DEPTH_OVERLAY = (
    "background: var(--sb-emphasis-bg, transparent); "
    "-webkit-background-clip: var(--sb-emphasis-bg-clip, border-box); "
    "background-clip: var(--sb-emphasis-bg-clip, border-box); "
    "-webkit-text-fill-color: var(--sb-emphasis-text-fill, currentColor); "
    "text-shadow: var(--sb-emphasis-glow, none); "
)


def _emphasis_span_style(mode: str) -> str:
    """Return inline style fragment for the emphasis span based on
    typography treatment mode + color_depth overlay.

    Order of declarations matters here: the typography mode's font /
    color / scale rules come FIRST, then the color_depth overlay
    appends. Browsers apply later declarations on top, so the overlay
    can override `color` with `-webkit-text-fill-color: transparent`
    when gradient_accents fires."""
    if mode == "color":
        return (
            "color: var(--sb-emphasis-color, var(--brand-signal, #FACC15)); "
            "font-weight: 900; "
            + _COLOR_DEPTH_OVERLAY
        )
    if mode == "weight":
        return (
            "font-weight: 900; "
            "letter-spacing: -0.02em; "
            "color: var(--sb-heading-color, var(--brand-text-primary, #09090B)); "
            + _COLOR_DEPTH_OVERLAY
        )
    if mode == "scale":
        return (
            "font-size: 1.4em; "
            "font-weight: 700; "
            "letter-spacing: -0.03em; "
            "line-height: 0.85; "
            "vertical-align: -0.05em; "
            "color: var(--sb-heading-color, var(--brand-text-primary, #09090B)); "
            + _COLOR_DEPTH_OVERLAY
        )
    # scale_color (playful)
    return (
        "font-size: 1.45em; "
        "font-weight: 900; "
        "letter-spacing: -0.03em; "
        "line-height: 0.85; "
        "vertical-align: -0.05em; "
        "color: var(--sb-emphasis-color, var(--brand-signal, #FACC15)); "
        + _COLOR_DEPTH_OVERLAY
    )


def render_heading(
    heading: str,
    heading_emphasis: str,
    treatments: Treatments,
    heading_target_path: str = "hero.heading",
    emphasis_target_path: str = "hero.heading_emphasis",
) -> str:
    """Render <h1> with Studio Brut emphasis treatment.

    Studio Brut headings are denser, heavier-baseline, and more
    graphic than Cathedral's. The emphasis word is NEVER italicized
    (Cathedral's signature) — instead receiving one of four Studio
    Brut emphasis modes based on the active typography treatment."""
    size_clamp = {
        "heading_dominant": "clamp(3.5rem, 12vw, 11rem)",
        "balanced":         "clamp(2.75rem, 8vw, 6rem)",
        "eyebrow_dominant": "clamp(2.25rem, 6vw, 4.5rem)",
    }[treatments.emphasis_weight]
    bottom_margin = {
        "generous": "28px",
        "standard": "20px",
        "compact":  "12px",
    }[treatments.spacing_density]

    mode = _EMPHASIS_MODE_BY_TYPOGRAPHY.get(treatments.typography, "color")

    before, emphasis_text, after = _split_emphasis(heading, heading_emphasis)
    safe_before = escape(before)
    safe_emphasis = escape(emphasis_text)
    safe_after = escape(after)

    emphasis_span = (
        f'<span class="sb-hero-heading-emphasis" '
        f'data-override-target="{escape(emphasis_target_path)}" '
        f'data-override-type="text" '
        f'data-emphasis-mode="{mode}" '
        f'style="{_emphasis_span_style(mode)}">'
        f"{safe_emphasis}"
        f"</span>"
    )

    return (
        f'<h1 class="sb-hero-heading" '
        f'data-override-target="{escape(heading_target_path)}" '
        f'data-override-type="text" '
        f'style="font-size: {size_clamp}; '
        f'font-weight: var(--sb-heading-weight, 800); '
        f'font-style: var(--sb-heading-style, normal); '
        f'line-height: var(--sb-heading-line-height, 0.95); '
        f'letter-spacing: var(--sb-heading-tracking, -0.02em); '
        f'text-transform: var(--sb-heading-case, none); '
        f'color: var(--sb-heading-color, var(--brand-text-primary, #09090B)); '
        f'font-family: var(--sb-display-stack, "Druk", "Bebas Neue", '
        f'"Space Grotesk", "Archivo Black", "Inter", system-ui, sans-serif); '
        f'margin: 0 0 {bottom_margin} 0;">'
        f"{safe_before}{emphasis_span}{safe_after}"
        f"</h1>"
    )
