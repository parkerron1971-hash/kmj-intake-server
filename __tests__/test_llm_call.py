"""llm_call — the model seam (layer-two P0.4).

Two things are under test:

  1. The seam behaves — endpoint override, headers, and (the subtle one)
     that it never silently retunes a caller's timeout.
  2. The seam STAYS the seam. `test_no_module_bypasses_the_seam` is the
     load-bearing test in this file: it fails the build the moment a new
     module hardcodes the Anthropic URL or constructs its own SDK client.
     Without it this migration decays back to N call sites, which is
     exactly how it got to 36 in the first place.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import re
import sys

_here = pathlib.Path(__file__).resolve().parent
_root = _here.parent
sys.path.insert(0, str(_root))
sys.path.insert(0, str(_here))

import httpx  # noqa: E402
import pytest  # noqa: E402

import llm_call  # noqa: E402


# ─── Endpoint: the substitution point ────────────────────────────────

def test_default_endpoint(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    assert llm_call.base_url() == "https://api.anthropic.com"
    assert llm_call.messages_url() == "https://api.anthropic.com/v1/messages"


def test_base_url_override_is_the_hipaa_swap(monkeypatch):
    """One env var moves EVERY call site — that is the whole point of the
    seam (LAYER_TWO_SEAM_REVIEW seam 6 / Section 5)."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://hipaa.example.com/")
    assert llm_call.messages_url() == "https://hipaa.example.com/v1/messages"


def test_base_url_is_read_per_call_not_at_import(monkeypatch):
    """A module-level constant would freeze the endpoint at import time and
    silently ignore the override."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://one.example.com")
    first = llm_call.messages_url()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://two.example.com")
    assert llm_call.messages_url() != first


# ─── Headers ─────────────────────────────────────────────────────────

def test_headers_carry_key_and_version(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    h = llm_call.headers()
    assert h["x-api-key"] == "sk-from-env"
    assert h["anthropic-version"] == llm_call.ANTHROPIC_VERSION == "2023-06-01"
    assert h["content-type"] == "application/json"


def test_explicit_key_beats_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    assert llm_call.headers(key="sk-caller")["x-api-key"] == "sk-caller"


def test_extra_headers_win_on_conflict():
    """The studio modules deliberately send a charset'd content-type."""
    h = llm_call.headers({"Content-Type": "application/json; charset=utf-8",
                          "Accept-Charset": "utf-8"})
    assert h["Content-Type"] == "application/json; charset=utf-8"
    assert h["Accept-Charset"] == "utf-8"


def test_missing_key_is_empty_string_not_none(monkeypatch):
    """Migrated callers all test `if not key`. None would still be falsy,
    but empty string is what they were built against."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm_call.api_key() == ""


# ─── Timeout fidelity — the regression this migration could have caused ──

class _RecordingAsyncClient:
    def __init__(self):
        self.kwargs = None

    async def post(self, url, **kwargs):
        self.kwargs = dict(kwargs, url=url)
        return "resp"


def test_apost_defers_to_client_timeout_when_none_given():
    """chief_llm's client owns a 45s timeout and passes none per request;
    brand_engine's owns 60s. Injecting a default here would silently
    retune both."""
    c = _RecordingAsyncClient()
    asyncio.run(llm_call.apost(c, {"model": "m"}))
    assert c.kwargs["timeout"] is httpx.USE_CLIENT_DEFAULT


def test_apost_passes_explicit_timeout_through():
    c = _RecordingAsyncClient()
    t = httpx.Timeout(connect=1.0, read=2.0, write=3.0, pool=4.0)
    asyncio.run(llm_call.apost(c, {"model": "m"}, timeout=t))
    assert c.kwargs["timeout"] is t


def test_apost_sends_payload_as_json_and_hits_the_seam_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-1")
    c = _RecordingAsyncClient()
    asyncio.run(llm_call.apost(c, {"model": "m", "max_tokens": 5}))
    assert c.kwargs["url"] == "https://gw.example.com/v1/messages"
    assert c.kwargs["json"] == {"model": "m", "max_tokens": 5}
    assert "content" not in c.kwargs
    assert c.kwargs["headers"]["x-api-key"] == "sk-1"


def test_content_path_bypasses_json_serialization():
    """The studio modules pre-encode UTF-8 bytes on purpose."""
    c = _RecordingAsyncClient()
    raw = '{"m":"café"}'.encode("utf-8")
    asyncio.run(llm_call.apost(c, content=raw))
    assert c.kwargs["content"] == raw
    assert "json" not in c.kwargs


def test_standalone_post_uses_default_timeout(monkeypatch):
    """post() owns no client, so it must NOT inherit httpx's 5s default."""
    seen = {}

    def fake_post(url, **kw):
        seen.update(kw, url=url)
        return "resp"

    monkeypatch.setattr(llm_call.httpx, "post", fake_post)
    llm_call.post({"model": "m"})
    assert seen["timeout"] is llm_call.DEFAULT_TIMEOUT


