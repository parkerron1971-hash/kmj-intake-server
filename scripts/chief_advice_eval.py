#!/usr/bin/env python3
# scripts/chief_advice_eval.py
# ─────────────────────────────────────────────────────────────────────
# THE CHIEF ADVICE EVAL — when a practitioner asks what Chief thinks, is
# the answer real direction?
#
# WHY THIS EXISTS. The turn eval scores which verbs a sentence becomes and
# says nothing about the words; the factual eval scores whether figures are
# true. Neither can tell "you should raise your rate to $250 and here is
# how" from "it depends — what's your current rate?", and neither sees an
# answer the answer check withheld as "No action ran … try again?". Kevin,
# 2026-09-28: "if people are asking for thoughts it should give some level
# of direction advice that can really be helpful, like the strategy coach."
#
# WHAT A ROW IS. A question a practitioner really asks, and the business it
# is asked in: a brand-new one (three contacts, nothing else) or an
# established one (offerings with prices, upcoming sessions, open
# invoices, clients at risk), across verticals. The turn runs for real —
# the real prompt, the real model, the tool loop and the answer check —
# with every read stubbed, so nothing touches Supabase and nothing is sent.
#
# TWO SCORES, KEPT APART:
#
#   checks   (always; deterministic) — did it answer (not walled), lead with
#            the answer rather than a question, commit to a recommendation,
#            offer a next step Chief can take, carry no unverified-claims
#            block, and write nothing on its own. Cheap proxies; a human
#            would agree with each on sight.
#
#   grade    (--grade; an LLM grader, opt-in) — the substance: used their
#            numbers, named the constraint, weighed options, recommended,
#            gave a doable next step, invented no business facts. A judge
#            adds its own variance, so it is reported beside the checks,
#            never folded into them, and Kevin spot-checks the replies.
#
#   python scripts/chief_advice_eval.py --live --out a.json
#   python scripts/chief_advice_eval.py --live --grade --only pricing_raise_est
#   python scripts/chief_advice_eval.py --compare a.json b.json
#
# Every run makes real model calls (about 6-8c a question). It is manual,
# like the live turn eval.

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))


# ─── The businesses ───────────────────────────────────────────────────

def _biz(type_: str, name: str, bid: str) -> Dict[str, Any]:
    return {"id": bid, "name": name, "type": type_, "owner_id": "00000000-0000-4000-8000-0000000000ee",
            "settings": {}}


def _contacts(biz, rows):
    out = []
    for i, (name, status, health) in enumerate(rows):
        out.append({"id": "00000000-0000-4000-8000-%012d" % (100 + i), "name": name,
                    "email": name.split()[0].lower() + "@example.com", "status": status,
                    "health_score": health, "business_id": biz["id"]})
    return out


def _new_context(biz):
    contacts = _contacts(biz, [("Marcus Reed", "active", 50), ("Monica Walton", "active", 50),
                               ("Ada Lovelace", "lead", 50)])
    return {"contacts": contacts, "contacts_lookup": contacts}


# An established practice: real prices, a calendar, money owed, people
# drifting. What a good answer should reach for.
_ESTABLISHED = {
    "coach": {
        "offerings": [("1:1 Coaching Session", 150, "session"), ("3-Month Coaching Package", 1200, "package"),
                      ("Free Discovery Call", 0, "consultation")],
        "contacts": [("Marcus Reed", "active", 82), ("Monica Walton", "active", 41), ("Ada Lovelace", "lead", 50),
                     ("Priya Shah", "active", 77), ("Jordan Lee", "active", 35), ("Sam Ortiz", "lead", 50),
                     ("Dana Kim", "past", 20), ("Chris Hall", "active", 68)],
        "sessions": ["Marcus Reed", "Priya Shah", "Chris Hall"],
        "invoices": [("Monica Walton", 1200, "overdue"), ("Jordan Lee", 150, "sent")],
    },
    "personal_services": {
        "offerings": [("Women's Cut", 65, "service"), ("Color + Cut", 160, "service"),
                      ("Blowout", 45, "service")],
        "contacts": [("Tasha Green", "active", 80), ("Maria Lopez", "active", 72), ("Kim Park", "active", 30),
                     ("Leah Brooks", "lead", 50), ("Nia Carter", "past", 15), ("Rosa Diaz", "active", 64)],
        "sessions": ["Tasha Green", "Maria Lopez", "Rosa Diaz", "Kim Park"],
        "invoices": [],
    },
    "contractor": {
        "offerings": [("Bathroom Remodel", 14000, "project"), ("Kitchen Remodel", 32000, "project"),
                      ("Handyman Hour", 95, "service")],
        "contacts": [("Tom Baker", "active", 70), ("Linda Moore", "lead", 50), ("Ray Evans", "lead", 50),
                     ("Grace Hill", "past", 40)],
        "sessions": ["Linda Moore"],
        "invoices": [("Tom Baker", 7000, "sent")],
    },
    "ministry": {
        "offerings": [("Sunday Service", 0, "event"), ("Youth Night", 0, "event"),
                      ("Marriage Workshop", 25, "event")],
        "contacts": [("Pat Johnson", "active", 75), ("Lee Wright", "active", 30), ("Gina Scott", "lead", 50),
                     ("Omar King", "active", 55), ("Beth Young", "past", 20)],
        "sessions": ["Pat Johnson"],
        "invoices": [],
    },
}


