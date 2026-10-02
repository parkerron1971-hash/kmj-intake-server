"""
worklog.py — the work log: what every building session did (2026-10-02).

Kevin's ask: "when I am working on something that Codex or Claude Code
[works on], it leaves a summary from that project with the PRs, so we can
match and determine if we should build or not."

THE LOG lives in each repo as `worklog/YYYY-MM-DD-<slug>.md`, one file per
piece of work, written by the session that did it (the rule is in
CLAUDE.md and AGENTS.md in both repos; the format is worklog/README.md):

    ---
    title: Support desk drafts replies
    date: 2026-10-02
    agent: Claude Code (Claude Opus 5.5)
    asked: "start wave 3"
    status: shipped            # shipped | in progress | stopped | waiting on Kevin
    prs: [kmj-intake-server#1177, solutionist-studio#1087]
    migrations: [supabase/APPLY-2026-10-02-support-drafts.sql (applied)]
    left_undone: []
    decisions: ["drafts never send; a person presses Send"]
    ---
    What was built, why, and what to check before building more.

THIS MODULE reads both repos' logs from their trunks through the GitHub
API (the backend's GITHUB_TOKEN already reaches both), parses them, and
answers two questions: what is the log (newest first), and what in it
matches a phrase ("have we built a refund flow?"). Platform Chief's
snapshot carries the index, and the unfinished-work watcher reads the
`status` and `left_undone` fields.

Read-only. Cached for 15 minutes. Never raises: a repo that cannot be read
is reported, not hidden.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
import yaml

logger = logging.getLogger("worklog")

REPOS = {
    "kmj-intake-server": ("parkerron1971-hash/kmj-intake-server", "main"),
    "solutionist-studio": ("parkerron1971-hash/solutionist-studio", "module-system"),
}
CACHE_SECONDS = 900
DONE = ("shipped", "done", "merged")
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

_cache: Dict[str, Any] = {"at": 0.0, "entries": None, "errors": []}
_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
_WORD = re.compile(r"[a-z0-9]+")


def _headers() -> Dict[str, str]:
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    h = {"Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if str(x).strip()]
    return [str(v)] if str(v).strip() else []


def parse_entry(text: str, repo: str, path: str) -> Optional[Dict[str, Any]]:
    """Pure: one log file → an entry, or None if it has no front matter."""
    m = _FRONT.match(text or "")
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict) or not meta.get("title"):
        return None
    status = str(meta.get("status") or "").strip().lower()
    return {
        "repo": repo,
        "path": path,
        "title": str(meta["title"]).strip(),
        "date": str(meta.get("date") or "")[:10],
        "agent": str(meta.get("agent") or "").strip(),
        "asked": str(meta.get("asked") or "").strip(),
        "status": status or "unknown",
        "done": status in DONE,
        "prs": _as_list(meta.get("prs")),
        "migrations": _as_list(meta.get("migrations")),
        "left_undone": _as_list(meta.get("left_undone")),
        "decisions": _as_list(meta.get("decisions")),
        "related": _as_list(meta.get("related")),
        "body": (m.group(2) or "").strip()[:4000],
    }


async def _read_repo(c: httpx.AsyncClient, name: str, full: str,
                     ref: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    r = await c.get(f"https://api.github.com/repos/{full}/contents/worklog",
                    headers=_headers(), params={"ref": ref})
    if r.status_code == 404:
        return [], None                      # no log yet in this repo
    if r.status_code >= 400:
        return [], f"{name}: {r.status_code}"
    out = []
    for f in r.json() or []:
        if f.get("type") != "file" or not str(f.get("name", "")).endswith(".md") \
                or f.get("name", "").lower() == "readme.md":
            continue
        fr = await c.get(f"https://api.github.com/repos/{full}/contents/{f['path']}",
                         headers=_headers(), params={"ref": ref})
        if fr.status_code >= 400:
            continue
        try:
            text = base64.b64decode(fr.json().get("content") or "").decode("utf-8", "replace")
        except Exception:
            continue
        entry = parse_entry(text, name, f["path"])
        if entry:
            out.append(entry)
    return out, None


async def entries(force: bool = False) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Every log entry from both repos, newest first, plus read errors."""
    if not force and _cache["entries"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["entries"], _cache["errors"]
    found: List[Dict[str, Any]] = []
    errors: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            for name, (full, ref) in REPOS.items():
                try:
                    got, err = await _read_repo(c, name, full, ref)
                    found += got
                    if err:
                        errors.append(err)
                except Exception as e:
                    errors.append(f"{name}: {e}")
    except Exception as e:
        errors.append(str(e))
    found.sort(key=lambda e: (e["date"], e["title"]), reverse=True)
    _cache.update(at=time.time(), entries=found, errors=errors)
    return found, errors


def search(items: List[Dict[str, Any]], query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Pure: entries that match a phrase, best first. Word overlap over the
    title, the ask, decisions, what was left and the body — enough to
    answer "did we already build or start this?" without a model."""
    words = {w for w in _WORD.findall((query or "").lower()) if len(w) > 2}
    if not words:
        return []
    scored = []
    for e in items:
        hay_title = set(_WORD.findall(e["title"].lower()))
        hay = set(_WORD.findall(" ".join([e["title"], e["asked"], e["body"],
                                          *e["decisions"], *e["left_undone"]]).lower()))
        score = 3 * len(words & hay_title) + len(words & hay)
        if score:
            scored.append((score, e))
    scored.sort(key=lambda x: (x[0], x[1]["date"]), reverse=True)
    return [e for _, e in scored[:limit]]


def compact(e: Dict[str, Any]) -> Dict[str, Any]:
    """The few fields Platform Chief's snapshot carries per entry."""
    return {"title": e["title"], "date": e["date"], "repo": e["repo"],
            "status": e["status"], "prs": e["prs"][:6],
            "left_undone": e["left_undone"][:4], "asked": e["asked"][:160]}
