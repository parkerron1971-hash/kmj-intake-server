"""
workflow_engine.py — Living Growth System Phase 3: the workflow engine.

The verbs of the Living Growth System. A workflow_definition is
{trigger, steps[]}; when a matching event fires we enqueue a workflow_run,
and a scan tick drains runs step-by-step.

LOCKED RULINGS honored:
  Fork 11  async execution via queue + scan-tick drain (NOT inline on the request)
  Fork 13  workflow_runs IS the durable queue (NOT agent_queue, which is comms-only)
  Fork 17  confirmation gate reuses the notification /act pattern — a step with
           requires_confirmation pauses the run at awaiting_confirmation
  Fork 18  global templates clone to the business on spawn
  Fork 19  run idempotency_key derives from the provider event id, so duplicate
           webhook deliveries collapse to one run (skipped_duplicate)

STEP DISPATCH — three kinds of step.action:
  1. internal op   — a key in STEP_HANDLERS (log / update_context / emit_event /
                     create_module_entry / create_milestone). Fully self-contained.
  2. connector op  — 'connector.<verb>'. Routes through the GENERIC connector seam
                     (connector_dispatch): looks up the connector, writes an
                     idempotent connector_action_log row, dispatches to
                     CONNECTOR_PROVIDERS. **The provider registry is intentionally
                     EMPTY** — no LearnWorlds-instance code here (that is its own
                     slice with its own client constraints). An unregistered
                     provider records 'skipped_no_provider' and the run continues.
  3. chief action  — any other key falls back to chief_of_staff.ACTION_HANDLERS
                     (lazy import) so workflows reuse Chief's existing verbs.

Server-side, service-role (no user JWT in a cron/scan context). RLS-safe.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("workflow_engine")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] workflow: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)
DRAIN_BATCH = 25  # runs processed per scan tick


# ──────────────────────────────────────────────────────────────
# Service-role REST (server-initiated; bypasses RLS by design)
# ──────────────────────────────────────────────────────────────

def _su() -> str:
    return (os.environ.get("SUPABASE_URL") or "").rstrip("/")


def _service_key() -> str:
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def _headers(prefer: Optional[str] = None) -> Dict[str, str]:
    h = {
        "apikey": _service_key(),
        "Authorization": f"Bearer {_service_key()}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


async def _sb(client: httpx.AsyncClient, method: str, path: str,
              body: Any = None, prefer: Optional[str] = None) -> Tuple[int, Any]:
    """Returns (status_code, parsed_json_or_None). Caller inspects status so
    idempotency-key unique violations (409) are distinguishable from errors."""
    try:
        r = await client.request(
            method, f"{_su()}/rest/v1{path}",
            headers=_headers(prefer),
            content=json.dumps(body) if body is not None else None,
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as e:
        logger.warning(f"sb {method} {path} transport error: {e}")
        return 0, None
    parsed = None
    if r.text:
        try:
            parsed = r.json()
        except ValueError:
            parsed = None
    if r.status_code >= 400 and r.status_code != 409:
        logger.warning(f"sb {method} {path}: {r.status_code} {r.text[:200]}")
    return r.status_code, parsed


# ──────────────────────────────────────────────────────────────
# Trigger matching + enqueue
# ──────────────────────────────────────────────────────────────

def _conditions_match(conditions: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    """Shallow equality match of trigger.conditions against the event payload.
    Empty conditions always match. Supports {field: value} (==) — deeper
    operators are a later refinement; keep the contract narrow + predictable."""
    if not conditions:
        return True
    for k, v in conditions.items():
        if payload.get(k) != v:
            return False
    return True


async def find_matching_workflows(client: httpx.AsyncClient, business_id: str,
                                  event_type: str) -> List[Dict[str, Any]]:
    """Enabled workflow_definitions for this business whose trigger.event_type
    matches. Business-scoped definitions only (global templates are cloned to
    the business at spawn time — Fork 18 — so by the time an event fires the
    business already owns its copy)."""
    status, rows = await _sb(
        client, "GET",
        f"/workflow_definitions?business_id=eq.{business_id}&enabled=eq.true"
        f"&trigger->>event_type=eq.{event_type}&select=*",
    )
    return rows if isinstance(rows, list) else []


async def enqueue_run(client: httpx.AsyncClient, workflow: Dict[str, Any],
                      business_id: str, idempotency_key: str,
                      trigger_event_id: Optional[str] = None,
                      trigger_ref: Optional[Dict[str, Any]] = None,
                      growth_objective_id: Optional[str] = None) -> Dict[str, Any]:
    """Create a pending workflow_run. Idempotent: a unique violation on
    (workflow_id, idempotency_key) means a duplicate trigger — we return
    {status: 'skipped_duplicate'} instead of double-running (Fork 19)."""
    steps = workflow.get("steps") or []
    body = {
        "workflow_id": workflow["id"],
        "business_id": business_id,
        "status": "pending",
        "trigger_event_id": trigger_event_id,
        "trigger_ref": trigger_ref or {},
        "context": {},
        "step_cursor": 0,
        "steps_total": len(steps),
        "idempotency_key": idempotency_key,
        "log": [],
    }
    if growth_objective_id:
        body["growth_objective_id"] = growth_objective_id
    code, row = await _sb(client, "POST", "/workflow_runs", body,
                          prefer="return=representation")
    if code == 409:
        logger.info(f"run dedup: workflow={workflow['id']} key={idempotency_key}")
        return {"status": "skipped_duplicate", "idempotency_key": idempotency_key}
    if code >= 400 or not row:
        return {"status": "error", "error": f"enqueue failed ({code})"}
    created = row[0] if isinstance(row, list) and row else row
    return {"status": "enqueued", "run": created}


async def on_event(business_id: str, event_type: str,
                   event_id: Optional[str] = None,
                   payload: Optional[Dict[str, Any]] = None,
                   provider_event_id: Optional[str] = None) -> Dict[str, Any]:
    """Trigger entry point: an event fired for a business. Find matching
    enabled workflows + enqueue a run for each. idempotency_key derives from
    the PROVIDER event id when present (Fork 19), else the internal event id."""
    payload = payload or {}
    out = {"enqueued": [], "skipped_duplicate": [], "no_match": True}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        workflows = await find_matching_workflows(client, business_id, event_type)
        if workflows:
            out["no_match"] = False
        for wf in workflows:
            if not _conditions_match((wf.get("trigger") or {}).get("conditions") or {}, payload):
                continue
            key_seed = provider_event_id or event_id or f"{event_type}:{int(time.time())}"
            idem = f"{wf.get('slug', wf['id'])}:{key_seed}"
            res = await enqueue_run(client, wf, business_id, idem,
                                    trigger_event_id=event_id, trigger_ref=payload)
            if res["status"] == "enqueued":
                out["enqueued"].append(wf.get("slug") or wf["id"])
            elif res["status"] == "skipped_duplicate":
                out["skipped_duplicate"].append(wf.get("slug") or wf["id"])
    return out


# ──────────────────────────────────────────────────────────────
# Internal step handlers (self-contained, no connector)
# ──────────────────────────────────────────────────────────────

async def _step_log(client, run, biz, step, ctx) -> Dict[str, Any]:
    return {"ok": True, "note": step.get("params", {}).get("message", "")}


async def _step_update_context(client, run, biz, step, ctx) -> Dict[str, Any]:
    ctx.update(step.get("params") or {})
    return {"ok": True, "context_keys": list((step.get("params") or {}).keys())}


async def _step_emit_event(client, run, biz, step, ctx) -> Dict[str, Any]:
    p = step.get("params") or {}
    code, row = await _sb(client, "POST", "/events", {
        "business_id": run["business_id"],
        "event_type": p.get("event_type", "workflow.step"),
        "data": {**(p.get("data") or {}), "_workflow_run_id": run["id"]},
        "source": "workflow_engine",
    }, prefer="return=representation")
    return {"ok": code < 400, "status": code}


async def _step_create_module_entry(client, run, biz, step, ctx) -> Dict[str, Any]:
    """Insert a module_entries row. REFUSES access-restricted modules (mirrors
    chief_of_staff guard) — restricted modules are written ONLY through the
    locked /restricted-modules endpoints, never via a workflow step."""
    p = step.get("params") or {}
    module_id = p.get("module_id") or ctx.get("module_id")
    if not module_id:
        return {"ok": False, "error": "no module_id"}
    code, mod = await _sb(client, "GET",
                          f"/custom_modules?id=eq.{module_id}&select=agent_config&limit=1")
    access = None
    if isinstance(mod, list) and mod:
        access = (mod[0].get("agent_config") or {}).get("access_level")
    if access == "restricted":
        return {"ok": False, "error": "refused: access-restricted module"}
    code, row = await _sb(client, "POST", "/module_entries", {
        "module_id": module_id,
        "business_id": run["business_id"],
        "data": p.get("data") or {},
        "status": "active",
        "created_by": "workflow_engine",
        "source": "workflow_engine",
    }, prefer="return=representation")
    return {"ok": code < 400, "status": code}


async def _step_create_milestone(client, run, biz, step, ctx) -> Dict[str, Any]:
    """Create a growth_milestone, optionally linked to this run (Phase 4/5)."""
    p = step.get("params") or {}
    obj_id = p.get("objective_id") or run.get("growth_objective_id")
    if not obj_id:
        return {"ok": False, "error": "no objective_id"}
    code, row = await _sb(client, "POST", "/growth_milestones", {
        "objective_id": obj_id,
        "business_id": run["business_id"],
        "title": p.get("title", "Milestone"),
        "due_date": p.get("due_date"),
        "source": "system",
        "order_index": p.get("order_index", 0),
        "linked_workflow_run_id": run["id"],
    }, prefer="return=representation")
    return {"ok": code < 400, "status": code}


STEP_HANDLERS: Dict[str, Callable] = {
    "log": _step_log,
    "update_context": _step_update_context,
    "emit_event": _step_emit_event,
    "create_module_entry": _step_create_module_entry,
    "create_milestone": _step_create_milestone,
}


# ──────────────────────────────────────────────────────────────
# Generic connector seam (NO provider-instance code — Fork stop point)
# ──────────────────────────────────────────────────────────────

# Provider handlers register here as their own slices (e.g. LearnWorlds).
# Intentionally EMPTY in this build — the engine ships the abstraction, not
# any instance. An unregistered provider is a no-op that records the intent.
CONNECTOR_PROVIDERS: Dict[str, Callable] = {}


async def connector_dispatch(client, run, biz, verb: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Generic connector step. Looks up the business's connector for the
    provider, writes an IDEMPOTENT connector_action_log row, then dispatches
    to CONNECTOR_PROVIDERS[provider]. With no provider registered (this build),
    records 'skipped_no_provider' and returns ok so the run isn't blocked —
    the real provider slice fills in later without touching this engine."""
    provider = params.get("provider")
    connector_id = None
    code, conns = await _sb(client, "GET",
        f"/connectors?business_id=eq.{run['business_id']}&provider=eq.{provider}"
        f"&status=eq.connected&select=id&limit=1")
    if isinstance(conns, list) and conns:
        connector_id = conns[0]["id"]

    if not connector_id:
        return {"ok": True, "skipped": "no_connector", "provider": provider}

    idem = params.get("idempotency_key") or f"{run.get('id')}:{verb}:{run.get('step_cursor', 0)}"
    handler = CONNECTOR_PROVIDERS.get(provider)

    if not handler:
        # Record the would-be action for audit; no external call made.
        await _sb(client, "POST", "/connector_action_log", {
            "connector_id": connector_id,
            "business_id": run["business_id"],
            "workflow_run_id": run["id"],
            "action": verb,
            "idempotency_key": idem,
            "request": params,
            "status": "skipped_duplicate" if False else "pending",
        }, prefer="return=minimal")
        return {"ok": True, "skipped": "no_provider", "provider": provider}
    # A registered provider would execute here (its own slice owns the call).
    return await handler(client, run, biz, connector_id, verb, params, idem)