def _established_context(biz):
    spec = _ESTABLISHED[biz["type"]]
    contacts = _contacts(biz, spec["contacts"])
    by_name = {c["name"]: c for c in contacts}
    offerings = [{"name": n, "price": p, "category": c} for n, p, c in spec["offerings"]]
    products = [{"id": "00000000-0000-4000-8000-%012d" % (300 + i), "name": n, "price": p, "type": "service",
                 "currency": "USD", "active": True} for i, (n, p, _c) in enumerate(spec["offerings"])]
    sessions = [{"id": "00000000-0000-4000-8000-%012d" % (400 + i), "title": "Session with " + n,
                 "contact_id": by_name[n]["id"], "starts_at": "2026-10-0%dT15:00:00Z" % (i + 1),
                 "status": "scheduled"} for i, n in enumerate(spec["sessions"])]
    invoices = [{"id": "inv-%d" % i, "number": "INV-%03d" % (10 + i), "client": n,
                 "contact_id": by_name[n]["id"], "total": amt, "status": st,
                 "due_date": "2026-09-15" if st == "overdue" else "2026-10-10"}
                for i, (n, amt, st) in enumerate(spec["invoices"])]
    at_risk = [c for c in contacts if c["health_score"] < 45 and c["status"] == "active"]
    return {"contacts": contacts, "contacts_lookup": contacts, "offerings": offerings,
            "products": products, "sessions": sessions, "sessions_complete": True,
            "open_invoices": invoices, "at_risk": at_risk}


BUSINESSES = {
    "coach_new": (_biz("coach", "Eval Coaching", "00000000-0000-4000-8000-000000000010"), _new_context),
    "coach_est": (_biz("coach", "Northstar Coaching", "00000000-0000-4000-8000-000000000011"), _established_context),
    "salon_est": (_biz("personal_services", "Studio Nine Salon", "00000000-0000-4000-8000-000000000012"),
                  _established_context),
    "trades_est": (_biz("contractor", "Baker Build & Remodel", "00000000-0000-4000-8000-000000000013"),
                   _established_context),
    "church_est": (_biz("ministry", "Grace Harbor Church", "00000000-0000-4000-8000-000000000014"),
                   _established_context),
}


# ─── The questions ────────────────────────────────────────────────────
# Asked the way practitioners ask on the phone. Each is a request for
# direction; none asks Chief to do anything yet.

