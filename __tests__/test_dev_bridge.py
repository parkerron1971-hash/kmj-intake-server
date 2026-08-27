# __tests__/test_dev_bridge.py
#
# The Dev Bridge's device lane, two-way: Kevin's Dev Desk replies ride the
# queue poll out to the session working the task, the device acks what it
# typed in, and a session's relayed output never flips a finished task back
# to 'working'. Supabase is faked at the module's own read/write helpers.

import asyncio
from unittest import mock

import pytest

import dev_bridge


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class FakeSupabase:
    """Just enough of dev_tasks for these routes: a list of rows, reads
    filtered by the eq./in. params the module actually sends, patches
    merged by id."""

    def __init__(self, rows):
        self.rows = {r["id"]: dict(r) for r in rows}
        self.patches = []

    async def get(self, _c, path, params):
        assert path == "dev_tasks"
        out = []
        for r in self.rows.values():
            ok = True
            for k, v in params.items():
                if k in ("select", "order", "limit"):
                    continue
                if v.startswith("eq."):
                    ok = ok and str(r.get(k)) == v[3:]
                elif v.startswith("in."):
                    ok = ok and str(r.get(k)) in v[4:-1].split(",")
            if ok:
                out.append(dict(r))
        return out

    async def patch(self, _c, path, params, body):
        assert path == "dev_tasks"
        tid = params["id"][3:]
        self.rows[tid].update(body)
        self.patches.append((tid, body))


async def _device_ok(_c, _authorization):
    return {"id": "dev-1", "name": "Solution Space"}


def _wire(monkeypatch, rows):
    fake = FakeSupabase(rows)
    monkeypatch.setattr(dev_bridge, "_sb_get", fake.get)
    monkeypatch.setattr(dev_bridge, "_sb_patch", fake.patch)
    monkeypatch.setattr(dev_bridge, "_require_device", _device_ok)
    return fake


QUEUED = {"id": "t-queued", "lane": "local", "status": "queued", "title": "New work",
          "details": "Do the thing", "repo": "backend",
          "project_path": r"C:\Users\kmccl\kmj-intake-server",
          "report_key": "k1", "created_at": "2026-08-27T10:00:00+00:00", "notes": []}

WORKING = {"id": "t-working", "lane": "local", "status": "working", "title": "In flight",
           "project_path": r"C:\Users\kmccl\kmj-intake-server", "report_key": "k2",
           "updated_at": "2026-08-27T10:05:00+00:00",
           "notes": [
               {"from": "kevin", "at": "2026-08-27T10:06:00+00:00", "text": "Use the blue one"},
               {"from": "kevin", "at": "2026-08-27T10:01:00+00:00", "text": "old, already typed in",
                "delivered_at": "2026-08-27T10:02:00+00:00"},
               {"from": "dev", "at": "2026-08-27T10:03:00+00:00", "text": "a report, not a reply"},
           ]}

DONE = {"id": "t-done", "lane": "local", "status": "done", "title": "Finished",
        "project_path": r"C:\Users\kmccl\kmj-intake-server", "report_key": "k3",
        "finished_at": "2026-08-27T09:00:00+00:00",
        "notes": [{"from": "kevin", "at": "2026-08-27T09:30:00+00:00", "text": "thanks"}]}


class TestQueuePoll:
    def test_queued_tasks_and_undelivered_replies_ride_the_same_poll(self, monkeypatch):
        _wire(monkeypatch, [QUEUED, WORKING, DONE])
        got = _run(dev_bridge.bridge_queue(authorization="Bearer x"))
        assert [t["id"] for t in got["tasks"]] == ["t-queued"]
        assert got["tasks"][0]["project_name"] == "kmj-intake-server"
        # Only Kevin's notes, only the ones nobody has acked, only on tasks
        # a session might still be sitting in.
        assert len(got["followups"]) == 1
        fu = got["followups"][0]
        assert fu["task_id"] == "t-working"
        assert fu["notes"] == [{"at": "2026-08-27T10:06:00+00:00", "text": "Use the blue one"}]

    def test_the_brief_tells_the_session_how_replies_arrive(self, monkeypatch):
        _wire(monkeypatch, [QUEUED])
        got = _run(dev_bridge.bridge_queue(authorization="Bearer x"))
        prompt = got["tasks"][0]["prompt"]
        assert prompt.startswith("Do the thing")
        assert "/dev-bridge/tasks/t-queued/report" in prompt
        assert "key: k1" in prompt
        assert "Kevin (from the Dev Desk)" in prompt
        assert "'done' or 'failed'" in prompt


class TestAck:
    def test_ack_marks_only_the_named_replies_delivered(self, monkeypatch):
        fake = _wire(monkeypatch, [WORKING])
        got = _run(dev_bridge.bridge_ack_notes(
            "t-working", dev_bridge.AckBody(at=["2026-08-27T10:06:00+00:00"]),
            authorization="Bearer x"))
        assert got == {"ok": True, "acked": 1}
        notes = fake.rows["t-working"]["notes"]
        assert notes[0].get("delivered_at")
        assert notes[2].get("delivered_at") is None  # the dev report is untouched
        # Second poll: nothing pending any more.
        again = _run(dev_bridge.bridge_queue(authorization="Bearer x"))
        assert again["followups"] == []

    def test_ack_of_nothing_new_writes_nothing(self, monkeypatch):
        fake = _wire(monkeypatch, [WORKING])
        got = _run(dev_bridge.bridge_ack_notes(
            "t-working", dev_bridge.AckBody(at=["2026-08-27T10:01:00+00:00"]),
            authorization="Bearer x"))
        assert got["acked"] == 0
        assert fake.patches == []


class TestDeviceStatus:
    def test_relayed_output_does_not_reopen_a_finished_task(self, monkeypatch):
        fake = _wire(monkeypatch, [DONE])
        _run(dev_bridge.bridge_status(
            "t-done", dev_bridge.StatusBody(status="working", note="final answer text",
                                            sender="session"),
            authorization="Bearer x"))
        assert fake.rows["t-done"]["status"] == "done"
        assert fake.rows["t-done"]["notes"][-1]["from"] == "session"
        assert fake.rows["t-done"]["notes"][-1]["text"] == "final answer text"

    def test_working_on_a_live_task_still_moves_the_status(self, monkeypatch):
        fake = _wire(monkeypatch, [dict(WORKING, status="opened")])
        _run(dev_bridge.bridge_status(
            "t-working", dev_bridge.StatusBody(status="working", note="Claude has the brief"),
            authorization="Bearer x"))
        assert fake.rows["t-working"]["status"] == "working"
        assert fake.rows["t-working"]["notes"][-1]["from"] == "device"

    def test_unknown_sender_is_rejected(self, monkeypatch):
        _wire(monkeypatch, [WORKING])
        with pytest.raises(dev_bridge.HTTPException) as e:
            _run(dev_bridge.bridge_status(
                "t-working", dev_bridge.StatusBody(status="working", sender="kevin"),
                authorization="Bearer x"))
        assert e.value.status_code == 422