# ─── SDK client ──────────────────────────────────────────────────────

def test_sdk_client_follows_the_same_endpoint_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-2")
    captured = {}

    class FakeAnthropic:
        def __init__(self, **kw):
            captured.update(kw)

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    llm_call.sdk_client(timeout=90.0, max_retries=1)
    assert captured == {"api_key": "sk-2", "base_url": "https://gw.example.com",
                        "timeout": 90.0, "max_retries": 1}


def test_sdk_client_omits_unset_knobs(monkeypatch):
    """A bare sdk_client() must keep the SDK's own defaults — matching the
    sites that wrote Anthropic(api_key=…) and nothing more."""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-3")
    captured = {}

    class FakeAnthropic:
        def __init__(self, **kw):
            captured.update(kw)

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    llm_call.sdk_client()
    assert captured == {"api_key": "sk-3"}


# ─── text_of ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("data,expected", [
    ({"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}, "ab"),
    ({"content": [{"type": "thinking", "text": "no"}, {"type": "text", "text": "yes"}]}, "yes"),
    ({"content": []}, ""),
    ({}, ""),
    (None, ""),
    ({"content": "not-a-list"}, ""),
])
def test_text_of(data, expected):
    assert llm_call.text_of(data) == expected


# ─── The anti-decay guard ────────────────────────────────────────────

_URL = re.compile(r'["\']https://api\.anthropic\.com')


def _constructs_anthropic(src: str) -> bool:
    """True if the module actually CONSTRUCTS an SDK client.

    Uses the AST rather than a regex: `Anthropic(` appears in docstrings
    ("Drop-in replacement for `Anthropic().messages.create(...)`") and in
    display strings ("Anthropic (Claude)"), and a regex flags those. Only
    a real ast.Call counts, and a bare `Anthropic()` with no api_key —
    which the SDK happily fills from the environment — is caught too."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = (fn.id if isinstance(fn, ast.Name)
                else fn.attr if isinstance(fn, ast.Attribute) else None)
        if name == "Anthropic":
            return True
    return False


def _sources():
    for p in _root.rglob("*.py"):
        parts = set(p.parts)
        if "__pycache__" in parts or "__tests__" in parts or "node_modules" in parts:
            continue
        if p.name == "llm_call.py":
            continue
        yield p


def test_no_module_bypasses_the_seam():
    """THE point of P0.4. Every Anthropic call goes through llm_call, so
    the endpoint and the key have exactly one place they are decided.

    If this fails you added a call site that hardcodes the URL or builds
    its own SDK client — route it through llm_call.apost / llm_call.post /
    llm_call.post_with / llm_call.astream / llm_call.sdk_client instead.
    Re-fragmenting this is what made the orchestrator and the HIPAA path a
    36-file rewrite before this arc."""
    offenders = []
    for p in _sources():
        try:
            src = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = p.relative_to(_root).as_posix()
        if _URL.search(src):
            offenders.append(f"{rel}: hardcodes the Anthropic URL")
        if _constructs_anthropic(src):
            offenders.append(f"{rel}: constructs Anthropic() directly")
    assert not offenders, "call sites bypassing llm_call:\n  " + "\n  ".join(offenders)
