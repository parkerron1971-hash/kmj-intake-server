"""Pass 4.0b PART 4 — build-with-loop orchestrator.

End-to-end Director loop that exercises the full Pass 4.0a + 4.0b chain
in one call:

  1. enrichment      — sparse intake → enriched_brief
  2. designer        — Designer Agent (with enriched_brief threaded in)
  3. brief_expander  — Designer recommendation → DesignBrief (conceptName,
                       tagline, blendRatio, philosophy, sections, palette)
  4. builder_v1      — Builder Agent first attempt
  5. critique_v1     — Director critique against Module rubric
  6. (conditional)   — when critique_v1.verdict == "fail" (any HIGH
                       violation), Builder regenerates with the v1
                       punch_list, followed by critique_v2.

Returns a structured audit trail with each step's elapsed time, full
result, and (for builder steps) extracted CTA text — so callers can read
whether the brand_metaphor reframing actually surfaced in the rendered
output. Builder/Critique soft-fails are captured in the audit; only
catastrophic exceptions raise.

Bundle synthesis: this orchestrator does NOT load a real Supabase bundle.
The caller supplies sparse fields (business_name, description, colors,
practitioner_voice, strategy_track_summary). We synthesize a minimal
bundle internally so ad-hoc tests like "Royal Palace" work without
fixture rows in the database.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── Bundle synthesis ─────────────────────────────────────────────────

def _synthesize_bundle(
    business_name: str,
    description: Optional[str],
    practitioner_voice: Optional[str],
    strategy_track_summary: Optional[str],
) -> Dict[str, Any]:
    """Build a minimal bundle dict matching the shape the Designer +
    Brief Expander expect from a real Supabase-backed `get_bundle` call.

    Only fills the keys the downstream agents actually read; everything
    else stays absent so the agents fall through to their own defaults.
    """
    return {
        "business": {
            "name": business_name,
            "tagline": "",
            "elevator_pitch": description or "",
            "type": "service",
            "subtype": "",
        },
        "voice": {
            "brand_voice": practitioner_voice or "",
            "tone_original": practitioner_voice or "",
            "audience": "",
            "tones": [],
            "voice_dos": [],
        },
        "practitioner": {"display_name": ""},
        "practitioner_intelligence": {
            "about_me": "",
            "about_business": description or "",
            "strategy_track": {
                "summary": strategy_track_summary or "",
                "unique_value_proposition": "",
                "target_audience": "",
                "practitioner_background": "",
            },
        },
    }


# ─── CTA extraction ──────────────────────────────────────────────────

# Match <button …>TEXT</button> and <a class="… btn|cta …" …>TEXT</a>.
# Multiline + dotall so inner content with newlines / nested spans is
# captured. Strip nested tags from the inner text afterward.
_BUTTON_RE = re.compile(r"<button\b[^>]*>(.*?)</button>", re.IGNORECASE | re.DOTALL)
# Accept class=value, class="value", or class='value'. The class token
# we care about must contain 'btn' or 'cta' (case-insensitive).
_CTA_LINK_RE = re.compile(
    r'<a\b[^>]*\bclass\s*=\s*["\']?[^"\'>]*(?:btn|cta)[^"\'>]*["\']?[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _extract_first_n_ctas(html: str, n: int = 3) -> List[str]:
    """Return up to N CTA text snippets from rendered HTML. Reads
    <button> elements and <a> elements whose class contains 'btn' or
    'cta'. Strips nested tags + collapses whitespace. Order preserves
    document position (button matches first, then link matches)."""
    if not html:
        return []
    raw_matches: List[str] = []
    raw_matches.extend(_BUTTON_RE.findall(html))
    raw_matches.extend(_CTA_LINK_RE.findall(html))

    cleaned: List[str] = []
    for inner in raw_matches:
        text = _TAG_STRIP_RE.sub(" ", inner)
        text = _WS_RE.sub(" ", text).strip()
        if text:
            cleaned.append(text)
        if len(cleaned) >= n:
            break
    return cleaned[:n]


# ─── Step helpers ────────────────────────────────────────────────────

def _stamp(step: str, t0: float, **payload) -> Dict[str, Any]:
    """Wrap a step result with the standard {step, elapsed_seconds, ...}
    shape used throughout the audit trail."""
    return {
        "step": step,
        "elapsed_seconds": round(time.time() - t0, 3),
        **payload,
    }


def _designer_summary(rec: Optional[Dict]) -> Dict[str, Any]:
    """Pull the Designer's full creative output for the audit trail. The
    user's PART 4 spec calls these out explicitly: strand pair, ratio,
    sub-strand, layout archetype, accent style, rationale, signature
    moment, and the _enrichment_used flag."""
    if not isinstance(rec, dict):
        return {}
    return {
        "strand_a_id": rec.get("strand_a_id"),
        "strand_b_id": rec.get("strand_b_id"),
        "ratio_a": rec.get("ratio_a"),
        "ratio_b": rec.get("ratio_b"),
        "sub_strand_id": rec.get("sub_strand_id"),
        "layout_archetype": rec.get("layout_archetype"),
        "accent_style": rec.get("accent_style"),
        "site_type": rec.get("site_type"),
        "rationale": rec.get("rationale"),
        "signature_moment": rec.get("signature_moment"),
        "pacing_rhythm": rec.get("pacing_rhythm"),
        "voice_proof_quote": rec.get("voice_proof_quote"),
        "cold_start": rec.get("cold_start"),
        "_enrichment_used": rec.get("_enrichment_used"),
        "_enrichment_available": rec.get("_enrichment_available"),
    }


def _brief_summary(brief: Optional[Dict]) -> Dict[str, Any]:
    """Pull the Brief Expander's creative naming + structure for the
    audit. conceptName + tagline are the headline fields the user wants
    visible to evaluate whether brand_metaphor reshaped the creative."""
    if not isinstance(brief, dict):
        return {}
    sections = brief.get("sections") or []
    section_names = [
        s.get("name") for s in sections if isinstance(s, dict) and s.get("name")
    ]
    palette = brief.get("palette") or []
    return {
        "conceptName": brief.get("conceptName"),
        "tagline": brief.get("tagline"),
        "blendRatio": brief.get("blendRatio"),
        "philosophy": brief.get("philosophy"),
        "tensionStatement": brief.get("tensionStatement"),
        "spatialDirection": brief.get("spatialDirection"),
        "copyVoice": brief.get("copyVoice"),
        "mood": brief.get("mood"),
        "section_names": section_names,
        "palette_count": len(palette) if isinstance(palette, list) else 0,
        "validation_warnings": brief.get("_validation_warnings"),
    }


# Per-archetype slot floor (Pass 4.0b.5.1). Mirrors the table in the
# Builder's SLOT TAGS prompt block. Used by _check_slot_coverage to
# raise an audit warning when Builder ships a site below the floor.
ARCHETYPE_SLOT_MINIMUMS: Dict[str, int] = {
    "service_business":   5,
    "coaching_practice":  5,
    "knowledge_brand":    5,
    "course_creator":     5,
    "ministry":           5,
    "community_platform": 5,
    "product_business":   6,
    "ecommerce":          6,
    "creative_agency":    6,
    "consultant":         6,
    "custom":             5,
}


def _check_slot_coverage(
    html: Optional[str],
    enriched_brief: Optional[Dict],
) -> Optional[Dict[str, Any]]:
    """Diagnostic: compare distinct data-slot count in shipping HTML
    against the per-archetype minimum. Returns a warning dict when
    under floor, None when at-or-above. Non-blocking — the audit
    surfaces this so operators can decide to re-run or enrich slots
    via the management UI."""
    import re as _re
    if not html:
        return None
    archetype = (enriched_brief or {}).get("content_archetype") or "custom"
    minimum = ARCHETYPE_SLOT_MINIMUMS.get(archetype, 5)
    found = set(
        _re.findall(
            r'data-slot\s*=\s*["\']?([a-z_0-9]+)',
            html,
            _re.IGNORECASE,
        )
    )
    slots_used = len(found)
    if slots_used >= minimum:
        return None
    return {
        "warning": "slot_coverage_below_archetype_minimum",
        "slots_used": slots_used,
        "minimum_for_archetype": minimum,
        "archetype": archetype,
        "slot_names": sorted(found),
        "advisory": (
            "Builder used fewer slots than recommended for this "
            "archetype. Consider re-running or manual slot enrichment "
            "via the management UI."
        ),
    }


def _critique_summary(critique: Optional[Dict], top_n: int = 5) -> Dict[str, Any]:
    """Extract critique verdict + counts + top-N violations for audit."""
    if not isinstance(critique, dict):
        return {}
    s = critique.get("summary") or {}
    violations = critique.get("violations") or []
    top = []
    for v in violations[:top_n]:
        if not isinstance(v, dict):
            continue
        top.append({
            "rule_id": v.get("rule_id"),
            "severity": v.get("severity"),
            "fix_hint": v.get("fix_hint"),
        })
    return {
        "verdict": s.get("verdict"),
        "total": s.get("total"),
        "high": s.get("high"),
        "medium": s.get("medium"),
        "low": s.get("low"),
        "deterministic_count": s.get("deterministic_count"),
        "llm_judged_count": s.get("llm_judged_count"),
        "rubric_loaded": critique.get("rubric_loaded"),
        "rubric_version": critique.get("rubric_version"),
        "top_violations": top,
    }


# ─── Main orchestrator ───────────────────────────────────────────────

def run_build_loop(
    business_name: str,
    module_id: str,
    description: Optional[str] = None,
    colors: Optional[List[str]] = None,
    practitioner_voice: Optional[str] = None,
    strategy_track_summary: Optional[str] = None,
    vocab_id: str = "sovereign-authority",
    max_attempts: int = 2,
    include_html: bool = True,
    business_id: Optional[str] = None,
    initial_punch_list: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run the full Director build-with-loop pipeline.

    Returns:
      {
        "status": "success" | "fail" | "error",
        "elapsed_total_seconds": float,
        "steps": [ ...audit entries... ],
        "regenerated": bool,
        "final_html": str | None,   # only when include_html=True
        "html_length": int,
        "persistence": dict | None,  # {site_id, preview_url} on persist
      }

    `status` reflects the final critique verdict — "success" when the
    last critique returns verdict=pass, "fail" when it still reports
    HIGH violations after the regenerate cap, "error" only when a step
    raised an unrecoverable exception that prevented a final HTML.

    `business_id` (Pass 4.0b.4): when supplied AND final_html is
    non-empty, the orchestrator writes the HTML to the matching
    business_sites row's site_config.generated_html, mirroring the
    persistence pattern at public_site.py:2710. This surfaces the
    build at /sites/{business_id}/preview without any frontend work.
    Persists regardless of pass/fail verdict (a failing build is still
    useful to inspect). Soft-fails: a persist exception is captured
    in the response payload, never raised.
    """
    start = time.time()
    steps: List[Dict[str, Any]] = []
    final_html: Optional[str] = None

    # ── 1. Enrichment ────────────────────────────────────────────
    t0 = time.time()
    enriched_brief: Optional[Dict] = None
    try:
        from agents.sparse_input_enrichment import enrich_intake
        enriched_brief = enrich_intake(
            business_name=business_name,
            description=description,
            colors=colors,
            practitioner_voice=practitioner_voice,
            strategy_track_summary=strategy_track_summary,
        )
    except Exception as e:
        logger.warning(f"[build-with-loop] enrichment crashed: {type(e).__name__}: {e}")
    steps.append(_stamp(
        "enrichment", t0,
        result=enriched_brief or {},
        error=None if enriched_brief is not None else "enrichment returned None",
    ))

    # ── 2. Designer Agent ────────────────────────────────────────
    bundle = _synthesize_bundle(
        business_name, description, practitioner_voice, strategy_track_summary
    )
    t0 = time.time()
    rec: Optional[Dict] = None
    designer_error: Optional[str] = None
    try:
        from studio_designer_agent import generate_design_recommendation
        rec, designer_error = generate_design_recommendation(
            bundle, vocab_id, [], cold_start=False, enriched_brief=enriched_brief,
        )
    except Exception as e:
        designer_error = f"{type(e).__name__}: {e}"
        logger.warning(f"[build-with-loop] designer crashed: {designer_error}")
    steps.append(_stamp(
        "designer", t0,
        result=_designer_summary(rec),
        error=designer_error,
    ))
    if not rec:
        return {
            "status": "error",
            "elapsed_total_seconds": round(time.time() - start, 3),
            "steps": steps,
            "regenerated": False,
            "final_html": None,
            "html_length": 0,
            "error": f"Designer Agent failed: {designer_error or 'unknown'}",
        }

    # ── 3. Brief Expander ────────────────────────────────────────
    t0 = time.time()
    brief: Optional[Dict] = None
    brief_error: Optional[str] = None
    try:
        from studio_brief_expander import expand_design_brief
        brief, brief_error = expand_design_brief(bundle, rec, [])
    except Exception as e:
        brief_error = f"{type(e).__name__}: {e}"
        logger.warning(f"[build-with-loop] brief expander crashed: {brief_error}")
    steps.append(_stamp(
        "brief_expander", t0,
        result=_brief_summary(brief),
        error=brief_error,
    ))
    if not brief:
        return {
            "status": "error",
            "elapsed_total_seconds": round(time.time() - start, 3),
            "steps": steps,
            "regenerated": False,
            "final_html": None,
            "html_length": 0,
            "error": f"Brief Expander failed: {brief_error or 'unknown'}",
        }

    # ── 4. Builder v1 ────────────────────────────────────────────
    from studio_builder_agent import build_html
    from agents.director_agent.critique import critique_site
    # Pass 4.0b.4: load the rubric ONCE and pass it into Builder v2 so
    # the regenerate prompt gets the MAINTAIN — DO NOT REGRESS block.
    # Builder v1 (no punch list) doesn't need the rubric — first attempts
    # use the legacy creative-director prompt.
    rubric_for_builder: Optional[Dict] = None
    try:
        from agents.design_intelligence.rubrics import load_rubric
        rubric_for_builder = load_rubric(module_id)
    except Exception as e:
        logger.warning(f"[build-with-loop] rubric load for builder failed: {e}")

    t0 = time.time()
    html_v1: Optional[str] = None
    builder_v1_error: Optional[str] = None
    builder_v1_warnings: List[str] = []
    try:
        # Pass 4.0c: when called from /director/refine, initial_punch_list
        # carries the user's enriched feedback moves. Builder v1 sees
        # them as the active punch list (alongside the Cinematic Authority
        # MAINTAIN block via rubric=rubric_for_builder).
        html_v1, builder_v1_error, errs = build_html(
            brief, bundle, None, [], [],
            punch_list=initial_punch_list,
            rubric=rubric_for_builder if initial_punch_list else None,
        )
        if errs:
            builder_v1_warnings = list(errs)
    except Exception as e:
        builder_v1_error = f"{type(e).__name__}: {e}"
        logger.warning(f"[build-with-loop] builder v1 crashed: {builder_v1_error}")
    steps.append(_stamp(
        "builder_v1", t0,
        result={
            "html_length": len(html_v1 or ""),
            "first_3_ctas": _extract_first_n_ctas(html_v1 or "", 3),
            "warnings": builder_v1_warnings,
        },
        error=builder_v1_error,
    ))
    final_html = html_v1

    # ── 5. Critique v1 ───────────────────────────────────────────
    t0 = time.time()
    critique_v1: Optional[Dict] = None
    critique_v1_error: Optional[str] = None
    try:
        critique_v1 = critique_site(
            module_id=module_id,
            html=html_v1 or "",
            css="",
            enriched_brief=enriched_brief,
        )
    except Exception as e:
        critique_v1_error = f"{type(e).__name__}: {e}"
        logger.warning(f"[build-with-loop] critique v1 crashed: {critique_v1_error}")
    steps.append(_stamp(
        "critique_v1", t0,
        result=_critique_summary(critique_v1),
        error=critique_v1_error,
    ))

    # ── 6. Regenerate gate ──────────────────────────────────────
    # Trigger when v1 verdict == "fail" (any HIGH violation) AND we
    # have attempts left. MEDIUM/LOW alone never trigger regenerate
    # (per Pass 4.0b spec — they're advisory, not blocking).
    v1_verdict = (critique_v1 or {}).get("summary", {}).get("verdict")
    v1_violations = (critique_v1 or {}).get("violations") or []
    regenerated = False
    final_critique = critique_v1

    if (
        v1_verdict == "fail"
        and max_attempts >= 2
        and html_v1 is not None
    ):
        # ── 7. Builder v2 (with punch list + rubric for MAINTAIN block) ─
        t0 = time.time()
        html_v2: Optional[str] = None
        builder_v2_error: Optional[str] = None
        builder_v2_warnings: List[str] = []
        try:
            html_v2, builder_v2_error, errs2 = build_html(
                brief, bundle, None, [], [],
                punch_list=v1_violations,
                rubric=rubric_for_builder,
            )
            if errs2:
                builder_v2_warnings = list(errs2)
        except Exception as e:
            builder_v2_error = f"{type(e).__name__}: {e}"
            logger.warning(f"[build-with-loop] builder v2 crashed: {builder_v2_error}")
        steps.append(_stamp(
            "builder_v2", t0,
            result={
                "html_length": len(html_v2 or ""),
                "first_3_ctas": _extract_first_n_ctas(html_v2 or "", 3),
                "warnings": builder_v2_warnings,
                "punch_list_size": len(v1_violations),
            },
            error=builder_v2_error,
        ))
        if html_v2:
            final_html = html_v2

            # ── 8. Critique v2 ──────────────────────────────────
            t0 = time.time()
            critique_v2: Optional[Dict] = None
            critique_v2_error: Optional[str] = None
            try:
                critique_v2 = critique_site(
                    module_id=module_id,
                    html=html_v2,
                    css="",
                    enriched_brief=enriched_brief,
                )
            except Exception as e:
                critique_v2_error = f"{type(e).__name__}: {e}"
                logger.warning(f"[build-with-loop] critique v2 crashed: {critique_v2_error}")
            steps.append(_stamp(
                "critique_v2", t0,
                result=_critique_summary(critique_v2),
                error=critique_v2_error,
            ))
            regenerated = True
            final_critique = critique_v2

    # ── 8.4. Slot coverage check (Pass 4.0b.5.1) ────────────────
    # Diagnostic warning when Builder used fewer data-slot tags than
    # the per-archetype minimum. NON-blocking — recorded in the audit
    # for operator review. Runs on the final shipping HTML so the
    # warning reflects the version the practitioner actually sees.
    coverage_warning = _check_slot_coverage(final_html, enriched_brief)
    if coverage_warning:
        steps.append({
            "step": "slot_coverage_warning",
            "elapsed_seconds": 0.0,
            "result": coverage_warning,
            "error": None,
        })

    # ── 8.5. Slot population (Pass 4.0b.5 PART 4) ───────────────
    # Walk the final HTML for data-slot tags and populate each slot
    # default via its strategy (Unsplash / DALL-E / placeholder).
    # Runs ONCE per build, after Builder + Critique are settled.
    # Independent of the regenerate loop — slots get populated against
    # the final shipping HTML, not per Builder iteration.
    #
    # Skipped without a business_id (no row to persist into) or without
    # final_html. Soft-fails — exceptions captured in the audit, never
    # block persistence.
    slot_population: Optional[Dict[str, Any]] = None
    if business_id and final_html:
        t0 = time.time()
        try:
            from agents.slot_system.builder_post_process import (
                populate_slots_for_site,
            )
            biz_for_slots = bundle.get("business") or {}
            slot_population = populate_slots_for_site(
                html=final_html,
                business_id=business_id,
                enriched_brief=enriched_brief,
                designer_pick=rec,
                business=biz_for_slots,
            )
        except Exception as e:
            logger.warning(
                f"[build-with-loop] slot population crashed: "
                f"{type(e).__name__}: {e}"
            )
            slot_population = {
                "elapsed_seconds": round(time.time() - t0, 3),
                "slots_found": [],
                "slots_populated": [],
                "slots_skipped": [],
                "budget_used_usd": 0.0,
                "warnings": [f"crash: {type(e).__name__}: {e}"],
            }
        steps.append(_stamp(
            "slot_population", t0,
            result={
                "slots_found": slot_population.get("slots_found", []),
                "populated_count": len(slot_population.get("slots_populated") or []),
                "skipped_count": len(slot_population.get("slots_skipped") or []),
                "budget_used_usd": slot_population.get("budget_used_usd", 0.0),
                "populated": slot_population.get("slots_populated", []),
                "skipped": slot_population.get("slots_skipped", []),
                "warnings": slot_population.get("warnings", []),
            },
        ))

    # ── Final status ────────────────────────────────────────────
    final_verdict = (final_critique or {}).get("summary", {}).get("verdict")
    if final_html is None:
        status = "error"
    elif final_verdict == "pass":
        status = "success"
    else:
        status = "fail"

    # ── 9. Persistence (Pass 4.0b.4) ────────────────────────────
    # Mirror the persistence pattern at public_site.py:2710 so the
    # build is immediately viewable at /sites/{business_id}/preview
    # and inside the MySite iframe. Persist even on verdict=fail —
    # the user wants to see and debug failing builds, not just
    # passing ones. Soft-fails so a Supabase blip never wrecks the
    # response.
    persistence: Optional[Dict[str, Any]] = None
    if business_id and final_html:
        try:
            from brand_engine import _sb_get as be_get, _sb_patch as be_patch
            rows = be_get(
                f"/business_sites?business_id=eq.{business_id}"
                "&select=id,site_config&limit=1"
            ) or []
            if not rows:
                persistence = {
                    "persisted": False,
                    "error": (
                        f"no business_sites row for business_id={business_id}"
                    ),
                }
            else:
                site_id = rows[0]["id"]
                cfg = dict(rows[0].get("site_config") or {})
                cfg["generated_html"] = final_html
                cfg["html_generated_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
                cfg["html_source"] = "build-with-loop"
                # Pass 4.0c: persist the brief/pick/inputs so /director/
                # refine can reload them without re-running enrichment +
                # designer + brief expander on every refine call. Only
                # write the keys we actually have — preserves any
                # hand-edited values from earlier passes.
                if enriched_brief is not None:
                    cfg["enriched_brief"] = enriched_brief
                if rec is not None:
                    cfg["design_recommendation"] = rec
                cfg["build_inputs"] = {
                    "business_name": business_name,
                    "module_id": module_id,
                    "description": description,
                    "colors": colors,
                    "practitioner_voice": practitioner_voice,
                    "strategy_track_summary": strategy_track_summary,
                    "vocab_id": vocab_id,
                    "max_attempts": max_attempts,
                }
                # Clear any prior failure markers so /preview falls through
                # to the new HTML cleanly.
                cfg.pop("html_build_failed_at", None)
                cfg.pop("html_build_error", None)
                be_patch(
                    f"/business_sites?id=eq.{site_id}",
                    {"site_config": cfg},
                )
                persistence = {
                    "persisted": True,
                    "site_id": site_id,
                    "preview_path": f"/sites/{business_id}/preview",
                    "html_length": len(final_html),
                }
        except Exception as e:
            logger.warning(
                f"[build-with-loop] persistence failed for {business_id}: "
                f"{type(e).__name__}: {e}"
            )
            persistence = {
                "persisted": False,
                "error": f"{type(e).__name__}: {e}",
            }

    return {
        "status": status,
        "elapsed_total_seconds": round(time.time() - start, 3),
        "regenerated": regenerated,
        "steps": steps,
        "final_html": final_html if include_html else None,
        "html_length": len(final_html or ""),
        "persistence": persistence,
        "slot_population": slot_population,
    }
