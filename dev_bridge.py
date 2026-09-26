"""
Dev Bridge — Mission Control's line to the developer side (2026-08-19).

Two lanes, one list:

  • cloud — a GitHub issue tagged @claude (the existing builder bridge);
    Claude Code runs in GitHub's cloud, opens the PR, auto-merges when green.
  • local — a row Solution Space (Kevin's Electron app) polls for; a task
    arriving there opens a live coding-agent session in the task's project —
    Claude Code by default, or Codex when the task names it — seeds the
    brief, and submits it.

A third kind of row is not dispatched at all (2026-09-26): a session Kevin
opens by hand in Solution Space announces itself (origin 'desktop'), so the
Dev Desk shows every project he has open on the desktop, not only the ones
he sent from his phone, and a reply reaches it the same way.

Both lanes report back into dev_tasks, which the Dev Desk panel renders.
When a session reports, or goes quiet while Kevin is away from the machine,
his phone hears about it (web push).
Auth: /platform/dev-desk/* uses the owner's JWT (require_owner) like every
other Mission Control endpoint; /dev-bridge/queue and /status use a device
token minted at pairing; /report uses the task's own report_key so the
session working the task can post its result.
"""

import asyncio
import hashlib
import logging
import ntpath
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

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

# The coding agents a local task can ask for. Claude Code is the default and
# every task before 2026-09-24 ran on it. The cloud lane is Claude only: it
# is the @claude GitHub workflow.
AGENTS = ("claude", "codex")
AGENT_NAMES = {"claude": "Claude Code", "codex": "Codex"}

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
    if _is_work(task):
        from chief_local_work import db
        await db('POST', '/rpc/chief_work_note', {'task_id': task['id'], 'note': {
            'id': str(uuid4()), 'from': sender, 'text': text[:4000], 'at': _now()}})
        return
    notes = list(task.get("notes") or [])
    notes.append({"from": sender, "text": text[:4000], "at": _now()})
    await _sb_patch(c, "dev_tasks", {"id": f"eq.{task['id']}"},
                    {"notes": notes, "updated_at": _now()})


# ─── Device auth ──────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _require_device(c: httpx.AsyncClient, authorization: Optional[str],
                          agents: Optional[List[str]] = None) -> Dict[str, Any]:
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
    beat: Dict[str, Any] = {"last_seen_at": _now()}
    if agents is not None:
        # What this build of Solution Space can open, so the Dev Desk can say
        # whether Codex is reachable before a task sits in the queue for it.
        beat["agents"] = agents
    try:
        await _sb_patch(c, "dev_bridge_devices", {"id": f"eq.{device['id']}"}, beat)
    except HTTPException:
        pass  # a failed heartbeat must not block the queue read
    return device


def _device_agents(raw: Optional[str]) -> List[str]:
    """The agents a polling device says it can run. A build that predates
    agents sends nothing, and it can only open Claude Code, so that is what
    it is offered: a Codex task must never be opened as Claude by an old
    build that ignores the field."""
    named = [a.strip().lower() for a in (raw or "").split(",")]
    supported = [a for a in AGENTS if a in named]
    return supported or ["claude"]


# ─── The seeded brief ─────────────────────────────────────────────────

def _compose_prompt(task: Dict[str, Any]) -> str:
    """The text Solution Space hands the fresh Claude Code session: the brief
    itself, plus how the conversation with Kevin works while he is away —
    his replies arrive in the session, and reports land in the Dev Desk."""
    body = (task.get("details") or "").strip() or task.get("title", "")
    if _is_work(task):
        body += ('\nYour final report may include work_result: {"summary":"What you produced and file paths", '
                 '"plan":null}. For strategy work, plan must match the schema in the brief. '
                 'Report editable output paths and any missing evidence. Never include credentials in reports.')
    return (
        f"{body}\n\n"
        "---\n"
        "This task came from Mission Control's Dev Desk. Kevin is most likely "
        "away from this machine, so nobody is at the keyboard: work the task "
        "through on your own, and talk to Kevin through the Dev Desk.\n\n"
        f"{_how_to_report(task)}"
    )


