# chief_jobs.py
# ═══════════════════════════════════════════════════════════════════════
# Feature 2 (cross-device Chief) — queued desk jobs.
#
# From the phone you tell Chief to start something heavy ("rebuild my
# site"); Chief enqueues a job (chief_jobs row), returns immediately, and
# the job runs server-side. On completion it writes a chief_activity row
# (source='system') so the desktop's "while you were away" recap announces
# "your site rebuild is ready" — the work is finished and waiting when you
# sit down.
#
# Execution model: in-process. enqueue() inserts the row and kicks an
# asyncio task; the task clears the request's user JWT (→ service role),
# marks the job running, runs the heavy work in a worker THREAD (so the
# event loop isn't blocked by sync compose/LLM calls), then records the
# outcome + the recap notice. All DB access here is SERVICE ROLE; the
# user-facing read endpoint filters by the verified caller's user_id.
# ═══════════════════════════════════════════════════════════════════════

import os
import json
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import UserSession, require_user_session

logger = logging.getLogger("chief_jobs")
router = APIRouter(prefix="/agents/chief", tags=["chief-jobs"])

HTTP_TIMEOUT = 180.0


def _url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _service_key() -> str:
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _sb(client: httpx.AsyncClient, method: str, path: str, body=None):
    """Service-role PostgREST call. The runner writes any user's rows and
    bypasses RLS; the read endpoint adds an explicit user_id filter."""
    key = _service_key()
    url = f"{_url()}/rest/v1{path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    resp = await client.request(
        method, url, headers=headers,
        content=json.dumps(body) if body is not None else None,
        timeout=HTTP_TIMEOUT,
    )
    if resp.status_code >= 400:
        logger.error(f"chief_jobs Supabase {method} {path}: {resp.status_code} {resp.text[:300]}")
        return None
    return json.loads(resp.text) if resp.text else None


# ─── Job kinds ─────────────────────────────────────────────────────────
# Extensible registry — add monthly_report / reconcile_month here later;
# the runner + endpoints + frontend are kind-agnostic.
KIND_META: Dict[str, Dict[str, Any]] = {
    "rebuild_site": {
        "label": "Site rebuild",
        "working": "rebuilding your site",
        "done": "your site is ready",
        "nav": "build:mysite",
    },
    # Arc 6 "Creative Engine" — three candidate design directions
    # (3× DRO author + 3× copy pass ≈ 60-120s; always a background job).
    "compose_directions": {
        "label": "Design directions",
        "working": "designing three directions for your site",
        "done": "three design directions are ready — pick one",
        "nav": "build:mysite",
    },
    # Site Arc 11 — the resident creator: revise ONE section of the
    # composed site under the owner's instruction (one atelier call +
    # deterministic re-render ≈ 30-90s). An unrefinable ask completes
    # with result {ok: false, error} — honest, never a crashed job.
    "refine_section": {
        "label": "Section refine",
        "working": "reworking that section",
        "done": "your section rework is ready",
        "nav": "build:mysite",
    },
}


# ─── Progress reporting (Arc 10 "wow" — the loading bar) ──────────────
# While a job is `running`, stage boundaries PATCH the job row's `result`
# field with {"progress": {"pct": N, "stage": "..."}} — no migration:
# `result` is unused until the completion PATCH overwrites it, and the
# existing frontend pollers already fetch the row (they read
# job.result.progress while status == 'running').
_PROGRESS_MIN_INTERVAL_S = 1.5   # throttle: skip pings closer than this…
_PROGRESS_MIN_JUMP = 15          # …unless the pct jumped at least this much


