# scripts/design_acceptance.py
# ─────────────────────────────────────────────────────────────────────
# A5 (2026-07-18) — THE KMJ DESIGN ACCEPTANCE HARNESS.
#
# Codifies the acceptance test from the Kimi K3 Design Integration spec
# §7, which until now existed only as dated manual runs cited in code
# comments. One fixed brief (the KMJ fixture) goes through the full live
# pipeline THREE times:
#
#   1. anthropic   — SITE_BUILDER_PROVIDER unset/anthropic (the default)
#   2. moonshot    — SITE_BUILDER_PROVIDER=moonshot (Kimi K3 composes)
#   3. fallback    — moonshot selected but its key is poisoned, so every
#                    creative stage fails open to the Claude ladder —
#                    proving the Symmetry Rule (a mid-build fallback must
#                    NOT produce a Frankenstein build: prompt content is
#                    provider-neutral, so the fallback build grades within
#                    1 point of the Kimi build on every rubric line).
#
# Pass criteria (spec §7, both providers AND the fallback run):
#   - quality gate green AND zero design-invariant findings
#   - vision grader: first-viewport impact >= 8, template smell <= 2,
#     broken = n   (deliberately stricter than the ship gate)
#   - inventions >= 3, none restating the brief (count from site_config)
#   - a composed nav renders (proxy: <nav in the document)
#   - provider parity: |kimi - claude| <= 1 on EVERY vision rubric line,
#     and |fallback - kimi| <= 1 (the Symmetry Rule check)
#
# What stays manual (the script prints reminders): "no invented proof"
# (D10) and the side-by-side against the hand-built KMJ reference
# ("different, not lesser") are judgment calls no script settles.
#
# Usage (from the repo root, env loaded: SUPABASE_*, ANTHROPIC_API_KEY,
# MOONSHOT_API_KEY for the kimi leg, playwright installed for grades):
#   python scripts/design_acceptance.py --business-id <fixture-business-id>
#
# The fixture business is a DEDICATED row (e.g. "KMJ Acceptance Fixture")
# whose brand kit / offerings / testimonials stay stable — the harness
# re-arms its interview answers (design_prefs) on every run, but the
# business data underneath must not drift or scores aren't comparable.
# Each run OVERWRITES the fixture's live page; never point this at a
# real practitioner's business.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

# Repo root on sys.path when invoked as a file.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# Local runs: load the repo .env (deploy targets inject env themselves).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_REPO_ROOT, ".env"))
except ImportError:
    pass

logger = logging.getLogger("design_acceptance")

# The fixed interview answers — the "original KMJ brief" in interview-v2
# shape (sanitize_design_prefs' allowlist). Rich on purpose: thin briefs
# test the fallback ladder, not design instinct.
FIXTURE_PREFS: Dict[str, Any] = {
    "feel_words": ["crafted", "quiet confidence", "editorial", "premium"],
    "boldness": 2,
    "structure": "one_page",
    "type_personality": "editorial",
    "colors": {"love": ["antique gold", "charcoal"], "avoid": ["purple"],
               "use_brand": True},
    "imagery_priority": "build_now",
    "wants_gallery": True,
    "offer": ("KMJ Creative Solutions designs brand identities, websites, "
              "and print pieces for small businesses that want to look "
              "like they paid an agency — without paying one."),
    "story": {
        "origin": ("Started at a kitchen table after one too many "
                   "'template-looking' websites shipped for friends who "
                   "deserved better."),
        "craft": ("Every piece is hand-composed: real type systems, real "
                  "grids, print-shop discipline applied to the web."),
        "proof": ("Repeat clients across three states; most work arrives "
                  "by referral."),
        "voice": ("Plain-spoken, a little wry, allergic to buzzwords."),
        "atmosphere": ("A print studio after hours — ink, paper, brass "
                       "details, low light."),
    },
    "proof_stats": [
        {"label": "identities shipped", "value": "40+"},
        {"label": "years in practice", "value": "6"},
    ],
    "process_steps": [
        {"title": "Listen", "blurb": "One long conversation about the work and who it's for."},
        {"title": "Sketch", "blurb": "Directions on paper before anything touches a screen."},
        {"title": "Compose", "blurb": "One direction, executed completely — type, color, rhythm."},
        {"title": "Refine", "blurb": "Two disciplined revision rounds, then press-ready files."},
    ],
    "creative": {
        "metaphor": ("A letterpress studio: heavy stock, brass type, ink "
                     "you can almost smell"),
        "surprise": "Print-grade craft on a screen",
        "remember": "This was made by a person, not a template",
        "loud_where": "hero",
        "tension": {"pole_a": "heritage print craft", "pole_b": "modern web",
                    "lean": 3},
    },
    "avoid": "gradients, stock handshakes, purple",
    "notes": "The reference client for design quality — make it feel hand-set.",
}

_RUBRIC_LINES = ("first_viewport_impact", "balance", "motif_visibility",
                 "rhythm", "template_smell")


# ─── Build runner ─────────────────────────────────────────────────────

def _site_config(business_id: str) -> Dict[str, Any]:
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=site_config&limit=1") or []
    return (rows[0].get("site_config") or {}) if rows else {}


