"""Opt-in response-flow checks using fictional data and real configured models.

No business records are loaded and no generated actions are executed. Provider
usage is metered normally. Run --live with provider credentials.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chief_of_staff as chief
import chief_models
import chief_truth as truth


async def main():
    ctx = {key: [] for key in ("queue", "events", "sessions", "insights", "modules", "at_risk", "contacts_lookup")}
    ctx.update(business={"name": "Example Studio"}, module_counts={},
               contacts_total=0, contacts_by_status={}, avg_health=None)
    system = chief._build_system_prompt(ctx, False) + chief_models.VOICE_DELIVERY_BLOCK
    system += ("\nFictional owner notes: Example Studio offers coaching for first-time founders "
               "to get their first paying customer. No marketing strategy has been approved.")
    cases = [
        ("arithmetic", "What is 1+1?", []),
        ("social", "Thanks, that helped.", [
            {"role": "user", "content": "Help me pick a first step."},
            {"role": "assistant", "content": "Start by talking to one prospective customer."}]),
        ("business_and_marketing", "What is my business about, and what marketing approach would you suggest?", []),
    ]
    failures = []
    async with httpx.AsyncClient(timeout=90) as client:
        for name, message, history in cases:
            draft = await chief._call_claude(client, system, history + [{"role": "user", "content": message}],
                model=chief_models.model_for("voice"), max_tokens=chief_models.max_tokens_for("voice"),
                effort=chief_models.effort_for("voice"), enable_web_search=False)
            actions, answer = chief._extract_actions_and_clean(draft)
            print(json.dumps({"case": name, "draft": answer, "words": len(answer.split())}), flush=True)
            assert not actions, "Information/social response unexpectedly proposed an action"
            if name == "arithmetic":
                answer, meta = await truth.finalize_reply(client, answer, ctx=ctx, view_detail={}, taken=[],
                    message=message, business_id=None, reviewer=truth.review_reply)
                assert answer == "2." and meta["status"] == "calculated"
            elif name == "social":
                answer, meta = await truth.finalize_reply(client, answer, ctx=ctx, view_detail={}, taken=[],
                    message=message, business_id=None, reviewer=truth.review_reply)
                assert len(answer.split()) <= 25 and "?" not in answer, "Social turn reopened the interview"
            else:
                if len(answer.split()) > 110:
                    failures.append("Ordinary voice answer exceeded delivery budget")
                assert "founder" in answer.lower() and "customer" in answer.lower(), "Business substance omitted"
            print(json.dumps({"case": name, "answer": answer, "words": len(answer.split())}), flush=True)

        receipts = [{"type": "update_contact_status", "label": name, "result": "lead \u2192 inactive"}
                    for name in ("Ada", "Ben", "Cy")]
        receipts.append({"type": "enqueue_job", "label": "Remaining cleanup", "result": "queued"})
        message = "Move these leads to inactive and continue the cleanup."
        answer = await chief._compose_post_action_reply(client, message,
            "All the cleanup is done.", receipts)
        answer, meta = await truth.finalize_reply(client, answer, ctx={}, view_detail={}, taken=receipts,
            message=message, business_id=None, reviewer=truth.review_reply)
        print(json.dumps({"case": "receipt_batch", "answer": answer, "grounding": meta}), flush=True)
        assert "inactive" in answer.lower() and "queued" in answer.lower()
        assert "all the cleanup is done" not in answer.lower()
        assert meta["status"] in ("supported", "receipts", "trimmed")
    assert not failures, "; ".join(failures)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    if not parser.parse_args().live:
        parser.error("--live is required; configured provider calls are metered")
    asyncio.run(main())
