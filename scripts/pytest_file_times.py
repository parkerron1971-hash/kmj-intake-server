"""scripts/pytest_file_times.py — how long each test file takes, for shard_tests.py.

CI loads it into every pytest slice (`-p pytest_file_times`, with scripts/ on
PYTHONPATH). At the end it prints one line,

    seconds per test file (to refresh scripts/test_seconds.json): {...}

each file's collecting time (importing it and building its tests) plus its
tests' setup, call and teardown. shard_tests.py splits the suite by these
seconds, so the parts finish close together. It reads and changes nothing
else, and it is not a test file (pytest never collects it).
"""
from __future__ import annotations

import json
import time
from collections import defaultdict

import pytest

_SECONDS: dict = defaultdict(float)


def _file(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    started = time.perf_counter()
    yield
    if isinstance(collector, pytest.Module):
        _SECONDS[_file(collector.nodeid)] += time.perf_counter() - started


def pytest_runtest_logreport(report):
    _SECONDS[_file(report.nodeid)] += getattr(report, "duration", 0.0) or 0.0


def pytest_terminal_summary(terminalreporter):
    out = {k: round(v, 1) for k, v in sorted(_SECONDS.items())}
    terminalreporter.write_line(
        "seconds per test file (to refresh scripts/test_seconds.json): " + json.dumps(out))
