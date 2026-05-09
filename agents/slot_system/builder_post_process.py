"""Pass 4.0b.5 PART 4 — Post-build slot population.

After Builder Agent returns HTML containing <img data-slot="X" src=""
alt="..."> tags and Critique completes, this module walks every slot
referenced in the HTML, resolves it via the slot's default_strategy
(Unsplash / DALL-E / placeholder), and persists the resolved URL via
slot_storage.set_slot_default.

Slot population is independent of the Builder regenerate loop. It
runs ONCE per build_with_loop call, on the final HTML that ships.

Design choices:
  - Skip slots that already have a default_url persisted. This makes
    re-fires cheap (PART 3's decorative_1 image survives a re-run)
    and lets the practitioner-driven /reroll endpoint (PART 5) be the
    explicit replacement path.
  - Skip slots whose default_strategy is "placeholder" — they exist
    to prompt practitioner uploads, not to auto-fill.
  - DALL-E budget cap rejection is logged as a warning, not an error.
    The slot stays at default_url=None so the renderer falls through
    to a styled placeholder.
  - Unsplash failure (no result) on an "unsplash_with_dalle_fallback"
    strategy triggers DALL-E fallback (subject to budget cap).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Match data-slot="..." (or single-quoted, or unquoted) and capture
# the slot name. Same regex shape used by slot_resolver._IMG_SLOT_RE
# but only needs the slot name here.
_SLOT_NAME_RE = re.compile(
    r"""<img\b[^>]*?\bdata-slot\s*=\s*["']?([a-z_0-9]+)["']?""",
    re.IGNORECASE,
)


