"""
fallback_brain.py — the backup brain (2026-07-12, Kevin's resilience ruling).

If Anthropic is unreachable, errors, or rate-limits Chief's turn, the
same conversation is retried ONCE against a second provider (OpenAI,
whose key is already on Railway for TTS + the inference gate). Chief
degrades — no prompt cache, a different model's instincts — but it
NEVER goes mute while the business rails keep running.

Design constraints:
  * Chief's operating manual + [ACTION:{...}] protocol are plain text,
    so the same system prompt ports verbatim — only the cache-split
    markers are stripped (OpenAI has no equivalent of Anthropic's
    cache_control blocks).
  * Fail-open discipline: any error here returns "" so the caller's
    existing "can't reach the language model" path still stands.
  * Kevin gets ONE push + changelog entry per outage window (6h dedup),
    not one per failed turn.

Env:
  FALLBACK_BRAIN        'on' (default) | 'off' — kill switch.
  FALLBACK_BRAIN_MODEL  OpenAI model id, default 'gpt-4o-mini'.
                        NOT gpt-4o: Chief's ~33.5k-token prompt
                        exceeds gpt-4o's 30k TPM ceiling on this
                        org's tier, so it 429'd every time. See
                        _model() for the full reasoning.
  OPENAI_API_KEY        already configured (TTS / inference gate).
"""

import json
import logging
import re
import os
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("fallback_brain")
# Every other module in this service attaches its own handler; this one
# did not, which made the feature undebuggable in exactly the situation
# it exists for. A bare logger's records depend on whatever uvicorn left
# the root config in, so a failed failover could produce NO log line at
# all — and silence reads identically to "the code never ran". First live
# test of this feature lost an hour to that ambiguity.
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] fallback: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
    logger.propagate = False

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

# One notification per outage window, tracked in-process. Railway runs a
# single instance; if that ever changes this just means one push per
# instance, which is still fine.
_NOTIFY_WINDOW_S = 6 * 3600
_last_notified: float = 0.0


def enabled() -> bool:
    if (os.environ.get("FALLBACK_BRAIN") or "on").strip().lower() == "off":
        return False
    return bool(os.environ.get("OPENAI_API_KEY"))


def _model() -> str:
    # gpt-4o-mini, not gpt-4o, and the live test is why.
    #
    # Chief's prompt is ~33,500 tokens (operating manual + business
    # context + dynamic state). On Anthropic that is cached and cheap. On
    # OpenAI there is no cache, and gpt-4o on this org's tier has a
    # 30,000 TPM ceiling — so a SINGLE Chief turn exceeded the per-minute
    # budget and the fallback returned 429 every time. Not intermittent:
    # arithmetic. The backup brain could never once have answered.
    #
    # gpt-4o-mini's ceiling on the same tier is far higher, so 33.5k fits.
    # It is also ~17x cheaper per turn (~$0.005 vs ~$0.084) on a path with
    # no prompt caching, which matters because every fallback turn pays
    # full freight for that whole manual.
    #
    # Quality dips, as the spec always said it would — this keeps people
    # moving during an outage, it is not the same brain. Raising the
    # OpenAI tier and setting FALLBACK_BRAIN_MODEL=gpt-4o is the upgrade
    # path if that trade stops being worth it.
    return (os.environ.get("FALLBACK_BRAIN_MODEL") or "gpt-4o-mini").strip()


def _flatten_system(system: Any) -> str:
    """Anthropic system can be a string (with our cache-split markers) or
    a list of text blocks. OpenAI wants one plain string."""
    if isinstance(system, list):
        text = "\n".join(
            (b.get("text") or "") for b in system if isinstance(b, dict))
    else:
        text = str(system or "")
    return (text.replace("[[CHIEF_GLOBAL_SPLIT]]", "\n")
                .replace("[[CHIEF_CACHE_SPLIT]]", "\n").strip())


