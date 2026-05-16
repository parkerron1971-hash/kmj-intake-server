"""Spike-only Phase 2.6 verification — fires three depth-aware Composer
calls and prints the composition JSON for each, focusing on the 5 new
depth treatment fields.

Run via:
  railway run python -m agents.composer._spike_phase26_verify
"""
from __future__ import annotations

import json
import sys
import traceback

from agents.composer.cathedral_hero_composer import compose_cathedral_hero

BUSINESSES = [
    ("KMJ Creative Solutions", "12773842-3cc6-41a7-9094-b8606e3f7549"),
    ("Director Loop Test",     "c8b7e157-903b-40c9-b5f2-700f196fe35b"),
    ("RoyalTeez Designz",      "a8d1abb7-b8c5-4ee0-8d46-84e69efc220d"),
]


def _depth_summary(treatments: dict) -> str:
    return (
        f"bg={treatments.get('background')} | "
        f"color_depth={treatments.get('color_depth')} | "
        f"orn={treatments.get('ornament')} | "
        f"typo={treatments.get('typography')} | "
        f"img={treatments.get('image_treatment')}"
    )


def main() -> int:
    print("=== Phase 2.6 verification ===")
    print("Firing 3 depth-aware Composer calls. ~$0.15-0.30.\n", flush=True)

    for name, bid in BUSINESSES:
        print(f"--- {name} ({bid}) ---", flush=True)
        try:
            comp = compose_cathedral_hero(bid)
        except Exception as exc:
            print(f"  ERROR: {exc}", flush=True)
            traceback.print_exc()
            continue
        t = comp.get("treatments") or {}
        # Surface the full JSON for the report artifact.
        print(json.dumps(comp, indent=2), flush=True)
        print(f"  DEPTH: {_depth_summary(t)}\n", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