CASES: List[Dict[str, str]] = [
    {"id": "pricing_raise_new", "biz": "coach_new",
     "message": "I'm thinking about raising my 1:1 coaching rate. How should I think about pricing it?"},
    {"id": "pricing_raise_est", "biz": "coach_est",
     "message": "Should I raise my 1:1 rate? What would you charge?"},
    {"id": "clients_30d_new", "biz": "coach_new",
     "message": "Give me a plan to get five new clients in the next 30 days."},
    {"id": "clients_30d_est", "biz": "coach_est",
     "message": "Give me a plan to get five new clients in the next 30 days."},
    {"id": "revenue_90d_est", "biz": "coach_est",
     "message": "Map out a 90-day plan to double my monthly revenue."},
    {"id": "calls_math_est", "biz": "coach_est",
     "message": "How many discovery calls do I need a week to hit $10k a month?"},
    {"id": "group_vs_1on1_est", "biz": "coach_est",
     "message": "Should I offer a group program or stay with 1:1 clients? Walk me through the tradeoffs."},
    {"id": "package_design_est", "biz": "coach_est",
     "message": "How should I structure a 3-month coaching package and price it?"},
    {"id": "reschedulers_est", "biz": "coach_est",
     "message": "A client keeps rescheduling at the last minute. How should I handle it without losing them?"},
    {"id": "focus_week_new", "biz": "coach_new",
     "message": "What should I focus on this week to grow the business?"},
    {"id": "focus_week_est", "biz": "coach_est",
     "message": "What should I focus on this week to grow the business?"},
    {"id": "overdue_approach_est", "biz": "coach_est",
     "message": "Monica is late paying. How should I approach it without hurting the relationship?"},
    {"id": "metrics_est", "biz": "coach_est",
     "message": "What numbers should I be tracking every week, and what are good targets?"},
    {"id": "ads_new", "biz": "coach_new",
     "message": "Is it worth running Facebook ads at my stage? What budget would you start with?"},
    {"id": "salon_slow_days", "biz": "salon_est",
     "message": "Tuesdays and Wednesdays are dead. What should I do about it?"},
    {"id": "salon_rebook", "biz": "salon_est",
     "message": "How do I get more clients to rebook before they leave the chair?"},
    {"id": "trades_leads", "biz": "trades_est",
     "message": "I've got two leads sitting there. How do I turn more estimates into signed jobs?"},
    {"id": "trades_pricing", "biz": "trades_est",
     "message": "Am I charging enough for bathroom remodels? How would you decide?"},
    {"id": "church_engagement", "biz": "church_est",
     "message": "Some members have gone quiet. How should we reconnect with them this month?"},
    {"id": "church_workshop", "biz": "church_est",
     "message": "We want to fill the marriage workshop. What's the plan?"},
]

# Verbs an advice turn may run without being asked: reads, and opening a
# view. Anything that writes is a miss here.
_DANGER_WORDS = ("send", "create", "delete", "draft_and_send", "void", "charge", "publish")


# ─── The deterministic checks ─────────────────────────────────────────

def _walls():
    import chief_truth as truth
    return (truth.NO_ACTION_REPLY, truth.UNVERIFIED_REPLY, truth._LEFT_OUT,
            "I could not verify the explanation.")


_COMMIT = re.compile(
    r"\b(?:I'?d\b|I would|I recommend|my (?:recommendation|advice|pick|suggestion)|I suggest|"
    r"here'?s what I'?d|start (?:with|by|here)|focus on|the move is|do this|go with|"
    r"raise (?:it|your rate) to|charge \$?\d|price (?:it|them) at|aim for|my take)\b", re.I)
_NEXT_STEP = re.compile(
    r"\b(?:want me to|would you like me to|should I|shall I|I can (?:\w+\s+){0,3}(?:for you|now|today|this week)|"
    r"say the word|just say|I'?ll (?:set|draft|build|put|add|create|line) (?:\w+\s+){0,4}if you)\b", re.I)
_CAVEAT = re.compile(r"still unverified|I left out|general rules from what I know, not from your records", re.I)


def _first_sentence(text: str) -> str:
    t = re.sub(r"^\s*#+\s.*\n", "", (text or "").strip())
    parts = re.split(r"(?<=[.!?])\s+|\n+", t)
    return next((p for p in parts if p.strip()), "")


def score_reply(reply: str, taken: List[str]) -> Dict[str, Any]:
    """Deterministic checks for one advice reply. Pure: unit-tested."""
    import action_registry
    text = (reply or "").strip()
    walled = any(text.startswith(w) or text == w for w in _walls()) or not text
    writes = [v for v in taken if action_registry.effect(v) == action_registry.WRITE
              or any(d in (v or "") for d in _DANGER_WORDS)]
    checks = {
        "answered": not walled,
        "leads_with_answer": not walled and not _first_sentence(text).rstrip().endswith("?"),
        "commits": not walled and bool(_COMMIT.search(text)),
        "offers_next_step": not walled and bool(_NEXT_STEP.search(text)),
        "no_caveat_block": not walled and not _CAVEAT.search(text),
        "wrote_nothing": not writes,
    }
    return {"checks": checks, "score": sum(checks.values()), "total": len(checks),
            "words": len(text.split()), "writes": writes}


# ─── The grader (opt-in) ──────────────────────────────────────────────

