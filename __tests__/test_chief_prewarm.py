"""
test_chief_prewarm.py — loading a turn's context while the practitioner
is still talking.

Kevin, 2026-08-14: "would it be better if we have it positioned so as I
talk it starts thinking, so when I am done it processed some of what I
said already?"

The cheap half of that is worth having: the revenue forecast,
relationship insights, habits, bookkeeping, voice samples and mentor
cooldown depend only on WHO is asking, so they can be fetched at
mic-open and be finished before the sentence is. The expensive half —
starting the model on a half-finished sentence — is not built and must
not be: people change direction mid-thought.

What has to hold for this to be safe rather than just fast:

  1. IT ACTUALLY SAVES THE WORK. A warm turn does not re-fetch what was
     already fetched.
  2. A MISS IS TODAY'S BEHAVIOUR. No warm entry, expired, wrong user,
     wrong business, server error — the turn fetches everything and
     answers identically. Correctness never depends on the hit.
  3. IT NEVER CROSSES PRACTITIONERS. The cache is keyed by user AND
     business. Serving one practitioner's forecast to another would be
     a data leak, not a slow page.
  4. ONLY MESSAGE-INDEPENDENT SOURCES ARE IN IT. The moment something
     that reads req.message gets warmed, Chief starts answering with
     the PREVIOUS question's context. _context_sources is the one list;
     this file pins what may be in it.
  5. IT DOESN'T CALL THE MODEL OR SPEND MONEY.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_of_staff as cos
import chief_prewarm


_BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "type": "coach",
        "owner_id": "user-1", "settings": {}, "created_at": "2026-01-01T00:00:00Z"}

# The sources that may be warmed. Anything reading req.message belongs
# nowhere near this list — see the module docstring.
EXPECTED_SOURCES = {
    "voice_examples", "session_context", "mentor_active", "forecast",
    "relationship_insights", "time_block", "habit_block", "bookkeeping_block",
}


class _Session:
    def __init__(self, uid="user-1"):
        self.user = type("U", (), {"id": uid})()
        self.token = "test-jwt"


@pytest.fixture(autouse=True)
def _clean_cache():
    chief_prewarm.clear()
    yield
    chief_prewarm.clear()


@pytest.fixture
def stubs(monkeypatch):
    """Count how many times each context source is actually fetched."""
    hits = {}

    def _count(name, value):
        async def inner(*a, **k):
            hits[name] = hits.get(name, 0) + 1
            return value
        return inner

    async def _fake_sb(client, method, path, body=None):
        return [_BIZ]
    monkeypatch.setattr(cos, "_sb", _fake_sb)

    for name, attr, value in [
        ("voice_examples", "_get_voice_examples", "VOICE"),
        ("session_context", "_get_session_context", "SESSION"),
        ("mentor_active", "_should_show_mentor_tip", True),
        ("forecast", "_forecast_revenue", {"next_30": 1200}),
        ("relationship_insights", "_analyze_relationships", [{"x": 1}]),
        ("time_block", "_get_time_context", "TIME"),
        ("habit_block", "_get_habit_insights", "HABIT"),
    ]:
        monkeypatch.setattr(cos, attr, _count(name, value))

    import chief_bookkeeping
    def _books(*a, **k):
        hits["bookkeeping_block"] = hits.get("bookkeeping_block", 0) + 1
        return "BOOKS"
    monkeypatch.setattr(chief_bookkeeping, "gather_and_format", _books)

    return hits


def _prewarm(session=None, business_id="biz-1"):
    return asyncio.run(cos.chief_prewarm_endpoint(
        cos.PrewarmRequest(business_id=business_id), session or _Session()))


# ─────────────────────────────────────────────────────────────────────
# 1. It fetches, and it saves the work
# ─────────────────────────────────────────────────────────────────────

def test_prewarm_loads_every_message_independent_source(stubs):
    r = _prewarm()
    assert r["ok"] is True
    assert r["warmed"] == len(EXPECTED_SOURCES)
    assert set(stubs) == EXPECTED_SOURCES
    assert all(v == 1 for v in stubs.values())


def test_the_warmed_values_are_what_the_turn_gets(stubs):
    _prewarm()
    warm = chief_prewarm.take("user-1", "biz-1")
    assert warm["voice_examples"] == "VOICE"
    assert warm["forecast"] == {"next_30": 1200}
    assert warm["bookkeeping_block"] == "BOOKS"
    assert set(warm) == EXPECTED_SOURCES


def test_a_warm_source_is_not_fetched_again(stubs):
    """The whole point: the turn spends nothing on what's already here."""
    _prewarm()
    before = dict(stubs)
    warm = chief_prewarm.take("user-1", "biz-1")
    sources = cos._context_sources(None, _BIZ)

    async def _go():
        return await asyncio.gather(*[
            cos._resolve_source(warm, n, *sources[n]) for n in sources])
    asyncio.run(_go())
    assert stubs == before, "a warmed source was fetched a second time"


def test_a_cold_source_is_fetched_normally(stubs):
    sources = cos._context_sources(None, _BIZ)

    async def _go():
        return await asyncio.gather(*[
            cos._resolve_source({}, n, *sources[n]) for n in sources])
    out = asyncio.run(_go())
    assert set(stubs) == EXPECTED_SOURCES
    assert "VOICE" in out


# ─────────────────────────────────────────────────────────────────────
# 2. A miss is today's behaviour, never an error
# ─────────────────────────────────────────────────────────────────────

def test_no_prewarm_means_an_empty_payload_not_a_failure():
    assert chief_prewarm.take("user-1", "biz-1") == {}


