"""
api_usage_logger.py — record Anthropic API calls to api_usage table.

Every successful call to Anthropic (from ai_proxy.py + chief_of_staff.py
today; more agents later) calls log_api_usage(...) with the model, token
counts, and identifying context. We compute the cost using the price
table below and insert one row.

Designed to be FIRE-AND-FORGET — the logger never raises and never blocks
the caller. If Supabase is unreachable, we log the failure to stderr and
move on. We'd rather lose an audit row than fail a user-facing AI call.

═══════════════════════════════════════════════════════════════════════
USAGE
═══════════════════════════════════════════════════════════════════════

    from api_usage_logger import log_api_usage

    # After every successful Anthropic call:
    await log_api_usage(
        endpoint="/ai/proxy",
        model="claude-sonnet-4-5-20250929",
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        business_id=req.metadata.get("business_id") if req.metadata else None,
        user_id=req.metadata.get("auth_user_id") if req.metadata else None,
        task_type=req.task_type,
        duration_ms=elapsed_ms,
    )

═══════════════════════════════════════════════════════════════════════
PRICING
═══════════════════════════════════════════════════════════════════════

Anthropic's published rates (per million tokens, USD), as of 2026-05-25.
Update here when prices change — old rows keep their captured cost.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx


logger = logging.getLogger("api_usage_logger")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] usage: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)


# Per-million-token prices in USD cents. Input first, then output.
# Source: anthropic.com/pricing as of 2026-05-25.
# Keys are matched by prefix so e.g. "claude-sonnet-4-5-20250929" matches
# the "claude-sonnet-4" entry.
MODEL_PRICING_CENTS: Dict[str, tuple[float, float]] = {
    # Opus 4.x — premium tier
    "claude-opus-4":     (1500.0, 7500.0),   # $15/MTok input, $75/MTok output
    # Sonnet 5 — Chief chat/voice lanes (Chief Layers arc). Priced at the
    # Sonnet tier; update if anthropic.com/pricing says otherwise.
    "claude-sonnet-5":   (300.0, 1500.0),
    # Sonnet 4.x — balanced
    "claude-sonnet-4":   (300.0, 1500.0),    # $3/MTok input, $15/MTok output
    # Haiku 4.x — fast / cheap
    "claude-haiku-4":    (80.0, 400.0),      # $0.80/MTok input, $4/MTok output
    # Legacy fallbacks for any old model strings still in flight
    "claude-3-5-sonnet": (300.0, 1500.0),
    "claude-3-5-haiku":  (80.0, 400.0),
    "claude-3-opus":     (1500.0, 7500.0),
}


def _price_for_model(model: str) -> tuple[float, float]:
    """Return (input_cents_per_MTok, output_cents_per_MTok). Falls back
    to Sonnet pricing if no prefix matches (safe middle estimate)."""
    if not model:
        return (300.0, 1500.0)
    m = model.lower()
    for prefix, prices in MODEL_PRICING_CENTS.items():
        if m.startswith(prefix):
            return prices
    return (300.0, 1500.0)


def _compute_cost_cents(model: str, input_tokens: int, output_tokens: int) -> float:
    in_cents_per_mtok, out_cents_per_mtok = _price_for_model(model)
    cost = (
        (input_tokens  / 1_000_000.0) * in_cents_per_mtok +
        (output_tokens / 1_000_000.0) * out_cents_per_mtok
    )
    return round(cost, 4)


def log_api_usage_sync(
    *,
    endpoint: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    business_id: Optional[str] = None,
    task_type: Optional[str] = None,
    ok: bool = True,
) -> None:
    """Synchronous variant for sync call sites (composer/director). Same
    row shape; never raises. Arc 19 — site builds must meter (weight 5/25)."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return
    body: Dict[str, Any] = {
        "endpoint": endpoint, "model": model,
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "cost_cents": _compute_cost_cents(model, input_tokens or 0, output_tokens or 0),
        "ok": ok,
    }
    if business_id: body["business_id"] = business_id
    if task_type:   body["task_type"] = task_type
    try:
        httpx.post(
            f"{SUPABASE_URL}/rest/v1/api_usage",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=body, timeout=10.0,
        )
    except Exception as e:
        logger.warning(f"api_usage sync insert failed: {e}")


async def log_api_usage(
    *,
    endpoint: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    business_id: Optional[str] = None,
    user_id: Optional[str] = None,
    task_type: Optional[str] = None,
    duration_ms: Optional[int] = None,
    ok: bool = True,
    error: Optional[str] = None,
) -> None:
    """Append one row to api_usage. Never raises."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        logger.warning("api_usage: Supabase not configured; skipping log")
        return

    cost_cents = _compute_cost_cents(model, input_tokens, output_tokens)
    body: Dict[str, Any] = {
        "endpoint":      endpoint,
        "model":         model,
        "input_tokens":  int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "cost_cents":    cost_cents,
        "ok":            ok,
    }
    if business_id: body["business_id"] = business_id
    if user_id:     body["user_id"] = user_id
    if task_type:   body["task_type"] = task_type
    if duration_ms is not None: body["duration_ms"] = int(duration_ms)
    if error:       body["error"] = str(error)[:500]

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.post(
                f"{SUPABASE_URL}/rest/v1/api_usage",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json=body,
            )
        if r.status_code >= 400:
            logger.warning(f"api_usage insert {r.status_code}: {r.text[:200]}")
    except Exception as e:
        # Never raise — usage logging must not break the live call.
        logger.warning(f"api_usage insert failed: {e}")


def now_ms() -> int:
    return int(time.time() * 1000)
