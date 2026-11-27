"""The answer check is told what Chief can do for this login (chief_truth.actions_capability).

Kevin, 2026-11-27, after asking Chief to work on the offering: "when i said what
said it said it could[n't] verify it's answer. that needs to be fixed in general".
Chief had offered to record the 22nd's gifts once he gave them. The review held it
back: "Nothing in the supplied sources shows ... that Chief can record offerings".
Its only capability sources were invoice delivery and Chief's computer.

Pins:
  * the actions this login may use that the draft points at are a capability
    source, each with what it does; a login without the key gets none of them
  * nothing for a reply that points at no action; never more than a handful
  * a capability supports "I can" and an offer, never that something ran
  * the review is told an offer needs a capability, not the records ready now
  * the source reaches the review
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import chief_areas  # noqa: E402
import chief_truth as truth  # noqa: E402

HELD = ("Whenever you have the gift amounts and names for the 22nd, just tell me and I'll record them into that "
        "service's count.")
CARE = {"areas": ["people_care"], "role": "manager", "lane": "people_care"}


def test_the_draft_that_was_held_back_now_has_its_action_named():
    text = truth.actions_capability(HELD)
    assert text.startswith("Actions Chief can use for the person in this chat")
    assert "- record_service_gifts: records the gifts a person names into one service's open count" in text
    assert "never that anything ran, that anything is set up, or what a record holds" in text


def test_a_login_without_the_key_gets_none_of_those_actions():
    assert "record_service_gifts" not in truth.actions_capability(HELD, CARE)
    assert "match_giving_deposits" not in truth.actions_capability("Want me to match the deposits?", CARE)


def test_nothing_for_a_reply_that_points_at_no_action_and_never_many():
    assert truth.actions_capability("Good morning! How are you today?") == ""
    assert truth.actions_capability("") == ""
    busy = ("I can record gifts, match deposits, send invoices, text contacts, email clients, book sessions, create "
            "tasks, draft posts, plan content, build pages and add products for you.")
    lines = [ln for ln in truth.actions_capability(busy).splitlines() if ln.startswith("- ")]
    assert 0 < len(lines) <= truth.CAPABILITY_ACTIONS_MAX


def test_it_never_raises():
    assert truth.actions_capability(HELD, handlers={"not_a_verb": None}) == ""
    assert truth.actions_capability(None) == ""


def test_the_review_is_told_an_offer_needs_a_capability_not_the_records_ready_now():
    assert "An offer of work to come" in truth.REVIEW_SYSTEM
    assert "supported by a capability source that names that action" in truth.REVIEW_SYSTEM
    assert "Every executed action claim needs a matching receipt" in truth.REVIEW_SYSTEM, "unchanged"


def test_a_capability_supports_an_offer_never_an_action_that_ran():
    sources = {"system:chief_actions": {"kind": "capability", "complete": True, "text": truth.actions_capability(HELD)}}
    offer = "just tell me and I'll record them"
    raw = json.dumps({"verdict": "supported", "claims": [
        {"text": offer, "kind": "fact", "source_id": "system:chief_actions", "quote": "records the gifts a person names"}]})
    verdict, _, _ = truth.assess_review(raw, HELD, sources)
    assert verdict == "supported"
    done = "I recorded the gifts."
    raw = json.dumps({"verdict": "supported", "claims": [
        {"text": done, "kind": "action", "source_id": "system:chief_actions", "quote": "records the gifts a person names"}]})
    verdict, _, reason = truth.assess_review(raw, done, sources)
    assert verdict == "unsupported" and "receipt" in reason


def test_the_source_reaches_the_review_for_this_logins_lane():
    reviewer = AsyncMock(return_value=json.dumps({"verdict": "supported", "claims": []}))

    async def one(scope):
        chief_areas.TURN.set(scope)
        return await truth.finalize_reply(None, HELD, ctx={}, view_detail="", taken=[],
                                          message="work on the offering", business_id="b", reviewer=reviewer)
    asyncio.run(one(None))
    sent = json.loads(reviewer.call_args.args[2][0]["content"])
    src = sent["sources"]["system:chief_actions"]
    assert src["kind"] == "capability" and "record_service_gifts" in src["text"]
    reviewer.reset_mock()
    asyncio.run(one(CARE))
    if reviewer.call_args:
        sent = json.loads(reviewer.call_args.args[2][0]["content"])
        assert "record_service_gifts" not in str(sent["sources"].get("system:chief_actions", {}))