GRADER_MODEL = os.environ.get("ADVICE_GRADER_MODEL", "claude-opus-5-5")
RUBRIC = """You grade one answer from Chief, an AI business partner, to a practitioner who asked for advice.
You get the question, a summary of the business's records Chief could see, and Chief's answer.
Score each criterion 0 (missing), 1 (partial) or 2 (clearly done):
- uses_their_data: grounds the advice in this business's actual records (prices, clients, calendar, money owed). If the records are nearly empty, 2 = says so briefly and still advises.
- names_constraint: identifies what is actually limiting them right now.
- weighs_options: gives real options or tradeoffs where the question calls for them (2 if a single clear path is the honest answer and it says why).
- recommends: commits to a specific recommendation instead of "it depends".
- next_step: ends with a concrete next step, ideally one Chief can do for them.
- no_invented_facts: states nothing about THIS business that the records do not show (general knowledge is fine when labelled or obviously general). 0 if it invents a figure, client or event.
Return JSON only."""
GRADE_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "integer", "enum": [0, 1, 2]} for k in (
        "uses_their_data", "names_constraint", "weighs_options", "recommends", "next_step", "no_invented_facts")},
    "required": ["uses_their_data", "names_constraint", "weighs_options", "recommends", "next_step",
                 "no_invented_facts"],
    "additionalProperties": False,
}
GRADE_SCHEMA["properties"]["note"] = {"type": "string"}


def _records_summary(biz, ctx) -> str:
    lines = [f"Business: {biz['name']} ({biz['type']})"]
    for key in ("offerings", "sessions", "open_invoices", "at_risk"):
        if ctx.get(key):
            lines.append(f"{key}: {json.dumps(ctx[key], default=str)[:1200]}")
    lines.append("contacts: " + ", ".join(f"{c['name']} ({c['status']}, health {c['health_score']})"
                                          for c in ctx.get("contacts_lookup") or []))
    return "\n".join(lines)


