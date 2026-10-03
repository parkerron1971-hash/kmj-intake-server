"""THE SILENT CALL (2026-10-03, live test on Vertical Test Coach).

A builder call on Opus 5.5 ran 5.5 minutes with no progress ping. The
heartbeat only rode the pings, so the scheduler replica's orphan sweep
(which cannot see the web process's _INFLIGHT) marked a healthy build
"interrupted by a server restart" at 5.6 minutes. The runner now beats on
its own clock for the whole life of the job.
"""
import asyncio
import time

import chief_jobs


def test_the_beat_is_well_inside_the_stale_window():
    assert chief_jobs.HEARTBEAT_EVERY_S * 3 <= chief_jobs.HEARTBEAT_STALE_MIN * 60


def test_a_long_silent_job_keeps_beating_and_stops_when_done(monkeypatch):
    stamps = []
    monkeypatch.setattr(chief_jobs, "HEARTBEAT_EVERY_S", 0.02)
    monkeypatch.setattr(chief_jobs, "_stamp_heartbeat",
                        lambda job_id: stamps.append((job_id, time.monotonic())))

    async def silent_job(job_id, user_id, business_id, kind, params, meta):
        # one long model call: no progress pings at all
        assert job_id in chief_jobs._INFLIGHT
        await asyncio.sleep(0.25)

    monkeypatch.setattr(chief_jobs, "_run_inner", silent_job)
    monkeypatch.setattr(chief_jobs.sb_clients, "clear_user_jwt", lambda: None)

    async def go():
        await chief_jobs._run("job-1", "u1", "b1", "rebuild_site", {})
        done_at = time.monotonic()
        await asyncio.sleep(0.1)          # the beat must not outlive the job
        return done_at

    done_at = asyncio.run(go())
    assert len(stamps) >= 5, stamps
    assert all(j == "job-1" for j, _ in stamps)
    assert all(t <= done_at for _, t in stamps)
    assert "job-1" not in chief_jobs._INFLIGHT


def test_a_failed_stamp_never_breaks_the_job(monkeypatch):
    monkeypatch.setattr(chief_jobs, "HEARTBEAT_EVERY_S", 0.01)

    def boom(job_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(chief_jobs, "_stamp_heartbeat", boom)
    ran = {}

    async def job(job_id, user_id, business_id, kind, params, meta):
        await asyncio.sleep(0.05)
        ran["ok"] = True

    monkeypatch.setattr(chief_jobs, "_run_inner", job)
    monkeypatch.setattr(chief_jobs.sb_clients, "clear_user_jwt", lambda: None)
    asyncio.run(chief_jobs._run("job-2", "u1", "b1", "rebuild_site", {}))
    assert ran == {"ok": True}