def test_an_expired_entry_is_a_miss(monkeypatch):
    chief_prewarm.store("user-1", "biz-1", {"forecast": 1})
    monkeypatch.setattr(chief_prewarm, "TTL_SECONDS", -1.0)
    assert chief_prewarm.take("user-1", "biz-1") == {}


def test_a_source_that_raises_still_warms_the_rest(stubs, monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("forecast is down")
    monkeypatch.setattr(cos, "_forecast_revenue", _boom)
    r = _prewarm()
    assert r["ok"] is True
    warm = chief_prewarm.take("user-1", "biz-1")
    assert warm["forecast"] is None, "the broken one falls back"
    assert warm["voice_examples"] == "VOICE", "the rest still warmed"


def test_a_business_the_caller_cannot_read_warms_nothing(monkeypatch):
    """RLS returns no row for someone else's business — so there is
    nothing to warm, and no error to leak that it exists."""
    async def _no_rows(client, method, path, body=None):
        return []
    monkeypatch.setattr(cos, "_sb", _no_rows)
    r = _prewarm(business_id="someone-elses-biz")
    assert r["ok"] is True and r["warmed"] == 0
    assert chief_prewarm.take("user-1", "someone-elses-biz") == {}


def test_the_endpoint_never_surfaces_an_error(monkeypatch):
    """A failed optimisation must look like one that wasn't worth doing."""
    async def _explode(*a, **k):
        raise RuntimeError("supabase is gone")
    monkeypatch.setattr(cos, "_sb", _explode)
    r = _prewarm()
    assert r["ok"] is True and r["warmed"] == 0


# ─────────────────────────────────────────────────────────────────────
# 3. It never crosses practitioners
# ─────────────────────────────────────────────────────────────────────

def test_another_practitioner_never_reads_this_cache(stubs):
    _prewarm(_Session("user-1"))
    assert chief_prewarm.take("user-1", "biz-1")["forecast"] == {"next_30": 1200}
    assert chief_prewarm.take("user-2", "biz-1") == {}, (
        "warming is keyed by user AND business — serving one "
        "practitioner's forecast to another is a leak, not a fast page"
    )


def test_another_business_never_reads_this_cache(stubs):
    _prewarm()
    assert chief_prewarm.take("user-1", "biz-2") == {}


@pytest.mark.parametrize("uid,bid", [(None, "biz-1"), ("user-1", None), (None, None)])
def test_a_missing_identity_is_never_a_wildcard(uid, bid):
    chief_prewarm.store(uid, bid, {"forecast": "SECRET"})
    assert chief_prewarm.take(uid, bid) == {}


# ─────────────────────────────────────────────────────────────────────
# 4. Only message-independent sources are warmable
# ─────────────────────────────────────────────────────────────────────

def test_the_warmable_set_is_exactly_the_message_independent_one():
    """If this fails, someone added a source to _context_sources. Confirm
    it cannot read the practitioner's message before widening the list —
    a warmed message-dependent source makes Chief answer with the
    PREVIOUS question's context, silently."""
    assert set(cos._context_sources(None, _BIZ)) == EXPECTED_SOURCES


def test_the_message_dependent_blocks_are_not_warmable():
    warmable = set(cos._context_sources(None, _BIZ))
    # vertical_context.build_vertical_learned_block reads req.message;
    # semantic memory recall reads it via _gather_context's query_text.
    for forbidden in ("learned_block", "ctx", "memories", "sentiment",
                      "draft_context", "priorities"):
        assert forbidden not in warmable


# ─────────────────────────────────────────────────────────────────────
# 5. It doesn't think, spend, or write
# ─────────────────────────────────────────────────────────────────────

def test_prewarm_never_calls_the_model(stubs, monkeypatch):
    called = []
    async def _spy(*a, **k):
        called.append(1)
        return "should not happen"
    monkeypatch.setattr(cos, "_call_claude", _spy)
    _prewarm()
    assert not called, (
        "prewarm must not speculate on a half-finished sentence — that "
        "buys tokens the practitioner retracts"
    )


def test_prewarm_does_not_run_the_sweeps_that_write(stubs, monkeypatch):
    """The autopilot + escalation sweeps draft emails and cost money.
    They stay on the turn, where a real message justifies them."""
    ran = []
    async def _sweep(*a, **k):
        ran.append(1)
        return 0
    monkeypatch.setattr(cos, "_autopilot_sweep", _sweep)
    monkeypatch.setattr(cos, "_evaluate_escalations", _sweep)
    monkeypatch.setattr(cos, "_generate_missing_recurring_instances", _sweep)
    _prewarm()
    assert not ran


# ─────────────────────────────────────────────────────────────────────
# The mic-tap throttle
# ─────────────────────────────────────────────────────────────────────

def test_tapping_the_mic_repeatedly_does_not_refetch(stubs):
    _prewarm()
    first = dict(stubs)
    r2 = _prewarm()
    r3 = _prewarm()
    assert r2["warmed"] == 0 and r3["warmed"] == 0
    assert stubs == first, "four mic taps must not be four Supabase sweeps"
    assert chief_prewarm.take("user-1", "biz-1")["voice_examples"] == "VOICE"


def test_the_throttle_opens_again_once_the_entry_ages(stubs, monkeypatch):
    _prewarm()
    monkeypatch.setattr(chief_prewarm, "MIN_REWARM_SECONDS", 0.0)
    assert _prewarm()["warmed"] == len(EXPECTED_SOURCES)
    assert all(v == 2 for v in stubs.values())
