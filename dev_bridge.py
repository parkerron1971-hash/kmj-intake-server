"""
Dev Bridge — Mission Control's line to the developer side (2026-08-19).

Two lanes, one list:

  • cloud — a GitHub issue tagged @claude (the existing builder bridge);
    Claude Code runs in GitHub's cloud, opens the PR, auto-merges when green.
  • local — a row Solution Space (Kevin's Electron app) polls for; a task
    arriving there opens a real Claude Code session in the task's project,
    seeds the brief, and submits it.

Both lanes report back into dev_tasks, which the Dev Desk panel renders.
Auth: /platform/dev-desk/* uses the owner's JWT (require_owner) like every
other Mission Control endpoint; /dev-bridge/queue and /status use a device
token minted at pairing; /report uses the task's own report_key so the
session working the task can post its result.
"""

import hashlib
import logging
import ntpath
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from lead_admin import require_owner, _service_headers, SUPABASE_URL

logger = logging.getLogger("dev_bridge")

router = APIRouter(tags=["dev-bridge"])

HTTP_TIMEOUT = httpx.Timeout(20.0)

PUBLIC_BASE_URL = (os.environ.get("PUBLIC_BASE_URL")
                   or "https://kmj-intake-server-production.up.railway.app").rstrip("/")

# Where each repo lives on Kevin's machine — the default project a local task
# opens in. A task can override with an explicit project_path.
LOCAL_PROJECTS = {
    "frontend": r"C:\Users\kmccl\solutionist-studio\solutionist-studio",
    "backend": r"C:\Users\kmccl\kmj-intake-server",
}

_BUILD_LABEL = "chief-build"
_GH_REPOS = {
    "frontend": "parkerron1971-hash/solutionist-studio",
    "backend": "parkerron1971-hash/kmj-intake-server",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Supabase helpers ─────────────────────────────────────────────────

async def _sb_get(c: httpx.AsyncClient, path: str, params: Dict[str, str]) -> List[Dict[str, Any]]:
    r = await c.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=_service_headers(), params=params)
    if r.status_code >= 400:
        raise HTTPException(502, f"dev_bridge read failed: {r.text[:200]}")
    return r.json() or []


