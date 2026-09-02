"""
support_router.py — the fix queue (2026-09-02).

The gap this closes: a practitioner reports a broken thing into
support_tickets, and the work that fixes broken things lives in dev_tasks.
Nothing joined the two. Somebody read the ticket, retyped it into the Dev
Desk, and from that moment the ticket was on its own — the fix shipped, the
ticket stayed "open", and the person who reported it was never told
anything. Mission Control's own panel says so out loud: "no email
notification yet — fast-follow".

So there are four moves here, and they are the whole operating procedure:

  1. TRIAGE   — every ticket gets a severity and a problem key the moment
                it is first read, without anyone doing anything. The list
                is ranked on arrival instead of waiting to be curated.
  2. DISPATCH — one call turns a ticket into a dev task. The brief carries
                the practitioner's own words and their client context, and
                the ticket remembers which task is fixing it.
  3. WALK BACK— when that task finishes, the ticket moves to 'shipped' by
                itself. Reconciliation runs on every queue read, so the
                board is never stale and nothing depends on a cron.
  4. TELL THEM— the reply endpoint writes the answer AND emails it. The
                loop closes at a person, which is the only place it counts.

Auth. /platform/support/* is the owner's JWT, like every other Mission
Control surface. /dev-bridge/tickets is the Solution Space device token,
so the ticket area in the app that opens the sessions can render the queue
and dispatch from it without holding Kevin's JWT — and a device may only
open LOCAL tasks, never fire a cloud build.

Reads and writes go through the service role, which is the point: the
existing Mission Control panel writes tickets straight from the browser
under RLS, so no server-side automation could ever hang off a reply.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

import support_queue as sq
from lead_admin import require_owner, _service_headers, SUPABASE_URL

logger = logging.getLogger("support_router")

router = APIRouter(tags=["support-queue"])

HTTP_TIMEOUT = httpx.Timeout(20.0)

# How many tickets the queue considers. The whole table is small; this is
# a guard against the day it is not.
QUEUE_LIMIT = 300
MESSAGE_PREVIEW = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Supabase helpers -------------------------------------------------

async def _sb_get(c: httpx.AsyncClient, path: str,
                  params: Dict[str, str]) -> List[Dict[str, Any]]:
    r = await c.get(f"{SUPABASE_URL}/rest/v1/{path}",
                    headers=_service_headers(), params=params)
    if r.status_code >= 400:
        raise HTTPException(502, f"support read failed: {r.text[:200]}")
    return r.json() or []


async def _sb_insert(c: httpx.AsyncClient, path: str,
                     body: Any, upsert: bool = False) -> List[Dict[str, Any]]:
    headers = dict(_service_headers())
    if upsert:
        headers["Prefer"] = "return=representation,resolution=merge-duplicates"
    r = await c.post(f"{SUPABASE_URL}/rest/v1/{path}", headers=headers, json=body)
    if r.status_code >= 400:
        raise HTTPException(502, f"support write failed — is the "
                                 f"APPLY-2026-09-02-support-fix-queue migration "
                                 f"applied? {r.text[:200]}")
    rows = r.json() if r.text else []
    return rows if isinstance(rows, list) else [rows]


async def _sb_patch(c: httpx.AsyncClient, path: str, params: Dict[str, str],
                    body: Dict[str, Any]) -> None:
    r = await c.patch(f"{SUPABASE_URL}/rest/v1/{path}", headers=_service_headers(),
                      params=params, json=body)
    if r.status_code >= 400:
        raise HTTPException(502, f"support update failed: {r.text[:200]}")


async def _get_ticket(c: httpx.AsyncClient, ticket_id: str) -> Dict[str, Any]:
    rows = await _sb_get(c, "support_tickets",
                         {"id": f"eq.{ticket_id}", "select": "*"})
    if not rows:
        raise HTTPException(404, "No such ticket")
    return rows[0]


# --- 1. Triage, without anybody doing anything ------------------------

def _seed_triage(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """The triage row a ticket gets the first time the queue reads it.

    Existing tickets land in the lane their old status already implies, so
    turning this on does not dump months of resolved tickets into the
    triage lane on day one.
    """
    severity, _why = sq.guess_severity(
        ticket.get("category") or "", ticket.get("subject") or "",
        ticket.get("message") or "")
    status = (ticket.get("status") or "open").lower()
    fix_state = {"resolved": "answered", "in_progress": "triaged"}.get(status, "new")
    row: Dict[str, Any] = {
        "ticket_id": ticket["id"],
        "severity": severity,
        "fix_state": fix_state,
        "problem_key": sq.problem_key(
            ticket.get("category") or "", ticket.get("subject") or "",
            ticket.get("message") or "", ticket.get("context") or {}),
        "triaged_by": "auto",
    }
    if ticket.get("replied_at"):
        row["first_response_at"] = ticket["replied_at"]
    if fix_state == "answered":
        row["closed_at"] = ticket.get("updated_at") or _now()
    return row


# Ids per `in.()` — a bounded URL, not a bounded table. Reading the triage
# table by "limit N" instead would eventually miss the row for a ticket in
# view, and the seeding insert below would then overwrite a hand-set
# severity with the keyword guess. Scope the read to the ids on screen.
_ID_CHUNK = 50


async def _triage_for(c: httpx.AsyncClient,
                      ticket_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ticket_ids), _ID_CHUNK):
        chunk = ticket_ids[i:i + _ID_CHUNK]
        if not chunk:
            continue
        rows = await _sb_get(c, "support_triage", {
            "ticket_id": f"in.({','.join(chunk)})", "select": "*"})
        for r in rows:
            out[r["ticket_id"]] = r
    return out


async def _ensure_triage(c: httpx.AsyncClient, tickets: List[Dict[str, Any]],
                         existing: Dict[str, Dict[str, Any]]) -> None:
    missing = [_seed_triage(t) for t in tickets if t["id"] not in existing]
    if not missing:
        return
    rows = await _sb_insert(c, "support_triage", missing, upsert=True)
    for row in rows:
        existing[row["ticket_id"]] = row


async def _upsert_triage(c: httpx.AsyncClient, ticket: Dict[str, Any],
                         patch: Dict[str, Any]) -> Dict[str, Any]:
    """Patch the triage row, or seed one and patch it in the same write.

    Read-then-write on purpose, NOT a merge-duplicates upsert: an upsert
    carrying the seed would overwrite a severity somebody had set by hand
    with the keyword guess, every time anyone replied to the ticket.
    """
    rows = await _sb_get(c, "support_triage",
                         {"ticket_id": f"eq.{ticket['id']}", "select": "*"})
    if rows:
        await _sb_patch(c, "support_triage",
                        {"ticket_id": f"eq.{ticket['id']}"}, patch)
        return {**rows[0], **patch}
    return (await _sb_insert(c, "support_triage",
                             {**_seed_triage(ticket), **patch}))[0]


# --- 3. The walk-back -------------------------------------------------

async def _reconcile(c: httpx.AsyncClient, triage: Dict[str, Dict[str, Any]],
                     tasks: Dict[str, Dict[str, Any]]) -> int:
    """Move tickets whose dev task has moved. Runs on every queue read:
    the board cannot go stale, and no scheduler has to be trusted."""
    moved = 0
    for row in triage.values():
        task = tasks.get(row.get("dev_task_id") or "")
        if not task or row.get("fix_state") not in ("queued", "fixing"):
            continue
        status = (task.get("status") or "").lower()
        want = sq.DEV_STATUS_TO_FIX_STATE.get(status)
        if status in ("failed", "cancelled"):
            # The fix did not happen. Back to the ready lane rather than
            # silently sitting in "in progress" — a task that died is a
            # ticket nobody is working on.
            want = "triaged"
        if not want or want == row.get("fix_state"):
            continue
        patch: Dict[str, Any] = {"fix_state": want, "updated_at": _now()}
        if want == "shipped":
            patch["shipped_at"] = _now()
        if status in ("failed", "cancelled"):
            patch["note"] = ((row.get("note") or "") +
                             f"\n[{_now()}] dev task {status} — back in the queue").strip()
        await _sb_patch(c, "support_triage",
                        {"ticket_id": f"eq.{row['ticket_id']}"}, patch)
        row.update(patch)
        moved += 1
    return moved


# --- the queue itself -------------------------------------------------

def _item(ticket: Dict[str, Any], triage: Dict[str, Any], repeats: int,
          task: Optional[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    score, why = sq.rank(ticket, triage, repeats, now)
    message = ticket.get("message") or ""
    return {
        "id": ticket["id"],
        "business_id": ticket.get("business_id"),
        "business": ticket.get("business_name") or (ticket.get("business_id") or "")[:8],
        "category": ticket.get("category"),
        "subject": ticket.get("subject"),
        "message": message[:MESSAGE_PREVIEW],
        "message_truncated": len(message) > MESSAGE_PREVIEW,
        "context": ticket.get("context") or {},
        "created_at": ticket.get("created_at"),
        "age_days": round(sq.age_days(ticket.get("created_at"), now), 1),
        "status": ticket.get("status"),
        "admin_reply": ticket.get("admin_reply"),
        "answered": bool(triage.get("first_response_at") or ticket.get("replied_at")),
        "severity": triage.get("severity") or "normal",
        "fix_state": triage.get("fix_state") or "new",
        "lane": sq.lane_of(triage.get("fix_state")),
        "problem_key": triage.get("problem_key"),
        "repeats": repeats,
        "triage_note": triage.get("note"),
        "triaged_by": triage.get("triaged_by"),
        "rank": score,
        "why": why,
        "dev_task": ({
            "id": task.get("id"),
            "lane": task.get("lane"),
            "status": task.get("status"),
            "title": task.get("title"),
            "issue_url": task.get("issue_url"),
            "updated_at": task.get("updated_at"),
        } if task else None),
    }


async def _load_queue(c: httpx.AsyncClient) -> Dict[str, Any]:
    tickets = await _sb_get(c, "support_tickets", {
        "select": "id,business_id,business_name,category,subject,message,context,"
                  "status,admin_reply,replied_at,created_at,updated_at",
        "order": "created_at.desc",
        "limit": str(QUEUE_LIMIT),
    })
    triage = await _triage_for(c, [t["id"] for t in tickets])
    await _ensure_triage(c, tickets, triage)

    task_ids = sorted({r["dev_task_id"] for r in triage.values()
                       if r.get("dev_task_id")})
    tasks: Dict[str, Dict[str, Any]] = {}
    if task_ids:
        rows = await _sb_get(c, "dev_tasks", {
            "id": f"in.({','.join(task_ids)})",
            "select": "id,lane,status,title,issue_url,updated_at",
        })
        tasks = {r["id"]: r for r in rows}
    moved = await _reconcile(c, triage, tasks)

    now = datetime.now(timezone.utc)
    repeats: Dict[str, int] = {}
    for t in tickets:
        key = (triage.get(t["id"], {}) or {}).get("problem_key")
        if key:
            repeats[key] = repeats.get(key, 0) + 1

    lanes: Dict[str, List[Dict[str, Any]]] = {ln: [] for ln in sq.OPEN_LANES}
    lanes["closed"] = []
    counts = {s: 0 for s in sq.FIX_STATES}
    unanswered = 0
    oldest_open = 0.0
    for t in tickets:
        tr = triage.get(t["id"]) or {}
        key = tr.get("problem_key")
        item = _item(t, tr, repeats.get(key, 1) if key else 1,
                     tasks.get(tr.get("dev_task_id") or ""), now)
        lanes.setdefault(item["lane"], []).append(item)
        counts[tr.get("fix_state") or "new"] = counts.get(tr.get("fix_state") or "new", 0) + 1
        if item["lane"] != "closed":
            if not item["answered"]:
                unanswered += 1
            oldest_open = max(oldest_open, item["age_days"])
    for ln in lanes:
        lanes[ln].sort(key=lambda i: i["rank"], reverse=True)
    # The closed lane is history, not work: newest first and only the
    # recent slice, so it never crowds out the four lanes that are work.
    lanes["closed"] = sorted(lanes["closed"],
                             key=lambda i: i["created_at"] or "", reverse=True)[:25]

    clusters = []
    for key, n in sorted(repeats.items(), key=lambda kv: kv[1], reverse=True):
        if n < 2:
            continue
        members = [i for ln in sq.OPEN_LANES for i in lanes[ln]
                   if i["problem_key"] == key]
        if not members:
            continue
        clusters.append({
            "problem_key": key,
            "count": n,
            "open": len(members),
            "severity": members[0]["severity"],
            "subject": members[0]["subject"],
            "ticket_ids": [m["id"] for m in members],
        })

    return {
        "ok": True,
        "generated_at": now.isoformat(),
        "reconciled": moved,
        "lanes": lanes,
        "clusters": clusters[:10],
        "counts": {
            **counts,
            "open_total": sum(len(lanes[ln]) for ln in sq.OPEN_LANES),
            "unanswered": unanswered,
            "oldest_open_days": round(oldest_open, 1),
            "blockers": sum(1 for ln in sq.OPEN_LANES for i in lanes[ln]
                            if i["severity"] == "blocker"),
        },
    }


@router.get("/platform/support/queue")
async def support_queue(_owner=Depends(require_owner)):
    """Everything the ticket area shows, one call: four working lanes, the
    repeat-problem clusters, and the counts that say whether support is
    keeping up."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        return await _load_queue(c)


