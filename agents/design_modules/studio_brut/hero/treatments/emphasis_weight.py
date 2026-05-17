"""Studio Brut emphasis_weight — controls the balance among eyebrow /
heading / subtitle. Same 3 options as Cathedral. Studio Brut's heading
sizes run larger at the heading_dominant end (clamp 3.5-11rem) to
support type-as-graphic compositions.

Variables here drive primitive-level decisions. The actual heading
font-size clamp lives in heading.py keyed off emphasis_weight; this
translator emits supplementary vars that some variants consume
(e.g. --sb-eyebrow-prominence-scale for eyebrow_dominant heroes).
"""
from __future__ import annotations

from typing import Dict

from ..types import EmphasisWeight


def emphasis_weight_vars(emphasis: EmphasisWeight) -> Dict[str, str]:
    """Return CSS variable assignments for emphasis-weight balance.

    Most of emphasis_weight's effect lives inline in heading.py /
    eyebrow.py / subtitle.py — this dict provides supplementary
    multipliers that variants can read for layout decisions (e.g.
    stat_strip uses --sb-eyebrow-prominence-scale to enlarge its
    code label when eyebrow_dominant)."""
    if emphasis == "heading_dominant":
        return {
            "--sb-heading-prominence-scale": "1.0",
            "--sb-eyebrow-prominence-scale": "0.85",
            "--sb-subtitle-prominence-scale": "0.92",
        }
    if emphasis == "eyebrow_dominant":
        return {
            "--sb-heading-prominence-scale": "0.85",
            "--sb-eyebrow-prominence-scale": "1.2",
            "--sb-subtitle-prominence-scale": "0.92",
        }
    # balanced
    return {
        "--sb-heading-prominence-scale": "0.95",
        "--sb-eyebrow-prominence-scale": "1.0",
        "--sb-subtitle-prominence-scale": "1.0",
    }
