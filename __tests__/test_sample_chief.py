"""Chief in the sample church (sample_chief.py, BE-4, 2026-11-15).

Kevin approved the sample-church signup on 2026-11-14 ("top tier, no cut
corners"). Chief answers ten questions about Grace Street Fellowship, a
made-up church, in its own lane. What is pinned here:

  · both chat handlers hand a sample over FIRST: every side-effecting step
    of the real turn is booby-trapped and none of them runs;
  · the app's own [SYSTEM:...] turns and the coaching modes are answered
    with a line, no model call, nothing counted;
  · the cap: ten, then capped with no model call; per PERSON across a new
    sample; a racing storm of questions makes exactly ten rows;
  · the model call only runs inside allow_sample_chief (llm_call refuses it
    otherwise), on the chat model, structured, the digest cached, the
    visitor's name after the breakpoint;
  · nothing is written but the question's own row; api_usage gets one row
    as sample_chief, units 0;
  · GET /sample-church/questions is the sample owner's only;
  · no digest (or a sample closing) counts nothing;
  · the voice: the eval's fixed replies all pass and its negative controls
    are all caught.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import pathlib
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_here.parent / "scripts"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402

import sample_chief as sch  # noqa: E402
import sample_church as sc  # noqa: E402
from auth_supabase import AuthedUser, UserSession, require_user  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

HOME, SAMPLE, SAMPLE2, REAL = "home-1", "sample-1", "sample-2", "real-1"
OWNER, STRANGER = "owner-1", "owner-2"
Q = "sample_church_questions"

import sample_chief_eval  # noqa: E402

DIGEST = sample_chief_eval.FIXTURE_DIGEST


def _sample(sid=SAMPLE, owner=OWNER, home=HOME, status="ready", digest=DIGEST, **over):
    marker = {"version": 1, "status": status}
    if digest is not None:
        marker["digest"] = digest
    row = {"id": sid, "owner_id": owner, "name": sc.NAME, "type": "church", "is_sample": True,
           "sample_of": home, "is_active": False,
           "settings": {sc.SETTINGS_KEY: marker, "practitioner_name": "Pastor Ana Ruiz"}}
    row.update(over)
    return row


class _DB(FakeSB):
    """FakeSB with the table's UNIQUE(user_id, n), thread-safe, and a log
    of every write by table."""

    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()
        self.writes = []
        self.jitter = 0.0

    def _pause(self):
        if self.jitter:
            time.sleep(random.random() * self.jitter)

    def get(self, path):
        self._pause()
        with self.lock:
            return super().get(path)

    def post(self, path, body, prefer="return=representation"):
        self._pause()
        with self.lock:
            table = path.split("?", 1)[0].lstrip("/")
            self.writes.append(("POST", table))
            if table == Q and any(r["user_id"] == body["user_id"] and r["n"] == body["n"]
                                  for r in self.rows(Q)):
                return None          # 23505: the unique index refused it
            return super().post(path, body, prefer)

    def patch(self, path, body):
        with self.lock:
            self.writes.append(("PATCH", path.split("?", 1)[0].lstrip("/")))
            return super().patch(path, body)

    def delete(self, path):
        with self.lock:
            self.writes.append(("DELETE", path.split("?", 1)[0].lstrip("/")))
            return super().delete(path)


@pytest.fixture
def db(monkeypatch):
    fb = _DB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="return=representation", **kw: fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    monkeypatch.setattr(sc, "_columns_ready", lambda: True)
    monkeypatch.delenv("SAMPLE_CHIEF_QUESTIONS", raising=False)
    monkeypatch.delenv("SAMPLE_CHIEF_EFFORT", raising=False)
    sc._reset_for_tests()
    fb.rows("businesses").extend([
        _sample(),
        {"id": HOME, "owner_id": OWNER, "type": "church", "is_sample": False, "sample_of": None},
        {"id": REAL, "owner_id": OWNER, "type": "church", "is_sample": False, "sample_of": None},
    ])
    import rate_limit
    import spend_guard
    monkeypatch.setattr(rate_limit, "allow", lambda bucket, key: True)
    monkeypatch.setattr(spend_guard, "over_budget", lambda business_id=None: False)
    import chief_stream_replay
    chief_stream_replay._receipts.clear()
    chief_stream_replay._inflight.clear()
    return fb


def _reply(answer="Four regulars have missed the last three Sundays.", drafts=None):
    return {"answer": answer, "drafts": drafts or []}


class _Wire:
    """The model, faked below llm_call (so its sample refusal is real)."""

    def __init__(self):
        self.calls = []          # (payload, allowed at call time)
        self.replies = []
        self.status = 200
        self.stop = "end_turn"
        self.usage = {"input_tokens": 300, "output_tokens": 200,
                      "cache_read_input_tokens": 1600, "cache_creation_input_tokens": 0}

    def client(self):
        wire = self

        class _C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, headers=None, timeout=None, json=None, **kw):
                wire.calls.append((json, sc.sample_chief_allowed()))
                body = wire.replies.pop(0) if wire.replies else _reply()
                return httpx.Response(wire.status, json={
                    "id": f"msg_{len(wire.calls)}", "model": "claude-sonnet-5-5",
                    "stop_reason": wire.stop,
                    "content": [{"type": "text", "text": globals()["json"].dumps(body)}],
                    "usage": dict(wire.usage)}, request=httpx.Request("POST", url))
        return _C()


@pytest.fixture
def wire(monkeypatch):
    w = _Wire()
    monkeypatch.setattr(sch, "_client", w.client)
    return w


@pytest.fixture
def usage(monkeypatch):
    rows = []

    async def _log(**kw):
        rows.append(kw)
    import api_usage_logger
    monkeypatch.setattr(api_usage_logger, "log_api_usage", _log)
    return rows


def _session(uid=OWNER):
    return UserSession(user=AuthedUser(id=uid, email=None, role="authenticated"), token="jwt")


def _req(message="Who's been drifting?", sid=SAMPLE, **kw):
    import chief_of_staff as cos
    return cos.ChatRequest(business_id=sid, message=message,
                           request_id=kw.pop("request_id", f"r-{random.random()}"), **kw)


def _ask(message="Who's been drifting?", sid=SAMPLE, uid=OWNER, **kw):
    import chief_of_staff as cos
    return asyncio.run(cos.chief_chat(_req(message, sid, **kw), user_session=_session(uid)))


def _questions(db, uid=OWNER):
    return [r for r in db.rows(Q) if r["user_id"] == uid]


# ─── The divert comes first, in both handlers ─────────────────────────

def _booby_trap(monkeypatch):
    """Every step of the real turn that reads, writes, sweeps, spends or
    learns: called at all, it raises AND is recorded (the stream swallows
    a failing chief_fast_track.plan, so the record is what the test reads)."""
    hits = []
    import billing_limits
    import chief_areas
    import chief_fast_track
    import chief_of_staff as cos
    import chief_tool_loop
    import chief_truth
    import sb_clients
    import turn_context

    def boom(name):
        def _f(*a, **k):
            hits.append(name)
            raise AssertionError(f"{name} ran for a sample church")
        return _f

    for mod, name in [
        (sb_clients, "set_user_jwt"), (chief_truth, "begin"), (chief_truth, "record"),
        (chief_truth, "finalize_reply"), (chief_areas, "turn_for"), (turn_context, "set_turn"),
        (billing_limits, "require_units"), (billing_limits, "require_chat_fair_use"),
        (chief_fast_track, "plan"), (chief_tool_loop, "run_tool_round"),
        (cos, "_sb"), (cos, "_generate_missing_recurring_instances"), (cos, "_spawn_turn_sweeps"),
        (cos, "_execute_actions"), (cos, "_archive_turn"), (cos, "_log_chief_activity"),
        (cos, "_mark_referenced_memories"), (cos, "_gather_context"), (cos, "_fetch_view_detail"),
        (cos, "_learn_patterns_async"), (cos, "_record_mentor_shown_async"),
    ]:
        monkeypatch.setattr(mod, name, boom(f"{mod.__name__}.{name}"))
    return hits


def test_chief_chat_hands_a_sample_over_before_anything_runs(db, wire, usage, monkeypatch):
    hits = _booby_trap(monkeypatch)
    out = _ask()
    assert hits == []
    assert out["sample"]["counted"] is True and out["sample"]["questions_left"] == 9
    assert out["response"] == "Four regulars have missed the last three Sundays."
    assert out["actions_taken"] == [] and len(wire.calls) == 1


def test_the_stream_hands_a_sample_over_before_anything_runs(db, wire, usage, monkeypatch):
    hits = _booby_trap(monkeypatch)
    import chief_of_staff as cos
    monkeypatch.setattr(cos, "chief_chat", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("the real turn ran for a sample")))
    wire.replies = [_reply("Here are the notes. " + sch.SAMPLE_LINE,
                           [{"kind": "text", "to_label": "Denise Carter", "body": "Hi Denise, we miss you."}])]

    async def _run():
        resp = await cos.chief_chat_stream(_req("Yes, write them."), user_session=_session())
        return [chunk async for chunk in resp.body_iterator]
    chunks = asyncio.run(_run())
    assert hits == []
    events = [json.loads(c[len("data: "):]) for c in chunks if c.startswith("data: ")]
    kinds = [e["type"] for e in events]
    assert kinds == ["status", "delta", "delta", "final"]
    assert events[0]["text"] == "reading Grace Street"
    final = events[-1]["payload"]
    assert "".join(e["text"] for e in events if e["type"] == "delta") == final["response"]
    assert events[1]["text"] == final["sample"]["answer"]
    assert final["sample"]["drafts"][0]["to_label"] == "Denise Carter"
    assert final["sample"]["questions_left"] == 9 and final["sample"]["capped"] is False
    assert chunks[0].startswith(":") and len(chunks[0]) > 16000      # the buffer-breaking preamble


def test_without_the_divert_the_traps_do_fire(db, wire, monkeypatch):
    """Guards the guard: the traps above sit on the real path's first steps."""
    hits = _booby_trap(monkeypatch)
    import chief_of_staff as cos

    async def _never(req):
        return False
    monkeypatch.setattr(cos, "_is_sample_turn", _never)
    with pytest.raises(AssertionError):
        _ask()
    assert hits[:1] == ["sb_clients.set_user_jwt"] and wire.calls == []


