"""Every verb Chief is TOLD to emit must be a verb Chief can RUN.

WHY THIS FILE EXISTS
  Chief's prompt is ~140k characters of capability description, and the
  practitioner experiences it as promises: "want me to build that?",
  "I'll generate the site and you can preview it", "say the word and I'll
  send it". Each of those is only as real as the [ACTION:] tag behind it.

  `_build_website_block` asked for `generate_website` after a seven-step
  interview that ends in an explicit yes/no question — and there has never
  been a `generate_website` handler. The dispatcher's unknown-action path
  caught the tag and tried to reason it into safe primitives, so nothing
  crashed and nothing was logged as broken. The practitioner said yes and
  got a shrug. It sat that way because nothing checked.

  `test_action_registry` pins ACTION_HANDLERS against the taxonomy and
  `test_add_module_field` pins two specific verbs against the prompt. This
  is the pin in the other direction, over every verb at once: the prompt
  may not NAME a verb that does not exist.

  A capability Chief describes and cannot perform is worse than one it
  lacks — it spends the practitioner's trust and their time, and it fails
  at the exact moment they said yes.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_of_staff as cos

# Anchored on the tag opener, so a `"type"` inside an action's own payload
# (a form field's type, a product_type, a nested schema) is not mistaken
# for a verb.
ACTION_TAG = re.compile(r'\[ACTION:\s*\{\s*"type"\s*:\s*"([a-zA-Z_]+)"')

# Every persona the practitioner can be talking to. Each is a different
# prompt with its own verb set, so checking one checks a third of them.
MODES = (None, "strategy_coach", "business_coach")


class _EmptyCtx(dict):
    def __missing__(self, key):
        return []


def _prompt(mode):
    return cos._build_system_prompt(
        _EmptyCtx(business={"id": "b1", "name": "T", "type": "coach",
                            "settings": {}, "voice_profile": {}}),
        False, mode=mode)


@pytest.mark.parametrize("mode", MODES)
def test_every_verb_the_prompt_names_has_a_handler(mode):
    named = set(ACTION_TAG.findall(_prompt(mode)))
    orphans = sorted(named - set(cos.ACTION_HANDLERS))
    assert not orphans, (
        f"Chief's {mode or 'operational'} prompt tells it to emit "
        f"{orphans} — and there is no handler for it. The tag falls through "
        f"to the unknown-action path, so the practitioner who said yes gets "
        f"nothing and no error. Either build the handler or stop promising "
        f"the verb.")


@pytest.mark.parametrize("mode", MODES)
def test_the_prompt_actually_names_verbs(mode):
    """Guards the guard. If the regex ever stops matching — a format
    change, a rename of the tag syntax — the test above passes over an
    empty set and silently protects nothing."""
    assert len(ACTION_TAG.findall(_prompt(mode))) > 5


def test_the_capabilities_the_practitioner_asked_for_are_all_reachable():
    """The specific list from the 2026-08-25 report, pinned by name.

    These are the things Chief offers to do for a practitioner mid-
    conversation. Each needs a handler AND a mention in the prompt — a
    handler nobody told the model about is unreachable, which is exactly
    how Client Forms stayed impossible while its table, its public submit
    door and its whole screen worked.
    """
    prompt = _prompt(None)
    for verb in (
        "create_client_form",      # client forms — the gap that started this
        "update_client_form",
        "list_client_forms",
        "ensure_module",           # modules
        "propose_module_from_intake",
        "create_course",           # courses
        "create_note",             # notes
        "save_note",
        "compose_template",        # a reusable contract template, stored
        "adjust_template",
        "generate_document",       # generating from one
        "draft_email",             # email
        "draft_and_send",
        "approve_draft",
        "enqueue_job",             # the website build
    ):
        assert verb in cos.ACTION_HANDLERS, f"{verb} has no handler"
        assert verb in prompt, f"{verb} exists but Chief is never told about it"
