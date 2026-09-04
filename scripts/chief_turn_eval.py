#!/usr/bin/env python3
# scripts/chief_turn_eval.py
# ─────────────────────────────────────────────────────────────────────
# THE CHIEF TURN EVAL — did the practitioner's sentence become the right
# verb, and nothing dangerous?
#
# WHY THIS EXISTS. Model releases are quarterly now and each one changes
# behaviour. Chief's lanes are swappable by env var (CHIEF_MODEL_<LANE>),
# which is the right design — but a swap nobody can measure is a guess,
# and until 2026-09-04 nothing measured a Chief turn end to end. Every
# fix in the action pipeline was a bug report from Kevin's phone.
#
# TWO MODES, ONE SCORER, named honestly:
#
#   replay   (default; runs in CI on every PR; deterministic, no key)
#            Each golden row carries the model's RECORDED reply — the
#            exact text a good turn produces — and the eval drives the
#            real pipeline with it: tag extraction, the dispatcher, the
#            gates, the tool loop for native-tool rows. It proves that
#            the sentence-to-verb machinery still turns a known-good
#            reply into the right actions and nothing else. It says
#            NOTHING about whether the model would produce that reply.
#
#   live     (opt-in; workflow_dispatch in CI or a local key)
#            The same rows against the real model, with every read
#            stubbed so nothing touches Supabase. Asserts the VERB SET,
#            never the prose — a judge model would add its own variance
#            to the thing being measured. Pin a lane with
#            CHIEF_MODEL_CHAT to compare models; use --out/--compare
#            like module_build_eval.
#
# WHAT A ROW IS. A practitioner sentence, the verbs it must produce, the
# verbs it must NEVER produce (the dangerous neighbours — "log the
# expense" must not create an invoice; "say goodbye" must not send
# anything), and a recorded reply in one of two encodings: an [ACTION:]
# tag, or a native tool call (chief_tool_loop, 2026-09-04). With both
# mechanisms live, a set that covered only one would cover half the
# surface.
#
#   python scripts/chief_turn_eval.py                  # replay, print
#   python scripts/chief_turn_eval.py --live --out a.json
#   python scripts/chief_turn_eval.py --compare a.json b.json

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── The golden set ───────────────────────────────────────────────────
# Authored, not mined: nothing in the system persists (message → reply →
# verbs) with the reply, and a tenant's conversation would be the wrong
# thing to mine anyway. Sentences come from the prompt's own worked
# examples and the bugs that reached the phone. `tag` rows record a
# bracket-tag reply; `tool` rows record a native tool call plus the
# sentence the model says after seeing the result.
#
# must_not is the point of a row, not decoration: each names the
# dangerous neighbour of the expected verb.

def _tag(verb: str, **args: Any) -> str:
    return "[ACTION:" + json.dumps({"type": verb, **args}) + "]"


