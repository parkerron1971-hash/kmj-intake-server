"""Chief's turns are saved under the login that asked, and each login recalls its own
(chief_of_staff._archive_turn, _recall_whose; chief_brain_pass._owners_own;
supabase/APPLY-2026-11-24-chief-conversations-by-login.sql).

Kevin, 2026-11-23: "check out a conversation Jessica was having with Chief". Her
words could not be read: the table let only the owner save, and a turn was saved
as the person who asked.

Pins:
  * once a row keeps its login, the server saves every turn itself, with the
    login it verified; before that, a turn is saved exactly as it always was
  * a recall keeps to whoever is asking: an office login its own, the owner the
    owner's own and the rows from before a login was kept; a surface with no
    login in it acts for the owner, never for the team
  * an office login may recall (it reads only its own)
  * what Chief learns nightly comes from the owner's conversations only
  * the SQL: who asked, an index, the two row rules, no rule that lets one login
    read another's
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from unittest.mock import AsyncMock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import chief_areas as ca  # noqa: E402
import chief_brain_pass as cbp  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import schema_probe  # noqa: E402
import sb_clients  # noqa: E402

OWNER = "00000000-0000-4000-8000-0000000000aa"
JESSICA = "00000000-0000-4000-8000-0000000000bb"
BIZ = {"id": "11111111-1111-4111-8111-111111111111", "owner_id": OWNER, "name": "Love City Church",
       "type": "ministry"}
SQL = os.path.join(ROOT, "supabase", "APPLY-2026-11-24-chief-conversations-by-login.sql")


@pytest.fixture
def column(monkeypatch):
    """Whether chief_conversations keeps who asked (the file applied) is set by the test."""
    state = {"there": True}

    async def has_async(table, cols):
        return state["there"] if tuple(cols) == ("user_id",) else False
    monkeypatch.setattr(schema_probe, "has_columns_async", has_async)
    monkeypatch.setattr(schema_probe, "has_columns",
                        lambda table, cols: state["there"] if tuple(cols) == ("user_id",) else False)
    return state


def as_login(uid):
    return cos._TURN_USER_ID.set(uid)


def archive(monkeypatch, uid):
    """Run one turn's save; returns (rows the server wrote, rows written as the person)."""
    served, as_person = [], []
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda path, body, **k: served.append((path, body)) or [body])

    async def sb(client, method, path, body=None, *a, **k):
        as_person.append((method, path, body))
        return [body]
    monkeypatch.setattr(cos, "_sb", sb)
    token = as_login(uid)
    try:
        asyncio.run(cos._archive_turn(None, BIZ, "Give Shapretta the December announcements",
                                      "I haven't done this yet.", [{"type": "give_assignment", "label": "x",
                                                                    "result": "Failed: HELD"}]))
    finally:
        cos._TURN_USER_ID.reset(token)
    return served, as_person


# ─── Saving ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("uid", [JESSICA, OWNER])
def test_once_a_row_keeps_its_login_the_server_saves_the_turn_under_it(monkeypatch, column, uid):
    served, as_person = archive(monkeypatch, uid)
    assert not as_person, "never as the person: the table would refuse an office login without a word"
    (path, row), = served
    assert path == "/chief_conversations" and row["user_id"] == uid and row["business_id"] == BIZ["id"]
    assert row["messages"][0] == {"role": "user", "content": "Give Shapretta the December announcements"}
    assert row["actions_taken"][0]["type"] == "give_assignment"


def test_before_the_column_a_turn_is_saved_exactly_as_it_always_was(monkeypatch, column):
    column["there"] = False
    served, as_person = archive(monkeypatch, JESSICA)
    assert not served
    (method, path, row), = as_person
    assert (method, path) == ("POST", "/chief_conversations") and "user_id" not in row


def test_with_nobody_in_the_turn_nothing_is_saved_as_the_server(monkeypatch, column):
    served, as_person = archive(monkeypatch, "")
    assert not served and len(as_person) == 1 and "user_id" not in as_person[0][2]


def test_a_save_that_does_not_land_never_costs_the_turn(monkeypatch, column, capsys):
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda path, body, **k: None)
    monkeypatch.setattr(cos, "_sb", AsyncMock(side_effect=AssertionError("not as the person")))
    token = as_login(JESSICA)
    try:
        asyncio.run(cos._archive_turn(None, BIZ, "hello", "hi", []))
    finally:
        cos._TURN_USER_ID.reset(token)
    assert "a turn wasn't saved" in capsys.readouterr().out


# ─── Recalling ────────────────────────────────────────────────────────

