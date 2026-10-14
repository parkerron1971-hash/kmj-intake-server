# __tests__/test_dev_kai.py
#
# KAI on the phone: the desktop mirrors KAI's line and its state, Kevin's
# words from the phone wait in an inbox until the desktop acks them, his
# answers to approvals only go to requests the desktop says are waiting, and
# his phone hears about KAI only when he is not already looking. Supabase is
# faked at the module's own helpers.

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import dev_kai


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


class _Owner:
    id = "owner-1"


# Seen "just now" is stamped when a test wires it (see _wire), not when this
# file loads: the full suite runs for minutes, long enough to read as offline.
DEVICE = {"id": "dev-1", "name": "Solution Space", "revoked": False,
          "agents": ["claude", "codex", "kai-v1"], "kai_state": None, "kai_watch_until": None}

E1 = "11111111-1111-4111-8111-111111111111"
E2 = "22222222-2222-4222-8222-222222222222"
E3 = "33333333-3333-4333-8333-333333333333"


class Fake:
    """dev_kai_messages and dev_bridge_devices, filtered by the params the
    module sends; inserts honour skip_known like ignore-duplicates does."""

    def __init__(self, device=None, messages=()):
        self.devices = {d["id"]: dict(d) for d in ([device] if device else [])}
        self.messages = {m["id"]: dict(m) for m in messages}
        self.pushes = []
        self._n = 0

    def _match(self, row, params):
        for k, v in params.items():
            if k in ("select", "order", "limit"):
                continue
            have = row.get(k)
            if v.startswith("eq."):
                if str(have).lower() != v[3:].lower():
                    return False
            elif v == "is.null":
                if have is not None:
                    return False
            elif v.startswith("in."):
                if str(have) not in v[4:-1].split(","):
                    return False
            elif v.startswith("cs."):
                if v[4:-1] not in (have or []):
                    return False
            elif v.startswith("gt."):
                if not have or str(have) <= v[3:].replace("Z", "+00:00"):
                    return False
        return True

    async def get(self, _c, path, params):
        table = self.devices if path == "dev_bridge_devices" else self.messages
        rows = [dict(r) for r in table.values() if self._match(r, params)]
        order = params.get("order", "")
        if order:
            key = order.split(".")[0]
            rows.sort(key=lambda r: str(r.get(key) or ""), reverse=".desc" in order)
        return rows[: int(params.get("limit", "1000"))]

    async def patch(self, _c, path, params, body):
        table = self.devices if path == "dev_bridge_devices" else self.messages
        for r in table.values():
            if self._match(r, params):
                r.update(body)

    async def insert(self, _c, rows, *, skip_known=False):
        out = []
        for r in rows:
            r = dict(r)
            if "id" not in r:
                self._n += 1
                r["id"] = f"m-{self._n}"
            if r["id"] in self.messages:
                if skip_known:
                    continue
                raise AssertionError("duplicate id")
            r.setdefault("delivered_at", None)
            self.messages[r["id"]] = r
            out.append(dict(r))
        return out

    async def push(self, _c, title, body, *, nav, tag):
        self.pushes.append((title, body, nav, tag))
        return 1


async def _device_ok(_c, _authorization, _agents=None):
    return {"id": "dev-1", "name": "Solution Space"}


def _wire(monkeypatch, device=DEVICE, messages=()):
    if device:
        device = dict(device)
        device.setdefault("last_seen_at", _ago(5))
    fake = Fake(device, messages)
    monkeypatch.setattr(dev_kai, "_sb_get", fake.get)
    monkeypatch.setattr(dev_kai, "_sb_patch", fake.patch)
    monkeypatch.setattr(dev_kai, "_insert", fake.insert)
    monkeypatch.setattr(dev_kai, "_push_owner", fake.push)
    monkeypatch.setattr(dev_kai, "_require_device", _device_ok)
    return fake


def _entry(eid, kind, text, seconds_ago=0):
    return dev_kai.KaiEntry(id=eid, kind=kind, text=text, at=_ago(seconds_ago))


