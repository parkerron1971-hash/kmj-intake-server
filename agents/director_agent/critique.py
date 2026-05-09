"""Pass 4.0b — Critique loop orchestrator.

Composes Layer 1 (deterministic_checker) + Layer 2 (llm_judge) into
a single punch-list result the Builder Agent can regenerate against.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from agents.design_intelligence.rubrics import load_rubric
from agents.director_agent.deterministic_checker import check_all_deterministic
from agents.director_agent.llm_judge import judge_all_llm

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def critique_site(
    module_id: str,
    html: str,
    css: str = "",
    enriched_brief: Optional[Dict] = None,
) -> Dict:
    """Critique a generated site against its Design Intelligence Module
    rubric. Returns a punch list of violations sorted HIGH → MEDIUM → LOW.

    Response shape:
      {
        "module_id": "<id>",
        "rubric_loaded": bool,
        "violations": [{rule_id, severity, description, evidence, fix_hint}, ...],
        "summary": {"total", "high", "medium", "low", "verdict": "pass"|"fail"}
      }

    The verdict is "pass" when zero HIGH-severity violations remain
    (MEDIUM/LOW don't block the regenerate decision in build_with_loop).
    A missing rubric short-circuits to a benign "no critique available"
    result so callers never crash on unknown modules.
    """
    rubric = load_rubric(module_id) if module_id else None
    if not rubric:
        return {
            "module_id": module_id,
            "rubric_loaded": False,
            "violations": [],
            "summary": {
                "total": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "verdict": "skipped",
                "reason": "no rubric for this module — critique skipped",
            },
        }

    deterministic = check_all_deterministic(rubric, html, css, enriched_brief)
    llm = judge_all_llm(rubric, html, enriched_brief)
    all_violations: List[Dict] = list(deterministic) + list(llm)

    # Sort HIGH → MEDIUM → LOW; preserve original order within each band
    all_violations.sort(
        key=lambda v: _SEVERITY_ORDER.get(v.get("severity", "LOW"), 99)
    )

    high = sum(1 for v in all_violations if v.get("severity") == "HIGH")
    medium = sum(1 for v in all_violations if v.get("severity") == "MEDIUM")
    low = sum(1 for v in all_violations if v.get("severity") == "LOW")

    return {
        "module_id": module_id,
        "rubric_loaded": True,
        "rubric_version": rubric.get("rubric_version"),
        "violations": all_violations,
        "summary": {
            "total": len(all_violations),
            "high": high,
            "medium": medium,
            "low": low,
            "verdict": "pass" if high == 0 else "fail",
            "deterministic_count": len(deterministic),
            "llm_judged_count": len(llm),
        },
    }