def recall_path(monkeypatch, uid, biz=BIZ):
    seen = []

    async def sb(client, method, path, *a, **k):
        seen.append(path)
        return []
    monkeypatch.setattr(cos, "_sb", sb)
    token = as_login(uid)
    try:
        out = asyncio.run(cos.handle_recall_conversation(None, biz, {"query": "announcements"}))
    finally:
        cos._TURN_USER_ID.reset(token)
    assert out["result"] and out["label"]
    return seen[0]


def test_an_office_login_recalls_only_its_own(monkeypatch, column):
    path = recall_path(monkeypatch, JESSICA)
    assert f"&user_id=eq.{JESSICA}&" in path and "or=(" not in path
    assert f"business_id=eq.{BIZ['id']}" in path


def test_the_owner_recalls_the_owners_own_and_what_was_saved_before(monkeypatch, column):
    path = recall_path(monkeypatch, OWNER)
    assert f"&or=(user_id.is.null,user_id.eq.{OWNER})&" in path


def test_a_surface_with_no_login_acts_for_the_owner_never_for_the_team(monkeypatch, column):
    """An outside agent's recall (the connector) has no person in it."""
    path = recall_path(monkeypatch, "")
    assert f"&or=(user_id.is.null,user_id.eq.{OWNER})&" in path and JESSICA not in path
    assert "&user_id=is.null&" in recall_path(monkeypatch, "", {"id": BIZ["id"]})


def test_before_the_column_the_recall_reads_as_it_always_did(monkeypatch, column):
    column["there"] = False
    path = recall_path(monkeypatch, JESSICA)
    assert "user_id" not in path


def test_an_office_login_may_recall_and_is_told_its_conversations_are_its_own():
    lane = {"areas": ["people_care"], "role": "manager", "lane": "people_care"}
    assert ca.refusal("recall_conversation", {}, lane) is None
    assert "recall_conversation" not in ca.OWNERS and ca.VERBS["recall_conversation"] == (ca.ALL,)
    said = ca.block(lane, {"role": "manager", "name": "Jessica McCloud", "first_name": "Jessica"}, BIZ)
    assert "The owner's own memories and past conversations aren't shown to this login" in said
    assert "This login's own earlier conversations with you are theirs: recall_conversation finds them." in said


# ─── What Chief learns from ───────────────────────────────────────────

def test_the_nightly_pass_learns_from_the_owners_conversations_only(monkeypatch, column):
    monkeypatch.setattr(cbp, "_get", lambda path: [{"owner_id": OWNER}] if path.startswith("/businesses") else [])
    assert cbp._owners_own(BIZ["id"]) == f"&or=(user_id.is.null,user_id.eq.{OWNER})"
    # An owner that can't be read: only the rows with no login, which are the owner's.
    monkeypatch.setattr(cbp, "_get", lambda path: [])
    assert cbp._owners_own(BIZ["id"]) == "&user_id=is.null"
    column["there"] = False
    assert cbp._owners_own(BIZ["id"]) == ""
    import inspect
    assert "{_owners_own(bid)}" in inspect.getsource(cbp.gather)


# ─── The SQL ──────────────────────────────────────────────────────────

def test_the_sql_keeps_who_asked_and_lets_no_login_read_anothers():
    sql = open(SQL, encoding="utf-8").read()
    live = "\n".join(ln for ln in sql.split("\n") if not ln.lstrip().startswith("--"))
    assert "add column if not exists user_id uuid" in live
    assert "create index if not exists chief_conversations_business_user" in live
    assert live.count("create policy") == 2 and "begin;" in live and "commit;" in live
    owner = live[live.index("create policy chief_conversations_business_owner"):live.index(
        "create policy chief_conversations_own_read")]
    assert owner.count("(user_id is null or user_id = auth.uid())") == 2, "read and write, both"
    assert "owner_id = auth.uid()" in owner
    own = live[live.index("create policy chief_conversations_own_read"):]
    assert "for select to authenticated" in own
    assert "user_id = auth.uid() and public.is_business_member(business_id)" in own
    # No rule opens the table wider than a login's own rows, and nothing here is destructive to rows.
    assert not re.search(r"using\s*\(\s*true\s*\)", live, re.I)
    assert not re.search(r"\b(delete from|truncate|drop table|drop column)\b", live, re.I)
    # The ledger lists it, and says it is waiting.
    ledger = open(os.path.join(ROOT, "docs", "MIGRATIONS.md"), encoding="utf-8").read()
    row = next(ln for ln in ledger.split("\n") if "APPLY-2026-11-24-chief-conversations-by-login.sql" in ln)
    assert "NOT APPLIED" in row
