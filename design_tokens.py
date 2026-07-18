# design_tokens.py
# ─────────────────────────────────────────────────────────────────────
# Phase 2, Stage C (Kevin's Kimi Design Integration spec): deterministic
# motion + rhythm tokens derived from the boldness dial (1-3). No LLM
# call. These land in ctx as `motion_tokens` and `rhythm_scale`,
# consumed by renderers (Phase 3 motion spec formalizes that) and
# graded by the invariants/judge. Motion stops being a renderer
# constant.
# ─────────────────────────────────────────────────────────────────────

from typing import Any, Dict

# Boldness → tokens, verbatim from the spec's table.
_TABLE: Dict[int, Dict[str, Any]] = {
    1: {  # quiet
        "rhythm_px": 96,
        "reveal": "12px fade",
        "reveal_distance_px": 12,
        "stagger_ms": 40,
        "hover_lift_px": 2,
        "duration_s": 0.25,
    },
    2: {  # balanced
        "rhythm_px": 128,
        "reveal": "20px fade-up",
        "reveal_distance_px": 20,
        "stagger_ms": 70,
        "hover_lift_px": 3,
        "duration_s": 0.4,
    },
    3: {  # loud
        "rhythm_px": 160,
        "reveal": "28px fade-up",
        "reveal_distance_px": 28,
        "stagger_ms": 90,
        "hover_lift_px": 5,
        "duration_s": 0.6,
    },
}


def boldness_from_prefs(site_prefs: Any) -> int:
    try:
        b = int((site_prefs or {}).get("boldness") or 2)
    except Exception:
        b = 2
    return b if b in (1, 2, 3) else 2


def motion_tokens(boldness: int) -> Dict[str, Any]:
    return dict(_TABLE.get(boldness if boldness in _TABLE else 2))


def rhythm_scale(boldness: int) -> Dict[str, Any]:
    """The page's allowed vertical-spacing steps (D5: ONE RHYTHM).
    Sections space at the base or its harmonic halves/quarters —
    anything else is an ad-hoc margin."""
    base = _TABLE.get(boldness if boldness in _TABLE else 2)["rhythm_px"]
    return {
        "base_px": base,
        "allowed_px": [base // 4, base // 2, base, int(base * 1.5)],
        "tolerance_px": 8,
    }
