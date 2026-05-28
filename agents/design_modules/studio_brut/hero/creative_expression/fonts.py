"""Pass 4.0i Phase B — Studio Brut font vocabulary (FINALIZED).

5 Google-Fonts-only pairings spread across categories (sans-condensed,
sans-geometric, serif-display, mono, sans-grotesque) so each font reads
as categorically distinct in the browser. Each font carries its OWN
treatment signature (case + base_weight + tracking) so the variant's
uniform uppercase-heavy-tight treatment can't flatten font personality.

OWNERSHIP RULE (Phase B finalize):
  Font choice owns:  typeface (font-family), text-transform (case),
                     and base letter-spacing character.
  Intensity owns:    final h1 size and weight TIER (800/900) via the
                     two-sided clamp.
  Treatments own:    color, emphasis span style, layout, etc.

Precedence is expressed in CSS via var-with-fallback in the primitives,
NOT via dict-merge order. Font's --hero-* vars override --sb-* treatment
vars at the CSS level.

WEIGHT-LOCK EXCEPTION (the editorial font specifically):
  DM Serif Display ships only at weight 400. Asking browsers for 800/900
  on a single-weight face produces faux-bold synthesis which looks
  cheap on serif display type. brutalist_editorial therefore declares
  weight_locked=True, which makes font_resolver emit --hero-font-fixed-weight=400;
  the primitive consumes this with precedence over intensity's
  --hero-display-weight, so a "bold-intensity editorial Hero" stays at
  the font's authentic 400 weight and gets its drama from size + scale
  + tracking instead.

VOCABULARY CHANGE FROM PHASE A:
  - brutalist_wide (Oswald) DROPPED — too sibling-similar to default
  - brutalist_display renamed to brutalist_editorial (clearer label)
  - brutalist_mono (Space Mono) ADDED — fills the technical-voice gap
  - default/geometric/sharp retained; geometric and sharp now carry
    per-font case + weight + tracking signatures (previously inherited
    the treatment's uniform uppercase-heavy)
"""
from __future__ import annotations

from typing import Dict, List

STUDIO_BRUT_FONTS: Dict[str, Dict] = {
    "brutalist_default": {
        "label": "Brutalist Default",
        "character": "condensed poster, urban streetwear, narrow stacked-display authority",
        "best_for": "streetwear, custom apparel, design studios with edge",
        "display": "'Bebas Neue', Impact, sans-serif",
        "body": "'Space Grotesk', system-ui, sans-serif",
        "google_families": [
            "Bebas+Neue",
            "Space+Grotesk:wght@300;400;500;700",
        ],
        # Per-font signature (Phase B finalize): font owns case, weight
        # character, and tracking. Intensity owns final size + weight tier.
        "case": "uppercase",
        "base_weight": 800,
        "tracking": "-1.6px",
        # Bebas Neue ships single weight; browsers won't synth bold on it
        # in practice but we don't weight-lock because intensity's 800/900
        # snaps cleanly to the available 400 face without faux-bold ugliness.
        "weight_locked": False,
        "preload_family": "Bebas+Neue",
    },
    "brutalist_geometric": {
        "label": "Brutalist Geometric",
        "character": "engineered precision, architectural, machined geometric",
        "best_for": "tech-adjacent creative, design firms, makers with precision aesthetic",
        "display": "'Bricolage Grotesque', 'Helvetica Neue', sans-serif",
        "body": "'Inter', system-ui, sans-serif",
        "code": "'JetBrains Mono', ui-monospace, monospace",
        "google_families": [
            "Bricolage+Grotesque:opsz,wght@12..96,700;12..96,800;12..96,900",
            "Inter:wght@400;500;600;700",
            "JetBrains+Mono:wght@400;500;700",
        ],
        # Lighter base-weight than default so the geometry reads as
        # engineered rather than poster-heavy. Tracking still tight but
        # looser than default to let letterforms breathe.
        "case": "uppercase",
        "base_weight": 700,
        "tracking": "-0.5px",
        "weight_locked": False,
        "preload_family": "Bricolage+Grotesque",
    },
    "brutalist_editorial": {
        "label": "Brutalist Editorial",
        "character": "serif display, editorial-maker dialect, mixed-case authority",
        "best_for": "writers, publishers, narrative-driven brands, design-aware editorial voices",
        "display": "'DM Serif Display', Georgia, serif",
        "body": "'Space Grotesk', system-ui, sans-serif",
        "google_families": [
            "DM+Serif+Display:ital@0;1",
            "Space+Grotesk:wght@300;400;500;700",
        ],
        # THE serif that breaks the uppercase mold. Mixed case + natural
        # 400 weight + near-zero tracking lets the typeface speak in its
        # own editorial voice. Bold intensity Heros render with size
        # + scale drama, not synthesized faux-bold weight.
        "case": "none",
        "base_weight": 400,
        "tracking": "-0.5px",
        # DM Serif Display ships single-weight at 400; weight_locked keeps
        # intensity from synthesizing faux-bold on serif display type.
        "weight_locked": True,
        "preload_family": "DM+Serif+Display",
    },
    "brutalist_mono": {
        "label": "Brutalist Mono",
        "character": "technical voice, code aesthetic, wide-tracked monospace",
        "best_for": "developer tools, technical creative, software studios, makers with code-native aesthetic",
        "display": "'Space Mono', 'JetBrains Mono', ui-monospace, monospace",
        "body": "'Space Grotesk', system-ui, sans-serif",
        # Mono itself can double as code accent — no separate code face needed.
        "code": "'Space Mono', 'JetBrains Mono', ui-monospace, monospace",
        "google_families": [
            "Space+Mono:wght@400;700",
            "Space+Grotesk:wght@300;400;500;700",
        ],
        # Wide tracking is the mono signature — mono headlines that feel
        # tight read as crowded. +0.05em opens the letters.
        "case": "uppercase",
        "base_weight": 700,
        "tracking": "0.05em",
        # Space Mono ships 400/700 only; intensity 800/900 snaps to 700.
        # No faux-bold synthesis concern on Mono since 700 is its true
        # bold and that's what intensity will resolve to.
        "weight_locked": False,
        "preload_family": "Space+Mono",
    },
    "brutalist_sharp": {
        "label": "Brutalist Sharp",
        "character": "refined-heavy, considered-fashion, mixed-case minimal",
        "best_for": "premium streetwear, design-aware fashion, considered urban brands, refined-cool category",
        "display": "'Inter', system-ui, sans-serif",
        "body": "'Manrope', system-ui, sans-serif",
        "google_families": [
            "Inter:wght@400;500;700;800;900",
            "Manrope:wght@400;500;600;700",
        ],
        # Mixed case + extreme weight (900) is the refined-heavy posture
        # — the considered-fashion voice. Minimal tracking; the weight
        # carries the impact.
        "case": "none",
        "base_weight": 900,
        "tracking": "-0.5px",
        "weight_locked": False,
        "preload_family": "Inter",
    },
}

STUDIO_BRUT_FONT_DEFAULT: str = "brutalist_default"

STUDIO_BRUT_FONT_IDS: List[str] = list(STUDIO_BRUT_FONTS.keys())