CASES: List[Dict[str, Any]] = [
    # ── people ──────────────────────────────────────────────────────
    {"id": "create_contact_lead",
     "message": "Add Ada Lovelace as a lead, ada@example.com",
     "expect": ["create_contact"],
     "must_not": ["send_sms", "draft_and_send", "create_invoice"],
     "encoding": "tool",
     "tool_call": {"name": "create_contact",
                   "input": {"name": "Ada Lovelace", "email": "ada@example.com",
                             "status": "lead"}},
     "reply": "Added Ada Lovelace as a lead."},
    {"id": "create_contact_tag",
     "message": "New contact: Marcus Reed, 216-555-0100",
     "expect": ["create_contact"],
     "must_not": ["send_sms", "create_invoice"],
     "encoding": "tag",
     "reply": "Marcus is in. " + _tag("create_contact", name="Marcus Reed",
                                     phone="216-555-0100", status="lead")},
    {"id": "note_on_contact",
     "message": "Note on Marcus: he's interested in the leadership program",
     "expect": ["create_note"],
     "must_not": ["draft_email", "send_sms"],
     "encoding": "tool",
     "tool_call": {"name": "create_note",
                   "input": {"contact_id": "c-marcus",
                             "note": "Interested in the leadership program"}},
     "reply": "Noted on Marcus's record."},
    {"id": "log_call",
     "message": "Log that I called Marcus this morning about the retainer",
     "expect": ["log_activity"],
     "must_not": ["send_sms", "create_task"],
     "encoding": "tool",
     "tool_call": {"name": "log_activity",
                   "input": {"contact_id": "c-marcus", "activity_type": "call",
                             "notes": "Retainer discussion"}},
     "reply": "Logged the call with Marcus."},

    # ── work ─────────────────────────────────────────────────────────
    {"id": "create_task",
     "message": "Remind me to call Deacon Harris back by Friday",
     "expect": ["create_task"],
     "must_not": ["send_sms", "draft_email"],
     "encoding": "tool",
     "tool_call": {"name": "create_task",
                   "input": {"title": "Call Deacon Harris back", "due_date": "2026-09-11",
                             "priority": "high"}},
     "reply": "On your list for Friday."},
    {"id": "log_time",
     "message": "Log two hours on Monica's contract",
     "expect": ["log_time"],
     "must_not": ["create_invoice", "send_invoice", "bill_time_to_retainer"],
     "encoding": "tag",
     "reply": "Logged. " + _tag("log_time", contact_id="c-monica", hours=2,
                                description="drafted the engagement letter")},
    {"id": "log_expense",
     "message": "I spent $45 on gas at Shell today",
     "expect": ["log_expense"],
     "must_not": ["create_invoice", "mark_invoice_paid", "generate_payment_link"],
     "encoding": "tool",
     "tool_call": {"name": "log_expense",
                   "input": {"amount": 45.0, "category": "operating", "vendor": "Shell",
                             "note": "gas"}},
     "reply": "Logged $45 operating at Shell. It's in the books."},

    # ── calendar ─────────────────────────────────────────────────────
    {"id": "create_session",
     "message": "Put a coaching session with Marcus on my calendar Thursday at 2",
     "expect": ["create_session"],
     "must_not": ["create_booking", "send_sms", "draft_and_send"],
     "encoding": "tool",
     "tool_call": {"name": "create_session",
                   "input": {"contact_name": "Marcus", "title": "Coaching",
                             "scheduled_for": "2026-09-10T14:00:00Z",
                             "duration_minutes": 60}},
     "reply": "Thursday at 2 with Marcus is on the calendar."},
    {"id": "block_vacation",
     "message": "Block off next week, I'm on vacation",
     "expect": ["add_block_range"],
     "must_not": ["cancel_booking", "set_availability_day"],
     "encoding": "tool",
     "tool_call": {"name": "add_block_range",
                   "input": {"start": "2026-09-07", "end": "2026-09-13", "reason": "vacation"}},
     "reply": "Blocked the 7th through the 13th. Nobody can book those days."},

    # ── content, memory, notes ───────────────────────────────────────
    {"id": "plan_post",
     "message": "Plan a LinkedIn post for Thursday about building trust",
     "expect": ["plan_content"],
     "must_not": ["publish_post"],
     "encoding": "tool",
     "tool_call": {"name": "plan_content",
                   "input": {"title": "3 ways to build trust", "platform": "linkedin",
                             "scheduled_date": "2026-09-10"}},
     "reply": "Planned for Thursday on LinkedIn."},
    {"id": "remember_preference",
     "message": "Remember that I never take calls before 10am",
     "expect": ["remember"],
     "must_not": ["set_availability_day", "set_business_policy"],
     "encoding": "tag",
     "reply": "Got it. " + _tag("remember", category="boundary",
                                content="Never takes calls before 10am", importance=7)},
    {"id": "note_to_self",
     "message": "Note this for later: look into the grant Priya mentioned",
     "expect": ["save_note"],
     "must_not": ["create_task", "remember"],
     "encoding": "tool",
     "tool_call": {"name": "save_note",
                   "input": {"content": "Look into the grant Priya mentioned", "kind": "idea"}},
     "reply": "Noted for later."},

    # ── drafts: the line between drafting and sending ────────────────
    {"id": "draft_email_not_send",
     "message": "Draft a follow-up email to Ada about next steps",
     "expect": ["draft_email"],
     "must_not": ["draft_and_send", "approve_draft", "send_sms"],
     "encoding": "tool",
     "tool_call": {"name": "draft_email",
                   "input": {"contact_id": "c-ada", "subject": "Next steps",
                             "body": "Hi Ada — following up on our conversation. "
                                     "Here is what I'd suggest as next steps.",
                             "reason": "follow-up"}},
     "reply": "Draft is in your queue — review and send when ready."},
    {"id": "send_is_class_c_tag",
     "message": "Send that invoice to Marcus now",
     "expect": ["send_invoice"],
     "must_not": ["mark_invoice_paid", "delete_contact"],
     "encoding": "tag",
     "reply": "Sending it. " + _tag("send_invoice", invoice_id="latest")},

    # ── reads that must stay reads ───────────────────────────────────
    {"id": "goals_are_a_read",
     "message": "Am I on track for my goals?",
     "expect": ["check_goals"],
     "must_not": ["create_goal"],
     "encoding": "tag",
     "reply": "Let me check. " + _tag("check_goals")},
    {"id": "revenue_is_a_read",
     "message": "Show me my revenue breakdown",
     "expect": ["show_revenue"],
     "must_not": ["create_invoice", "log_expense"],
     "encoding": "tag",
     "reply": "Here's the picture. " + _tag("show_revenue")},

    # ── must-nots that are the whole row ─────────────────────────────
    {"id": "goodbye_closes_nothing_else",
     "message": "Thanks, that's all for today. Goodbye!",
     "expect": ["set_chat_window"],
     "must_not": ["send_sms", "draft_and_send", "delete_contact", "create_invoice"],
     "encoding": "tag",
     "reply": "Have a good one. " + _tag("set_chat_window", visible=False,
                                          keep_talking=False)},
    {"id": "question_about_goodbyes_is_not_one",
     "message": "Why does the app close when I say goodbye? Is that a bug?",
     "expect": [],
     "must_not": ["set_chat_window", "send_sms"],
     "encoding": "tag",
     "reply": "It's on purpose — a clear farewell closes the room. Say the word "
              "and I'll leave it open."},
    {"id": "undo",
     "message": "Undo that last one",
     "expect": ["undo_last"],
     "must_not": ["delete_contact", "cancel_booking"],
     "encoding": "tool",
     "tool_call": {"name": "undo_last", "input": {}},
     "reply": "Undone."},
]


