"""Agents at work: GitHub and backend agents on one screen, in plain words."""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import agents_live as al

NOW = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
AG = {a["id"]: a for a in al.AGENTS}


def run(status="completed", conclusion="success", title="Support Tickets on the real queue", at="2026-10-02T14:00:00Z"):
    return {"status": status, "conclusion": conclusion, "display_title": title,
            "created_at": at, "html_url": "https://github.com/x/runs/1"}


def test_github_runs_read_as_plain_words():
    e = al._gh_event(AG["pr_reviewer"], al.FE, run())
    assert e["text"] == "Reviewed app PR: Support Tickets on the real queue" and e["status"] == "clear"
    e = al._gh_event(AG["deploy_checker"], al.BE, run(conclusion="failure"))
    assert e["text"] == "The backend deploy did not go live" and e["status"] == "failed"
    e = al._gh_event(AG["on_call"], al.BE, run(status="in_progress", conclusion=None))
    assert e["status"] == "running" and e["text"] == "Investigating an incident"


def test_backend_runs_light_up_by_outcome():
    names = {"money_auditor": "Money auditor"}
    assert al._be_event({"agent": "money_auditor", "ok": True, "findings": 2, "summary": "s"}, names)["status"] == "found"
    assert al._be_event({"agent": "money_auditor", "ok": True, "findings": 0}, names)["status"] == "clear"
    assert al._be_event({"agent": "money_auditor", "ok": False}, names)["status"] == "failed"


def test_tally_counts_today_only():
    feed = [{"agent": "pr_reviewer", "status": "clear", "at": "2026-10-02T10:00:00Z"},
            {"agent": "pr_reviewer", "status": "clear", "at": "2026-10-01T10:00:00Z"},
            {"agent": "deploy_checker", "status": "clear", "at": "2026-10-02T11:00:00Z"},
            {"agent": "money_auditor", "status": "found", "at": "2026-10-02T10:00:00Z"},
            {"agent": "uptime", "status": "failed", "at": "2026-10-02T09:00:00Z"}]
    runs = [{"agent": "support_desk", "started_at": "2026-10-02T08:00:00Z", "details": {"drafted": 3}},
            {"agent": "support_desk", "started_at": "2026-10-01T08:00:00Z", "details": {"drafted": 9}}]
    assert al.tally(feed, runs, NOW) == {"drafts_written": 3, "prs_reviewed": 1, "deploys_verified": 1,
                                         "findings_raised": 1, "failed_runs": 1}


class _Resp:
    def __init__(self, body, status=200):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


class FakeAll:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        if "platform_agent_runs" in url:
            return _Resp([{"agent": "money_auditor", "started_at": "2026-10-02T10:00:00Z",
                           "finished_at": "2026-10-02T10:00:05Z", "ok": True, "findings": 1,
                           "summary": "1 business past due", "details": {}}])
        if "pr-review.yml" in url:
            return _Resp({"workflow_runs": [run()]})
        return _Resp({"workflow_runs": []})


def test_snapshot_puts_every_agent_on_one_screen(monkeypatch):
    al._gh_cache.clear()
    monkeypatch.setattr(al, "_service_headers", lambda: {})
    monkeypatch.setattr(al.httpx, "AsyncClient", lambda **kw: FakeAll())
    snap = asyncio.run(al.snapshot(now=NOW))
    cards = {c["id"]: c for c in snap["agents"]}
    assert len(cards) == len(al.AGENTS)
    assert cards["money_auditor"]["status"] == "found"
    assert cards["pr_reviewer"]["status"] == "clear"
    assert cards["support_desk"]["status"] == "never"
    assert cards["on_call"]["can_run"] is False and cards["security_steward"]["can_run"] is True
    assert any(e["text"].startswith("Reviewed app PR") for e in snap["feed"])
    assert snap["feed"][0]["at"] >= snap["feed"][-1]["at"], "newest first"


def test_run_now_refuses_event_only_agents():
    out = asyncio.run(al.run("pr_reviewer"))
    assert out["ok"] is False and "own event" in out["error"]


class FakeRejected(FakeAll):
    async def get(self, url, headers=None, params=None):
        if "platform_agent_runs" in url:
            return _Resp([{"agent": "support_desk", "started_at": f"2026-10-02T0{i}:00:00Z", "ok": True,
                           "findings": 0, "summary": "no customer tickets waiting on a draft"} for i in range(9, 0, -1)])
        return _Resp({"message": "Bad credentials"}, 401)


def test_a_rejected_github_token_is_said_plainly_and_quiet_runs_do_not_flood(monkeypatch):
    al._gh_cache.clear()
    monkeypatch.setattr(al, "_service_headers", lambda: {})
    monkeypatch.setattr(al.httpx, "AsyncClient", lambda **kw: FakeRejected())
    snap = asyncio.run(al.snapshot(now=NOW))
    assert snap["warnings"] and "GITHUB_TOKEN" in snap["warnings"][0]
    assert sum(1 for e in snap["feed"] if e["agent"] == "support_desk") == 1
