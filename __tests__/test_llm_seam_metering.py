"""Every Anthropic call reaches api_usage exactly once.

spend_guard — the only global brake on AI spend — works by summing
api_usage.cost_cents since midnight. 23 modules called the llm_call seam
and never wrote a row, so the brake was blind to growth_engine,
brand_engine, module_spec_generator, foundation_agent, contract_agent,
discovery, vertical_distill and sixteen others. The control meant to
stop a runaway could not see a large slice of the spend it was counting.

Metering moved to the seam, which covers all of them and every future
caller. The hazard that creates is the opposite one: 19 modules meter
themselves, and counting them twice would inflate the number the brake
reads and trip it early — the same outage from the other direction.

So these tests pin both halves: the seam meters, and it does not
double-meter. The drift test is the load-bearing one, because
_SELF_METERING is a hand-written set describing code elsewhere, and that
is precisely the kind of thing that rots without anyone noticing.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import llm_call

ROOT = pathlib.Path(__file__).resolve().parent.parent
LLM_MARKERS = ("llm_call.post", "llm_call.apost", "llm_call.post_with",
               "llm_call.sdk_client", "llm_call.astream")
METER_MARKERS = ("log_api_usage", "log_api_usage_sync")


def _modules_calling_the_seam():
    # rglob, not glob: `passes` lives in agents/composer/drl/, and a
    # root-only sweep reports it as missing from _SELF_METERING — which
    # would read as "this module stopped metering" when in fact the
    # search never looked there. The first run of this test found
    # exactly that.
    out = {}
    for p in sorted(ROOT.rglob("*.py")):
        s = str(p)
        if "__pycache__" in s or "__tests__" in s or "site-packages" in s:
            continue
        if p.name in ("llm_call.py", "model_ladder.py"):
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not any(m in src for m in LLM_MARKERS):
            continue
        out[p.stem] = any(m in src for m in METER_MARKERS)
    return out


class _Resp:
    def __init__(self, usage=None, status=200, model="claude-sonnet-5"):
        self.status_code = status
        self._body = {"model": model, "usage": usage or {}}

    def json(self):
        return self._body


class TestDrift:
    def test_self_metering_set_matches_reality(self):
        """_SELF_METERING describes code in OTHER files. If a module
        stops metering itself and is not removed here, its spend silently
        stops being counted — the original bug, reintroduced quietly."""
        actual = {m for m, meters in _modules_calling_the_seam().items() if meters}
        declared = set(llm_call._SELF_METERING)
        missing = actual - declared
        stale = declared - actual
        assert not missing, (
            f"these modules meter themselves but are NOT in _SELF_METERING, "
            f"so the seam will count them twice: {sorted(missing)}")
        assert not stale, (
            f"these are in _SELF_METERING but no longer meter themselves, so "
            f"their spend is now invisible to spend_guard: {sorted(stale)}")

    def test_there_really_are_unmetered_callers_to_cover(self):
        """Guards the guard — if this drops to zero the sweep has broken,
        not the problem been solved."""
        gaps = [m for m, meters in _modules_calling_the_seam().items() if not meters]
        assert len(gaps) > 5, f"sweep looks broken; found only {gaps}"


class TestSeamMeters:
    def test_an_unmetered_caller_gets_a_row(self, monkeypatch):
        rows = []
        monkeypatch.setattr("api_usage_logger.log_api_usage_sync",
                            lambda **kw: rows.append(kw))
        llm_call._meter(_Resp({"input_tokens": 100, "output_tokens": 50}),
                        {"model": "claude-sonnet-5"}, "growth_engine", 0.0)
        assert len(rows) == 1
        assert rows[0]["endpoint"] == "llm:growth_engine"
        assert rows[0]["input_tokens"] == 100
        assert rows[0]["output_tokens"] == 50

    def test_a_self_metering_caller_gets_nothing(self, monkeypatch):
        """The double-count guard. chief_of_staff already writes its own
        row; a second one here would inflate the brake's number."""
        rows = []
        monkeypatch.setattr("api_usage_logger.log_api_usage_sync",
                            lambda **kw: rows.append(kw))
        llm_call._meter(_Resp({"input_tokens": 100, "output_tokens": 50}),
                        {}, "chief_of_staff", 0.0)
        assert rows == []

    def test_cache_tokens_are_carried(self, monkeypatch):
        """Cache reads are priced at 0.1x and writes at 1.25x — dropping
        them would misprice every cached call."""
        rows = []
        monkeypatch.setattr("api_usage_logger.log_api_usage_sync",
                            lambda **kw: rows.append(kw))
        llm_call._meter(_Resp({"input_tokens": 10, "output_tokens": 5,
                               "cache_read_input_tokens": 900,
                               "cache_creation_input_tokens": 40}),
                        {}, "discovery", 0.0)
        assert rows[0]["cache_read_tokens"] == 900
        assert rows[0]["cache_creation_tokens"] == 40

    def test_a_failed_call_is_not_metered(self, monkeypatch):
        rows = []
        monkeypatch.setattr("api_usage_logger.log_api_usage_sync",
                            lambda **kw: rows.append(kw))
        llm_call._meter(_Resp(status=429), {}, "discovery", 0.0)
        assert rows == []

    def test_a_response_without_usage_is_not_metered(self, monkeypatch):
        rows = []
        monkeypatch.setattr("api_usage_logger.log_api_usage_sync",
                            lambda **kw: rows.append(kw))
        llm_call._meter(_Resp({}), {}, "discovery", 0.0)
        assert rows == []

    def test_metering_never_breaks_a_successful_call(self, monkeypatch):
        """An AI call that already succeeded must not fail because the
        bookkeeping did."""
        def _boom(**kw):
            raise RuntimeError("supabase down")
        monkeypatch.setattr("api_usage_logger.log_api_usage_sync", _boom)
        llm_call._meter(_Resp({"input_tokens": 1, "output_tokens": 1}),
                        {}, "discovery", 0.0)  # must not raise

    def test_unparseable_body_is_survived(self, monkeypatch):
        class Bad:
            status_code = 200

            def json(self):
                raise ValueError("not json")
        llm_call._meter(Bad(), {}, "discovery", 0.0)  # must not raise


class TestCallerAttribution:
    def test_model_ladder_is_transparent(self):
        """model_ladder wraps the seam. Blaming it would hide every real
        caller behind one name — and would let a self-metering module
        reach the seam disguised as one that is not."""
        assert "model_ladder" in llm_call._TRANSPARENT
        assert "llm_call" in llm_call._TRANSPARENT

    def test_caller_is_this_test_module(self):
        assert llm_call._caller_module() == "test_llm_seam_metering"


class TestWiring:
    @pytest.mark.parametrize("fn", ["apost", "post_with", "post"])
    def test_every_non_streaming_sender_meters(self, fn):
        import inspect
        src = inspect.getsource(getattr(llm_call, fn))
        assert "_meter(" in src, f"llm_call.{fn} does not meter"

    def test_astream_is_left_alone(self):
        """A streamed response has no buffered body to read usage from —
        metering it here would consume the stream the caller needs."""
        import inspect
        assert "_meter(" not in inspect.getsource(llm_call.astream)