def _extract_slot_names_from_html(html: str) -> List[str]:
    """Return every distinct slot_name referenced via data-slot in
    document order (first-occurrence wins for ordering)."""
    if not html:
        return []
    seen: Set[str] = set()
    ordered: List[str] = []
    for m in _SLOT_NAME_RE.finditer(html):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def populate_slots_for_site(
    html: str,
    business_id: str,
    enriched_brief: Optional[Dict[str, Any]] = None,
    designer_pick: Optional[Dict[str, Any]] = None,
    business: Optional[Dict[str, Any]] = None,
    force_regenerate: bool = False,
) -> Dict[str, Any]:
    """Walk every data-slot in `html`, populate each slot's default_url
    via its strategy, persist results.

    Args:
      html: final Builder HTML, with data-slot tags.
      business_id: Supabase business id (drives storage path + persist).
      enriched_brief, designer_pick, business: passed through to the
        query / prompt composers.
      force_regenerate: when True, regenerate even if default_url is
        already set. Used by the PART 5 /reroll endpoint, NOT by the
        normal build flow.

    Returns:
      {
        "elapsed_seconds": float,
        "slots_found": [slot_name, ...],
        "slots_populated": [
          {slot_name, source: "unsplash"|"dalle", url, cost_usd, credit?},
          ...
        ],
        "slots_skipped": [
          {slot_name, reason: "already_set"|"placeholder_strategy"
                             |"unknown_slot"|"no_unsplash_result"
                             |"budget_cap"|"dalle_failed"},
          ...
        ],
        "budget_used_usd": float,
        "warnings": [ ... ],
      }

    Soft-fails per slot — one slot's failure never blocks another.
    Top-level exceptions are caught and surfaced in `warnings` so the
    caller (build_with_loop) gets a structured manifest, not a crash.
    """
    start = time.time()
    enriched_brief = enriched_brief or {}
    designer_pick = designer_pick or {}
    business = business or {}

    # Lazy imports — keep this module importable in test contexts
    # without Anthropic / OpenAI / Supabase env vars.
    try:
        from agents.slot_system.slot_definitions import (
            SLOT_DEFINITIONS,
            get_slot_definition,
        )
        from agents.slot_system import slot_storage
        from agents.slot_system.unsplash_client import (
            build_unsplash_query,
            query_unsplash,
        )
        from agents.slot_system.dalle_client import (
            build_dalle_prompt,
            can_dalle_generate,
            dalle_cost,
            generate_dalle_image,
        )
    except Exception as e:
        return {
            "elapsed_seconds": round(time.time() - start, 3),
            "slots_found": [],
            "slots_populated": [],
            "slots_skipped": [],
            "budget_used_usd": 0.0,
            "warnings": [f"slot_system import failed: {type(e).__name__}: {e}"],
        }

    slots_found = _extract_slot_names_from_html(html)
    populated: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    warnings: List[str] = []
    budget_used = 0.0

    # Snapshot existing slots once so we can check "already set" without
    # round-tripping Supabase per slot. This is a single read; per-slot
    # writes still use slot_storage.set_slot_default which re-reads
    # site_config to avoid clobber.
    try:
        existing_slots = slot_storage.get_all_slots(business_id) or {}
    except Exception as e:
        warnings.append(f"get_all_slots failed: {type(e).__name__}: {e}")
        existing_slots = {}

    for slot_name in slots_found:
        defn = get_slot_definition(slot_name)
        if not defn:
            skipped.append({"slot_name": slot_name, "reason": "unknown_slot"})
            warnings.append(f"unknown slot in HTML: {slot_name}")
            continue

        existing = existing_slots.get(slot_name) or {}
        if not force_regenerate and existing.get("default_url"):
            skipped.append({"slot_name": slot_name, "reason": "already_set"})
            continue

        strategy = defn.get("default_strategy")

        if strategy == "placeholder":
            skipped.append({
                "slot_name": slot_name,
                "reason": "placeholder_strategy",
            })
            continue

        # ─── Unsplash path ──────────────────────────────────────
        if strategy in ("unsplash", "unsplash_with_dalle_fallback"):
            try:
                aspect = (defn.get("aspect_ratio") or "")
                # Aspect → orientation hint. 1:1 = squarish, w>h = landscape,
                # w<h = portrait. For 4:5 (about_subject) we use portrait.
                orientation = "landscape"
                if aspect == "1:1":
                    orientation = "squarish"
                elif ":" in aspect:
                    try:
                        w, h = aspect.split(":")
                        if int(w) < int(h):
                            orientation = "portrait"
                    except (ValueError, AttributeError):
                        pass
                min_w = (defn.get("min_dimensions") or {}).get("width", 1200)
                query = build_unsplash_query(
                    slot_name=slot_name,
                    enriched_brief=enriched_brief,
                    designer_pick=designer_pick,
                    business=business,
                )
                result = query_unsplash(
                    query=query,
                    orientation=orientation,
                    min_width=min_w,
                )
            except Exception as e:
                warnings.append(
                    f"unsplash exception for {slot_name}: "
                    f"{type(e).__name__}: {e}"
                )
                result = None

            if result and result.get("url"):
                ok = slot_storage.set_slot_default(
                    business_id=business_id,
                    slot_name=slot_name,
                    url=result["url"],
                    source="unsplash",
                    credit=result.get("credit"),
                )
                if ok:
                    populated.append({
                        "slot_name": slot_name,
                        "source": "unsplash",
                        "url": result["url"],
                        "cost_usd": 0.0,
                        "credit": result.get("credit"),
                    })
                    continue
                warnings.append(f"persist failed for {slot_name}")
                # fall through to dalle fallback below if applicable

            # No Unsplash result. If pure unsplash strategy, give up.
            if strategy == "unsplash":
                skipped.append({
                    "slot_name": slot_name,
                    "reason": "no_unsplash_result",
                })
                continue
            # else fall through to DALL-E fallback

        # ─── DALL-E path (direct or fallback) ───────────────────
        if strategy == "dalle" or (
            strategy == "unsplash_with_dalle_fallback"
            and not any(p["slot_name"] == slot_name for p in populated)
        ):
            expected = dalle_cost("hd", "1024x1024")
            allowed, current_spend = can_dalle_generate(business_id, expected)
            if not allowed:
                skipped.append({
                    "slot_name": slot_name,
                    "reason": "budget_cap",
                    "current_spend_usd": current_spend,
                })
                warnings.append(
                    f"DALL-E budget cap reached before {slot_name} "
                    f"(current=${current_spend:.3f}, expected=${expected:.3f})"
                )
                continue

            try:
                prompt = build_dalle_prompt(
                    slot_name=slot_name,
                    enriched_brief=enriched_brief,
                    designer_pick=designer_pick,
                )
                gen = generate_dalle_image(
                    prompt=prompt,
                    business_id=business_id,
                    slot_name=slot_name,
                    quality="hd",
                    size="1024x1024",
                    style="natural",
                )
            except Exception as e:
                warnings.append(
                    f"dalle exception for {slot_name}: "
                    f"{type(e).__name__}: {e}"
                )
                gen = None

            if not gen:
                skipped.append({
                    "slot_name": slot_name,
                    "reason": "dalle_failed",
                })
                continue

            ok = slot_storage.set_slot_default(
                business_id=business_id,
                slot_name=slot_name,
                url=gen["url"],
                source="dalle",
                credit=None,
            )
            if not ok:
                warnings.append(f"persist failed for {slot_name} (DALL-E URL)")
                continue
            populated.append({
                "slot_name": slot_name,
                "source": "dalle",
                "url": gen["url"],
                "cost_usd": gen.get("cost_usd", expected),
                "credit": None,
            })
            budget_used += float(gen.get("cost_usd", expected))

    return {
        "elapsed_seconds": round(time.time() - start, 3),
        "slots_found": slots_found,
        "slots_populated": populated,
        "slots_skipped": skipped,
        "budget_used_usd": round(budget_used, 4),
        "warnings": warnings,
    }
