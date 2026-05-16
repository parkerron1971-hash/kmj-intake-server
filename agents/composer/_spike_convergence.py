"""Spike-only convergence diagnostic. Fires 2 more compositions per
business and prints a convergence report against the Phase 3 outputs.

Pass 4.0f Phase 4-bis — does Composer pick the same variant for the
same business across multiple runs? Convergent => intentional choice.
Divergent => low-confidence / arbitrary => surfaces an architectural
concern before Phase 5.

Run via:
  railway run python -m agents.composer._spike_convergence
"""
from __future__ import annotations

import json
import sys
import traceback
from collections import Counter
from typing import Any, Dict, List

from agents.composer.cathedral_hero_composer import compose_cathedral_hero

BUSINESSES = [
    ("KMJ Creative Solutions", "12773842-3cc6-41a7-9094-b8606e3f7549"),
    ("Director Loop Test",     "c8b7e157-903b-40c9-b5f2-700f196fe35b"),
    ("RoyalTeez Designz",      "a8d1abb7-b8c5-4ee0-8d46-84e69efc220d"),
]

# Phase 3 results — captured verbatim from CHECKPOINT 3 so we can
# compare run #1 (Phase 3) against runs #2 + #3 (this diagnostic).
PHASE_3_RESULTS = {
    "12773842-3cc6-41a7-9094-b8606e3f7549": {
        "variant": "asymmetric_right",
        "treatments": {
            "color_emphasis": "signal_dominant",
            "spacing_density": "generous",
            "emphasis_weight": "heading_dominant",
        },
        "heading_emphasis": "breakthrough",
    },
    "c8b7e157-903b-40c9-b5f2-700f196fe35b": {
        "variant": "annotated_hero",
        "treatments": {
            "color_emphasis": "signal_dominant",
            "spacing_density": "standard",
            "emphasis_weight": "balanced",
        },
        "heading_emphasis": "loop",
    },
    "a8d1abb7-b8c5-4ee0-8d46-84e69efc220d": {
        "variant": "asymmetric_right",
        "treatments": {
            "color_emphasis": "signal_dominant",
            "spacing_density": "standard",
            "emphasis_weight": "heading_dominant",
        },
        "heading_emphasis": "throne",
    },
}


def _summarize_run(run: Dict[str, Any]) -> str:
    v = run.get("variant", "?")
    t = run.get("treatments", {})
    he = (run.get("content") or {}).get("heading_emphasis", "?")
    return (
        f"variant={v} | "
        f"{t.get('color_emphasis','?')}/{t.get('spacing_density','?')}/"
        f"{t.get('emphasis_weight','?')} | "
        f"emphasis_word={he!r}"
    )


def main() -> int:
    print("=== Phase 4-bis: Composer convergence diagnostic ===")
    print(f"Firing 2 more calls per business (6 total). Cost ~$0.30.\n", flush=True)

    all_runs: Dict[str, List[Dict[str, Any]]] = {}
    for name, bid in BUSINESSES:
        runs: List[Dict[str, Any]] = []
        # Seed the runs list with Phase 3's result (already known) so
        # we get a 3-way comparison.
        seed = PHASE_3_RESULTS[bid]
        runs.append({
            "_label": "run #1 (Phase 3)",
            "variant": seed["variant"],
            "treatments": seed["treatments"],
            "content": {"heading_emphasis": seed["heading_emphasis"]},
            "reasoning": "(captured at Phase 3 — see CHECKPOINT 3)",
        })
        for run_idx in (2, 3):
            print(f"--- {name} — firing run #{run_idx} ---", flush=True)
            try:
                comp = compose_cathedral_hero(bid)
                comp["_label"] = f"run #{run_idx} (diagnostic)"
                runs.append(comp)
                print(f"  {_summarize_run(comp)}", flush=True)
            except Exception as exc:
                print(f"  ERROR: {exc}", flush=True)
                traceback.print_exc()
                runs.append({"_label": f"run #{run_idx}", "_error": str(exc)})
        all_runs[bid] = runs
        print("", flush=True)

    print("\n=== CONVERGENCE REPORT ===\n", flush=True)
    for name, bid in BUSINESSES:
        runs = all_runs[bid]
        variants = [r.get("variant") for r in runs if r.get("variant")]
        v_counter = Counter(variants)
        treatments_keys = [
            (r.get("treatments", {}).get("color_emphasis"),
             r.get("treatments", {}).get("spacing_density"),
             r.get("treatments", {}).get("emphasis_weight"))
            for r in runs if r.get("variant")
        ]
        emphasis_words = [
            (r.get("content") or {}).get("heading_emphasis")
            for r in runs if (r.get("content") or {}).get("heading_emphasis")
        ]

        majority_variant, majority_count = v_counter.most_common(1)[0]
        if majority_count == len(runs):
            verdict = f"CONVERGENT — all {len(runs)} runs picked {majority_variant!r}"
        elif majority_count >= len(runs) - 1:
            verdict = (
                f"MOSTLY CONVERGENT — {majority_count}/{len(runs)} picked "
                f"{majority_variant!r}; outlier(s) exist"
            )
        else:
            verdict = (
                f"DIVERGENT — variants split: "
                f"{dict(v_counter)}"
            )

        print(f"### {name}")
        print(f"  verdict: {verdict}")
        print(f"  variant counts:        {dict(v_counter)}")
        print(f"  treatment fingerprints: {treatments_keys}")
        print(f"  emphasis words:        {emphasis_words}")
        print("")
        for r in runs:
            label = r.pop("_label", "?")
            if r.get("_error"):
                print(f"    {label}: ERROR {r['_error']}")
                continue
            print(f"    {label}: {_summarize_run(r)}")
            reasoning = r.get("reasoning") or ""
            # Trim to ~200 chars so report stays readable.
            if reasoning and reasoning != "(captured at Phase 3 — see CHECKPOINT 3)":
                trimmed = reasoning.strip().replace("\n", " ")[:240]
                print(f"      reasoning: {trimmed}{'...' if len(reasoning) > 240 else ''}")
        print("", flush=True)

    print("=== End of report ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
