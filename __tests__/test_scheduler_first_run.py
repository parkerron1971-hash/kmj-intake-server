"""Long-interval jobs actually fire.

APScheduler schedules an interval job's FIRST run at now + interval, and
that clock restarts with the process. On a repo that deploys several
times a day, a 24-hour job is reset before it ever fires — it exists, it
is registered, it appears in the job list, and it never runs once.

stripe_usage_report is a 24-hour job, which means metered usage was not
reaching Stripe. Two jobs had been fixed by passing next_run_time at the
call site; the other eighteen had not.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

pytest.importorskip("apscheduler")

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import kmj_intake_automation as kia


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def _noop():
    pass


@pytest.fixture
def sched():
    s = BackgroundScheduler()
    yield s
    try:
        s.shutdown(wait=False)
    except Exception:
        pass


def _add(s, job_id, **interval):
    return s.add_job(_noop, "interval", id=job_id, **interval)


class TestStaggering:
    def test_a_daily_job_gets_a_first_run_soon(self, sched):
        _add(sched, "stripe_usage_report", hours=24)
        moved = kia.stagger_long_interval_first_runs(sched, now=NOW)
        assert "stripe_usage_report" in moved
        job = sched.get_job("stripe_usage_report")
        assert job.next_run_time - NOW < timedelta(minutes=30)

    def test_a_weekly_job_gets_one_too(self, sched):
        """168 hours — realistically this had never run."""
        _add(sched, "vertical_seed", hours=168)
        assert "vertical_seed" in kia.stagger_long_interval_first_runs(sched, now=NOW)

    def test_short_intervals_are_left_alone(self, sched):
        """A 5-minute job fires 5 minutes after boot; the deploy clock
        is irrelevant to it."""
        _add(sched, "workflow_drain", minutes=5)
        _add(sched, "gl_drain", minutes=1)
        assert kia.stagger_long_interval_first_runs(sched, now=NOW) == []

    def test_a_deliberate_first_run_is_not_overwritten(self, sched):
        """ledger_anchor_sweep sets next_run_time by hand with a comment
        explaining exactly why 3 minutes. That reasoning must survive."""
        deliberate = NOW + timedelta(minutes=3)
        sched.add_job(_noop, "interval", hours=6, id="ledger_anchor_sweep",
                      next_run_time=deliberate)
        moved = kia.stagger_long_interval_first_runs(sched, now=NOW)
        assert "ledger_anchor_sweep" not in moved
        assert sched.get_job("ledger_anchor_sweep").next_run_time == deliberate

    def test_runs_are_staggered_not_simultaneous(self, sched):
        for i in range(5):
            _add(sched, f"daily_{i}", hours=24)
        kia.stagger_long_interval_first_runs(sched, now=NOW)
        times = [sched.get_job(f"daily_{i}").next_run_time for i in range(5)]
        assert len(set(times)) == 5, "a boot must not fire everything at once"

    def test_cron_jobs_are_untouched(self, sched):
        """They already have a real wall-clock time."""
        sched.add_job(_noop, "cron", hour=13, minute=0, id="push_morning_brief")
        assert kia.stagger_long_interval_first_runs(sched, now=NOW) == []

    def test_it_is_idempotent_across_boots(self, sched):
        """Two calls must not push the job further out each time."""
        _add(sched, "daily", hours=24)
        kia.stagger_long_interval_first_runs(sched, now=NOW)
        first = sched.get_job("daily").next_run_time
        kia.stagger_long_interval_first_runs(sched, now=NOW)
        assert sched.get_job("daily").next_run_time == first

    def test_an_empty_scheduler_is_fine(self, sched):
        assert kia.stagger_long_interval_first_runs(sched, now=NOW) == []


class TestTheRealRegistration:
    def test_startup_calls_it_before_start(self):
        """Ordering matters: modifying a job after the scheduler is
        running is a different code path with different behaviour."""
        import inspect
        src = inspect.getsource(kia.startup)
        assert "stagger_long_interval_first_runs(scheduler)" in src
        assert (src.index("stagger_long_interval_first_runs(scheduler)")
                < src.index("scheduler.start()"))

    def test_threshold_sits_between_the_two_populations(self):
        """Above the frequent drains, below the daily reports."""
        assert 5 < kia.STAGGER_THRESHOLD_MINUTES <= 60


class TestCronJobsAreImmuneToTheDeployReset:
    """The stagger shrinks the starvation window; it does not close it.

    Slots are STAGGER_SLOT_MINUTES apart and CUMULATIVE, so a job late in
    the registration order gets ~20-25 minutes rather than two. On
    2026-08-31 the production worker armed twelve jobs; `vertical_curate`
    was eleventh, came due at 11:16:32, and a merge redeployed the worker
    at 11:16:09 — twenty-three seconds early. Its sibling `vertical_seed`,
    one slot ahead, fired and wrote its rows.

    A cron trigger carries a real wall-clock time, so a redeploy cannot
    reset it. These tests pin the two halves of that: the stagger leaves
    cron jobs alone, and the two projection jobs are actually cron.
    """

    def test_the_stagger_does_not_touch_a_cron_job(self, sched):
        """A pending job has no next_run_time until something sets one, so
        the assertion is that the stagger neither reports the cron job nor
        gives it one — the wall-clock trigger keeps owning the schedule."""
        from apscheduler.triggers.cron import CronTrigger

        sched.add_job(_noop, CronTrigger(hour=4, minute=20), id="nightly")
        _add(sched, "weekly_interval", hours=168)

        moved = kia.stagger_long_interval_first_runs(sched, now=NOW)

        assert "nightly" not in moved
        assert "weekly_interval" in moved, "the control job must still be moved"
        nightly = sched.get_job("nightly")
        assert isinstance(nightly.trigger, CronTrigger)
        assert getattr(nightly, "next_run_time", None) is None, (
            "the stagger gave a cron job a next_run_time, which would "
            "override the wall-clock time that makes it deploy-proof")

    def test_a_late_slot_interval_job_really_does_wait_20_plus_minutes(self, sched):
        """The number that made this worth changing. Twelve long-interval
        jobs put the eleventh over twenty minutes out — long enough for a
        merge to land on top of it."""
        for i in range(12):
            _add(sched, f"job{i}", hours=168)
        kia.stagger_long_interval_first_runs(sched, now=NOW)
        eleventh = sched.get_job("job10").next_run_time
        assert (eleventh - NOW) >= timedelta(minutes=20), (
            f"eleventh slot is only {(eleventh - NOW)} out — if the slot "
            f"width changed, the reasoning in the vertical_seed/"
            f"vertical_curate comment needs revisiting")

    def test_the_two_projection_jobs_are_registered_as_cron(self):
        """A tripwire, not a proof: if someone converts these back to an
        interval trigger, the deploy-reset starvation comes back and the
        symptom is silence — the rows simply never appear, which is
        indistinguishable from nothing new to write."""
        import inspect
        src = inspect.getsource(kia.startup)
        for job_id in ("vertical_seed", "vertical_curate"):
            assert f'id="{job_id}"' in src, f"{job_id} is not registered"
            # The add_job call for this id must say "cron", not "interval".
            call_start = src.rindex("scheduler.add_job", 0, src.index(f'id="{job_id}"'))
            call = src[call_start:src.index(f'id="{job_id}"')]
            assert '"cron"' in call, f"{job_id} is not a cron job"
            assert '"interval"' not in call, f"{job_id} is back on an interval trigger"
