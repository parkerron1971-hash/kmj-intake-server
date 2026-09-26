"""
chief_fast_track.py — the first track of Chief's two-track reply.

Kevin, 2026-09-25 (Dev Desk): the first token within about 500ms on every
request, no exceptions; a Haiku call fires at once and streams a
conversational opening or a direct answer while Sonnet runs behind it when
the router escalated; Sonnet's output continues the stream with no gap; a
thin Haiku answer, or a practitioner saying it missed, silently hands the
turn to Sonnet. The baseline was 8-10 seconds to the first word.

HOW A STREAMED TURN RUNS NOW (POST /agents/chief/chat/stream)

  arrival ─┬─ model_router.score() + decide()           (~1 ms, no I/O)
           │
           ├─ lane "cache": a repeat of a record-free answer, sent at once.
           │
           ├─ lane "fast":  Haiku writes the whole answer (AnswerGate). The
           │                full turn never runs — unless the answer opens
           │                by deflecting, claims something it cannot, or
           │                comes back thin; then the full turn runs and its
           │                answer continues after whatever was shown.
           │
           └─ lane "full":  Haiku writes the opening (OpenerGate) while the
                            full turn (chief_chat, Sonnet, unchanged) reads
                            the business. The turn is told what the opening
                            said, in the uncached prompt tail, and its
                            checked answer continues the same stream.
                            Ambiguous requests ask the Haiku classifier
                            first (bounded), then go fast or full.

  In every lane a deadline (ROUTER_TTFT_BUDGET_MS, less a small margin,
  from the moment the request reached the app) guards the first word: if no
  model has produced a safe one by then, a local lead ("Sure —") goes out
  and the model's words follow it. That is what makes "no exceptions" true
  rather than usually true: Haiku's first token is 383ms median, 433ms p95
  on a warm connection, but 420-710ms on a cold one, and the tail is the
  network's, not ours. The connection is kept warm between turns for the
  same reason.

WHAT THE FIRST TRACK MAY SAY
  The answer check (chief_truth) exists because a spoken false success
  cannot be taken back, and it holds model prose until it is proved. The
  first track does not get around that: an opening states no facts (only
  what Chief is about to do), and a fast-lane answer is only ever given to
  a request that needs no records — it has none to misstate. See the gates
  in model_router.

WHAT THIS DOES NOT CHANGE
  The plain /agents/chief/chat endpoint; everything inside the full turn
  (tools, actions, the answer check, sentence streaming); the voice call's
  own spoken opener (when the client already said one, no second opening is
  written). Kill switches: CHIEF_ROUTER=off (all of it), CHIEF_ROUTER_FAST_LANE,
  CHIEF_ROUTER_OPENER, CHIEF_ROUTER_CACHE (each =off).
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import re
import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends

import chief_models
import llm_call
import model_router as mr
import route_ledger

logger = logging.getLogger("chief_fast_track")

router = APIRouter()


# ─── Switches ────────────────────────────────────────────────────────

def _on(name: str) -> bool:
    return (os.environ.get(name) or "on").strip().lower() not in ("off", "0", "false", "no")


def enabled() -> bool:
    """The router runs only with a key to call Haiku with; without one every
    turn is exactly the pre-router turn."""
    return _on("CHIEF_ROUTER") and bool(llm_call.api_key())


def ledger_only() -> bool:
    """Router off but a key present: still measure first-token time, so the
    before/after is one query over the same table."""
    return (not _on("CHIEF_ROUTER")) and bool(llm_call.api_key()) and _on("ROUTER_LOG_WHEN_OFF")


def _deadline_margin_s() -> float:
    try:
        return max(0.0, int(os.environ.get("ROUTER_DEADLINE_MARGIN_MS") or 40) / 1000.0)
    except (TypeError, ValueError):
        return 0.04


def _classifier_timeout_s() -> float:
    try:
        return max(0.2, int(os.environ.get("ROUTER_CLASSIFIER_TIMEOUT_MS") or 900) / 1000.0)
    except (TypeError, ValueError):
        return 0.9


# How long the first track may keep the stream to itself before the full
# turn's own words take over, whatever the model is doing.
OPENER_HARD_CAP_S = 2.5
FAST_ANSWER_CAP_S = 20.0
FAST_MAX_TOKENS = 500
OPENER_MAX_TOKENS = 40


# ─── When the request arrived ────────────────────────────────────────

# Set by sse_middleware at the outermost ASGI layer, before auth, so the
# first-token clock includes everything the practitioner waits through.
ARRIVED: "contextvars.ContextVar[Optional[float]]" = contextvars.ContextVar(
    "stream_arrived", default=None)


def arrived_at() -> float:
    t = ARRIVED.get()
    return t if isinstance(t, float) else time.perf_counter()


# ─── A warm connection ───────────────────────────────────────────────

_client: Optional[httpx.AsyncClient] = None
_client_loop: Any = None
_last_use = 0.0
_warm_task: Optional["asyncio.Task"] = None


def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0),
        limits=httpx.Limits(max_keepalive_connections=16, max_connections=32,
                            keepalive_expiry=180.0))


def client() -> httpx.AsyncClient:
    """One keep-alive client for the first track, per event loop. A fresh
    TLS handshake to the API was measured at +50-300ms on Haiku's first
    token — most of the budget's slack. Built at import (below): building
    one loads the certificate store synchronously, and on the first live
    probe that blocked the loop past the deadline (first word at 549ms)."""
    global _client, _client_loop, _last_use
    loop = asyncio.get_running_loop()
    if _client is not None and _client_loop is None and not _client.is_closed:
        _client_loop = loop                  # the import-time client, first use
    if _client is None or _client_loop is not loop or _client.is_closed:
        _client = _new_client()
        _client_loop = loop
    _last_use = time.monotonic()
    _ensure_warm(loop)
    return _client


def _ensure_warm(loop: Any) -> None:
    """While Chief has been used in the last ten minutes, touch the API every
    45s so the next turn finds an open connection. Free (the models list),
    and it stops on its own when nobody is talking to Chief."""
    global _warm_task
    if not _on("ROUTER_KEEP_WARM"):
        return
    if _warm_task is not None and not _warm_task.done():
        return

    async def _loop() -> None:
        while time.monotonic() - _last_use < 600:
            await asyncio.sleep(45)
            c = _client
            if c is None or c.is_closed or _client_loop is not asyncio.get_running_loop():
                return
            try:
                await c.get(llm_call.base_url() + "/v1/models?limit=1",
                            headers=llm_call.headers(), timeout=5.0)
            except Exception:
                pass

    try:
        _warm_task = loop.create_task(_loop())
    except Exception:  # pragma: no cover
        _warm_task = None


try:
    _client = _new_client()
except Exception:  # pragma: no cover — built lazily instead
    _client = None


# ─── In-process memory ───────────────────────────────────────────────

CACHE = mr.SemanticCache()
# (user, business) → when a full turn last came back whole. The fast lane
# skips chief_chat, so it leans on a recent full turn for what chief_chat
# establishes: that the business is this user's (the RLS read) and that
# they are inside their allowance.
_KNOWN_GOOD: Dict[str, float] = {}
KNOWN_GOOD_TTL_S = 1800
# conversation → what the last turn was, for "that's not what I asked".
_CONVO: Dict[str, Dict[str, Any]] = {}
STICKY_TURNS = 4


def _pair(user_id: str, business_id: str) -> str:
    return f"{user_id}:{business_id}"


def _convo_key(user_id: str, req: Any) -> str:
    return f"{user_id}:{getattr(req, 'conversation_id', None) or getattr(req, 'business_id', '')}"


def note_full_turn_ok(user_id: str, business_id: str) -> None:
    if user_id and business_id:
        _KNOWN_GOOD[_pair(user_id, business_id)] = time.time()
        if len(_KNOWN_GOOD) > 5000:
            cut = time.time() - KNOWN_GOOD_TTL_S
            for k in [k for k, t in _KNOWN_GOOD.items() if t < cut]:
                _KNOWN_GOOD.pop(k, None)


def known_good(user_id: str, business_id: str) -> bool:
    t = _KNOWN_GOOD.get(_pair(user_id, business_id))
    return bool(t) and time.time() - t < KNOWN_GOOD_TTL_S


def _remember_turn(key: str, lane: str, *, opener: str = "", dissatisfied: bool = False) -> None:
    st = _CONVO.setdefault(key, {"turns": 0, "sticky_until": 0})
    st["turns"] += 1
    st["lane"] = lane
    st["at"] = time.time()
    if opener:
        st["last_opener"] = opener
    if dissatisfied:
        st["sticky_until"] = st["turns"] + STICKY_TURNS
    if len(_CONVO) > 5000:
        for k in sorted(_CONVO, key=lambda k: _CONVO[k].get("at", 0))[:1000]:
            _CONVO.pop(k, None)


# ─── The opening, handed to the full turn ────────────────────────────

class OpenerHolder:
    """What the first track has said, for the full turn to continue from.

    The turn freezes it when it builds its prompt: from then on the first
    track releases nothing more, so the words the turn is told about are
    exactly the words the practitioner saw."""

    def __init__(self) -> None:
        self.text = ""
        self.frozen = False
        self.dangling = False
        self.done = asyncio.Event()
        self.closing = ""            # a dash the first track still owes
        self.deadline: Optional[float] = None   # when the local lead goes out

    def said(self, piece: str) -> None:
        if piece and not self.frozen:
            self.text += piece

    def finish(self, *, dangling: bool = False) -> None:
        if not self.frozen:
            self.dangling = dangling
        self.done.set()

    def freeze(self) -> str:
        if not self.frozen:
            self.frozen = True
            if not self.done.is_set():
                # Cut off mid-stream by the turn: if the words so far do not
                # end a sentence, the first track closes them with a dash.
                t = self.text.rstrip()
                self.dangling = bool(t) and not re.search(r"[.!?…—–]$", t)
                if self.dangling:
                    self.closing = " —"
            self.done.set()
        return self.text + self.closing


OPENER: "contextvars.ContextVar[Optional[OpenerHolder]]" = contextvars.ContextVar(
    "chief_opener", default=None)


async def opener_for_turn(wait_s: float = 0.35) -> str:
    """Called by chief_chat just before its model call: the opening already
    shown, or "" when there is none. Waits briefly for an opening still
    being written, then freezes it."""
    holder = OPENER.get()
    if holder is None:
        return ""
    if not holder.done.is_set():
        # Never freeze before the first-word deadline: a turn that reached
        # its prompt that early would otherwise silence the lead that holds
        # the budget. Real turns get here after their context reads (~1s).
        until_deadline = (holder.deadline - time.perf_counter()) if holder.deadline else 0.0
        try:
            await asyncio.wait_for(holder.done.wait(), timeout=max(wait_s, until_deadline + wait_s))
        except asyncio.TimeoutError:
            pass
    return holder.freeze().strip()


def continuation_block(opener: str) -> str:
    """The uncached prompt tail that makes the turn continue the opening
    instead of starting over. Empty when nothing was said."""
    said = (opener or "").strip()
    if not said:
        return ""
    return (
        "\n\nWHAT YOU HAVE ALREADY SAID THIS TURN — the practitioner has already "
        f"seen (and, on a call, heard) your reply begin with: «{said}»\n"
        "Your reply continues straight on from those words. Do not repeat or "
        "rephrase them, do not acknowledge the request again, and do not greet "
        "again: begin with the substance, as the next sentence. Those words "
        "claimed nothing — every fact is still yours to establish from the "
        "records, and the usual rules for what you may say apply."
    )


def join_reply(opener: str, reply: str) -> str:
    """The reply on file: the opening, then the turn's answer."""
    o = (opener or "").rstrip()
    r = (reply or "").lstrip()
    if not o:
        return reply or ""
    if not r:
        return o
    return o + " " + r


