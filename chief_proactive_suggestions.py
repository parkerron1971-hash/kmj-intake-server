"""
chief_proactive_suggestions.py — Phase C.1.3 (NT8a/b/e).

Emits proactive `chief_suggestions` rows when a business hits a
meaningful state change. Idempotent: never duplicates a (business_id,
archetype) suggestion if one already exists in proposed/snoozed state.

Called from chief_chat's entry path (best-effort, never blocks). Cost
is one Supabase read per turn plus 0-N inserts on fresh state changes.

Discipline anchors:
  NT8a  — blueprint signal + LLM knowledge unlock. This module reads the
          business_type_module_blueprint to know what core modules a
          vertical typically has; the LLM uses its broader knowledge
          when the practitioner later RUNS the proposal (NT8f).
  NT8b  — triggers on meaningful state change, not every turn. We
          implement two baseline signals: low_module_count + fresh_signup.
          Additional signals (foundation_complete, etc.) come later.
  NT8e  — only `chief_can_suggest=true` archetypes from ArchetypeEnum
          are ever stored. fallback_generic is never suggested.
  NT8g  — when the blueprint mentions a module slug whose archetype is
          NOT chief_can_suggest (or doesn't exist), we DON'T emit a
          suggestion — that would be Chief overcommitting. The team
          sees the demand signal indirectly through which suggestions
          got accepted.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import sb_clients

logger = logging.getLogger("chief_proactive_suggestions")

# Days since signup that count as "fresh."
FRESH_SIGNUP_DAYS = 7

# Module-count threshold below which we treat the business as "low".
LOW_MODULE_COUNT_THRESHOLD = 3

# Hard cap on simultaneously-active suggestions so the panel never
# overwhelms.
MAX_ACTIVE_SUGGESTIONS = 4


def maybe_emit_proactive_suggestions(business: Dict[str, Any]) -> int:
    """Best-effort. Returns count of newly-inserted suggestion rows. Never
    raises — failures log + return 0 so the chat path keeps moving."""
    try:
        return _emit(business)
    except Exception as e:  # pragma: no cover
        logger.warning(f"proactive suggestions failed for biz={business.get('id')}: {e}")
        return 0


def _emit(business: Dict[str, Any]) -> int:
    biz_id = business.get("id")
    biz_type = (business.get("type") or "").strip().lower() or "custom"
    if not biz_id:
        return 0

    # Cap check up front — if the practitioner already has the max active
    # suggestions, don't add more. The panel's job is to clear them.
    active_count = _count_active(biz_id)
    if active_count >= MAX_ACTIVE_SUGGESTIONS:
        return 0

    # State-change signals (NT8b baseline).
    signals = _detect_state_signals(business)
    if not signals:
        return 0

    # Load the closed enum of currently-suggestable archetypes (NT8e gate).
    try:
        from module_spec_generator import suggestable_archetypes, ARCHETYPE_METADATA
        ok_archetypes = set(suggestable_archetypes())
    except Exception as e:
        logger.warning(f"could not load archetype metadata: {e}")
        return 0

    # Load the blueprint for this business type — the structural signal.
    # If no rows for this type, fall back to a generic-friendly subset.
    blueprint_rows = sb_clients.sb_get_as_service(
        f"/business_type_module_blueprint?business_type=eq.{biz_type}"
        f"&tier=eq.core&order=sort_order.asc&select=module_slug,module_name,reason,description"
    ) or []

    # VABI v1 — when the blueprint table has nothing for this vertical,
    # fall back to vertical_intelligence's module_suggestions list so
    # newly-mapped verticals (lawyer, ministry, etc.) still get curated
    # first-modules even before someone seeds business_type_module_blueprint.
    if not blueprint_rows:
        try:
            from vertical_intelligence import get_module_suggestions
            vi_suggestions = get_module_suggestions(biz_type)
            blueprint_rows = [
                {
                    "module_slug": s.get("slug"),
                    "module_name": (s.get("slug") or "").replace("-", " ").title(),
                    "reason": s.get("headline"),
                    "description": s.get("headline"),
                }
                for s in vi_suggestions if s.get("slug")
            ]
        except Exception as e:
            logger.warning(f"VABI fallback for module suggestions failed: {e}")

    # What modules does the business ALREADY have? Don't suggest those.
    existing_rows = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{biz_id}&is_active=eq.true"
        f"&select=slug,archetype"
    ) or []
    existing_slugs = {(r.get("slug") or "").lower() for r in existing_rows}

    # Already-active or recently-decided suggestion targets — don't dupe.
    existing_sug_rows = sb_clients.sb_get_as_service(
        f"/chief_suggestions?business_id=eq.{biz_id}"
        f"&status=in.(proposed,snoozed,accepted)&select=archetype,kind,title"
    ) or []
    existing_sug_archetypes = {(r.get("archetype") or "").lower() for r in existing_sug_rows}
    existing_sug_titles = {(r.get("title") or "").lower() for r in existing_sug_rows}

    inserted = 0
    capacity = MAX_ACTIVE_SUGGESTIONS - active_count

    # Suggest the FIRST blueprint-derived module that:
    #   (a) maps to a chief_can_suggest archetype
    #   (b) the business doesn't already have
    #   (c) hasn't been suggested before (any non-dismissed state)
    # Blueprint module_slug → archetype mapping is heuristic for now: if
    # the slug contains "book" or "appoint", assume booking_calendar.
    # Future expansion: store archetype directly on blueprint rows.
    for row in blueprint_rows:
        if inserted >= capacity:
            break
        slug = (row.get("module_slug") or "").lower()
        name = row.get("module_name") or slug.replace("-", " ").title()
        if not slug:
            continue
        if slug in existing_slugs:
            continue
        archetype = _slug_to_archetype(slug)
        if archetype not in ok_archetypes:
            # NT8g — the blueprint mentions something we can't ship cleanly
            # yet. We don't suggest. Future archetype work fills these in.
            continue
        if archetype in existing_sug_archetypes:
            continue
        title = f"Set up {name}"
        if title.lower() in existing_sug_titles:
            continue

        intake_seed = (row.get("description") or row.get("reason") or
                       f"I need {name.lower()} for my {biz_type} business.")
        triggered_by = ",".join(signals)

        new_row = sb_clients.sb_post_as_service("/chief_suggestions", {
            "business_id": biz_id,
            "kind": "module",
            "archetype": archetype,
            "title": title,
            "rationale": row.get("reason") or
                f"Common for {biz_type} businesses at your stage.",
            "status": "proposed",
            "triggered_by": triggered_by,
            "intake_seed": intake_seed,
        })
        if isinstance(new_row, list) and new_row:
            inserted += 1

    return inserted


def _slug_to_archetype(slug: str) -> str:
    """Heuristic — until blueprint rows carry an explicit archetype column.
    Conservative: when in doubt, return fallback_generic (which will be
    filtered out by the suggestable_archetypes gate)."""
    s = slug.lower()
    if "book" in s or "appoint" in s or "schedule" in s or "session" in s:
        return "booking_calendar"
    return "fallback_generic"


def _count_active(business_id: str) -> int:
    rows = sb_clients.sb_get_as_service(
        f"/chief_suggestions?business_id=eq.{business_id}"
        f"&status=in.(proposed,snoozed)&select=id"
    ) or []
    return len(rows) if isinstance(rows, list) else 0


def _detect_state_signals(business: Dict[str, Any]) -> List[str]:
    """Return a list of state-change signals that fired. Empty list = no
    proactive suggestion this turn."""
    signals: List[str] = []
    biz_id = business.get("id")

    # Signal 1: fresh signup
    created_at = business.get("created_at") or ""
    if created_at:
        try:
            from datetime import datetime, timezone
            ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if (now - ts).days <= FRESH_SIGNUP_DAYS:
                signals.append("fresh_signup")
        except Exception:
            pass

    # Signal 2: low module count
    mod_rows = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{biz_id}&is_active=eq.true&select=id"
    ) or []
    n_modules = len(mod_rows) if isinstance(mod_rows, list) else 0
    if n_modules < LOW_MODULE_COUNT_THRESHOLD:
        signals.append("low_module_count")

    return signals
