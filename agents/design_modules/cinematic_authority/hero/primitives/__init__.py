"""Shared Hero primitives. Each renders one HTML fragment and is
treatment-aware — primitives consult Treatments to vary size, weight,
color, and spacing. Every text-bearing primitive emits a
data-override-target + data-override-type attribute so the Edit Mode
script can hook into it (Pass 4.0e PART 2 contract)."""

from .eyebrow import render_eyebrow
from .heading import render_heading
from .subtitle import render_subtitle
from .cta_button import render_cta_button
from .diamond_motif import render_diamond_motif

__all__ = [
    "render_eyebrow",
    "render_heading",
    "render_subtitle",
    "render_cta_button",
    "render_diamond_motif",
]
