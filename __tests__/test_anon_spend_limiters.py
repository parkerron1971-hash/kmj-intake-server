"""Limiters on money-spending surfaces are keyed on values the caller
cannot choose.

Three surfaces spend real money on AI. /pulse was anonymous and had no
limiter at all — and an anonymous caller has no business to bill, so its
spend is unattributed and counts only toward the PLATFORM ceiling. The
per-tenant ceiling added later cannot help here; one loop still exhausts
the shared cap and takes Chief offline for EVERY customer at once, for
about fifty dollars. This limiter is what stands in front of that.

The other two had limiters keyed on values the caller supplies: the
intake endpoint on the first X-Forwarded-For hop (whatever the caller
typed), and the AI proxy on a business_id read out of the request body.
A limiter keyed on an attacker-chosen string is decorative.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import rate_limit


class _Req:
    """Minimal stand-in for a Starlette Request."""

    def __init__(self, xff: str | None = None, peer: str = "10.0.0.1"):
        self.headers = {"x-forwarded-for": xff} if xff is not None else {}
        self.client = type("C", (), {"host": peer})()


@pytest.fixture(autouse=True)
def _clean_buckets():
    rate_limit._buckets.clear()
    yield
    rate_limit._buckets.clear()


class TestTrustedClientIp:
    def test_takes_the_last_hop_not_the_first(self):
        """Railway APPENDS the peer it observed, so the last entry is the
        one no upstream caller chose."""
        req = _Req("1.2.3.4, 5.6.7.8, 203.0.113.9")
        assert rate_limit.trusted_client_ip(req) == "203.0.113.9"

    def test_a_spoofed_header_cannot_move_the_key(self):
        """The attack the first-hop reader allowed: vary the header,
        get a fresh bucket every request."""
        real_peer = "203.0.113.9"
        keys = {rate_limit.trusted_client_ip(_Req(f"{spoof}, {real_peer}"))
                for spoof in ("1.1.1.1", "2.2.2.2", "3.3.3.3", "evil")}
        assert keys == {real_peer}, "spoofed hops must not create new buckets"

    def test_falls_back_to_the_socket_peer(self):
        assert rate_limit.trusted_client_ip(_Req(None, peer="198.51.100.7")) == "198.51.100.7"

    def test_never_raises(self):
        class Broken:
            headers = None
            client = None
        assert rate_limit.trusted_client_ip(Broken()) == "unknown"


class TestPulseBucket:
    def test_bucket_is_registered(self):
        assert "pulse" in rate_limit._LIMITS

    def test_window_is_hourly_not_per_minute(self):
        """The daily total is what matters — the global spend ceiling is
        what an attacker is actually racing toward."""
        _limit, window = rate_limit._LIMITS["pulse"]
        assert window == 3600

    def test_limit_is_small(self):
        limit, _w = rate_limit._LIMITS["pulse"]
        assert limit <= 20, "a real caller opens the app once a morning"

    def test_it_actually_stops_a_loop(self):
        limit, _w = rate_limit._LIMITS["pulse"]
        ip = "203.0.113.9"
        allowed = sum(1 for _ in range(limit + 25)
                      if rate_limit.allow_strict("pulse", ip))
        assert allowed == limit

    def test_one_caller_cannot_exhaust_another(self):
        limit, _w = rate_limit._LIMITS["pulse"]
        for _ in range(limit + 5):
            rate_limit.allow_strict("pulse", "attacker")
        assert rate_limit.allow_strict("pulse", "someone-else") is True


class TestStrictFailsClosed:
    def test_allow_strict_denies_when_the_limiter_errors(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("bucket store unavailable")
        monkeypatch.setattr(rate_limit, "_check", _boom)
        assert rate_limit.allow_strict("pulse", "x") is False

    def test_plain_allow_still_fails_open(self, monkeypatch):
        """Deliberately unchanged: a limiter glitch must never stop a
        practitioner running their own business."""
        def _boom(*a, **k):
            raise RuntimeError("bucket store unavailable")
        monkeypatch.setattr(rate_limit, "_check", _boom)
        assert rate_limit.allow("proxy", "x") is True


class TestCallSitesUseTheTrustedKey:
    """Guards against the fix being quietly reverted — the previous
    pattern is a one-line edit away and reads perfectly innocent."""

    def _src(self, name):
        import inspect
        import importlib
        return inspect.getsource(importlib.import_module(name))

    def test_intake_endpoint_uses_trusted_client_ip(self):
        src = self._src("intake_endpoint")
        assert "rate_limit.trusted_client_ip(request)" in src
        assert 'x-forwarded-for") or "").split(",")[0]' not in src

    def test_pulse_is_rate_limited_at_all(self):
        src = self._src("kmj_intake_automation")
        assert 'allow_strict("pulse"' in src

    def test_ai_proxy_does_not_key_on_request_metadata(self):
        src = self._src("ai_proxy")
        assert '(req.metadata or {}).get("business_id") or "") or rate_limit.client_ip' not in src
