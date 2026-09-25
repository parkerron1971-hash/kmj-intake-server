"""
voice_metrics.py — time to first audio on a call, and its SLO.

Dev Desk, 2026-09-25 (the voice output brief): "log time-to-first-audio per
turn as the primary metric, separately from time-to-first-token, and treat
one second at the ninety-fifth percentile as the service level objective."

Only the app can see audio. The server knows when it sent the first word
(route_ledger's time to first TOKEN); it cannot know when the speaker made a
sound. So the call (ChiefCallMode) measures each spoken turn itself and
reports it here once the turn has been heard:

  ttfa_ms          the user's turn ended (the speech-to-text relay's
                   speech_stopped) → the first audible sample of anything
                   Chief said: the cached opener, the lead, or the reply.
                   THE number, against VOICE_TTFA_BUDGET_MS (1000).
  reply_audio_ms   the same clock → the first audio of the reply itself,
                   not the filler. Logged beside it so a fast opener cannot
                   hide a slow answer.
  transcript_ms / first_text_ms   where the time went in between.
  vad_silence_ms   the silence the relay waits before calling a turn over.
                   It comes BEFORE speech_stopped, so it is not inside
                   ttfa_ms; the practitioner's felt wait is the sum.

One row per spoken turn in `voice_turn_log` (APPLY-2026-09-25-voice-turn-
log.sql), joinable to model_route_log on request_id. A 15-minute p95 window
(route_ledger.SloWindow, VOICE_SLO_*) pages the owner once per breach,
separately from the first-token page, so neither can mask the other.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import route_ledger
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("voice_metrics")
router = APIRouter()


def budget_ms() -> int:
    try:
        return max(200, int(os.environ.get("VOICE_TTFA_BUDGET_MS") or 1000))
    except (TypeError, ValueError):
        return 1000


WINDOW = route_ledger.SloWindow(metric="ttfa_ms", budget=budget_ms, env="VOICE_SLO")

_FIRST_AUDIO = {"opener", "lead", "reply", "phrase", "none"}
_OUTCOMES = {"spoken", "interrupted", "failed", "silent", "superseded"}
_ENGINES = {"openai", "elevenlabs", "browser", "unknown"}
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class VoiceTurn(BaseModel):
    request_id: Optional[str] = None
    business_id: Optional[str] = None
    ttfa_ms: Optional[int] = None
    reply_audio_ms: Optional[int] = None
    transcript_ms: Optional[int] = None
    first_text_ms: Optional[int] = None
    vad_silence_ms: Optional[int] = None
    first_audio: Optional[str] = None
    outcome: Optional[str] = None
    engine: Optional[str] = None
    barge_in: Optional[bool] = None
    barge_in_ms: Optional[int] = None      # the practitioner started talking → Chief went quiet
    underruns: Optional[int] = None
    tts_requests: Optional[int] = None
    tts_cache_hits: Optional[int] = None


def _ms(v: Any) -> Optional[int]:
    """A duration from the client: an int in [0, 10 min], or nothing."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 600_000 else None


def _count(v: Any) -> Optional[int]:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 10_000 else None


def _pick(v: Optional[str], allowed: set, default: str) -> str:
    v = (v or "").strip().lower()
    return v if v in allowed else default


