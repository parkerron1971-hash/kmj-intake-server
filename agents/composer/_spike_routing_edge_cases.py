"""Spike-only Phase D edge-case routing stress test.

Constructs 5 SYNTHETIC business contexts representing genuinely
ambiguous archetype combinations and fires the router against them
via _route_from_context (bypassing the Supabase fetch). Verifies the
router handles ambiguity gracefully:

  - Either returns confidence >= 0.7 with clear primary choice
  - OR returns confidence < 0.7 with alternative_module populated
  - Never silently picks one module while obviously fitting another

Five edge cases (per Pass 4.0g Phase D scope):

  1. Creative agency that does pastoral consulting
     (creative + pastoral — likely Cathedral; archetype mixed)
  2. Urban photographer who shoots law firm headshots
     (Studio Brut for the photographer, but the work is Cathedral-adjacent)
  3. Design studio that builds technical methodologies
     (creative AND consultancy — could go either way)
  4. Streetwear brand with 'luxury heritage' positioning
     (Studio Brut for streetwear, but luxury hints Cathedral)
  5. Pastor who also runs a creative agency
     (pastor is Cathedral, agency might lean either way; depends on framing)

Run via:
  railway run python -m agents.composer._spike_routing_edge_cases
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Dict, List

from agents.composer.module_router import _route_from_context


# Five synthetic business contexts. Each is what fetch_routing_context
# would return for a hypothetical business with the described
# archetypal tension.
EDGE_CASES: List[Dict[str, Any]] = [
    {
        "business_id": "edge_01_pastoral_agency",
        "business_name": "Wellspring Creative",
        "business_description": (
            "A creative agency rooted in pastoral counseling and faith-led "
            "leadership. We help church communities and ministry organizations "
            "find their voice through thoughtful brand storytelling, sermon "
            "design, and community publishing. Editorial restraint with "
            "spiritual depth."
        ),
        "inferred_archetype": "creative_agency_pastoral",
        "inferred_vibe": "contemplative, ministry-led, editorial",
        "brand_metaphor": "the cathedral and the studio in one practice",
        "tone_words": ["pastoral", "considered", "spiritual", "editorial"],
        "brand_kit": {
            "primary": "#1A2A45", "secondary": "#3A2820",
            "accent": "#C8A872", "background": "#F6F1E7", "text": "#0F172A",
        },
    },
    {
        "business_id": "edge_02_urban_photog_law",
        "business_name": "Halsted & Vine",
        "business_description": (
            "An urban photographer based in Chicago's West Loop, specializing "
            "in editorial portraits, street fashion, and — increasingly — "
            "corporate headshots for law firms, financial advisors, and "
            "executive practices that want their leadership photography to "
            "feel less like LinkedIn and more like a magazine cover."
        ),
        "inferred_archetype": "urban_photographer_dual",
        "inferred_vibe": "editorial fashion meets corporate gravity",
        "brand_metaphor": "the streetlight and the boardroom",
        "tone_words": ["editorial", "urban", "considered", "graphic"],
        "brand_kit": {
            "primary": "#0A0A0A", "secondary": "#3D3D3D",
            "accent": "#E63946", "background": "#F4F4F0", "text": "#0A0A0A",
        },
    },
    {
        "business_id": "edge_03_design_methodology",
        "business_name": "Forge & Frame",
        "business_description": (
            "A design studio that builds structured methodologies for "
            "brand systems, design ops, and creative team scaling. We are "
            "designers, but our deliverable is process — frameworks, "
            "playbooks, training programs. Half studio, half consultancy."
        ),
        "inferred_archetype": "design_studio_methodology",
        "inferred_vibe": "structured creativity, frameworks-first",
        "brand_metaphor": "the workshop and the field manual",
        "tone_words": ["structured", "creative", "methodical", "rigorous"],
        "brand_kit": {
            "primary": "#1E1E1E", "secondary": "#2A2A2A",
            "accent": "#FF6B35", "background": "#F2F2F2", "text": "#1E1E1E",
        },
    },
    {
        "business_id": "edge_04_streetwear_luxury",
        "business_name": "Maison Concrete",
        "business_description": (
            "A streetwear label with luxury heritage positioning. We hand-"
            "finish every garment in a small Brooklyn atelier, working with "
            "fabrics sourced from Italian heritage mills. Streetwear "
            "silhouettes; couture construction; archival craftsmanship "
            "language."
        ),
        "inferred_archetype": "streetwear_luxury_heritage",
        "inferred_vibe": "atelier-meets-streetwear, archival luxury",
        "brand_metaphor": "the workshop floor and the heritage atelier",
        "tone_words": ["streetwear", "heritage", "crafted", "considered"],
        "brand_kit": {
            "primary": "#1F1F1F", "secondary": "#2D2820",
            "accent": "#B8956A", "background": "#EDE8DD", "text": "#1F1F1F",
        },
    },
    {
        "business_id": "edge_05_pastor_creative",
        "business_name": "Marcus Vale Creative",
        "business_description": (
            "Pastor Marcus Vale leads a small urban congregation and runs a "
            "creative agency on the side, helping other independent ministries "
            "find a voice that is direct, real, and unafraid of personality. "
            "Sermons that sound like spoken word. Brand work that sounds "
            "like the pastor talking to you across a kitchen table."
        ),
        "inferred_archetype": "pastor_creative_agency",
        "inferred_vibe": "direct address, real-talk ministry, personality-led",
        "brand_metaphor": "the kitchen table and the pulpit",
        "tone_words": ["direct", "personable", "real", "ministry"],
        "brand_kit": {
            "primary": "#2C1810", "secondary": "#1A1A1A",
            "accent": "#D9534F", "background": "#FAF6F0", "text": "#2C1810",
        },
    },
]


def main() -> int:
    print("=== Phase D routing edge-case stress test ===")
    print(f"Firing {len(EDGE_CASES)} synthetic-fixture routing calls "
          f"(~${0.01 * len(EDGE_CASES):.2f}).\n", flush=True)

    results: List[Dict[str, Any]] = []
    for ctx in EDGE_CASES:
        eid = ctx["business_id"]
        name = ctx["business_name"]
        archetype = ctx["inferred_archetype"]
        print(f"--- {eid}: {name} ({archetype}) ---", flush=True)
        try:
            decision = _route_from_context(ctx)
            results.append({"context": ctx, "decision": decision})
            mod = decision.get("module_id")
            conf = decision.get("confidence")
            alt = decision.get("alternative_module")
            print(
                f"  module={mod:>12} | conf={conf:.2f} | alt={alt}",
                flush=True,
            )
            reasoning = (decision.get("reasoning") or "").strip().replace("\n", " ")
            print(f"    reasoning: {reasoning[:400]}"
                  f"{'...' if len(reasoning) > 400 else ''}", flush=True)

            # Assess: did the router gracefully handle ambiguity?
            # Pass = either high confidence (>=0.7, no alt required)
            #        OR moderate confidence (<0.7) with alt populated
            # Fail = low confidence with no alt (or impossible state)
            if conf is None:
                handling = "FAIL (no confidence returned)"
            elif conf >= 0.7:
                handling = (
                    f"HIGH-CONFIDENCE PICK ({mod} @ {conf:.2f}) — "
                    f"router committed despite mixed archetype"
                )
            elif alt and alt != mod:
                handling = (
                    f"GRACEFUL AMBIGUITY ({mod} primary @ {conf:.2f}, "
                    f"alt={alt}) — router surfaced second-choice"
                )
            else:
                handling = (
                    f"WEAK AMBIGUITY ({mod} @ {conf:.2f}, alt missing) — "
                    f"router should have populated alternative_module"
                )
            print(f"  handling: {handling}\n", flush=True)
        except Exception as exc:
            print(f"  ERROR: {exc}", flush=True)
            traceback.print_exc()
            results.append({"context": ctx, "_error": str(exc)})

    print("=== EDGE-CASE SUMMARY ===")
    for r in results:
        if r.get("_error"):
            print(f"  {r['context']['business_id']:36s} -> ERROR")
            continue
        ctx = r["context"]
        d = r["decision"]
        print(
            f"  {ctx['business_id']:36s} -> "
            f"{d.get('module_id'):>12} @ {d.get('confidence'):.2f} "
            f"(alt: {d.get('alternative_module') or 'none'})"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
