#!/usr/bin/env python3
# scripts/chief_rare_actions_eval.py
# ─────────────────────────────────────────────────────────────────────
# THE RARE-ACTIONS EVAL — does Chief still reach the verbs it seldom uses?
#
# WHY THIS EXISTS (2026-11-03). CHIEF_BRIEF=lean (chief_lean_brief) keeps
# the full how-to only for the verbs that did ~90% of Chief's work in the
# last 60 days; every other verb keeps one line in the manual and its
# full how-to comes back from the action_guide lookup, and the rarely
# used tools are deferred until that lookup loads them. The turn eval
# measures the common verbs. This one asks for verbs OUTSIDE the kept
# set, so the short brief cannot pass by luck: each row needs a verb
# that is a one-liner (and often a deferred tool) in lean mode.
#
# Same machinery and scorer as scripts/chief_turn_eval.py (live mode):
# the real chief_chat, every read stubbed, the door spied so nothing is
# executed. It also records which names Chief looked up with
# action_guide, so a run says whether the lookup was used before a
# one-line verb ran.
#
#   python scripts/chief_rare_actions_eval.py --list
#   python scripts/chief_rare_actions_eval.py --live --out rare.json
#   CHIEF_BRIEF=lean python scripts/chief_rare_actions_eval.py --live --out rare-lean.json
#
# --live calls the real model and costs money (about 10-20c a row).
# There is no replay mode: a recorded reply would say nothing about
# whether the short brief finds the verb.

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import chief_turn_eval as te  # noqa: E402

# Each row: the sentence, the verb it needs (any one of `expect_any`),
# and the dangerous neighbours it must not produce. Verbs are checked
# against chief_lean_brief in __tests__/test_chief_lean_brief.py: none
# of them may be in the kept set, or the row measures nothing.
CASES: List[Dict[str, Any]] = [
    {"id": "plan_post",
     "message": "Draft a LinkedIn post for next Tuesday about why we raised our prices, and put it on my content calendar.",
     "expect_any": ["plan_content"], "must_not": ["publish_post", "send_sms", "batch_email"]},
    {"id": "capture_idea",
     "message": "I have an idea I want to write about someday: five lessons from our launch. Just capture it for now.",
     "expect_any": ["capture_idea"], "must_not": ["publish_post", "plan_campaign"]},
    {"id": "set_goal",
     "message": "Set a goal: reach 50 contacts by June 30, tracked automatically. It's for our Q3 launch.",
     "expect_any": ["create_goal"], "must_not": ["create_growth_objective", "create_task"]},
    {"id": "growth_objective",
     "message": "Put this on my growth timeline: we're committing to launch a group coaching program by March 1. Steps: outline in December, beta cohort in January, launch March 1.",
     "expect_any": ["create_growth_objective"], "must_not": ["create_goal", "send_sms"]},
    {"id": "faq",
     "message": "Add this to my FAQ: Do you offer virtual sessions? Yes, every session can be on Zoom.",
     "expect_any": ["add_faq"], "must_not": ["send_sms", "batch_email"]},
    {"id": "policy",
     "message": "My cancellation policy is 24 hours notice or the session is charged. Save that.",
     "expect_any": ["set_business_policy"], "must_not": ["send_sms", "batch_email"]},
    {"id": "testimonial",
     "message": "Ada said: 'Working with Eval Co changed how I run my week.' Add that as a testimonial from Ada.",
     "expect_any": ["add_testimonial"], "must_not": ["send_sms", "draft_and_send"]},
    {"id": "campaign_status",
     "message": "How are my outreach campaigns doing?",
     "expect_any": ["campaign_status"], "must_not": ["plan_campaign", "batch_email"]},
    {"id": "ledger",
     "message": "Search the record: what did you change on Monica's invoices last month?",
     "expect_any": ["search_ledger"], "must_not": ["void_invoice", "delete_invoice", "send_invoice"]},
    {"id": "lead_time",
     "message": "Don't let anyone book me with less than 24 hours notice.",
     "expect_any": ["set_lead_time"], "must_not": ["set_availability_day", "send_sms"]},
]


