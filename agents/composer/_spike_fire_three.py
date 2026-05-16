"""Spike-only test harness: fire compose_cathedral_hero against three real
business IDs and print full composition JSONs verbatim.

Phase 3 CHECKPOINT 3 verification artifact generator. NOT for production.
Run via:
  railway run python -m agents.composer._spike_fire_three
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


def main() -> int:
    print("=== Phase 3 spike: firing 3 Composer calls ===")
    print(f"Model: claude-sonnet-4-5-20250929, ~$0.05/call forecast\n", flush=True)

    results = []
    for name, bid in BUSINESSES:
        print(f"--- {name} ({bid}) ---", flush=True)
        try:
            comp = compose_cathedral_hero(bid)
            results.append((name, bid, comp))
            print(json.dumps(comp, indent=2), flush=True)
        except Exception as exc:
            print(f"ERROR composing for {name}: {exc}", flush=True)
            traceback.print_exc()
            results.append((name, bid, {"_error": str(exc)}))
        print("", flush=True)

    print("=== All 3 compositions captured ===", flush=True)
    for name, _, comp in results:
        variant = comp.get("variant_id", "?")
        gap = "GAP" if "gap" in (comp.get("reasoning", "") or "").lower() else "fit"
        print(f"  {name}: variant={variant}  [{gap}]", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