def test_a_real_church_is_not_diverted(db):
    import chief_of_staff as cos
    assert asyncio.run(cos._is_sample_turn(_req(sid=REAL))) is False
    assert asyncio.run(cos._is_sample_turn(_req(sid=SAMPLE))) is True


def test_a_sample_someone_else_owns_is_not_found(db, wire, usage):
    with pytest.raises(HTTPException) as e:
        _ask(uid=STRANGER)
    assert e.value.status_code == 404 and wire.calls == [] and _questions(db, STRANGER) == []


def test_the_stream_refuses_a_stranger_as_a_real_http_error(db, wire):
    import chief_of_staff as cos

    async def _run():
        return await cos.chief_chat_stream(_req(), user_session=_session(STRANGER))
    with pytest.raises(HTTPException) as e:
        asyncio.run(_run())
    assert e.value.status_code == 404 and wire.calls == []


def test_the_rate_limit_applies(db, wire, monkeypatch):
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow", lambda bucket, key: False)
    with pytest.raises(HTTPException) as e:
        _ask()
    assert e.value.status_code == 429 and wire.calls == [] and db.rows(Q) == []


# ─── Not a question: no model call, nothing counted ───────────────────

@pytest.mark.parametrize("message,mode,reason", [
    ("[SYSTEM:opening_greeting:morning]", None, "system"),
    ("[SYSTEM:room_first_visit]", None, "system"),
    ("Help me plan my offerings", "business_coach", "coaching"),
    ("Let's plan the year", "strategy_coach", "coaching"),
])
def test_system_turns_and_coaching_are_not_counted(db, wire, usage, message, mode, reason):
    out = _ask(message, mode=mode)
    assert out["sample"]["reason"] == reason and out["sample"]["counted"] is False
    assert wire.calls == [] and db.rows(Q) == [] and usage == []
    assert out["sample"]["questions_left"] == 10