# ─── The trim (2026-07-28) ───────────────────────────────────────────
# Forwarding Chief's whole system prompt is what made this feature
# impossible: ~33,500 tokens against a per-minute ceiling, so the request
# was rejected before the model saw a word of it.
#
# The prompt carries three segments, marked for Anthropic's cache:
#   1  universal identity + rules      (above [[CHIEF_GLOBAL_SPLIT]])
#   2  operating manual + the ~128-verb ACTION catalogue
#   3  live business state             (below [[CHIEF_CACHE_SPLIT]])
#
# Segment 2 is the bulk, and a backup brain does not need it — because
# the backup brain does not ACT. That is a deliberate narrowing, not
# only a size saving: a degraded model emitting [ACTION:{...}] tags that
# create, send, invoice or book is the one combination worth refusing.
# It answers, it explains, it promises the action for when the primary is
# back. Everything today's registry work says about class-C verbs argues
# the same way.
#
# So: a compact purpose-written manual, a slice of segment 2's head for
# voice and vertical, and as much of segment 3 as fits — segment 3 being
# the part that actually answers "how did this week go".

# Matches the [ACTION:{...}] tags the primary prompt teaches by example.
_ACTION_TAG_RE = re.compile(r"\[ACTION:.*?\]\]?", re.S)

FALLBACK_VOICE_CHARS = 3_000      # segment 2 head — who this business is
FALLBACK_STATE_CHARS = 9_000      # segment 3 — the live numbers
FALLBACK_MAX_MESSAGES = 8         # recent turns only

_BACKUP_MANUAL = """You are Chief, the operating intelligence for this business.

You are running as a BACKUP because the primary model is unavailable. Two
rules follow from that, and they matter more than anything else here:

1. You CANNOT take actions right now. No creating, editing, sending,
   invoicing, booking, publishing or deleting — none of it is wired up on
   this path. Never emit an [ACTION:...] tag; it will not run.
2. If asked to DO something, say plainly that you will handle it as soon
   as the connection is back, and answer whatever part of the question you
   can answer with what you know.

Otherwise be yourself: direct, warm, concrete. Lead with the answer. Use
the real names and numbers below rather than generalities. Keep it short —
you are covering a gap, not writing an essay."""


def _fallback_system(system: Any) -> str:
    """The trimmed system prompt: small enough to actually send."""
    raw = str(system or "") if not isinstance(system, list) else _flatten_system(system)

    # Markers are present because the fallback is handed the ORIGINAL
    # string, not the block list built for Anthropic's cache.
    if "[[CHIEF_CACHE_SPLIT]]" in raw:
        stable, _, dynamic = raw.partition("[[CHIEF_CACHE_SPLIT]]")
    else:
        stable, dynamic = raw, ""
    if "[[CHIEF_GLOBAL_SPLIT]]" in stable:
        _universal, _, per_business = stable.partition("[[CHIEF_GLOBAL_SPLIT]]")
    else:
        per_business = stable

    parts = [_BACKUP_MANUAL]
    # Scrub action-tag examples out of the voice slice. Telling the model
    # "never emit [ACTION:...]" while handing it worked examples of
    # exactly that is an instruction fighting a demonstration, and
    # demonstrations usually win. Cheaper to remove them than to hope.
    voice = _ACTION_TAG_RE.sub("", per_business)[:FALLBACK_VOICE_CHARS].strip()
    if voice:
        parts.append("=== HOW THIS BUSINESS SOUNDS ===\n" + voice)
    state = dynamic.strip()[:FALLBACK_STATE_CHARS].strip()
    if state:
        parts.append("=== LIVE BUSINESS STATE ===\n" + state)
    return "\n\n".join(parts)


def _trim_messages(messages: List[Dict]) -> List[Dict]:
    """Recent turns only. History is unbounded on the primary path, where
    it is cached; here every token is paid for and counted against the
    per-minute ceiling that broke this feature in the first place."""
    return messages[-FALLBACK_MAX_MESSAGES:] if len(messages) > FALLBACK_MAX_MESSAGES else messages


