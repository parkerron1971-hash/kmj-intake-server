"""
unfinished_work.py — the Unfinished-work watcher (2026-10-02).

Kevin found 54 open pull requests across the two repos, some six weeks
old, green and never merged, plus a security audit left uncommitted, and
asked: "do we have an agent that watches these, like unfinished work?"
Nothing did. This does, every morning.

WHAT IT GATHERS (both repos)
  ready         open PRs that pass their checks and can merge now
  updated       green PRs that were behind trunk: it brings them up to
                date (GitHub's update-branch) so they are ready too
  conflicts     PRs that conflict with trunk: a person or session must
                resolve them
  failing       PRs whose checks fail
  news          "News draft" PRs waiting on Kevin's yes to publish
  stale         anything open for 14+ days, whatever its state
  migrations    rows in docs/MIGRATIONS.md still marked PENDING
  work log      work-log entries (worklog.py) not marked shipped, and
                anything they list as left undone

WHAT IT DOES WITH IT
  - one GitHub issue, `unfinished-work`, whose body is replaced every
    morning with the current list (so it never piles up comments);
  - a platform_agent_runs row, and one operator-log item when something is
    ready for Kevin's yes, so Business Chief brings it up;
  - GET /platform/unfinished returns the same lists for Mission Control
    and Platform Chief's snapshot.

IT NEVER MERGES, closes, rebases by hand or resolves conflicts. Updating a
green branch is the one write it makes to a PR. Daily 13:00 UTC (9 AM
Eastern), POST /platform/agents/unfinished-work/run on demand. Kill switch:
UNFINISHED_WORK=off.

Uncommitted work on a machine cannot be seen from here; the work-log rule
in CLAUDE.md/AGENTS.md asks a session that stops with uncommitted work to
open a draft PR with its log entry, which this then shows.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from lead_admin import _service_headers, SUPABASE_URL

logger = logging.getLogger("unfinished_work")

AGENT = "unfinished_work"
REPOS = {
    "kmj-intake-server": ("parkerron1971-hash/kmj-intake-server", "main"),
    "solutionist-studio": ("parkerron1971-hash/solutionist-studio", "module-system"),
}
ISSUE_REPO = "parkerron1971-hash/kmj-intake-server"
ISSUE_LABEL = "unfinished-work"
STALE_DAYS = 14
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)
GREEN = ("success", "neutral", "skipped")

LAST: Dict[str, Any] = {}


def enabled() -> bool:
    return (os.environ.get("UNFINISHED_WORK") or "on").strip().lower() not in (
        "0", "off", "false", "no")


def _gh() -> Dict[str, str]:
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    h = {"Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def classify(pr: Dict[str, Any], checks: List[str], now: datetime) -> List[str]:
    """Pure: the buckets one open PR belongs to. `pr` is GitHub's pull
    object (with mergeable_state); `checks` the conclusions of its runs."""
    out: List[str] = []
    title = pr.get("title") or ""
    state = (pr.get("mergeable_state") or "").lower()
    failing = any(c not in GREEN for c in checks if c)   # "" = still running
    if title.startswith("News draft"):
        out.append("news")
    elif pr.get("draft"):
        out.append("draft")
    elif state == "dirty":
        out.append("conflicts")
    elif failing:
        out.append("failing")
    elif state == "behind":
        out.append("behind")
    elif state in ("clean", "unstable", "has_hooks"):
        out.append("ready")
    else:
        out.append("checking")                    # blocked/unknown: still computing
    created = pr.get("created_at")
    if created:
        try:
            age = now - datetime.fromisoformat(created.replace("Z", "+00:00"))
            if age >= timedelta(days=STALE_DAYS):
                out.append("stale")
        except ValueError:
            pass
    return out


def pending_migrations(markdown: str) -> List[str]:
    """Pure: ledger rows in docs/MIGRATIONS.md still marked PENDING."""
    out = []
    for line in (markdown or "").splitlines():
        if line.startswith("|") and "PENDING" in line.upper():
            m = re.search(r"`([^`]+\.sql)`", line)
            if m:
                out.append(m.group(1))
    return out


async def _pr_list(c: httpx.AsyncClient, full: str) -> List[Dict[str, Any]]:
    r = await c.get(f"https://api.github.com/repos/{full}/pulls", headers=_gh(),
                    params={"state": "open", "per_page": 100})
    return r.json() if r.status_code < 400 else []


async def _pr_detail(c: httpx.AsyncClient, full: str, n: int) -> Dict[str, Any]:
    r = await c.get(f"https://api.github.com/repos/{full}/pulls/{n}", headers=_gh())
    return r.json() if r.status_code < 400 else {}


async def _checks(c: httpx.AsyncClient, full: str, sha: str) -> List[str]:
    r = await c.get(f"https://api.github.com/repos/{full}/commits/{sha}/check-runs",
                    headers=_gh(), params={"per_page": 50})
    if r.status_code >= 400:
        return []
    return [(x.get("conclusion") or "") for x in (r.json().get("check_runs") or [])]


async def _update_branch(c: httpx.AsyncClient, full: str, n: int) -> bool:
    r = await c.put(f"https://api.github.com/repos/{full}/pulls/{n}/update-branch",
                    headers=_gh(), json={})
    return r.status_code in (200, 202)


async def _migrations(c: httpx.AsyncClient) -> List[str]:
    full, ref = REPOS["kmj-intake-server"]
    r = await c.get(f"https://api.github.com/repos/{full}/contents/docs/MIGRATIONS.md",
                    headers=_gh(), params={"ref": ref})
    if r.status_code >= 400:
        return []
    try:
        return pending_migrations(base64.b64decode(r.json().get("content") or "").decode("utf-8", "replace"))
    except Exception:
        return []


async def gather(now: Optional[datetime] = None, update: bool = True) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    buckets: Dict[str, List[Dict[str, Any]]] = {
        k: [] for k in ("ready", "updated", "conflicts", "failing", "news", "draft",
                        "checking", "stale")}
    errors: List[str] = []
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        for name, (full, _ref) in REPOS.items():
            try:
                prs = await _pr_list(c, full)
            except Exception as e:
                errors.append(f"{name}: {e}")
                continue
            for p in prs:
                d = await _pr_detail(c, full, p["number"]) or p
                checks = await _checks(c, full, (d.get("head") or {}).get("sha", ""))
                item = {"repo": name, "number": p["number"], "title": p.get("title"),
                        "url": p.get("html_url"), "created_at": (p.get("created_at") or "")[:10]}
                for b in classify(d, checks, now):
                    if b == "behind":
                        ok = update and await _update_branch(c, full, p["number"])
                        buckets["updated" if ok else "checking"].append(item)
                    else:
                        buckets[b].append(item)
        migrations = await _migrations(c)
    log_open: List[Dict[str, Any]] = []
    try:
        import worklog
        items, errs = await worklog.entries()
        errors += errs
        log_open = [worklog.compact(e) for e in items if not e["done"] or e["left_undone"]]
    except Exception as e:
        errors.append(f"work log: {e}")
    return {"generated_at": now.isoformat(), **buckets, "migrations": migrations,
            "work_log_open": log_open, "errors": errors}


def _line(i: Dict[str, Any]) -> str:
    repo = "app" if i["repo"] == "solutionist-studio" else "backend"
    return f"- [{repo} #{i['number']}]({i['url']}) {i['title']} · opened {i['created_at']}"


def render(r: Dict[str, Any]) -> str:
    """Pure: the issue body."""
    def section(title: str, items: List[str], empty: Optional[str] = None) -> List[str]:
        if not items:
            return [f"### {title}", empty, ""] if empty else []
        return [f"### {title} ({len(items)})", *items, ""]

    out = [f"Updated {r['generated_at'][:16].replace('T', ' ')} UTC. This list is rewritten every "
           "morning; nothing here was merged, closed or changed except bringing green PRs up to date.",
           ""]
    out += section("Ready for your yes (green, can merge now)", [_line(i) for i in r["ready"]],
                   "Nothing waiting.")
    out += section("Brought up to date this morning (merge once checks pass)",
                   [_line(i) for i in r["updated"]])
    out += section("News drafts waiting on you", [_line(i) for i in r["news"]])
    out += section("Conflicts: need a session to resolve", [_line(i) for i in r["conflicts"]])
    out += section("Failing checks", [_line(i) for i in r["failing"]])
    # The ledger is hand-kept and its PENDING marks drift (three applied
    # migrations still read PENDING on 2026-10-02), so this says what the
    # ledger says, not that the database lacks them.
    out += section("Marked PENDING in docs/MIGRATIONS.md (check whether applied, then update the row)",
                   [f"- `{m}`" for m in r["migrations"]])
    out += section("Open in the work log", [
        f"- **{e['title']}** ({e['date']}, {e['status']})"
        + (f": left undone: {'; '.join(e['left_undone'])}" if e["left_undone"] else "")
        for e in r["work_log_open"]])
    stale = r["stale"]
    if stale:
        out += section(f"Open {STALE_DAYS}+ days", [_line(i) for i in stale])
    if r["errors"]:
        out += ["Could not read: " + "; ".join(r["errors"]), ""]
    return "\n".join(out)


async def _publish_issue(body: str, title: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(f"https://api.github.com/repos/{ISSUE_REPO}/issues", headers=_gh(),
                        params={"state": "open", "labels": ISSUE_LABEL, "per_page": 5})
        existing = r.json() if r.status_code < 400 else []
        if existing:
            n = existing[0]["number"]
            await c.patch(f"https://api.github.com/repos/{ISSUE_REPO}/issues/{n}", headers=_gh(),
                          json={"title": title, "body": body})
            return existing[0].get("html_url")
        r = await c.post(f"https://api.github.com/repos/{ISSUE_REPO}/issues", headers=_gh(),
                         json={"title": title, "body": body, "labels": [ISSUE_LABEL]})
        return r.json().get("html_url") if r.status_code < 400 else None


async def watch_tick() -> Dict[str, Any]:
    """One morning pass. Never raises (scheduler-safe)."""
    if not enabled():
        return {"skipped": True}
    started = datetime.now(timezone.utc)
    headers = _service_headers()
    try:
        r = await gather(now=started)
        LAST.clear()
        LAST.update(r)
        counts = {k: len(r[k]) for k in ("ready", "updated", "news", "conflicts", "failing",
                                         "stale", "migrations", "work_log_open")}
        ready = counts["ready"] + counts["updated"]
        title = (f"Unfinished work: {ready} ready for your yes, {counts['news']} news drafts, "
                 f"{counts['conflicts']} conflicting, {counts['migrations']} migrations pending")
        url = None
        if (os.environ.get("GITHUB_TOKEN") or "").strip():
            url = await _publish_issue(render(r), title)
        summary = title.removeprefix("Unfinished work: ")
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            if ready or counts["news"] or counts["migrations"]:
                await c.post(f"{SUPABASE_URL}/rest/v1/platform_changelog",
                             headers={**headers, "Prefer": "return=minimal"},
                             json={"category": "pending", "status": "pending", "agent": AGENT,
                                   "title": f"Unfinished work: {summary}"[:300],
                                   "detail": (f"The full list: {url}" if url else "")[:2000]})
            await c.post(f"{SUPABASE_URL}/rest/v1/platform_agent_runs",
                         headers={**headers, "Prefer": "return=minimal"},
                         json={"agent": AGENT, "started_at": started.isoformat(),
                               "finished_at": datetime.now(timezone.utc).isoformat(),
                               "ok": True, "findings": ready, "summary": summary[:500],
                               "details": {**counts, "issue": url, "errors": r["errors"]}})
        return {"ok": True, "summary": summary, "issue": url, **counts}
    except Exception as e:
        logger.error(f"watch tick failed: {e}")
        return {"ok": False, "error": str(e)[:300]}
