"""Pass 4.0d PART 2 — Classifier + dispatcher test harness.

Hits the live deployed /chief endpoints with a canonical suite of
practitioner messages. Prints classification + (dry-run) dispatch for
each. Designed so the practitioner can re-run anytime to verify the
classifier's accuracy hasn't drifted after a model update.

Usage:
  python -m agents.chief_executive.test_classifier
  python -m agents.chief_executive.test_classifier --base http://localhost:8000
  python -m agents.chief_executive.test_classifier --classify-only

Exit code is 0 if every test case classified as expected (best-effort
match — see CASES table), non-zero otherwise. The output is human-
readable so a glance is enough to spot regressions.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

import httpx

DEFAULT_BASE = "https://kmj-intake-server-production.up.railway.app"
# Real-looking-but-throwaway UUID. content_edit and color_swap dispatches
# use dry_run=True so this never actually hits the DB.
DRY_BUSINESS_ID = "00000000-0000-0000-0000-000000000000"

# Each case: (label, user_text, expected_intent, optional spot-checks on params).
# Spot-checks are dicts like {"target_path_contains": "head"} — softer than
# exact match because the LLM has latitude in its phrasing.
CASES: List[Dict[str, Any]] = [
    {
        "label": "concrete text edit",
        "user_text": "Change the hero headline to Crown Your Closet",
        "expected_intent": "content_edit",
        "spot_checks": {
            "target_path_contains": "hero",
            "new_text_contains": "Crown Your Closet",
        },
    },
    {
        "label": "design refinement (abstract)",
        "user_text": "Make the gold a touch warmer",
        "expected_intent": "design_refine",
        "spot_checks": {
            "feedback_text_contains_any": ["gold", "warm"],
        },
    },
    {
        "label": "design refinement — vibe",
        "user_text": "The hero feels weak — give it more weight and authority",
        "expected_intent": "design_refine",
    },
    {
        "label": "concrete color swap",
        "user_text": "Change the authority color to deep navy",
        "expected_intent": "color_swap",
        "spot_checks": {
            "role_contains_any": ["authority"],
            "new_color_contains_any": ["navy"],
        },
    },
    {
        "label": "slot change — hero photo",
        "user_text": "Swap the hero photo for a different one",
        "expected_intent": "slot_change",
        "spot_checks": {
            "slot_name_contains": "hero",
        },
    },
    {
        "label": "multi_intent — text + design",
        "user_text": "Change the hero headline to Crown Your Closet AND make the gold warmer",
        "expected_intent": "multi_intent",
        "spot_checks": {
            "sub_intent_set": {"content_edit", "design_refine"},
        },
    },
    {
        "label": "operational task",
        "user_text": "Add a task to follow up with the Davidson lead next week",
        "expected_intent": "operational_task",
    },
    {
        "label": "scheduling",
        "user_text": "Block out Tuesday morning for sermon prep",
        "expected_intent": "scheduling",
    },
    {
        "label": "briefing request",
        "user_text": "What's on my plate today?",
        "expected_intent": "briefing_request",
    },
    {
        "label": "ambiguous",
        "user_text": "Update the site",
        "expected_intent": "ambiguous",
    },
]


def _spot_check(params: Dict[str, Any], checks: Dict[str, Any]) -> List[str]:
    """Return list of FAILED checks (empty means all passed)."""
    fails: List[str] = []
    for key, expected in checks.items():
        if key.endswith("_contains"):
            field = key[: -len("_contains")]
            val = str(params.get(field) or "").lower()
            if str(expected).lower() not in val:
                fails.append(f"params.{field}={val!r} doesn't contain {expected!r}")
        elif key.endswith("_contains_any"):
            field = key[: -len("_contains_any")]
            val = str(params.get(field) or "").lower()
            if not any(str(opt).lower() in val for opt in expected):
                fails.append(
                    f"params.{field}={val!r} contains none of {expected!r}"
                )
        elif key == "sub_intent_set":
            # Compare against the top-level classification's sub_intents.
            # The caller passes the full classification dict here as well.
            actual = params.get("__sub_intent_set") or set()
            if not set(expected).issubset(actual):
                fails.append(
                    f"sub_intents {sorted(actual)} missing {sorted(set(expected) - actual)}"
                )
        else:
            fails.append(f"unknown spot-check key {key!r}")
    return fails


def _run_one(
    base: str,
    case: Dict[str, Any],
    classify_only: bool,
    business_id: str,
) -> Dict[str, Any]:
    """Run one case via either /chief/_diag/classify or /chief/message."""
    label = case["label"]
    user_text = case["user_text"]
    expected = case["expected_intent"]
    spot_checks = case.get("spot_checks") or {}

    out: Dict[str, Any] = {
        "label": label,
        "user_text": user_text,
        "expected_intent": expected,
        "spot_check_failures": [],
    }

    try:
        if classify_only:
            resp = httpx.post(
                f"{base}/chief/_diag/classify",
                json={"user_text": user_text},
                timeout=60.0,
            )
            classification = resp.json()
            result = None
        else:
            resp = httpx.post(
                f"{base}/chief/message",
                json={
                    "business_id": business_id,
                    "user_text": user_text,
                    "dry_run": True,
                },
                timeout=60.0,
            )
            body = resp.json()
            classification = body.get("classification") or {}
            result = {
                "overall_status": body.get("overall_status"),
                "summary": body.get("summary"),
                "results": body.get("results"),
            }
    except Exception as e:
        return {
            **out,
            "actual_intent": "<request_failed>",
            "passed": False,
            "error": str(e),
        }

    actual = classification.get("intent")
    out["actual_intent"] = actual
    out["confidence"] = classification.get("confidence")
    out["reasoning"] = classification.get("reasoning")
    out["params"] = classification.get("params")
    if classification.get("sub_intents"):
        out["sub_intents"] = [
            {"intent": s.get("intent"), "params": s.get("params")}
            for s in classification["sub_intents"]
        ]

    if not classify_only:
        out["dispatch"] = result

    intent_match = (actual == expected)

    # Wire sub_intent set for spot-check
    if "sub_intent_set" in spot_checks:
        params_for_check = dict(classification.get("params") or {})
        params_for_check["__sub_intent_set"] = {
            s.get("intent") for s in (classification.get("sub_intents") or [])
        }
    else:
        params_for_check = classification.get("params") or {}

    fails = _spot_check(params_for_check, spot_checks)
    out["spot_check_failures"] = fails
    out["passed"] = intent_match and not fails

    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE,
                        help=f"Backend base URL (default: {DEFAULT_BASE})")
    parser.add_argument("--classify-only", action="store_true",
                        help="Hit /chief/_diag/classify (skip dispatcher)")
    parser.add_argument("--business-id", default=DRY_BUSINESS_ID,
                        help="business_id for dispatch dry-runs")
    args = parser.parse_args()

    endpoint = "/chief/_diag/classify" if args.classify_only else "/chief/message (dry_run)"
    print(f"=== Chief classifier test suite ===")
    print(f"endpoint: {args.base}{endpoint}")
    print(f"cases: {len(CASES)}")
    print()

    passed = 0
    failed = 0
    results = []
    for case in CASES:
        r = _run_one(args.base, case, args.classify_only, args.business_id)
        results.append(r)
        verdict = "PASS" if r["passed"] else "FAIL"
        conf = r.get("confidence")
        conf_str = f"{conf:.2f}" if isinstance(conf, (int, float)) else "n/a"
        print(f"[{verdict}] {r['label']}")
        print(f"   user:     {r['user_text']!r}")
        print(f"   expected: {r['expected_intent']}")
        print(f"   actual:   {r['actual_intent']}  (conf={conf_str})")
        if r.get("reasoning"):
            print(f"   reason:   {r['reasoning']}")
        if r.get("sub_intents"):
            print(f"   sub:      {r['sub_intents']}")
        if r.get("params"):
            params_short = {k: (v if not isinstance(v, str) or len(v) <= 80 else v[:77] + '...')
                            for k, v in r["params"].items()}
            print(f"   params:   {params_short}")
        if r.get("dispatch"):
            d = r["dispatch"]
            print(f"   dispatch: status={d['overall_status']!r}, summary={d['summary'][:100]!r}")
        for f in r["spot_check_failures"]:
            print(f"   spot-fail: {f}")
        if r.get("error"):
            print(f"   error:    {r['error']}")
        print()
        if r["passed"]:
            passed += 1
        else:
            failed += 1

    print(f"=== {passed}/{len(CASES)} passed, {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
