"""Pass 4.0b — Design Intelligence Module rubrics.

Each Module has a sibling `<module_id>_rubric.json` here that the
Director Agent's Critique loop scores generated HTML against.

Two layers per rubric:
  layer_1_deterministic — rules a Python checker can score by parsing
                          HTML/CSS (font-size thresholds, border-radii,
                          presence of specific classes/structures, etc.)
  layer_2_llm_judged    — qualitative rules that need a Sonnet judge
                          (rhythm, depth, brand-metaphor consistency,
                          emotional progression).

The rubric is canonical reference for Critique. The Module markdown
itself stays untouched — rubrics are extracted from prose, not edits
to it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

RUBRIC_DIR = Path(__file__).parent


def load_rubric(module_id: str) -> Optional[Dict]:
    """Load the rubric JSON for a Design Intelligence Module.

    Returns None when the rubric file doesn't exist (the Director
    Agent treats this as 'no module-driven critique available — ship
    Builder output as-is').
    """
    path = RUBRIC_DIR / f"{module_id}_rubric.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_rubrics() -> list:
    """Return module_ids that have a rubric on disk. Useful for ops
    diagnostics — quickly see which modules can run Critique."""
    return sorted(
        p.name.replace("_rubric.json", "")
        for p in RUBRIC_DIR.glob("*_rubric.json")
    )
