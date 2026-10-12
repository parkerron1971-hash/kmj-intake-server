"""The site builder sends a business's site content to Moonshot only when
Moonshot's host is a listed subprocessor (2026-10-12).

The privacy policy names every company that receives business data, and
Moonshot is not on it. Its key is set in production and one env flip
(SITE_BUILDER_PROVIDER, SITE_STAGE_PROVIDERS, SHIP_JUDGE_PROVIDER) used to
route builds there. Now the flip does nothing until CHIEF_SUBPROCESSOR_HOSTS
lists the host, which is the record that the policy names it.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import site_llm


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in ("SITE_BUILDER_PROVIDER", "SITE_STAGE_PROVIDERS", "SHIP_JUDGE_PROVIDER",
              "SITE_JUDGE_PROVIDER", "CHIEF_SUBPROCESSOR_HOSTS", "MOONSHOT_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(site_llm, "_UNLISTED_WARNED", False)


def test_an_unlisted_moonshot_stays_on_claude_everywhere(monkeypatch, capsys):
    monkeypatch.setenv("SITE_BUILDER_PROVIDER", "moonshot")
    monkeypatch.setenv("SITE_STAGE_PROVIDERS", '{"atelier": "moonshot"}')
    monkeypatch.setenv("SHIP_JUDGE_PROVIDER", "moonshot")
    assert site_llm.provider() == "anthropic"
    assert site_llm.provider_for("atelier/compose") == "anthropic"
    assert site_llm.provider_for("copy/hero") == "anthropic"
    assert site_llm.judge_provider() == "anthropic"
    assert "CHIEF_SUBPROCESSOR_HOSTS" in capsys.readouterr().out


def test_a_listed_moonshot_runs_as_configured(monkeypatch):
    monkeypatch.setenv("CHIEF_SUBPROCESSOR_HOSTS", "api.moonshot.ai")
    monkeypatch.setenv("SITE_BUILDER_PROVIDER", "moonshot")
    monkeypatch.setenv("SHIP_JUDGE_PROVIDER", "moonshot")
    assert site_llm.provider() == "moonshot"
    assert site_llm.provider_for("copy/hero") == "moonshot"
    assert site_llm.provider_for("drl/signals") == "anthropic", "the brain rule still holds"
    assert site_llm.judge_provider() == "moonshot"


def test_an_explicit_provider_name_is_gated_too(monkeypatch):
    called = []
    monkeypatch.setattr(site_llm, "_call_moonshot", lambda **kw: called.append(kw))

    class _Fake:
        def __init__(self, **kw):
            self.messages = self

        def create(self, **kw):
            class _R:
                content = []
            return _R()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _Fake)
    site_llm.create_message(model="claude-haiku-5-5", max_tokens=16, system="s",
                            user_content="u", provider_name="moonshot")
    assert called == [], "an unlisted moonshot is never called"


def test_the_default_is_untouched():
    assert site_llm.provider() == "anthropic"
    assert site_llm.judge_provider() == "anthropic"
