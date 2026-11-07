"""A church's drafted reply to a card is a welcome, not a sales reply.

Renee's card on the test church (2026-11-06) came back telling someone who had
just visited "before you ever walk in the door", and telling her it didn't want
to guess at service times. The draft knew neither that she had come nor what
the church's public facts were.

  1. Every church card: short, from a pastor, and never a word about what the
     note doesn't know.
  2. A connect card: someone who has visited is thanked for coming.
  3. The church's public facts reach the draft, and nothing else is a source.
  4. Other businesses' drafts are untouched.
"""
from __future__ import annotations

import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import church_follow_up as cfu  # noqa: E402
import intake_endpoint  # noqa: E402

CONNECT = {"name": "Connect card", "form_type": "connect_card"}
PLAN_A_VISIT = {"name": "Plan your visit", "form_type": "general"}
FACTS = ["Coming up: Sun, Nov 8: Sunday Worship (Main Hall)", "Where: 12 Elm St"]


def test_every_church_card_is_short_and_never_says_what_it_does_not_know():
    rules = cfu.welcome_note_rules(PLAN_A_VISIT, FACTS)
    assert "under 120 words" in rules
    assert "Never tell the reader what you don't know" in rules
    assert "Use only the church facts below" in rules


def test_a_connect_card_thanks_someone_who_has_visited():
    rules = cfu.welcome_note_rules(CONNECT, FACTS)
    assert "thank them for coming" in rules
    assert "never write as if they haven't come yet" in rules
    assert "This is my first time" in rules


def test_a_visit_card_is_not_told_they_already_came():
    assert "thank them for coming" not in cfu.welcome_note_rules(PLAN_A_VISIT, FACTS)


def test_the_churchs_facts_reach_the_note():
    rules = cfu.welcome_note_rules(CONNECT, FACTS)
    assert "- Coming up: Sun, Nov 8: Sunday Worship (Main Hall)" in rules
    assert "- Where: 12 Elm St" in rules


def test_no_facts_on_file_says_so_rather_than_leaving_a_gap():
    assert "- None on file." in cfu.welcome_note_rules(CONNECT, [])


def test_facts_are_capped():
    rules = cfu.welcome_note_rules(CONNECT, [f"Fact {i}" for i in range(cfu.MAX_NOTE_FACTS + 5)])
    assert f"Fact {cfu.MAX_NOTE_FACTS - 1}" in rules and f"Fact {cfu.MAX_NOTE_FACTS}" not in rules


def test_the_draft_carries_the_rules_only_for_a_church():
    src = inspect.getsource(intake_endpoint.submit_intake)
    assert 'church_rules = ""' in src and "if church_follow_up.is_church(business):" in src
    assert "{church_rules}" in src
    assert src.index("{church_rules}") < src.index("RESPOND ONLY WITH VALID JSON")
