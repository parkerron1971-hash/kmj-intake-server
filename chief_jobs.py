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
from business_access import business_access

logger = logging.getLogger("chief_jobs")
router = APIRouter(prefix="/agents/chief", tags=["chief-jobs"])

HTTP_TIMEOUT = 180.0

# Job ids whose runner is alive IN THIS PROCESS.
#
# Site-builder audit (2026-08-13): the stale sweep existed to clear rows
# orphaned by a deploy — jobs run in-process, so a restart leaves them
# stuck at queued/running forever. But it decided "orphaned" purely by
# age, and a full Opus build genuinely approaches the 10-minute mark.
# A slow-but-alive build was therefore marked failed while its thread
# kept running, which (a) told the practitioner their build had died and
# (b) freed the dedupe slot so the retry started a SECOND build over the
# first — two threads writing the same site row and two 600-credit
# markers.
#
# Age cannot tell the two apart. Process identity can: a row orphaned by
# a restart belongs to a process that no longer exists, so its id cannot
# be in this set. Anything in here is slow, not dead, and is never swept.
_INFLIGHT: set = set()


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
    # 2026-08-09 — THE BLUEPRINT. The longest single LLM call the product
    # makes (a live draft ran 30.6k in / 7.8k out) and it used to sit on a
    # synchronous request, so the browser gave up while the server happily
    # finished and charged for it. Same road as rebuild_site now: the job
    # outlives the tab, and the desktop recap announces it.
    "author_spec": {
        "label": "Blueprint",
        "working": "drafting your design blueprint",
        "done": "your blueprint is ready to read",
        "nav": "build:mysite",
    },
    "revise_spec": {
        "label": "Blueprint revision",
        "working": "revising your design blueprint",
        "done": "your revised blueprint is ready",
        "nav": "build:mysite",
    },
    # THE BROWSER HAND (2026-09-04). Starts from an approved proposal
    # (_do_approve_one, channel "hand"), never from a click or a chat
    # turn directly. Bounded by browser_hand.run's own budgets; the
    # heartbeat and orphan sweep cover a deploy mid-run.
    "browser_hand": {
        "label": "Browser hand",
        "working": "working through that site",
        "done": "the hand finished — see what it found",
        "nav": "operate:queue",
    },
    # THE SITE CHECK (2026-09-04, site_check.py). Chief's check_site verb
    # and the post-deploy hook both land here. Screenshots + findings are
    # filed on the site row; site_health reads them back.
    "site_check": {
        "label": "Site check",
        "working": "looking over the live site",
        "done": "site check finished — ask for site health to read it",
        "nav": "build",
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


# ─── Heartbeat + recovery (2026-09-04) ────────────────────────────────
#
# The only recovery for a job orphaned by a deploy was LAZY: the next
# enqueue of the same kind for the same business swept it (see
# enqueue). Until that happened the practitioner's "Chief is working
# on…" chip spun forever on a corpse, and nothing else ever looked.
#
# Two pieces close it. A HEARTBEAT: the progress callback already
# PATCHes the row every ~1.5s while the build is alive; it now stamps
# heartbeat_at too, which is what lets a sweep tell "slow on another
# replica" from "dead" — the thing age alone cannot (a full Opus build
# approaches ten minutes) and process identity (_INFLIGHT) cannot across
# processes. And two SWEEPS that share one rule: at boot, and every few
# minutes on the scheduler leader.
#
# NO AUTO-RETRY, deliberately. Every job kind is a paid model build
# (rebuild_site writes a 600-credit marker; author_spec is the largest
# single call the product makes, and the reason it became a job was a
# timeout that charged twice). A swept row is marked failed with the
# retryable reason the retry button already understands; the human
# presses it. An automatic retry here re-creates the double-build money
# bug the 2026-08-13 audit closed.

# A `running` row whose last heartbeat is older than this is dead.
HEARTBEAT_STALE_MIN = 5
# Without the heartbeat column (migration not applied yet), fall back to
# started_at with the older, longer threshold enqueue already uses.
STARTED_STALE_MIN = 10
INTERRUPTED_REASON = "interrupted by a server restart — safe to retry"

# Flips to False after the first refused heartbeat PATCH (column not
# migrated yet), so a missing column costs one warning, not one failed
# request per progress ping.
_HEARTBEAT_OK = True


def _stamp_heartbeat(job_id: str) -> None:
    global _HEARTBEAT_OK
    if not _HEARTBEAT_OK:
        return
    try:
        sb_clients.sb_patch_as_service(
            f"/chief_jobs?id=eq.{job_id}", {"heartbeat_at": _now()})
    except Exception as e:
        _HEARTBEAT_OK = False
        logger.warning(f"[chief_jobs] heartbeat disabled — column missing? "
                       f"apply APPLY-2026-09-04-chief-jobs-heartbeat.sql ({e})")


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
            # A SEPARATE patch so a not-yet-migrated column can never
            # take the progress bar down with it.
            _stamp_heartbeat(job_id)
        except Exception as e:
            logger.debug(f"[chief_jobs] progress ping skipped for {job_id}: {e}")

    return progress


def _age_min(stamp: Any, now: datetime) -> Optional[float]:
    if not stamp:
        return None
    try:
        return (now - datetime.fromisoformat(
            str(stamp).replace("Z", "+00:00"))).total_seconds() / 60
    except Exception:
        return None


def is_orphaned(row: Dict[str, Any], now: datetime, inflight: set) -> bool:
    """THE RULE, shared by the boot sweep and the tick. Pure.

    A live row is orphaned when nobody can vouch for it: not in THIS
    process's _INFLIGHT (that is the only kind of slow-but-alive we can
    see), and its heartbeat is stale — or, with no heartbeat on file,
    it started long enough ago that enqueue's own sweep would already
    have called it dead. A queued row that was never picked up gets the
    started_at rule on created_at.
    """
    if str(row.get("id")) in inflight:
        return False
    status = row.get("status")
    if status not in ("queued", "running"):
        return False
    hb = _age_min(row.get("heartbeat_at"), now)
    if hb is not None:
        return hb > HEARTBEAT_STALE_MIN
    started = _age_min(row.get("started_at") or row.get("created_at"), now)
    if started is None:
        return True          # unparseable → nobody can vouch for it
    return started > STARTED_STALE_MIN


def sweep_orphans(reason: str = "boot") -> int:
    """Mark every orphaned live row failed-with-a-retryable-reason.
    Sync (it runs from startup and from a scheduler thread), service
    role, never raises. Returns how many rows it swept."""
    try:
        rows = sb_clients.sb_get_as_service(
            "/chief_jobs?status=in.(queued,running)"
            "&select=id,status,started_at,created_at,heartbeat_at,kind,business_id"
            "&order=created_at.asc&limit=200") or []
    except Exception as e:
        # The heartbeat column may not exist yet; ask again without it.
        try:
            rows = sb_clients.sb_get_as_service(
                "/chief_jobs?status=in.(queued,running)"
                "&select=id,status,started_at,created_at,kind,business_id"
                "&order=created_at.asc&limit=200") or []
        except Exception as e2:
            logger.warning(f"[chief_jobs] orphan sweep ({reason}) could not read: {e2}")
            return 0
        logger.info(f"[chief_jobs] orphan sweep reading without heartbeat_at: {e}")
    if not isinstance(rows, list):
        return 0
    now = datetime.now(timezone.utc)
    swept = 0
    for row in rows:
        if not is_orphaned(row, now, _INFLIGHT):
            continue
        try:
            sb_clients.sb_patch_as_service(
                f"/chief_jobs?id=eq.{row['id']}&status=in.(queued,running)",
                {"status": "failed", "error": INTERRUPTED_REASON,
                 "finished_at": now.isoformat()})
            swept += 1
            logger.warning(f"[chief_jobs] {reason} sweep: {row.get('kind')} job "
                           f"{row.get('id')} for {str(row.get('business_id'))[:8]} "
                           f"was {row.get('status')} with nobody running it — "
                           f"marked failed, retryable")
        except Exception as e:
            logger.warning(f"[chief_jobs] {reason} sweep could not mark {row.get('id')}: {e}")
    return swept


async def recover_tick() -> None:
    """Scheduler tick (leader-gated by the caller): the same sweep,
    every few minutes, for the deploy that happened while nobody was
    enqueuing."""
    n = await asyncio.to_thread(sweep_orphans, "tick")
    if n:
        logger.info(f"[chief_jobs] recovery tick swept {n} orphaned job(s)")


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
    if kind in ("author_spec", "revise_spec"):
        # THE BLUEPRINT (2026-08-09). Text-only — never triggers a build,
        # never touches the composed page. author_spec_work returns
        # {ok: false, error} for the honest failures (nothing to revise,
        # notes missing, the author didn't answer, the save didn't land),
        # so those complete as jobs carrying their reason rather than
        # crashing — the practitioner needs to know whether they were
        # charged, and a stack trace can't tell them.
        from site_composer import author_spec_work
        result = author_spec_work(
            business_id,
            notes=str((params or {}).get("notes") or ""),
            revise=(kind == "revise_spec"),
            progress_cb=progress)
        return result if isinstance(result, dict) else {}
    if kind == "browser_hand":
        import browser_hand
        import event_spine
        spec = (params or {}).get("spec") or {}
        result = browser_hand.run(business_id, job_id or "run", spec, progress_cb=progress)
        if not result.get("ok"):
            # the recap reads `error` for an honest failure line
            result.setdefault("error", result.get("summary"))
        event_spine.emit("hand_run_completed", business_id, data={
            "job_id": job_id, "queue_id": (params or {}).get("queue_id"),
            "task": result.get("task"), "ok": bool(result.get("ok")),
            "stopped": result.get("stopped"), "summary": result.get("summary"),
            "frames": result.get("frames"), "steps": len(result.get("steps") or []),
        }, source="browser_hand")
        return result
    if kind == "site_check":
        import site_check
        p = params or {}
        result = site_check.run(
            business_id, reason=str(p.get("reason") or "chief"),
            vision=(p.get("vision") is None or bool(p.get("vision"))),
            progress_cb=progress)
        if not result.get("ok"):
            result.setdefault("error", result.get("summary"))
        else:
            # the recap line carries the count, not a generic "done"
            result["summary"] = result.get("summary")
        return result
    raise ValueError(f"unknown job kind: {kind}")


# ─── Runner ────────────────────────────────────────────────────────────
async def _run(job_id: str, user_id: str, business_id: str, kind: str, params: dict) -> None:
    # Background task: it inherited the request's JWT contextvar via
    # create_task's context copy — neutralize it so DB access is service role.
    sb_clients.clear_user_jwt()
    meta = KIND_META.get(kind, {"label": kind, "done": "done", "nav": None})
    # Claim the in-process slot for the whole life of the runner, so the
    # stale sweep can tell a slow build from one orphaned by a restart.
    _INFLIGHT.add(job_id)
    try:
        await _run_inner(job_id, user_id, business_id, kind, params, meta)
    finally:
        _INFLIGHT.discard(job_id)


async def _run_inner(job_id: str, user_id: str, business_id: str, kind: str,
                     params: dict, meta: dict) -> None:
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
            import audit_log
            await asyncio.to_thread(
                audit_log.record, business_id, actor_type="chief",
                actor_id=user_id, verb=f"job:{kind}"[:80],
                ok=not (isinstance(result, dict) and result.get("ok") is False),
                summary=_done_summary, source="system")
        except Exception as e:
            logger.exception(f"[chief_jobs] job {job_id} ({kind}) failed")
            await _sb(client, "PATCH", f"/chief_jobs?id=eq.{job_id}",
                      {"status": "failed", "error": str(e)[:500], "finished_at": _now()})
            await _sb(client, "POST", "/chief_activity", [{
                "user_id": user_id, "business_id": business_id, "source": "system",
                "action_type": f"job:{kind}", "label": meta["label"],
                "summary": "couldn't finish — tap to retry", "nav": meta.get("nav"),
            }])
            import audit_log
            await asyncio.to_thread(
                audit_log.record, business_id, actor_type="chief",
                actor_id=user_id, verb=f"job:{kind}"[:80], ok=False,
                error=str(e)[:500], summary=meta["label"], source="system")


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
        if age_min <= STALE_AFTER_MIN or str(row.get("id")) in _INFLIGHT:
            # Fresh, or old but demonstrably still running in this
            # process. Either way it is a live job: dedupe against it
            # instead of killing it and starting a second paid build.
            if str(row.get("id")) in _INFLIGHT and age_min > STALE_AFTER_MIN:
                logger.info(f"[chief_jobs] {kind} job {row.get('id')} is "
                            f"{age_min:.0f}min old but still running here — "
                            f"slow, not orphaned; not sweeping")
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
        # The read-above/insert-here pair is not atomic: two clicks
        # inside one round-trip both saw "nothing fresh". The partial
        # unique index (supabase/APPLY-2026-08-13-chief-jobs-single-
        # active.sql) is what actually holds the invariant, and it
        # rejects the loser with a unique violation. That loser must
        # return the winner's row — NOT None, which the callers surface
        # as "couldn't start your build" over a build that is in fact
        # running, and which invites the retry that starts a second one.
        raced = await _sb(
            client, "GET",
            f"/chief_jobs?business_id=eq.{business_id}&kind=eq.{kind}"
            "&status=in.(queued,running)&select=*&order=created_at.desc&limit=1")
        winner = raced[0] if isinstance(raced, list) and raced else None
        if winner:
            logger.info(f"[chief_jobs] enqueue raced for {business_id[:8]} "
                        f"{kind} — returning the winning job {winner.get('id')}")
            return {**winner, "deduped": True}
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


@router.get("/hand/runs")
async def hand_runs(
    business_id: str,
    limit: int = 10,
    user_session: UserSession = Depends(require_user_session),
    # Frames carry whatever a third-party site showed; a seat below
    # member does not get them. Same 404-for-both answer as every
    # guarded route (business_access), on top of the user_id filter.
    _biz: Dict[str, Any] = Depends(business_access("member")),
):
    """What the browser hand did, frame by frame (browser_hand.py). One
    entry per run the practitioner approved: the task, what stopped it,
    the summary, and every step with a signed link to the screen the
    hand saw before it acted. Links are minted here, per request, from
    the private bucket — nothing about a run is a public URL. Scoped by
    the caller's user id AND the business, like /jobs."""
    uid = getattr(getattr(user_session, "user", None), "id", None)
    if not uid:
        return {"runs": []}
    q = (f"/chief_jobs?user_id=eq.{uid}&business_id=eq.{business_id}"
         "&kind=eq.browser_hand"
         "&select=id,status,error,result,params,created_at,started_at,finished_at"
         f"&order=created_at.desc&limit={max(1, min(int(limit or 10), 50))}")
    async with httpx.AsyncClient() as client:
        rows = await _sb(client, "GET", q)
    import browser_hand
    import storage_links
    out = []
    for r in (rows or []):
        res = r.get("result") if isinstance(r.get("result"), dict) else {}
        params = r.get("params") if isinstance(r.get("params"), dict) else {}
        spec = params.get("spec") if isinstance(params.get("spec"), dict) else {}
        steps = []
        for s in (res.get("steps") or []):
            frame = s.get("frame")
            url = None
            if frame:
                try:
                    url = await asyncio.to_thread(
                        storage_links.signed_url_sync, browser_hand.FRAME_BUCKET, frame, ttl=3600)
                except Exception as e:
                    logger.warning(f"[hand] frame link failed for {r.get('id')}: {e}")
            steps.append({"n": s.get("n"), "url": s.get("url"), "action": s.get("action"),
                          "note": s.get("note"), "frame_url": url})
        out.append({
            "id": r.get("id"), "status": r.get("status"), "error": r.get("error"),
            "created_at": r.get("created_at"), "finished_at": r.get("finished_at"),
            "queue_id": params.get("queue_id"),
            "task": res.get("task") or spec.get("task"),
            "domains": res.get("domains") or spec.get("domains") or [],
            "stopped": res.get("stopped"), "ok": res.get("ok"),
            "summary": res.get("summary"), "frames": res.get("frames"),
            "steps": steps,
        })
    return {"runs": out}


class _RetryReq(BaseModel):
    job_id: str


class _RebuildReq(BaseModel):
    business_id: str
    brief_notes: Optional[str] = None
    design_prefs: Optional[Dict[str, Any]] = None   # Arc 2 "Ask the Owner"
    # Refine mode: reuse the stored design rationale (keep the current
    # direction, redo the execution) instead of rolling a new one.
    refine: bool = False


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
        # A hand-built site is code (site_adopt.py): composing over it
        # would be undone by the next deploy. The Studio hides its build
        # door for such a site; this is the same refusal at the endpoint.
        block = await asyncio.to_thread(_hand_built_block, req.business_id)
        if block:
            raise HTTPException(409, f"This site is hand-built: {block}")
        params: Dict[str, Any] = {}
        if req.refine:
            params["refine"] = True
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


def _hand_built_block(business_id: str) -> Optional[str]:
    try:
        import site_adopt
        return site_adopt.hand_built_block_for(business_id)
    except Exception:
        return None


class _SpecJobReq(BaseModel):
    business_id: str
    notes: Optional[str] = None      # owner's words; REQUIRED when revising
    revise: bool = False


@router.post("/jobs/spec")
async def author_spec_endpoint(req: _SpecJobReq,
                               user_session: UserSession = Depends(require_user_session)):
    """Enqueue blueprint authoring (or revision) as a BACKGROUND job.

    THE CANONICAL BLUEPRINT PATH (2026-08-09). The synchronous
    /composer/spec/author still works for older clients, but it regularly
    outlives the browser: one live draft ran 30.6k in / 7.8k out, the
    request died, and the practitioner saw "failed to fetch" over a call
    that had actually SUCCEEDED and been charged for. Enqueuing means the
    work outlives the tab and the result is readable afterwards, so a
    timeout can never again cost a second full charge.

    Ownership verified before enqueuing, same as the rebuild path."""
    uid = getattr(getattr(user_session, "user", None), "id", None)
    if not uid:
        raise HTTPException(401, "auth required")
    notes = (req.notes or "").strip()
    if req.revise and not notes:
        raise HTTPException(400, "revision notes are required")
    async with httpx.AsyncClient() as client:
        owned = await _sb(client, "GET",
                          f"/businesses?id=eq.{req.business_id}&owner_id=eq.{uid}"
                          "&select=id&limit=1")
        if not owned:
            raise HTTPException(403, "not your business")
        params: Dict[str, Any] = {}
        if notes:
            params["notes"] = notes[:2000]
        job = await enqueue(client, user_id=uid, business_id=req.business_id,
                            kind=("revise_spec" if req.revise else "author_spec"),
                            params=params, source="desktop")
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