# --- 2. Dispatch: a ticket becomes work -------------------------------

def _fix_brief(ticket: Dict[str, Any], extra: str = "") -> str:
    """The brief the fixing session opens with. It carries the
    practitioner's own words, because a paraphrase is where the actual
    symptom goes missing, plus the client context that says where to look.
    """
    ctx = ticket.get("context") or {}
    lines = [
        "A practitioner reported this from Help & Support. Reproduce it, "
        "fix it, and keep the fix narrow.",
        "",
        f"Business: {ticket.get('business_name') or ticket.get('business_id')}",
        f"Category: {ticket.get('category')}",
        f"Filed: {ticket.get('created_at')}",
        f"Support ticket: {ticket.get('id')}",
        "",
        f"Subject: {ticket.get('subject')}",
        "",
        "What they said, verbatim:",
        (ticket.get("message") or "").strip(),
    ]
    if isinstance(ctx, dict) and ctx:
        bits = [f"{k}: {v}" for k, v in ctx.items() if k != "user_agent"]
        if ctx.get("user_agent"):
            bits.append(f"user_agent: {str(ctx['user_agent'])[:160]}")
        lines += ["", "Client context at the time:", "  " + "\n  ".join(bits)]
    if extra.strip():
        lines += ["", "Extra direction:", extra.strip()]
    lines += [
        "",
        "When you are done, say in one plain sentence what the practitioner "
        "will now see differently — that sentence is what gets sent back to "
        "them, so no builder, GitHub or Claude Code language in it.",
    ]
    return "\n".join(lines)


