"""
test_charge_per_message.py — a Chief message is charged once.

2026-10-16. The meter priced every api_usage ROW, so one message was
charged 12 credits per model call (13-37 in practice), a call that failed
was charged as if it had answered, and a church's members' safety checks
drew on the pastor's Chief allowance. What must hold now:

  1. ONE PRICE PER MESSAGE: inside a turn, the first chat row carries
     chat_price(); every later chat row in the same turn carries 0, even
     from a copied context (executor writes) or a racing call.
  2. A FAILED CALL IS FREE, in a turn or out of one.
  3. HELPERS RIDE THE MESSAGE: an unpriced call inside a turn (the
     answer check, the quick plan) is 0. A priced action (premium voice,
     a hero, a document) keeps its own price.
  4. OUTSIDE A TURN NOTHING MOVES: rows fall back to the endpoint table,
     whose Chief price is call_price(), the old per-call 12.
  5. EXPLICIT UNITS WIN, always.
  6. MEMBER-SIDE SAFETY CHECKS ARE FREE (msg_screen, member_photos).
House rules: sync tests + asyncio.run.
"""
from __future__ import annotations

import asyncio
import contextvars
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import api_usage_logger as ul
import pricing_config as pc
import schema_probe
import turn_context
import usage_metering as um

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _shipped_prices(monkeypatch):
    for k in ("PRICE_CHAT_PRICE", "CHAT_PRICE", "PRICE_CALL_PRICE", "CALL_PRICE"):
        monkeypatch.delenv(k, raising=False)


class _Turn:
    def __init__(self, tid="req-1"):
        self.tid = tid

    def __enter__(self):
        self.tokens = turn_context.set_turn(self.tid)
        return self

    def __exit__(self, *exc):
        turn_context.reset(self.tokens)


# ─── 1. one price per message ────────────────────────────────────────

def test_the_first_chat_row_carries_the_price_and_the_rest_are_free():
    with _Turn():
        first = ul._priced_units("/chief/backend", True, None)
        second = ul._priced_units("/chief/backend", True, None)
        fallback = ul._priced_units("/chief/backend-fallback", True, None)
        draft = ul._priced_units("/chief/draft", True, None)
    assert first == pc.chat_price() == 20
    assert second == 0 and fallback == 0 and draft == 0


def test_each_message_is_charged_once_not_once_per_session():
    with _Turn("req-a"):
        a = [ul._priced_units("/chief/backend", True, None) for _ in range(3)]
    with _Turn("req-b"):
        b = [ul._priced_units("/chief/backend", True, None) for _ in range(2)]
    assert a == [20, 0, 0] and b == [20, 0]


def test_the_claim_is_shared_with_copied_contexts():
    """llm_call writes rows from an executor with a COPY of the turn's
    context. The copy must see that the message was already charged."""
    with _Turn():
        assert ul._priced_units("/chief/backend", True, None) == 20
        copy = contextvars.copy_context()
        assert copy.run(ul._priced_units, "/chief/backend", True, None) == 0


def test_a_copy_that_claims_first_is_seen_by_the_turn():
    with _Turn():
        copy = contextvars.copy_context()
        assert copy.run(ul._priced_units, "/chief/backend", True, None) == 20
        assert ul._priced_units("/chief/backend", True, None) == 0


def test_claim_charge_outside_a_turn_is_always_true():
    assert turn_context.claim_charge() is True
    assert turn_context.claim_charge() is True


# ─── 2. a failed call is free ────────────────────────────────────────

def test_a_failed_chat_call_is_free_in_a_turn_and_does_not_use_up_the_charge():
    with _Turn():
        failed = ul._priced_units("/chief/backend", False, None)
        retry = ul._priced_units("/chief/backend", True, None)
    assert failed == 0
    assert retry == 20, "the retry that answered is the one that is charged"


def test_a_failed_chat_call_is_free_outside_a_turn():
    assert ul._priced_units("/chief/backend", False, None) == 0
    assert ul._priced_units("/chief/draft", False, None) == 0


# ─── 3. helpers ride the message; priced actions keep their price ────

def test_an_unpriced_helper_in_a_turn_is_free():
    with _Turn():
        assert ul._priced_units("llm:chief_truth", True, None) == 0
        assert ul._priced_units("llm:chief_quick_plan", True, None) == 0


