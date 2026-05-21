"""Pass 4.0i Phase B — Studio Brut font vocabulary.

5 Google-Fonts-only pairings. Each pairing locks display + body + an
optional code accent face (for code_label accent rendering). Adobe
Fonts options deferred to Pass 4.0i.x per Phase A design doc.

Each entry's google_families is a list of Google Fonts CSS2 family
specs (the `family=` query-string components) — font_resolver
composes them into a single stylesheet URL per font_id.

Authoring constraint: display_weight is the numeric weight the variant
will apply via --hero-display-weight (subject to intensity override —
bold intensity bumps to 900 if base is lower). Body weights are
loaded in a small range so primitive styling can vary regular vs
medium vs bold body type without re-loading.
"""
from __future__ import annotations

from typing import Dict, List

STUDIO_BRUT_FONTS: Dict[str, Dict] = {
    "brutalist_default": {
        "label": "Brutalist Default",
        "character": "graphic poster, urban streetwear, narrow stacked-display authority",
        "best_for": "streetwear, custom apparel, design studios with edge",
        "display": "'Bebas Neue', Impact, sans-serif",
        "body": "'Space Grotesk', system-ui, sans-serif",
        "google_families": [
            "Bebas+Neue",
            "Space+Grotesk:wght@300;400;500;700",
        ],
        # Bebas Neue ships at weight 400 only; intensity does not bump it
        # (the display family handles weight visually via its own face).
        "display_weight": 400,
        "preload_family": "Bebas+Neue",
    },
    "brutalist_wide": {
        "label": "Brutalist Wide",
        "character": "stretched-letter authority, broader stance, narrow-tall display energy",
        "best_for": "confident product brands, statement-makers",
        "display": "'Oswald', 'Arial Narrow', sans-serif",
        "body": "'Space Grotesk', system-ui, sans-serif",
        "google_families": [
            "Oswald:wght@600;700;900",
            "Space+Grotesk:wght@300;400;500;700",
        ],
        "display_weight": 700,
        "preload_family": "Oswald",
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
        "display_weight": 800,
        "preload_family": "Bricolage+Grotesque",
    },
    "brutalist_display": {
        "label": "Brutalist Display",
        "character": "serif touch within the graphic frame, hand-touched maker feel",
        "best_for": "independent makers, artists, personality-led brands",
        "display": "'DM Serif Display', Georgia, serif",
        "body": "'Space Grotesk', system-ui, sans-serif",
        "google_families": [
            "DM+Serif+Display:ital@0;1",
            "Space+Grotesk:wght@300;400;500;700",
        ],
        # DM Serif Display ships at 400 only (heavy by design).
        "display_weight": 400,
        "preload_family": "DM+Serif+Display",
    },
    "brutalist_sharp": {
        "label": "Brutalist Sharp",
        "character": "refined-brutalist, less posterly, more confident-cool",
        "best_for": "premium streetwear, design-aware fashion, considered urban brands",
        "display": "'Inter', system-ui, sans-serif",
        "body": "'Manrope', system-ui, sans-serif",
        "google_families": [
            "Inter:wght@400;500;700;800;900",
            "Manrope:wght@400;500;600;700",
        ],
        "display_weight": 900,
        "preload_family": "Inter",
    },
}

STUDIO_BRUT_FONT_DEFAULT: str = "brutalist_default"

STUDIO_BRUT_FONT_IDS: List[str] = list(STUDIO_BRUT_FONTS.keys())