async def _dispatch(c: httpx.AsyncClient, ticket: Dict[str, Any], *,
                    lane: str, repo: str, project_path: str,
                    title: str, extra: str, by: str) -> Dict[str, Any]:
    repo = (repo or "frontend").strip().lower()
    if repo not in ("frontend", "backend"):
        raise HTTPException(422, "repo must be 'frontend' or 'backend'")
    title = (title or "").strip() or f"FIX: {(ticket.get('subject') or '')[:160]}"
    details = _fix_brief(ticket, extra)

    if lane == "cloud":
        from chief_of_staff import _fire_build_issue
        issue_url = await _fire_build_issue(c, title, details, repo)
        if not issue_url:
            # No dead dev_task row for a dispatch that never happened —
            # the ticket stays where it was, which is the truth.
            raise HTTPException(502, "GitHub dispatch failed — GITHUB_TOKEN "
                                     "missing or the API rejected it")
        row = (await _sb_insert(c, "dev_tasks", {
            "lane": "cloud",
            "status": "dispatched",
            "title": title,
            "details": details,
            "repo": repo,
            "issue_url": issue_url,
        }))[0]
    else:
        from dev_bridge import LOCAL_PROJECTS
        row = (await _sb_insert(c, "dev_tasks", {
            "lane": "local",
            "status": "queued",
            "title": title,
            "details": details,
            "repo": repo,
            "project_path": (project_path or "").strip() or LOCAL_PROJECTS.get(repo, ""),
            "report_key": secrets.token_hex(16),
        }))[0]

    await _upsert_triage(c, ticket, {
        "dev_task_id": row.get("id"),
        "fix_state": "queued",
        "queued_at": _now(),
        "updated_at": _now(),
        "triaged_by": by,
    })
    # The practitioner's own view of the ticket should say something is
    # happening, and 'in_progress' is the only word their panel knows.
    if (ticket.get("status") or "open") == "open":
        await _sb_patch(c, "support_tickets", {"id": f"eq.{ticket['id']}"},
                        {"status": "in_progress"})
    return {"ok": True, "task": row, "ticket_id": ticket["id"]}