def row_for(body: VoiceTurn, user_id: str, business_id: Optional[str]) -> Dict[str, Any]:
    ttfa = _ms(body.ttfa_ms)
    budget = budget_ms()
    outcome = _pick(body.outcome, _OUTCOMES, "spoken")
    # A turn that ended without a sound (the stream failed, or it was
    # superseded before speaking) is not a sample of how fast Chief speaks;
    # it is kept on the row but out of the SLO.
    applies = ttfa is not None and outcome not in ("superseded",)
    return {
        "request_id": (body.request_id or "")[:80] or None,
        "business_id": business_id,
        "user_id": user_id if _UUID.match(user_id or "") else None,
        "ttfa_ms": ttfa,
        "reply_audio_ms": _ms(body.reply_audio_ms),
        "transcript_ms": _ms(body.transcript_ms),
        "first_text_ms": _ms(body.first_text_ms),
        "vad_silence_ms": _ms(body.vad_silence_ms),
        "first_audio": _pick(body.first_audio, _FIRST_AUDIO, "none"),
        "outcome": outcome,
        "engine": _pick(body.engine, _ENGINES, "unknown"),
        "barge_in": bool(body.barge_in),
        "barge_in_ms": _ms(body.barge_in_ms),
        "underruns": _count(body.underruns),
        "tts_requests": _count(body.tts_requests),
        "tts_cache_hits": _count(body.tts_cache_hits),
        "budget_ms": budget,
        "slo_applies": applies,
        "slo_met": (ttfa <= budget) if applies else None,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


_skip_db_until = 0.0
_missing_logged = False


def _write(row: Dict[str, Any]) -> None:
    if (os.environ.get("VOICE_LOG_DB") or "on").strip().lower() == "off":
        return
    if time.time() < _skip_db_until:
        return

    def _go() -> None:
        global _skip_db_until, _missing_logged
        try:
            import sb_clients
            ok = bool(sb_clients.sb_post_as_service("/voice_turn_log", row))
        except Exception:
            ok = False
        if not ok:
            _skip_db_until = time.time() + 600
            if not _missing_logged:
                _missing_logged = True
                logger.warning("[voice] voice_turn_log write failed — is "
                               "supabase/APPLY-2026-09-25-voice-turn-log.sql applied? "
                               "The [voice] log lines carry every field meanwhile.")
    try:
        threading.Thread(target=_go, name="voice-log", daemon=True).start()
    except Exception:  # pragma: no cover
        pass


def _page(alert: Dict[str, Any]) -> None:
    note = (f"Calls are slow to make a sound: p95 time to first audio {alert['p95_ms']}ms "
            f"against {alert['budget_ms']}ms (p50 {alert['p50_ms']}ms) over the last "
            f"{alert['samples']} spoken turns in {alert['window_s'] // 60} minutes, measured "
            f"by the app from the end of the practitioner's turn to the first audible sample. "
            f"Read the [voice] log lines: reply_audio vs ttfa says whether the openers are "
            f"missing or the speech provider is slow. Budget: VOICE_TTFA_BUDGET_MS.")
    logger.warning("[voice] SLO BREACH %s", alert)
    route_ledger.page_owner("Chief call first-audio time over budget (p95)", note,
                            push_title="Calls are slow to start speaking",
                            push_body=f"p95 first audio {alert['p95_ms']}ms "
                                      f"(budget {alert['budget_ms']}ms).")


def record(row: Dict[str, Any]) -> None:
    """Log, write, feed the SLO window, page on a breach. Never raises."""
    logger.info(
        "[voice] ttfa=%sms budget=%sms slo=%s first=%s reply_audio=%sms transcript=%sms "
        "first_text=%sms vad=%sms outcome=%s engine=%s barge_in=%s(%sms) underruns=%s "
        "tts=%s/%s cached",
        row["ttfa_ms"], row["budget_ms"],
        "n/a" if row["slo_met"] is None else ("met" if row["slo_met"] else "MISSED"),
        row["first_audio"], row["reply_audio_ms"], row["transcript_ms"], row["first_text_ms"],
        row["vad_silence_ms"], row["outcome"], row["engine"], row["barge_in"],
        row["barge_in_ms"], row["underruns"], row["tts_cache_hits"], row["tts_requests"])
    try:
        alert = WINDOW.add(row)
        if alert:
            _page(alert)
    except Exception as e:  # pragma: no cover
        logger.warning("[voice] slo window failed: %s", e)
    _write(row)


@router.post("/agents/chief/voice/turn")
async def report_voice_turn(body: VoiceTurn, user: AuthedUser = Depends(require_user)):
    """The call's own measurement of one spoken turn. Signed-in only; the
    business is recorded only when it is the caller's (the owner check
    every write here makes)."""
    try:
        import rate_limit
        if not rate_limit.allow("voice", str(user.id)):
            raise HTTPException(status_code=429, detail="Too many voice reports.")
    except HTTPException:
        raise
    except Exception:
        pass
    business_id: Optional[str] = None
    raw_biz = (body.business_id or "").strip()
    if raw_biz:
        if not _UUID.match(raw_biz):
            raise HTTPException(status_code=400, detail="business_id is not an id")
        from whisper_proxy import _owns_business
        owned = await asyncio.to_thread(_owns_business, str(user.id), raw_biz)
        if not owned:
            raise HTTPException(status_code=403, detail="not authorized for this business")
        business_id = raw_biz
    row = row_for(body, str(user.id), business_id)
    record(row)
    return {"ok": True, "slo_met": row["slo_met"], "budget_ms": row["budget_ms"]}


def stats_from_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = [r for r in rows if isinstance(r, dict)]
    budget = budget_ms()
    ttfa = sorted(int(r["ttfa_ms"]) for r in rows
                  if isinstance(r.get("ttfa_ms"), int) and r.get("slo_applies", True))
    reply = sorted(int(r["reply_audio_ms"]) for r in rows if isinstance(r.get("reply_audio_ms"), int))
    firsts: Dict[str, int] = {}
    for r in rows:
        k = str(r.get("first_audio") or "none")
        firsts[k] = firsts.get(k, 0) + 1
    n = len(rows)
    pct = route_ledger.percentile
    return {
        "turns": n, "budget_ms": budget,
        "ttfa_p50_ms": pct(ttfa, 50), "ttfa_p95_ms": pct(ttfa, 95), "ttfa_p99_ms": pct(ttfa, 99),
        "slo_met_pct": (round(100.0 * sum(1 for v in ttfa if v <= budget) / len(ttfa), 1)
                        if ttfa else None),
        "reply_audio_p50_ms": pct(reply, 50), "reply_audio_p95_ms": pct(reply, 95),
        "first_audio": firsts,
        "barge_in_rate": round(sum(1 for r in rows if r.get("barge_in")) / n, 3) if n else None,
        "underruns": sum(int(r.get("underruns") or 0) for r in rows),
        "tts_cache_hit_rate": (
            round(sum(int(r.get("tts_cache_hits") or 0) for r in rows)
                  / max(1, sum(int(r.get("tts_requests") or 0) for r in rows)), 3)
            if any(r.get("tts_requests") for r in rows) else None),
    }


def _require_owner_dep():
    from lead_admin import require_owner
    return require_owner


@router.get("/platform/voice/stats")
async def voice_stats(hours: int = 24, _owner: Any = Depends(_require_owner_dep())):
    """Time to first audio: the live window and the logged history. Owner only."""
    hours = max(1, min(int(hours or 24), 24 * 30))
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))
    rows: List[Dict[str, Any]] = []
    try:
        import sb_clients
        got = await asyncio.to_thread(
            sb_clients.sb_get_as_service,
            f"/voice_turn_log?created_at=gte.{since}&order=created_at.desc&limit=5000"
            "&select=ttfa_ms,reply_audio_ms,first_audio,barge_in,underruns,tts_requests,"
            "tts_cache_hits,slo_applies,outcome")
        rows = got if isinstance(got, list) else []
    except Exception as e:  # pragma: no cover
        logger.warning("[voice] stats read failed: %s", e)
    return {"ok": True, "live_window": WINDOW.snapshot(),
            "logged": {"hours": hours, **stats_from_rows(rows)}}