# ─── Prompts ─────────────────────────────────────────────────────────

_OPENER_SYSTEM = """You are Chief, the chief of staff inside a small-business owner's app. Another part of you is reading their records and will write the real reply. Your words are the first thing they see and hear, and that reply continues straight on from them.

Write only the opening: 3 to 10 words saying what you are about to do with their request. Start with "Let me", "I'll", "Checking", "Looking at", "Pulling up", "Give me a second" or "On it" (you may put "Sure," or "Got it," first). End with a period.

It has to stay true whatever the records turn out to say, so it contains:
- no answer, no yes or no, and no facts about their business, clients, money, dates or records;
- no numbers, and no names they did not say themselves;
- nothing about anything being done, sent, found, booked or paid.

Match the request: a question → you are checking; a task → you are on it; a piece of writing → you will draft it; a decision → you will think it through. Vary your wording."""

_FAST_SYSTEM = """You are Chief, the chief of staff inside a small-business owner's app, replying in a conversation. This message needs none of their records and no action: it is a pleasantry, or a general question you can answer from general knowledge.

Reply naturally and briefly: a sentence or two for a pleasantry; a short, direct answer for a question (under 120 words), no headings.
- You cannot see their business in this reply. If a good answer needs their records, calendar, clients, messages or anything about their business, or asks you to do something, reply with exactly NEED_RECORDS and nothing else.
- Never say you did, sent, saved, booked or changed anything, and do not offer to."""

