"""
agents_live.py — "Agents at work": one live picture of every agent
(2026-10-02, Kevin: "is there a visual area where I can see what they're
doing?").

Mission Control → Agents showed only the backend's watchers. Half the
agents run on GitHub (on-call, deploy checker, PR reviewer, security
steward, the weekly Chief evals, the uptime probe), so their work was only
visible as issues and PR comments. This module puts both on one screen:

  agents  every agent in plan order, with a status light (running, clear,
          found something, failed, not run yet), its last run in one line,
          a link to it, and whether "Run now" works for it;
  feed    what they did, newest first, in plain words: backend runs and
          findings plus GitHub workflow runs (which PR was reviewed, which
          deploy was verified, which incident was diagnosed);
  today   the day's tally: drafts written, PRs reviewed, deploys verified,
          findings raised, runs that failed.

run(id) runs a backend agent now, or dispatches a GitHub agent's workflow
where it has a manual trigger. Read-mostly; GitHub reads are cached for 30
seconds so a page polling every 30 seconds costs a handful of API calls.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

from lead_admin import _service_headers, SUPABASE_URL

logger = logging.getLogger("agents_live")

BE = "parkerron1971-hash/kmj-intake-server"
FE = "parkerron1971-hash/solutionist-studio"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)
CACHE_SECONDS = 30

# The agents, in the order of the plan. `source` says where they run.
# backend: platform_agent_runs rows under `agent`; github: workflow runs.
AGENTS: List[Dict[str, Any]] = [
    {"id": "on_call", "name": "On-call", "source": "github", "kind": "AI · diagnosis only",
     "workflows": [(BE, "oncall.yml")], "job": "Diagnoses outages and incidents"},
    {"id": "deploy_checker", "name": "Deploy checker", "source": "github", "kind": "watcher",
     "workflows": [(BE, "deploy-check.yml"), (FE, "deploy-check.yml")],
     "dispatch": (BE, "deploy-check.yml"), "job": "Confirms every merge went live"},
    {"id": "pr_reviewer", "name": "PR reviewer", "source": "github", "kind": "AI · comments only",
     "workflows": [(BE, "pr-review.yml"), (FE, "pr-review.yml")], "job": "Reviews every pull request"},
    {"id": "support_desk", "name": "Support desk", "source": "backend", "kind": "AI · drafts only",
     "job": "Drafts replies to tickets waiting on one"},
    {"id": "money_auditor", "name": "Money auditor", "source": "backend", "kind": "watcher",
     "job": "Payments, plans and Stripe vs. the database"},
    {"id": "chief_quality", "name": "Chief quality & cost", "source": "backend", "kind": "watcher",
     "workflows": [(BE, "chief-eval-weekly.yml")], "dispatch": (BE, "chief-eval-weekly.yml"),
     "job": "Chief's cost, speed and errors; weekly evals"},
    {"id": "security_steward", "name": "Security steward", "source": "github", "kind": "watcher",
     "workflows": [(BE, "security-steward.yml")], "dispatch": (BE, "security-steward.yml"),
     "job": "Secrets, access rules, keys and backups"},
    {"id": "customer_health", "name": "Customer health", "source": "backend", "kind": "AI · drafts only",
     "job": "Businesses that stalled or went quiet"},
    {"id": "unfinished_work", "name": "Unfinished work", "source": "backend", "kind": "watcher",
     "job": "Open PRs, pending migrations, work left undone"},
    {"id": "trial_expiry", "name": "Trial expiry", "source": "backend", "kind": "system",
     "job": "Ends trials given in the app"},
    {"id": "hermes", "name": "Hermes", "source": "backend", "kind": "watcher",
     "job": "Texts and email delivery"},
    {"id": "uptime", "name": "Uptime probe", "source": "github", "kind": "watcher",
     "workflows": [(BE, "uptime.yml")], "dispatch": (BE, "uptime.yml"),
     "job": "Checks every 10 minutes that production answers"},
]

# Backend agents' "Run now": module, function. Imported lazily.
BACKEND_RUN = {
    "support_desk": ("support_drafts", "drafts_tick"),
    "money_auditor": ("money_auditor", "audit_tick"),
    "chief_quality": ("chief_quality", "quality_tick"),
    "customer_health": ("customer_health", "health_tick"),
    "unfinished_work": ("unfinished_work", "watch_tick"),
    "trial_expiry": ("trial_expiry", "expire_tick"),
    "hermes": ("hermes_agent", "hermes_tick"),
}

_gh_cache: Dict[str, Any] = {}
_gh_problem: Dict[str, Optional[str]] = {"text": None}


def _gh_headers() -> Dict[str, str]:
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    h = {"Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _workflow_runs(c: httpx.AsyncClient, repo: str, wf: str) -> List[Dict[str, Any]]:
    key = f"{repo}/{wf}"
    hit = _gh_cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        r = await c.get(f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs",
                        headers=_gh_headers(), params={"per_page": 8})
        runs = (r.json().get("workflow_runs") or []) if r.status_code < 400 else []
        if r.status_code in (401, 403):
            # Found 2026-10-02: the server's GITHUB_TOKEN had gone bad, and
            # every GitHub agent read as "never run". Say what is wrong.
            _gh_problem["text"] = (
                "GitHub rejects the server's GITHUB_TOKEN ("
                f"{r.status_code}), so the GitHub agents' work can't be shown here, and "
                "Chief's build bridge, the Dev Desk cloud lane and incident filing are "
                "down too. Set a new token on Railway.")
    except Exception:
        runs = []
    _gh_cache[key] = (time.time(), runs)
    return runs


def _gh_status(run: Dict[str, Any]) -> str:
    if run.get("status") in ("queued", "in_progress", "waiting", "pending", "requested"):
        return "running"
    c = run.get("conclusion")
    if c in ("success", "neutral"):
        return "clear"
    if c in ("skipped", "cancelled", None):
        return "skipped"
    return "failed"


def _gh_event(agent: Dict[str, Any], repo: str, run: Dict[str, Any]) -> Dict[str, Any]:
    """Pure: one GitHub workflow run as a feed line in plain words."""
    side = "app" if repo == FE else "backend"
    title = run.get("display_title") or run.get("name") or ""
    status = _gh_status(run)
    verbs = {
        "deploy_checker": {"clear": f"Confirmed the {side} deploy went live",
                           "failed": f"The {side} deploy did not go live",
                           "running": f"Checking the {side} deploy"},
        "pr_reviewer": {"clear": f"Reviewed {side} PR: {title}",
                        "failed": f"Review of {side} PR failed to run: {title}",
                        "running": f"Reviewing {side} PR: {title}"},
        "on_call": {"clear": "Diagnosed an incident", "failed": "On-call investigation failed",
                    "running": "Investigating an incident"},
        "security_steward": {"clear": "Weekly security check finished",
                             "failed": "Weekly security check failed to run",
                             "running": "Running the weekly security check"},
        "chief_quality": {"clear": "Chief's weekly evals finished",
                          "failed": "Chief's weekly evals found a problem or failed",
                          "running": "Running Chief's weekly evals"},
        "uptime": {"clear": "Production answered", "failed": "Production did not answer",
                   "running": "Checking production"},
    }.get(agent["id"], {})
    text = verbs.get(status) or f"{agent['name']}: {title}"
    return {"agent": agent["id"], "agent_name": agent["name"], "at": run.get("created_at"),
            "status": status, "text": text, "url": run.get("html_url")}


def _be_event(row: Dict[str, Any], names: Dict[str, str]) -> Dict[str, Any]:
    status = "failed" if row.get("ok") is False else ("found" if (row.get("findings") or 0) > 0 else "clear")
    return {"agent": row.get("agent"), "agent_name": names.get(row.get("agent"), row.get("agent")),
            "at": row.get("finished_at") or row.get("started_at"), "status": status,
            "text": row.get("summary") or "", "url": None}


def tally(feed: List[Dict[str, Any]], runs: List[Dict[str, Any]], now: datetime) -> Dict[str, int]:
    """Pure: today's (UTC) counts. `runs` must hold all of today's support_desk
    runs that drafted something; the feed window alone loses them by evening."""
    day = now.strftime("%Y-%m-%d")
    today = [e for e in feed if (e.get("at") or "").startswith(day)]
    drafted = sum(int(((r.get("details") or {}).get("drafted")) or 0) for r in runs
                  if r.get("agent") == "support_desk" and (r.get("started_at") or "").startswith(day))
    return {
        "drafts_written": drafted,
        "prs_reviewed": sum(1 for e in today if e["agent"] == "pr_reviewer" and e["status"] == "clear"),
        "deploys_verified": sum(1 for e in today if e["agent"] == "deploy_checker" and e["status"] == "clear"),
        "findings_raised": sum(1 for e in today if e["status"] == "found"),
        "failed_runs": sum(1 for e in today if e["status"] == "failed"),
    }


async def _latest_run(c: httpx.AsyncClient, headers: Dict[str, str], agent: str) -> Optional[Dict[str, Any]]:
    try:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/platform_agent_runs", headers=headers, params={
            "select": "agent,started_at,finished_at,ok,findings,summary,details",
            "agent": f"eq.{agent}", "order": "started_at.desc", "limit": "1"})
        rows = r.json() if r.status_code < 400 else []
    except Exception:
        return None
    return next((x for x in rows or [] if x.get("agent") == agent), None)


async def _drafting_runs_today(c: httpx.AsyncClient, headers: Dict[str, str], now: datetime) -> List[Dict[str, Any]]:
    try:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/platform_agent_runs", headers=headers, params={
            "select": "agent,started_at,details", "agent": "eq.support_desk",
            "findings": "gt.0", "started_at": f"gte.{now.strftime('%Y-%m-%dT00:00:00Z')}",
            "limit": "1000"})
        return r.json() if r.status_code < 400 else []
    except Exception:
        return []


async def snapshot(now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    headers = _service_headers()
    names = {a["id"]: a["name"] for a in AGENTS}
    feed: List[Dict[str, Any]] = []
    runs: List[Dict[str, Any]] = []
    cards: List[Dict[str, Any]] = []
    _gh_problem["text"] = None
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        try:
            r = await c.get(f"{SUPABASE_URL}/rest/v1/platform_agent_runs", headers=headers, params={
                "select": "agent,started_at,finished_at,ok,findings,summary,details",
                "order": "started_at.desc", "limit": "200"})
            runs = r.json() if r.status_code < 400 else []
        except Exception:
            runs = []
        # A routine pass that found nothing is not news: keep findings and
        # failures, plus only the latest quiet run per agent, so a
        # five-minute agent cannot flood the feed.
        seen_quiet = set()
        for x in runs[:120]:
            ev = _be_event(x, names)
            if ev["status"] == "clear":
                if x.get("agent") in seen_quiet:
                    continue
                seen_quiet.add(x.get("agent"))
            feed.append(ev)
        gh_runs: Dict[str, List[tuple]] = {}
        for a in AGENTS:
            for repo, wf in a.get("workflows", []):
                for run in await _workflow_runs(c, repo, wf):
                    gh_runs.setdefault(a["id"], []).append((repo, run))
                    ev = _gh_event(a, repo, run)
                    if ev["status"] != "skipped":
                        feed.append(ev)
        # The window above is the newest 200 rows, and the support desk alone
        # writes 288 a day, so by evening a once-a-day agent's run has
        # fallen out of it and its card would read "not run yet". Fetch
        # the latest run of any backend agent the window missed.
        latest = {a["id"]: next((x for x in runs if x.get("agent") == a["id"]), None)
                  for a in AGENTS if a["source"] == "backend"}
        missing = [k for k, v in latest.items() if v is None]
        found = await asyncio.gather(*(_latest_run(c, headers, k) for k in missing))
        latest.update({k: v for k, v in zip(missing, found) if v})
        drafted_today = await _drafting_runs_today(c, headers, now)
    for a in AGENTS:
        last: Optional[Dict[str, Any]] = None
        if a["source"] == "backend":
            row = latest.get(a["id"])
            if row:
                last = _be_event(row, names)
        if not last and gh_runs.get(a["id"]):
            mine = [p for p in gh_runs[a["id"]] if _gh_status(p[1]) != "skipped"] or gh_runs[a["id"]]
            repo, run = max(mine, key=lambda p: p[1].get("created_at") or "")
            last = _gh_event(a, repo, run)
        cards.append({
            "id": a["id"], "name": a["name"], "kind": a["kind"], "source": a["source"],
            "job": a["job"], "status": last["status"] if last else "never",
            "last": last, "can_run": a["id"] in BACKEND_RUN or bool(a.get("dispatch")),
        })
    feed.sort(key=lambda e: e.get("at") or "", reverse=True)
    warnings = [_gh_problem["text"]] if _gh_problem["text"] else []
    return {"generated_at": now.isoformat(), "agents": cards, "feed": feed[:60],
            "today": tally(feed, drafted_today, now), "warnings": warnings}


async def run(agent_id: str) -> Dict[str, Any]:
    """Run a backend agent now, or dispatch a GitHub agent's workflow."""
    if agent_id in BACKEND_RUN:
        mod, fn = BACKEND_RUN[agent_id]
        try:
            module = __import__(mod)
        except ImportError:
            return {"ok": False, "error": f"{agent_id} is not deployed yet"}
        result = await getattr(module, fn)()
        return {"ok": bool(result.get("ok", True)) and not result.get("skipped"), "result": result}
    agent = next((a for a in AGENTS if a["id"] == agent_id), None)
    if not agent or not agent.get("dispatch"):
        return {"ok": False, "error": "This agent starts on its own event and has no Run now."}
    repo, wf = agent["dispatch"]
    ref = "module-system" if repo == FE else "main"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.post(f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/dispatches",
                         headers=_gh_headers(), json={"ref": ref})
    _gh_cache.pop(f"{repo}/{wf}", None)
    if r.status_code == 204:
        return {"ok": True, "result": {"summary": f"Started {agent['name']} on GitHub"}}
    return {"ok": False, "error": f"GitHub said {r.status_code}: {r.text[:200]}"}