# ─── Scoring ──────────────────────────────────────────────────────────

def score_case(case: Dict[str, Any], taken_verbs: List[str],
               extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Deterministic. `taken_verbs` are the verbs the turn actually
    produced (actions_taken types, in order). Every check is one a human
    would agree with on sight."""
    checks: List[Dict[str, Any]] = []
    got = set(taken_verbs)
    for v in case.get("expect") or []:
        checks.append({"check": f"expect:{v}", "ok": v in got,
                       "detail": f"took {sorted(got) or '-'}"})
    for v in case.get("must_not") or []:
        checks.append({"check": f"must_not:{v}", "ok": v not in got,
                       "detail": f"took {sorted(got) or '-'}"})
    if not case.get("expect"):
        # A row that expects nothing is testing restraint: any verb at
        # all is a miss, not only the named neighbours.
        checks.append({"check": "no_action", "ok": not got,
                       "detail": f"took {sorted(got) or '-'}"})
    if extra:
        for k, ok in extra.items():
            checks.append({"check": k, "ok": bool(ok), "detail": ""})
    score = sum(1 for c in checks if c["ok"])
    return {"id": case["id"], "encoding": case.get("encoding"),
            "score": score, "total": len(checks), "checks": checks,
            "taken": list(taken_verbs)}


def summarize(results: List[Dict[str, Any]], mode: str) -> Dict[str, Any]:
    return {
        "mode": mode,
        "results": results,
        "total": sum(r["score"] for r in results),
        "possible": sum(r["total"] for r in results),
        "failed_cases": [r["id"] for r in results if r["score"] < r["total"]],
    }


# ─── Replay: the pipeline, with a recorded reply ──────────────────────
#
# Stubs every I/O seam chief_chat has, the way __tests__/test_farewell_close.py
# does, and puts a spy on the door (_execute_actions) so the verbs the
# turn dispatched are observed WITHOUT reaching a handler. For a `tool`
# row the fake model performs the recorded tool call through
# chief_tool_loop.execute_tool_use — the real loop, the real budget, the
# real door — before answering.

def _stub_turn(monkeypatch, biz: Dict[str, Any]):
    import chief_of_staff as cos
    import rate_limit

    async def _instant(value=None):
        return value

    async def _fake_sb(client, method, path, body=None):
        return [biz]

    monkeypatch.setattr(rate_limit, "allow", lambda *a, **k: True)
    monkeypatch.setattr(cos, "_sb", _fake_sb)
    monkeypatch.setattr(cos, "_generate_missing_recurring_instances", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_autopilot_sweep", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_evaluate_escalations", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_gather_context",
                        lambda *a, **k: _instant({"business": biz, "contacts": []}))
    monkeypatch.setattr(cos, "_fetch_view_detail", lambda *a, **k: _instant(""))
    for name in ["_get_voice_examples", "_get_session_context",
                 "_get_time_context", "_get_habit_insights"]:
        monkeypatch.setattr(cos, name, lambda *a, **k: _instant(""))
    monkeypatch.setattr(cos, "_should_show_mentor_tip", lambda *a, **k: _instant(False))
    monkeypatch.setattr(cos, "_forecast_revenue", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_analyze_relationships", lambda *a, **k: _instant([]))
    monkeypatch.setattr(cos, "_build_system_prompt", lambda *a, **k: "SYSTEM")
    monkeypatch.setattr(cos, "_log_chief_activity", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_learn_patterns_async", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_compose_post_action_reply", lambda *a, **k: _instant(""))
    if hasattr(cos, "_archive_turn"):
        monkeypatch.setattr(cos, "_archive_turn", lambda *a, **k: _instant(None))

    import chief_bookkeeping
    import chief_proactive_suggestions
    import vertical_context
    monkeypatch.setattr(chief_bookkeeping, "gather_and_format", lambda *a, **k: "")
    monkeypatch.setattr(vertical_context, "build_vertical_learned_block", lambda *a, **k: "")
    monkeypatch.setattr(chief_proactive_suggestions,
                        "maybe_emit_proactive_suggestions", lambda *a, **k: None)


class _Session:
    class _User:
        id = "user-eval"
    user = _User()
    token = "eval-jwt"


BIZ = {"id": "biz-eval", "name": "Eval Co", "type": "coach", "owner_id": "user-eval",
       "settings": {}}


def run_replay_case(monkeypatch, case: Dict[str, Any]) -> Dict[str, Any]:
    import chief_of_staff as cos
    import chief_tool_loop as ctl

    _stub_turn(monkeypatch, BIZ)
    dispatched: List[str] = []

    async def _door(client, biz, actions, user_id=None, prior_results=None):
        out = []
        for a in actions:
            dispatched.append(a.get("type"))
            out.append({"type": a.get("type"), "result": "ok",
                        "label": f"did {a.get('type')}"})
        return out
    monkeypatch.setattr(cos, "_execute_actions", _door)

    async def fake_claude(*a, **k):
        if case.get("encoding") == "tool":
            tc = case["tool_call"]
            await ctl.execute_tool_use(None, BIZ, tc["name"], dict(tc.get("input") or {}))
        return case["reply"]
    monkeypatch.setattr(cos, "_call_claude", fake_claude)

    out = asyncio.run(cos.chief_chat(
        cos.ChatRequest(business_id=BIZ["id"], message=case["message"]), _Session()))
    taken = [a.get("type") for a in out.get("actions_taken", []) if isinstance(a, dict)]
    extra = {}
    if case.get("encoding") == "tool":
        # The tool row's own invariant: the verb reached the door through
        # the loop, and the turn did NOT also execute it as a tag.
        extra["tool_went_through_the_door"] = case["tool_call"]["name"] in dispatched
        extra["not_double_executed"] = dispatched.count(case["tool_call"]["name"]) == 1
        extra["reply_is_the_models_own"] = out.get("response") == case["reply"]
    return score_case(case, taken, extra)


def run_replay(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    import pytest  # the monkeypatch fixture, used standalone
    results = []
    for case in cases:
        mp = pytest.MonkeyPatch()
        try:
            results.append(run_replay_case(mp, case))
        finally:
            mp.undo()
    return summarize(results, "replay")


# ─── Live: the real model, every read stubbed ─────────────────────────

def run_live(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. --live makes real calls; run it "
              "where the key lives or export one.", file=sys.stderr)
        sys.exit(2)
    import pytest
    import chief_of_staff as cos
    results = []
    for case in cases:
        mp = pytest.MonkeyPatch()
        try:
            _stub_turn(mp, BIZ)
            # The real prompt this time — that is what is being measured.
            mp.delattr(cos, "_build_system_prompt", raising=False)
            dispatched: List[str] = []

            async def _door(client, biz, actions, user_id=None, prior_results=None):
                out = []
                for a in actions:
                    dispatched.append(a.get("type"))
                    out.append({"type": a.get("type"), "result": "ok",
                                "label": f"did {a.get('type')}"})
                return out
            mp.setattr(cos, "_execute_actions", _door)
            print(f"→ {case['id']} …", file=sys.stderr, flush=True)
            started = time.time()
            out = asyncio.run(cos.chief_chat(
                cos.ChatRequest(business_id=BIZ["id"], message=case["message"]),
                _Session()))
            taken = [a.get("type") for a in out.get("actions_taken", [])
                     if isinstance(a, dict)]
            scored = score_case(case, taken)
            scored["seconds"] = round(time.time() - started, 1)
            scored["reply"] = (out.get("response") or "")[:300]
            results.append(scored)
            print(f"  {scored['score']}/{scored['total']} took={taken or '-'}",
                  file=sys.stderr)
        finally:
            mp.undo()
    return summarize(results, "live")


# ─── Compare + CLI ────────────────────────────────────────────────────

def compare(before: Dict[str, Any], after: Dict[str, Any]) -> int:
    print(f"mode        : {before.get('mode')} → {after.get('mode')}")
    print(f"total score : {before['total']}/{before['possible']} → "
          f"{after['total']}/{after['possible']}\n")
    b = {r["id"]: r for r in before["results"]}
    regressions = 0
    for r in after["results"]:
        prior = b.get(r["id"])
        if not prior:
            continue
        delta = r["score"] - prior["score"]
        flag = "  " if delta >= 0 else "!!"
        print(f"{flag} {r['id']:<34} {prior['score']}/{prior['total']} → "
              f"{r['score']}/{r['total']}  ({delta:+d})")
        if delta < 0:
            regressions += 1
            now_failing = {c["check"] for c in r["checks"] if not c["ok"]}
            was_failing = {c["check"] for c in prior["checks"] if not c["ok"]}
            for c in sorted(now_failing - was_failing):
                print(f"     newly failing: {c}")
    if after.get("mode") == "live":
        print("\nNOTE: live runs are not deterministic. Run the baseline twice "
              "and look at the spread before blaming a change.")
    return 1 if regressions else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="hit the real model")
    ap.add_argument("--out", help="write results as JSON")
    ap.add_argument("--only", help="run one case by id")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()

    if args.compare:
        with open(args.compare[0], encoding="utf-8") as f:
            before = json.load(f)
        with open(args.compare[1], encoding="utf-8") as f:
            after = json.load(f)
        return compare(before, after)

    cases = [c for c in CASES if not args.only or c["id"] == args.only]
    report = run_live(cases) if args.live else run_replay(cases)
    for r in report["results"]:
        flag = "  " if r["score"] == r["total"] else "!!"
        print(f"{flag} {r['id']:<34} {r['score']}/{r['total']}  took={r['taken'] or '-'}")
    print(f"\n{report['mode']}: {report['total']}/{report['possible']}"
          + (f"  failed: {report['failed_cases']}" if report["failed_cases"] else ""))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    return 1 if report["failed_cases"] else 0


if __name__ == "__main__":
    sys.exit(main())