_CLASSIFIER_SYSTEM = """Classify one message sent to Chief, an AI chief of staff inside a small-business app that can read the owner's records (clients, invoices, bookings, email, money, website) and take actions for them.

Return only JSON: {"needs_records": true|false, "needs_action": true|false, "complexity": "low"|"medium"|"high", "confidence": 0.0-1.0}
- needs_records: a good answer depends on their business data or on earlier conversation.
- needs_action: they want something done, created, sent, changed or scheduled, including a "yes" / "go ahead" to something Chief proposed.
- complexity: high = multi-step reasoning, strategy, code, or a long written piece; medium = a normal question; low = a pleasantry or a quick general-knowledge answer.
- confidence: how sure you are of the whole classification."""

_VOICE_NOTE = "\nThis reply is spoken aloud: plain sentences, no lists, no markdown, no emoji."


def _history_tail(req: Any, n: int = 4) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for m in (getattr(req, "conversation_history", None) or [])[-n:]:
        role = "assistant" if getattr(m, "role", "") == "assistant" else "user"
        text = str(getattr(m, "content", "") or "").strip()
        if not text or text.startswith("[SYSTEM:"):
            continue
        out.append({"role": role, "content": text[:700]})
    # The Messages API wants user first and alternating roles.
    while out and out[0]["role"] != "user":
        out.pop(0)
    merged: List[Dict[str, str]] = []
    for m in out:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += "\n\n" + m["content"]
        else:
            merged.append(dict(m))
    return merged


def _prior_assistant(req: Any) -> str:
    for m in reversed(getattr(req, "conversation_history", None) or []):
        if getattr(m, "role", "") == "assistant":
            return str(getattr(m, "content", "") or "")
    return ""


