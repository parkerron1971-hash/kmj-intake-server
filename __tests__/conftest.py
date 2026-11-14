# __tests__/conftest.py
import os

# The easel step (canvas self-review, Director's Cut arc 2) launches
# real chromium screenshots and a vision call when left on — unit tests
# must never pay for either (a local playwright install made the whole
# canvas suite take 60s+ and would have burned API tokens with a key in
# the env). Tests that exercise the switch itself re-enable it via
# mock.patch.dict.
os.environ.setdefault("CANVAS_VISION_LOOP", "off")

# Same rule for builder v2's vision loop (the eyes): screenshots + a
# vision call belong to real builds, never to unit tests.
os.environ.setdefault("SITE_V2_VISION_LOOP", "off")

# Lead scoring fires on a worker thread from four capture paths. A
# detached thread outliving a test's mock.patch block would reach the
# real network, and would do it non-deterministically. "off" here; the
# wiring tests flip it to "sync" via mock.patch.dict, which is also the
# only mode in which they can assert anything.
os.environ.setdefault("LEAD_SCORING_MODE", "off")

# The rail's practice (chief_rail) reads records on a worker thread after
# every streamed Chief turn. Same rule as lead scoring: off here; its own
# tests call it directly with the reads faked.
os.environ.setdefault("CHIEF_RAIL", "off")

# Members' quiet hours (member_push) follow the church's clock: left on, a
# test's notification would wait or not depending on the hour it runs. The
# quiet-hours tests turn it on with monkeypatch.setenv and a fixed clock.
os.environ.setdefault("MEMBER_QUIET_HOURS", "off")


# Chief's per-turn state lives in contextvars that a real turn resets at
# its start and that a test which calls the door or the tool loop
# directly never does. The taint counter was the one that bit: a
# grounding test that defuses a poisoned email bumped it, and every
# trust-gate test after it in the same process saw "suspicious content
# in inbox" and held a batch email (six order-dependent failures on
# trunk, 2026-09-14). Every test starts from a fresh turn.
import pytest


@pytest.fixture(autouse=True)
def _fresh_chief_turn():
    try:
        import chief_of_staff as _cos
        _cos._UNTRUSTED_TAINT.set(0)
    except Exception:  # pragma: no cover - a test that never imports Chief
        pass
    try:
        import chief_tool_loop as _loop
        _loop.reset_turn()
    except Exception:  # pragma: no cover
        pass
    yield


# church_duties keeps a login's duties a minute per process, keyed by the
# church and the login. The job gates ask it (board, rooms, sign-ups, the
# leaders note, the weekly text, chat rules), and test files share church
# and login ids, so one file's fake office would answer the next's. Only a
# module already imported is cleared: importing it here would bind it to
# whatever sb_clients a test file had not stubbed yet.
@pytest.fixture(autouse=True)
def _fresh_church_duties():
    import sys as _sys
    _cd = _sys.modules.get("church_duties")
    if _cd is not None:
        _cd._CACHE.clear()
        _cd._FAILED.clear()
    # church_map remembers, per process, that the map's columns answered:
    # every test asks its own fake again.
    _cm = _sys.modules.get("church_map")
    if _cm is not None:
        _cm._READY.clear()
    yield


# bank_money caches "does plaid_transactions.money_kind exist?" for five
# minutes. In one test process that cache would carry one test's fake
# database into the next, so every test starts unprobed.
@pytest.fixture(autouse=True)
def _fresh_money_kind_probe():
    try:
        import time as _time
        import bank_money as _bm
        # A definite "not yet", cached, so no test probes the network. Tests
        # of the after-migration behaviour monkeypatch bank_money.supported.
        _bm._probe.update(at=_time.monotonic(), ok=False)
    except Exception:  # pragma: no cover
        pass


# bookkeeping_close caches "does accounting_periods.close_checklist exist?"
# the same way; same pin, same reason.
@pytest.fixture(autouse=True)
def _fresh_close_checklist_probe():
    try:
        import time as _time
        import bookkeeping_close as _bc
        _bc._probe.update(at=_time.monotonic(), ok=False)
    except Exception:  # pragma: no cover
        pass


# sample_church keeps "is this business a sample?" for good (ids are never
# reused in production) and owners' emails for ten minutes. Test files share
# business ids, so one file's fake sample would answer the next's: every test
# starts with nothing remembered. Only a module already imported is cleared.
@pytest.fixture(autouse=True)
def _fresh_sample_church():
    import sys as _sys
    _sc = _sys.modules.get("sample_church")
    if _sc is not None:
        _sc._reset_for_tests()
    yield