def _flatten_content(content: Any) -> str:
    """Anthropic message content may be a string or a list of blocks."""
    if isinstance(content, list):
        return "\n".join(
            (b.get("text") or "") for b in content
            if isinstance(b, dict) and b.get("type") in (None, "text"))
    return str(content or "")


async def _notify_owner(reason: str) -> None:
    """Tell Kevin the backup brain engaged — once per window."""
    global _last_notified
    now = time.time()
    if now - _last_notified < _NOTIFY_WINDOW_S:
        return
    _last_notified = now
    try:
        # Reuse the watchdog's owner-resolution + changelog + push rails.
        import platform_watchdog as wd
        import push_notifications
        from lead_admin import _service_headers
        headers = _service_headers()
        async with httpx.AsyncClient(timeout=15) as c:
            await wd._log_finding(
                c, headers,
                "Backup brain engaged",
                f"Anthropic call failed ({reason[:200]}); Chief answered on "
                f"{_model()}. Quality may dip until the primary recovers — "
                "no practitioner saw an outage.",
                pending=True)
            owner = await wd._owner_user_id(c, headers)
        if owner:
            push_notifications.send_to_user(
                owner,
                title="Chief switched to the backup brain",
                body=f"Anthropic is erroring; replies are running on {_model()}. "
                     "The system is fine — check Mission Control when you can.",
                nav="studio")
    except Exception as e:
        logger.warning(f"[fallback] owner notify failed (non-fatal): {e}")


async def call_fallback(client: httpx.AsyncClient, system: Any,
                        messages: List[Dict], max_tokens: int,
                        business_id: Optional[str] = None,
                        reason: str = "") -> str:
    """One attempt against the fallback provider. Returns '' on any
    failure so the caller's existing mute-path handling stands."""
    if not enabled():
        # Say WHICH gate closed. "Disabled" and "no key" are different
        # problems with different fixes, and from the outside both look
        # like Chief going quiet.
        logger.warning(
            "[fallback] NOT attempted — %s",
            "FALLBACK_BRAIN=off" if (os.environ.get("FALLBACK_BRAIN") or "on"
                                     ).strip().lower() == "off"
            else "OPENAI_API_KEY is not set")
        return ""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = _model()
    logger.info("[fallback] attempting %s (primary failed: %s)", model, reason[:120])

    oai_messages: List[Dict[str, str]] = [
        {"role": "system", "content": _fallback_system(system)}]
    for m in _trim_messages(messages):
        role = m.get("role") or "user"
        if role not in ("user", "assistant"):
            role = "user"
        oai_messages.append({"role": role, "content": _flatten_content(m.get("content"))})

    started_ms = int(time.time() * 1000)
    try:
        resp = await client.post(
            OPENAI_CHAT_URL,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": model, "messages": oai_messages,
                  "max_completion_tokens": max_tokens},
            timeout=60.0)
    except httpx.HTTPError as e:
        logger.warning(f"[fallback] OpenAI request failed: {e}")
        return ""
    if resp.status_code >= 400:
        logger.warning(f"[fallback] OpenAI error {resp.status_code}: {resp.text[:200]}")
        return ""

    try:
        data = resp.json()
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
    except (ValueError, AttributeError, IndexError) as e:
        logger.warning(f"[fallback] OpenAI response parse failed: {e}")
        return ""

    try:
        from api_usage_logger import log_api_usage
        await log_api_usage(
            endpoint="/chief/backend-fallback", model=model,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            business_id=business_id,
            duration_ms=int(time.time() * 1000) - started_ms)
    except Exception:
        pass

    if text.strip():
        logger.warning(f"[fallback] Chief answered on {model} (primary: {reason[:120]})")
        await _notify_owner(reason)
    return text.strip()
