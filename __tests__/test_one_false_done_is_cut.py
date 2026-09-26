"""The end-of-reply glitch, 2026-09-25 (Kevin: "seems like there was a
glitch at the end").

"You can put this in my calendar as well as set these in my notes." Chief
created three tasks and its reply ALSO said the plan was saved to Notes —
nothing was. The answer check rightly refused that false "done", but it
withheld the whole reply and delivered the bare receipt labels, which the
call read aloud: "check mark Task colon Chase overdue invoices plus check
beta client status due two thousand twenty-six…".

Now the false sentence is cut, the rest (re-checked) is delivered, and the
reply says the notes are not done. When nothing can be saved by cutting,
the receipts are said as a sentence, with the same honesty.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth

TAKEN = [
    {"type": "create_task", "result": "added",
     "label": "✅ Task: Chase overdue invoices + check beta client status — due 2026-09-26"},
    {"type": "create_task", "result": "added",
     "label": "✅ Task: Reach out to 4 stale leads (60-86 days cold) — due 2026-09-27"},
    {"type": "create_task", "result": "added",
     "label": "✅ Task: List Founders' Table cohort as a sellable offering — due 2026-09-28"},
]
MESSAGE = "You can put this in my calendar as well as set these in my notes."


def _run(reply, claims, verdict="unsupported"):
    raw = json.dumps({"verdict": verdict, "claims": claims})

    async def reviewer(*a, **k):
        return raw

    return asyncio.run(truth.finalize_reply(
        None, reply, ctx={}, view_detail="", taken=TAKEN, message=MESSAGE,
        business_id=None, reviewer=reviewer, repairer=None, budget_s=20.0))


def _receipt_quote(i):
    sources = truth.evidence_for_review({}, "", TAKEN)
    return json.loads(sources[f"result:{i}"]["text"])["label"]


def test_the_false_done_is_cut_and_said_as_not_done():
    reply = ("I've added the first three days to your calendar as tasks. "
             "I also saved the whole seven-day plan to your notes.")
    claims = [
        {"text": "I've added the first three days to your calendar as tasks", "kind": "action",
         "source_id": "result:0", "quote": _receipt_quote(0)},
        {"text": "saved the whole seven-day plan to your notes", "kind": "action",
         "source_id": "", "quote": "", "gap": "no save_note receipt"},
    ]
    text, grounding = _run(reply, claims)
    assert text.startswith("I've added the first three days to your calendar as tasks.")
    assert "saved the whole seven-day plan to your notes." not in text.split("This part didn't happen:")[0]
    assert "This part didn't happen: saved the whole seven-day plan to your notes." in text
    assert "✅" not in text and "Task:" not in text
    assert grounding["status"] == "trimmed"


def test_when_cutting_cannot_save_it_the_receipts_are_said_not_read():
    reply = "I've added all seven days to your calendar and saved the plan to your notes."
    claims = [{"text": "saved the plan to your notes", "kind": "action",
               "source_id": "", "quote": "", "gap": "no save_note receipt"}]
    text, grounding = _run(reply, claims)
    assert grounding["status"] == "receipts"
    assert text.startswith("I added three tasks: Chase overdue invoices + check beta client status, "
                           "due Saturday, September 26;")
    assert "and List Founders' Table cohort as a sellable offering, due Monday, September 28." in text
    assert text.endswith(truth._NOT_ALL_DONE)
    assert "✅" not in text and "2026-09" not in text


def test_a_false_done_with_nothing_written_is_still_withheld():
    """No write receipt at all: cutting cannot turn "I sent it" into an
    answer, and nothing done-sounding may survive a trim."""
    raw = json.dumps({"verdict": "unsupported", "claims": [
        {"text": "I sent the invoice to Maria", "kind": "action", "source_id": "", "quote": "",
         "gap": "no send receipt"}]})

    async def reviewer(*a, **k):
        return raw
    text, grounding = asyncio.run(truth.finalize_reply(
        None, "I sent the invoice to Maria. It's on its way.", ctx={}, view_detail="",
        taken=[], message="send Maria her invoice", business_id=None,
        reviewer=reviewer, repairer=None, budget_s=20.0))
    assert "I sent the invoice" not in text
    assert grounding["status"] in ("withheld", "unchecked", "trimmed") and grounding["status"] != "supported"


def test_the_failing_action_claim_is_named_in_the_reason():
    sources = truth.evidence_for_review({}, "", TAKEN)
    raw = json.dumps({"verdict": "unsupported", "claims": [
        {"text": "saved it to your notes", "kind": "action", "source_id": "", "quote": "",
         "gap": "none"}]})
    verdict, _, reason = truth.assess_review(raw, "I saved it to your notes.", sources)
    assert verdict == "unsupported"
    assert reason == truth.ACTION_WITHOUT_RECEIPT + " :: saved it to your notes"