def test_the_opening_greeting_says_how_many_are_left(db, wire):
    assert "I'll answer 10 questions here." in _ask("[SYSTEM:opening_greeting:morning]")["response"]
    _ask()
    assert "You have 9 questions left here." in _ask("[SYSTEM:opening_greeting:evening]")["response"]


# ─── Not ready: nothing counted ───────────────────────────────────────

@pytest.mark.parametrize("status,digest,line,reason", [
    ("ready", None, sch.SETTING_UP, "setting_up"),
    ("ready", "", sch.SETTING_UP, "setting_up"),
    ("pending", DIGEST, sch.SETTING_UP, "setting_up"),
    ("ending", DIGEST, sch.CLOSING, "closing"),
])
def test_no_digest_or_a_closing_sample_counts_nothing(db, wire, usage, status, digest, line, reason):
    db.t["businesses"][0] = _sample(status=status, digest=digest)
    out = _ask()
    assert out["response"] == line and out["sample"]["reason"] == reason
    assert out["sample"]["counted"] is False and wire.calls == [] and db.rows(Q) == []
    assert sch.SETTING_UP == "Grace Street is still being set up. Try again in a moment."


def test_paused_ai_counts_nothing(db, wire, monkeypatch):
    import spend_guard
    monkeypatch.setattr(spend_guard, "over_budget", lambda business_id=None: business_id == SAMPLE)
    out = _ask()
    assert out["sample"]["reason"] == "paused" and wire.calls == [] and db.rows(Q) == []