# ──────────────────────────────────────────────────────────────
# Step execution + run advancement
# ──────────────────────────────────────────────────────────────

PAUSE = "__pause__"


async def execute_step(client, run, biz, step, ctx) -> Dict[str, Any]:
    """Run one step. Returns the step result dict, or {'pause': True} when a
    confirmation gate stops the run (Fork 17)."""
    action = step.get("action", "")

    # Confirmation gate: a step requiring confirmation pauses until the cursor
    # is listed in context._confirmed_steps (set by confirm_run).
    if step.get("requires_confirmation"):
        confirmed = (ctx.get("_confirmed_steps") or [])
        if run.get("step_cursor", 0) not in confirmed:
            return {"pause": True, "reason": "awaiting_confirmation"}

    if action.startswith("connector."):
        verb = action.split(".", 1)[1]
        return await connector_dispatch(client, run, biz, verb, step.get("params") or {})

    handler = STEP_HANDLERS.get(action)
    if handler:
        return await handler(client, run, biz, step, ctx)

    # Fall back to Chief's existing action verbs (lazy import to avoid cycle).
    # ACTION LEDGER (2026-08-03): one of six dispatchers into
    # ACTION_HANDLERS, and the last one running real business actions
    # with NO audit row anywhere — a workflow step could send, charge or
    # delete and leave no trace at all. Bulk is refused here for the same
    # reason as on the scheduler: a workflow step is unattended by
    # definition, and the registry holds that bulk is never
    # autonomy-eligible at any class.
    try:
        from chief_of_staff import ACTION_HANDLERS
        chief_handler = ACTION_HANDLERS.get(action)
        if chief_handler:
            # STAGE 3: the shared evaluator. A workflow step is unattended
            # by definition, so this is also where a regulated practice's
            # client-facing protection applies.
            authorized_by = "workflow"
            try:
                import policy_engine
                verdict = policy_engine.evaluate(
                    str(biz.get("id") or ""), verb=action, surface="workflow",
                    prompted=False, biz_row=biz)
                authorized_by = verdict.rule
                if not verdict.allowed:
                    return {"ok": False, "error": verdict.reason,
                            "policy": verdict.as_error()}
            except Exception as e:
                # FAIL CLOSED, matching chief_scheduler. Failing open
                # here silently disabled the three things the engine
                # blocks — including unattended client contact for a
                # regulated practice — whenever the check itself broke.
                logger.warning(f"policy check failed for {action!r}: {e}")
                return {"ok": False,
                        "error": "action safety check unavailable"}
            ok, err, res = True, None, None
            try:
                res = await chief_handler(
                    client, biz, {"type": action, **(step.get("params") or {})})
                ok = (res or {}).get("failed") is not True
            except Exception as e:
                ok, err = False, str(e)
            try:
                import audit_log
                audit_log.record(
                    str(biz.get("id") or ""), actor_type="system",
                    actor_id="workflow", verb=action, ok=ok, error=err,
                    summary=str(step.get("label") or action)[:240],
                    payload={"workflow_run_id": str(run.get("id") or "")},
                    result=res, source="workflow", authorized_by=authorized_by)
            except Exception:
                pass
            if err:
                return {"ok": False, "error": err}
            return {"ok": True, "chief_result": res}
    except Exception as e:
        logger.warning(f"chief handler fallback failed for {action!r}: {e}")
    return {"ok": False, "error": f"unknown step action: {action!r}"}


