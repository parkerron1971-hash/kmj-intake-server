"""
growth_objective_agent.py — LGS Phase 4: the spine. Growth Objectives + the
structure they spawn.

A Growth Objective is a committed growth decision ("launch a group program",
"add recurring revenue") that SPAWNS structure: modules, workflows, milestones.
This is the loop's payload — the Growth Partner (Chief mode) proposes one, the
practitioner commits, and create_growth_objective materializes it.

LOCKED RULINGS honored:
  Fork 3  growth_objectives is its OWN table — NOT settings.goals. metrics may
          REFERENCE a simple goal via linked_goal_key without merging the layers.
  Fork 9  goals / growth_objectives / strategy_tracks stay 3 distinct layers.
  Fork 18 spawned workflows are CLONED from global templates to the business.
  Fork 26 milestones are the timeline rows (Phase 5 renders them); spawned here.

Server-side, service-role (the spawn runs in a Chief turn / cron context).
Module spawning SKIPS access_level:restricted (Giving) — same guard as everywhere;
a growth objective never auto-provisions a restricted module.

spawns shape (on growth_objectives.spawns):
  {"modules": [slug,...], "workflows": [slug,...], "milestones": [{title,due_date?},...]}
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import sb_clients

logger = logging.getLogger("growth_objective_agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] growth_obj: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ──────────────────────────────────────────────────────────────
# Spawn helpers (each soft-fails; a partial spawn is reported, never raises)
# ──────────────────────────────────────────────────────────────

def _business_type(business_id: str) -> str:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=type&limit=1"
    ) or []
    return (rows[0].get("type") if rows else None) or "custom"


def _spawn_modules(business_id: str, business_type: str, slugs: List[str]) -> List[str]:
    """Provision specific blueprint modules by slug into custom_modules. Skips
    restricted modules + slugs that already exist. Returns created module ids."""
    if not slugs:
        return []
    existing = {
        r.get("slug")
        for r in (sb_clients.sb_get_as_service(
            f"/custom_modules?business_id=eq.{business_id}&select=slug") or [])
        if isinstance(r, dict)
    }
    created_ids: List[str] = []
    for slug in slugs:
        if slug in existing:
            continue
        bp = sb_clients.sb_get_as_service(
            f"/business_type_module_blueprint"
            f"?business_type=eq.{business_type}&module_slug=eq.{slug}&limit=1"
        ) or []
        if not bp:
            logger.info(f"no blueprint row for {business_type}/{slug}; skip spawn")
            continue
        row = bp[0]
        if ((row.get("agent_config") or {}).get("access_level")) == "restricted":
            logger.info(f"skip restricted module spawn: {slug}")
            continue
        created = sb_clients.sb_post_as_service("/custom_modules", {
            "business_id": business_id,
            "name": row.get("module_name") or slug,
            "slug": slug,
            "description": row.get("description"),
            "icon": row.get("icon") or "📋",
            "schema": row.get("schema") or {"fields": []},
            "agent_config": row.get("agent_config") or {"enabled": True, "triggers": []},
            "is_active": True,
            "sort_order": row.get("sort_order") or 0,
        })
        if isinstance(created, list) and created:
            created_ids.append(created[0].get("id"))
            existing.add(slug)
    return [i for i in created_ids if i]


def _spawn_workflows(business_id: str, business_type: str, slugs: List[str]) -> List[str]:
    """Clone global workflow templates (business_id NULL) to this business by
    slug (Fork 18). Skips slugs already cloned. Returns created workflow ids.
    Webhook-triggered templates stay DISABLED on clone (Fork 21 — reactive paths
    don't go live until signature verification ships)."""
    if not slugs:
        return []
    existing = {
        r.get("slug")
        for r in (sb_clients.sb_get_as_service(
            f"/workflow_definitions?business_id=eq.{business_id}&select=slug") or [])
        if isinstance(r, dict)
    }
    created_ids: List[str] = []
    for slug in slugs:
        if slug in existing:
            continue
        tmpl = sb_clients.sb_get_as_service(
            f"/workflow_definitions?business_id=is.null&slug=eq.{slug}&limit=1"
        ) or []
        if not tmpl:
            logger.info(f"no global workflow template for slug={slug}; skip")
            continue
        t = tmpl[0]
        trigger = t.get("trigger") or {}
        # Fork 21: a webhook/reactive trigger stays disabled until sig-verify ships.
        is_reactive = bool(trigger.get("event_type", "").startswith(("payment.", "webhook.")))
        created = sb_clients.sb_post_as_service("/workflow_definitions", {
            "business_id": business_id,
            "business_type": business_type,
            "name": t.get("name"),
            "slug": slug,
            "trigger": trigger,
            "steps": t.get("steps") or [],
            "connector_provider": t.get("connector_provider"),
            "enabled": (not is_reactive) and bool(t.get("enabled", True)),
            "source": "growth_objective",
        })
        if isinstance(created, list) and created:
            created_ids.append(created[0].get("id"))
            existing.add(slug)
    return [i for i in created_ids if i]


def _spawn_milestones(business_id: str, objective_id: str,
                      milestones: List[Dict[str, Any]]) -> int:
    """Create growth_milestones rows for the objective. Returns count created."""
    n = 0
    for i, m in enumerate(milestones or []):
        created = sb_clients.sb_post_as_service("/growth_milestones", {
            "objective_id": objective_id,
            "business_id": business_id,
            "title": m.get("title") or f"Milestone {i+1}",
            "due_date": m.get("due_date"),
            "status": "pending",
            "source": "system",
            "order_index": i,
        })
        if isinstance(created, list) and created:
            n += 1
    return n


# ──────────────────────────────────────────────────────────────
# Create + spawn (the materialize step)
# ──────────────────────────────────────────────────────────────

def create_growth_objective(business_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a growth_objective and materialize its spawns (modules, workflows,
    milestones). Best-effort per spawn — a partial spawn is reported, never fatal.
    Returns {ok, objective, spawn_report}."""
    if not business_id or not payload.get("title"):
        return {"ok": False, "error": "business_id and title required"}

    spawns = payload.get("spawns") or {}
    obj_body = {
        "business_id": business_id,
        "title": payload["title"],
        "decision_summary": payload.get("decision_summary"),
        "rationale": payload.get("rationale"),
        "status": payload.get("status", "active"),
        "target_date": payload.get("target_date"),
        "metrics": payload.get("metrics") or {},
        "spawns": spawns,
        "source": payload.get("source", "growth_dialogue"),
    }
    created = sb_clients.sb_post_as_service("/growth_objectives", obj_body)
    if not (isinstance(created, list) and created):
        return {"ok": False, "error": "objective insert failed"}
    objective = created[0]
    obj_id = objective["id"]

    biz_type = _business_type(business_id)
    module_ids = _spawn_modules(business_id, biz_type, spawns.get("modules") or [])
    workflow_ids = _spawn_workflows(business_id, biz_type, spawns.get("workflows") or [])
    ms_count = _spawn_milestones(business_id, obj_id, spawns.get("milestones") or [])

    # Backfill the linked ids onto the objective.
    sb_clients.sb_patch_as_service(
        f"/growth_objectives?id=eq.{obj_id}",
        {"linked_module_ids": module_ids, "linked_workflow_ids": workflow_ids},
    )

    spawn_report = {
        "modules_created": module_ids,
        "workflows_created": workflow_ids,
        "milestones_created": ms_count,
    }
    logger.info(f"growth objective {obj_id} biz={business_id} spawned {spawn_report}")
    return {"ok": True, "objective": {**objective,
            "linked_module_ids": module_ids, "linked_workflow_ids": workflow_ids},
            "spawn_report": spawn_report}


# ──────────────────────────────────────────────────────────────
# Reads + Chief context
# ──────────────────────────────────────────────────────────────

def list_objectives(business_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    q = f"/growth_objectives?business_id=eq.{business_id}&order=created_at.desc&select=*"
    if status:
        q += f"&status=eq.{status}"
    rows = sb_clients.sb_get_as_service(q)
    return rows if isinstance(rows, list) else []


def get_objective(objective_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/growth_objectives?id=eq.{objective_id}&select=*&limit=1") or []
    return rows[0] if rows else None


def growth_context_block(business_id: str) -> str:
    """Markdown summary of ACTIVE growth objectives, injected into the Chief
    context every turn so the Growth Partner stays anchored to commitments.
    Returns "" when there are no active/at-risk objectives."""
    try:
        objs = [o for o in list_objectives(business_id)
                if o.get("status") in ("active", "at_risk", "proposed")]
    except Exception as e:
        logger.warning(f"growth_context_block failed: {e}")
        return ""
    if not objs:
        return ""
    lines = ["## Growth Objectives"]
    for o in objs[:6]:
        metric = (o.get("metrics") or {})
        target = metric.get("target")
        tline = f" — target: {target}" if target else ""
        td = f" (by {o['target_date']})" if o.get("target_date") else ""
        lines.append(f"- [{o.get('status')}] **{o.get('title')}**{tline}{td}")
    lines.append(
        "Speak as the Growth Partner: track these toward their targets, "
        "surface at-risk ones, and propose the next concrete move."
    )
    return "\n".join(lines)
