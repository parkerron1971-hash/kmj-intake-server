"""Content-free provider timings on the Chief request's monotonic clock.

Dispatch means local HTTP dispatch, not provider receipt. Browser speech clocks
have a different origin; join by request_id but never subtract their offsets.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import time
from contextlib import asynccontextmanager

logger = logging.getLogger("chief.request_timing")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
CURRENT = contextvars.ContextVar("chief_request_timing", default=None)
_ROLES = {"chief_main": "main", "chief_auxiliary": "auxiliary",
          "/chief/opener": "opener", "/chief/route": "classifier",
          "/chief/backend": "fast", "/chief/voice-bridge": "preview",
          "/chief/headline": "preview"}
_MODULE_ROLES = {"chief_truth": "review", "chief_headline": "preview",
                 "chief_voice_bridge": "preview"}


def role_for(task, caller):
    return _ROLES.get(task) or _MODULE_ROLES.get(caller, "auxiliary")


class Trace:
    def __init__(self, arrived, request_id):
        self.arrived = arrived
        self.request_id = request_id
        self.calls = []
        self.main_work_started_ms = None

    def now(self):
        return round(max(0, time.perf_counter() - self.arrived) * 1000)

    def work_started(self):
        if self.main_work_started_ms is None:
            self.main_work_started_ms = self.now()

    def start(self, role, model, transport):
        call = Call(self, role, str(model or "unknown")[:100], transport)
        if len(self.calls) < 32:
            self.calls.append(call)
        call.emit("dispatch")
        return call

    def snapshot(self):
        calls = [dict(c.data) for c in self.calls]
        main = next((c for c in calls if c["role"] == "main"), None)
        opener = next((c for c in calls if c["role"] == "opener"), None)
        fast = next((c for c in calls if c["role"] == "fast"), None)
        lead = opener or fast
        return {"clock_origin": "server_arrival", "main_work_started_ms": self.main_work_started_ms,
                "main_prepare_ms": (main["start_ms"] - self.main_work_started_ms
                    if main and self.main_work_started_ms is not None else None),
                "lead_to_main_request_ms": (main["start_ms"] - lead["start_ms"]
                    if main and lead else None),
                "lead_role": lead["role"] if lead else None, "calls": calls}


class Call:
    def __init__(self, trace, role, model, transport):
        self.trace = trace
        self.data = {"call": len(trace.calls) + 1, "role": role, "model": model,
                     "transport": transport, "start_ms": trace.now(), "headers_ms": None,
                     "first_text_ms": None, "first_text_wait_ms": None,
                     "end_ms": None, "outcome": None, "status": None}
        self.complete = False
        self.provider_error = False

    def emit(self, event):
        try:
            logger.info("[chief request] %s", json.dumps({"request_id": self.trace.request_id,
                        "event": event, **self.data}))
        except Exception:
            pass  # telemetry never changes transport behavior

    def headers(self, status):
        self.data["headers_ms"] = self.trace.now()
        self.data["status"] = status

    def observe(self, event):
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "message_stop":
            self.complete = True
        elif kind == "error":
            self.provider_error = True
        delta = event.get("delta") or {}
        block = event.get("content_block") or {}
        text = (delta.get("text") if isinstance(delta, dict) and delta.get("type") == "text_delta"
                else block.get("text") if isinstance(block, dict) and block.get("type") == "text" else None)
        if isinstance(text, str) and text.strip() and self.data["first_text_ms"] is None:
            self.data["first_text_ms"] = self.trace.now()
            self.data["first_text_wait_ms"] = self.data["first_text_ms"] - self.data["start_ms"]
            self.emit("first_text")

    def finish(self, outcome):
        if self.data["end_ms"] is None:
            self.data["end_ms"] = self.trace.now()
            self.data["outcome"] = outcome
            self.emit("end")


class TimedResponse:
    def __init__(self, response, call):
        self._response, self._call = response, call

    def __getattr__(self, name):
        return getattr(self._response, name)

    async def aiter_lines(self):
        async for line in self._response.aiter_lines():
            if line.startswith("data:"):
                try:
                    self._call.observe(json.loads(line[5:].strip()))
                except (ValueError, TypeError):
                    pass
            yield line


@asynccontextmanager
async def stream(context, trace, role, model):
    call = trace.start(role, model, "sse")
    outcome = "incomplete"
    try:
        async with context as response:
            call.headers(response.status_code)
            yield TimedResponse(response, call)
            outcome = ("http_error" if response.status_code >= 400 else
                       "provider_error" if call.provider_error else
                       "complete" if call.complete else "incomplete")
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except BaseException:
        outcome = "error"
        raise
    finally:
        call.finish(outcome)


async def post_response(operation, trace, role, model):
    """Nonstreaming POST: first-token/header times are deliberately unknown."""
    call = trace.start(role, model, "json")
    outcome = "error"
    try:
        response = await operation
        call.data["status"] = response.status_code
        outcome = "http_error" if response.status_code >= 400 else "complete"
        return response
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    finally:
        call.finish(outcome)