# ─── The cap ──────────────────────────────────────────────────────────

def test_ten_questions_then_capped_without_a_model_call(db, wire, usage):
    for i in range(10):
        out = _ask(f"Question {i}")
        assert out["sample"]["counted"] is True and out["sample"]["n"] == i + 1
        assert out["sample"]["questions_left"] == 9 - i
    out = _ask("One more?")
    assert out["sample"]["capped"] is True and out["sample"]["questions_left"] == 0
    assert out["response"] == "That's your 10. Chief keeps going in your own church once you choose a plan."
    assert len(wire.calls) == 10 and len(_questions(db)) == 10
    assert sorted(r["n"] for r in _questions(db)) == list(range(1, 11))
    # /billing/access reads the same count.
    assert sc.questions_left(OWNER) == 0


def test_the_cap_is_per_person_across_a_new_sample(db, wire):
    for i in range(10):
        _ask(f"Question {i}")
    db.rows("businesses").append(_sample(sid=SAMPLE2, home="home-2"))
    out = _ask("A fresh sample, ten more?", sid=SAMPLE2)
    assert out["sample"]["capped"] is True and len(wire.calls) == 10
    # Someone else starts at ten.
    db.rows("businesses").append(_sample(sid="sample-3", owner=STRANGER, home="home-3"))
    assert _ask("Hello there", sid="sample-3", uid=STRANGER)["sample"]["questions_left"] == 9


def test_the_cap_follows_its_switch(db, wire, monkeypatch):
    monkeypatch.setenv("SAMPLE_CHIEF_QUESTIONS", "2")
    assert sc.questions_of() == 2
    _ask("one")
    assert _ask("two")["sample"]["questions_left"] == 0
    out = _ask("three")
    assert out["sample"]["capped"] is True and out["sample"]["questions_of"] == 2
    assert out["response"].startswith("That's your 2.")
    for raw in ("0", "51", "ten", ""):
        monkeypatch.setenv("SAMPLE_CHIEF_QUESTIONS", raw)
        assert sc.questions_of() == 10


