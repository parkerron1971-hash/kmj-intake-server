"""The prompt cache outlives a pause in the conversation.

Measured live on 2026-08-10, two real turns through production:

    cold   cache_write 43,603 tok   19.75c
    warm   cache_read  43,603 tok    4.31c

A warm turn is 78% cheaper and the cached prefix is 43.6k tokens —
nearly the whole prompt. The cache was never broken; it was EXPIRING.
Without an anthropic-beta header, cache_control runs on the default
five-minute ttl, so a practitioner who sends a message, thinks for six
minutes and sends another pays the full cold price again. Real
conversation has pauses in it.

A 1h write costs 2x base instead of 1.25x; reads stay 0.1x. Six
exchanges across an hour: ~118c on the 5-minute ttl, ~51c on the hour.

The load-bearing test here is the DOWNGRADE. _call_claude treats 4xx as
our own bug and never retries it, so an unsupported beta name would not
make Chief dearer — it would make Chief dead.
"""
from __future__ import annotations

import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_of_staff as cos


@pytest.fixture(autouse=True)
def _reset():
    cos._extended_cache_ok = True
    yield
    cos._extended_cache_ok = True


class TestTheTtlIsAsked_For:
    def test_cache_control_carries_the_hour(self):
        assert cos._cache_control(True) == {"type": "ephemeral", "ttl": "1h"}

    def test_and_omits_it_when_disabled(self):
        """No ttl key at all, not ttl=None — the API is strict about the
        shape and a null would be a 400 rather than a default."""
        assert cos._cache_control(False) == {"type": "ephemeral"}

    def test_the_beta_header_rides_along(self):
        assert cos._beta_headers(True) == {
            "anthropic-beta": cos._EXTENDED_CACHE_BETA}
        assert cos._beta_headers(False) is None

    def test_both_request_paths_send_it(self):
        """Streaming and non-streaming. Sending it on one only would make
        the cache behave differently depending on whether the practitioner
        had voice on."""
        src = inspect.getsource(cos._call_claude)
        assert src.count("extra_headers=_beta_headers(_extended)") == 2


class TestItCanBeTurnedOff:
    def test_env_kills_it_without_a_deploy(self, monkeypatch):
        monkeypatch.setenv("CHIEF_EXTENDED_CACHE", "off")
        assert cos._extended_cache_enabled() is False

    def test_default_is_on(self, monkeypatch):
        monkeypatch.delenv("CHIEF_EXTENDED_CACHE", raising=False)
        assert cos._extended_cache_enabled() is True

    def test_a_process_level_rejection_sticks(self, monkeypatch):
        monkeypatch.delenv("CHIEF_EXTENDED_CACHE", raising=False)
        cos._extended_cache_ok = False
        assert cos._extended_cache_enabled() is False


class TestTheDowngradeIsTheSafetyNet:
    """_call_claude never retries a 4xx — it treats them as our bug. So a
    beta the API will not accept has to be caught by name, or the first
    turn after deploy is the last one."""

    @pytest.mark.parametrize("body", [
        "unexpected field ttl",
        "extended-cache-ttl-2025-04-11 is not enabled for this account",
        'invalid "anthropic-beta" header',
        "beta feature unavailable",
    ])
    def test_a_beta_rejection_is_recognised(self, body):
        assert cos._looks_like_beta_rejection(400, body) is True

    @pytest.mark.parametrize("status,body", [
        (400, "max_tokens must be greater than 0"),
        (400, "messages: at least one message is required"),
        (401, "invalid x-api-key"),
        (429, "rate limit exceeded"),
        (500, "internal server error"),
    ])
    def test_a_real_error_is_NOT_swallowed(self, status, body):
        """The dangerous failure is the opposite one: treating a genuine
        400 as a beta problem, downgrading, retrying, and hiding a real
        bug behind a slightly cheaper cache."""
        assert cos._looks_like_beta_rejection(status, body) is False

    def test_both_paths_downgrade_and_retry(self):
        src = inspect.getsource(cos._call_claude)
        assert src.count("_looks_like_beta_rejection") == 2
        assert src.count('globals()["_extended_cache_ok"] = False') == 2

    def test_the_retry_reuses_the_same_turn(self):
        """It must re-issue THIS call, not fall through to the error
        handler — otherwise the first practitioner after a deploy still
        loses their turn."""
        src = inspect.getsource(cos._call_claude)
        assert src.count("return await _call_claude(") == 2


class TestTheShapeStaysHonest:
    def test_the_recorded_shape_says_which_ttl_was_used(self, monkeypatch):
        """api_usage is where the win gets measured. If a 1h turn and a
        5m turn were both logged as cached-3seg, the query proving the
        change worked could not distinguish them."""
        src = inspect.getsource(cos._call_claude)
        assert 'prompt_shape += "-1h"' in src

    def test_an_uncached_prompt_is_not_labelled_1h(self):
        src = inspect.getsource(cos._call_claude)
        i = src.index('prompt_shape += "-1h"')
        guard = src[max(0, i - 200):i]
        assert 'uncached-single' in guard, (
            "a prompt with no cache blocks must not be tagged as 1h-cached")
