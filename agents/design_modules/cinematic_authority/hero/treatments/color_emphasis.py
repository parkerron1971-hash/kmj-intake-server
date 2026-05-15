"""color_emphasis treatment — controls which brand role colors carry
visual weight where.

Three options:
  signal_dominant   — italic emphasis + eyebrow + CTA all in signal
                      (gold). Heading uses text_primary.
                      Most common pattern; the Cathedral classic.
  authority_dominant — Heading uses brand authority (deep anchor).
                      Signal restricted to italic emphasis only.
                      Eyebrow + CTA shift to authority color too,
                      for a more monolithic feel.
  dual_emphasis     — Both authority + signal carry weight equally.
                      Heading authority color, italic + eyebrow + CTA
                      signal color. More color-active overall.
"""
from __future__ import annotations

from typing import Dict

from ..types import ColorEmphasis


def color_emphasis_vars(emphasis: ColorEmphasis) -> Dict[str, str]:
    """Return CSS variable assignments for the given color emphasis.

    Variable names mirror the existing brand-kit role vocabulary so the
    primitives can read --heading-color / --emphasis-color / etc.
    Falls back to brand-kit defaults at the primitive level if vars
    aren't set (so primitives remain usable in isolation for testing)."""
    if emphasis == "signal_dominant":
        return {
            "--heading-color": "var(--brand-text-primary)",
            "--emphasis-color": "var(--brand-signal)",
            "--eyebrow-color": "var(--brand-signal)",
            "--subtitle-color": "var(--brand-text-primary)",
            "--cta-bg": "var(--brand-signal)",
            "--cta-text": "var(--brand-text-on-signal)",
        }
    if emphasis == "authority_dominant":
        return {
            "--heading-color": "var(--brand-authority)",
            "--emphasis-color": "var(--brand-signal)",
            "--eyebrow-color": "var(--brand-authority)",
            "--subtitle-color": "var(--brand-text-primary)",
            "--cta-bg": "var(--brand-authority)",
            "--cta-text": "var(--brand-text-on-authority)",
        }
    # dual_emphasis
    return {
        "--heading-color": "var(--brand-authority)",
        "--emphasis-color": "var(--brand-signal)",
        "--eyebrow-color": "var(--brand-signal)",
        "--subtitle-color": "var(--brand-text-primary)",
        "--cta-bg": "var(--brand-signal)",
        "--cta-text": "var(--brand-text-on-signal)",
    }
