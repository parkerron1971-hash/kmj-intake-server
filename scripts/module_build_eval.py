#!/usr/bin/env python3
# scripts/module_build_eval.py
# ─────────────────────────────────────────────────────────────────────
# THE MODULE BUILD EVAL — does a change to the generator still build the
# right thing?
#
# WHY THIS EXISTS. The build-capability arc left one item explicitly
# blocked: moving guidance OUT of module_spec_generator._SYSTEM_PROMPT
# (307 lines, ~17.8KB) and into build_skills/. Extraction is not a
# refactor — a section that stops being in the base prompt is a section
# that non-matching builds no longer receive. The only honest way to know
# whether that cost anything is to build the same intakes before and
# after and compare. Until this harness runs, "the prompt got smaller"
# and "Chief still builds as well" are two claims, and only the first one
# is free.
#
# MANUAL ONLY, like scripts/design_acceptance.py. It makes real Sonnet
# calls against real intakes, so it can never ride the fake-based pytest
# suite. It needs ANTHROPIC_API_KEY, which lives on Railway, not on a dev
# machine — run it there or export a key locally.
#
#   python scripts/module_build_eval.py                 # score current HEAD
#   python scripts/module_build_eval.py --out before.json
#   ...make the change...
#   python scripts/module_build_eval.py --out after.json
#   python scripts/module_build_eval.py --compare before.json after.json
#
# WHAT IT SCORES. Structural properties only, computed deterministically:
# does the spec validate, would the app render it (module_inspect — the
# same contract DynamicModule enforces), did it produce the fields and
# triggers this intake obviously calls for. It does NOT ask a model to
# grade taste. A judge model would add its own variance to the thing we
# are trying to measure, and every check here is one a human would agree
# with on sight.
#
# READ THE VARIANCE NOTE BEFORE TRUSTING A DIFF. The generator runs at
# temperature 0.4, so two runs of the SAME code differ. Run the baseline
# twice and look at the spread before concluding a change caused
# anything: a 1-point move is noise. That is why --compare prints both
# the per-case detail and the run-to-run caveat rather than a verdict.

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import module_inspect            # noqa: E402
import module_spec_generator     # noqa: E402


# ─── The fixtures ─────────────────────────────────────────────────────
# Each case is a real practitioner sentence plus the structural facts any
# competent build of it must satisfy. `expect_field_types` is what the
# shape genuinely requires — not a wish list, so a miss is a real miss.

