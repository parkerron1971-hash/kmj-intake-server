"""Pass 4.0c PART 3 — Director Refine + chat history.

The refine flow:

  1. Insert user message into site_chat_history (status='pending').
  2. Detect in-flight build for this business — return 409 if found.
  3. Load business design state (enriched_brief + design_pick + build_inputs
     from site_config; falls back to businesses table for legacy sites).
  4. enrich_feedback(user_text, module_id, brief, pick) → expanded_moves.
  5. Insert system message (status='in_progress', enriched_intent +
     expanded_moves on the row).
  6a. estimated_regenerate_needed=False → try slot reroll if a slot
      name is detectable in the moves; mark system message complete
      with the slot outcome.
  6b. estimated_regenerate_needed=True → call run_build_loop with
      initial_punch_list=expanded_moves. Wait synchronously. Update
      system message with critique summary + cost on completion.

The HTTP request to /director/refine may exceed proxy/curl timeouts
on the slow path (3-5 min builds). The chat row in site_chat_history
is the source of truth — frontend polls /chat-history to detect
completion via build_status='completed' regardless of HTTP outcome.

Owner gating: NONE. Same trust-on-URL pattern as the rest of the
codebase. Pass 4.0c+ retrofit for cross-cutting auth.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from agents.director_agent.feedback_enrichment import enrich_feedback

logger = logging.getLogger(__name__)

IN_FLIGHT_WINDOW_MINUTES = 10
HTTP_TIMEOUT = 30.0


# ─── Supabase REST helpers (sync; mirror brand_engine pattern) ─────

def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_anon() -> str:
    return os.environ.get("SUPABASE_ANON", "")


def _sb_headers(prefer_representation: bool = True) -> Dict[str, str]:
    h = {
        "apikey": _sb_anon(),
        "Authorization": f"Bearer {_sb_anon()}",
        "Content-Type": "application/json",
    }
    if prefer_representation:
        h["Prefer"] = "return=representation"
    return h


def _sb_post(path: str, body: Any) -> Optional[Any]:
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.post(
                f"{_sb_url()}/rest/v1{path}",
                headers=_sb_headers(),
                content=json.dumps(body),
            )
        if r.status_code >= 400:
            logger.warning(f"sb POST {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"sb POST {path} failed: {e}")
        return None


def _sb_patch(path: str, body: Dict[str, Any]) -> Optional[Any]:
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.patch(
                f"{_sb_url()}/rest/v1{path}",
                headers=_sb_headers(),
                content=json.dumps(body),
            )
        if r.status_code >= 400:
            logger.warning(f"sb PATCH {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"sb PATCH {path} failed: {e}")
        return None


def _sb_delete(path: str) -> bool:
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.delete(
                f"{_sb_url()}/rest/v1{path}",
                headers=_sb_headers(prefer_representation=False),
            )
        if r.status_code >= 400:
            logger.warning(f"sb DELETE {path}: {r.status_code} {r.text[:200]}")
            return False
        return True
    except httpx.HTTPError as e:
        logger.warning(f"sb DELETE {path} failed: {e}")
        return False


# ─── Chat history operations ────────────────────────────────────────

def insert_chat_message(
    business_id: str,
    message_type: str,
    user_text: Optional[str] = None,
    enriched_intent: Optional[str] = None,
    expanded_moves: Optional[List[Dict[str, Any]]] = None,
    build_id: Optional[str] = None,
    build_status: str = "pending",
    build_summary: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Insert a row into site_chat_history. Returns the created row
    (with id) on success, None on failure."""
    body = {
        "business_id": business_id,
        "message_type": message_type,
        "user_text": user_text,
        "enriched_intent": enriched_intent,
        "expanded_moves": expanded_moves,
        "build_id": build_id,
        "build_status": build_status,
        "build_summary": build_summary,
    }
    res = _sb_post("/site_chat_history", body)
    if isinstance(res, list) and res:
        return res[0]
    return None


def update_chat_message_status(
    message_id: str,
    build_status: str,
    build_summary: Optional[Dict[str, Any]] = None,
    build_id: Optional[str] = None,
) -> bool:
    """Update a chat message's build_status (and optionally
    build_summary, build_id). Returns True on success."""
    patch: Dict[str, Any] = {"build_status": build_status}
    if build_summary is not None:
        patch["build_summary"] = build_summary
    if build_id is not None:
        patch["build_id"] = build_id
    res = _sb_patch(f"/site_chat_history?id=eq.{message_id}", patch)
    return res is not None