def _claim(uid=OWNER, sid=SAMPLE):
    return sch.claim(uid, cap=10, home_id=HOME, sample_id=sid, question="q")


def test_a_storm_of_racing_questions_makes_exactly_ten(db):
    db.jitter = 0.002
    outcomes = []

    def _until_final(_):
        for _try in range(50):
            got, row, _ = _claim()
            if got in ("ok", "capped"):
                return got
        return "gave up"
    with ThreadPoolExecutor(max_workers=24) as pool:
        outcomes = list(pool.map(_until_final, range(40)))
    assert outcomes.count("ok") == 10 and outcomes.count("capped") == 30
    rows = _questions(db)
    assert len(rows) == 10 and sorted(r["n"] for r in rows) == list(range(1, 11))


def test_a_race_for_one_number_lets_one_through_and_the_loser_reads_again(db, monkeypatch):
    """Two questions read the same empty table; both try n=1. One wins, the
    other reads again once and takes n=2: two rows, never two n=1."""
    import sb_clients
    barrier = threading.Barrier(2)
    real_get = db.get
    first_reads = threading.local()

    def _get(path):
        out = real_get(path)
        if path.startswith(f"/{Q}") and not getattr(first_reads, "done", False):
            first_reads.done = True
            barrier.wait(timeout=5)
        return out
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _claim()[0], range(2)))
    assert results == ["ok", "ok"]
    assert sorted(r["n"] for r in _questions(db)) == [1, 2]


def test_an_insert_whose_answer_was_lost_counts_once(db, monkeypatch):
    import sb_clients

    def _lossy(path, body, prefer="return=representation", **kw):
        db.post(path, body, prefer)
        return None
    monkeypatch.setattr(sb_clients, "sb_post_as_service", _lossy)
    got, row, _ = _claim()
    assert got == "ok" and len(_questions(db)) == 1 and _questions(db)[0]["id"] == row["id"]


def test_a_failed_write_is_not_a_question(db, monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda *a, **k: None)
    assert _claim()[0] == "unwritable" and db.rows(Q) == []


def test_an_abandoned_claim_is_let_go(db):
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    fresh = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    db.rows(Q).extend([
        {"id": "a1", "user_id": OWNER, "n": 1, "answer": "kept", "created_at": old,
         "sample_business_id": SAMPLE},
        {"id": "a2", "user_id": OWNER, "n": 2, "answer": None, "created_at": old,
         "sample_business_id": SAMPLE},       # a deploy cut this turn short
        {"id": "a3", "user_id": OWNER, "n": 3, "answer": None, "created_at": fresh,
         "sample_business_id": SAMPLE},       # still being answered
    ])
    got, row, before = _claim()
    assert got == "ok" and row["n"] == 2
    assert {r["id"] for r in _questions(db)} == {"a1", "a3", row["id"]}


def test_a_hole_in_the_numbers_is_filled_not_stuck_on(db):
    """count+1 would collide with n=3 for ever; the smallest free n doesn't."""
    db.rows(Q).extend([{"id": f"h{n}", "user_id": OWNER, "n": n, "answer": "a",
                        "created_at": "2026-11-15T10:00:0%dZ" % n, "sample_business_id": SAMPLE}
                       for n in (1, 3)])
    assert _claim()[1]["n"] == 2
    assert _claim()[1]["n"] == 4


# ─── The model call ───────────────────────────────────────────────────