def _how_to_report(task: Dict[str, Any]) -> str:
    """The report channel, in the words every brief uses — a dispatched
    task's and a reopened desktop session's alike."""
    report_url = f"{PUBLIC_BASE_URL}/dev-bridge/tasks/{task['id']}/report"
    return (
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


def _reopen_brief(task: Dict[str, Any]) -> str:
    """For an agent that cannot resume a past conversation by itself: the
    original brief plus what has been said on the Dev Desk since, so a fresh
    session picks the task up where it was left. Terminal captures are left
    out — they are screen noise, not conversation."""
    if task.get("origin") == "desktop":
        return _desktop_reopen_brief(task)
    lines = []
    for n in (task.get("notes") or [])[-16:]:
        who = {"kevin": "Kevin", "dev": "You (report)", "device": "Solution Space"}.get(n.get("from"))
        text = (n.get("text") or "").strip()
        if who and text:
            lines.append(f"- {who}: {text[:1200]}")
    history = "\n".join(lines) or "- (nothing yet)"
    return (
        f"{_compose_prompt(task)}\n"
        "---\n"
        "You are picking this task up again in a new session. What has been "
        "said on the Dev Desk so far, oldest first:\n"
        f"{history}\n\n"
        "Kevin's newest message is the last line above. Check the working tree "
        "for what was already done before changing anything, then continue.\n"
    )


def _desktop_reopen_brief(task: Dict[str, Any]) -> str:
    """A session Kevin opened by hand has no brief to replay. When he replies
    from his phone after it closed, the fresh session gets what there is:
    that it was open, the last screen it showed (the only record of what it
    was doing), and what Kevin has said since."""
    notes = task.get("notes") or []
    screen = next((n.get("text") or "" for n in reversed(notes)
                   if n.get("from") == "session"), "").strip()
    lines = []
    for n in notes[-16:]:
        who = {"kevin": "Kevin", "dev": "You (report)"}.get(n.get("from"))
        text = (n.get("text") or "").strip()
        if who and text:
            lines.append(f"- {who}: {text[:1200]}")
    history = "\n".join(lines) or "- (nothing yet)"
    last_screen = "\n".join(screen.splitlines()[-40:]) or "(none was captured)"
    return (
        f"Kevin had a {AGENT_NAMES.get(task.get('agent') or 'claude', 'coding')} "
        f"session open in this project ({task.get('title') or 'this folder'}) "
        "on his desktop. It has since closed, and he has messaged it from "
        "Mission Control's Dev Desk on his phone. He is away from this "
        "machine, so nobody is at the keyboard.\n\n"
        "The last screen that session showed:\n"
        f"```\n{last_screen}\n```\n\n"
        "What Kevin has said on the Dev Desk, oldest first:\n"
        f"{history}\n\n"
        "His newest message is the last line above. Check the working tree "
        "and recent commits for what was already done before changing "
        "anything, then do what he asks.\n\n"
        "---\n"
        f"{_how_to_report(task)}"
    )


# ─── Owner lane: the Dev Desk ─────────────────────────────────────────

class DispatchBody(BaseModel):
    lane: str  # 'local' | 'cloud'
    title: str
    details: Optional[str] = None
    repo: Optional[str] = None  # 'frontend' | 'backend'
    project_path: Optional[str] = None
    agent: Optional[str] = None  # 'claude' (default) | 'codex' — local lane only


class NoteBody(BaseModel):
    text: str


class PairBody(BaseModel):
    name: Optional[str] = None


_DESK_COLUMNS = ("id,created_at,updated_at,lane,status,title,details,repo,agent,origin,"
                 "project_path,issue_url,notes,picked_up_at,finished_at")


@router.get("/platform/dev-desk")
async def dev_desk(lite: bool = False, _owner=Depends(require_owner)):
    """Everything the Dev Desk panel shows, one call. Fails soft on the
    GitHub half so the task list never blanks because of a rate limit.

    `lite` skips the GitHub half entirely. The panel polls it every few
    seconds while a conversation is live, which would otherwise spend three
    GitHub API calls a poll on lists that change a few times a day."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        try:
            tasks = await _sb_get(c, "dev_tasks", {
                "select": _DESK_COLUMNS,
                "origin": "eq.dev_desk",
                "order": "created_at.desc",
                "limit": "50",
            })
            # Desktop sessions are their own window, newest activity first:
            # Kevin opens several a day, and in one shared window of 50 they
            # would push every dispatched conversation off the desk in a week.
            tasks += await _sb_get(c, "dev_tasks", {
                "select": _DESK_COLUMNS,
                "origin": "eq.desktop",
                "order": "updated_at.desc",
                "limit": "20",
            })
        except HTTPException:
            # No origin column yet (APPLY-2026-09-26-dev-desk-desktop-sessions
            # not applied): the desk still opens, as it did before desktop
            # sessions existed. Announcing one fails loud until then.
            tasks = await _sb_get(c, "dev_tasks", {
                "select": _DESK_COLUMNS.replace("origin,", ""),
                "order": "created_at.desc",
                "limit": "50",
            })
        devices = await _sb_get(c, "dev_bridge_devices", {
            "select": "id,name,created_at,last_seen_at,revoked,agents",
            "order": "created_at.desc",
        })
        if lite:
            return {"ok": True, "tasks": tasks, "devices": devices}
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
    if repo not in LOCAL_PROJECTS:
        raise HTTPException(422, "Choose the frontend or backend project.")
    agent = (body.agent or "claude").strip().lower()
    if agent not in AGENTS:
        raise HTTPException(422, "Choose Claude Code or Codex.")
    if lane == "cloud" and agent != "claude":
        raise HTTPException(422, "Codex works in Solution Space on Kevin's machine — "
                                 "the cloud builder is Claude on GitHub.")
    from platform_chief_authority import current_authorization, digest
    approved = current_authorization.get()
    scope = {'lane': lane, 'repo': repo, 'title': title, 'details': body.details,
             'project_path': body.project_path or LOCAL_PROJECTS[repo]}
    # Named only when it is not the default, so a Claude task's scope hashes
    # exactly as it did before agents existed.
    if agent != "claude":
        scope['agent'] = agent
    authorization = {'owner_id': str(_owner.id), 'approved_at': _now(),
                     'source': 'chief_review' if approved else 'dev_desk',
                     'approval_id': approved[1]['id'] if approved else None,
                     'scope_hash': digest(scope), 'scope': scope,
                     'deployment': 'owner_review_required'}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        if lane == "cloud":
            # Same dispatcher the Platform Chief's queue_build uses: a GitHub
            # issue on the chosen repo that the Claude Code workflow builds.
            from chief_of_staff import _fire_build_issue
            issue_url = await _fire_build_issue(c, title, body.details or title, repo)
            row = await _sb_insert(c, "dev_tasks", {
                "authority_record": authorization,
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
            "authority_record": authorization,
            "lane": "local",
            "status": "queued",
            "title": title,
            "details": body.details,
            "repo": repo,
            "agent": agent,
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
        if _is_work(task):
            from chief_local_work import reply, Reply
            await reply(UUID(task_id), Reply(id=uuid4(), text=text), _owner)
            return {'ok': True, 'posted_to_issue': False, 'reopened': task.get('status') in _FINISHED_STATUSES}
        await _append_note(c, task, "kevin", text)
        # Cloud-lane follow-ups go to the issue too, so the cloud builder
        # actually sees them — a note only the Dev Desk shows would dead-end.
        posted_to_issue = False
        if task.get("lane") == "cloud" and task.get("issue_url"):
            posted_to_issue = await _comment_on_issue(c, task["issue_url"], text)
        # The Dev Desk is a conversation: a reply on a finished local task
        # picks it back up. Replies are only delivered on active tasks, so
        # without this the message would sit on the row and reach no one.
        reopened = False
        if task.get("lane") == "local" and task.get("status") in _FINISHED_STATUSES:
            await _sb_patch(c, "dev_tasks", {"id": f"eq.{task_id}"},
                            {"status": "working", "finished_at": None,
                             "updated_at": _now()})
            reopened = True
    return {"ok": True, "posted_to_issue": posted_to_issue, "reopened": reopened}


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
    # Solution Space's read of whether Kevin is at the machine (no input for
    # a while). A relayed screen from a session that went quiet while he is
    # away is the one his phone hears about; a build that predates the field
    # sends nothing, and nothing is pushed.
    away: Optional[bool] = None


class ReportBody(BaseModel):
    key: str
    status: str
    note: Optional[str] = None
    # One plain sentence for the person who reported the problem, when this
    # task came from a support ticket. It is shown to them verbatim if it
    # passes the practitioner guard, so it must read like something a human
    # would say about their own business — never about the work.
    for_practitioner: Optional[str] = None
    work_result: Optional[Dict[str, Any]] = None


def _is_work(task):
    return (task.get('authority_record') or {}).get('scope', {}).get('account_mode') == 'subscription'


async def _bound_work(task, device):
    if not _is_work(task):
        return
    from chief_local_work import db
    rows = await db('GET', f"/platform_chief_work?id=eq.{UUID(task['id'])}&device_id=eq.{UUID(device['id'])}&limit=1")
    if not rows:
        raise HTTPException(409, 'This conversation is not claimed by this device.')


@router.post('/dev-bridge/tasks/{task_id}/claim')
async def bridge_claim(task_id: UUID, authorization: Optional[str] = Header(None)):
    from chief_local_work import db
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
    claimed = await db('POST', '/rpc/chief_work_claim', {'task_id': str(task_id), 'device': device['id']})
    if claimed is not True:
        raise HTTPException(409, 'Conversation was already claimed or this desktop needs updating.')
    return {'ok': True}


@router.get("/dev-bridge/queue")
async def bridge_queue(authorization: Optional[str] = Header(None),
                       agents: Optional[str] = None, capabilities: Optional[str] = None):
    # Only work for an agent this device can open. The rest waits in the
    # queue for a device that can — see _device_agents.
    can_run = _device_agents(agents)
    workbench = 'workbench-v1' in (capabilities or '').split(',')
    agent_filter = f"in.({','.join(can_run)})"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization, can_run + (['workbench-v1'] if workbench else []))
        rows = await _sb_get(c, "dev_tasks", {
            "lane": "eq.local",
            "status": "eq.queued",
            "agent": agent_filter,
            "select": "id,title,details,repo,agent,project_path,report_key,created_at,authority_record,notes",
            **({} if workbench else {'authority_record->scope->>account_mode': 'is.null'}),
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
            "agent": agent_filter,
            "select": "id,title,details,repo,agent,project_path,report_key,notes,authority_record",
            **({} if workbench else {'authority_record->scope->>account_mode': 'is.null'}),
            "order": "updated_at.asc",
            "limit": "20",
        })
    tasks = []
    for t in rows:
        if _is_work(t) and not workbench:
            continue
        # ntpath, not os.path: these are Windows paths and this runs on Linux,
        # where os.path.basename of a C: path is the whole string — which is
        # how Solution Space once gained a project named by its full path.
        name = ntpath.basename((t.get("project_path") or "").rstrip("\\/")) or None
        tasks.append({
            "id": t["id"],
            "title": t.get("title"),
            "prompt": _reopen_brief(t) if _is_work(t) and t.get('notes') else _compose_prompt(t),
            "account_mode": 'subscription' if _is_work(t) else 'configured',
            "reply_stamps": [n['at'] for n in _undelivered_replies(t)] if _is_work(t) else [],
            "project_path": t.get("project_path"),
            "project_name": name,
            "repo": t.get("repo"),
            "agent": t.get("agent") or "claude",
            "created_at": t.get("created_at"),
        })
    followups = []
    for t in active:
        if _is_work(t):
            if not workbench:
                continue
            try:
                await _bound_work(t, device)
            except HTTPException as e:
                if e.status_code == 409:
                    continue
                raise
        pending = _undelivered_replies(t)
        if pending:
            followups.append({
                "task_id": t["id"],
                "account_mode": 'subscription' if _is_work(t) else 'configured',
                "title": t.get("title"),
                "project_path": t.get("project_path"),
                "agent": t.get("agent") or "claude",
                "notes": pending,
                # For when the task's session is gone and its agent cannot
                # resume one: a fresh session gets the whole story instead.
                "reopen_brief": _reopen_brief(t),
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
        device = await _require_device(c, authorization)
        task = await _get_task(c, task_id)
        await _bound_work(task, device)
        if _is_work(task):
            from chief_local_work import db
            await db('POST', '/rpc/chief_work_ack', {'task_id': str(UUID(task_id)), 'stamps': list(wanted)})
            return {'ok': True, 'acked': len(wanted)}
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
        device = await _require_device(c, authorization)
        task = await _get_task(c, task_id)
        await _bound_work(task, device)
        if _is_work(task) and status == 'picked_up':
            raise HTTPException(409, 'Claim this conversation before opening it.')
        # A session's relayed output can arrive after its own 'done' report;
        # that must not flip a finished task back to 'working'. The note still
        # lands — it is the final answer Kevin wants to read.
        settled = task.get("status") in _FINISHED_STATUSES
        if not (settled and (status == "working" or _is_work(task))):
            patch: Dict[str, Any] = {"status": status, "updated_at": _now()}
            if status == "picked_up" and not task.get("picked_up_at"):
                patch["picked_up_at"] = _now()
            if status == "failed":
                patch["finished_at"] = _now()
            await _sb_patch(c, "dev_tasks", {"id": f"eq.{task_id}"}, patch)
        if body.note:
            if sender == "session" and task.get("origin") == "desktop":
                await _put_screen(c, task, body.note)
            else:
                await _append_note(c, task, sender, body.note)
        pushed = 0
        if (sender == "session" and body.away and not settled
                and not _is_work(task) and not _said_it_itself(task)):
            pushed = await _tell_kevin(
                c, task, f"{task.get('title') or 'A session'} — your turn",
                "It stopped: finished, or waiting on you. Its screen is on the Dev Desk.")
    return {"ok": True, "pushed": pushed}


# A session that reported in its own words within this window has already
# told Kevin what the quiet means; a generic "it stopped" on top would
# replace its sentence on his lock screen (one notification per task).
_OWN_WORDS_S = 300


def _said_it_itself(task: Dict[str, Any]) -> bool:
    cutoff = datetime.now(timezone.utc).timestamp() - _OWN_WORDS_S
    for n in task.get("notes") or []:
        if n.get("from") != "dev":
            continue
        try:
            at = datetime.fromisoformat(str(n.get("at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.timestamp() >= cutoff:
            return True
    return False


async def _put_screen(c: httpx.AsyncClient, task: Dict[str, Any], text: str) -> None:
    """A desktop session relays its screen every time it goes quiet — every
    turn, in a session Kevin is using by hand. Consecutive screens replace
    one another instead of piling up: the thread keeps the newest screen
    between two things anyone said, which is all the panel shows anyway."""
    notes = list(task.get("notes") or [])
    screen = {"from": "session", "text": text[:4000], "at": _now()}
    if notes and notes[-1].get("from") == "session":
        notes[-1] = screen
    else:
        notes.append(screen)
    await _sb_patch(c, "dev_tasks", {"id": f"eq.{task['id']}"},
                    {"notes": notes, "updated_at": _now()})


# ─── Telling Kevin: web push to his phone ─────────────────────────────

async def _tell_kevin(c: httpx.AsyncClient, task: Dict[str, Any],
                      title: str, body: str) -> int:
    """One notification per task — the tag makes a newer one replace the
    older on the lock screen instead of stacking — and a tap opens that
    task's thread on the Dev Desk. Returns how many devices it reached.
    Fail-soft: a report or a relay never fails because the telling did."""
    try:
        import platform_watchdog
        import push_notifications
        if not push_notifications.push_enabled():
            return 0
        owner = await platform_watchdog._owner_user_id(c, _service_headers())
        if not owner:
            logger.warning("dev_bridge push skipped — no owner user id resolved")
            return 0
        # send_to_user posts to each push service synchronously.
        return await asyncio.to_thread(
            push_notifications.send_to_user, owner,
            title=title[:90], body=body[:220],
            nav=f"studio:platform-dev-desk:{task['id']}",
            tag=f"dev-task-{task['id']}",
        )
    except Exception as e:
        logger.warning(f"dev_bridge push failed for {task.get('id')}: {e}")
        return 0


# ─── Desktop sessions: the ones Kevin opened by hand ──────────────────

class DesktopSessionBody(BaseModel):
    project_path: str
    project_name: Optional[str] = None
    agent: Optional[str] = None  # 'claude' (default) | 'codex'
    label: Optional[str] = None  # what Solution Space calls the pane, if named


@router.post("/dev-bridge/sessions")
async def bridge_open_session(body: DesktopSessionBody,
                              authorization: Optional[str] = Header(None)):
    """Solution Space announces a session Kevin opened himself. It becomes a
    live Dev Desk conversation with no brief: its screen arrives as it goes
    quiet, and a reply is typed into it like any task's. The report key is
    for the session that reopens it after it closed — see
    _desktop_reopen_brief — since nobody is at the keyboard then."""
    agent = (body.agent or "claude").strip().lower()
    if agent not in AGENTS:
        raise HTTPException(422, "agent must be claude or codex")
    path = body.project_path.strip()
    if not path:
        raise HTTPException(422, "project_path required")
    name = ((body.project_name or "").strip()
            or ntpath.basename(path.rstrip("\\/")) or "project")
    repo = next((k for k, v in LOCAL_PROJECTS.items() if v.lower() == path.lower()), None)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
        try:
            row = await _sb_insert(c, "dev_tasks", {
                "lane": "local",
                "origin": "desktop",
                "device_id": device["id"],
                "status": "working",
                "title": ((body.label or "").strip() or name)[:200],
                "repo": repo,
                "agent": agent,
                "project_path": path,
                "report_key": secrets.token_hex(16),
            })
        except HTTPException as e:
            raise HTTPException(e.status_code, "Desktop sessions need "
                                "supabase/APPLY-2026-09-26-dev-desk-desktop-sessions.sql "
                                f"applied. {e.detail}")
    return {"ok": True, "task_id": row.get("id")}


class SweepBody(BaseModel):
    live: List[str] = []


# A session announced, or a closed one reopened by a reply, is not in the
# device's live list until it is bound to a pane; a sweep in that window
# must not close it.
_SWEEP_GRACE_S = 120


@router.post("/dev-bridge/sessions/{task_id}/closed")
async def bridge_close_session(task_id: str, authorization: Optional[str] = Header(None)):
    """The pane closed. Only a desktop session ends this way — a dispatched
    task ends with its own report — so anything else is left as it is."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
        task = await _get_task(c, task_id)
        if task.get("origin") != "desktop" or task.get("device_id") != device["id"]:
            return {"ok": True, "closed": False}
        closed = await _close_desktop(c, task, "The session was closed in Solution Space.")
    return {"ok": True, "closed": closed}


@router.post("/dev-bridge/sessions/sweep")
async def bridge_sweep_sessions(body: SweepBody, authorization: Optional[str] = Header(None)):
    """Solution Space says which desktop sessions it still has open; the rest
    of its own are over. A restart or a crash never sends 'closed', and
    without this every session it lost would sit on the Dev Desk as live."""
    live = set(body.live or [])
    # Z form — '+00:00' reads as a space in a PostgREST query string.
    before = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() - _SWEEP_GRACE_S, timezone.utc,
    ).isoformat().replace("+00:00", "Z")
    closed = 0
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
        rows = await _sb_get(c, "dev_tasks", {
            "origin": "eq.desktop",
            "device_id": f"eq.{device['id']}",
            "status": f"in.({','.join(sorted(_ACTIVE_STATUSES))})",
            "updated_at": f"lt.{before}",
            "select": "id,status,origin,device_id,notes",
            "limit": "50",
        })
        for t in rows:
            if t["id"] not in live and await _close_desktop(
                    c, t, "Solution Space no longer has this session open."):
                closed += 1
    return {"ok": True, "closed": closed}