def get_chat_history(business_id: str) -> List[Dict[str, Any]]:
    """Return all chat messages for a business, ordered by created_at."""
    from brand_engine import _sb_get as be_get
    rows = be_get(
        f"/site_chat_history?business_id=eq.{business_id}"
        "&select=*&order=created_at.asc"
    ) or []
    return rows if isinstance(rows, list) else []


def delete_chat_history(business_id: str) -> bool:
    """Wipe all chat messages for a business. Used by the 'start fresh'
    UX path."""
    return _sb_delete(f"/site_chat_history?business_id=eq.{business_id}")


def find_in_flight_build(business_id: str) -> Optional[Dict[str, Any]]:
    """Returns the in-flight system message for this business if one
    exists within the last IN_FLIGHT_WINDOW_MINUTES, else None.

    Used by /director/refine as the 409 gate so two parallel refine
    requests don't double-spend on a Builder regenerate."""
    from brand_engine import _sb_get as be_get
    cutoff_ts = time.time() - (IN_FLIGHT_WINDOW_MINUTES * 60)
    cutoff_iso = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(cutoff_ts)
    )
    rows = be_get(
        f"/site_chat_history?business_id=eq.{business_id}"
        f"&build_status=eq.in_progress"
        f"&created_at=gte.{cutoff_iso}"
        "&select=*&order=created_at.desc&limit=1"
    ) or []
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


# ─── Business design state loader ───────────────────────────────────

def get_business_design_state(business_id: str) -> Dict[str, Any]:
    """Load everything refine needs to know about a business:
      - enriched_brief (from site_config, populated by future builds)
      - design_pick (from site_config.design_recommendation)
      - build_inputs (the original /director/build-with-loop request,
        persisted by build_with_loop on completion)
      - business_name (from businesses table fallback)

    Returns a dict that's never empty — every key is at least None.
    Designed so callers can destructure without optional-key gymnastics."""
    from brand_engine import _sb_get as be_get

    state: Dict[str, Any] = {
        "business_id": business_id,
        "business_name": "",
        "site_id": None,
        "enriched_brief": None,
        "design_pick": None,
        "build_inputs": None,
        "generated_html_length": 0,
    }

    biz_rows = be_get(
        f"/businesses?id=eq.{business_id}&select=name&limit=1"
    ) or []
    if biz_rows:
        state["business_name"] = biz_rows[0].get("name") or ""

    site_rows = be_get(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=id,site_config&limit=1"
    ) or []
    if site_rows:
        state["site_id"] = site_rows[0].get("id")
        cfg = site_rows[0].get("site_config") or {}
        state["enriched_brief"] = cfg.get("enriched_brief")
        state["design_pick"] = cfg.get("design_recommendation")
        state["build_inputs"] = cfg.get("build_inputs")
        gh = cfg.get("generated_html") or ""
        state["generated_html_length"] = len(gh) if isinstance(gh, str) else 0

    return state


def resolve_module_id(design_pick: Optional[Dict[str, Any]]) -> str:
    """Resolve the active Design Intelligence Module from a design pick.
    Falls back to 'cinematic_authority' (the only module shipped today)
    when no pick or no match. Always returns a non-empty string."""
    if not design_pick:
        return "cinematic_authority"
    try:
        from agents.design_intelligence import find_module_for_strands
        module_id = find_module_for_strands(
            strand_a=design_pick.get("strand_a_id") or "",
            strand_b=design_pick.get("strand_b_id") or "",
            ratio_a=int(design_pick.get("ratio_a") or 50),
        )
        return module_id or "cinematic_authority"
    except Exception as e:
        logger.warning(f"[refine] resolve_module_id failed: {e}")
        return "cinematic_authority"


# ─── Slot detection (for slot-only refines) ─────────────────────────