def test_the_call_runs_only_inside_the_sample_lane(db, wire, usage, monkeypatch):
    _ask()
    assert wire.calls[0][1] is True                      # allow_sample_chief was on
    assert sc.sample_chief_allowed() is False            # and off again after
    # Without the lane, llm_call refuses before the call: nothing spent,
    # nothing counted.
    monkeypatch.setattr(sc, "allow_sample_chief", contextlib.nullcontext)
    out = _ask("Who's serving Sunday?")
    assert out["sample"]["reason"] == "failed" and out["sample"]["counted"] is False
    assert len(wire.calls) == 1 and len(_questions(db)) == 1
    assert out["sample"]["questions_left"] == 9


def test_the_request_is_the_chat_model_structured_and_cached(db, wire):
    import chief_models
    _ask("Who's been drifting?")
    _ask("Yes, write them.")
    first, second = wire.calls[0][0], wire.calls[1][0]
    assert first["model"] == chief_models.model_for("chat")
    assert first["output_config"]["effort"] == "low"
    fmt = first["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"] == sch.REPLY_SCHEMA
    rules, records, tail = first["system"]
    assert rules["text"] == sch.RULES and "cache_control" not in rules
    assert records["text"] == sch.RECORDS_HEAD + DIGEST
    assert records["cache_control"] == {"type": "ephemeral"}
    assert "Pastor Ana" in tail["text"] and "cache_control" not in tail
    # The cached prefix is byte-identical from question to question.
    assert first["system"][:2] == second["system"][:2]
    assert first["messages"] == [{"role": "user", "content": "Who's been drifting?"}]
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    assert json.loads(second["messages"][1]["content"])["answer"].startswith("Four regulars")


def test_history_is_this_samples_questions_since_its_last_seed(db, wire):
    """BE-2 re-seeds when the week turns: last week's answers quote last
    week's records, and another sample's quote another's."""
    seed = datetime.now(timezone.utc) - timedelta(hours=1)
    db.t["businesses"][0]["settings"][sc.SETTINGS_KEY]["seeded_at"] = seed.isoformat()
    stamp = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")  # noqa: E731
    db.rows(Q).extend([
        {"id": "old", "user_id": OWNER, "n": 1, "question": "last week?", "answer": "Last week's.",
         "drafts": [], "sample_business_id": SAMPLE, "created_at": stamp(seed - timedelta(days=2))},
        {"id": "other", "user_id": OWNER, "n": 2, "question": "other sample?", "answer": "Another's.",
         "drafts": [], "sample_business_id": SAMPLE2, "created_at": stamp(seed + timedelta(minutes=1))},
        {"id": "now", "user_id": OWNER, "n": 3, "question": "this week?", "answer": "This week's.",
         "drafts": [], "sample_business_id": SAMPLE, "created_at": stamp(seed + timedelta(minutes=2))},
    ])
    out = _ask("And then?")
    assert out["sample"]["n"] == 4 and out["sample"]["questions_left"] == 6
    sent = wire.calls[0][0]["messages"]
    assert [m["content"] for m in sent if m["role"] == "user"] == ["this week?", "And then?"]


def test_the_last_question_is_told_it_is_the_last(db, wire, monkeypatch):
    monkeypatch.setenv("SAMPLE_CHIEF_QUESTIONS", "1")
    _ask()
    assert "last question" in wire.calls[0][0]["system"][-1]["text"]


def test_the_structured_reply_is_parsed_and_cleaned(db, wire):
    wire.replies = [_reply("Here are the drafts. " + sch.SAMPLE_LINE, [
        {"kind": "email", "to_label": "  the greeting\nteam ", "subject": "Thank you", "body": "Thank you, greeters."},
        {"kind": "text", "to_label": "Priya Shah", "subject": "dropped on a text", "body": "Hi Priya."},
        {"kind": "fax", "to_label": "Kofi Mensah", "body": "Hi Kofi."},
        {"kind": "note", "to_label": "x", "body": "   "},
        {"kind": "post", "to_label": "everyone", "body": "One"},
        {"kind": "post", "to_label": "everyone", "body": "Two"},
    ])]
    out = _ask("Write the notes.")
    drafts = out["sample"]["drafts"]
    assert [d["kind"] for d in drafts] == ["email", "text", "note", "post"]
    assert drafts[0] == {"kind": "email", "to_label": "the greeting team", "body": "Thank you, greeters.",
                         "subject": "Thank you"}
    assert "subject" not in drafts[1]
    assert out["response"].startswith(out["sample"]["answer"] + "\n\n**Draft email to the greeting team**")
    stored = _questions(db)[0]
    assert stored["answer"] == out["sample"]["answer"] and stored["drafts"] == drafts
    with pytest.raises(ValueError):
        sch.parse_reply('{"answer": "", "drafts": []}')
    with pytest.raises(ValueError):
        sch.parse_reply("not json")