async def _sb_insert(c: httpx.AsyncClient, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    r = await c.post(f"{SUPABASE_URL}/rest/v1/{path}", headers=_service_headers(), json=body)
    if r.status_code >= 400:
        raise HTTPException(502, f"dev_bridge write failed — is the dev-bridge "
                                 f"migration applied? {r.text[:200]}")
    rows = r.json() if r.text else []
    return rows[0] if isinstance(rows, list) and rows else {}


async def _sb_patch(c: httpx.AsyncClient, path: str, params: Dict[str, str],
                    body: Dict[str, Any]) -> None:
    r = await c.patch(f"{SUPABASE_URL}/rest/v1/{path}", headers=_service_headers(),
                      params=params, json=body)
    if r.status_code >= 400:
        raise HTTPException(502, f"dev_bridge update failed: {r.text[:200]}")


async def _get_task(c: httpx.AsyncClient, task_id: str) -> Dict[str, Any]:
    rows = await _sb_get(c, "dev_tasks", {"id": f"eq.{task_id}", "select": "*"})
    if not rows:
        raise HTTPException(404, "No such task")
    return rows[0]


async def _append_note(c: httpx.AsyncClient, task: Dict[str, Any],
                       sender: str, text: str) -> None:
    notes = list(task.get("notes") or [])
    notes.append({"from": sender, "text": text[:4000], "at": _now()})
    await _sb_patch(c, "dev_tasks", {"id": f"eq.{task['id']}"},
                    {"notes": notes, "updated_at": _now()})


# ─── Device auth ──────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _require_device(c: httpx.AsyncClient, authorization: Optional[str]) -> Dict[str, Any]:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Device token required")
    rows = await _sb_get(c, "dev_bridge_devices", {
        "token_hash": f"eq.{_hash_token(token)}",
        "revoked": "eq.false",
        "select": "id,name",
    })
    if not rows:
        raise HTTPException(401, "Unknown or revoked device token")
    device = rows[0]
    try:
        await _sb_patch(c, "dev_bridge_devices", {"id": f"eq.{device['id']}"},
                        {"last_seen_at": _now()})
    except HTTPException:
        pass  # a failed heartbeat must not block the queue read
    return device


# ─── The seeded brief ─────────────────────────────────────────────────

def _compose_prompt(task: Dict[str, Any]) -> str:
    """The text Solution Space hands the fresh Claude Code session: the brief
    itself, plus how the conversation with Kevin works while he is away —
    his replies arrive in the session, and reports land in the Dev Desk."""
    body = (task.get("details") or "").strip() or task.get("title", "")
    report_url = f"{PUBLIC_BASE_URL}/dev-bridge/tasks/{task['id']}/report"
    return (
        f"{body}\n\n"
        "---\n"
        "This task came from Mission Control's Dev Desk. Kevin is most likely "
        "away from this machine, so nobody is at the keyboard: work the task "
        "through on your own, and talk to Kevin through the Dev Desk.\n\n"
        "To report, POST to:\n"
        f"  {report_url}\n"
        "  JSON body with three fields: key (given below), status, and note.\n"
        "  status is 'working' for a progress update or a question, 'done' "
        "when finished, or 'failed' with the reason. note is a short "
        "plain-language message to Kevin: what you did, where, and anything "
        "he should check.\n"
        f"  key: {task.get('report_key', '')}\n"
        "  If this task came from a support ticket, the final 'done' report "
        "may also carry a fourth field, for_practitioner: ONE plain sentence "
        "saying what the person who reported it will now see differently. It "
        "is shown to them as-is, so write it in their language — nothing "
        "about repos, branches, PRs or the tooling.\n\n"
        "If you need a decision from Kevin, post a 'working' report that asks "
        "the question, then wait. His reply will arrive here as a new message "
        "in this session, prefixed 'Kevin (from the Dev Desk)'. Always finish "
        "with a 'done' or 'failed' report — a task without one reads as still "
        "running.\n"
    )


# ─── Owner lane: the Dev Desk ─────────────────────────────────────────

class DispatchBody(BaseModel):
    lane: str  # 'local' | 'cloud'
    title: str
    details: Optional[str] = None
    repo: Optional[str] = None  # 'frontend' | 'backend'
    project_path: Optional[str] = None


class NoteBody(BaseModel):
    text: str


class PairBody(BaseModel):
    name: Optional[str] = None


@router.get("/platform/dev-desk")
async def dev_desk(_owner=Depends(require_owner)):
    """Everything the Dev Desk panel shows, one call. Fails soft on the
    GitHub half so the task list never blanks because of a rate limit."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        tasks = await _sb_get(c, "dev_tasks", {
            "select": "id,created_at,updated_at,lane,status,title,details,repo,"
                      "project_path,issue_url,notes,picked_up_at,finished_at",
            "order": "created_at.desc",
            "limit": "50",
        })
        devices = await _sb_get(c, "dev_bridge_devices", {
            "select": "id,name,created_at,last_seen_at,revoked",
            "order": "created_at.desc",
        })
        cloud_open = await _open_build_issues(c)
    try:
        from platform_console import _recent_merged_prs
        ships = await _recent_merged_prs()
    except Exception:
        ships = []
    return {"ok": True, "tasks": tasks, "devices": devices,
            "cloud_open": cloud_open, "recent_ships": ships[:10]}


async def _open_build_issues(c: httpx.AsyncClient) -> List[Dict[str, Any]]:
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    out: List[Dict[str, Any]] = []
    for key, repo in _GH_REPOS.items():
        try:
            r = await c.get(f"https://api.github.com/repos/{repo}/issues",
                            headers=headers,
                            params={"state": "open", "labels": _BUILD_LABEL,
                                    "per_page": "10"})
            if r.status_code >= 400:
                continue
            for issue in r.json():
                out.append({
                    "repo": key,
                    "number": issue.get("number"),
                    "title": issue.get("title"),
                    "url": issue.get("html_url"),
                    "created_at": issue.get("created_at"),
                    "comments": issue.get("comments"),
                })
        except Exception as e:
            logger.warning(f"open build issues ({repo}): {e}")
    out.sort(key=lambda i: i.get("created_at") or "", reverse=True)
    return out


@router.post("/platform/dev-desk/tasks")
async def dispatch_task(body: DispatchBody, _owner=Depends(require_owner)):
    lane = (body.lane or "").strip().lower()
    if lane not in ("local", "cloud"):
        raise HTTPException(422, "lane must be 'local' or 'cloud'")
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "title required")
    repo = (body.repo or "frontend").strip().lower()

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        if lane == "cloud":
            # Same dispatcher the Platform Chief's queue_build uses: a GitHub
            # issue on the chosen repo that the Claude Code workflow builds.
            from chief_of_staff import _fire_build_issue
            issue_url = await _fire_build_issue(c, title, body.details or title, repo)
            row = await _sb_insert(c, "dev_tasks", {
                "lane": "cloud",
                "status": "dispatched" if issue_url else "failed",
                "title": title,
                "details": body.details,
                "repo": repo,
                "issue_url": issue_url,
                "notes": ([] if issue_url else
                          [{"from": "device", "at": _now(),
                            "text": "GitHub dispatch failed — GITHUB_TOKEN missing or API error"}]),
            })
            return {"ok": bool(issue_url), "task": row, "issue_url": issue_url}

        project_path = (body.project_path or "").strip() or LOCAL_PROJECTS.get(repo, "")
        row = await _sb_insert(c, "dev_tasks", {
            "lane": "local",
            "status": "queued",
            "title": title,
            "details": body.details,
            "repo": repo,
            "project_path": project_path,
            "report_key": secrets.token_hex(16),
        })
        return {"ok": True, "task": row}


@router.post("/platform/dev-desk/tasks/{task_id}/note")
async def add_owner_note(task_id: str, body: NoteBody, _owner=Depends(require_owner)):
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "text required")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        task = await _get_task(c, task_id)
        await _append_note(c, task, "kevin", text)
        # Cloud-lane follow-ups go to the issue too, so the cloud builder
        # actually sees them — a note only the Dev Desk shows would dead-end.
        posted_to_issue = False
        if task.get("lane") == "cloud" and task.get("issue_url"):
            posted_to_issue = await _comment_on_issue(c, task["issue_url"], text)
    return {"ok": True, "posted_to_issue": posted_to_issue}


async def _comment_on_issue(c: httpx.AsyncClient, issue_url: str, text: str) -> bool:
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        return False
    # https://github.com/{owner}/{repo}/issues/{n} → the API path pieces
    try:
        parts = issue_url.rstrip("/").split("/")
        gh_owner, gh_repo, number = parts[-4], parts[-3], parts[-1]
        body_text = text if "@claude" in text else f"@claude {text}"
        r = await c.post(
            f"https://api.github.com/repos/{gh_owner}/{gh_repo}/issues/{number}/comments",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            json={"body": body_text},
        )
        return r.status_code in (200, 201)
    except Exception as e:
        logger.warning(f"issue comment failed: {e}")
        return False


@router.post("/platform/dev-desk/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, _owner=Depends(require_owner)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        task = await _get_task(c, task_id)
        if task.get("status") in ("done", "cancelled"):
            return {"ok": True, "status": task["status"]}
        await _sb_patch(c, "dev_tasks", {"id": f"eq.{task_id}"},
                        {"status": "cancelled", "updated_at": _now(),
                         "finished_at": _now()})
    return {"ok": True, "status": "cancelled"}


@router.post("/platform/dev-desk/pair")
async def pair_device(body: PairBody, _owner=Depends(require_owner)):
    """Mint a device token for Solution Space. The plaintext is returned
    exactly once; only its hash is stored."""
    token = secrets.token_urlsafe(32)
    name = (body.name or "").strip() or "Solution Space"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        row = await _sb_insert(c, "dev_bridge_devices", {
            "name": name, "token_hash": _hash_token(token),
        })
    return {"ok": True, "device_id": row.get("id"), "name": name, "token": token}


# ─── Device lane: Solution Space ──────────────────────────────────────

class StatusBody(BaseModel):
    status: str
    note: Optional[str] = None
    sender: Optional[str] = None  # 'device' (default) | 'session'


class ReportBody(BaseModel):
    key: str
    status: str
    note: Optional[str] = None
    # One plain sentence for the person who reported the problem, when this
    # task came from a support ticket. It is shown to them verbatim if it
    # passes the practitioner guard, so it must read like something a human
    # would say about their own business — never about the work.
    for_practitioner: Optional[str] = None


@router.get("/dev-bridge/queue")
async def bridge_queue(authorization: Optional[str] = Header(None)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await _require_device(c, authorization)
        rows = await _sb_get(c, "dev_tasks", {
            "lane": "eq.local",
            "status": "eq.queued",
            "select": "id,title,details,repo,project_path,report_key,created_at",
            "order": "created_at.asc",
            "limit": "5",
        })
        # Kevin's replies on tasks a session is already working. The device
        # types each one into that session and acks it; until the ack lands
        # the note keeps coming back, so a crash between the two never loses
        # a reply (the device de-duplicates by timestamp).
        active = await _sb_get(c, "dev_tasks", {
            "lane": "eq.local",
            "status": f"in.({','.join(sorted(_ACTIVE_STATUSES))})",
            "select": "id,title,project_path,notes",
            "order": "updated_at.asc",
            "limit": "20",
        })
    tasks = []
    for t in rows:
        # ntpath, not os.path: these are Windows paths and this runs on Linux,
        # where os.path.basename of a C: path is the whole string — which is
        # how Solution Space once gained a project named by its full path.
        name = ntpath.basename((t.get("project_path") or "").rstrip("\\/")) or None
        tasks.append({
            "id": t["id"],
            "title": t.get("title"),
            "prompt": _compose_prompt(t),
            "project_path": t.get("project_path"),
            "project_name": name,
            "repo": t.get("repo"),
            "created_at": t.get("created_at"),
        })
    followups = []
    for t in active:
        pending = _undelivered_replies(t)
        if pending:
            followups.append({
                "task_id": t["id"],
                "title": t.get("title"),
                "project_path": t.get("project_path"),
                "notes": pending,
            })
    return {"ok": True, "tasks": tasks, "followups": followups}


# Statuses in which a session may still be at work on a task, and so can
# still take a reply from Kevin.
_ACTIVE_STATUSES = {"picked_up", "opened", "working"}
_FINISHED_STATUSES = {"done", "failed", "cancelled"}


def _undelivered_replies(task: Dict[str, Any]) -> List[Dict[str, str]]:
    """Kevin's notes on a task that no device has acked yet."""
    out = []
    for n in task.get("notes") or []:
        if n.get("from") == "kevin" and not n.get("delivered_at") and n.get("at"):
            out.append({"at": n["at"], "text": n.get("text") or ""})
    return out


class AckBody(BaseModel):
    """Timestamps (the notes' `at`) the device has typed into the session."""
    at: List[str]


@router.post("/dev-bridge/tasks/{task_id}/notes/ack")
async def bridge_ack_notes(task_id: str, body: AckBody,
                           authorization: Optional[str] = Header(None)):
    wanted = set(body.at or [])
    if not wanted:
        raise HTTPException(422, "at required")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await _require_device(c, authorization)
        task = await _get_task(c, task_id)
        notes = list(task.get("notes") or [])
        acked = 0
        for n in notes:
            if n.get("from") == "kevin" and n.get("at") in wanted and not n.get("delivered_at"):
                n["delivered_at"] = _now()
                acked += 1
        if acked:
            await _sb_patch(c, "dev_tasks", {"id": f"eq.{task_id}"},
                            {"notes": notes, "updated_at": _now()})
    return {"ok": True, "acked": acked}


_DEVICE_STATUSES = {"picked_up", "opened", "working", "failed"}
# Who a device-lane note is shown as: the device itself (Solution Space
# talking about what it did) or the session (the terminal's own output,
# relayed so Kevin can read it from the Dev Desk).
_DEVICE_SENDERS = {"device", "session"}


@router.post("/dev-bridge/tasks/{task_id}/status")
async def bridge_status(task_id: str, body: StatusBody,
                        authorization: Optional[str] = Header(None)):
    status = (body.status or "").strip().lower()
    if status not in _DEVICE_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(_DEVICE_STATUSES)}")
    sender = (body.sender or "device").strip().lower()
    if sender not in _DEVICE_SENDERS:
        raise HTTPException(422, f"sender must be one of {sorted(_DEVICE_SENDERS)}")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await _require_device(c, authorization)
        task = await _get_task(c, task_id)
        # A session's relayed output can arrive after its own 'done' report;
        # that must not flip a finished task back to 'working'. The note still
        # lands — it is the final answer Kevin wants to read.
        settled = task.get("status") in _FINISHED_STATUSES
        if not (settled and status == "working"):
            patch: Dict[str, Any] = {"status": status, "updated_at": _now()}
            if status == "picked_up" and not task.get("picked_up_at"):
                patch["picked_up_at"] = _now()
            if status == "failed":
                patch["finished_at"] = _now()
            await _sb_patch(c, "dev_tasks", {"id": f"eq.{task_id}"}, patch)
        if body.note:
            await _append_note(c, task, sender, body.note)
    return {"ok": True}