class TriageBody(BaseModel):
    severity: Optional[str] = None
    fix_state: Optional[str] = None
    problem_key: Optional[str] = None
    duplicate_of: Optional[str] = None
    note: Optional[str] = None


class DispatchBody(BaseModel):
    lane: str = "local"                  # 'local' | 'cloud'
    repo: Optional[str] = "frontend"     # 'frontend' | 'backend'
    project_path: Optional[str] = None
    title: Optional[str] = None
    details: Optional[str] = None        # extra direction, appended to the brief


class ReplyBody(BaseModel):
    text: str
    resolve: bool = False


@router.post("/platform/support/tickets/{ticket_id}/triage")
async def triage_ticket(ticket_id: str, body: TriageBody,
                        owner=Depends(require_owner)):
    patch: Dict[str, Any] = {"updated_at": _now(),
                             "triaged_by": (owner.email or "owner").lower()}
    if body.severity:
        if body.severity not in sq.SEVERITIES:
            raise HTTPException(422, f"severity must be one of {list(sq.SEVERITIES)}")
        patch["severity"] = body.severity
    if body.fix_state:
        if body.fix_state not in sq.FIX_STATES:
            raise HTTPException(422, f"fix_state must be one of {list(sq.FIX_STATES)}")
        patch["fix_state"] = body.fix_state
        if sq.lane_of(body.fix_state) == "closed":
            patch["closed_at"] = _now()
    if body.problem_key is not None:
        patch["problem_key"] = body.problem_key.strip() or None
    if body.duplicate_of is not None:
        patch["duplicate_of"] = body.duplicate_of or None
    if body.note is not None:
        patch["note"] = body.note[:4000]

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        ticket = await _get_ticket(c, ticket_id)
        row = await _upsert_triage(c, ticket, patch)
        # A ticket closed as won't-fix or duplicate is not open work; the
        # practitioner's own status should stop saying it is.
        if patch.get("fix_state") in ("wont_fix", "duplicate"):
            await _sb_patch(c, "support_tickets", {"id": f"eq.{ticket_id}"},
                            {"status": "resolved"})
    return {"ok": True, "triage": row}


