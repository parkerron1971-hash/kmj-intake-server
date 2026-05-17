"""Spike-only Phase E verification.

Two test passes:

  TEST 1 — Cathedral backward compatibility
    Fire compose_hero(business_id, module_id='cathedral') for the 3
    Phase 3 spike businesses (KMJ, Director Loop, RoyalTee). Compare
    the variant + structural treatment fingerprint against Pass 4.0f
    Phase 3 captures. Same Cathedral composer behavior should produce
    matching variant + matching structural-treatment fingerprint
    (depth-treatment values may vary since they're Phase 2.6 additions
    and Composer was tuning at higher temperature back then).

  TEST 2 — Phase E end-to-end pipeline
    Fire compose_and_render_hero(business_id) for the same 3
    businesses. Verify:
      - Module Router runs first (returns routing_decision)
      - Module-specific Composer composes within that module
      - Module-specific render produces standalone HTML
      - Final dict has {business_id, module_id, routing_decision,
        composition, html} populated

    Expected routing per Phase D convergence test:
      KMJ -> cathedral, Director Loop -> cathedral, RoyalTee -> studio_brut

Cost: ~$0.40 (3 router + 3 composer for TEST 2 = 6 Sonnet calls;
TEST 1 reuses Cathedral compositions = 3 more calls).

Run via:
  railway run python -m agents.composer._spike_phase_e_verify
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Dict, List

# Cathedral Phase 3 captures from spike_phase3_compositions.txt.
# Used by TEST 1 to verify backward compat — variant + structural
# treatment fingerprint should match (depth treatments are Phase 2.6
# additions and may vary).
PHASE_3_FINGERPRINTS = {
    "12773842-3cc6-41a7-9094-b8606e3f7549": {
        "name": "KMJ Creative Solutions",
        "variant": "asymmetric_right",
        "structural": ("signal_dominant", "generous", "heading_dominant"),
        "heading_emphasis": "breakthrough",
    },
    "c8b7e157-903b-40c9-b5f2-700f196fe35b": {
        "name": "Director Loop Test",
        "variant": "annotated_hero",
        "structural": ("signal_dominant", "standard", "balanced"),
        "heading_emphasis": "loop",
    },
    "a8d1abb7-b8c5-4ee0-8d46-84e69efc220d": {
        "name": "RoyalTeez Designz",
        "variant": "asymmetric_right",
        "structural": ("signal_dominant", "standard", "heading_dominant"),
        "heading_emphasis": "throne",
    },
}

BUSINESSES = list(PHASE_3_FINGERPRINTS.keys())


def _structural_fingerprint(comp: Dict[str, Any]) -> tuple:
    t = comp.get("treatments") or {}
    return (
        t.get("color_emphasis"),
        t.get("spacing_density"),
        t.get("emphasis_weight"),
    )


def _depth_fingerprint(comp: Dict[str, Any]) -> str:
    t = comp.get("treatments") or {}
    return (
        f"bg={t.get('background')} | "
        f"color={t.get('color_depth')} | "
        f"orn={t.get('ornament')} | "
        f"typo={t.get('typography')} | "
        f"img={t.get('image_treatment')}"
    )


def test_cathedral_backward_compat() -> int:
    """TEST 1 — fire Cathedral composer through the new generalized
    code path and compare against Phase 3 captures."""
    print("=== TEST 1: Cathedral backward compatibility ===")
    print(f"Firing compose_hero(business_id, module_id='cathedral') "
          f"for {len(BUSINESSES)} Phase 3 businesses.\n", flush=True)

    from agents.composer.hero_composer import compose_hero

    matched = 0
    for bid in BUSINESSES:
        exp = PHASE_3_FINGERPRINTS[bid]
        print(f"--- {exp['name']} ({bid}) ---", flush=True)
        try:
            comp = compose_hero(bid, module_id="cathedral")
        except Exception as exc:
            print(f"  ERROR: {exc}", flush=True)
            traceback.print_exc()
            continue

        variant = comp.get("variant")
        structural = _structural_fingerprint(comp)
        depth = _depth_fingerprint(comp)
        emphasis_word = (comp.get("content") or {}).get("heading_emphasis")

        variant_match = variant == exp["variant"]
        structural_match = structural == exp["structural"]
        emphasis_match = emphasis_word == exp["heading_emphasis"]
        overall = variant_match and structural_match

        v_note = "(matches Phase 3)" if variant_match else f"(was {exp['variant']!r} in Phase 3)"
        s_note = "(matches Phase 3)" if structural_match else f"(was {exp['structural']} in Phase 3)"
        e_note = "(matches Phase 3)" if emphasis_match else f"(was {exp['heading_emphasis']!r})"
        print(f"  variant:          {variant!r}  {v_note}")
        print(f"  structural:       {structural}  {s_note}")
        print(f"  depth (Phase 2.6+): {depth}")
        print(f"  heading_emphasis: {emphasis_word!r}  {e_note}")
        print(f"  module_id surfaced: "
              f"{(comp.get('_composer_metadata') or {}).get('module_id')!r}")
        if overall:
            matched += 1
            print(f"  -> backward compat OK\n", flush=True)
        else:
            print(f"  -> backward compat MISMATCH (variant or structural drifted)\n", flush=True)

    print(f"=== TEST 1 verdict: {matched}/{len(BUSINESSES)} Cathedral "
          f"businesses produced matching variant + structural fingerprint ===")
    return matched


def test_end_to_end_pipeline() -> List[Dict[str, Any]]:
    """TEST 2 — fire the full Module Router -> Composer -> Render
    pipeline for the 3 spike businesses. Capture per-business
    results for the CHECKPOINT E report."""
    print("\n=== TEST 2: Phase E end-to-end pipeline ===")
    print(f"Firing compose_and_render_hero(business_id) for "
          f"{len(BUSINESSES)} businesses (3 router calls + 3 composer "
          f"calls = 6 Sonnet calls ~$0.20).\n", flush=True)

    from agents.composer.render_pipeline import compose_and_render_hero

    results: List[Dict[str, Any]] = []
    for bid in BUSINESSES:
        name = PHASE_3_FINGERPRINTS[bid]["name"]
        print(f"--- {name} ({bid}) ---", flush=True)
        try:
            envelope = compose_and_render_hero(bid)
            results.append(envelope)
            routing = envelope.get("routing_decision") or {}
            comp = envelope.get("composition") or {}
            mod = envelope.get("module_id")
            html_len = len(envelope.get("html") or "")
            print(
                f"  ROUTER:   module={routing.get('module_id')!r}  "
                f"conf={routing.get('confidence'):.2f}  "
                f"alt={routing.get('alternative_module')!r}"
            )
            print(
                f"  COMPOSER: variant={comp.get('variant')!r}  "
                f"depth={_depth_fingerprint(comp)}"
            )
            content = comp.get("content") or {}
            print(
                f"  CONTENT:  heading={content.get('heading')!r}  "
                f"emphasis={content.get('heading_emphasis')!r}"
            )
            print(f"  RENDER:   html_length={html_len} bytes  "
                  f"module={mod!r}\n", flush=True)
        except Exception as exc:
            print(f"  ERROR: {exc}", flush=True)
            traceback.print_exc()
            results.append({"business_id": bid, "_error": str(exc)})

    return results


def main() -> int:
    t1_matched = test_cathedral_backward_compat()
    t2_results = test_end_to_end_pipeline()

    print("=== PHASE E VERIFICATION SUMMARY ===")
    print(f"TEST 1 (Cathedral backward compat): "
          f"{t1_matched}/{len(BUSINESSES)} variant+structural matches")
    print(f"TEST 2 (end-to-end pipeline):       "
          f"{sum(1 for r in t2_results if r.get('html'))}/{len(BUSINESSES)} "
          f"full pipeline completions")

    # Routing accuracy on TEST 2
    print("\n=== Routing accuracy ===")
    expected_routing = {
        "12773842-3cc6-41a7-9094-b8606e3f7549": "cathedral",
        "c8b7e157-903b-40c9-b5f2-700f196fe35b": "cathedral",
        "a8d1abb7-b8c5-4ee0-8d46-84e69efc220d": "studio_brut",
    }
    routing_correct = 0
    for r in t2_results:
        bid = r.get("business_id")
        if not bid:
            continue
        actual = r.get("module_id")
        expected = expected_routing.get(bid)
        name = PHASE_3_FINGERPRINTS.get(bid, {}).get("name", bid[:8])
        match = actual == expected
        print(f"  {name:30s} -> actual={actual!r:14} "
              f"expected={expected!r:14} {'OK' if match else 'MISMATCH'}")
        if match:
            routing_correct += 1
    print(f"  -> {routing_correct}/{len(t2_results)} routings match expected")

    return 0


if __name__ == "__main__":
    sys.exit(main())