def _row(case: Dict[str, Any]) -> Dict[str, Any]:
    """The turn eval's row shape: the expected verb as a set of one is
    scored after the fact against `expect_any`."""
    return {"id": case["id"], "message": case["message"], "expect": [],
            "must_not": case.get("must_not") or [], "business": case.get("business")}


def score(case: Dict[str, Any], taken: List[str], looked_up: List[str]) -> Dict[str, Any]:
    hit = [v for v in case["expect_any"] if v in taken]
    bad = [v for v in case.get("must_not") or [] if v in taken]
    return {"id": case["id"], "found": bool(hit), "verb": hit[0] if hit else None,
            "forbidden": bad, "looked_up": looked_up,
            "lookup_before_use": bool(hit) and any(v in looked_up for v in hit),
            "ok": bool(hit) and not bad}


def run_live(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; --live makes real calls.", file=sys.stderr)
        sys.exit(2)
    import pytest
    import chief_of_staff as cos
    import chief_lean_brief
    import chief_tool_loop as ctl
    results = []
    for case in cases:
        mp = pytest.MonkeyPatch()
        try:
            real_prompt = cos._build_system_prompt
            row = _row(case)
            biz = te._business_for(row)
            te._stub_turn(mp, biz, row)
            mp.setattr(cos, "_build_system_prompt", real_prompt)
            dispatched: List[Dict[str, Any]] = []
            native_reads: List[str] = []
            looked: List[str] = []
            execute_tool = ctl.execute_tool_use
            guide = chief_lean_brief.tool_result

            async def _observe_tool(client, biz, name, args):
                import action_registry
                if action_registry.effect(name) == action_registry.READ:
                    native_reads.append(name)
                return await execute_tool(client, biz, name, args)

            def _observe_guide(args):
                looked.append(str((args or {}).get("name") or ""))
                return guide(args)

            mp.setattr(ctl, "execute_tool_use", _observe_tool)
            mp.setattr(chief_lean_brief, "tool_result", _observe_guide)
            mp.setattr(cos, "_execute_actions", te._door_spy(dispatched))
            print(f"→ {case['id']} …", file=sys.stderr, flush=True)
            started = time.time()
            out = asyncio.run(cos.chief_chat(
                cos.ChatRequest(business_id=biz["id"], message=case["message"]),
                te._Session()))
            taken = [a.get("type") for a in out.get("actions_taken", []) if isinstance(a, dict)]
            taken = list(dict.fromkeys(taken + [a.get("type") for a in dispatched] + native_reads))
            r = score(case, taken, looked)
            r["took"] = taken
            r["seconds"] = round(time.time() - started, 1)
            r["reply"] = (out.get("response") or "")[:300]
            results.append(r)
            print(f"  {'ok ' if r['ok'] else 'MISS'} took={taken or '-'} looked_up={looked or '-'}",
                  file=sys.stderr)
        finally:
            mp.undo()
    return {"mode": "live", "brief": os.environ.get("CHIEF_BRIEF") or "full", "results": results,
            "found": sum(r["found"] for r in results), "ok": sum(r["ok"] for r in results),
            "total": len(results),
            "lookup_before_use": sum(r["lookup_before_use"] for r in results)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="hit the real model")
    ap.add_argument("--list", action="store_true", help="print the rows")
    ap.add_argument("--only", help="comma-separated row ids")
    ap.add_argument("--out", help="write the report as JSON")
    args = ap.parse_args()
    cases = CASES
    if args.only:
        want = set(args.only.split(","))
        cases = [c for c in CASES if c["id"] in want]
    if args.list or not args.live:
        for c in cases:
            print(f"{c['id']:18s} {'/'.join(c['expect_any']):28s} {c['message']}")
        return 0
    report = run_live(cases)
    print(f"{report['brief']}: {report['ok']}/{report['total']} right verb, nothing forbidden; "
          f"looked up first: {report['lookup_before_use']}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
