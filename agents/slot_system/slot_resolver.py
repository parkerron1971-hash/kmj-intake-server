"""Pass 4.0b.5 — Render-time slot resolution.

Pure function — no IO, no Supabase, no HTTP. Given a slot's persisted
state dict, decides what URL the renderer should emit and how to label
attribution.

Precedence:
  1. custom_url present  → render the practitioner's upload (no credit)
  2. default_url present → render the suggested image (Unsplash credit
                           or DALL-E generation marker)
  3. nothing present     → render the placeholder slot UI
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def resolve_slot_url(
    slot_data: Optional[Dict[str, Any]],
    slot_name: str,
) -> Dict[str, Any]:
    """Decide what to render for a given slot.

    Returns:
      {
        "url": str | None,        # None → render placeholder
        "source": "custom" | "default" | "placeholder",
        "credit": dict | None,    # attribution payload when default
                                  # came from Unsplash; None otherwise
        "is_placeholder": bool,   # convenience flag for the renderer
      }

    `slot_name` is included in the output for callers that fan out and
    need to keep slot identity attached to the resolved record.
    """
    base = {"slot_name": slot_name}

    if not slot_data:
        return {
            **base,
            "url": None,
            "source": "placeholder",
            "credit": None,
            "is_placeholder": True,
        }

    custom_url = slot_data.get("custom_url")
    if custom_url:
        return {
            **base,
            "url": custom_url,
            "source": "custom",
            "credit": None,
            "is_placeholder": False,
        }

    default_url = slot_data.get("default_url")
    if default_url:
        return {
            **base,
            "url": default_url,
            "source": "default",
            "credit": slot_data.get("default_credit"),
            "is_placeholder": False,
        }

    return {
        **base,
        "url": None,
        "source": "placeholder",
        "credit": None,
        "is_placeholder": True,
    }
