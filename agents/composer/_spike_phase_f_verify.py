"""Pass 4.0g Phase F — verification harness.

Fires the full multi-module pipeline (Module Router -> module-specific
Composer -> module-specific render) for all three spike businesses via
the new comparison page renderer, prints each business's pipeline
result, dumps the rendered HTML to a temp file, then verifies the
in-memory cache short-circuits the second render.

Run via:
  railway run python -m agents.composer._spike_phase_f_verify

Cost: ~$0.45 (9 Sonnet calls: 3 router + 3 composer + 3 force-Cathedral
composer). Same cost as a cold visit to the comparison page in a
browser.
"""
from __future__ import annotations

import os
import sys
import time


def main() -> int:
    from agents.composer.multi_module_comparison_page import (
        SPIKE_BUSINESSES,
        _CACHE,
        _gather_all,
        invalidate_cache,
        render_multi_module_comparison_html,
    )

    print("=== PASS 4.0g PHASE F — multi-module comparison verification ===")
    print()
    print(
        f"env-ok: SUPABASE_URL={bool(os.environ.get('SUPABASE_URL'))}, "
        f"ANTHROPIC_API_KEY={bool(os.environ.get('ANTHROPIC_API_KEY'))}"
    )
    print()

    invalidate_cache()

    t0 = time.time()
    entries = _gather_all(include_force_cathedral=True)
    cold_secs = time.time() - t0
    print(f"COLD pipeline run: {cold_secs:.1f}s for {len(entries)} businesses")
    print()

    for e in entries:
        print("--- " + e["name"] + " ---")
        print(f"  business_id: {e['business_id']}")
        if e.get("pipeline_error"):
            print(f"  PIPELINE ERROR: {e['pipeline_error']}")
            continue
        r = e.get("routing") or {}
        c = e.get("composition") or {}
        print(
            f"  ROUTER   : module={r.get('module_id')!r}  "
            f"conf={r.get('confidence')}  alt={r.get('alternative_module')!r}"
        )
        print(f"             reasoning: {(r.get('reasoning') or '')[:240]}")
        print(f"  COMPOSER : variant={c.get('variant')!r}")
        tr = c.get("treatments") or {}
        print(
            "             structural=("
            f"{tr.get('color_emphasis')},{tr.get('spacing_density')},"
            f"{tr.get('emphasis_weight')})"
        )
        print(
            "             depth=("
            f"bg:{tr.get('background')}, color:{tr.get('color_depth')}, "
            f"orn:{tr.get('ornament')}, typo:{tr.get('typography')}, "
            f"img:{tr.get('image_treatment')})"
        )
        cont = c.get("content") or {}
        print(
            f"             heading={cont.get('heading')!r}  "
            f"emphasis={cont.get('heading_emphasis')!r}"
        )
        print(f"             cta={cont.get('cta_primary')!r}")
        print(
            f"  RENDER   : module={e.get('module_id')!r}  "
            f"html_bytes={len(e.get('html') or '')}"
        )
        fc = e.get("force_cathedral_composition") or {}
        fh = e.get("force_cathedral_html") or ""
        fe = e.get("force_cathedral_error")
        if fe:
            print(f"  FORCE_CATH ERROR: {fe}")
        else:
            print(f"  FORCE_CATH: variant={fc.get('variant')!r}  html_bytes={len(fh)}")
        print()

    html = render_multi_module_comparison_html(refresh=False, include_force_cathedral=True)
    out_path = os.path.join(os.environ.get("TEMP", "/tmp"), "pass_4_0g_phase_f_verify.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML rendered: {len(html)} bytes  -> {out_path}")

    t0 = time.time()
    _ = render_multi_module_comparison_html(refresh=False, include_force_cathedral=True)
    warm_secs = time.time() - t0
    print(f"WARM render (cache hit): {warm_secs:.2f}s")
    print(f"Cache populated: {len(_CACHE)}/{len(SPIKE_BUSINESSES)} businesses")

    # Verdict — fail nonzero if any business pipeline blew up entirely.
    failed = [e["name"] for e in entries if e.get("pipeline_error")]
    if failed:
        print()
        print(f"FAIL — pipeline error on: {failed}")
        return 1
    print()
    print("PASS — all 3 businesses completed full pipeline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