async def advance_run(client, run: Dict[str, Any]) -> Dict[str, Any]:
    """Advance a run through its steps from step_cursor. Persists progress after
    each step. Stops on: completion (done), confirmation gate (awaiting_confirmation),
    or step failure (failed). Returns the final run status."""
    wf_code, wf = await _sb(client, "GET",
        f"/workflow_definitions?id=eq.{run['workflow_id']}&select=steps&limit=1")
    steps = (wf[0].get("steps") if isinstance(wf, list) and wf else None) or []
    if not steps:
        await _patch_run(client, run["id"], {"status": "done",
                         "completed_at": _now(), "error": "no steps"})
        return {"status": "done", "note": "no steps"}

    # Load biz once (Chief handlers + some steps want the row).
    bc, biz_rows = await _sb(client, "GET",
        f"/businesses?id=eq.{run['business_id']}&select=*&limit=1")
    # A stub row here disabled the regulated-vertical gate: policy_engine
    # trusts any dict carrying an id, and a stub has no `type`, so a
    # therapy practice read as unregulated. Fail the run instead.
    biz = biz_rows[0] if isinstance(biz_rows, list) and biz_rows else None
    if not biz:
        return {"ok": False, "error": "business unavailable"}

    ctx = dict(run.get("context") or {})
    log = list(run.get("log") or [])
    cursor = run.get("step_cursor", 0)

    await _patch_run(client, run["id"], {"status": "running"})

    while cursor < len(steps):
        step = steps[cursor]
        run_view = {**run, "step_cursor": cursor, "context": ctx}
        result = await execute_step(client, run_view, biz, step, ctx)

        if result.get("pause"):
            await _patch_run(client, run["id"], {
                "status": "awaiting_confirmation", "step_cursor": cursor,
                "context": ctx, "log": log,
            })
            return {"status": "awaiting_confirmation", "step": cursor}

        log.append({"step": cursor, "action": step.get("action"),
                    "result": result, "at": _now()})

        if not result.get("ok", False):
            await _patch_run(client, run["id"], {
                "status": "failed", "step_cursor": cursor, "context": ctx,
                "log": log, "error": result.get("error", "step failed"),
            })
            return {"status": "failed", "step": cursor, "error": result.get("error")}

        cursor += 1
        await _patch_run(client, run["id"], {"step_cursor": cursor,
                         "context": ctx, "log": log})

    await _patch_run(client, run["id"], {"status": "done", "step_cursor": cursor,
                     "context": ctx, "log": log, "completed_at": _now()})
    return {"status": "done", "steps_run": cursor}