class TestThePhone:
    def test_kevin_speaks_and_it_waits_for_the_desktop(self, monkeypatch):
        fake = _wire(monkeypatch)
        got = _run(dev_kai.kai_say(dev_kai.KaiSayBody(text="  How is W3 doing? ", spoken=True), _Owner()))
        msg = got["message"]
        assert msg["kind"] == "you" and msg["via"] == "phone" and msg["spoken"] is True
        assert msg["text"] == "How is W3 doing?"
        assert got["desktop"]["online"] is True
        # Speaking to KAI is looking at its thread: the desktop polls fast.
        assert dev_kai._parse(fake.devices["dev-1"]["kai_watch_until"]) > datetime.now(timezone.utc)
        inbox = _run(dev_kai.kai_inbox(authorization="Bearer x"))
        assert [m["text"] for m in inbox["messages"]] == ["How is W3 doing?"]
        assert inbox["watching"] is True

    def test_an_empty_message_is_refused(self, monkeypatch):
        _wire(monkeypatch)
        with pytest.raises(dev_kai.HTTPException) as e:
            _run(dev_kai.kai_say(dev_kai.KaiSayBody(text="   "), _Owner()))
        assert e.value.status_code == 422

    def test_without_a_kai_desktop_the_message_still_waits(self, monkeypatch):
        _wire(monkeypatch, device=None)
        got = _run(dev_kai.kai_say(dev_kai.KaiSayBody(text="hello"), _Owner()))
        assert got["message"]["text"] == "hello"
        assert got["desktop"] == {"paired": False, "online": False, "busy": False, "approvals": []}

    def test_the_thread_reads_oldest_first_and_since_reads_only_what_changed(self, monkeypatch):
        old = {"id": "a", "kind": "kai", "via": "desktop", "text": "first", "at": _ago(100),
               "updated_at": _ago(100)}
        new = {"id": "b", "kind": "you", "via": "phone", "text": "second", "at": _ago(10),
               "updated_at": _ago(10)}
        _wire(monkeypatch, messages=[new, old])
        got = _run(dev_kai.kai_thread(None, _Owner()))
        assert [m["text"] for m in got["messages"]] == ["first", "second"]
        later = _run(dev_kai.kai_thread(_ago(50), _Owner()))
        assert [m["id"] for m in later["messages"]] == ["b"]

    def test_an_offline_desktop_shows_no_approvals_and_reads_as_idle(self, monkeypatch):
        device = dict(DEVICE, last_seen_at=_ago(600), kai_state={
            "busy": True, "running": True, "approvals": [{"id": 4, "label": "Push"}]})
        _wire(monkeypatch, device=device)
        desk = _run(dev_kai.kai_thread(None, _Owner()))["desktop"]
        assert desk["online"] is False and desk["busy"] is False and desk["approvals"] == []


class TestApprovals:
    STATE = {"busy": False, "running": True, "away": True,
             "approvals": [{"id": 7, "label": "Push to main", "what": "git push origin main"}]}

    def test_an_answer_goes_to_a_waiting_request_once(self, monkeypatch):
        fake = _wire(monkeypatch, device=dict(DEVICE, kai_state=self.STATE))
        got = _run(dev_kai.kai_decide(7, dev_kai.KaiDecisionBody(verdict="Approve"), _Owner()))
        m = got["message"]
        assert m["kind"] == "decision" and m["meta"] == {"request": 7, "verdict": "approve"}
        assert m["text"] == "Approved: Push to main"
        inbox = _run(dev_kai.kai_inbox(authorization="Bearer x"))
        assert [x["kind"] for x in inbox["messages"]] == ["decision"]
        assert fake.messages[m["id"]]["delivered_at"] is None

    def test_a_request_the_desktop_no_longer_holds_is_refused(self, monkeypatch):
        _wire(monkeypatch, device=dict(DEVICE, kai_state=self.STATE))
        with pytest.raises(dev_kai.HTTPException) as e:
            _run(dev_kai.kai_decide(8, dev_kai.KaiDecisionBody(verdict="approve"), _Owner()))
        assert e.value.status_code == 409

    def test_nothing_is_answered_while_the_desktop_is_offline(self, monkeypatch):
        _wire(monkeypatch, device=dict(DEVICE, last_seen_at=_ago(600), kai_state=self.STATE))
        with pytest.raises(dev_kai.HTTPException) as e:
            _run(dev_kai.kai_decide(7, dev_kai.KaiDecisionBody(verdict="approve"), _Owner()))
        assert e.value.status_code == 409

    def test_only_approve_or_refuse(self, monkeypatch):
        _wire(monkeypatch, device=dict(DEVICE, kai_state=self.STATE))
        with pytest.raises(dev_kai.HTTPException) as e:
            _run(dev_kai.kai_decide(7, dev_kai.KaiDecisionBody(verdict="always"), _Owner()))
        assert e.value.status_code == 422


