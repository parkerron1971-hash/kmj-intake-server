"""
chief_scheduler.py — "schedule anything" (2026-07-10, Kevin's
adaptive-Chief directive).

Chief's action toolkit could only act NOW; a real assistant's power is
deferring and composing. This module executes chief_scheduled_actions
rows when they come due: any ACTION_HANDLERS verb, one-shot or
recurring, with the outcome delivered back to the practitioner as a
chief_notifications row + Web Push + activity-rail entry.

Tick: every minute on the scheduler leader (gl_drain precedent).
Kill switch: CHIEF_SCHEDULER=off.

Safety: verbs that only make sense in a live client session (navigate,
set_timer) and self-nesting (schedule_action & friends) are refused at
SCHEDULING time in chief_of_staff.handle_schedule_action — by the time
a row exists here it's executable. A handler crash marks the row
failed with the error preserved; recurrence reschedules instead of
completing; every outcome is visible, nothing fails dark.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

import sb_clients

logger = logging.getLogger("chief_scheduler")

MAX_PER_TICK = 25

# Denylist mirrored from chief_of_staff.handle_schedule_action —
# belt-and-suspenders in case a row is inserted by other means.
CLIENT_ONLY_OR_NESTING = {"navigate", "set_timer", "schedule_action",
                          "cancel_scheduled", "list_scheduled"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_run(run_at: datetime, recurrence: str) -> Optional[datetime]:
    """The next occurrence AFTER now, stepping from the scheduled time so
    a delayed tick doesn't drift the schedule."""
    step = {"daily": timedelta(days=1), "weekly": timedelta(weeks=1),
            "weekdays": timedelta(days=1)}.get(recurrence)
    if not step:
        return None
    nxt = run_at
    while nxt <= _now():
        nxt += step
        if recurrence == "weekdays":
            while nxt.weekday() >= 5:   # Sat/Sun roll to Monday
                nxt += timedelta(days=1)
    return nxt


async def _notify_outcome(biz: Dict[str, Any], row: Dict[str, Any],
                          ok: bool, detail: str) -> None:
    """Deliver the outcome: in-app notification + push + activity rail.
    Best-effort on every leg — a delivery hiccup never fails the run."""
    title = ("⏰ " + str(row.get("label") or "Scheduled action")) if ok else \
            ("⚠️ Scheduled action failed: " + str(row.get("label") or ""))
    body = detail[:240]
    try:
        await asyncio.to_thread(sb_clients.sb_post_as_service, "/chief_notifications", {
            "business_id": biz["id"], "type": "reminder",
            "title": title[:120], "body": body, "priority": "normal",
        })
    except Exception as e:
        logger.warning(f"[scheduler] notification insert failed: {e}")
    owner = biz.get("owner_id")
    if owner:
        try:
            import push_notifications
            await asyncio.to_thread(
                push_notifications.send_to_user, str(owner),
                title=title[:80], body=body[:160], nav="home")
        except Exception as e:
            logger.warning(f"[scheduler] push failed (non-fatal): {e}")
        try:
            await asyncio.to_thread(sb_clients.sb_post_as_service, "/chief_activity", {
                "user_id": str(owner), "business_id": biz["id"],
                "source": "system",
                "action_type": f"scheduled:{(row.get('action') or {}).get('type')}",
                "label": title[:120], "summary": body,
            })
        except Exception as e:
            logger.warning(f"[scheduler] activity log failed: {e}")


