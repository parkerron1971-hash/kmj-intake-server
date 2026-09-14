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
