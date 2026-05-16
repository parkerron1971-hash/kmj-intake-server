"""Spike-only Phase D convergence test.

Fires route_module for the three known spike businesses 3 times each
(9 Sonnet 4.5 calls, ~$0.09). Reports per-business module + confidence
+ reasoning, then a convergence verdict per business:

  CONVERGENT      — 3/3 same module with all confidences >= 0.8
  MOSTLY CONVERGENT — 3/3 same module with at least one confidence < 0.8
  SPLIT             — runs disagree on module

Expected (per Pass 4.0g Phase D scope):
  KMJ Creative Solutions     -> cathedral (creative agency framed as
                                strategic consultancy)
  Director Loop Test         -> cathedral (technical consultancy,
                                methodology-driven)
  RoyalTeez Designz          -> studio_brut (custom apparel design,
                                visual portfolio brand)

Run via:
  railway run python -m agents.composer._spike_routing_convergence
"""
from __future__ import annotations

import json
import sys
import traceback
from collections import Counter
from typing import Any, Dict, List

from agents.composer.module_router import route_module

BUSINESSES = [
    ("KMJ Creative Solutions", "12773842-3cc6-41a7-9094-b8606e3f7549", "cathedral"),
    ("Director Loop Test",     "c8b7e157-903b-40c9-b5f2-700f196fe35b", "cathedral"),
    ("RoyalTeez Designz",      "a8d1abb7-b8c5-4ee0-8d46-84e69efc220d", "studio_brut"),
]

RUNS_PER_BUSINESS = 3


def _verdict(modules: List[str], confidences: List[float]) -> str:
    counts = Counter(modules)
    most_common_mod, most_common_count = counts.most_common(1)[0]
    if most_common_count == len(modules):
        if all(c >= 0.8 for c in confidences):
            return f"CONVERGENT (3/3 {most_common_mod}, all conf >= 0.8)"
        return (
            f"MOSTLY CONVERGENT (3/3 {most_common_mod}, "
            f"min conf {min(confidences):.2f} < 0.8)"
        )
    return f"SPLIT — module counts: {dict(counts)}"


def main() -> int:
    print("=== Phase D routing convergence test ===")
    print(f"Firing {RUNS_PER_BUSINESS} runs per business x "
          f"{len(BUSINESSES)} businesses = "
          f"{RUNS_PER_BUSINESS * len(BUSINESSES)} Sonnet calls. "
          f"~${0.01 * RUNS_PER_BUSINESS * len(BUSINESSES):.2f}.\n", flush=True)

    overall: List[Dict[str, Any]] = []
    for name, bid, expected in BUSINESSES:
        print(f"--- {name} ({bid}) — expected: {expected} ---", flush=True)
        runs: List[Dict[str, Any]] = []
        for run_idx in range(1, RUNS_PER_BUSINESS + 1):
            try:
                d = route_module(bid)
                runs.append(d)
                print(
                    f"  run #{run_idx}: "
                    f"module={d.get('module_id'):>12} | "
                    f"conf={d.get('confidence'):.2f} | "
                    f"alt={d.get('alternative_module')}",
                    flush=True,
                )
                reasoning = (d.get("reasoning") or "").strip().replace("\n", " ")
                print(f"    reasoning: {reasoning[:240]}"
                      f"{'...' if len(reasoning) > 240 else ''}", flush=True)
            except Exception as exc:
                print(f"  run #{run_idx}: ERROR {exc}", flush=True)
                traceback.print_exc()
                runs.append({"_error": str(exc)})

        modules = [r.get("module_id") for r in runs if r.get("module_id")]
        confs = [r.get("confidence") for r in runs if r.get("confidence") is not None]
        verdict = _verdict(modules, confs) if modules else "ALL ERRORED"
        matches_expected = (
            "MATCHES EXPECTED"
            if modules and Counter(modules).most_common(1)[0][0] == expected
            else f"DIVERGES (expected {expected})"
        )
        print(f"  verdict: {verdict}")
        print(f"  vs expected: {matches_expected}\n", flush=True)

        overall.append({
            "name": name,
            "business_id": bid,
            "expected": expected,
            "modules": modules,
            "confidences": confs,
            "verdict": verdict,
            "matches_expected": matches_expected,
        })

    print("=== CONVERGENCE SUMMARY ===")
    for entry in overall:
        print(
            f"  {entry['name']:30s} -> {entry['verdict']} "
            f"| {entry['matches_expected']}"
        )

    # Per-business JSON for downstream report assembly
    print("\n=== RAW PER-RUN JSONs ===")
    for entry in overall:
        print(f"### {entry['name']}")
        print(json.dumps(
            {"modules": entry["modules"], "confidences": entry["confidences"]},
            indent=2,
        ))

    return 0


if __name__ == "__main__":
    sys.exit(main())