def test_a_claim_of_sending_is_replaced_and_drafts_always_say_sample(db, wire):
    wire.replies = [_reply("Done. I sent all four texts."),
                    _reply("Here's the note.", [{"kind": "text", "to_label": "Denise Carter", "body": "Hi Denise."}]),
                    _reply("Okay.")]
    assert _ask("Send them.")["sample"]["answer"] == sch.HONEST
    assert _ask("Write Denise a note.")["sample"]["answer"] == f"Here's the note. {sch.SAMPLE_LINE}"
    assert _ask("Delete everyone.")["sample"]["answer"] == f"Okay. {sch.ACT_LINE}"


@pytest.mark.parametrize("status,stop", [(500, "end_turn"), (200, "max_tokens"), (200, "refusal")])
def test_a_failed_answer_is_not_counted_but_a_billed_one_is_metered(db, wire, usage, status, stop):
    wire.status, wire.stop = status, stop
    out = _ask()
    assert out["response"] == sch.FAILED and out["sample"]["counted"] is False
    assert out["sample"]["questions_left"] == 10 and db.rows(Q) == []
    if status == 200:          # the model ran: the spend is on the books
        assert len(usage) == 1 and usage[0]["ok"] is False and usage[0]["endpoint"] == "sample_chief"
    else:
        assert usage == []


# ─── Nothing else is written; the spend is on the books ───────────────

def test_only_the_question_row_is_ever_written(db, wire, usage):
    wire.replies = [_reply(), _reply("Here.", [{"kind": "text", "to_label": "Priya Shah", "body": "Hi Priya."}])]
    _ask()
    _ask("Text Priya a welcome.")
    _ask("[SYSTEM:opening_greeting:morning]")
    assert {t for _, t in db.writes} == {Q}
    for table in ("chief_conversations", "chief_memories", "chief_notifications", "chief_activity",
                  "agent_queue", "chief_scheduled_actions", "api_usage"):
        assert db.rows(table) == []


def test_usage_is_logged_as_sample_chief_and_stored_on_the_row(db, wire, usage):
    import api_usage_logger as aul
    _ask(request_id="turn-77")
    (row,) = usage
    assert row["endpoint"] == "sample_chief" and row["task_type"] == "sample_chief"
    assert row["business_id"] == SAMPLE and row["user_id"] == OWNER and row["units"] == 0
    assert row["model"] == "claude-sonnet-5-5" and row["ok"] is True
    assert (row["input_tokens"], row["output_tokens"], row["cache_read_tokens"]) == (300, 200, 1600)
    assert row["response_id"] == "msg_1" and row["turn_id"] == "turn-77"
    cents = aul._compute_cost_cents("claude-sonnet-5-5", 300, 200, 1600, 0, 0)
    (q,) = _questions(db)
    assert q["cost_cents"] == cents and q["input_tokens"] == 1900 and q["output_tokens"] == 200
    assert q["model"] == "claude-sonnet-5-5" and q["question"] == "Who's been drifting?"
    assert q["home_business_id"] == HOME and q["sample_business_id"] == SAMPLE


def test_the_seam_does_not_meter_it_twice():
    import llm_call
    assert "sample_chief" in llm_call._SELF_METERING