async def _execute_row(row: Dict[str, Any]) -> None:
    rid = row.get("id")
    action = row.get("action") if isinstance(row.get("action"), dict) else {}
    atype = str(action.get("type") or "")

    biz_rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/businesses?id=eq.{row.get('business_id')}"
        "&select=id,name,type,settings,owner_id&limit=1")
    biz = (biz_rows or [None])[0]
    if not biz:
        await asyncio.to_thread(sb_clients.sb_patch_as_service,
            f"/chief_scheduled_actions?id=eq.{rid}",
            {"status": "failed", "last_error": "business not found",
             "last_run_at": _now().isoformat()})
        return

    recurrence_raw = str(row.get("recurrence") or "").strip().lower()

    # LEDGER STAGE 0 (2026-08-03) — the scheduler consults the registry.
    # It used to run ANY handler verb at its due time with only a 5-verb
    # client-only denylist: a class-C verb scheduled once in chat then
    # fired unprompted, forever, on a recurrence, with the chat path's
    # _gate_class_c nowhere near it.
    #
    # What this gate does NOT do: block recurring class-C. Recurring
    # invoices are a deliberate product feature (see action_registry's
    # note on create_invoice + auto_send), so refusing them here would
    # break intended behavior — that's Kevin's ruling to make, not a
    # gate's. What it DOES enforce is the registry's own standing rule
    # that BULK verbs are never autonomy-eligible at any class, which
    # this path has been quietly violating. Unknown/unclassified fails
    # closed, matching _gate_class_c.
    # STAGE 3: one evaluator instead of a local registry read. It adds the
    # regulated-vertical gate (a scheduled client-facing send for a
    # therapist is unattended client contact) on top of the bulk and
    # drift refusals this path already made.
    authorized_by = "scheduled"
    gate_refusal: Optional[str] = None
    if atype not in CLIENT_ONLY_OR_NESTING:
        try:
            import policy_engine
            verdict = policy_engine.evaluate(
                str(biz.get("id") or ""), verb=atype, surface="scheduled",
                prompted=False, biz_row=biz)
            # Cadence is NOT appended to the rule: "scheduled" already
            # implies unattended, and payload.recurrence carries the
            # once-vs-recurring fact in a queryable field.
            authorized_by = verdict.rule
            if not verdict.allowed:
                gate_refusal = verdict.reason
        except Exception as e:
            logger.warning(f"[scheduler] policy check failed for {atype}: {e}")
            gate_refusal = "action safety check unavailable"

    ok, detail = False, ""
    if gate_refusal:
        detail = gate_refusal
    elif atype in CLIENT_ONLY_OR_NESTING:
        detail = f"'{atype}' can't run server-side"
    else:
        # Lazy import (workflow_engine precedent) — Chief's whole verb
        # set is the scheduler's verb set, no second registry to drift.
        from chief_of_staff import ACTION_HANDLERS
        handler = ACTION_HANDLERS.get(atype)
        if not handler:
            detail = f"unknown action '{atype}'"
        else:
            try:
                # Every run from here is unattended by definition. Set
                # rather than defaulted, and set on the dict the handler
                # actually receives, so a stored payload cannot arrive
                # claiming otherwise: a schedule that could declare
                # itself prompted would be a schedule that approves its
                # own irreversible actions. Handlers that don't care
                # ignore it; publish_post uses it to demand a recorded
                # human approval before posting in public.
                action["_unattended"] = True
                async with httpx.AsyncClient() as client:
                    result = await handler(client, biz, action)
                res_text = str((result or {}).get("result") or "")
                # "failed": True is the machine-readable failure seam
                # (PR #345); the "failed…" result-text prefix is the
                # older convention. Honor both — a failed handler that
                # audits as ok=true is worse than no audit row.
                ok = not ((result or {}).get("failed") is True
                          or res_text.lower().startswith("failed"))
                detail = (str((result or {}).get("label") or "") or res_text
                          or "done")[:240]
            except Exception as e:
                detail = f"handler raised: {e}"

    recurrence = recurrence_raw
    nxt = _next_run(_parse_ts(row.get("run_at")), recurrence) if ok and recurrence else None
    patch: Dict[str, Any] = {"last_run_at": _now().isoformat()}
    if nxt:
        patch["run_at"] = nxt.isoformat()          # stays queued
    else:
        patch["status"] = "done" if ok else "failed"
        if not ok:
            patch["last_error"] = detail[:300]
    await asyncio.to_thread(sb_clients.sb_patch_as_service,
        f"/chief_scheduled_actions?id=eq.{rid}", patch)

    # S11 audit coverage — EVERY scheduled execution lands in the
    # unified audit log with the ok/failed truth, not just the ones
    # that also managed to notify. actor_type must pass the table's
    # CHECK ('user','chief','agent','system'), so the scheduler's
    # identity rides actor_id + source. Fail-soft by construction:
    # audit_log.record never raises, and a False return is logged.
    try:
        import audit_log
        wrote = await asyncio.to_thread(
            audit_log.record, biz["id"],
            actor_type="system", actor_id="scheduler",
            verb=(atype or "unknown")[:80],
            ok=ok, error=(detail[:500] if not ok else None),
            summary=(str(row.get("label") or "") or detail)[:240],
            payload={"scheduled_action_id": str(rid),
                     "recurrence": recurrence or None,
                     "authorized_by": authorized_by},
            source="scheduler")
        if not wrote:
            logger.warning(f"[scheduler] audit write failed for {atype} ({str(rid)[:8]})")
    except Exception as e:
        logger.warning(f"[scheduler] audit write failed for {atype}: {e}")

    await _notify_outcome(biz, row, ok, detail)
    logger.info(f"[scheduler] {('ok' if ok else 'FAIL')} {atype} "
                f"({str(rid)[:8]}) — {detail[:80]}"
                + (f" — next {nxt.isoformat()}" if nxt else ""))


def _parse_ts(v: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return _now()


async def due_tick() -> None:
    """Scheduler tick (leader-gated, every minute)."""
    if (os.environ.get("CHIEF_SCHEDULER") or "on").lower() == "off":
        return
    try:
        rows = await asyncio.to_thread(
            sb_clients.sb_get_as_service,
            f"/chief_scheduled_actions?status=eq.queued"
            # Z form — '+00:00' reads as a space in query strings.
            f"&run_at=lte.{_now().isoformat().replace('+00:00', 'Z')}"
            f"&order=run_at.asc&limit={MAX_PER_TICK}&select=*")
    except Exception as e:  # pragma: no cover
        logger.warning(f"[scheduler] due fetch failed: {e}")
        return
    for row in rows or []:
        try:
            await _execute_row(row)
        except Exception as e:  # pragma: no cover
            logger.warning(f"[scheduler] row {str(row.get('id'))[:8]} crashed: {e}")
