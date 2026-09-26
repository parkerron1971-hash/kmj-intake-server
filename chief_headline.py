"""
chief_headline.py — Haiku says the headline, Sonnet says the rest.

Kevin, 2026-09-25: "i can tell the difference of haiku and when sonnet 5
launches so can we give haiku more so it's more smooth." On a question the
practitioner heard a quick opener, then about nine seconds of silence while
Sonnet read the records and thought, then the answer.

Once the turn has read the business (the context every turn gathers
before its model call), Haiku writes the headline answer from those same
records — one sentence, two at most — and each sentence goes through the
turn's own sentence streamer: the deterministic prover the streaming lane
already uses (chief_truth.streamable_sentence: every figure and name in one
record, nothing claimed done, nothing about the business unproved). Only a
proven sentence is said. Sonnet is then told what was said, in the uncached
tail, and continues with the detail.

Only for a question that needs the records and asks for nothing to be done
(model_router), on a streamed turn, within HEADLINE_WAIT_S. Anything else —
no records that answer it ("NEED_MORE"), an unproven sentence, a slow model —
and the turn simply goes on as before. Switch: CHIEF_HEADLINE=off.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

import chief_models
import model_router as mr
import route_ledger

logger = logging.getLogger("chief_headline")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] headline: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

HEADLINE_WAIT_S = 1.8
EVIDENCE_CHARS = 14000
PER_SOURCE_CHARS = 4000

SYSTEM = """You are Chief, the chief of staff inside a small-business owner's app. The owner asked a question, and the records below are from their business.

Say the headline answer in ONE short sentence (two at most), using only these records: state the fact itself, with the exact figures (as digits), names and dates the records give. Each sentence is about ONE record (one person, one invoice, one booking) or one total the records state — when the answer is a list, lead with the biggest item or the total, never the whole list in one sentence. No "yes" or "no" in front of it, no "as of" date, no preamble, no advice, and nothing about anything being done or sent. The full answer follows yours, so do not try to cover everything.

If these records do not answer the question, reply exactly NEED_MORE."""

_KINDS = ("lookup", "general", "unknown", "followup")


def enabled() -> bool:
    if (os.environ.get("CHIEF_HEADLINE") or "on").strip().lower() in ("off", "0", "false", "no"):
        return False
    import chief_fast_track
    return chief_fast_track.enabled()


def eligible(message: str, prior_assistant: str = "", *, lane: str, is_greeting: bool,
             is_coach_mode: bool) -> bool:
    """A question about the records that asks for nothing to be done."""
    if not enabled() or is_greeting or is_coach_mode or lane not in ("chat", "voice"):
        return False
    if not mr.is_question(message):
        return False
    c = mr.score(message, prior_assistant)
    return c.needs_records and not c.needs_action and c.kind in _KINDS


def evidence_text(evidence: Dict[str, Dict[str, Any]], limit: int = EVIDENCE_CHARS) -> str:
    """Only the records the prover itself trusts (chief_truth._fast_evidence:
    the business's own records — never mail, texts, the web or memory), so
    nothing a stranger wrote can steer what is said before the review.
    evidence_for_review orders them lowest rank first, so this reads from
    the end."""
    import chief_truth
    parts: List[str] = []
    total = 0
    for sid, src in reversed(list((evidence or {}).items())):
        if not isinstance(src, dict) or not chief_truth._fast_evidence(sid, src):
            continue
        text = str(src.get("text") or "")[:PER_SOURCE_CHARS]
        if not text.strip() or total + len(text) > limit:
            continue
        parts.append(f"[{sid}]\n{text}")
        total += len(text)
    return "\n\n".join(parts)


def continuation_block(said: str) -> str:
    """The uncached tail that makes Sonnet go on from the headline."""
    said = (said or "").strip()
    if not said:
        return ""
    return (
        "\n\nTHE HEADLINE IS ALREADY SAID — the practitioner has just seen (and, on a "
        f"call, heard) the first sentence of your answer: «{said}»\n"
        "Continue with what they need next — the detail, the context, what it means for "
        "them — without repeating it. If the records show it is wrong or incomplete, say "
        "so plainly in your first sentence."
    )


class _TallyOnly:
    """stream_text bills its call to the request's route tally."""

    def __init__(self) -> None:
        self.tally = route_ledger.TALLY.get() or route_ledger.Tally()


async def say(message: str, streamer: Any, evidence: Dict[str, Dict[str, Any]], *,
              history: Optional[List[Dict[str, str]]] = None, voice: bool = False,
              business_id: Optional[str] = None, wait_s: float = HEADLINE_WAIT_S) -> str:
    """Stream Haiku's headline through the turn's sentence streamer. Returns
    what was said (proven sentences only) — "" when nothing was. The
    streamer is left open for the model call that follows."""
    import chief_fast_track as cft
    records = evidence_text(evidence)
    if not records or streamer is None or not getattr(streamer, "open", False):
        return ""
    before = streamer.text
    t0 = time.perf_counter()
    system = SYSTEM + ("\nThis is spoken aloud: short, plain words." if voice else "")
    messages = list(history or [])[-2:] + [{"role": "user", "content":
                                            f"RECORDS:\n{records}\n\nQUESTION: {message[:1500]}"}]
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    out: Dict[str, Any] = {}
    outcome = {"why": "said"}

    async def _run() -> None:
        head = ""
        written = ""
        decided = False
        # The main model starts when this ends, so it ends at the first
        # paragraph break: Haiku likes to go on into the whole list. Cut
        # here, not with a stop sequence — the API refuses a whitespace one.
        async for piece in cft.stream_text(system, messages, model=chief_models.model_for("fast"),
                                           max_tokens=90, rec=_TallyOnly(), endpoint="/chief/headline",
                                           units=0, business_id=business_id, out=out):
            if not decided:
                head += piece
                if len(head.strip()) < 10:
                    continue
                decided = True
                if head.lstrip().upper().startswith("NEED"):
                    outcome["why"] = "records do not answer it"
                    return
                piece = head
            both = written + piece
            cut = both.find("\n\n", len(written.rstrip()) if written.strip()
                            else len(both) - len(both.lstrip()))
            if cut >= 0:
                piece = (written + piece)[len(written):cut]
            written += piece
            streamer(piece)
            if not streamer.open:
                outcome["why"] = "a sentence the records do not prove"
                return
            if cut >= 0:
                break
        if not decided:
            if not head.strip() or head.lstrip().upper().startswith("NEED"):
                outcome["why"] = "records do not answer it"
                return
            streamer(head)
        # The last sentence ends the stream without trailing space; this
        # is what lets the streamer see it as whole.
        if streamer.open:
            streamer("\n")
        if not streamer.open:
            outcome["why"] = "a sentence the records do not prove"

    try:
        await asyncio.wait_for(_run(), timeout=wait_s)
    except asyncio.TimeoutError:
        outcome["why"] = "timeout"
    except Exception as e:  # pragma: no cover — never cost the turn
        outcome["why"] = f"error: {type(e).__name__}"
    said = streamer.text[len(before):]
    try:
        streamer.reopen()
    except Exception:  # pragma: no cover
        pass
    logger.info("[headline] %s: said=%d chars in %dms%s", outcome["why"], len(said.strip()),
                int((time.perf_counter() - t0) * 1000),
                f" ({out['error'][:60]})" if out.get("error") else "")
    return said
