"""
The "before first real launch" items, closed (2026-09-04).

Two findings from the anonymous-surface audit, both cheap to fix and
both dated "before launch" for months:

  1. Four anonymous WRITE or SPEND routes keyed their limiter on the
     FIRST X-Forwarded-For hop — the one the caller types. A limiter
     keyed on a caller-chosen string is decorative. Three OAuth buckets
     were checked strictly but never registered, so they fell to the
     60/min default. Two routes had no limiter at all, one of them with
     a docstring claiming a middleware that does not exist.

  2. Every customer booking link on the platform was signed by one
     global secret, so a key recovered for one business minted links
     for all of them, and rotating it broke every link at once.

The tests are source-level where the previous pattern is a one-line
edit away and reads perfectly innocent, the way test_anon_spend_limiters
already does.
"""
from __future__ import annotations

import datetime as _dt
import importlib
import inspect
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import customer_token as ct
import rate_limit


def _src(name):
    return inspect.getsource(importlib.import_module(name))


# ─── 1. limiters keyed on the trusted hop ────────────────────────────

class TestTrustedHop:
    def test_booking_widget_reads_the_last_hop(self):
        import booking_widget_router as bw

        class _Req:
            headers = {"x-forwarded-for": "6.6.6.6, 203.0.113.9"}
            client = None
        assert bw._client_ip(_Req()) == "203.0.113.9"
        assert 'split(",")[0]' not in inspect.getsource(bw._client_ip)

    @pytest.mark.parametrize("module", ["events_rsvp_router", "giving_router"])
    def test_rsvp_and_giving_use_the_trusted_key(self, module):
        src = _src(module)
        assert "trusted_client_ip(request)" in src
        assert "from rate_limit import client_ip" not in src

    def test_oauth_front_door_uses_the_trusted_key(self):
        src = _src("mcp_oauth")
        assert "rate_limit.client_ip(request)" not in src
        assert src.count("rate_limit.trusted_client_ip(request)") == 3

    @pytest.mark.parametrize("bucket", ["mcp_oauth_register", "mcp_oauth_consent",
                                        "mcp_oauth_token"])
    def test_oauth_buckets_are_registered_not_defaulted(self, bucket):
        assert bucket in rate_limit._LIMITS, f"{bucket} fell to _DEFAULT (60/min)"
        max_req, window = rate_limit._LIMITS[bucket]
        assert (max_req, window) != rate_limit._DEFAULT


class TestUnlimitedRoutesNowHaveOne:
    def test_booking_checkout_is_limited_and_the_false_comment_is_gone(self):
        src = _src("stripe_payments_router")
        assert "wizard rate-limit middleware" not in src.split("RATE-LIMITED HERE")[0] or \
            "No such middleware exists" in src
        assert 'allow_strict("booking_checkout"' in src
        assert "booking_checkout" in rate_limit._LIMITS

    def test_waitlist_is_limited(self):
        src = _src("launch_access")
        assert 'allow_strict("waitlist"' in src
        assert "request: Request = None" not in src.split("def join_waitlist")[1].split("\n")[0]
        assert "waitlist" in rate_limit._LIMITS

    def test_sms_opt_in_is_limited_per_ip_as_well_as_per_phone(self):
        src = _src("sms_routing")
        i = src.index("def sms_opt_in")
        body = src[i:i + 2500]
        assert 'allow_strict("sms_opt_in"' in body
        assert "_OPTIN_HITS" in body, "the per-phone limit stays too"
        assert "sms_opt_in" in rate_limit._LIMITS

    def test_track_has_a_per_ip_bucket_that_fails_open(self):
        src = _src("site_analytics")
        assert 'rate_limit.allow("track"' in src
        assert 'allow_strict("track"' not in src, "a beacon must never error"
        assert "track" in rate_limit._LIMITS

    def test_strict_buckets_are_hourly_and_small(self):
        for bucket in ("booking_checkout", "waitlist", "sms_opt_in", "mcp_oauth_register"):
            max_req, window = rate_limit._LIMITS[bucket]
            assert window == 3600 and max_req <= 20, bucket


# ─── 2. per-business signing keys ────────────────────────────────────

@pytest.fixture(autouse=True)
def _root(monkeypatch):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "root-secret-for-tests")


def test_new_tokens_carry_the_version_and_verify():
    tok = ct.issue_customer_token("biz-a", "cus-1")
    claims = ct.verify_customer_token(tok)
    assert claims and claims["biz"] == "biz-a" and claims["cus"] == "cus-1"
    assert claims["v"] == ct.TOKEN_VERSION


