"""The worker can be split off the web process — and the split cannot
silently stop the work.

WHAT THIS FIXES. Every replica ran the full scheduler. Twenty jobs times
N replicas, all firing at once, with a lease as the only thing stopping
them from doing the same work twice — and a job that takes longer than
the lease, or a lease read that fails, turns that into duplicate sends.
Scaling the web tier to survive traffic and scaling the number of copies
of the nightly sweep were the same dial, which is the actual bug.

WHAT THE SPLIT MAKES POSSIBLE, AND WHY THE ALARM MATTERS MORE THAN THE
SPLIT. Once a process can decline to run jobs, an operator can set every
service to `web`, never create the worker, and the scheduled work stops
while every health check stays green. Each replica is genuinely healthy
and honestly reports that it does not run jobs — nothing looking at one
process can tell the difference between "I don't run jobs because
somebody else does" and "I don't run jobs and neither does anyone."

Only the shared lease can answer that, which is why `lease_is_fresh`
exists and why the external monitor reads it. And why it returns None,
never False, when it does not know: a monitor that pages on "unknown"
gets muted, and a muted monitor is the outage.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
import sys
import textwrap

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import scheduler_lock

APP = pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py"
SRC = APP.read_text(encoding="utf-8")


def _code(src: str) -> str:
    """Executable code only — comments and docstrings discarded.

    Assertions about what code DOES have to read code. Matching raw
    source matches the prose explaining the code, and this file is
    heavily commented on purpose.
    """
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _role_fns():
    """The two functions under test, evaluated in isolation.

    Importing kmj_intake_automation would start the app. Lifting the
    function definitions out of the module source runs the real code
    without the 200-odd imports behind it.
    """
    tree = ast.parse(SRC)
    wanted = {"process_role", "runs_scheduled_jobs"}
    picked = [n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {n.name for n in picked} == wanted, "role helpers are not module-level"
    ns: dict = {"os": importlib.import_module("os")}
    exec(compile(ast.Module(body=picked, type_ignores=[]), "<roles>", "exec"), ns)
    return ns


class TestTheDefaultChangesNothing:
    """The single most important property here. This ships to a running
    system where no service has PROCESS_ROLE set, and if an unset
    variable meant anything other than "behave exactly as before", the
    deploy itself would stop every scheduled job."""

    def test_unset_means_all(self, monkeypatch):
        monkeypatch.delenv("PROCESS_ROLE", raising=False)
        ns = _role_fns()
        assert ns["process_role"]() == "all"
        assert ns["runs_scheduled_jobs"]() is True

    def test_empty_means_all(self, monkeypatch):
        """Railway writes an empty string for a variable someone cleared
        rather than deleting. Empty must not be a fourth behaviour."""
        monkeypatch.setenv("PROCESS_ROLE", "")
        ns = _role_fns()
        assert ns["process_role"]() == "all"
        assert ns["runs_scheduled_jobs"]() is True

    def test_a_typo_means_all(self, monkeypatch):
        """`PROCESS_ROLE=Worker ` with a stray space or capital, or an
        outright misspelling, must fail toward RUNNING the jobs. The
        failure mode of running them twice is caught by the lease; the
        failure mode of nobody running them is an outage."""
        for bad in ("wrker", "web-1", "  ", "workers", "none"):
            monkeypatch.setenv("PROCESS_ROLE", bad)
            ns = _role_fns()
            assert ns["process_role"]() == "all", bad
            assert ns["runs_scheduled_jobs"]() is True, bad


class TestTheRolesDoWhatTheySay:
    @pytest.mark.parametrize("role,runs", [
        ("web", False), ("worker", True), ("all", True),
    ])
    def test_only_web_declines(self, monkeypatch, role, runs):
        monkeypatch.setenv("PROCESS_ROLE", role)
        ns = _role_fns()
        assert ns["process_role"]() == role
        assert ns["runs_scheduled_jobs"]() is runs

    def test_case_and_whitespace_are_forgiven(self, monkeypatch):
        """`PROCESS_ROLE=Web` typed into a dashboard field must not
        silently become `all` and start a second scheduler."""
        for spelling in ("WEB", " web", "Web  "):
            monkeypatch.setenv("PROCESS_ROLE", spelling)
            ns = _role_fns()
            assert ns["process_role"]() == "web", spelling
            assert ns["runs_scheduled_jobs"]() is False, spelling


class TestTheSchedulerIsActuallyGated:
    def test_start_is_behind_the_check(self):
        """Registration still happens on every replica — an APScheduler
        that was never started runs nothing, so gating `.start()` is
        sufficient, and the alternative (maintaining a second list of
        which jobs a web replica may register) is a list that drifts."""
        assert "if runs_scheduled_jobs():" in SRC
        i = SRC.index("if runs_scheduled_jobs():")
        assert "scheduler.start()" in SRC[i:i + 300]

    def test_start_is_not_ALSO_called_unconditionally(self):
        """The gate is worthless if a second bare `scheduler.start()`
        survives somewhere else in the file."""
        code = _code(SRC)
        assert code.count("scheduler.start()") == 1

    def test_a_web_replica_says_so_out_loud(self):
        """Silence here is how the bad configuration hides. The startup
        log has to state that this process runs no jobs."""
        i = SRC.index("if runs_scheduled_jobs():")
        near = SRC[i:i + 700]
        assert "scheduler NOT started" in near
        assert "NOTHING is scheduled" in near

    def test_shutdown_does_not_explode_when_it_never_started(self):
        """APScheduler raises SchedulerNotRunningError on shutdown of a
        scheduler that was never started. Every web replica would then
        log a crash on every deploy — noise that trains people to ignore
        shutdown errors."""
        src = SRC[SRC.index("async def shutdown"):]
        src = src[:src.index("\n@") if "\n@" in src[10:] else 400]
        assert "scheduler.running" in src


class TestReadinessReportsTheNewFacts:
    def test_it_reports_the_role(self):
        assert '"role"' in SRC or "'role'" in SRC

    def test_it_reports_the_lease(self):
        assert "scheduler_lease_fresh" in SRC

    def test_a_stale_lease_does_NOT_fail_readiness(self):
        """This is deliberate and worth pinning. /health/ready answers
        "can THIS replica serve traffic". A web replica serves traffic
        perfectly well while the worker is down, and folding the lease
        into `ready` would make Railway pull healthy web replicas out of
        rotation over a background-job problem — turning a partial
        outage into a total one.

        The lease is REPORTED so the external monitor can page on it.
        """
        i = SRC.index("scheduler_lease_fresh")
        window = SRC[max(0, i - 900):i + 400]
        # the ready verdict is computed from the hard dependency only
        assert 'checks["scheduler_lease_fresh"]' in window
        ready_lines = [ln for ln in window.splitlines()
                       if "ready" in ln and "=" in ln and "lease" in ln]
        assert not ready_lines, f"lease folded into the ready verdict: {ready_lines}"


class TestAWebReplicaIsReadyWithoutAScheduler:
    """The bug this class exists for was in the line the split did NOT
    touch.

    `ready = supabase_ok and scheduler.running` was correct while every
    process ran the scheduler, and became a trap the moment one could
    decline to: PROCESS_ROLE=web makes scheduler.running false BY
    DESIGN, so readiness would 503, Railway's healthcheck would fail,
    and the entire web tier would never come up. The change meant to
    stop twenty schedulers would have taken the front door down instead.

    It was missed by checking only the fields the split ADDED — the new
    lease field correctly stays out of the verdict, which is what the
    first pass verified. The pre-existing term was the one that broke.
    """

    @staticmethod
    def _ready_expr():
        """The real assignments from health_ready, evaluated in a
        namespace we control. Reading the truth table off the shipped
        expression, not off a paraphrase of it in this file."""
        lines = [ln.strip() for ln in SRC.splitlines()]
        got = [ln for ln in lines
               if ln.startswith("scheduler_ok =") or ln.startswith("ready = ")]
        assert got, "readiness verdict not found"
        return got

    @pytest.mark.parametrize("role,sched_running,expect_ready", [
        # a web replica, correctly running no scheduler
        ("web", False, True),
        # a worker whose scheduler died — a real outage, must 503
        ("worker", False, False),
        ("all", False, False),
        # everything healthy
        ("web", True, True),
        ("worker", True, True),
        ("all", True, True),
    ])
    def test_the_truth_table(self, monkeypatch, role, sched_running, expect_ready):
        monkeypatch.setenv("PROCESS_ROLE", role)
        ns = _role_fns()

        class _Sched:
            running = sched_running

        env = {"scheduler": _Sched(), "supabase_ok": True,
               "runs_scheduled_jobs": ns["runs_scheduled_jobs"]}
        for line in self._ready_expr():
            exec(line, env)
        assert env["ready"] is expect_ready

    def test_supabase_still_dominates(self, monkeypatch):
        """The original hard dependency must survive the fix — a
        readiness probe that stops noticing an unreachable database is
        worse than the bug it replaced."""
        monkeypatch.setenv("PROCESS_ROLE", "web")
        ns = _role_fns()

        class _Sched:
            running = True

        env = {"scheduler": _Sched(), "supabase_ok": False,
               "runs_scheduled_jobs": ns["runs_scheduled_jobs"]}
        for line in self._ready_expr():
            exec(line, env)
        assert env["ready"] is False


class TestUnknownIsNotFalse:
    """The property the whole alarm rests on."""

    def test_signature_admits_unknown(self):
        src = inspect.getsource(scheduler_lock.lease_is_fresh)
        assert "Optional[bool]" in src

    def test_every_failure_path_returns_None(self):
        """Three ways to not know: the lock is disabled, the table is
        absent, the read failed. All three must be None. A False here
        pages ten minutes after every fresh install, forever, until
        somebody mutes the monitor."""
        code = _code(inspect.getsource(scheduler_lock.lease_is_fresh))
        for line in code.splitlines():
            s = line.strip()
            if s.startswith("return False"):
                pytest.fail("a failure path returns False instead of None")
        assert code.count("return None") >= 3

    @staticmethod
    def _readable(monkeypatch, reader):
        """Put the module in the state where it WILL attempt a read.

        The first draft of these tests patched a name the module does
        not use — it calls sb_clients.sb_get_as_service, not a local
        alias — so every case fell into the exception path and returned
        None. Both assertions "passed" for the wrong reason, and the
        one that expected True is the only reason it was caught.
        """
        import sb_clients
        monkeypatch.setattr(scheduler_lock, "_disabled", lambda: False)
        monkeypatch.setattr(scheduler_lock, "_lease_table_present", True)
        monkeypatch.setattr(sb_clients, "sb_get_as_service", reader)

    def test_it_returns_None_when_it_cannot_read(self, monkeypatch):
        """Behavioural: force the read to blow up and confirm the answer
        is None rather than an exception or a False."""
        def _boom(*a, **k):
            raise RuntimeError("supabase down")
        self._readable(monkeypatch, _boom)
        assert scheduler_lock.lease_is_fresh() is None

    def test_no_row_is_unknown_not_stale(self, monkeypatch):
        """A lease row that does not exist yet is a system that has not
        elected a leader for the first time — not one that stopped."""
        self._readable(monkeypatch, lambda *a, **k: [])
        assert scheduler_lock.lease_is_fresh() is None

    def test_a_fresh_lease_is_True_and_an_old_one_is_False(self, monkeypatch):
        """The signal has to be able to fire, or it is decoration."""
        import datetime as dt

        def _rows_expiring_at(offset_sec):
            t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=offset_sec)
            return [{"expires_at": t.isoformat().replace("+00:00", "Z")}]

        # A leader renewing normally holds a lease expiring in the
        # future; the renewal itself was at most RENEW_SEC ago.
        self._readable(monkeypatch,
                       lambda *a, **k: _rows_expiring_at(scheduler_lock.LEASE_TTL_SEC))
        assert scheduler_lock.lease_is_fresh() is True

        # Nobody has renewed in an hour.
        self._readable(monkeypatch, lambda *a, **k: _rows_expiring_at(-3600))
        assert scheduler_lock.lease_is_fresh() is False


class TestTheMonitorWatchesIt:
    """The check that closes the loop. The split is only safe because
    something outside the system notices when nobody is running jobs."""

    WF = (pathlib.Path(__file__).resolve().parent.parent
          / ".github" / "workflows" / "uptime.yml").read_text(encoding="utf-8")

    def test_the_probe_looks_at_the_lease(self):
        assert "scheduler_lease_fresh" in self.WF

    def test_it_pages_only_on_an_explicit_false(self):
        """`grep false` and not `grep -v true`: a null must stay quiet.
        Written as a literal match so the pattern in the workflow is the
        thing being asserted, not a paraphrase of it."""
        assert '"scheduler_lease_fresh"[[:space:]]*:[[:space:]]*false' in self.WF

    def test_the_alert_says_what_to_do(self):
        """"Lease stale" means nothing to somebody woken at 3am. The
        message has to name the fix."""
        assert "PROCESS_ROLE=worker" in self.WF