def test_a_lost_stream_reposted_gets_the_same_answer_not_a_second_question(db, wire):
    import chief_of_staff as cos
    req = _req(request_id="same-turn")

    async def _both():
        resp = await cos.chief_chat_stream(req, user_session=_session())
        async for _ in resp.body_iterator:
            pass
        return await cos.chief_chat(req, user_session=_session())
    out = asyncio.run(_both())
    assert out["sample"]["n"] == 1 and len(wire.calls) == 1 and len(_questions(db)) == 1


# ─── GET /sample-church/questions ─────────────────────────────────────

def _client(uid):
    from starlette.testclient import TestClient
    app = FastAPI()
    app.include_router(sch.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id=uid, email=None, role="authenticated")
    return TestClient(app)


def test_the_questions_are_the_owners_only(db, wire):
    wire.replies = [_reply("First answer."), _reply("Second.", [{"kind": "note", "to_label": "the deacons", "body": "B"}])]
    _ask("first?")
    _ask("second?")
    r = _client(OWNER).get(f"/sample-church/questions?business_id={SAMPLE}")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["questions_left"] == 8 and body["questions_of"] == 10
    assert [(q["n"], q["question"], q["answer"]) for q in body["questions"]] == [
        (1, "first?", "First answer."), (2, "second?", f"Second. {sch.SAMPLE_LINE}")]
    assert body["questions"][1]["drafts"] == [{"kind": "note", "to_label": "the deacons", "body": "B"}]
    assert _client(STRANGER).get(f"/sample-church/questions?business_id={SAMPLE}").status_code == 404
    assert _client(OWNER).get(f"/sample-church/questions?business_id={REAL}").status_code == 404


def test_the_questions_route_needs_a_login():
    from starlette.testclient import TestClient
    app = FastAPI()
    app.include_router(sch.router)
    assert TestClient(app).get(f"/sample-church/questions?business_id={SAMPLE}").status_code == 401


def test_the_router_is_mounted_before_the_catch_all():
    src = (_here.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert src.index("app.include_router(sample_chief_router)") < src.index("app.include_router(public_site_router)")


# ─── The voice ────────────────────────────────────────────────────────

def test_the_eval_passes_offline_and_catches_every_negative_control():
    out = sample_chief_eval.run_offline(quiet=True)
    assert out["passed"] == out["total"], [r for r in out["results"] if not r["ok"]]
    assert out["total"] >= 30
    assert sum(1 for c in sample_chief_eval.CASES if c.get("expect")) >= 8


def test_chiefs_own_words_keep_the_brand_voice():
    import brand_voice
    lines = [sch.SAMPLE_LINE, sch.ACT_LINE, sch.HONEST, sch.SETTING_UP, sch.CLOSING, sch.PAUSED,
             sch.BUSY, sch.FAILED, sch.COACHING, sch.HERE, sch.capped_line(10),
             sch.welcome_line(10, 10), sch.welcome_line(3, 10), sch.welcome_line(0, 10)]
    for line in lines:
        assert not any(rx.search(line) for rx, _ in brand_voice._AVOID_RE), line
        assert "!" not in line and not sch.claims_done(line), line
    assert sch.check_reply("q", "I'm your AI assistant.", [], DIGEST) == ["avoid_word"]


def test_the_claim_check_reads_negations_and_drafts():
    yes = ["I sent the texts.", "I've scheduled the reminder.", "We've posted it.",
           "The email was sent this morning.", "It went out at noon."]
    no = [sch.SAMPLE_LINE, sch.HONEST, "I haven't sent anything.", "In your church I'd send them.",
          "I've added three drafts below.", "Nothing has been sent or saved.", "I can send these in your church."]
    assert all(sch.claims_done(s) for s in yes)
    assert not any(sch.claims_done(s) for s in no)
    assert sch.asks_to_act("Send it.") and sch.asks_to_act("ok, delete everyone")
    assert not sch.asks_to_act("Who should I text this week?")