def detect_slot_from_moves(
    moves: List[Dict[str, Any]],
) -> Optional[str]:
    """Scan expanded_moves for a known slot_name. Returns the first
    match or None. Used when estimated_regenerate_needed=False to
    auto-trigger a slot reroll on the affected slot."""
    try:
        from agents.slot_system.slot_definitions import SLOT_DEFINITIONS
    except Exception:
        return None
    slot_names = list(SLOT_DEFINITIONS.keys())
    blob_parts: List[str] = []
    for m in moves or []:
        if not isinstance(m, dict):
            continue
        for k in ("rule_id", "description", "fix_hint"):
            v = m.get(k)
            if v:
                blob_parts.append(str(v))
    blob = " ".join(blob_parts).lower()
    for slot_name in slot_names:
        if slot_name in blob:
            return slot_name
    return None


# ─── Diagnose endpoint (fixed v1 question) ──────────────────────────

DIAGNOSE_QUESTION = "What feels missing? (pick any that apply)"
DIAGNOSE_OPTIONS = [
    {"id": "depth", "label": "More visual depth"},
    {"id": "animation", "label": "More animation"},
    {"id": "imagery", "label": "More imagery"},
    {"id": "typography", "label": "Bolder typography"},
    {"id": "rhythm", "label": "Stronger section rhythm"},
    {"id": "voice", "label": "More on-brand voice"},
]


def get_diagnose_question() -> Dict[str, Any]:
    """Return the diagnose multi-select. Pass 4.0c v1: fixed 6 options;
    a future pass can make it module-aware."""
    return {
        "question": DIAGNOSE_QUESTION,
        "options": DIAGNOSE_OPTIONS,
        "submit_action": (
            "POST /director/refine with the joined option labels as user_text"
        ),
    }


# ─── Main refine flow ───────────────────────────────────────────────

