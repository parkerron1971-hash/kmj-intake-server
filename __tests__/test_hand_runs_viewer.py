"""GET /agents/chief/hand/runs — what the browser hand did, frame by frame.

Pins: scoped by the caller's user AND the business; only browser_hand
jobs; every frame becomes a signed link minted from the private bucket
(never a public path); the task and sites come from the result, or from
the approved spec while the run is still going; a broken signing helper
costs the link, not the run.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_jobs
import storage_links
import browser_hand


class _Session:
    class user:
        id = "own-1"


def _rows():
    return [
        {"id": "job-1", "status": "done", "error": None, "created_at": "2026-09-04T10:00:00Z",
         "started_at": None, "finished_at": "2026-09-04T10:01:00Z",
         "params": {"spec": {"task": "Find the renewal date", "domains": ["portal.example"]}, "queue_id": "q-1"},
         "result": {"ok": True, "stopped": "done", "summary": "Renews 2027-01-15", "task": "Find the renewal date",
                    "domains": ["portal.example"], "frames": 2,
                    "steps": [{"n": 1, "url": "https://portal.example/x", "action": {"action": "click", "x": 1, "y": 2},
                               "note": None, "frame": "biz-1/hand/job-1/01.jpg"},
                              {"n": 2, "url": "https://portal.example/y", "action": {"action": "done", "summary": "ok"},
                               "note": None, "frame": None}]}},
        {"id": "job-2", "status": "running", "error": None, "created_at": "2026-09-04T11:00:00Z",
         "started_at": None, "finished_at": None,
         "params": {"spec": {"task": "Check the supplier price list", "domains": ["supplier.example"]}},
         "result": None},
    ]


def test_runs_are_scoped_signed_and_shaped(monkeypatch):
    seen = []

    async def _sb(client, method, path, body=None):
        seen.append(path)
        return _rows()
    monkeypatch.setattr(chief_jobs, "_sb", _sb)
    monkeypatch.setattr(storage_links, "signed_url_sync",
                        lambda bucket, path, ttl=3600, download_as=None: f"https://signed/{bucket}/{path}?ttl={ttl}")

    out = asyncio.run(chief_jobs.hand_runs("biz-1", 5, _Session(), _biz={"id": "biz-1"}))
    q = seen[0]
    assert "user_id=eq.own-1" in q and "business_id=eq.biz-1" in q and "kind=eq.browser_hand" in q
    assert "limit=5" in q
    runs = out["runs"]
    assert [r["id"] for r in runs] == ["job-1", "job-2"]
    done = runs[0]
    assert done["task"] == "Find the renewal date" and done["stopped"] == "done" and done["ok"] is True
    assert done["queue_id"] == "q-1" and done["domains"] == ["portal.example"]
    assert done["steps"][0]["frame_url"] == f"https://signed/{browser_hand.FRAME_BUCKET}/biz-1/hand/job-1/01.jpg?ttl=3600"
    assert done["steps"][1]["frame_url"] is None
    assert "/object/public/" not in str(out)
    running = runs[1]
    assert running["task"] == "Check the supplier price list", "the spec speaks while the run is still going"
    assert running["domains"] == ["supplier.example"] and running["steps"] == []


def test_a_broken_signer_costs_the_link_not_the_run(monkeypatch):
    async def _sb(client, method, path, body=None):
        return _rows()[:1]
    monkeypatch.setattr(chief_jobs, "_sb", _sb)

    def boom(*a, **k):
        raise RuntimeError("storage down")
    monkeypatch.setattr(storage_links, "signed_url_sync", boom)
    out = asyncio.run(chief_jobs.hand_runs("biz-1", 10, _Session(), _biz={"id": "biz-1"}))
    assert out["runs"][0]["steps"][0]["frame_url"] is None
    assert out["runs"][0]["summary"] == "Renews 2027-01-15"


def test_the_route_is_guarded_by_business_access():
    import inspect
    sig = inspect.signature(chief_jobs.hand_runs)
    assert "_biz" in sig.parameters, "business_access is the guard the ratchet counts"


def test_no_user_no_runs():
    class _NoUser:
        user = None
    assert asyncio.run(chief_jobs.hand_runs("biz-1", 10, _NoUser(), _biz={"id": "biz-1"})) == {"runs": []}