def test_each_business_signs_with_its_own_key():
    assert ct.derive_key("customer-token", "biz-a") != ct.derive_key("customer-token", "biz-b")
    assert ct.derive_key("customer-token", "biz-a") != ct.derive_key("agent-key", "biz-a"), (
        "two purposes for one business must not share a key")
    assert len(ct.derive_key("customer-token", "biz-a")) == 32


def test_the_root_no_longer_signs_a_current_token():
    """A token signed by the raw root but claiming v2 must be refused —
    that is the containment property: knowing the root-signing shape
    of the OLD format buys nothing against the new one."""
    payload = {"biz": "biz-a", "cus": "cus-1", "iat": int(time.time()),
               "exp": int(time.time()) + 600, "v": ct.TOKEN_VERSION}
    p64 = ct._b64url_encode(json.dumps(payload, separators=(",", ":"),
                                       sort_keys=True).encode())
    import hashlib, hmac
    sig = hmac.new(b"root-secret-for-tests", p64.encode(), hashlib.sha256).digest()
    assert ct.verify_customer_token(f"{p64}.{ct._b64url_encode(sig)}") is None


def test_a_key_for_one_business_cannot_mint_for_another():
    """Sign a payload naming biz-b with biz-a's derived key."""
    payload = {"biz": "biz-b", "cus": "cus-9", "iat": int(time.time()),
               "exp": int(time.time()) + 600, "v": ct.TOKEN_VERSION}
    p64 = ct._b64url_encode(json.dumps(payload, separators=(",", ":"),
                                       sort_keys=True).encode())
    import hashlib, hmac
    sig = hmac.new(ct.derive_key("customer-token", "biz-a"), p64.encode(),
                   hashlib.sha256).digest()
    assert ct.verify_customer_token(f"{p64}.{ct._b64url_encode(sig)}") is None


def test_a_legacy_root_signed_token_still_verifies_until_sunset():
    """Links already in customers' inboxes keep working for their TTL."""
    payload = {"biz": "biz-a", "cus": "cus-1", "iat": int(time.time()),
               "exp": int(time.time()) + 600}
    p64 = ct._b64url_encode(json.dumps(payload, separators=(",", ":"),
                                       sort_keys=True).encode())
    import hashlib, hmac
    sig = hmac.new(b"root-secret-for-tests", p64.encode(), hashlib.sha256).digest()
    claims = ct.verify_customer_token(f"{p64}.{ct._b64url_encode(sig)}")
    assert claims and claims["biz"] == "biz-a" and "v" not in claims


def test_an_unknown_version_is_refused_not_retried():
    payload = {"biz": "biz-a", "cus": "cus-1", "iat": int(time.time()),
               "exp": int(time.time()) + 600, "v": 99}
    p64 = ct._b64url_encode(json.dumps(payload, separators=(",", ":"),
                                       sort_keys=True).encode())
    import hashlib, hmac
    for key in (b"root-secret-for-tests", ct.derive_key("customer-token", "biz-a")):
        sig = hmac.new(key, p64.encode(), hashlib.sha256).digest()
        assert ct.verify_customer_token(f"{p64}.{ct._b64url_encode(sig)}") is None


def test_expired_and_malformed_still_fail():
    payload = {"biz": "biz-a", "cus": "cus-1", "iat": 1, "exp": 2, "v": ct.TOKEN_VERSION}
    p64 = ct._b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    import hashlib, hmac
    sig = hmac.new(ct.derive_key("customer-token", "biz-a"), p64.encode(), hashlib.sha256).digest()
    assert ct.verify_customer_token(f"{p64}.{ct._b64url_encode(sig)}") is None
    assert ct.verify_customer_token("garbage") is None
    assert ct.verify_customer_token("a.b") is None


def test_the_legacy_branch_has_a_sunset_and_it_has_not_passed():
    """When this fails, delete the `version is None` branch in
    verify_customer_token and this test together. Every root-signed
    token has expired by then; the branch is dead code."""
    assert ct.LEGACY_SUNSET
    today = _dt.date.today().isoformat()
    assert today < ct.LEGACY_SUNSET, (
        f"LEGACY_SUNSET {ct.LEGACY_SUNSET} has passed — delete the root-signed "
        "fallback in customer_token.verify_customer_token and this test")


def test_the_dependency_still_binds_the_path_business(monkeypatch):
    """Step 2 of the 4-step pattern is unchanged: a v2 token for biz-a
    presented on biz-b's path is a 403, before any row is read."""
    from fastapi import HTTPException

    class _Req:
        headers = {"authorization": f"Bearer {ct.issue_customer_token('biz-a', 'cus-1')}"}
        query_params = {}
    with pytest.raises(HTTPException) as e:
        ct.require_customer_token_dep("biz-b", _Req())
    assert e.value.status_code == 403