def run_refine(
    business_id: str,
    user_text: str,
    quality: str = "hd",
) -> Dict[str, Any]:
    """Execute the full refine flow. Returns a dict with status info
    and (when build completed) the new HTML's audit summary.

    Possible top-level shapes:
      {"status": "in_flight", "in_flight_message_id": "...",
       "in_flight_started_at": "...", "advice": "..."}            ← 409 case
      {"status": "slot_only", "user_message_id": "...",
       "system_message_id": "...", "slot_name": ..., ...}         ← slot path
      {"status": "regenerate_completed", "user_message_id": "...",
       "system_message_id": "...", "build_summary": {...}}        ← Builder path
      {"status": "regenerate_failed", ...}                        ← Builder error
      {"status": "no_business_state", ...}                        ← legacy site
    """
    # 1. In-flight check ─ done BEFORE the user message insert so we
    #    don't pollute history when rejecting a duplicate request.
    inflight = find_in_flight_build(business_id)
    if inflight:
        return {
            "status": "in_flight",
            "in_flight_message_id": inflight.get("id"),
            "in_flight_started_at": inflight.get("created_at"),
            "advice": (
                "A refine is already running for this business. Wait for it "
                "to complete (typically 3-5 minutes) before submitting another."
            ),
        }

    # 2. Insert user message
    user_msg = insert_chat_message(
        business_id=business_id,
        message_type="user",
        user_text=user_text,
        build_status="pending",
    )
    if not user_msg:
        return {
            "status": "error",
            "error": "Could not persist user message to chat history",
        }
    user_message_id = user_msg.get("id")

    # 3. Load business state
    state = get_business_design_state(business_id)
    if not state.get("site_id"):
        update_chat_message_status(
            user_message_id, "failed",
            build_summary={"error": "no business_sites row for this business_id"},
        )
        return {
            "status": "no_business_state",
            "user_message_id": user_message_id,
            "error": "no business_sites row for this business_id",
        }

    # 4. Determine module_id and call enrich_feedback
    module_id = resolve_module_id(state.get("design_pick"))
    enrichment = enrich_feedback(
        user_text=user_text,
        module_id=module_id,
        enriched_brief=state.get("enriched_brief"),
        design_pick=state.get("design_pick"),
    )
    inferred_intent = enrichment.get("inferred_intent") or ""
    expanded_moves = enrichment.get("expanded_moves") or []
    needs_regen = bool(enrichment.get("estimated_regenerate_needed"))

    # 5. Insert system message — status starts in_progress to gate
    #    parallel refines via the in-flight check.
    system_msg = insert_chat_message(
        business_id=business_id,
        message_type="system",
        enriched_intent=inferred_intent,
        expanded_moves=expanded_moves,
        build_status="in_progress",
    )
    if not system_msg:
        update_chat_message_status(
            user_message_id, "failed",
            build_summary={"error": "Could not persist system message"},
        )
        return {
            "status": "error",
            "error": "Could not persist system message to chat history",
        }
    system_message_id = system_msg.get("id")

    # 6a. Slot-only path — no Builder regenerate. Try to auto-trigger
    #     a slot reroll if the moves point at a specific slot.
    if not needs_regen:
        slot_name = detect_slot_from_moves(expanded_moves)
        slot_outcome: Dict[str, Any] = {
            "regenerate_skipped": True,
            "module_id": module_id,
            "scope": enrichment.get("scope"),
            "moves_count": len(expanded_moves),
            "detected_slot_name": slot_name,
        }
        if slot_name:
            slot_outcome.update(_attempt_slot_reroll(
                business_id=business_id,
                slot_name=slot_name,
                quality=quality,
            ))
        update_chat_message_status(
            system_message_id, "completed", build_summary=slot_outcome,
        )
        update_chat_message_status(user_message_id, "completed")
        return {
            "status": "slot_only",
            "user_message_id": user_message_id,
            "system_message_id": system_message_id,
            "module_id": module_id,
            "inferred_intent": inferred_intent,
            "expanded_moves": expanded_moves,
            "slot_outcome": slot_outcome,
        }

    # 6b. Regenerate path — call run_build_loop with initial_punch_list.
    build_inputs = state.get("build_inputs") or {}
    business_name = (
        build_inputs.get("business_name")
        or state.get("business_name")
        or "Untitled"
    )
    build_summary: Dict[str, Any] = {
        "module_id": module_id,
        "moves_count": len(expanded_moves),
        "scope": enrichment.get("scope"),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        from agents.director_agent.build_with_loop import run_build_loop
        result = run_build_loop(
            business_name=business_name,
            module_id=module_id,
            description=build_inputs.get("description"),
            colors=build_inputs.get("colors"),
            practitioner_voice=build_inputs.get("practitioner_voice"),
            strategy_track_summary=build_inputs.get("strategy_track_summary"),
            vocab_id=build_inputs.get("vocab_id") or "sovereign-authority",
            max_attempts=int(build_inputs.get("max_attempts") or 2),
            include_html=False,
            business_id=business_id,
            initial_punch_list=expanded_moves,
        )
    except Exception as e:
        logger.warning(f"[refine] run_build_loop crashed: {type(e).__name__}: {e}")
        build_summary["error"] = f"{type(e).__name__}: {e}"
        build_summary["finished_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
        )
        update_chat_message_status(
            system_message_id, "failed", build_summary=build_summary,
        )
        update_chat_message_status(user_message_id, "failed")
        return {
            "status": "regenerate_failed",
            "user_message_id": user_message_id,
            "system_message_id": system_message_id,
            "error": build_summary["error"],
        }

    # Extract critique summary + cost from the loop result for the
    # chat row's build_summary. This is what the frontend renders in
    # the version marker.
    final_critique = None
    cost_dalle = 0.0
    builder_attempts = 0
    for step in result.get("steps") or []:
        sname = step.get("step")
        if sname == "critique_v2":
            final_critique = step.get("result") or {}
        elif sname == "critique_v1" and final_critique is None:
            final_critique = step.get("result") or {}
        elif sname == "slot_population":
            r = step.get("result") or {}
            cost_dalle += float(r.get("budget_used_usd") or 0)
        elif sname in ("builder_v1", "builder_v2"):
            builder_attempts += 1

    build_summary.update({
        "final_status": result.get("status"),
        "regenerated": bool(result.get("regenerated")),
        "elapsed_total_seconds": result.get("elapsed_total_seconds"),
        "html_length": result.get("html_length"),
        "builder_attempts": builder_attempts,
        "critique": {
            "verdict": (final_critique or {}).get("verdict"),
            "high": (final_critique or {}).get("high"),
            "medium": (final_critique or {}).get("medium"),
            "low": (final_critique or {}).get("low"),
        },
        "cost_dalle_usd": round(cost_dalle, 4),
        "persistence": result.get("persistence"),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })

    final_status = (
        "completed" if result.get("status") in ("success", "fail") else "failed"
    )
    update_chat_message_status(
        system_message_id, final_status, build_summary=build_summary,
    )
    update_chat_message_status(user_message_id, "completed")

    return {
        "status": "regenerate_completed",
        "user_message_id": user_message_id,
        "system_message_id": system_message_id,
        "module_id": module_id,
        "inferred_intent": inferred_intent,
        "expanded_moves": expanded_moves,
        "build_summary": build_summary,
    }


def _attempt_slot_reroll(
    business_id: str,
    slot_name: str,
    quality: str = "hd",
) -> Dict[str, Any]:
    """Attempt a slot reroll. Returns a structured outcome dict that
    gets merged into the system message's build_summary. Never raises."""
    try:
        from agents.slot_system import slot_storage
        from agents.slot_system.slot_definitions import get_slot_definition
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
        return {"slot_reroll_status": "import_failed", "error": str(e)}

    defn = get_slot_definition(slot_name)
    if not defn:
        return {
            "slot_reroll_status": "unknown_slot",
            "slot_name": slot_name,
        }
    strategy = defn.get("default_strategy")
    if strategy == "placeholder":
        return {
            "slot_reroll_status": "placeholder_strategy",
            "slot_name": slot_name,
            "advice": "Profile slots are uploads only.",
        }

    slot_storage.reset_rerolls_if_new_day(business_id, slot_name)
    can_reroll, current_count = slot_storage.can_reroll(business_id, slot_name)
    if not can_reroll:
        return {
            "slot_reroll_status": "rate_limited",
            "slot_name": slot_name,
            "current_count": current_count,
        }

    record = slot_storage.get_slot(business_id, slot_name) or {}

    if strategy in ("unsplash", "unsplash_with_dalle_fallback"):
        cached_query = record.get("default_query")
        if not cached_query:
            try:
                from brand_engine import _sb_get as be_get
                rows = be_get(
                    f"/businesses?id=eq.{business_id}&select=name&limit=1"
                ) or []
                biz = rows[0] if rows else {}
            except Exception:
                biz = {}
            cached_query = build_unsplash_query(
                slot_name=slot_name,
                enriched_brief={},
                designer_pick={},
                business={"name": biz.get("name") or "", "elevator_pitch": ""},
            )
        # Aspect → orientation hint, mirroring the populate logic.
        aspect = defn.get("aspect_ratio") or ""
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
        result = query_unsplash(
            query=cached_query,
            orientation=orientation,
            min_width=min_w,
            result_index=current_count + 1,
        )
        if result and result.get("url"):
            slot_storage.set_slot_default(
                business_id=business_id,
                slot_name=slot_name,
                url=result["url"],
                source="unsplash",
                credit=result.get("credit"),
                query=cached_query,
            )
            slot_storage.increment_reroll(business_id, slot_name)
            return {
                "slot_reroll_status": "ok",
                "slot_name": slot_name,
                "source": "unsplash",
                "url": result["url"],
                "cost_usd": 0.0,
                "credit": result.get("credit"),
            }
        if strategy == "unsplash":
            return {
                "slot_reroll_status": "no_unsplash_result",
                "slot_name": slot_name,
            }
        # else fall through to DALL-E

    if strategy == "dalle" or strategy == "unsplash_with_dalle_fallback":
        cached_prompt = record.get("default_dalle_prompt")
        if not cached_prompt:
            cached_prompt = build_dalle_prompt(slot_name, {}, {})
        size = "1024x1024"
        expected = dalle_cost(quality, size)
        allowed, current_spend = can_dalle_generate(business_id, expected)
        if not allowed:
            return {
                "slot_reroll_status": "budget_cap_exceeded",
                "slot_name": slot_name,
                "current_spend_usd": current_spend,
                "expected_cost_usd": expected,
            }
        gen = generate_dalle_image(
            prompt=cached_prompt,
            business_id=business_id,
            slot_name=slot_name,
            quality=quality,
            size=size,
            style="natural",
        )
        if not gen:
            return {
                "slot_reroll_status": "dalle_failed",
                "slot_name": slot_name,
            }
        slot_storage.set_slot_default(
            business_id=business_id,
            slot_name=slot_name,
            url=gen["url"],
            source="dalle",
            credit=None,
            dalle_prompt=cached_prompt,
        )
        slot_storage.increment_reroll(business_id, slot_name)
        return {
            "slot_reroll_status": "ok",
            "slot_name": slot_name,
            "source": "dalle",
            "url": gen["url"],
            "cost_usd": gen.get("cost_usd", expected),
        }

    return {"slot_reroll_status": "unhandled_strategy", "strategy": strategy}