def run_build(business_id: str, mode: str) -> Dict[str, Any]:
    """One full compose under the given provider mode; returns the
    compose result + the persisted site_config telemetry."""
    assert mode in ("anthropic", "moonshot", "fallback")
    # Provider env is process-global — set it per run, restore nothing
    # (the script owns the process).
    if mode == "anthropic":
        os.environ.pop("SITE_BUILDER_PROVIDER", None)
    else:
        os.environ["SITE_BUILDER_PROVIDER"] = "moonshot"
    poisoned_key: Optional[str] = None
    if mode == "fallback":
        poisoned_key = os.environ.get("MOONSHOT_API_KEY")
        os.environ["MOONSHOT_API_KEY"] = "sk-poisoned-forced-fallback"

    import site_composer
    try:
        result = site_composer.compose_site(
            business_id, use_llm=True, design_prefs=dict(FIXTURE_PREFS))
    finally:
        if poisoned_key is not None:
            os.environ["MOONSHOT_API_KEY"] = poisoned_key

    cfg = _site_config(business_id)
    verdict = result.get("vision_verdict") or cfg.get("vision_verdict") or {}
    invariants = ((result.get("quality_report") or {}).get("design_invariants")
                  or (cfg.get("quality_report") or {}).get("design_invariants")
                  or [])
    return {
        "mode": mode,
        "dro_status": result.get("dro_status"),
        "composition_source": result.get("composition_source"),
        "gate_passed": bool((result.get("quality_report") or {}).get("passed")),
        "invariant_findings": invariants,
        "verdict": verdict,
        "inventions": cfg.get("invention_count"),
        "html": cfg.get("generated_html") or "",
        "model_fallbacks": cfg.get("model_fallbacks") or [],
    }


# ─── Checks ───────────────────────────────────────────────────────────

def check_run(run: Dict[str, Any]) -> List[str]:
    """The §7 pass criteria for ONE run. Returns failure strings."""
    fails: List[str] = []
    v = run["verdict"]
    if not v:
        fails.append("no vision verdict (grader unavailable?)")
    else:
        if int(v.get("first_viewport_impact") or 0) < 8:
            fails.append(f"first-viewport impact {v.get('first_viewport_impact')} < 8")
        if int(v.get("template_smell") or 10) > 2:
            fails.append(f"template smell {v.get('template_smell')} > 2")
        if v.get("broken") == "y":
            fails.append(f"broken section: {v.get('broken_where') or 'unspecified'}")
    if not run["gate_passed"]:
        fails.append("quality gate not green")
    if run["invariant_findings"]:
        fails.append("design invariants: " + "; ".join(
            f"{f.get('rule_id')}: {str(f.get('evidence'))[:80]}"
            for f in run["invariant_findings"]))
    inv = run["inventions"]
    if not isinstance(inv, int) or inv < 3:
        fails.append(f"inventions {inv} < 3")
    if "<nav" not in (run["html"] or ""):
        fails.append("no composed <nav> in the document")
    return fails


def check_parity(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    """Symmetry Rule: per-rubric-line scores within 1 point."""
    fails: List[str] = []
    va, vb = a["verdict"] or {}, b["verdict"] or {}
    if not va or not vb:
        return ["parity skipped — a run has no verdict"]
    for line in _RUBRIC_LINES:
        try:
            diff = abs(int(va.get(line)) - int(vb.get(line)))
        except Exception:
            fails.append(f"parity: ungradeable line {line}")
            continue
        if diff > 1:
            fails.append(f"parity: {line} differs by {diff} "
                         f"({va.get(line)} vs {vb.get(line)})")
    return fails


# ─── Main ─────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="KMJ design acceptance harness")
    ap.add_argument("--business-id", required=True,
                    help="the DEDICATED fixture business id (its live page "
                         "is overwritten on every run)")
    ap.add_argument("--modes", default="anthropic,moonshot,fallback",
                    help="comma list subset of anthropic,moonshot,fallback")
    ap.add_argument("--json", dest="json_out", default="",
                    help="optional path to write the raw report JSON")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    runs: List[Dict[str, Any]] = []
    overall_fails: List[str] = []

    for mode in modes:
        print(f"\n=== BUILD: {mode} ===", flush=True)
        try:
            run = run_build(args.business_id, mode)
        except Exception as e:
            print(f"  BUILD RAISED: {type(e).__name__}: {e}")
            overall_fails.append(f"{mode}: build raised {type(e).__name__}: {e}")
            continue
        runs.append(run)
        v = run["verdict"] or {}
        print(f"  dro_status={run['dro_status']} source={run['composition_source']}")
        print(f"  verdict: impact={v.get('first_viewport_impact')} "
              f"balance={v.get('balance')} motif={v.get('motif_visibility')} "
              f"rhythm={v.get('rhythm')} smell={v.get('template_smell')} "
              f"broken={v.get('broken')} judge={v.get('judge_provider')}")
        print(f"  inventions={run['inventions']} "
              f"invariants={len(run['invariant_findings'])} "
              f"gate={'green' if run['gate_passed'] else 'RED'}")
        if run["model_fallbacks"]:
            print(f"  model fallbacks: {len(run['model_fallbacks'])} "
                  f"(expected on the fallback leg)")
        for f in check_run(run):
            overall_fails.append(f"{mode}: {f}")
            print(f"  FAIL: {f}")

    by_mode = {r["mode"]: r for r in runs}
    for a, b in (("anthropic", "moonshot"), ("fallback", "moonshot")):
        if a in by_mode and b in by_mode:
            for f in check_parity(by_mode[a], by_mode[b]):
                overall_fails.append(f"parity {a}~{b}: {f}")
                print(f"  FAIL parity {a}~{b}: {f}")

    print("\n=== MANUAL CHECKS (no script settles these) ===")
    print("  - D10: read the page — no invented clients/stats/testimonials.")
    print("  - Side-by-side with the hand-built KMJ reference: different, not lesser.")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"runs": [{k: v for k, v in r.items() if k != "html"}
                                for r in runs],
                       "failures": overall_fails}, fh, indent=2, default=str)
        print(f"\nraw report: {args.json_out}")

    if overall_fails:
        print(f"\nACCEPTANCE: FAIL ({len(overall_fails)} failure(s))")
        return 1
    print("\nACCEPTANCE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