@router.post("/platform/support/tickets/{ticket_id}/dispatch")
async def dispatch_ticket(ticket_id: str, body: DispatchBody,
                          owner=Depends(require_owner)):
    """Turn a ticket into a fix. One call, both lanes."""
    lane = (body.lane or "local").strip().lower()
    if lane not in ("local", "cloud"):
        raise HTTPException(422, "lane must be 'local' or 'cloud'")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        ticket = await _get_ticket(c, ticket_id)
        return await _dispatch(c, ticket, lane=lane, repo=body.repo or "frontend",
                               project_path=body.project_path or "",
                               title=body.title or "", extra=body.details or "",
                               by=(owner.email or "owner").lower())


# --- 4. Telling them --------------------------------------------------

async def _recipient_email(c: httpx.AsyncClient,
                           ticket: Dict[str, Any]) -> Optional[str]:
    """Who filed it. The ticket's own user first, the business owner as the
    fallback — a seat holder can file, and the row records which."""
    headers = _service_headers()
    base = SUPABASE_URL.rstrip("/")
    uid = ticket.get("user_id")
    if uid:
        try:
            r = await c.get(f"{base}/auth/v1/admin/users/{uid}", headers=headers)
            if r.status_code < 400 and r.json().get("email"):
                return r.json()["email"]
        except Exception as e:
            logger.warning(f"ticket recipient lookup failed: {e}")
    try:
        rows = await _sb_get(c, "businesses", {
            "id": f"eq.{ticket.get('business_id')}", "select": "owner_id"})
        owner_id = rows[0].get("owner_id") if rows else None
        if owner_id:
            r = await c.get(f"{base}/auth/v1/admin/users/{owner_id}", headers=headers)
            if r.status_code < 400:
                return r.json().get("email")
    except Exception as e:
        logger.warning(f"ticket owner lookup failed: {e}")
    return None


