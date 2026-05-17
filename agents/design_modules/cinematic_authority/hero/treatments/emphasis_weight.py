"""emphasis_weight treatment — controls which element anchors the
visual hierarchy.

Three options:
  heading_dominant — Heading is the visual anchor. Large display
                     scale, subtitle subordinate. Most common.
  balanced         — Heading and subtitle roughly equal presence.
                     Heading smaller, subtitle larger. Used for
                     two-thought hero structures.
  eyebrow_dominant — Eyebrow label visually prominent. Heading
                     smaller. Used for category-defining brands
                     where the category label is the headline
                     ("STUDIO BRUT" before the heading).

The primitives read emphasis_weight directly (via the Treatments
object) rather than via CSS vars, since the size + weight changes
are clamp()-based and don't translate cleanly to a single var name.
This function still exists to provide section-level layout hints
(e.g. text alignment, hero-internal vertical rhythm) as CSS vars.
"""
from __future__ import annotations

from typing import Dict

from ..types import EmphasisWeight


def emphasis_weight_vars(weight: EmphasisWeight) -> Dict[str, str]:
    """Return CSS variable assignments for the given emphasis weight.

    These vars supplement (don't replace) the size/weight clamps inside
    primitives — they cover section-level rhythm that's hierarchy-
    sensitive (intra-block gaps, optional rule treatment, etc.).
    """
    if weight == "heading_dominant":
        return {
            "--hero-heading-display-bias": "max",  # diagnostic; not consumed by primitives
            "--hero-text-rhythm-gap": "24px",
            "--hero-eyebrow-rule-width": "48px",
            "--hero-cta-top-margin": "8px",
        }
    if weight == "eyebrow_dominant":
        return {
            "--hero-heading-display-bias": "min",
            "--hero-text-rhythm-gap": "20px",
            "--hero-eyebrow-rule-width": "96px",
            "--hero-cta-top-margin": "16px",
        }
    # balanced
    return {
        "--hero-heading-display-bias": "balanced",
        "--hero-text-rhythm-gap": "28px",
        "--hero-eyebrow-rule-width": "64px",
        "--hero-cta-top-margin": "12px",
    }