def _make_progress_cb(job_id: str):
    """Build the synchronous progress(pct, stage) reporter for one job.

    Runs INSIDE the worker thread, so it uses the sync service-role
    client (sb_clients.sb_patch_as_service), never the async _sb.
    Fail-soft by construction: any error is swallowed — a progress ping
    must never break the compose. pct is clamped 0..100 and kept
    monotonic (a self-heal re-render never walks the bar backwards)."""
    state = {"t": 0.0, "pct": -1}

    def progress(pct: Any, stage: Any) -> None:
        try:
            p = max(0, min(100, int(pct)))
            p = max(p, state["pct"])          # monotonic — never backwards
            now = time.monotonic()
            if (p < 100
                    and (now - state["t"]) < _PROGRESS_MIN_INTERVAL_S
                    and (p - state["pct"]) < _PROGRESS_MIN_JUMP):
                return                        # throttled
            state["t"] = now
            state["pct"] = p
            sb_clients.sb_patch_as_service(
                f"/chief_jobs?id=eq.{job_id}",
                {"result": {"progress": {"pct": p, "stage": str(stage)[:140]}}})
        except Exception as e:
            logger.debug(f"[chief_jobs] progress ping skipped for {job_id}: {e}")

    return progress


def _execute_kind(kind: str, business_id: str, params: dict,
                  job_id: Optional[str] = None) -> dict:
    """SYNC heavy work, run in a worker thread so the event loop stays free.
    Returns a JSON-serializable result dict. Raises on failure."""
    progress = _make_progress_cb(job_id) if job_id else None
    if kind == "rebuild_site":
        # Lazy import — avoids any import-time cost/cycles at module load.
        # compose_site (DRL PR3) authors the Design Rationale Object first,
        # then composes concept-threaded copy that obeys it.
        from site_composer import compose_site
        notes = (params or {}).get("brief_notes") or ""
        # Arc 2 "Ask the Owner": compose_site sanitizes + persists the prefs
        # to businesses.settings.site_prefs before composing; when absent it
        # reuses the stored site_prefs automatically.
        result = compose_site(business_id, brief_notes=notes, use_llm=True,
                              design_prefs=(params or {}).get("design_prefs"),
                              progress_cb=progress,
                              # Refine mode: keep the current design
                              # direction, regenerate the execution.
                              refine=bool((params or {}).get("refine")))
        return result if isinstance(result, dict) else {}
    if kind == "compose_directions":
        # Arc 6 — authors + stores the three direction drafts; the result
        # carries the directions list (draft_id/stance/label/summary/
        # tagline). The frontend then GETs /composer/directions/{biz} for
        # preview tokens.
        from site_composer import compose_directions
        result = compose_directions(
            business_id, design_prefs=(params or {}).get("design_prefs"),
            progress_cb=progress)
        return result if isinstance(result, dict) else {}
    if kind == "refine_section":
        # Site Arc 11 — refine ONE section under the owner's instruction.
        # refine_section returns {ok: false, error} on an unrefinable ask
        # (validator failure, unknown section, no composed page) — that is
        # a COMPLETED job with an honest result, not an exception.
        from site_composer import refine_section
        result = refine_section(
            business_id,
            section=str((params or {}).get("section") or ""),
            instruction=str((params or {}).get("instruction") or ""),
            progress_cb=progress)
        return result if isinstance(result, dict) else {}
    raise ValueError(f"unknown job kind: {kind}")


