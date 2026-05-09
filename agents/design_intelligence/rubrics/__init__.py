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


_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def rubric_to_canonical_checklist(rubric: Optional[Dict]) -> str:
    """Render a rubric as a bulleted checklist of canonical rule
    descriptions, sorted HIGH → MEDIUM → LOW. Includes both deterministic
    and LLM-judged rules so the Builder Agent has the full standard in
    front of it on regenerate.

    Used by the MAINTAIN — DO NOT REGRESS prompt block (Pass 4.0b.4):
    when Builder regenerates against a Director punch list, this list
    tells it what already-correct work it must NOT regress on while
    fixing the punch list items. Sourcing from the rubric file means
    the prompt block updates automatically when the rubric changes.

    Returns an empty string when the rubric is missing or has no rules,
    so the caller can simply concatenate without a falsy guard.
    """
    if not isinstance(rubric, dict):
        return ""
    rules = list(rubric.get("layer_1_deterministic") or []) + \
            list(rubric.get("layer_2_llm_judged") or [])
    if not rules:
        return ""
    rules.sort(key=lambda r: _SEVERITY_ORDER.get(r.get("severity", "LOW"), 99))
    lines = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        sev = (r.get("severity") or "MEDIUM").upper()
        desc = (r.get("description") or "").strip()
        if desc:
            lines.append(f"- [{sev}] {desc}")
    return "\n".join(lines)