# ─── Model calls ─────────────────────────────────────────────────────

def _log_usage(endpoint: str, model: str, usage: Dict[str, Any], *, business_id: Optional[str],
               units: Optional[int], started: float, ok: bool = True) -> None:
    """api_usage row for a first-track call (off the event loop)."""
    def _go() -> None:
        try:
            from api_usage_logger import log_api_usage_sync
            log_api_usage_sync(
                endpoint=endpoint, model=model,
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
                cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
                business_id=business_id, units=units,
                duration_ms=int((time.perf_counter() - started) * 1000))
        except Exception as e:  # pragma: no cover
            logger.warning("[fast_track] usage log failed: %s", e)
    try:
        asyncio.get_running_loop().run_in_executor(None, _go)
    except RuntimeError:  # pragma: no cover
        _go()


async def stream_text(system: str, messages: List[Dict[str, Any]], *, model: str,
                      max_tokens: int, rec: route_ledger.RouteRecord, endpoint: str,
                      units: Optional[int], business_id: Optional[str],
                      out: Dict[str, Any]) -> AsyncIterator[str]:
    """Stream a small Haiku call's text. Usage and stop_reason land in `out`,
    the request's tally and api_usage. Raises nothing: an error ends the
    stream with out["error"] set."""
    payload = {"model": model, "max_tokens": max_tokens, "stream": True,
               "system": system, "messages": messages}
    started = time.perf_counter()
    usage: Dict[str, Any] = {}
    try:
        async with llm_call.astream(client(), payload, timeout=httpx.Timeout(
                connect=3.0, read=15.0, write=5.0, pool=2.0)) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread())[:200]
                out["error"] = f"{resp.status_code} {body!r}"
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except ValueError:
                    continue
                et = evt.get("type")
                if et == "content_block_delta":
                    d = evt.get("delta") or {}
                    if d.get("type") == "text_delta" and d.get("text"):
                        yield d["text"]
                elif et == "message_start":
                    usage.update(((evt.get("message") or {}).get("usage")) or {})
                elif et == "message_delta":
                    if (evt.get("delta") or {}).get("stop_reason"):
                        out["stop_reason"] = evt["delta"]["stop_reason"]
                    u = evt.get("usage") or {}
                    if u.get("output_tokens") is not None:
                        usage["output_tokens"] = u["output_tokens"]
    except (httpx.HTTPError, asyncio.TimeoutError) as e:
        out["error"] = f"{type(e).__name__}: {e}"
    finally:
        out["usage"] = usage
        if usage:
            rec.tally.add(model, int(usage.get("input_tokens") or 0),
                          int(usage.get("output_tokens") or 0),
                          int(usage.get("cache_read_input_tokens") or 0),
                          int(usage.get("cache_creation_input_tokens") or 0))
            _log_usage(endpoint, model, usage, business_id=business_id, units=units,
                       started=started, ok=not out.get("error"))