async def _patch_run(client, run_id: str, body: Dict[str, Any]) -> None:
    await _sb(client, "PATCH", f"/workflow_runs?id=eq.{run_id}", body)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ──────────────────────────────────────────────────────────────
# Scan tick (the drain) + confirmation resume
# ──────────────────────────────────────────────────────────────

async def drain_tick(limit: int = DRAIN_BATCH) -> Dict[str, Any]:
    """One scan tick: pick up pending/running runs and advance each. Called by
    a Railway cron (Fork 7) — never a frontend heartbeat for money paths.
    awaiting_confirmation runs are skipped until confirmed."""
    report = {"advanced": 0, "done": 0, "failed": 0, "awaiting": 0}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        code, runs = await _sb(client, "GET",
            f"/workflow_runs?status=in.(pending,running)"
            f"&order=created_at.asc&limit={limit}&select=*")
        if not isinstance(runs, list):
            return report
        for run in runs:
            try:
                res = await advance_run(client, run)
                report["advanced"] += 1
                st = res.get("status")
                if st == "done":
                    report["done"] += 1
                elif st == "failed":
                    report["failed"] += 1
                elif st == "awaiting_confirmation":
                    report["awaiting"] += 1
            except Exception as e:
                logger.exception(f"drain advance failed for run {run.get('id')}: {e}")
    return report


async def confirm_run(run_id: str, confirmed_by: str) -> Dict[str, Any]:
    """Resume an awaiting_confirmation run: mark the paused step's cursor as
    confirmed in context and flip status back to running so the next drain
    tick advances it (Fork 17 — reuses the notification /act confirmation)."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        code, rows = await _sb(client, "GET",
            f"/workflow_runs?id=eq.{run_id}&select=*&limit=1")
        if not isinstance(rows, list) or not rows:
            return {"ok": False, "error": "run not found"}
        run = rows[0]
        if run.get("status") != "awaiting_confirmation":
            return {"ok": False, "error": f"run not awaiting confirmation (status={run.get('status')})"}
        ctx = dict(run.get("context") or {})
        confirmed = list(ctx.get("_confirmed_steps") or [])
        if run.get("step_cursor", 0) not in confirmed:
            confirmed.append(run.get("step_cursor", 0))
        ctx["_confirmed_steps"] = confirmed
        ctx["_confirmed_by"] = confirmed_by
        await _patch_run(client, run_id, {"status": "running", "context": ctx})
        return {"ok": True, "run_id": run_id, "resumed_at_step": run.get("step_cursor", 0)}