async def grade(question: str, summary: str, reply: str) -> Optional[Dict[str, Any]]:
    import httpx
    import llm_call
    payload = {"model": GRADER_MODEL, "max_tokens": 2000, "system": RUBRIC,
               "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": GRADE_SCHEMA}},
               "messages": [{"role": "user", "content": json.dumps(
                   {"question": question, "records": summary, "answer": reply})}]}
    async with httpx.AsyncClient() as client:
        resp = await llm_call.apost(client, payload, timeout=120, key=llm_call.api_key())
    if resp.status_code >= 400:
        return None
    text = "".join(b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text")
    try:
        return json.loads(text)
    except ValueError:
        return None


# ─── Live run ─────────────────────────────────────────────────────────

_USAGE: List[Dict[str, Any]] = []


def _capture_usage():
    """Meter in memory: the fixture businesses are not real rows, and a
    run should say what it cost per question."""
    import api_usage_logger as aul
    orig = {aul.log_api_usage_sync, aul.log_api_usage}

    def _sync(**kw):
        try:
            kw["cents"] = kw.get("cost_cents_override") or aul._compute_cost_cents(
                kw.get("model") or "", kw.get("input_tokens") or 0, kw.get("output_tokens") or 0,
                kw.get("cache_read_tokens") or 0, kw.get("cache_creation_tokens") or 0,
                kw.get("cache_creation_1h_tokens") or 0)
        except Exception:
            kw["cents"] = 0
        _USAGE.append(kw)

    async def _async(**kw):
        _sync(**kw)
    for mod in list(sys.modules.values()):
        for name in ("log_api_usage_sync", "log_api_usage"):
            try:
                if getattr(mod, name, None) in orig:
                    setattr(mod, name, _sync if name.endswith("sync") else _async)
            except Exception:
                pass


def run_live(cases: List[Dict[str, str]], with_grade: bool = False) -> Dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. --live makes real calls.", file=sys.stderr)
        sys.exit(2)
    import pytest
    import chief_of_staff as cos
    import chief_turn_eval as te
    _capture_usage()
    results = []
    for case in cases:
        biz, make_ctx = BUSINESSES[case["biz"]]
        ctx = {**te._fixture_context(biz), **make_ctx(biz)}
        mp = pytest.MonkeyPatch()
        try:
            real_prompt = cos._build_system_prompt
            mp.setattr(te, "_fixture_context", lambda b, c=None, _ctx=ctx: _ctx)
            te._stub_turn(mp, biz)
            mp.setattr(cos, "_build_system_prompt", real_prompt)
            taken_writes: List[str] = []

            async def _door(client, b, actions, user_id=None, prior_results=None, owner_text=None):
                out = []
                for a in actions:
                    taken_writes.append(a.get("type"))
                    out.append({"type": a.get("type"), "result": "ok", "label": f"did {a.get('type')}"})
                return out
            mp.setattr(cos, "_execute_actions", _door)
            print(f"→ {case['id']} …", file=sys.stderr, flush=True)
            _USAGE.clear()
            started = time.time()
            out = asyncio.run(cos.chief_chat(
                cos.ChatRequest(business_id=biz["id"], message=case["message"]), te._Session()))
            if not isinstance(out, dict):
                out = {"response": "", "actions_taken": []}
            reply = out.get("response") or ""
            taken = [a.get("type") for a in out.get("actions_taken", []) if isinstance(a, dict)]
            row = {"id": case["id"], "biz": case["biz"], "message": case["message"],
                   **score_reply(reply, taken_writes + taken),
                   "seconds": round(time.time() - started, 1),
                   "cents": round(sum(u.get("cents") or 0 for u in _USAGE), 2),
                   "grounding": (out.get("grounding") or {}).get("status"),
                   "reply": reply}
            if with_grade:
                row["grade"] = asyncio.run(grade(case["message"], _records_summary(biz, ctx), reply))
            results.append(row)
            print(f"  {row['score']}/{row['total']} {row['seconds']}s {row['grounding']}", file=sys.stderr)
        finally:
            mp.undo()
    return summarize(results)


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(results) or 1
    check_names = list(results[0]["checks"]) if results else []
    rates = {k: round(sum(r["checks"][k] for r in results) / n, 3) for k in check_names}
    graded = [r["grade"] for r in results if isinstance(r.get("grade"), dict)]
    grade_means = ({k: round(statistics.mean(g[k] for g in graded), 2)
                    for k in GRADE_SCHEMA["required"]} if graded else None)
    import chief_models
    return {
        "model": chief_models.model_for("chat"), "effort": chief_models.effort_for("chat"),
        "results": results, "rates": rates, "grade_means": grade_means,
        "walled": [r["id"] for r in results if not r["checks"]["answered"]],
        "median_seconds": statistics.median([r["seconds"] for r in results]) if results else 0,
        "mean_cents": round(statistics.mean([r["cents"] for r in results]), 2) if results else 0,
    }


def compare(before: Dict[str, Any], after: Dict[str, Any]) -> int:
    print(f"model   : {before.get('model')}/{before.get('effort')} → {after.get('model')}/{after.get('effort')}")
    for k in after.get("rates", {}):
        print(f"{k:18} {before['rates'].get(k, 0):.2f} → {after['rates'][k]:.2f}")
    if before.get("grade_means") and after.get("grade_means"):
        for k, v in after["grade_means"].items():
            print(f"grade {k:18} {before['grade_means'].get(k)} → {v}")
    print(f"walled  : {len(before.get('walled', []))} → {len(after.get('walled', []))}  {after.get('walled')}")
    print(f"median s: {before.get('median_seconds')} → {after.get('median_seconds')}")
    print(f"cents/q : {before.get('mean_cents')} → {after.get('mean_cents')}")
    print("\nNOTE: live runs vary. Run each side twice before calling a difference.")
    return 1 if len(after.get("walled", [])) > len(before.get("walled", [])) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="run the questions against the real model")
    ap.add_argument("--grade", action="store_true", help="also score substance with the LLM grader")
    ap.add_argument("--only", help="comma-separated case ids")
    ap.add_argument("--out", help="write the report as JSON")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()
    if args.compare:
        with open(args.compare[0], encoding="utf-8") as f:
            before = json.load(f)
        with open(args.compare[1], encoding="utf-8") as f:
            after = json.load(f)
        return compare(before, after)
    if not args.live:
        ap.error("the advice eval only has a live mode; the scorer is unit-tested in __tests__")
    ids = set((args.only or "").split(",")) - {""}
    cases = [c for c in CASES if not ids or c["id"] in ids]
    report = run_live(cases, with_grade=args.grade)
    for r in report["results"]:
        flag = "  " if r["score"] == r["total"] else "!!"
        g = r.get("grade")
        gs = f"  grade={sum(v for k, v in g.items() if k != 'note')}/12" if isinstance(g, dict) else ""
        print(f"{flag} {r['id']:<22} {r['score']}/{r['total']}  {r['seconds']:>5}s {r['cents']:>5}c{gs}")
    print("\nrates:", json.dumps(report["rates"]))
    if report["grade_means"]:
        print("grade:", json.dumps(report["grade_means"]))
    print(f"walled: {report['walled']}  median {report['median_seconds']}s  {report['mean_cents']}c/question")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
