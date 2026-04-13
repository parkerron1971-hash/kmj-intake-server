"""
ai_proxy.py — Solutionist System AI Proxy

Self-contained FastAPI router that proxies Anthropic Claude API calls
from the Solutionist Studio Tauri client to Anthropic's API server-side.
The Anthropic API key never leaves Railway.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT — how to wire this into your existing Railway FastAPI app
═══════════════════════════════════════════════════════════════════════

1. Drop this file into your Railway project (e.g. alongside your main.py).

2. In your existing main.py, add:

       from ai_proxy import router as ai_proxy_router
       app.include_router(ai_proxy_router)

   This adds POST /ai/proxy without touching any of your existing routes.

3. Set the environment variable in the Railway dashboard:

       ANTHROPIC_API_KEY=sk-ant-api03-...

   (Use a NEW key — the old one was leaked in the desktop client and
   should be rotated in the Anthropic dashboard.)

4. Make sure httpx is in your requirements.txt:

       httpx>=0.27.0

5. CORS — the Tauri desktop client runs from a non-http origin
   (typically `tauri://localhost` or `https://tauri.localhost` on
   Windows). Confirm your existing CORSMiddleware allowlist includes
   that origin, or use `allow_origins=["*"]` for the single-user
   desktop app. This file does NOT touch your CORS config.

6. Optional hardening (TODO, not required for v1):
   - Add a shared-secret header check (X-Studio-Secret) so only the
     Tauri client can hit /ai/proxy
   - Add per-IP rate limiting via slowapi
   - Add request body size limits

═══════════════════════════════════════════════════════════════════════
ENDPOINT
═══════════════════════════════════════════════════════════════════════

POST /ai/proxy

Request body (JSON):
    {
      "task_type":     "plan" | "build" | "score" | "draft" | "volume" | "briefing" | null,
      "messages":      [{"role": "user"|"assistant", "content": "..."}],
      "system":        "...",        # optional system prompt
      "max_tokens":    4096,         # optional, default 4096
      "temperature":   1.0,          # optional, default 1.0
      "model_override": null,        # optional escape hatch — server respects if present
      "metadata":      {}            # optional, passed through to Anthropic
    }

Response (JSON):
    {
      "content":     "...joined text from all text blocks...",
      "model":       "claude-sonnet-4-5-20250929",
      "stop_reason": "end_turn",
      "usage":       {"input_tokens": 123, "output_tokens": 456},
      "raw":         { ...full Anthropic response... }
    }

On Anthropic error (4xx/5xx), returns the matching status with:
    { "error": "...", "status": N }
"""

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Server-owned model selection. Change here, no client redeploy needed.
TASK_MODEL_MAP: Dict[str, str] = {
    "plan":     "claude-sonnet-4-5-20250929",
    "build":    "claude-opus-4-6",
    "score":    "claude-sonnet-4-5-20250929",
    "draft":    "claude-sonnet-4-5-20250929",
    "volume":   "claude-haiku-4-5-20251001",
    "briefing": "claude-sonnet-4-5-20250929",
}
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 1.0

# Generous timeout — Opus completions can take 60+ seconds.
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)

logger = logging.getLogger("ai_proxy")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] ai_proxy: %(message)s"
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ═══════════════════════════════════════════════════════════════════════
# REQUEST / RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════

class Message(BaseModel):
    role: str
    content: Any  # str OR list of content blocks (passthrough for future use)


class ProxyRequest(BaseModel):
    task_type: Optional[str] = None
    messages: List[Message]
    system: Optional[str] = None
    max_tokens: Optional[int] = Field(default=DEFAULT_MAX_TOKENS)
    temperature: Optional[float] = Field(default=DEFAULT_TEMPERATURE)
    model_override: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["ai_proxy"])


def _select_model(task_type: Optional[str], override: Optional[str]) -> str:
    """Pick the model: override > task_type lookup > default."""
    if override:
        return override
    if task_type and task_type in TASK_MODEL_MAP:
        return TASK_MODEL_MAP[task_type]
    return DEFAULT_MODEL


def _join_text_blocks(content: Any) -> str:
    """
    Anthropic returns `content` as a list of typed blocks. We join all
    text blocks for callers that just want the prose. Non-text blocks
    are skipped here but remain available via the `raw` field.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


@router.post("/ai/proxy")
async def ai_proxy(req: ProxyRequest):
    """Proxy a Claude Messages API call. The API key never leaves Railway."""

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY env var is not set on Railway")
        raise HTTPException(
            status_code=500,
            detail="AI proxy is not configured: ANTHROPIC_API_KEY missing on server",
        )

    model = _select_model(req.task_type, req.model_override)

    # Build the Anthropic payload. Only include fields Anthropic expects.
    anthropic_payload: Dict[str, Any] = {
        "model": model,
        "max_tokens": req.max_tokens or DEFAULT_MAX_TOKENS,
        "temperature": req.temperature if req.temperature is not None else DEFAULT_TEMPERATURE,
        "messages": [m.model_dump() for m in req.messages],
    }
    if req.system:
        anthropic_payload["system"] = req.system
    if req.metadata:
        anthropic_payload["metadata"] = req.metadata

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                ANTHROPIC_API_URL,
                headers=headers,
                json=anthropic_payload,
            )
    except httpx.TimeoutException as e:
        logger.error(f"Anthropic request timed out: {e}")
        raise HTTPException(status_code=504, detail="Anthropic API timed out")
    except httpx.HTTPError as e:
        logger.error(f"Anthropic request failed: {e}")
        raise HTTPException(status_code=502, detail=f"Anthropic API request failed: {e}")

    # Pass through Anthropic errors with their status code
    if resp.status_code >= 400:
        try:
            err_body = resp.json()
        except Exception:
            err_body = {"error": resp.text}
        logger.warning(
            f"Anthropic returned {resp.status_code} for task_type={req.task_type} model={model}: {err_body}"
        )
        raise HTTPException(status_code=resp.status_code, detail=err_body)

    data = resp.json()

    # Normalize the response so the client doesn't have to dig
    content_text = _join_text_blocks(data.get("content"))
    usage = data.get("usage", {})

    logger.info(
        f"ai_proxy ok task_type={req.task_type} model={model} "
        f"input_tokens={usage.get('input_tokens')} output_tokens={usage.get('output_tokens')}"
    )

    return {
        "content": content_text,
        "model": data.get("model", model),
        "stop_reason": data.get("stop_reason"),
        "usage": usage,
        "raw": data,
    }


@router.get("/ai/proxy/health")
async def ai_proxy_health():
    """Liveness probe — confirms the router is mounted and the key is present."""
    return {
        "status": "ok",
        "key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "default_model": DEFAULT_MODEL,
        "task_types": list(TASK_MODEL_MAP.keys()),
    }