async def _email_reply(c: httpx.AsyncClient, ticket: Dict[str, Any],
                       text: str) -> Tuple[bool, Optional[str]]:
    """Fail-soft: the reply is saved either way. An email that could not go
    out must not lose the answer, but it must be REPORTED — a silent
    failure here is the exact hole this endpoint exists to close."""
    to = await _recipient_email(c, ticket)
    if not to:
        return False, "no email on file for the person who filed it"
    try:
        from email_sender import send_via_resend
        from platform_addresses import public_contact_email
        await send_via_resend(
            to_email=to,
            to_name=None,
            from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
            from_name="Solutionist Support",
            subject=f"Re: {(ticket.get('subject') or 'your support ticket')[:150]}",
            body=(
                f"{text.strip()}\n\n"
                f"---\n"
                f"You wrote on {ticket.get('created_at', '')[:10]}:\n"
                f"{(ticket.get('message') or '').strip()[:1200]}\n\n"
                f"You can see this and everything else you have sent in the app "
                f"under Help & Support, My tickets."
            ),
            reply_to=public_contact_email(),
        )
        return True, None
    except Exception as e:
        logger.warning(f"support reply email failed: {e}")
        return False, str(e)[:200]


@router.post("/platform/support/tickets/{ticket_id}/reply")
async def reply_ticket(ticket_id: str, body: ReplyBody, _owner=Depends(require_owner)):
    """The answer, written to the ticket AND sent to the person. Before
    this, a reply sat in a column the practitioner had to go looking for."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(422, "text required")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        ticket = await _get_ticket(c, ticket_id)
        emailed, why = await _email_reply(c, ticket, text)
        await _sb_patch(c, "support_tickets", {"id": f"eq.{ticket_id}"}, {
            "admin_reply": text[:5000],
            "replied_at": _now(),
            "status": "resolved" if body.resolve else (
                "in_progress" if ticket.get("status") == "open" else ticket.get("status")),
        })
        existing = await _sb_get(c, "support_triage", {
            "ticket_id": f"eq.{ticket_id}", "select": "first_response_at"})
        patch: Dict[str, Any] = {"updated_at": _now()}
        # first_response_at is set once and never moved: it is the clock on
        # how long somebody waited to hear anything at all.
        if not (existing[0].get("first_response_at") if existing else None):
            patch["first_response_at"] = _now()
        if body.resolve:
            patch["fix_state"] = "answered"
            patch["closed_at"] = _now()
        await _upsert_triage(c, ticket, patch)
    return {"ok": True, "emailed": emailed, "email_error": why}


# --- The Solution Space lane ------------------------------------------
# The ticket area lives in the app that opens the sessions, so it needs
# the queue and the dispatch WITHOUT the owner's JWT. The device token is
# the same one the dev-task queue already uses.

@router.get("/dev-bridge/tickets")
async def bridge_tickets(authorization: Optional[str] = Header(None)):
    from dev_bridge import _require_device
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await _require_device(c, authorization)
        return await _load_queue(c)


class BridgeDispatchBody(BaseModel):
    repo: Optional[str] = "frontend"
    project_path: Optional[str] = None
    title: Optional[str] = None
    details: Optional[str] = None


@router.post("/dev-bridge/tickets/{ticket_id}/dispatch")
async def bridge_dispatch_ticket(ticket_id: str, body: BridgeDispatchBody,
                                 authorization: Optional[str] = Header(None)):
    """Local lane only. A device token opens a session on Kevin's own
    machine; it must never be able to spend the cloud builder's budget."""
    from dev_bridge import _require_device
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
        ticket = await _get_ticket(c, ticket_id)
        return await _dispatch(c, ticket, lane="local", repo=body.repo or "frontend",
                               project_path=body.project_path or "",
                               title=body.title or "", extra=body.details or "",
                               by=f"device:{device.get('name') or device.get('id')}")