# ─── Runner ────────────────────────────────────────────────────────────
async def _run(job_id: str, user_id: str, business_id: str, kind: str, params: dict) -> None:
    # Background task: it inherited the request's JWT contextvar via
    # create_task's context copy — neutralize it so DB access is service role.
    sb_clients.clear_user_jwt()
    meta = KIND_META.get(kind, {"label": kind, "done": "done", "nav": None})
    async with httpx.AsyncClient() as client:
        await _sb(client, "PATCH", f"/chief_jobs?id=eq.{job_id}",
                  {"status": "running", "started_at": _now()})
        try:
            result = await asyncio.to_thread(_execute_kind, kind, business_id,
                                             params, job_id)
            await _sb(client, "PATCH", f"/chief_jobs?id=eq.{job_id}",
                      {"status": "done", "result": result, "finished_at": _now()})
            # Honest recap (Site Arc 11): a job that COMPLETED with an
            # ok:false result (e.g. an unrefinable refine ask) announces
            # its error, not the success line. Kinds without an "ok" key
            # keep the success summary unchanged.
            _done_summary = meta.get("done", "done")
            if isinstance(result, dict) and result.get("ok") is False:
                _done_summary = str(result.get("error")
                                    or "couldn't finish — try again")[:140]
            await _sb(client, "POST", "/chief_activity", [{
                "user_id": user_id, "business_id": business_id, "source": "system",
                "action_type": f"job:{kind}", "label": meta["label"],
                "summary": _done_summary, "nav": meta.get("nav"),
            }])
        except Exception as e:
            logger.exception(f"[chief_jobs] job {job_id} ({kind}) failed")
            await _sb(client, "PATCH", f"/chief_jobs?id=eq.{job_id}",
                      {"status": "failed", "error": str(e)[:500], "finished_at": _now()})
            await _sb(client, "POST", "/chief_activity", [{
                "user_id": user_id, "business_id": business_id, "source": "system",
                "action_type": f"job:{kind}", "label": meta["label"],
                "summary": "couldn't finish — tap to retry", "nav": meta.get("nav"),
            }])


async def enqueue(client: httpx.AsyncClient, *, user_id: str, business_id: str,
                  kind: str, params: Optional[dict] = None,
                  source: str = "desktop") -> Optional[dict]:
    """Insert a queued job and kick off its runner. Returns the job row.
    Raises ValueError for an unknown kind.

    Server-side dedupe: when a FRESH job of the same kind for the same
    business is already queued/running, the EXISTING row is returned (with
    "deduped": True riding along) instead of enqueuing a second compose —
    callers treat it identically to a fresh enqueue.

    Stale-job recovery: jobs run in-process (asyncio.create_task), so a
    deploy/restart mid-run leaves rows stuck at queued/running forever.
    Without a cutoff, dedupe would then pin every future enqueue to that
    corpse — the business could never compose again. Any same-kind row
    older than STALE_AFTER_MIN is marked failed here and a new job starts."""
    if kind not in KIND_META:
        raise ValueError(f"unknown job kind: {kind}")
    STALE_AFTER_MIN = 10
    existing = await _sb(
        client, "GET",
        f"/chief_jobs?business_id=eq.{business_id}&kind=eq.{kind}"
        "&status=in.(queued,running)&select=*&order=created_at.desc&limit=5")
    now = datetime.now(timezone.utc)
    fresh: Optional[dict] = None
    for row in (existing if isinstance(existing, list) else []):
        started = row.get("started_at") or row.get("created_at") or ""
        try:
            age_min = (now - datetime.fromisoformat(
                str(started).replace("Z", "+00:00"))).total_seconds() / 60
        except Exception:
            age_min = STALE_AFTER_MIN + 1  # unparseable → treat as stale
        if age_min <= STALE_AFTER_MIN:
            fresh = fresh or row
        else:
            logger.warning(f"[chief_jobs] sweeping stale {row.get('status')} "
                           f"{kind} job {row.get('id')} ({age_min:.0f}min old) "
                           f"for {business_id[:8]} — likely orphaned by a restart")
            await _sb(client, "PATCH", f"/chief_jobs?id=eq.{row['id']}", {
                "status": "failed",
                "error": "interrupted by a server restart — safe to retry",
                "finished_at": now.isoformat(),
            })
    if fresh:
        logger.info(f"[chief_jobs] dedupe: {kind} already "
                    f"{fresh.get('status')} for {business_id[:8]} — "
                    f"returning job {fresh.get('id')}")
        return {**fresh, "deduped": True}
    rows = await _sb(client, "POST", "/chief_jobs", [{
        "user_id": user_id, "business_id": business_id, "kind": kind,
        "status": "queued", "source": source, "params": params or {},
    }])
    job = rows[0] if isinstance(rows, list) and rows else None
    if not job:
        return None
    asyncio.create_task(_run(job["id"], user_id, business_id, kind, params or {}))
    return job