CASES: List[Dict[str, Any]] = [
    {
        "id": "booking",
        "business": {"name": "Cut & Fade", "type": "barber"},
        "intake": ("I need to keep track of my appointments — who's coming in, "
                   "what they booked, when, and whether they showed up."),
        "expect_field_types": ["date", "select"],
        "expect_any_field_types": ["contact_link", "offering_ref"],
        "expect_trigger_kinds": ["overdue"],
        "expect_skill": "booking-module",
    },
    {
        "id": "pipeline",
        "business": {"name": "Ridgeline Consulting", "type": "consultant"},
        "intake": ("I want a board of my leads moving through stages so I can "
                   "see what's stuck — new enquiry through to won or lost."),
        "expect_field_types": ["select"],
        "expect_views": ["board"],
        "expect_trigger_kinds": [],
        "expect_skill": "pipeline-module",
    },
    {
        "id": "feedback",
        "business": {"name": "Bloom Therapy", "type": "coach"},
        "intake": ("After each session I want to record how the client rated it "
                   "out of five and what they said, so I can spot a bad trend."),
        "expect_field_types": ["rating", "textarea"],
        "expect_trigger_kinds": [],
        "expect_skill": "feedback-module",
    },
    {
        "id": "equipment",
        "business": {"name": "Northgate Studio", "type": "custom"},
        "intake": ("Track the gear I lend out: what it is, who has it, when it's "
                   "due back, and what it cost me."),
        "expect_field_types": ["date", "currency"],
        "expect_any_field_types": ["contact_link", "text"],
        "expect_trigger_kinds": ["overdue"],
    },
    {
        # Added after round 2 shipped module_ref. The four changes scored a
        # clean 36/36 and NOT ONE CASE PRODUCED A module_ref — none of the
        # intakes described a relationship between two modules, so the
        # headline field type of that round was unverified end to end. Unit
        # tests proved the contract; nothing proved Chief emits one. That is
        # the exact shape of every bug this harness has caught.
        #
        # This intake names two trackable objects AND the link between them,
        # so decomposition (G13) should produce both modules and wire the
        # dependent one back with module_ref. A single module with a text
        # "job" field is precisely the failure module_ref exists to fix, and
        # should score as one.
        "id": "linked",
        "business": {"name": "Harbour Trades", "type": "service_provider"},
        "intake": ("I run jobs for customers, and I invoice against each job. "
                   "I want to see what is still unbilled on a job."),
        "expect_field_types": ["module_ref", "currency"],
        "expect_trigger_kinds": [],
        "expect_skill": "payments-module",
    },
    {
        # The first live gap the fallback banner ever recorded that a
        # practitioner actually used: a credit-repair consultant's
        # "Credit Profiles" landed on fallback_generic with the reason
        # "needs a CreditScoreTracker archetype with time-series
        # visualization ... and milestone alerts". progress_tracker is that
        # archetype; this case is that intake.
        "id": "tracker",
        "business": {"name": "Clear Path Credit", "type": "consultant"},
        "intake": ("I help clients repair their credit. I want to log each "
                   "person's score every month and watch it climb toward 720, "
                   "and be told the day someone gets there."),
        "expect_field_types": ["number", "date", "contact_link"],
        "expect_trigger_kinds": ["target_reached"],
        "expect_archetype": "progress_tracker",
        "expect_skill": "tracker-module",
    },
    {
        "id": "vague",
        "business": {"name": "Harbour Co", "type": "custom"},
        "intake": "I need to stay on top of things.",
        # Deliberately underspecified.
        #
        # CORRECTED after run 2. This case used to assert that the model
        # REFUSES and asks a clarifying question. That rule lives in the
        # frontend AI tab (ModuleBuilder.tsx), NOT in this path — the
        # generator's only stated contract for a vague intake is
        # "confidence: 'low' if vague". Run 1 produced no specs and run 2
        # produced a generic "Items" module, and BOTH are within spec; the
        # score rose 1/1 -> 4/4 for what looked like worse behaviour, and
        # neither number meant what the note claimed.
        #
        # So test the contract that exists: whatever it builds, it must say
        # it is not sure.
        "expect_field_types": [],
        "expect_trigger_kinds": [],
        "expect_confidence": "low",
        "note": "underspecified on purpose — the contract is low confidence, "
                "not refusal; read what it built",
    },
]


# ─── Scoring ──────────────────────────────────────────────────────────