async def classify(message: str, prior_assistant: str, *, rec: route_ledger.RouteRecord,
                   business_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The Haiku tie-breaker. None on any failure (the policy then goes up)."""
    model = chief_models.model_for("route")
    content = (f"Chief's previous message: {prior_assistant[-300:]}\n\n" if prior_assistant else "") \
        + f"The message: {message[:800]}"
    out: Dict[str, Any] = {}
    parts: List[str] = []
    async for piece in stream_text(_CLASSIFIER_SYSTEM, [{"role": "user", "content": content}],
                                   model=model, max_tokens=80, rec=rec,
                                   endpoint="/chief/route", units=0,
                                   business_id=business_id, out=out):
        parts.append(piece)
    raw = "".join(parts)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


# ─── The plan for one request ────────────────────────────────────────

Event = Dict[str, Any]


class TwoTrack:
    """The first track of one streamed request. Built by plan(); the stream
    endpoint iterates lead() before (and while) the full turn's events."""

    def __init__(self, req: Any, user_id: str, rec: route_ledger.RouteRecord,
                 complexity: mr.Complexity, route: mr.Route, *, passive: bool = False) -> None:
        self.req = req
        self.user_id = user_id
        self.rec = rec
        self.c = complexity
        self.route = route
        self.passive = passive              # router off: measure only
        self.holder = OpenerHolder()
        self.holder.deadline = (rec.arrived + route_ledger.budget_ms() / 1000.0
                                - _deadline_margin_s())
        self.voice = (getattr(req, "client_surface", "") or "") == "voice"
        self.message = str(getattr(req, "message", "") or "")
        self.business_id = str(getattr(req, "business_id", "") or "")
        self.verified = known_good(user_id, self.business_id)
        self.cache_scope = _pair(user_id, self.business_id)
        self.cache_hit: Optional[mr.CacheHit] = None
        self.fast_answer = ""
        self.lead_text = ""                 # everything the first track sent
        self.turn_started = False
        self._key = _convo_key(user_id, req)
        self._decided: Optional[str] = None
        self.finished = False
        client_opener = (getattr(req, "spoken_opener", None) or "").strip()
        self.client_opener = bool(client_opener)
        # The app talking to itself (greeting pulls, coach sentinels) is not
        # a practitioner waiting on a reply: no opening, and no SLO verdict.
        self.system_turn = str(getattr(req, "message", "") or "").lstrip().startswith("[SYSTEM:")
        if self.system_turn:
            rec.slo_applies = False
        # "Let me check…" in front of "thanks" or "bye" reads as a machine that
        # did not listen; those get the one-word lead at the deadline instead.
        self.model_opener = complexity.kind not in ("social", "farewell") and not self.system_turn

    # -- what the endpoint asks ------------------------------------------------

    @property
    def lane(self) -> str:
        return self.rec.lane

    def starts_turn_now(self) -> bool:
        return self.passive or (self.rec.lane == mr.LANE_FULL and not self.route.ambiguous)

    def bind_turn_context(self) -> List[Any]:
        """Context the full turn task must be created with (reset after)."""
        return [(OPENER, OPENER.set(self.holder)),
                (route_ledger.TALLY, route_ledger.TALLY.set(self.rec.tally))]

    def mark_turn_delta(self) -> None:
        """A delta from the full turn went out."""
        self.rec.mark_first_token("turn" if not self.lead_text else None)

    def answered(self) -> bool:
        """The first track gave the whole reply (fast lane or cache)."""
        return (self.rec.lane in (mr.LANE_FAST, mr.LANE_CACHE) and not self.rec.escalated
                and bool(self.lead_text.strip()))

    def finish(self, payload: Optional[Dict[str, Any]] = None, *, error: Optional[str] = None) -> None:
        if self.finished:
            return
        self.finished = True
        if error:
            self.rec.error = error
        ok = isinstance(payload, dict) and not error
        if ok and self.turn_started:
            note_full_turn_ok(self.user_id, self.business_id)
        if not self.passive:
            _remember_turn(self._key, self.rec.lane, opener=self.holder.text.strip(),
                           dissatisfied=self.rec.reason == "dissatisfied")
        if self.rec.answer_model is None and self.turn_started:
            self.rec.answer_model = chief_models.model_for(
                chief_models.lane_for_chat(getattr(self.req, "mode", "") or "",
                                           getattr(self.req, "client_surface", "") or ""))
        route_ledger.finish(self.rec)

    def final_payload(self) -> Dict[str, Any]:
        """The fast lane's (or the cache's) answer, in /chat's shape."""
        text = self.lead_text
        return {"response": text, "actions_taken": [],
                "grounding": {"status": "unchecked", "reason": "no records needed",
                              "sources": []},
                "routing": {"lane": self.rec.lane, "model": self.rec.answer_model}}

    # -- the lead phase --------------------------------------------------------

    async def lead(self, start_turn: Callable[[], Any]) -> AsyncIterator[Event]:
        """Yield the first track's wire events. Calls start_turn() when the
        full turn has to run and has not been started yet."""
        if self.passive:
            return
        deadline = self.rec.arrived + route_ledger.budget_ms() / 1000.0 - _deadline_margin_s()
        self.holder.deadline = deadline
        if self.rec.lane == mr.LANE_CACHE and self.cache_hit is not None:
            async for ev in self._emit(self.cache_hit.answer, "cache"):
                yield ev
            return
        if self.rec.lane == mr.LANE_FAST:
            async for ev in self._fast(deadline, start_turn):
                yield ev
            return
        async for ev in self._full(deadline, start_turn):
            yield ev

    async def _emit(self, text: str, source: str) -> AsyncIterator[Event]:
        if not text:
            return
        if self.holder.frozen and source not in ("cache", "answer"):
            return
        self.rec.mark_first_token(source)
        self.lead_text += text
        self.holder.said(text)
        yield {"type": "delta", "text": text, "checked": True, "lead": source}

    def _lead(self, kind: Optional[str] = None) -> str:
        """This turn's local lead: an interjection on screen, a whole short
        sentence on a call (or none, for thanks and goodbyes)."""
        return mr.local_lead(kind or self.c.kind, voice=self.voice)

    def _lead_is_sentence(self) -> bool:
        return bool(re.search(r"[.!?]\s*$", self.lead_text))

    def _lead_allowed(self) -> bool:
        return (_on("CHIEF_ROUTER_LOCAL_LEAD") and not self.lead_text
                and not self.client_opener and not self.system_turn and bool(self._lead()))

    def _joined(self, text: str) -> str:
        """Model text that follows what the first track already said."""
        if self.lead_text and not self.lead_text[-1:].isspace() and not text.startswith(" "):
            return " " + text
        return text

    def _lead_needed(self, deadline: float) -> bool:
        return self._lead_allowed() and time.perf_counter() >= deadline

    async def _lead_while(self, task: Optional["asyncio.Future"], deadline: float
                          ) -> AsyncIterator[Event]:
        """Wait for `task` (or, with None, just for the deadline), sending the
        local lead if the deadline comes first and nothing has been said."""
        while True:
            if task is not None and task.done():
                return
            now = time.perf_counter()
            if not self._lead_allowed():
                if task is not None:
                    await task
                return
            if now >= deadline:
                async for ev in self._emit(self._lead(), "local"):
                    yield ev
                if task is not None:
                    await task
                return
            if task is None:
                await asyncio.sleep(deadline - now)
            else:
                await asyncio.wait({task}, timeout=deadline - now)

    async def _pump(self, gen: AsyncIterator[str], q: "asyncio.Queue[Optional[str]]") -> None:
        try:
            async for piece in gen:
                await q.put(piece)
        finally:
            await q.put(None)

    async def _next(self, q: "asyncio.Queue[Optional[str]]", deadline: float,
                    hard_stop: float) -> Any:
        """The next model piece, or 'LEAD' when the deadline needs a local
        lead first, or 'STOP' when the first track is out of time."""
        now = time.perf_counter()
        if now >= hard_stop:
            return "STOP"
        wait = hard_stop - now
        if self._lead_allowed():
            if now >= deadline:
                return "LEAD"
            wait = min(wait, deadline - now)
        try:
            return await asyncio.wait_for(q.get(), timeout=max(0.0, wait))
        except asyncio.TimeoutError:
            return "LEAD" if self._lead_needed(deadline) else ("STOP" if time.perf_counter() >= hard_stop else "AGAIN")

    async def _full(self, deadline: float, start_turn: Callable[[], Any]) -> AsyncIterator[Event]:
        # An ambiguous request may yet be answered by Haiku alone, and an
        # opening in front of that answer was measured coming back twice
        # ("I'll look into that. I'll look into that. …"); while the
        # classifier decides, the local lead holds the budget instead.
        want_opener = (_on("CHIEF_ROUTER_OPENER") and not self.client_opener
                       and self.model_opener and not self.route.ambiguous)
        if self.client_opener:
            self.rec.mark_first_token("client")
        verdict_task = None
        if self.route.ambiguous:
            t0 = time.perf_counter()
            verdict_task = asyncio.ensure_future(classify(
                self.message, _prior_assistant(self.req), rec=self.rec,
                business_id=self.business_id if self.verified else None))
            verdict_task.add_done_callback(
                lambda _t: setattr(self.rec, "classifier_ms", int((time.perf_counter() - t0) * 1000)))
        if not want_opener:
            decided = mr.LANE_FULL
            if verdict_task is not None:
                deciding = asyncio.ensure_future(self._decide_ambiguous(verdict_task, start_turn))
                async for ev in self._lead_while(deciding, deadline):
                    yield ev
                decided = deciding.result()
            if decided == mr.LANE_FAST:
                async for ev in self._fast(deadline, start_turn, continuing=bool(self.lead_text)):
                    yield ev
                return
            if not self.turn_started:
                start_turn()
                self.turn_started = True
            # No model opening: the one-word lead still holds the budget.
            async for ev in self._lead_while(None, deadline):
                yield ev
            self.holder.finish()
            return

        gate = mr.OpenerGate(self.message)
        q: "asyncio.Queue[Optional[str]]" = asyncio.Queue()
        out: Dict[str, Any] = {}
        system = _OPENER_SYSTEM
        last = (_CONVO.get(self._key) or {}).get("last_opener")
        if last:
            system += f"\nYour last opening in this conversation was «{last}» — do not reuse it."
        content = self.message[:1200] + (" (said aloud on a call)" if self.voice else "")
        pump = asyncio.ensure_future(self._pump(stream_text(
            system, [{"role": "user", "content": content}],
            model=chief_models.model_for("fast"), max_tokens=OPENER_MAX_TOKENS, rec=self.rec,
            endpoint="/chief/opener", units=0,
            business_id=self.business_id if self.verified else None, out=out), q))
        hard_stop = self.rec.arrived + OPENER_HARD_CAP_S
        try:
            while not gate.closed and not self.holder.frozen:
                piece = await self._next(q, deadline, hard_stop)
                if piece == "AGAIN":
                    continue
                if piece == "STOP":
                    gate.close("timeout")
                    break
                if piece == "LEAD":
                    lead = self._lead()
                    gate.after_lead = True
                    gate.lower_after_lead = not re.search(r"[.!?]\s*$", lead)
                    async for ev in self._emit(lead, "local"):
                        yield ev
                    continue
                if piece is None:
                    tail = gate.finish()
                    async for ev in self._emit(self._joined(tail) if tail else "", "model"):
                        yield ev
                    break
                text = gate.feed(piece)
                if text:
                    async for ev in self._emit(self._joined(text), "model"):
                        yield ev
            if gate.cut_reason and gate.cut_reason not in ("sentence_end", "model_end"):
                self.rec.opener_cut = gate.cut_reason
            if out.get("error"):
                self.rec.opener_cut = (self.rec.opener_cut or "") + f" error:{out['error'][:60]}"
            # Close an opening that stopped mid-sentence with a dash, so what
            # follows reads as the next thought rather than a collision. A
            # frozen holder already told the turn about that dash.
            closing = self.holder.closing if self.holder.frozen else (
                " —" if gate.text and gate.dangling else "")
            if closing and not self.lead_text.rstrip().endswith(("—", "–")):
                self.lead_text += closing
                if not self.holder.frozen:
                    self.holder.said(closing)
                yield {"type": "delta", "text": closing, "checked": True, "lead": "model"}
        finally:
            if not pump.done():
                pump.cancel()
            self.holder.finish()
        if not self.turn_started:
            start_turn()
            self.turn_started = True

    async def _decide_ambiguous(self, task: "asyncio.Future", start_turn: Callable[[], Any]) -> str:
        """Fold the classifier's verdict in and act on it once."""
        if getattr(self, "_decided", None):
            return self._decided
        try:
            verdict = await asyncio.wait_for(asyncio.shield(task), timeout=_classifier_timeout_s())
        except (asyncio.TimeoutError, Exception):
            verdict = None
        c2 = mr.from_classifier(self.c, verdict)
        allow_fast = _on("CHIEF_ROUTER_FAST_LANE") and self.verified
        r2 = mr.decide(c2, allow_fast=allow_fast)
        self.c = c2
        self.rec.complexity = c2.as_log()
        self.rec.lane = r2.lane
        self.rec.reason = f"ambiguous→{r2.reason}"
        self._decided = r2.lane
        if r2.lane == mr.LANE_FULL and not self.turn_started:
            start_turn()
            self.turn_started = True
        return r2.lane

    async def _fast(self, deadline: float, start_turn: Callable[[], Any], *,
                    continuing: bool = False) -> AsyncIterator[Event]:
        """Haiku answers alone. Escalates silently when it should not."""
        self.rec.lane = mr.LANE_FAST
        model = chief_models.model_for("fast")
        self.rec.answer_model = model
        gate = mr.AnswerGate()
        q: "asyncio.Queue[Optional[str]]" = asyncio.Queue()
        out: Dict[str, Any] = {}
        system = _FAST_SYSTEM + (_VOICE_NOTE if self.voice else "")
        if continuing and self.lead_text.strip():
            system += (f"\nYour reply has already begun with «{self.lead_text.strip()}»; continue "
                       "straight on from it without repeating it.")
        messages = _history_tail(self.req) + [{"role": "user", "content": self.message[:4000]}]
        if messages[0]["role"] != "user":  # pragma: no cover — _history_tail guarantees it
            messages = messages[1:]
        guard = asyncio.ensure_future(asyncio.to_thread(_fast_guards, self.user_id, self.business_id))
        pump = asyncio.ensure_future(self._pump(stream_text(
            system, messages, model=model, max_tokens=FAST_MAX_TOKENS, rec=self.rec,
            endpoint="/chief/backend", units=None, business_id=self.business_id, out=out), q))
        hard_stop = self.rec.arrived + FAST_ANSWER_CAP_S
        after_lead = bool(self.lead_text)
        first_model_text = True
        escalate: Optional[str] = None
        try:
            while not gate.closed:
                piece = await self._next(q, deadline, hard_stop)
                if piece == "AGAIN":
                    continue
                if piece == "STOP":
                    escalate = "timeout"
                    break
                if piece == "LEAD":
                    after_lead = True
                    async for ev in self._emit(self._lead(), "local"):
                        yield ev
                    continue
                text = gate.finish() if piece is None else gate.feed(piece)
                if text:
                    if not guard.done():
                        try:
                            await asyncio.wait_for(asyncio.shield(guard), timeout=0.25)
                        except asyncio.TimeoutError:
                            pass
                    if (guard.done() and not guard.cancelled() and guard.exception() is None
                            and guard.result() is False):
                        escalate = "guard"
                        break
                    if first_model_text and after_lead:
                        text = " " + mr.strip_interjection(
                            text.lstrip(), lower=not self._lead_is_sentence())
                    first_model_text = False
                    self.fast_answer += text
                    async for ev in self._emit(text, "answer"):
                        yield ev
                if piece is None:
                    break
            escalate = escalate or gate.escalate or (
                ("error:" + str(out.get("error"))[:40]) if out.get("error") else None) or \
                mr.looks_thin(self.fast_answer, self.c, stop_reason=str(out.get("stop_reason") or ""))
        finally:
            if not pump.done():
                pump.cancel()

        if escalate:
            self.rec.escalate(escalate)
            self.rec.lane = mr.LANE_FULL
            self.rec.answer_model = None
            if not self.lead_text and not self.client_opener:
                # Nothing shown yet: the budget still holds with a lead.
                async for ev in self._emit(self._lead("general" if self.c.kind == "general"
                                                      else "other"), "local"):
                    yield ev
            if self.lead_text and not re.search(r"[.!?…—–]\s*$", self.lead_text.rstrip()):
                self.lead_text += " —"
                yield {"type": "delta", "text": " —", "checked": True, "lead": "answer"}
            self.holder.text = self.lead_text
            self.holder.finish()
            start_turn()
            self.turn_started = True
            return
        self.holder.finish()
        answer = self.fast_answer.strip()
        if self.c.cacheable and _on("CHIEF_ROUTER_CACHE") and answer and not continuing:
            # Stored as a reply of its own: text that followed a local lead
            # was lower-cased to join it ("Sure — gross margin is…").
            answer = answer[0].upper() + answer[1:]
            CACHE.put(self.cache_scope, self.message, answer, model=model,
                      cost_cents=self.rec.tally.cost_cents())


def _fast_guards(user_id: str, business_id: str) -> bool:
    """What chief_chat checks before it spends, for a turn that skips it:
    the per-user rate limit and the daily spend ceilings. Fail-open, like
    the originals."""
    try:
        import rate_limit
        if not rate_limit.allow("chief", str(user_id)):
            return False
    except Exception:
        pass
    try:
        import spend_guard
        if spend_guard.over_budget(business_id):
            return False
    except Exception:
        pass
    return True


def plan(req: Any, user_session: Any) -> Optional[TwoTrack]:
    """Route one stream request. None = the router is out of the picture
    (no user session, no key, or switched off without measuring)."""
    user = getattr(user_session, "user", None)
    user_id = str(getattr(user, "id", "") or "")
    if not user_id:
        return None
    on = enabled()
    if not on and not ledger_only():
        return None
    rec = route_ledger.RouteRecord(
        arrived=arrived_at(), business_id=getattr(req, "business_id", None), user_id=user_id,
        conversation_id=getattr(req, "conversation_id", None),
        surface=getattr(req, "client_surface", None))
    if getattr(req, "request_id", None):
        # The app's id for this turn: what a client-side measurement (time
        # to first audio on a call) is reported against.
        rec.request_id = str(req.request_id)[:80]
    message = str(getattr(req, "message", "") or "")
    c = mr.score(message, _prior_assistant(req),
                 has_images=bool(getattr(req, "image_ids", None)),
                 mode=getattr(req, "mode", None))
    rec.complexity = c.as_log()
    if not on:
        rec.lane, rec.reason = "off", "router_off"
        return TwoTrack(req, user_id, rec, c, mr.Route("off", "router_off"), passive=True)

    key = _convo_key(user_id, req)
    st = _CONVO.get(key) or {}
    unhappy = mr.dissatisfied(message)
    sticky = int(st.get("sticky_until") or 0) > int(st.get("turns") or 0)
    business_id = str(getattr(req, "business_id", "") or "")
    allow_fast = (_on("CHIEF_ROUTER_FAST_LANE") and known_good(user_id, business_id))
    route = mr.decide(c, allow_fast=allow_fast, dissatisfied_now=unhappy, sticky_up=sticky)
    if unhappy and st.get("lane") == mr.LANE_FAST:
        rec.escalate("dissatisfied_after_fast")
    rec.lane, rec.reason = route.lane, route.reason
    track = TwoTrack(req, user_id, rec, c, route)
    if route.lane == mr.LANE_FAST and c.cacheable and _on("CHIEF_ROUTER_CACHE"):
        hit = CACHE.get(track.cache_scope, message)
        if hit is not None:
            track.cache_hit = hit
            rec.lane, rec.reason = mr.LANE_CACHE, "cache"
            rec.cache_hit, rec.cache_similarity = True, round(hit.similarity, 3)
            rec.answer_model = hit.model
    return track


# ─── The owner's view ────────────────────────────────────────────────

def _require_owner_dep():
    from lead_admin import require_owner
    return require_owner


@router.get("/platform/routing/stats")
async def routing_stats(hours: int = 24, _owner: Any = Depends(_require_owner_dep())):
    """First-token SLO and routing mix: the live window from this process,
    and the logged history for threshold tuning. Owner only."""
    hours = max(1, min(int(hours or 24), 24 * 30))
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))
    rows: List[Dict[str, Any]] = []
    try:
        import sb_clients
        got = await asyncio.to_thread(
            sb_clients.sb_get_as_service,
            f"/model_route_log?created_at=gte.{since}&order=created_at.desc&limit=5000"
            "&select=lane,complexity,escalated,escalation_reason,opener_source,ttft_ms,"
            "total_ms,cost_cents,answer_model,slo_met,kind")
        rows = got if isinstance(got, list) else []
    except Exception as e:  # pragma: no cover
        logger.warning("[route] stats read failed: %s", e)
    return {
        "ok": True,
        "router": {"enabled": enabled(), "fast_lane": _on("CHIEF_ROUTER_FAST_LANE"),
                   "opener": _on("CHIEF_ROUTER_OPENER"), "cache": _on("CHIEF_ROUTER_CACHE"),
                   "thresholds": {"fast_max_score": mr.fast_max_score(),
                                  "full_min_score": mr.full_min_score(),
                                  "min_confidence": mr.min_confidence()},
                   "cache_entries": len(CACHE)},
        "live_window": route_ledger.WINDOW.snapshot(),
        "logged": {"hours": hours, **route_ledger.stats_from_rows(rows)},
    }
