# site_llm.py
# ─────────────────────────────────────────────────────────────────────
# Provider switch for the WEBSITE DESIGN BUILD pipeline (2026-07-17,
# Kevin's ruling: test Kimi K3 on site generation).
#
# Scope: the composer/director build stages —
#   module_router · hero_composer · DRL passes · sparse_input_enrichment
#   · feedback_enrichment — plus the Director's llm_judge on its OWN
#   independent switch. Default: the judge stays on Claude even while
#   the builder runs on Kimi (an independent grader is the honest
#   quality read); flip SITE_JUDGE_PROVIDER deliberately to compare
#   Claude-judged vs Kimi-self-judged builds.
#
# Env contract (flip per environment, no code changes):
#   SITE_BUILDER_PROVIDER  "anthropic" (default) | "moonshot" — build stages
#   SITE_JUDGE_PROVIDER    "anthropic" (default) | "moonshot" — the judge
#   SITE_BUILDER_MODEL     model id for the chosen provider
#                          (moonshot default: "kimi-k3")
#   MOONSHOT_API_KEY       required for moonshot
#   MOONSHOT_BASE_URL      default https://api.moonshot.ai/v1
#
# Moonshot's API is OpenAI-compatible (POST /chat/completions), so no
# extra SDK — plain httpx. The response is wrapped to quack like the
# Anthropic SDK message (`.content[0].text`, `.usage.input_tokens`,
# `.usage.output_tokens`), so call sites keep their existing extraction
# and usage-logging lines untouched.
#
# FAIL-OPEN: any moonshot failure (missing key, HTTP error, timeout,
# empty body) logs loudly and falls through to the Anthropic call. A
# bad experiment must never break a practitioner's site build.
# ─────────────────────────────────────────────────────────────────────

import logging
import os
from typing import Any, List, Optional

import httpx

logger = logging.getLogger("site_llm")

MOONSHOT_DEFAULT_MODEL = "kimi-k3"


class _TextBlock:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _Message:
    """Anthropic-SDK-shaped wrapper so existing call sites need no changes."""

    def __init__(self, text: str, input_tokens: int, output_tokens: int, model: str):
        self.content: List[_TextBlock] = [_TextBlock(text)]
        self.usage = _Usage(input_tokens, output_tokens)
        self.model = model


def provider() -> str:
    return (os.environ.get("SITE_BUILDER_PROVIDER") or "anthropic").strip().lower()


def judge_provider() -> str:
    """The Director's judge gets its OWN switch (2026-07-17, Kevin's
    ruling): default anthropic even while the builder runs on Kimi —
    Claude grading Kimi's work is the honest quality read. Flip
    SITE_JUDGE_PROVIDER=moonshot deliberately to see the difference
    when Kimi judges its own output. The two env vars are independent
    on purpose."""
    # K5 (Phase 1): the ship-gate judge is PINNED, never mirrored.
    # Arc C (2026-07-21, Kevin's ruling "the critic isn't the author"):
    # the legacy SITE_JUDGE_PROVIDER alias is RETIRED for the judge —
    # Railway had it set to moonshot, which silently made Kimi grade
    # Kimi's own builds. SHIP_JUDGE_PROVIDER remains the one deliberate
    # override; everything else judges on Claude.
    legacy = (os.environ.get("SITE_JUDGE_PROVIDER") or "").strip().lower()
    pinned = (os.environ.get("SHIP_JUDGE_PROVIDER") or "").strip().lower()
    if legacy and not pinned:
        logger.warning(
            "[site_llm] SITE_JUDGE_PROVIDER=%s is set but no longer honored "
            "for the judge (self-grading hazard) — set SHIP_JUDGE_PROVIDER "
            "explicitly if a non-Claude judge is truly intended.", legacy)
    return (pinned or "anthropic")


def _moonshot_model() -> str:
    return (os.environ.get("SITE_BUILDER_MODEL") or MOONSHOT_DEFAULT_MODEL).strip()


def _call_moonshot(*, max_tokens: int, temperature: Optional[float],
                   system: str, user_content: str, timeout: float) -> _Message:
    key = (os.environ.get("MOONSHOT_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("MOONSHOT_API_KEY not configured")
    base = (os.environ.get("MOONSHOT_BASE_URL") or "https://api.moonshot.ai/v1").rstrip("/")
    model = _moonshot_model()
    # Kimi K3 is a REASONING model: it spends completion tokens on
    # internal reasoning BEFORE the visible answer (live-probed: 86
    # reasoning tokens for a one-line reply). The composer's max_tokens
    # values are sized for Claude's direct output, so grant thinking
    # headroom on top — otherwise short-budget stages come back with
    # empty content.
    payload: dict = {
        "model": model,
        "max_tokens": max_tokens + 3000,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    }
    # Kimi K3 rejects any temperature except 1 ("invalid temperature:
    # only 1 is allowed for this model" — live-probed 2026-07-18). The
    # composer's temperature tuning is Claude-specific anyway, so we
    # simply never send sampling params to moonshot. Before this fix,
    # EVERY moonshot call 400'd and silently fell back to Claude — the
    # Kimi experiment was never actually running.
    _ = temperature  # accepted for signature parity; deliberately unsent
    with httpx.Client(timeout=timeout) as client:
        r = client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
    if r.status_code >= 400:
        raise RuntimeError(f"moonshot {r.status_code}: {r.text[:200]}")
    data = r.json()
    text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if not text:
        raise RuntimeError("moonshot returned empty content")
    usage = data.get("usage") or {}
    return _Message(
        text,
        int(usage.get("prompt_tokens") or 0),
        int(usage.get("completion_tokens") or 0),
        data.get("model") or model,
    )


def create_message(*, model: str, max_tokens: int, system: str, user_content: str,
                   temperature: Optional[float] = None, timeout: float = 120.0,
                   task: str = "site", provider_name: Optional[str] = None) -> Any:
    """Drop-in replacement for `Anthropic().messages.create(...)` in the
    site-build pipeline. `model` is the Anthropic model the call site
    would have used — kept as the fail-open fallback and the default
    provider's model. `provider_name` overrides the global switch for
    call sites with their own toggle (the judge)."""
    if (provider_name or provider()) == "moonshot":
        try:
            msg = _call_moonshot(
                max_tokens=max_tokens, temperature=temperature,
                system=system, user_content=user_content, timeout=timeout,
            )
            logger.info(f"[site_llm] {task}: moonshot/{msg.model} ok "
                        f"(in={msg.usage.input_tokens} out={msg.usage.output_tokens})")
            return msg
        except Exception as e:
            logger.warning(
                f"[site_llm] {task}: moonshot failed ({type(e).__name__}: {e}) "
                f"— falling back to anthropic/{model}"
            )
    # Default / fallback: Anthropic, exactly as before — with the SAME
    # sampling gate the direct ladder uses (#185 follow-up, 2026-07-18):
    # Opus 4.7/4.8, Sonnet 5 and Fable-class models 400 on a raw
    # temperature param, and the fail-open replay targets exactly those
    # models (the acceptance fallback leg lost every atelier fragment to
    # this before the gate was applied here too).
    from anthropic import Anthropic
    import model_ladder
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = Anthropic(api_key=api_key)
    kwargs: dict = {
        "model": model, "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
        "timeout": timeout,
    }
    kwargs.update(model_ladder.sampling_kwargs(model, temperature))
    return client.messages.create(**kwargs)