_REPORT_STATUSES = {"working", "done", "failed"}


@router.post("/dev-bridge/tasks/{task_id}/report")
async def bridge_report(task_id: str, body: ReportBody):
    """The working session's own channel back to the Dev Desk. Auth is the
    task's report_key — scoped to this one task."""
    status = (body.status or "").strip().lower()
    if status not in _REPORT_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(_REPORT_STATUSES)}")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        task = await _get_task(c, task_id)
        key = task.get("report_key")
        if not key or not secrets.compare_digest(str(body.key or ""), str(key)):
            raise HTTPException(401, "Bad report key")
        patch: Dict[str, Any] = {"status": status, "updated_at": _now()}
        if status in ("done", "failed"):
            patch["finished_at"] = _now()
        await _sb_patch(c, "dev_tasks", {"id": f"eq.{task_id}"}, patch)
        if body.note:
            await _append_note(c, task, "dev", body.note)

    # If this task came from a support ticket, the person who reported the
    # problem hears about it now — in the session's own sentence when it is
    # fit to send, and the standard one when it is not. Fail-soft: a task
    # report must never fail because the telling did.
    told = False
    if status == "done":
        try:
            from support_router import note_fix_shipped
            told = await note_fix_shipped(task_id, body.for_practitioner)
        except Exception as e:
            logger.warning(f"ticket walk-back failed for {task_id}: {e}")
    return {"ok": True, "told_the_practitioner": told}
