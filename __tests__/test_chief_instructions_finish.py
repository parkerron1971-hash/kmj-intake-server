"""An instruction given to Chief finishes, or Chief says plainly why not.

Three walls seen in the conversation log on 2026-09-18, all on the
voice surface, all after the practitioner gave a clear instruction:

1. A held class-C action (create invoice, spoken) was reported with the
   MODEL-facing hold text read aloud: "Say back exactly what you are
   about to do... emit this same action again... Do NOT tell them it is
   done". The practitioner heard the stage directions.
2. "stop." after that hold drew "No action ran in this request. I
   couldn't verify my proposed answer. Would you like me to try again?"
   because the honest sentence "the $10 test invoice was never created
   or sent" was reviewed as an action claim with no write receipt.
3. A plain "can you create an invoice and text it?" was answered with
   "I couldn't verify that answer" because the offer "I'll create the
   invoice once you..." tripped the completion-claim detector.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from unittest.mock import AsyncMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos
import chief_truth as truth

_BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "type": "coach",
        "owner_id": "user-1", "settings": {}}


def _a_class_c_verb() -> str:
    import action_registry
    for verb, entry in action_registry.REGISTRY.items():
        if (entry.get("effect") == action_registry.WRITE
                and entry.get("reversibility") == "C"
                and not entry.get("bulk")):
            return verb
    raise AssertionError("no single-target class-C verb in the registry")


def _held(action=None):
    tv = cos._TURN_IS_VOICE.set(True)
    tc = cos._TURN_CONFIRMED.set(False)
    try:
        verdict, res = asyncio.run(cos._gate_class_c(None, _BIZ, _a_class_c_verb(), action or {}, 0))
    finally:
        cos._TURN_IS_VOICE.reset(tv)
        cos._TURN_CONFIRMED.reset(tc)
    assert verdict == "handled" and res["failed"] is True
    return res


# ── 1. the hold reads back in the practitioner's terms ─────────────────

def test_the_held_reply_never_reads_the_stage_directions_aloud():
    res = _held({"to": "Jessica McCloud", "amount": 10})
    spoken = cos._deterministic_fallback_reply([res])
    assert spoken == res["label"]
    for leak in ("emit this same action", "do not tell them", "say back exactly", "held for a spoken yes"):
        assert leak not in spoken.lower(), leak
    assert "Jessica McCloud" in spoken and "$10.00" in spoken
    assert "go ahead" in spoken and "send it" in spoken
    assert "nothing has run" in spoken.lower()
    # The model still gets its instructions, unchanged.
    assert "emit this same action again" in res["result"]


def test_a_hold_beside_a_real_failure_keeps_both_honest():
    res = _held({"to": "Jessica McCloud", "amount": 10})
    failed = {"type": "create_module_entry", "failed": True,
              "result": "Failed: I couldn't find that module.", "label": "Entry not saved"}
    spoken = cos._deterministic_fallback_reply([failed, res])
    assert "create module entry didn't go through" in spoken
    assert "couldn't find that module" in spoken
    assert res["label"] in spoken
    assert "emit this same action" not in spoken.lower()


def test_a_hold_beside_a_success_reads_the_success_then_the_hold():
    res = _held({"to": "Jessica McCloud", "amount": 10})
    ok = {"type": "create_note", "result": "saved", "label": "Note saved on Jessica McCloud"}
    spoken = cos._deterministic_fallback_reply([ok, res])
    assert spoken.startswith("Note saved on Jessica McCloud.")
    assert res["label"] in spoken
    assert "didn't go through" not in spoken


# ── 2. saying nothing happened is not a completion claim ───────────────

def _review(*claims):
    return json.dumps({"verdict": "unsupported", "claims": list(claims)})


def _claim(text, kind="action", source_id="", quote="", gap="no receipt"):
    claim = {"text": text, "kind": kind, "source_id": source_id, "quote": quote}
    if gap:
        claim["gap"] = gap
    return claim


def test_a_negated_action_sentence_is_the_execution_state():
    for text in ("The $10 test invoice for Jessica McCloud was never created or sent.",
                 "Nothing has gone out yet.", "I haven't sent anything.",
                 "No invoice was created.", "The text wasn't sent."):
        assert truth.is_non_execution_claim(text), text
    for text in ("Done. I've sent the invoice.", "Invoice created and sent to Jessica.",
                 "I've sent it, no problem."):
        assert not truth.is_non_execution_claim(text), text


def test_stop_after_a_hold_is_answered_not_walled():
    draft = "Okay, I've stopped. The $10 test invoice for Jessica McCloud was never created or sent."
    raw = _review(_claim("The $10 test invoice for Jessica McCloud was never created or sent."))
    reviewer = AsyncMock(return_value=raw)
    repairer = AsyncMock(side_effect=AssertionError("no repair needed"))
    result, meta = asyncio.run(truth.finalize_reply(None, draft, ctx={}, view_detail="", taken=[],
        message="stop.", business_id="biz", reviewer=reviewer, repairer=repairer,
        conversation_history=[{"role": "user", "content": "send a test invoice of $10 to Jessica"}]))
    assert result == draft
    assert meta["status"] == "supported" and "turn:execution" in meta["sources"]


def test_a_negated_sentence_cannot_hide_a_completed_write():
    # This turn DID send something; "nothing went out" would be a lie and
    # still needs the reviewer to cite the receipt.
    sources = {"result:0": {"kind": "receipt", "text": json.dumps({"type": "send_sms", "result": "sent"}), "complete": True}}
    verdict, _, reason = truth.assess_review(_review(_claim("Nothing has gone out yet.")),
                                             "Nothing has gone out yet.", sources)
    assert verdict == "unsupported" and "receipt" in reason
    # A failed receipt is not a write that went through.
    sources = {"result:0": {"kind": "receipt", "text": json.dumps({"type": "send_sms", "failed": True, "result": "Failed: offline"}), "complete": True}}
    verdict, _, _ = truth.assess_review(_review(_claim("Nothing has gone out yet.")),
                                        "Nothing has gone out yet.", sources)
    assert verdict == "supported"


def test_a_positive_action_claim_still_needs_its_receipt():
    result, meta = asyncio.run(truth.finalize_reply(None, "I texted your invoice.",
        ctx={}, view_detail="", taken=[], message="Text the invoice", business_id="biz",
        reviewer=AsyncMock(return_value=_review(_claim("I texted your invoice."))),
        repairer=AsyncMock(return_value="")))
    assert result == truth.NO_ACTION_REPLY and meta["status"] == "withheld"


# ── 3. an offer is not a completion claim ─────────────────────────────

def test_an_offer_hinged_on_a_go_ahead_is_not_a_completion_claim():
    for reply in ("Once you say go ahead, I'll create the invoice and text it to Jessica.",
                  "I can do that. Which invoice, and who should it go to? I'll create it when you confirm.",
                  "Want me to? If so, I'll add her as a contact first."):
        assert not truth.has_completion_claim(reply), reply


def test_a_stated_completion_is_still_a_completion_claim():
    for reply in ("I've created the invoice.", "Done. It's on its way.",
                  "I'll create the invoice now.", "The appointment is booked.",
                  "I've created the invoice, and once you confirm I'll send it."):
        assert truth.has_completion_claim(reply), reply


def test_a_capability_answer_flows_when_the_reviewer_is_unavailable():
    draft = ("Yes. Tell me who it's for and the amount, and once you say go ahead "
             "I'll create the invoice and text it to them.")
    result, meta = asyncio.run(truth.finalize_reply(None, draft, ctx={}, view_detail="", taken=[],
        message="can you create an invoice and send it by text?", business_id="biz",
        reviewer=AsyncMock(return_value="")))
    # An offer with nothing to check now flows on the fast lane without
    # waiting for the reviewer at all (2026-09-23); either way, it flows.
    assert result == draft and meta["status"] in ("unchecked", "fast")
