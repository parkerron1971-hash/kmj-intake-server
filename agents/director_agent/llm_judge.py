"""Pass 4.0b — Layer 2 LLM-judged rule checkers.

Calls Sonnet with the rendered HTML + each rule's `judgment_prompt`,
asks for a verdict (pass/fail) + evidence + fix_hint. Returns the
same violation dict shape as the deterministic checker so `critique.py`
can concatenate the two lists.

Soft-fails on missing API key, LLM error, or non-JSON model output —
the rule is skipped, not failed. We don't want to penalize Builder
output for an LLM/judge plumbing bug.

Project conventions matched:
  - Direct anthropic.Anthropic SDK
  - Model claude-sonnet-4-5-20250929
  - Multi-block content extraction (defensive)
  - System+user prompt split with strict JSON instruction
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List, Optional

from anthropic import Anthropic

logger = logging.getLogger(__name__)

JUDGE_MODEL = "claude-sonnet-4-5-20250929"
JUDGE_MAX_TOKENS = 600
JUDGE_TEMPERATURE = 0.2  # low — consistent judgments, not creative variance
HTML_INPUT_CAP = 50_000  # truncate to avoid token blowups on huge sites


JUDGE_SYSTEM_PROMPT = """You are a design quality judge for the Solutionist Design System. You evaluate generated websites against specific design quality rules.

For each rule, respond with strict JSON only:
{
  "verdict": "pass" | "fail",
  "evidence": "1-2 sentences citing what you observed in the HTML",
  "fix_hint": "if fail: 1 sentence directing how to fix; if pass: null"
}

Be strict. A 'pass' means the page genuinely satisfies the rule. A 'fail' means there's a real, observable gap. Do NOT pass borderline cases — flag them as fail with specific evidence. Do NOT add commentary outside the JSON. No markdown fences."""


def judge_all_llm(
    rubric: Dict,
    html: str,
    enriched_brief: Optional[Dict] = None,
) -> List[Dict]:
    """Run every Layer 2 rule. Returns a list of violation dicts."""
    if not rubric:
        return []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        # No key on server → skip Layer 2 entirely (deterministic still
        # runs). We don't want to fail Builder output because the judge
        # plumbing is misconfigured.
        logger.warning(
            "[director.llm_judge] ANTHROPIC_API_KEY not set; skipping Layer 2"
        )
        return []

    violations: List[Dict] = []
    for rule in rubric.get("layer_2_llm_judged", []):
        try:
            v = judge_rule(rule, html, enriched_brief)
            if v:
                violations.append(v)
        except Exception as e:
            logger.warning(
                f"[director.llm_judge] rule {rule.get('id')} raised: "
                f"{type(e).__name__}: {e}"
            )
    return violations


def judge_rule(
    rule: Dict,
    html: str,
    enriched_brief: Optional[Dict] = None,
) -> Optional[Dict]:
    """Call the Sonnet judge for a single rule. Returns a violation dict
    when the judge says fail, None when pass / parse-failure / no-call."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    judgment_prompt = rule.get("judgment_prompt", "")
    if not judgment_prompt:
        return None

    user_parts: List[str] = [
        f"RULE: {rule.get('description', '')}",
        f"JUDGMENT QUESTION: {judgment_prompt}",
    ]
    if enriched_brief:
        try:
            user_parts.append(
                "ENRICHED BRIEF:\n" + json.dumps(enriched_brief, indent=2)
            )
        except Exception:
            pass  # if it doesn't serialize, omit rather than crash

    truncated_html = (html or "")[:HTML_INPUT_CAP]
    user_parts.append(f"HTML TO JUDGE:\n{truncated_html}")

    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=JUDGE_MAX_TOKENS,
            temperature=JUDGE_TEMPERATURE,
            system=JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
        )
    except Exception as e:
        logger.warning(
            f"[director.llm_judge] Anthropic call failed for {rule.get('id')}: "
            f"{type(e).__name__}: {e}"
        )
        return None

    text = "".join(
        b.text for b in msg.content if getattr(b, "type", None) == "text"
    ).strip()
    text = _strip_code_fence(text)
    if not text:
        return None

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Try to locate a JSON object inside the text (model occasionally
        # adds a stray sentence despite instructions).
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group(0))
            except json.JSONDecodeError:
                logger.warning(
                    f"[director.llm_judge] non-JSON response for {rule.get('id')}; "
                    "skipping"
                )
                return None
        else:
            return None

    if not isinstance(result, dict):
        return None

    verdict = (result.get("verdict") or "").lower().strip()
    if verdict != "fail":
        return None  # pass or unknown verdict → no violation

    return {
        "rule_id": rule.get("id"),
        "severity": rule.get("severity", "MEDIUM"),
        "description": rule.get("description", ""),
        "evidence": (result.get("evidence") or "").strip(),
        "fix_hint": (result.get("fix_hint") or rule.get("fix_hint") or "").strip(),
    }


def _strip_code_fence(text: str) -> str:
    """Strip leading ```json … ``` if the model added one despite
    instructions. No-op when no fence present."""
    text = (text or "").strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl > 0:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[: -3]
    return text.strip()