async def _close_desktop(c: httpx.AsyncClient, task: Dict[str, Any], why: str) -> bool:
    if task.get("status") in _FINISHED_STATUSES:
        return False
    await _sb_patch(c, "dev_tasks", {"id": f"eq.{task['id']}"},
                    {"status": "done", "finished_at": _now(), "updated_at": _now()})
    await _append_note(c, task, "device", why)
    return True


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
        if _is_work(task):
            if task.get('status') in ('queued', 'cancelled'):
                raise HTTPException(409, 'This conversation is not active.')
            if task.get('status') in ('done', 'failed') and status != task['status']:
                raise HTTPException(409, 'This conversation is already settled. Send an owner reply to continue it.')
            if body.work_result is not None:
                from chief_local_work import save_result
                await save_result(task, body.work_result)
        patch: Dict[str, Any] = {"status": status, "updated_at": _now()}
        if status in ("done", "failed"):
            patch["finished_at"] = _now()
        await _sb_patch(c, "dev_tasks", {"id": f"eq.{task_id}"}, patch)
        if body.note:
            await _append_note(c, task, "dev", body.note)
        # Every report is the session speaking to Kevin on purpose — a
        # finish, a failure, a progress line or a question — so each one
        # reaches his phone, in the session's own words.
        if not _is_work(task):
            name = task.get("title") or "A task"
            said = " ".join((body.note or "").split())
            await _tell_kevin(c, task, *{
                "done": (f"Done — {name}", said or "Finished. The report is on the Dev Desk."),
                "failed": (f"Stopped — {name}", said or "It stopped with a failure."),
            }.get(status, (name, said or "New update on the Dev Desk.")))

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