def score_case(case: Dict[str, Any], result: Dict[str, Any],
               skills: Optional[List[str]] = None) -> Dict[str, Any]:
    """Deterministic. Every point is a fact about the produced spec."""
    checks: List[Dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    # WHICH SKILL ATTACHED is scored, because the first live run found the
    # feedback case pulling booking-module ("rating" is not a substring of
    # "rated", while "session" matched booking) and every structural check
    # still passed. Chief was handed the wrong playbook and the number
    # said nothing. Checked before generation so a total failure still
    # reports the selection.
    want = case.get("expect_skill")
    if want is not None:
        got = skills or []
        check(f"skill:{want}", want in got, f"attached {got or '-'}")

    if not result.get("ok"):
        check("generated", False, str(result.get("error"))[:200])
        return _finish(case, checks, None, specs if 'specs' in dir() else [])

    specs = result.get("specs") or []
    check("generated", True, f"{len(specs)} spec(s)")
    if not specs:
        return _finish(case, checks, None, specs if 'specs' in dir() else [])

    # ACROSS EVERY SPEC, not just the first.
    #
    # This read specs[0] and nothing else, which made it blind to exactly
    # the thing it was extended to check. The `linked` case decomposed
    # correctly into Jobs + Invoices and scored field_type:module_ref as a
    # MISS — because the module_ref lives on the Invoices spec, pointing
    # back at Jobs, and the scorer only ever looked at Jobs. The parent of
    # a relationship never holds the reference; the child does. So a
    # harness that reads one spec can never see a link.
    #
    # A proposal is one answer to one intake. Score the answer.
    spec = specs[0]                      # for confidence + the summary
    types, views, trigger_kinds = set(), set(), set()
    unrenderable, all_warnings = [], []
    for sp in specs:
        sch = sp.get("schema") or {}
        for f in (sch.get("fields") or []):
            if isinstance(f, dict):
                types.add(f.get("type"))
        views |= set(sch.get("views") or [])
        for t in ((sp.get("agent_config") or {}).get("triggers") or []):
            if isinstance(t, dict):
                trigger_kinds.add(t.get("type"))
        rep = module_inspect.inspect_module_schema(
            sch, sp.get("agent_config"), sp.get("archetype"))
        if not rep["renderable"]:
            unrenderable.append(f"{sp.get('slug') or sp.get('name')}: "
                                + "; ".join(rep["problems"][:2]))
        all_warnings.extend(f"{sp.get('slug') or sp.get('name')}: {w}"
                            for w in rep["warnings"])

    # EVERY spec must render. One red module in a two-module proposal is
    # still a practitioner staring at an error panel.
    check("renders", not unrenderable, "; ".join(unrenderable[:3]))
    check("no_warnings", not all_warnings, "; ".join(all_warnings[:3]))

    for t in case.get("expect_field_types", []):
        check(f"field_type:{t}", t in types, f"got {sorted(types)}")

    any_of = case.get("expect_any_field_types") or []
    if any_of:
        check("field_type:any_of:" + "|".join(any_of),
              bool(types & set(any_of)), f"got {sorted(types)}")

    for v in case.get("expect_views", []):
        check(f"view:{v}", v in views, f"got {sorted(views)}")

    for k in case.get("expect_trigger_kinds", []):
        check(f"trigger:{k}", k in trigger_kinds, f"got {sorted(trigger_kinds)}")

    # WHICH ARCHETYPE — the surface the practitioner actually gets. A
    # tracker that validates, renders and attaches the right skill but
    # lands on fallback_generic is a plain table with a banner, which is
    # the exact outcome the archetype exists to replace.
    want_arch = case.get("expect_archetype")
    if want_arch:
        got_archs = sorted({sp.get("archetype") for sp in specs})
        check(f"archetype:{want_arch}", want_arch in got_archs, f"got {got_archs}")

    # Every field type used must be one the vocabulary allows. A spec that
    # invents a type validates nowhere and renders nowhere.
    import module_vocabulary
    unknown = types - set(module_vocabulary.FIELD_TYPES)
    check("known_field_types", not unknown, f"unknown: {sorted(unknown)}")

    # A vague intake may still produce a module — what it must not do is
    # claim certainty about one. This is the generator's actual stated
    # contract, and the only thing separating "reasonable guess" from
    # "confidently wrong".
    want_conf = case.get("expect_confidence")
    if want_conf:
        got_conf = spec.get("confidence")
        check(f"confidence:{want_conf}", got_conf == want_conf, f"got {got_conf!r}")

    return _finish(case, checks, spec, specs)


def _summarise(spec: Dict[str, Any]) -> Dict[str, Any]:
    sch = spec.get("schema") or {}
    return {
        "name": spec.get("name"),
        "slug": spec.get("slug"),
        "archetype": spec.get("archetype"),
        "fields": [(f.get("name"), f.get("type"))
                   + ((f.get("module_slug"),) if f.get("type") == "module_ref" else ())
                   for f in (sch.get("fields") or [])],
        "views": sch.get("views"),
        "triggers": [t.get("type") for t in
                     ((spec.get("agent_config") or {}).get("triggers") or [])],
        "confidence": spec.get("confidence"),
    }


def _finish(case, checks, spec, specs=None) -> Dict[str, Any]:
    passed = sum(1 for c in checks if c["ok"])
    return {
        "id": case["id"],
        "score": passed,
        "total": len(checks),
        "checks": checks,
        "note": case.get("note"),
        "spec_summary": None if not spec else _summarise(spec),
        # Every module in the proposal, so a decomposition can be read.
        # Showing only the first is how the linked case looked like a
        # failure when the answer was on the module the summary omitted.
        "specs": [_summarise(sp) for sp in (specs or [])],
    }


def run(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. This harness makes real calls; "
              "run it where the key lives (Railway) or export one.",
              file=sys.stderr)
        sys.exit(2)

    results = []
    for case in cases:
        print(f"→ {case['id']} …", file=sys.stderr, flush=True)
        started = time.time()
        # Resolve the selection first so it can be scored even if the
        # generation blows up.
        try:
            import build_skills
            attached = [s["name"] for s in build_skills.select_skills(
                case["intake"], case["business"].get("type", ""))]
        except Exception:                                     # noqa: BLE001
            attached = []
        try:
            out = module_spec_generator.generate_module_proposal(
                case["business"], case["intake"])
        except Exception as e:                                # noqa: BLE001
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        scored = score_case(case, out, attached)
        scored["seconds"] = round(time.time() - started, 1)
        scored["skills"] = attached
        results.append(scored)
        print(f"  {scored['score']}/{scored['total']}"
              f"  skills={scored['skills'] or '-'}", file=sys.stderr)

    total = sum(r["score"] for r in results)
    possible = sum(r["total"] for r in results)
    return {
        "results": results,
        "total": total,
        "possible": possible,
        "prompt_chars": len(module_spec_generator._SYSTEM_PROMPT),
    }


def compare(before: Dict[str, Any], after: Dict[str, Any]) -> int:
    print(f"\nprompt size : {before['prompt_chars']} → {after['prompt_chars']} chars "
          f"({after['prompt_chars'] - before['prompt_chars']:+d})")
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
        print(f"{flag} {r['id']:<10} {prior['score']}/{prior['total']} → "
              f"{r['score']}/{r['total']}  ({delta:+d})")
        if delta < 0:
            regressions += 1
            now_failing = {c["check"] for c in r["checks"] if not c["ok"]}
            was_failing = {c["check"] for c in prior["checks"] if not c["ok"]}
            for c in sorted(now_failing - was_failing):
                detail = next(x["detail"] for x in r["checks"] if x["check"] == c)
                print(f"     newly failing: {c}  {detail}")

    print("\nNOTE: the generator runs at temperature 0.4, so two runs of the "
          "SAME code differ. Before blaming a change, run the baseline twice "
          "and look at the spread. A one-point move is noise.")
    if regressions:
        print(f"\n{regressions} case(s) scored lower. Not automatically a "
              "veto — read the newly-failing checks above and decide.")
    return 1 if regressions else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", help="write results as JSON")
    ap.add_argument("--only", help="run one case by id")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="compare two result files; makes no API calls")
    args = ap.parse_args()

    if args.compare:
        with open(args.compare[0], encoding="utf-8") as f:
            before = json.load(f)
        with open(args.compare[1], encoding="utf-8") as f:
            after = json.load(f)
        return compare(before, after)

    cases = CASES
    if args.only:
        cases = [c for c in CASES if c["id"] == args.only]
        if not cases:
            print(f"no case with id {args.only!r}", file=sys.stderr)
            return 2

    report = run(cases)
    print(f"\nTOTAL {report['total']}/{report['possible']}  "
          f"(prompt {report['prompt_chars']} chars)")
    for r in report["results"]:
        if r.get("note"):
            print(f"  {r['id']}: {r['note']}")
            print(f"    produced: {json.dumps(r['spec_summary'], ensure_ascii=False)}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
