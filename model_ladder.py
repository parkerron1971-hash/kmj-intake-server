"""
model_ladder.py — Site Arc 12 "REASONING": model failures can never be
silent or fatal again.

Shared by the DRL passes (agents/composer/drl/passes.py) and the atelier
(atelier.py) — the two LLM layers whose quiet death produced a live page
with ZERO bespoke sections and (via the DRO gate) ZERO ceremony seams,
with nothing in the logs louder than a per-section warning.

What lives here:

  timeout_for(task, model)      — Opus streams ~2-3x slower than Sonnet;
                                  ceilings scale by model family. Composes
                                  run as background jobs, so long ceilings
                                  are safe.
  sampling_kwargs(model, t)     — Opus 4.7/4.8 (and Sonnet 5 / Fable)
                                  REJECT `temperature` with a 400; sending
                                  it means every call fails identically
                                  and "the model went silent". Omit it for
                                  those families, keep it for Sonnet 4.x.
  call_with_ladder(...)         — the fallback ladder:
                                    1. primary model, family-scaled timeout
                                    2. model-identity error (404/403/
                                       invalid-model 400) → ONE retry on
                                       FALLBACK_MODEL, logged LOUD
                                       (logger.error) + persisted
                                       breadcrumb (site_config.
                                       model_fallbacks)
                                    3. TIMEOUT → ONE retry on the SAME
                                       model with max_tokens reduced 35%
                                       (a shorter brief that finishes
                                       beats a rich one that never
                                       arrives) → then the sonnet rung →
                                       (callers' own minimal-mode, where
                                       present, remains the last rung)
                                    4. transport/5xx → re-raise untouched;
                                       the SDK's max_retries + the
                                       callers' existing attempt/retry
                                       machinery own those.
  record_model_fallback(...)    — the persisted breadcrumb: appends to
                                  business_sites.site_config.model_fallbacks
                                  (capped list; render_and_persist re-reads
                                  fresh site_config before its patch, so
                                  breadcrumbs written mid-compose survive).
  probe_models_once(models)     — cheap startup insurance: on the first
                                  compose per process, fire a 1-token ping
                                  at the configured DRL + atelier models
                                  (10s timeout, daemon thread, catches
                                  everything). Pure observability — an
                                  unreachable model shows up as
                                  '[model-probe] {model} unreachable: …'
                                  minutes before anyone stares at a bare
                                  fallback page. Never blocks, never raises.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional, Tuple

import llm_call

logger = logging.getLogger("model_ladder")

# The ladder's one rung down. Sonnet 4.5 (dated full ID): accepts
# `temperature`, streams fast, and has been the composer's reliable
# workhorse across Arcs 1-11.
FALLBACK_MODEL = "claude-sonnet-4-5-20250929"

# Timeout-retry token reduction: 1 - 0.35.
TOKEN_REDUCTION = 0.65
_MIN_REDUCED_TOKENS = 256

# task → (fast-family ceiling, slow-family ceiling), seconds.
#   "signals" — DRL signal detection (SIGNAL_MAX_TOKENS≈3200)
#   "dro"     — DRO authoring incl. minimal mode (DRO_MAX_TOKENS=32000, streamed)
#   "atelier" — bespoke section authoring (ATELIER_MAX_TOKENS≈8000)
#   "spec"    — page-spec/copy composition (SPEC_MAX_TOKENS=4000)
# Slow-family (Opus/Fable) ceilings are ~2x: Opus streams ~2-3x slower
# per token. The compose runs as a chief_jobs background job (stale sweep
# at 10 min), so 240s worst-case single calls stay inside budget.
_TIMEOUTS = {
    "signals": (75.0, 120.0),
    "dro": (120.0, 240.0),
    "atelier": (120.0, 240.0),
    "spec": (75.0, 120.0),
    # Canvas Pass (Phase 1): whole-page chunk authoring (8-12K tokens per
    # call) — same ceilings as the atelier family.
    "canvas": (120.0, 240.0),
}
_DEFAULT_TIMEOUTS = (120.0, 240.0)

# Model families that stream slowly (get the long ceilings).
_SLOW_FAMILY_MARKERS = ("opus", "fable", "mythos")

# Model families that REJECT sampling params (temperature/top_p/top_k → 400).
_NO_SAMPLING_MARKERS = ("opus-4-7", "opus-4-8", "opus-5", "fable", "mythos", "sonnet-5")

# 400s that mean "the model id itself is the problem" (vs. a payload bug).
_MODEL_ERR_MARKERS = ("not_found", "not found", "does not exist",
                      "unknown model", "invalid model", "model:",
                      "permission", "access")


def _is_slow_family(model: str) -> bool:
    m = (model or "").lower()
    return any(k in m for k in _SLOW_FAMILY_MARKERS)


# THE CEILING FOLLOWS THE OUTPUT (2026-08-29). A per-call timeout has to
# fit the tokens it asks for. Sonnet 5 streams ~40 tok/s: a 14k-token DRO
# needs ~350s, and the 120s "fast family" ceiling timed out EVERY
# rationale; the -35% retry then hit its own cap mid-JSON, and the
# api_usage ledger showed every DRO at exactly 9,100 output tokens
# (14000 x 0.65) — paid for, unparseable, and the reason builds fell to
# minimal mode. The family ceiling stays as the FLOOR; the output size
# raises it: max_tokens / 30 tok/s + 30s of connect-and-first-token.
_MIN_TOKENS_PER_SECOND = 30.0
_CEILING_OVERHEAD_S = 30.0


def timeout_for(task: str, model: str, max_tokens: Optional[int] = None) -> float:
    """Per-call ceiling: the family floor (Opus: signals 120s / DRO 240s /
    atelier 240s; Sonnet: 75/120/120) raised to what `max_tokens` needs at
    a conservative streaming rate. Callers that know their output budget
    pass it; the bare form keeps the old floors."""
    fast, slow = _TIMEOUTS.get(task, _DEFAULT_TIMEOUTS)
    floor = slow if _is_slow_family(model) else fast
    try:
        n = int(max_tokens or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return floor
    return max(floor, n / _MIN_TOKENS_PER_SECOND + _CEILING_OVERHEAD_S)


def supports_sampling(model: str) -> bool:
    """False for the families where `temperature` returns a 400
    (Opus 4.7/4.8, Sonnet 5, Fable/Mythos)."""
    m = (model or "").lower()
    return not any(k in m for k in _NO_SAMPLING_MARKERS)


def sampling_kwargs(model: str, temperature: Optional[float]) -> dict:
    """`{"temperature": t}` where the model accepts it, `{}` where it
    would 400. This is the fix for the live Arc 11 failure mode: the
    atelier's Opus default + temperature=0.8 made EVERY bespoke call
    fail with an invalid_request 400, silently, per section."""
    if temperature is None or not supports_sampling(model):
        return {}
    return {"temperature": temperature}


def is_model_unavailable_error(e: BaseException) -> bool:
    """Model-identity failures: 404 (unknown model), 403 (no access),
    or a 400 whose message points at the model id. These ladder to
    FALLBACK_MODEL; everything else keeps its existing semantics."""
    status = getattr(e, "status_code", None)
    if status in (403, 404):
        return True
    if status == 400:
        msg = str(e).lower()
        return "model" in msg and any(k in msg for k in _MODEL_ERR_MARKERS)
    return False


def is_timeout_error(e: BaseException) -> bool:
    """SDK read/connect timeouts (anthropic.APITimeoutError and friends).
    These do NOT ladder blindly — they get one same-model retry at
    reduced max_tokens first (see call_with_ladder)."""
    try:
        import anthropic
        if isinstance(e, anthropic.APITimeoutError):
            return True
    except Exception:
        pass
    name = type(e).__name__.lower()
    return "timeout" in name or "timed out" in str(e).lower()


def record_model_fallback(business_id: str, *, task: str, from_model: str,
                          to_model: Optional[str], reason: str) -> None:
    """Persist the breadcrumb: site_config.model_fallbacks (list, capped
    at 20, newest last). to_model=None records 'no rung succeeded'.
    Fail-soft — forensics must never break a compose."""
    if not business_id or business_id == "unknown":
        return
    try:
        import sb_clients
        rows = sb_clients.sb_get_as_service(
            f"/business_sites?business_id=eq.{business_id}"
            "&select=id,site_config&limit=1") or []
        if not rows:
            return
        site = rows[0]
        cfg = dict(site.get("site_config") or {})
        entries = list(cfg.get("model_fallbacks") or [])
        entries.append({
            "task": task,
            "from_model": from_model,
            "to_model": to_model,
            "reason": str(reason)[:200],
            "at": datetime.now(timezone.utc).isoformat(),
        })
        cfg["model_fallbacks"] = entries[-20:]
        sb_clients.sb_patch_as_service(
            f"/business_sites?id=eq.{site['id']}", {"site_config": cfg})
    except Exception as e:
        logger.info(f"[model-ladder] breadcrumb write skipped for "
                    f"{str(business_id)[:8]}: {e}")


def call_with_ladder(do_call: Callable[..., Any], *, model: str, task: str,
                     business_id: str = "", max_tokens: int,
                     ) -> Tuple[Any, str]:
    """Run `do_call(model=…, max_tokens=…, timeout=…)` under the ladder.
    Returns (result, model_actually_used). Raises only when every rung
    failed — and by then the failure has been logged LOUD and
    breadcrumbed, so it is never silent (callers may still fail-soft).

    Rungs:
      model-identity error → ONE retry on FALLBACK_MODEL.
      timeout → ONE retry on the SAME model at 65% max_tokens, then the
                FALLBACK_MODEL rung (also at 65% — finishing beats rich).
      anything else (transport, 5xx, overloaded) → re-raise: the SDK's
                max_retries and the callers' attempt/parse-retry loops
                already own those semantics.
    """
    def _sonnet_rung(orig: BaseException, tokens: int, why: str) -> Tuple[Any, str]:
        if (model or "").strip() == FALLBACK_MODEL:
            raise orig  # already on the bottom rung — nothing below us
        logger.error(f"[model-ladder] {task}: {model} unavailable "
                     f"({orig}) — falling back to sonnet")
        record_model_fallback(business_id, task=task, from_model=model,
                              to_model=FALLBACK_MODEL,
                              reason=f"{why}: {type(orig).__name__}: {orig}")
        return (do_call(model=FALLBACK_MODEL, max_tokens=tokens,
                        timeout=timeout_for(task, FALLBACK_MODEL, tokens)),
                FALLBACK_MODEL)

    primary_timeout = timeout_for(task, model, max_tokens)
    try:
        return do_call(model=model, max_tokens=max_tokens,
                       timeout=primary_timeout), model
    except Exception as e:
        if is_model_unavailable_error(e):
            return _sonnet_rung(e, max_tokens, "model_unavailable")
        if is_timeout_error(e):
            reduced = max(int(max_tokens * TOKEN_REDUCTION),
                          _MIN_REDUCED_TOKENS)
            logger.warning(
                f"[model-ladder] {task}: {model} timed out after "
                f"{primary_timeout:.0f}s — retrying SAME model at "
                f"max_tokens={reduced} (-35%)")
            try:
                return do_call(model=model, max_tokens=reduced,
                               timeout=timeout_for(task, model, reduced)), model
            except Exception as e2:
                if not (is_timeout_error(e2)
                        or is_model_unavailable_error(e2)):
                    raise  # transport/5xx keep their existing semantics
                return _sonnet_rung(e2, reduced, "timeout_after_reduction")
        raise


# ─── Startup model probe (cheap insurance, once per process) ───────────
_probe_done = False
_probe_lock = threading.Lock()


def probe_models_once(models: Iterable[Optional[str]]) -> None:
    """On the FIRST compose per process, ping each configured model with
    a 1-token request (10s timeout) from a daemon thread. Failures log
    '[model-probe] {model} unreachable: {err}' — pure observability;
    never blocks a compose, never raises."""
    global _probe_done
    with _probe_lock:
        if _probe_done:
            return
        _probe_done = True
    targets = [m for m in dict.fromkeys(models) if m]

    def _run() -> None:
        try:
            # The SDK import now happens inside llm_call.sdk_client, which
            # keeps it just as lazy as it was here.
            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                logger.info("[model-probe] skipped: no ANTHROPIC_API_KEY")
                return
            client = llm_call.sdk_client(key=key, timeout=10.0, max_retries=0)
            for m in targets:
                try:
                    # NO temperature — the slow families reject it.
                    client.messages.create(
                        model=m, max_tokens=1,
                        messages=[{"role": "user", "content": "ping"}])
                    logger.info(f"[model-probe] {m} reachable")
                except Exception as e:
                    logger.error(f"[model-probe] {m} unreachable: {e}")
        except Exception as e:
            logger.info(f"[model-probe] skipped: {e}")

    try:
        threading.Thread(target=_run, daemon=True,
                         name="model-probe").start()
    except Exception as e:
        logger.info(f"[model-probe] thread start failed (ignored): {e}")
