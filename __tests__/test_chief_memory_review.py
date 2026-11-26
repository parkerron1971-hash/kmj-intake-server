"""Chief's notes for a business, checked for tidying (chief_memory_review, the
Chief read `review_memories`), and forget by a note's own id.

Kevin, 2026-11-24, on Chief's memory: "ok great. lets build this." The second of
three.

Pins:
  * which notes a reply carries is worked out the way the turn itself picks them
  * notes that share most of their words are grouped; a pair that differs by a
    not, a number, a day or an amount is marked may_disagree, never a duplicate
  * nothing is offered for dropping only because it is old: old notes are listed,
    and the read changes nothing
  * insights, the Notes pad and Chief's own bookkeeping rows are left out
  * forget by memory_id takes exactly that note, only among this business's
    active notes; a phrase still works as before
  * Chief is told, under its notes, when more are kept than a reply carries
  * it is the owner's in a lane, Chief's alone, and wired where a read is wired
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import action_registry  # noqa: E402
import chief_areas as ca  # noqa: E402
import chief_memory_review as mr  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import chief_tool_loop as loop  # noqa: E402

BIZ = {"id": "11111111-1111-4111-8111-111111111111", "owner_id": "o"}


def note(n, content, importance=5, days=1, category="preference", used=None):
    at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return {"id": f"00000000-0000-4000-8000-{n:012d}", "content": content, "importance": importance,
            "category": category, "source": "user_stated", "created_at": at,
            "last_referenced_at": (datetime.now(timezone.utc) - timedelta(days=used)).isoformat() if used is not None else None}


def ids(items):
    return [int(i["memory_id"][-12:]) for i in items]


# ─── Which notes a reply carries ──────────────────────────────────────

def test_with_few_notes_all_are_carried_and_nothing_needs_tidying():
    out = mr.review([note(1, "Prefers texts over calls"), note(2, "Office is closed on Mondays")])
    assert out["kept"] == 2 and out["carried"] == 2 and out["not_carried"] == [] and out["look_alike"] == []
    assert out["result"] == "2 notes kept; all of them carried on every reply. Nothing needs tidying."
    assert out["label"] == "Nothing to tidy" and out["type"] == "review_memories"


def test_past_the_top_fifty_the_rest_are_named_the_way_the_turn_picks_them():
    rows = [note(i, f"Fact number {i} about the church office xyz{i}", importance=8, days=2) for i in range(1, 51)]
    rows += [note(i, f"Old small thing {i} qrs{i}", importance=2, days=300) for i in range(51, 64)]
    out = mr.review(rows)
    assert out["kept"] == 63 and out["carried"] == 50 and out["not_carried_count"] == 13
    assert set(ids(out["not_carried"])) <= set(range(51, 64)) and len(out["not_carried"]) == mr.LIST_MAX
    assert "50 carried on every reply and 13 not carried (only the top 50 are)" in out["result"]
    # The same pick the turn's context makes.
    pool = sorted(sorted(rows, key=lambda m: m["created_at"], reverse=True),
                  key=lambda m: m["importance"], reverse=True)[:100]
    assert mr.carried_ids(rows) == {m["id"] for m in cos._blend_memories(pool)}


def test_a_recently_used_small_note_can_be_carried_over_a_stale_bigger_one():
    rows = [note(i, f"Middling fact {i} abc{i}", importance=5, days=400) for i in range(1, 51)]
    rows.append(note(99, "Touched this week zzz", importance=4, days=400, used=1))
    assert rows[-1]["id"] in mr.carried_ids(rows)


# ─── Look-alikes ──────────────────────────────────────────────────────

def test_two_notes_that_say_the_same_thing_are_grouped_for_the_owner_to_pick():
    out = mr.review([note(1, "Kevin prefers a text before any phone call"),
                     note(2, "Kevin prefers a text message before any phone call"),
                     note(3, "The youth group meets in the gym")])
    (g,) = out["look_alike"]
    assert ids(g["notes"]) == [1, 2] and g["may_disagree"] is False and "Ask which wording to keep" in g["why"]
    assert "1 group that look alike" in out["result"]


@pytest.mark.parametrize("a,b", [
    ("Take coaching calls on Friday", "Do not take coaching calls on Friday"),
    ("Staff meeting is Tuesday at the office", "Staff meeting is Thursday at the office"),
    ("Second service starts at 11 in the sanctuary", "Second service starts at 10 in the sanctuary"),
    ("The retreat deposit per person is $50", "The retreat deposit per person is $75"),
    ("Send the newsletter weekly to members", "Send the newsletter monthly to members"),
])
def test_a_pair_that_differs_by_a_not_a_number_or_a_day_is_never_called_a_duplicate(a, b):
    out = mr.review([note(1, a), note(2, b)])
    (g,) = out["look_alike"]
    assert g["may_disagree"] is True and "Show both and ask which is true" in g["why"]
    assert "1 of which may disagree" in out["result"]


def test_the_same_words_twice_is_said_as_that_and_disagreements_come_first():
    out = mr.review([note(1, "Always greet new families by name"), note(2, "always greet  new families by name"),
                     note(3, "Bill clients on the 1st of the month"), note(4, "Bill clients on the 15th of the month")])
    first, second = out["look_alike"]
    assert first["may_disagree"] and ids(first["notes"]) == [3, 4]
    assert second["why"] == "The same words twice."


def test_notes_about_different_things_are_not_grouped():
    out = mr.review([note(1, "Prefers texts over calls"), note(2, "The roof fund goal is $40,000"),
                     note(3, "Wednesday is the day off")])
    assert out["look_alike"] == []


# ─── Old notes ────────────────────────────────────────────────────────

def test_an_old_note_is_listed_never_dropped_and_the_read_changes_nothing():
    rows = [note(1, "Anniversary is June 3", importance=9, days=400), note(2, "Liked the blue flyer", importance=2, days=200),
            note(3, "New this week", days=2), note(4, "Old but touched yesterday", days=500, used=1)]
    out = mr.review(rows)
    assert ids(out["unused"]) == [2, 1], "least important first"
    assert out["unused"][0]["last_used_days_ago"] >= 199 and out["unused_count"] == 2
    assert "Never drop a note only because it is old" in out["how_to_change"]
    assert "It changes nothing" in mr.TOOL["description"] and "may_disagree is NOT a duplicate" in mr.TOOL["description"]
    assert mr.TOOL["input_schema"]["properties"] == {}


def test_insights_the_notes_pad_and_bookkeeping_rows_are_left_out():
    rows = [note(1, "Tuesdays have been thin since March", category="insight"),
            note(2, "[note:idea] a podcast about grief", category="other"),
            note(3, "asked about domains", category="jit_asked"), note(4, "Prefers texts")]
    out = mr.review(rows)
    assert out["kept"] == 1 and out["carried"] == 1


def test_a_long_note_is_cut_and_the_answer_reaches_chief_whole():
    rows = [note(i, ("Service planning detail " + f"k{i} ") + "word " * 200, importance=1, days=300) for i in range(1, 90)]
    out = mr.review(rows)
    assert all(len(n["note"]) <= mr.TEXT_CHARS for n in out["not_carried"] + out["unused"])
    assert "truncated" not in loop._shrink(out).lower()
    assert out["not_carried_count"] == 39 and out["unused_count"] == 89 and "Not every note is listed" in out["shown"]
    assert len(out["not_carried"]) >= 3 and len(out["unused"]) >= 3


# ─── The read ─────────────────────────────────────────────────────────

def run(rows, monkeypatch):
    seen = []

    async def sb(client, method, path, body=None, *a, **k):
        seen.append((method, path))
        return rows
    monkeypatch.setattr(cos, "_sb", sb)
    return asyncio.run(mr.handle_review_memories(None, BIZ, {})), seen


def test_the_read_is_this_businesss_active_notes_and_says_when_it_could_not(monkeypatch):
    out, seen = run([note(1, "Prefers texts")], monkeypatch)
    assert seen == [("GET", f"/chief_memories?business_id=eq.{BIZ['id']}&is_active=eq.true"
                            f"&order=importance.desc,created_at.desc&limit={mr.READ_MAX}"
                            "&select=id,category,content,importance,source,created_at,last_referenced_at")]
    assert out["kept"] == 1 and out["result"] and out["label"]
    out, _ = run(None, monkeypatch)
    assert out["failed"] and "couldn't read" in out["result"] and out["label"]
    out, seen = run([], monkeypatch)
    assert out["result"].startswith("0 notes kept")
    assert asyncio.run(mr.handle_review_memories(None, {}, {}))["failed"]


# ─── forget by a note's own id ────────────────────────────────────────

def forget(action, monkeypatch, found=True, readable=True):
    calls = []

    async def sb(client, method, path, body=None, *a, **k):
        calls.append((method, path, body))
        if method == "GET" and "/chief_memories?id=eq." in path:
            return ([{"id": action.get("memory_id"), "content": "Take coaching calls on Friday"}] if found else []) \
                if readable else None
        if method == "GET":
            return [{"id": "a", "content": "Take coaching calls on Friday"},
                    {"id": "b", "content": "Do not take coaching calls on Friday"}]
        return [{}]
    monkeypatch.setattr(cos, "_sb", sb)
    return asyncio.run(cos.handle_forget(None, BIZ, action)), calls


def test_forget_by_id_takes_exactly_that_note_of_this_business(monkeypatch):
    mid = "00000000-0000-4000-8000-000000000002"
    out, calls = forget({"type": "forget", "memory_id": mid}, monkeypatch)
    assert out["result"] == "forgotten" and out["label"].startswith("Forgot: Take coaching calls")
    assert calls == [
        ("GET", f"/chief_memories?id=eq.{mid}&business_id=eq.{BIZ['id']}&is_active=eq.true&select=id,content&limit=1", None),
        ("PATCH", f"/chief_memories?id=eq.{mid}&business_id=eq.{BIZ['id']}", {"is_active": False})]


def test_forget_by_an_id_that_isnt_this_businesss_active_note_touches_nothing(monkeypatch):
    mid = "00000000-0000-4000-8000-000000000009"
    out, calls = forget({"type": "forget", "memory_id": mid}, monkeypatch, found=False)
    assert out["result"] == "couldn't find that memory" and out["label"] and [c[0] for c in calls] == ["GET"]
    out, calls = forget({"type": "forget", "memory_id": mid}, monkeypatch, readable=False)
    assert out["result"] and out["label"] and [c[0] for c in calls] == ["GET"]
    for bad in ("1", "x&business_id=eq.other", "not-a-uuid-at-all-not-a-uuid-at-all!", "a" * 36 + "&"):
        out, calls = forget({"type": "forget", "memory_id": bad}, monkeypatch)
        assert out["result"] and out["label"] and calls == [], bad


def test_forget_by_a_phrase_still_works_as_it_did(monkeypatch):
    out, calls = forget({"type": "forget", "memory_content": "do not take coaching calls friday"}, monkeypatch)
    assert out["result"] == "forgotten" and calls[-1][0] == "PATCH"


# ─── Chief is told when some aren't carried ───────────────────────────

def test_the_notes_block_says_when_more_are_kept_than_a_reply_carries():
    assert cos._notes_not_carried_line({}) == "" and cos._notes_not_carried_line({"memories_not_carried": 0}) == ""
    assert cos._notes_not_carried_line({"memories_not_carried": "x"}) == ""
    line = cos._notes_not_carried_line({"memories_not_carried": 13})
    assert "At least 13 more notes are kept but not carried here" in line and "review_memories" in line
    import inspect
    src = inspect.getsource(cos)
    assert '"memories_not_carried": max(0, len(memories or []) - len(mem_pool)),' in src
    assert "{_notes_not_carried_line(ctx)}" in src


# ─── Where it is wired ────────────────────────────────────────────────

def test_it_is_the_owners_in_a_lane_chiefs_alone_and_the_manual_says_when():
    lane = {"areas": ["people_care"], "role": "manager", "lane": "people_care"}
    assert "review_memories" in ca.OWNERS and ca.refusal("review_memories", {}, lane)
    cls = action_registry.classification("review_memories")
    assert cls and cls.get("chief_only") and cls.get("effect") == "read"
    assert cos.ACTION_HANDLERS["review_memories"] is mr.handle_review_memories
    assert "review_memories" in cos._ACTION_PHRASES
    import chief_prompt
    import inspect
    import mcp_server
    assert not action_registry.may_expose_to_agent("review_memories", allow_writes=True)
    assert "review_memories" not in mcp_server.exposed_tools(allow_writes=True)
    src = inspect.getsource(chief_prompt)
    assert "→   review_memories" in src and '"type":"forget","memory_id"' in src
    assert "chief_memory_review.TOOL" in inspect.getsource(loop)