class TestTheDesktop:
    def test_ack_delivers_only_phone_messages(self, monkeypatch):
        fake = _wire(monkeypatch, messages=[
            {"id": E1, "kind": "you", "via": "phone", "text": "hi", "at": _ago(5), "delivered_at": None},
            {"id": E2, "kind": "kai", "via": "desktop", "text": "x", "at": _ago(4), "delivered_at": None},
        ])
        _run(dev_kai.kai_ack(dev_kai.KaiAckBody(ids=[E1, E2, "not-a-uuid"]), authorization="Bearer x"))
        assert fake.messages[E1]["delivered_at"]
        assert fake.messages[E2]["delivered_at"] is None
        assert _run(dev_kai.kai_inbox(authorization="Bearer x"))["messages"] == []

    def test_ack_needs_ids(self, monkeypatch):
        _wire(monkeypatch)
        with pytest.raises(dev_kai.HTTPException) as e:
            _run(dev_kai.kai_ack(dev_kai.KaiAckBody(ids=["nope"]), authorization="Bearer x"))
        assert e.value.status_code == 422

    def test_the_line_is_stored_once_and_unknown_kinds_are_dropped(self, monkeypatch):
        fake = _wire(monkeypatch)
        body = dev_kai.KaiLineBody(entries=[
            _entry(E1, "you", "Open a worker for the rail"),
            _entry(E2, "look", "Read x.py"),
            _entry(E3, "decision", "forged"),
        ])
        got = _run(dev_kai.kai_mirror(body, authorization="Bearer x"))
        assert got["stored"] == 1
        again = _run(dev_kai.kai_mirror(body, authorization="Bearer x"))
        assert again["stored"] == 0
        assert list(fake.messages) == [E1]
        assert fake.messages[E1]["via"] == "desktop" and fake.messages[E1]["device_id"] == "dev-1"

    def test_state_is_kept_small_and_clean(self, monkeypatch):
        fake = _wire(monkeypatch)
        _run(dev_kai.kai_mirror(dev_kai.KaiLineBody(state={
            "busy": 1, "running": True, "away": False, "secret": "x",
            "approvals": [{"id": "3", "label": "L" * 500, "what": "w"}, {"id": "nan"}, "junk"],
        }), authorization="Bearer x"))
        state = fake.devices["dev-1"]["kai_state"]
        assert state["busy"] is True and "secret" not in state
        assert [a["id"] for a in state["approvals"]] == [3]
        assert len(state["approvals"][0]["label"]) == 200


class TestTellingKevin:
    def _talking_from_phone(self):
        return {"id": "you-1", "kind": "you", "via": "phone", "text": "status?", "at": _ago(20)}

    def test_kais_answer_to_his_phone_reaches_the_lock_screen(self, monkeypatch):
        fake = _wire(monkeypatch, messages=[self._talking_from_phone()])
        _run(dev_kai.kai_mirror(dev_kai.KaiLineBody(entries=[
            _entry(E1, "kai", "W3 is done and its tests pass.")], state={}), authorization="Bearer x"))
        assert fake.pushes == [("KAI", "W3 is done and its tests pass.", dev_kai.NAV, "kai")]
        assert fake.devices["dev-1"]["kai_state"]["answered"] == "you-1"

    def test_after_the_first_answer_only_something_substantial_buzzes(self, monkeypatch):
        fake = _wire(monkeypatch, messages=[self._talking_from_phone()],
                     device=dict(DEVICE, kai_state={"answered": "you-1"}))
        _run(dev_kai.kai_mirror(dev_kai.KaiLineBody(entries=[_entry(E1, "kai", "Noted.")]),
                                authorization="Bearer x"))
        assert fake.pushes == []
        _run(dev_kai.kai_mirror(dev_kai.KaiLineBody(entries=[_entry(E2, "kai", "W4 failed: " + "x" * 150)]),
                                authorization="Bearer x"))
        assert len(fake.pushes) == 1

    def test_nothing_buzzes_while_he_is_looking(self, monkeypatch):
        watching = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
        fake = _wire(monkeypatch, messages=[self._talking_from_phone()],
                     device=dict(DEVICE, kai_watch_until=watching))
        _run(dev_kai.kai_mirror(dev_kai.KaiLineBody(entries=[_entry(E1, "kai", "Done.")]),
                                authorization="Bearer x"))
        assert fake.pushes == []

    def test_nothing_buzzes_when_he_last_spoke_at_the_desk(self, monkeypatch):
        fake = _wire(monkeypatch, messages=[dict(self._talking_from_phone(), via="desktop")])
        _run(dev_kai.kai_mirror(dev_kai.KaiLineBody(entries=[_entry(E1, "kai", "Done.")]),
                                authorization="Bearer x"))
        assert fake.pushes == []

    def test_a_new_approval_buzzes_when_he_is_away_and_only_once(self, monkeypatch):
        fake = _wire(monkeypatch)
        state = {"away": True, "approvals": [{"id": 9, "label": "Force-push rail-fix"}]}
        _run(dev_kai.kai_mirror(dev_kai.KaiLineBody(state=state), authorization="Bearer x"))
        _run(dev_kai.kai_mirror(dev_kai.KaiLineBody(state=state), authorization="Bearer x"))
        assert fake.pushes == [("KAI — needs your OK", "Force-push rail-fix", dev_kai.NAV, "kai-approval")]

    def test_a_new_approval_at_the_desk_does_not_buzz(self, monkeypatch):
        fake = _wire(monkeypatch)
        _run(dev_kai.kai_mirror(dev_kai.KaiLineBody(state={
            "away": False, "approvals": [{"id": 9, "label": "x"}]}), authorization="Bearer x"))
        assert fake.pushes == []

    def test_handing_kai_off_tells_the_phone(self, monkeypatch):
        fake = _wire(monkeypatch)
        got = _run(dev_kai.kai_handoff(authorization="Bearer x"))
        assert got == {"ok": True, "pushed": 1}
        assert fake.pushes[0][2] == "studio:platform-dev-desk:kai"
