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


async def _device_ok(_c, _authorization, _agents=None):
    return {"id": "dev-1", "name": "Solution Space"}


def _wire(monkeypatch, rows):
    fake = FakeSupabase(rows)
    monkeypatch.setattr(dev_bridge, "_sb_get", fake.get)
    monkeypatch.setattr(dev_bridge, "_sb_patch", fake.patch)
    monkeypatch.setattr(dev_bridge, "_require_device", _device_ok)
    return fake


QUEUED = {"id": "t-queued", "lane": "local", "status": "queued", "title": "New work", "agent": "claude",
          "details": "Do the thing", "repo": "backend",
          "project_path": r"C:\Users\kmccl\kmj-intake-server",
          "report_key": "k1", "created_at": "2026-08-27T10:00:00+00:00", "notes": []}

WORKING = {"id": "t-working", "lane": "local", "status": "working", "title": "In flight", "agent": "claude",
           "project_path": r"C:\Users\kmccl\kmj-intake-server", "report_key": "k2",
           "updated_at": "2026-08-27T10:05:00+00:00",
           "notes": [
               {"from": "kevin", "at": "2026-08-27T10:06:00+00:00", "text": "Use the blue one"},
               {"from": "kevin", "at": "2026-08-27T10:01:00+00:00", "text": "old, already typed in",
                "delivered_at": "2026-08-27T10:02:00+00:00"},
               {"from": "dev", "at": "2026-08-27T10:03:00+00:00", "text": "a report, not a reply"},
           ]}

DONE = {"id": "t-done", "lane": "local", "status": "done", "title": "Finished", "agent": "claude",
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


# ─── Agents: Claude Code or Codex (2026-09-24) ──────────────────────────

CODEX_QUEUED = dict(QUEUED, id="t-codex", agent="codex", title="Codex work",
                    details="Codex does the thing", report_key="k4",
                    created_at="2026-08-27T09:00:00+00:00")
CODEX_WORKING = dict(WORKING, id="t-codex-live", agent="codex", details="Tidy the rail",
                     repo="frontend", report_key="k5",
                     notes=[{"from": "dev", "at": "2026-08-27T10:03:00+00:00",
                             "text": "Which colour for the rail?"},
                            {"from": "session", "at": "2026-08-27T10:04:00+00:00",
                             "text": "> screen noise"},
                            {"from": "kevin", "at": "2026-08-27T10:06:00+00:00",
                             "text": "Amber"}])


class TestAgents:
    def test_a_build_that_predates_agents_is_never_handed_codex_work(self, monkeypatch):
        _wire(monkeypatch, [QUEUED, CODEX_QUEUED, CODEX_WORKING])
        got = _run(dev_bridge.bridge_queue(authorization="Bearer x"))
        # It would open Codex work as Claude, so it does not see it at all,
        # including replies on a Codex task another device is working.
        assert [t["id"] for t in got["tasks"]] == ["t-queued"]
        assert got["tasks"][0]["agent"] == "claude"
        assert got["followups"] == []

    def test_a_build_that_can_run_codex_gets_it_named(self, monkeypatch):
        _wire(monkeypatch, [QUEUED, CODEX_QUEUED])
        got = _run(dev_bridge.bridge_queue(authorization="Bearer x", agents="claude,codex"))
        by_id = {t["id"]: t for t in got["tasks"]}
        assert set(by_id) == {"t-queued", "t-codex"}
        assert by_id["t-codex"]["agent"] == "codex"
        assert by_id["t-codex"]["prompt"].startswith("Codex does the thing")

    def test_the_device_says_what_it_can_open(self, monkeypatch):
        _wire(monkeypatch, [])
        seen = []

        async def device(_c, _authorization, agents=None):
            seen.append(agents)
            return {"id": "dev-1", "name": "Solution Space"}
        monkeypatch.setattr(dev_bridge, "_require_device", device)
        _run(dev_bridge.bridge_queue(authorization="Bearer x", agents="codex, claude, grok"))
        _run(dev_bridge.bridge_queue(authorization="Bearer x"))
        # Unknown names are dropped; the order is ours, not the caller's.
        assert seen == [["claude", "codex"], ["claude"]]

    def test_a_codex_reply_carries_the_whole_story_for_a_fresh_session(self, monkeypatch):
        _wire(monkeypatch, [CODEX_WORKING])
        got = _run(dev_bridge.bridge_queue(authorization="Bearer x", agents="claude,codex"))
        fu = got["followups"][0]
        assert fu["agent"] == "codex"
        brief = fu["reopen_brief"]
        assert brief.startswith("Tidy the rail")
        assert "key: k5" in brief
        assert "- You (report): Which colour for the rail?" in brief
        assert brief.rstrip().endswith("then continue.")
        assert "- Kevin: Amber" in brief
        assert "screen noise" not in brief


class _Owner:
    id = "owner-1"


class TestDispatchAgents:
    def _insert(self, monkeypatch):
        inserted = []

        async def insert(_c, path, body):
            inserted.append((path, body))
            return dict(body, id="new-task")
        monkeypatch.setattr(dev_bridge, "_sb_insert", insert)
        return inserted

    def test_codex_is_recorded_on_the_task_and_in_its_scope(self, monkeypatch):
        inserted = self._insert(monkeypatch)
        got = _run(dev_bridge.dispatch_task(dev_bridge.DispatchBody(
            lane="local", title="Try Codex", repo="frontend", agent="Codex"), _Owner()))
        assert got["ok"]
        row = inserted[0][1]
        assert row["agent"] == "codex"
        assert row["authority_record"]["scope"]["agent"] == "codex"

    def test_a_claude_task_scope_is_unchanged_by_agents(self, monkeypatch):
        inserted = self._insert(monkeypatch)
        _run(dev_bridge.dispatch_task(dev_bridge.DispatchBody(
            lane="local", title="Plain", repo="backend"), _Owner()))
        row = inserted[0][1]
        assert row["agent"] == "claude"
        assert "agent" not in row["authority_record"]["scope"]

    @pytest.mark.parametrize("lane,agent", [("cloud", "codex"), ("local", "grok")])
    def test_codex_in_the_cloud_and_unknown_agents_are_refused(self, monkeypatch, lane, agent):
        inserted = self._insert(monkeypatch)
        with pytest.raises(dev_bridge.HTTPException) as e:
            _run(dev_bridge.dispatch_task(dev_bridge.DispatchBody(
                lane=lane, title="x", repo="frontend", agent=agent), _Owner()))
        assert e.value.status_code == 422
        assert inserted == []


class TestReplyReopens:
    def test_a_reply_on_a_finished_local_task_picks_it_back_up(self, monkeypatch):
        fake = _wire(monkeypatch, [DONE])
        got = _run(dev_bridge.add_owner_note("t-done", dev_bridge.NoteBody(text="One more thing"),
                                             _Owner()))
        assert got["reopened"] is True
        row = fake.rows["t-done"]
        assert row["status"] == "working" and row["finished_at"] is None
        # ...and the reply now rides the next poll to a session.
        again = _run(dev_bridge.bridge_queue(authorization="Bearer x"))
        assert [n["text"] for n in again["followups"][0]["notes"]] == ["thanks", "One more thing"]

    def test_a_reply_on_a_live_task_does_not_touch_its_status(self, monkeypatch):
        fake = _wire(monkeypatch, [WORKING])
        got = _run(dev_bridge.add_owner_note("t-working", dev_bridge.NoteBody(text="Also this"),
                                             _Owner()))
        assert got["reopened"] is False
        assert fake.rows["t-working"]["status"] == "working"
