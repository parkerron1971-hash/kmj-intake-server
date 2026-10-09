"""
test_s45_site_builder.py — the site builder's Sonnet 4.5 defaults and fallbacks move off it (retires 2026-11-30).

Production runs the builder on Opus 5.5 and the judge on Sonnet 5.5 through
env vars; what still named Sonnet 4.5 were code defaults, last resorts and
the model ladder's rescue rung, all of which would 404 after the date. They
move to Sonnet 5.5 (Anthropic's named replacement) with thinking held off
where Sonnet 4.5 never thought, and ~30% more room. site_llm sends
`thinking` through extra_body: the pinned SDK (0.34.2) predates the keyword,
so passing it directly (as the composer probe has since #1327) would be a
TypeError before the request left.
"""
from __future__ import annotations

import importlib
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
S55 = "claude-sonnet-5-5"

FILES = ["site_llm.py", "model_ladder.py", "builder_v2.py", "design_coach.py", "spec_author.py",
         "vision_grader.py", "site_check.py", "canvas.py", "design_specs.py", "nav_spec.py",
         "discovery.py", "agents/composer/hero_composer.py", "agents/composer/module_router.py",
         "agents/director_agent/llm_judge.py", "agents/director_agent/feedback_enrichment.py",
         "agents/sparse_input_enrichment.py", "agents/composer/_spike_fire_three.py",
         "agents/composer/drl/passes.py"]


@pytest.mark.parametrize("path", FILES)
def test_no_site_builder_file_names_sonnet_4_5_any_more(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    assert "claude-sonnet-4-5" not in src and "claude-sonnet-4-20250514" not in src


def test_site_llm_sends_thinking_through_extra_body_not_as_a_keyword(monkeypatch):
    import site_llm
    calls = []

    class Client:
        class messages:
            @staticmethod
            def create(**kw):
                calls.append(kw)
                return object()
    monkeypatch.setattr(site_llm.llm_call, "sdk_client", lambda key=None: Client())
    monkeypatch.setattr(site_llm, "provider_for", lambda task: "anthropic")
    site_llm.create_message(model=S55, max_tokens=400, system="s", user_content="u",
                            temperature=0.4, task="nav_spec",
                            thinking={"type": "between_tools"})
    kw = calls[0]
    assert "thinking" not in kw and "temperature" not in kw
    assert kw["extra_body"] == {"thinking": {"type": "between_tools"}}


def test_the_ladder_rescue_rung_is_sonnet_5_5_and_rolls_back(monkeypatch):
    import model_ladder
    monkeypatch.delenv("MODEL_LADDER_FALLBACK_MODEL", raising=False)
    assert importlib.reload(model_ladder).FALLBACK_MODEL == S55
    monkeypatch.setenv("MODEL_LADDER_FALLBACK_MODEL", "claude-sonnet-5")
    assert importlib.reload(model_ladder).FALLBACK_MODEL == "claude-sonnet-5"
    monkeypatch.delenv("MODEL_LADDER_FALLBACK_MODEL")
    importlib.reload(model_ladder)


AGENTS = [("agents.composer.hero_composer", "COMPOSER_MODEL", "HERO_COMPOSER_MODEL"),
          ("agents.composer.module_router", "ROUTER_MODEL", "MODULE_ROUTER_MODEL"),
          ("agents.director_agent.llm_judge", "JUDGE_MODEL", "DIRECTOR_JUDGE_MODEL"),
          ("agents.director_agent.feedback_enrichment", "ENRICHMENT_MODEL", "FEEDBACK_ENRICHMENT_MODEL"),
          ("agents.sparse_input_enrichment", "ENRICHMENT_MODEL", "SPARSE_ENRICHMENT_MODEL")]


@pytest.mark.parametrize("mod,attr,env", AGENTS)
def test_agent_default_is_sonnet_5_5_with_a_rollback(monkeypatch, mod, attr, env):
    monkeypatch.delenv(env, raising=False)
    m = importlib.reload(importlib.import_module(mod))
    assert getattr(m, attr) == S55
    monkeypatch.setenv(env, "claude-sonnet-5")
    assert getattr(importlib.reload(m), attr) == "claude-sonnet-5"
    monkeypatch.delenv(env)
    importlib.reload(m)


@pytest.mark.parametrize("path", ["design_specs.py", "nav_spec.py", "agents/composer/hero_composer.py",
                                  "agents/composer/module_router.py", "agents/director_agent/llm_judge.py",
                                  "agents/director_agent/feedback_enrichment.py",
                                  "agents/sparse_input_enrichment.py"])
def test_every_site_llm_call_here_holds_thinking_off(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    assert src.count("site_llm.create_message(") == src.count("thinking=model_ladder.thinking_off_kwargs(")


def test_spec_and_discovery_defaults(monkeypatch):
    for env in ("DESIGN_SPEC_MODEL", "NAV_SPEC_MODEL", "DISCOVERY_STUDY_MODEL"):
        monkeypatch.delenv(env, raising=False)
    import design_specs
    import discovery
    import nav_spec
    assert design_specs._spec_model() == nav_spec._spec_model() == discovery._study_model() == S55
    assert discovery._sdk_thinking_off(S55) == {"extra_body": {"thinking": {"type": "between_tools"}}}
    # On a model that cannot turn thinking off (the ladder may hand it Opus),
    # nothing is added.
    assert discovery._sdk_thinking_off("claude-opus-5-5") == {}
