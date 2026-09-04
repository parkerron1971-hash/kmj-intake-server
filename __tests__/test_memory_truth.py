"""
The memory claims are true (2026-09-04).

Three gaps the Astra brief named: recall read a table nothing wrote,
the proactive-suggestion docstring promised signals it never named,
and a deploy orphaned running jobs with no recovery until someone
happened to enqueue the same kind. These pin the fixes — and, as
always here, the things that must NOT happen: no confabulated recall,
no automatic retry of a paid build.
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_jobs
import chief_of_staff as cos


# ─── 1. every turn goes on file ──────────────────────────────────────

def test_a_turn_becomes_one_row_in_the_browsers_own_shape():
    taken = [{"type": "create_contact", "label": "Added Ada", "result": "created",
              "nav": {"tab": "operate"}, "frontend_event": {"name": "x"}},
             {"type": "create_task", "label": "Task", "result": "added"},
             "not-a-dict"]
    row = cos._conversation_row("biz-1", "  add Ada Lovelace as a lead ", "Done — Ada is in.", taken)
    assert row["business_id"] == "biz-1"
    assert row["messages"] == [{"role": "user", "content": "add Ada Lovelace as a lead"},
                               {"role": "assistant", "content": "Done — Ada is in."}]
    assert row["message_count"] == 2
    assert row["summary"].startswith("You: add Ada Lovelace as a lead — Chief: Done")
    assert row["key_topics"] == ["create_contact", "create_task"]
    assert row["actions_taken"] == [
        {"type": "create_contact", "label": "Added Ada", "result": "created"},
        {"type": "create_task", "label": "Task", "result": "added"}]
    assert "nav" not in str(row["actions_taken"]), "plumbing is not history"
    assert row["started_at"] and row["ended_at"]


def test_the_row_is_bounded():
    row = cos._conversation_row("b", "x" * 10000, "y" * 10000,
                                [{"type": f"v{i}"} for i in range(30)])
    assert len(row["messages"][0]["content"]) == cos._ARCHIVE_MESSAGE_CHARS
    assert len(row["summary"]) <= cos._ARCHIVE_SUMMARY_CHARS
    assert len(row["key_topics"]) == 10 and len(row["actions_taken"]) == 20


def test_archive_never_raises_and_skips_empty_turns(monkeypatch):
    calls = []

    async def _sb(client, method, path, body=None):
        calls.append((method, path, body))
        raise RuntimeError("db down")
    monkeypatch.setattr(cos, "_sb", _sb)
    asyncio.run(cos._archive_turn(None, {"id": "b"}, "hello", "hi", []))
    assert calls and calls[0][0] == "POST" and calls[0][1] == "/chief_conversations"
    calls.clear()
    asyncio.run(cos._archive_turn(None, {"id": "b"}, "   ", "hi", []))
    asyncio.run(cos._archive_turn(None, {}, "hello", "hi", []))
    assert not calls


def test_chief_chat_archives_every_non_greeting_turn():
    src = inspect.getsource(cos.chief_chat)
    i = src.index("await _archive_turn(client, biz, req.message, response_text, taken)")
    assert "if not is_greeting:" in src[i - 200:i]
    # After the audit hook, before the return — same best-effort block.
    assert src.index("audit hook failed") < i < src.index('"actions_taken": taken,\n            }')


# ─── 2. recall says what is on file, and nothing else ────────────────

def _run(coro):
    return asyncio.run(coro)


def _rows():
    return [
        {"id": "1", "summary": "You: raise Marcus's rate — Chief: Marcus is now $150",
         "key_topics": ["update_offering"], "messages": [
             {"role": "user", "content": "raise Marcus's rate to 150"},
             {"role": "assistant", "content": "Marcus is now $150"}],
         "ended_at": "2026-09-03T10:00:00Z", "message_count": 2},
        {"id": "2", "summary": "You: plan a post — Chief: planned for Friday",
         "key_topics": ["plan_content"], "messages": [
             {"role": "user", "content": "plan a linkedin post about trust"},
             {"role": "assistant", "content": "Planned for Friday."}],
         "ended_at": "2026-09-02T10:00:00Z", "message_count": 2},
    ]


def test_recall_matches_the_messages_not_only_the_summary(monkeypatch):
    async def _sb(client, method, path, body=None):
        assert "select=" in path and "messages" in path
        return _rows()
    monkeypatch.setattr(cos, "_sb", _sb)
    out = _run(cos.handle_recall_conversation(None, {"id": "b"}, {"query": "trust"}))
    assert out["result"] == "1 conversations"
    assert "plan a post" in out["summary"] and "Marcus" not in out["summary"]


def test_recall_with_no_match_says_so_instead_of_returning_everything(monkeypatch):
    """The confabulation source: a query with no hits used to fall back
    to every row, so the model got 'material' about things that were
    never said."""
    async def _sb(client, method, path, body=None):
        return _rows()
    monkeypatch.setattr(cos, "_sb", _sb)
    out = _run(cos.handle_recall_conversation(None, {"id": "b"}, {"query": "Priya"}))
    assert out["result"] == "no_matches"
    assert out["conversations"] == []
    assert "Priya" in out["summary"]


def test_recall_empty_state_no_longer_claims_an_auto_archive(monkeypatch):
    async def _sb(client, method, path, body=None):
        return []
    monkeypatch.setattr(cos, "_sb", _sb)
    out = _run(cos.handle_recall_conversation(None, {"id": "b"}, {"query": "x"}))
    assert out["result"] == "no_conversations"
    assert "auto-archive" not in out["summary"]


def test_conversation_matches_is_case_insensitive_and_reads_topics():
    row = _rows()[0]
    assert cos._conversation_matches(row, "MARCUS")
    assert cos._conversation_matches(row, "update_offering")
    assert not cos._conversation_matches(row, "linkedin")
    assert cos._conversation_matches(row, "")


# ─── 3. the suggestions module says what it is ───────────────────────

def test_the_suggestions_docstring_names_no_unbuilt_signal():
    import chief_proactive_suggestions as cps
    doc = cps.__doc__
    assert "come later" not in doc
    assert "notification_engine" in doc
    assert "onboarding-module\n          recommender" in doc or "onboarding-module recommender" in doc.replace("\n          ", " ")


# ─── 4. orphaned jobs are found, marked, and never retried ───────────

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat()


def test_the_orphan_rule():
    live = {"id": "a", "status": "running", "heartbeat_at": _ago(1), "started_at": _ago(20)}
    dead = {"id": "b", "status": "running", "heartbeat_at": _ago(6), "started_at": _ago(20)}
    slow_here = {"id": "c", "status": "running", "heartbeat_at": _ago(30)}
    old_no_hb = {"id": "d", "status": "running", "heartbeat_at": None, "started_at": _ago(11)}
    young_no_hb = {"id": "e", "status": "running", "heartbeat_at": None, "started_at": _ago(3)}
    queued_old = {"id": "f", "status": "queued", "created_at": _ago(12)}
    done = {"id": "g", "status": "done", "heartbeat_at": _ago(60)}
    junk = {"id": "h", "status": "running", "started_at": "not a date"}
    assert not chief_jobs.is_orphaned(live, NOW, set())
    assert chief_jobs.is_orphaned(dead, NOW, set())
    assert not chief_jobs.is_orphaned(slow_here, NOW, {"c"}), "in-process = slow, not dead"
    assert chief_jobs.is_orphaned(old_no_hb, NOW, set())
    assert not chief_jobs.is_orphaned(young_no_hb, NOW, set())
    assert chief_jobs.is_orphaned(queued_old, NOW, set())
    assert not chief_jobs.is_orphaned(done, NOW, set())
    assert chief_jobs.is_orphaned(junk, NOW, set())


def test_sweep_marks_orphans_failed_retryable_and_nothing_else(monkeypatch):
    import sb_clients
    patched = []
    rows = [
        {"id": "dead", "status": "running", "heartbeat_at": _ago(9), "kind": "rebuild_site",
         "business_id": "b1"},
        {"id": "alive", "status": "running", "heartbeat_at": _ago(0), "kind": "rebuild_site",
         "business_id": "b1"},
    ]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: rows)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: patched.append((p, b)) or [{}])
    monkeypatch.setattr(chief_jobs, "datetime",
                        type("D", (), {"now": staticmethod(lambda tz=None: NOW),
                                       "fromisoformat": datetime.fromisoformat}))
    assert chief_jobs.sweep_orphans("test") == 1
    path, body = patched[0]
    assert "id=eq.dead" in path and "status=in.(queued,running)" in path, (
        "the guard in the PATCH itself: a row that finished in the meantime is left alone")
    assert body["status"] == "failed"
    assert body["error"] == chief_jobs.INTERRUPTED_REASON
    assert body["finished_at"]


def test_sweep_never_enqueues_or_retries():
    src = inspect.getsource(chief_jobs.sweep_orphans) + inspect.getsource(chief_jobs.recover_tick)
    assert "enqueue" not in src and "_run(" not in src and "create_task" not in src


def test_sweep_survives_a_missing_heartbeat_column(monkeypatch):
    import sb_clients
    calls = []

    def _get(path):
        calls.append(path)
        if "heartbeat_at" in path:
            raise RuntimeError("column chief_jobs.heartbeat_at does not exist")
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    assert chief_jobs.sweep_orphans("test") == 0
    assert len(calls) == 2 and "heartbeat_at" not in calls[1]


def test_heartbeat_disables_itself_after_one_refusal(monkeypatch):
    import sb_clients
    calls = []

    def _patch(path, body):
        calls.append((path, body))
        raise RuntimeError("400 column does not exist")
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", _patch)
    monkeypatch.setattr(chief_jobs, "_HEARTBEAT_OK", True)
    chief_jobs._stamp_heartbeat("j1")
    chief_jobs._stamp_heartbeat("j1")
    assert len(calls) == 1, "one warning, not one failed request per progress ping"
    assert chief_jobs._HEARTBEAT_OK is False


def test_progress_ping_stamps_the_heartbeat_separately(monkeypatch):
    import sb_clients
    calls = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: calls.append(b) or [{}])
    monkeypatch.setattr(chief_jobs, "_HEARTBEAT_OK", True)
    cb = chief_jobs._make_progress_cb("j1")
    cb(10, "composing")
    assert [list(b)[0] for b in calls] == ["result", "heartbeat_at"]


def test_startup_sweeps_on_the_leader_and_schedules_the_tick():
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "kmj_intake_automation.py").read_text(encoding="utf-8")
    boot = src[src.index("scheduler_lock.try_acquire()"): src.index("sync_action_types")]
    assert "scheduler_lock.is_leader()" in boot and "sweep_orphans(\"boot\")" in boot
    assert 'g("chief_jobs_recover", _chief_jobs_mod.recover_tick)' in src


def test_migration_is_additive_and_documented():
    root = pathlib.Path(__file__).resolve().parent.parent
    sql = root.joinpath("supabase/APPLY-2026-09-04-chief-jobs-heartbeat.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS heartbeat_at" in sql
    assert "DROP COLUMN" not in sql.split("Rollback")[0]
    ledger = root.joinpath("docs/MIGRATIONS.md").read_text(encoding="utf-8")
    assert "APPLY-2026-09-04-chief-jobs-heartbeat.sql" in ledger