def test_a_priced_action_in_a_turn_keeps_its_own_price():
    with _Turn():
        assert ul._priced_units("/ai/tts-el", True, None) is None
        assert ul._priced_units("/composer/hero", True, None) is None
    assert um.weight_for("/ai/tts-el") == pc.premium_voice_price()


# ─── 4. outside a turn nothing moves ─────────────────────────────────

def test_outside_a_turn_rows_fall_back_to_the_table():
    assert ul._priced_units("/chief/backend", True, None) is None
    assert ul._priced_units("llm:growth_engine", True, None) is None
    assert um.weight_for("/chief/backend") == pc.call_price() == 12
    assert um.weight_for("llm:growth_engine") == pc.DEFAULT_WEIGHT


# ─── 5. explicit units win ───────────────────────────────────────────

def test_explicit_units_are_never_repriced():
    with _Turn():
        assert ul._priced_units("/chief/backend", True, 7) == 7
        assert ul._priced_units("/chief/backend", False, 7) == 7
        assert ul._priced_units("llm:chief_truth", True, 0) == 0
    assert ul._priced_units("/composer/compose", True, 900) == 900


# ─── the rows actually written ───────────────────────────────────────

class _Posted:
    def __init__(self):
        self.bodies = []


def _capture_sync_post(monkeypatch):
    posted = _Posted()

    def fake_post(url, headers=None, json=None, timeout=None):
        posted.bodies.append(json)
    monkeypatch.setattr(ul, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(ul, "SUPABASE_SERVICE_ROLE_KEY", "service")
    monkeypatch.setattr(ul.httpx, "post", fake_post)
    monkeypatch.setattr(schema_probe, "has_columns", lambda table, cols: True)
    return posted


def test_a_message_with_two_calls_and_a_check_is_charged_twenty(monkeypatch):
    """The shape measured in production: a tool round, a final call and
    the answer check. Was 12 + 12 + 1 = 25; now 20."""
    posted = _capture_sync_post(monkeypatch)
    with _Turn("req-row"):
        for ep in ("/chief/backend", "/chief/backend", "llm:chief_truth"):
            ul.log_api_usage_sync(endpoint=ep, model="claude-sonnet-5-5",
                                  input_tokens=1, output_tokens=1, business_id="b1")
    units = [b["units"] for b in posted.bodies]
    assert units == [20, 0, 0]
    assert sum(um.weight_for_row(b) for b in posted.bodies) == 20


def test_the_async_writer_prices_the_same_way(monkeypatch):
    sent = []

    class _Resp:
        status_code = 201
        text = ""

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            sent.append(json)
            return _Resp()

    async def _cols(table, cols):
        return True
    monkeypatch.setattr(ul, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(ul, "SUPABASE_SERVICE_ROLE_KEY", "service")
    monkeypatch.setattr(ul.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(schema_probe, "has_columns_async", _cols)

    async def _turn():
        with _Turn("req-async"):
            await ul.log_api_usage(endpoint="/chief/backend", model="m", input_tokens=0,
                                   output_tokens=0, ok=False, error="http")
            await ul.log_api_usage(endpoint="/chief/backend", model="m",
                                   input_tokens=1, output_tokens=1)
            await ul.log_api_usage(endpoint="/chief/backend", model="m",
                                   input_tokens=1, output_tokens=1)
    asyncio.run(_turn())
    assert [b["units"] for b in sent] == [0, 20, 0]


def test_a_row_outside_a_turn_is_written_as_before(monkeypatch):
    posted = _capture_sync_post(monkeypatch)
    ul.log_api_usage_sync(endpoint="/chief/backend", model="m",
                          input_tokens=1, output_tokens=1, business_id="b1")
    assert "units" not in posted.bodies[-1]


# ─── 6. member-side safety checks are free ───────────────────────────

@pytest.mark.parametrize("module,task", [("msg_screen.py", "msg_screen"),
                                         ("member_photos.py", "member_photo_screen")])
def test_member_safety_checks_never_draw_on_the_church_allowance(module, task):
    src = (ROOT / module).read_text(encoding="utf-8")
    call = src[src.index(f'task="{task}"'):]
    call = call[:call.index("\n        if resp.status_code")]   # the end of the apost(...) call
    assert "units=0" in call, f"{module}: the {task} call must pass units=0"