# ─── Endpoints ─────────────────────────────────────────────────────────
@router.get("/jobs")
async def list_jobs(
    business_id: Optional[str] = None,
    active: bool = True,
    limit: int = 10,
    user_session: UserSession = Depends(require_user_session),
):
    """In-progress (and recent) jobs for the caller — powers the desktop
    "Chief is working on…" chip. Service role + explicit user_id filter."""
    uid = getattr(getattr(user_session, "user", None), "id", None)
    if not uid:
        return {"jobs": []}
    q = (f"/chief_jobs?user_id=eq.{uid}"
         "&select=id,kind,status,error,result,created_at,started_at,finished_at"
         f"&order=created_at.desc&limit={max(1, min(int(limit or 10), 50))}")
    if active:
        q += "&status=in.(queued,running)"
    if business_id:
        q += f"&business_id=eq.{business_id}"
    async with httpx.AsyncClient() as client:
        rows = await _sb(client, "GET", q)
    out = []
    for r in (rows or []):
        m = KIND_META.get(r.get("kind"), {})
        out.append({**r, "working": m.get("working", "working on it"),
                    "label": m.get("label", r.get("kind"))})
    return {"jobs": out}


class _RetryReq(BaseModel):
    job_id: str


class _RebuildReq(BaseModel):
    business_id: str
    brief_notes: Optional[str] = None
    design_prefs: Optional[Dict[str, Any]] = None   # Arc 2 "Ask the Owner"


@router.post("/jobs/rebuild")
async def rebuild_site_endpoint(req: _RebuildReq,
                                user_session: UserSession = Depends(require_user_session)):
    """Enqueue a site rebuild as a BACKGROUND job (the canonical build path).
    Used by MySite + the Composer panel so a build never blocks/times out —
    it runs server-side and the desktop recap announces completion. Ownership
    is verified before enqueuing."""
    uid = getattr(getattr(user_session, "user", None), "id", None)
    if not uid:
        raise HTTPException(401, "auth required")
    async with httpx.AsyncClient() as client:
        owned = await _sb(client, "GET",
                          f"/businesses?id=eq.{req.business_id}&owner_id=eq.{uid}&select=id&limit=1")
        if not owned:
            raise HTTPException(403, "not your business")
        params: Dict[str, Any] = {}
        if (req.brief_notes or "").strip():
            params["brief_notes"] = req.brief_notes
        if req.design_prefs is not None:
            # Lenient shape validation at the door (unknown keys dropped,
            # strings trimmed/capped, enums clamped) so the stored job params
            # are already clean. Lazy import — same pattern as _execute_kind.
            from site_composer import sanitize_design_prefs
            prefs = sanitize_design_prefs(req.design_prefs)
            if prefs:
                params["design_prefs"] = prefs
        job = await enqueue(client, user_id=uid, business_id=req.business_id,
                            kind="rebuild_site", params=params, source="desktop")
    out = {"ok": True, "job_id": (job or {}).get("id")}
    if (job or {}).get("deduped"):
        out["deduped"] = True
    return out


@router.post("/jobs/retry")
async def retry_job(req: _RetryReq, user_session: UserSession = Depends(require_user_session)):
    """Re-queue a failed job. Ownership verified before re-running."""
    uid = getattr(getattr(user_session, "user", None), "id", None)
    if not uid:
        raise HTTPException(401, "auth required")
    async with httpx.AsyncClient() as client:
        rows = await _sb(client, "GET",
                         f"/chief_jobs?id=eq.{req.job_id}&user_id=eq.{uid}&select=*")
        job = rows[0] if isinstance(rows, list) and rows else None
        if not job:
            raise HTTPException(404, "job not found")
        await _sb(client, "PATCH", f"/chief_jobs?id=eq.{req.job_id}",
                  {"status": "queued", "error": None, "started_at": None, "finished_at": None})
    asyncio.create_task(_run(job["id"], uid, job["business_id"], job["kind"], job.get("params") or {}))
    return {"ok": True}
