"""
test_turn_linkage.py — one id joins a Chief turn to everything it caused.

Layer Two, step 1. What must hold:
  1. THE TURN ID REACHES EVERY WRITER: api_usage rows, the archive row,
     and each ledger row's payload["_ai"] (where the row hash covers it).
  2. BEFORE THE MIGRATION, NOTHING CHANGES: with the probe saying the
     columns are missing, no new key is sent (an unknown column would
     400 the insert and lose the row).
  3. CHIEF'S ORIGINAL SURVIVES THE EDIT, ONCE: the first original is
     kept; a second edit never overwrites it.
  4. WHO REVIEWED IS RECORDED on approve and dismiss.
  5. CHAT DRAFTS GO ON THE OUTCOME LEDGER, stamped with the turn, and
     never steer Chief: digest, retirement and stats read agent moves
     only, exactly as before.
House rules: sync tests + asyncio.run.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import api_usage_logger as ul
import audit_log
import outcome_ledger as ol
import sb_clients
import schema_probe
import turn_context
import turn_linkage


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_probe():
    schema_probe.reset()
    yield
    schema_probe.reset()


def _columns(monkeypatch, present: bool):
    monkeypatch.setattr(schema_probe, "has_columns", lambda table, cols: present)

    async def _async(table, cols):
        return present
    monkeypatch.setattr(schema_probe, "has_columns_async", _async)


# ─── turn_context ────────────────────────────────────────────────────

def test_ai_context_reads_the_turn_and_its_main_call():
    tokens = turn_context.set_turn("req-123")
    try:
        lane_token = turn_context.set_lane("chat")
        turn_context.note_main_call(model="claude-sonnet-5-5", lane="chat", response_id="msg_abc")
        turn_context.reset_lane(lane_token)
        assert turn_context.ai_context() == {
            "turn": "req-123", "model": "claude-sonnet-5-5", "lane": "chat", "resp": "msg_abc"}
        # Explicit arguments win.
        assert turn_context.ai_context(model="claude-opus-5")["model"] == "claude-opus-5"
    finally:
        turn_context.reset(tokens)
    # Outside a turn nothing is invented.
    assert turn_context.ai_context() == {}
    assert turn_context.turn_id() == ""


def test_lane_is_scoped_to_the_call():
    token = turn_context.set_lane("voice")
    assert turn_context.lane() == "voice"
    turn_context.reset_lane(token)
    assert turn_context.lane() == ""


# ─── api_usage ───────────────────────────────────────────────────────

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
    return posted


def test_sync_row_carries_turn_lane_provider_and_response(monkeypatch):
    posted = _capture_sync_post(monkeypatch)
    _columns(monkeypatch, True)
    tokens = turn_context.set_turn("req-9")
    lane_token = turn_context.set_lane("review")
    try:
        ul.log_api_usage_sync(endpoint="llm:chief_truth", model="claude-sonnet-5-5",
                              input_tokens=10, output_tokens=5, response_id="msg_1")
    finally:
        turn_context.reset_lane(lane_token)
        turn_context.reset(tokens)
    body = posted.bodies[-1]
    assert body["turn_id"] == "req-9"
    assert body["lane"] == "review"
    assert body["provider"] == "anthropic"
    assert body["response_id"] == "msg_1"


def test_sync_row_unchanged_before_the_migration(monkeypatch):
    posted = _capture_sync_post(monkeypatch)
    _columns(monkeypatch, False)
    tokens = turn_context.set_turn("req-9")
    try:
        ul.log_api_usage_sync(endpoint="x", model="claude-haiku-5-5", input_tokens=1,
                              output_tokens=1, response_id="msg_2")
    finally:
        turn_context.reset(tokens)
    body = posted.bodies[-1]
    for key in ul._LINK_COLS:
        assert key not in body


def test_async_row_carries_one_hour_writes_and_turn(monkeypatch):
    sent = []

    class _Resp:
        status_code = 201
        text = ""

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.append(json)
            return _Resp()
    monkeypatch.setattr(ul, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(ul, "SUPABASE_SERVICE_ROLE_KEY", "service")
    monkeypatch.setattr(ul.httpx, "AsyncClient", _Client)
    _columns(monkeypatch, True)
    tokens = turn_context.set_turn("req-async")
    try:
        _run(ul.log_api_usage(endpoint="/chief/backend", model="claude-sonnet-5-5",
                              input_tokens=1, output_tokens=1, cache_creation_tokens=100,
                              cache_creation_1h_tokens=80, lane="chat", response_id="msg_3"))
    finally:
        turn_context.reset(tokens)
    body = sent[-1]
    assert body["turn_id"] == "req-async"
    assert body["lane"] == "chat"
    assert body["cache_creation_1h_tokens"] == 80
    assert body["response_id"] == "msg_3"


@pytest.mark.parametrize("model,provider", [
    ("claude-opus-5-5", "anthropic"), ("gpt-4o-mini-tts", "openai"),
    ("text-embedding-3-small", "openai"), ("eleven_flash_v2_5", "elevenlabs"),
    ("kimi-k3", "moonshot"), ("jev", None), ("", None),
])
def test_provider_is_read_from_the_model_name(model, provider):
    assert ul.provider_for(model) == provider


def test_the_probe_never_runs_without_a_database(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    calls = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: calls.append(path) or [])
    assert schema_probe.has_columns("api_usage", ("turn_id",)) is False
    assert calls == []


def test_the_probe_caches_its_answer(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    calls = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: calls.append(path) or [])
    assert schema_probe.has_columns("agent_queue", ("turn_id",)) is True
    assert schema_probe.has_columns("agent_queue", ("turn_id",)) is True
    assert calls == ["/agent_queue?select=turn_id&limit=1"]


# ─── the ledger ──────────────────────────────────────────────────────

def _capture_audit(monkeypatch):
    rows = []

    def fake_post(path, row, prefer=None):
        rows.append(row)
        return [{"id": "a1"}]
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake_post)
    return rows


def test_chief_ledger_rows_carry_the_turn_in_the_hashed_payload(monkeypatch):
    rows = _capture_audit(monkeypatch)
    tokens = turn_context.set_turn("req-ledger")
    turn_context.note_main_call(model="claude-sonnet-5-5", lane="chat", response_id="msg_9")
    try:
        audit_log.record_chief_turn(user_id="u1", business_id="b1", source="desktop",
                                    taken=[{"type": "create_task", "label": "Task", "result": "ok"}],
                                    action_failed=lambda t: False)
    finally:
        turn_context.reset(tokens)
    ai = rows[-1]["payload"]["_ai"]
    assert ai["turn"] == "req-ledger"
    assert ai["lane"] == "chat"
    assert ai["resp"] == "msg_9"
    assert rows[-1]["payload"]["label"] == "Task"


def test_the_ai_record_survives_a_truncated_payload(monkeypatch):
    rows = _capture_audit(monkeypatch)
    audit_log.record("b1", actor_type="chief", verb="x",
                     payload={"label": "y" * (audit_log._RESULT_CAP + 50)},
                     ai={"turn": "req-1", "model": "m", "ignored": "z"})
    payload = rows[-1]["payload"]
    assert "truncated" in payload
    assert payload["_ai"] == {"turn": "req-1", "model": "m"}


def test_no_ai_record_means_no_key(monkeypatch):
    rows = _capture_audit(monkeypatch)
    audit_log.record("b1", actor_type="user", verb="x", payload={"a": 1})
    assert "_ai" not in rows[-1]["payload"]


# ─── drafts: original, reviewer, turn, outcome ───────────────────────

def test_original_is_kept_once(monkeypatch):
    _columns(monkeypatch, True)
    patches = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: patches.append((path, body)) or [])
    assert turn_linkage.keep_original("q1", {"subject": "Hi", "body": "Dear valued client"})
    path, body = patches[-1]
    assert "original_body=is.null" in path   # set once: a second edit matches nothing
    assert body == {"original_subject": "Hi", "original_body": "Dear valued client"}


def test_original_waits_for_the_migration(monkeypatch):
    _columns(monkeypatch, False)
    patches = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: patches.append((path, body)) or [])
    assert turn_linkage.keep_original("q1", {"body": "x"}) is False
    assert patches == []


def test_reviewer_is_recorded(monkeypatch):
    _columns(monkeypatch, True)
    patches = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: patches.append((path, body)) or [])
    assert turn_linkage.mark_reviewed("q1", "user-7")
    assert patches[-1] == ("/agent_queue?id=eq.q1", {"reviewed_by": "user-7"})
    assert turn_linkage.mark_reviewed("q1", None) is False


def test_a_turns_drafts_are_stamped_and_recorded_as_chat_moves(monkeypatch):
    _columns(monkeypatch, True)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    patches, posts = [], []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: patches.append((path, body)) or [])
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, rows, prefer=None: posts.append((path, rows)) or [])
    taken = [
        {"type": "draft_nurture", "queue_id": "q1", "contact_id": "c1", "result": "queued"},
        {"type": "create_task", "task_id": "t1", "result": "ok"},          # not a draft
        {"type": "draft_email", "queue_id": "q2", "result": "failed", "failed": True},
    ]
    failed = lambda t: bool(t.get("failed"))
    assert turn_linkage.after_turn("b1", "req-5", taken, failed) == 1
    path, body = patches[-1]
    assert path.startswith("/agent_queue?id=in.(q1)") and "turn_id=is.null" in path
    assert body == {"turn_id": "req-5"}
    table, rows = posts[-1]
    assert table == ol.TABLE
    assert [(r["verb"], r["surface"], r["queue_id"], r["turn_id"], r["outcome"]) for r in rows] == [
        ("draft_nurture", "chat", "q1", "req-5", ol.PENDING)]


def test_chat_moves_never_steer_chief(monkeypatch):
    seen = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: seen.append(path) or [])
    ol.recent_moves("b1")
    assert "surface=neq.chat" in seen[-1]
    ol.recent_moves("b1", include_chat=True)
    assert "surface=neq" not in seen[-1]


def test_nothing_is_linked_without_a_turn(monkeypatch):
    calls = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda *a: calls.append(a))
    assert turn_linkage.after_turn("b1", "", [{"type": "x", "queue_id": "q"}], lambda t: False) == 0
    assert calls == []


def test_operating_on_an_existing_draft_does_not_claim_it():
    taken = [{"type": "save_draft", "queue_id": "q-old"},
             {"type": "approve_draft", "queue_id": "q-old2"},
             {"type": "draft_email", "queue_id": "q-new"}]
    assert turn_linkage.drafted_queue_ids(taken, lambda t: False) == ["q-new"]


def test_sync_row_stores_one_hour_writes_once_the_column_exists(monkeypatch):
    posted = _capture_sync_post(monkeypatch)
    _columns(monkeypatch, True)
    ul.log_api_usage_sync(endpoint="llm:x", model="claude-sonnet-5-5", input_tokens=1,
                          output_tokens=1, cache_creation_tokens=100, cache_creation_1h_tokens=60)
    assert posted.bodies[-1]["cache_creation_1h_tokens"] == 60
