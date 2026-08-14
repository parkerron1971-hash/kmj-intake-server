"""
lead_scoring.py — one score, every door.

WHY THIS EXISTS
═══════════════════════════════════════════════════════════════════════
`contacts.lead_score` used to be written in exactly one place in the
whole backend — intake_endpoint, the embeddable form. Every reader
gated on it therefore only ever saw intake-form leads:

    notification_engine  hot-lead urgent alert   (lead_score >= 70)
    contract_agent       proposal candidates     (lead_score >= 60)
    ContactsList.tsx     the "Hot Leads" list    (lead_score >= 80)
    chief_of_staff       Chief's daily briefing  (a fourth threshold)

Leads arriving through the composed site's contact form, the site
concierge or the booking widget carried a null score, so they were
invisible to all four. The "Hot Leads" list rendered empty and read as
a fact. This module makes the score a property of BEING a lead rather
than a property of having arrived through one particular form.

THE RUBRIC IS VERTICAL-NEUTRAL
═══════════════════════════════════════════════════════════════════════
The scorer it replaces enumerated `warm_welcome (church/ministry
visitor)` and `discovery_invite (coaching/consulting prospect)` — a
lookup table covering two of seven verticals, leaving a barber, an
attorney and a contractor with no bucket. What follows is named,
weighted SIGNALS instead. "They told us what they need", "we can
actually reach them", "they said it was urgent" mean the same thing in
every trade.

TWO PASSES, AND THE FIRST ONE ALWAYS RUNS
═══════════════════════════════════════════════════════════════════════
    1. score_lead()      deterministic, no I/O, no spend. ALWAYS runs.
                         lead_score is therefore never null and every
                         reader above works with the AI switched off.
    2. refinement        optional Haiku pass, bounded to +/-REFINE_BAND
                         points, behind spend_guard, and only when
                         there is enough free text to be worth reading.

The refinement can only nudge. A capture path that loses its Anthropic
key degrades to a slightly blunter score, never to a null one.
"""
from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("lead_scoring")

# Cheap by design: this is a triage pass on an anonymous endpoint, not a
# thinker. Same model the concierge and the ledger navigator use.
REFINE_MODEL = os.environ.get("LEAD_SCORE_MODEL", "claude-haiku-4-5-20251001")

# How far the AI may move the deterministic score in either direction.
# Narrow on purpose — the rubric is the instrument, the model is a
# second opinion on the prose, and a model having a bad day must not be
# able to turn a well-qualified lead cold.
REFINE_BAND = 25

# The refinement only pays for itself when there is prose to read.
REFINE_MIN_FREE_TEXT = 40

# Background refinement runs here so a visitor's form submit never waits
# on an LLM. Bounded: an unbounded thread-per-submission would be its
# own denial-of-service under a spam burst.
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lead-score")


# ─── field classification ─────────────────────────────────────────────
# Submissions are free-form dicts built by the practitioner in the form
# builder, so the rubric classifies keys by meaning rather than reading
# a fixed schema.

IDENTITY_KEYS = {
    "name", "full_name", "fullname", "first_name", "firstname", "fname",
    "last_name", "lastname", "lname", "email", "email_address", "e_mail",
    "phone", "phone_number", "telephone", "tel", "mobile", "cell",
}

ORG_KEYS = {
    "organization", "organisation", "org", "company", "company_name",
    "business", "business_name", "church", "ministry", "firm", "practice",
    "role", "title", "job_title", "position",
}

# Honeypot names the intake door drops on. Never scored, never counted
# toward completeness — they are supposed to be empty.
HONEYPOT_KEYS = {"_hp", "website_url", "company_url", "fax"}

TIME_KEYS = {
    "date", "time", "appointment", "appointment_time", "slot",
    "preferred_time", "preferred_date", "scheduled_for", "availability",
    "when",
}

# Urgency is a word list rather than a per-vertical table because
# "I need this now" reads the same to a barber and to a law firm. Kept
# deliberately tight: "this month" and "no rush" are timeline-select
# options that do NOT mean urgent.
URGENCY = re.compile(
    r"\b(asap|as soon as possible|urgent(?:ly)?|emergency|immediately|"
    r"right away|today|tonight|tomorrow|this week|by (?:friday|monday|"
    r"tuesday|wednesday|thursday|saturday|sunday)|deadline|time[- ]"
    r"sensitive|last minute)\b",
    re.IGNORECASE,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


# ─── the signals ──────────────────────────────────────────────────────
# (key, points, human-readable reason). Weights sum past 100 on purpose;
# the total is clamped. Nothing here names a vertical.

W_EMAIL = 20            # we can reach them by mail
W_PHONE = 14            # we can reach them by voice
W_NEED_STATED = 26      # they said what they want, in their own words
W_NEED_NAMED = 10       # ...briefly
W_AT_LENGTH = 8         # ...at length: effort is intent
W_COMPLETE_MOST = 12    # answered nearly everything asked
W_COMPLETE_HALF = 6

# Calibration: reachable by both channels + a real description of the
# problem + answered everything = 72, i.e. just into the "high" band.
# That combination IS a lead worth calling today, and the rubric has to
# say so without needing urgency words or a 200-word essay on top.
AT_LENGTH_CHARS = 180

# Completeness is meaningless on a form that asked one question.
# Without this floor, "name only" on a name-only form scores as though
# the person answered everything.
MIN_FIELDS_FOR_COMPLETENESS = 3
W_IDENTIFIED = 8        # named their org / role
W_URGENT = 12           # said it was time-sensitive
W_PICKED_TIME = 15      # committed to a slot
W_CONVERSED = 10        # talked to the concierge before leaving details

SOURCE_SIGNALS = {
    "booking_widget": (W_PICKED_TIME, "picked a time"),
    "site_concierge": (W_CONVERSED, "talked with the site concierge first"),
}


@dataclass
class LeadScore:
    """The outcome of a scoring pass. `signals` is the audit trail — the
    reason a number is what it is, in words a practitioner can read."""
    score: int
    signals: List[str] = field(default_factory=list)
    priority: str = "medium"
    response_type: str = "answer_then_offer"
    reasoning: str = ""
    refined: bool = False
    model: Optional[str] = None

    def as_event_data(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "priority": self.priority,
            "signals": self.signals,
            "response_type": self.response_type,
            "reasoning": self.reasoning,
            "refined": self.refined,
            "model": self.model,
        }


def priority_for(score: int) -> str:
    return "high" if score >= 70 else ("medium" if score >= 40 else "low")


# ─── pass 1: the rubric ───────────────────────────────────────────────

def _classify(submission: Dict[str, Any]) -> Dict[str, Any]:
    """Split a free-form submission into the buckets the rubric weighs."""
    free_text: List[str] = []
    answered = 0
    offered = 0
    org_given = False
    time_given = False
    all_values: List[str] = []

    for raw_key, value in (submission or {}).items():
        key = str(raw_key).strip().lower()
        if key in HONEYPOT_KEYS:
            continue
        offered += 1
        if value is None:
            continue
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        text = text.strip()
        if not text or text.lower() in ("false", "none", "null", "[]", "{}"):
            continue
        answered += 1
        all_values.append(text)

        if key in IDENTITY_KEYS:
            continue
        if key in ORG_KEYS:
            org_given = True
            continue
        if key in TIME_KEYS:
            time_given = True
            continue
        free_text.append(text)

    return {
        "free_text": " ".join(free_text),
        "answered": answered,
        "offered": offered,
        "org_given": org_given,
        "time_given": time_given,
        "haystack": " ".join(all_values),
    }


def score_lead(submission: Dict[str, Any], *, source: str = "",
               email: str = "", phone: str = "") -> LeadScore:
    """The deterministic pass. Pure — no network, no spend, never raises.

    `email`/`phone` are passed separately because the capture paths have
    already normalized them; a submission dict may spell the keys any
    way the practitioner typed them into the form builder.
    """
    parts = _classify(submission)
    signals: List[str] = []
    total = 0

    if email and EMAIL_RE.match(email.strip()):
        total += W_EMAIL
        signals.append("gave a usable email")
    if str(phone or "").strip():
        total += W_PHONE
        signals.append("gave a phone number")

    free_len = len(parts["free_text"])
    if free_len >= REFINE_MIN_FREE_TEXT:
        total += W_NEED_STATED
        signals.append("described what they need")
        if free_len >= AT_LENGTH_CHARS:
            total += W_AT_LENGTH
            signals.append(f"wrote at length ({free_len} characters)")
    elif free_len > 0:
        total += W_NEED_NAMED
        signals.append("named what they need, briefly")

    if parts["offered"] >= MIN_FIELDS_FOR_COMPLETENESS:
        ratio = parts["answered"] / parts["offered"]
        if ratio >= 0.8:
            total += W_COMPLETE_MOST
            signals.append("answered nearly every question")
        elif ratio >= 0.5:
            total += W_COMPLETE_HALF
            signals.append("answered about half the questions")

    if parts["org_given"]:
        total += W_IDENTIFIED
        signals.append("identified their organization or role")

    if URGENCY.search(parts["haystack"]):
        total += W_URGENT
        signals.append("signalled urgency")

    bonus = SOURCE_SIGNALS.get(source)
    if bonus:
        total += bonus[0]
        signals.append(bonus[1])
    elif parts["time_given"]:
        total += W_PICKED_TIME
        signals.append("proposed a time")

    if not signals:
        signals.append("left only a name")

    score = max(0, min(100, total))
    return LeadScore(
        score=score,
        signals=signals,
        priority=priority_for(score),
        response_type=_response_type_for(score, parts, source),
        reasoning="; ".join(signals),
    )


def _response_type_for(score: int, parts: Dict[str, Any],
                       source: str = "") -> str:
    """What KIND of reply this submission wants.

    Deliberately not a vertical map. A church visitor and a new gym
    member both want `welcome`; a consulting prospect and a roofing
    estimate both want `book_time`. The shape of the ask decides, not
    the trade.
    """
    if parts["time_given"] or source == "booking_widget":
        return "book_time"
    if score >= 70:
        return "book_time"
    if parts["free_text"]:
        return "answer_then_offer"
    if score < 40:
        return "nurture"
    return "welcome"


# ─── pass 2: the refinement ───────────────────────────────────────────

REFINE_SYSTEM = """You are triaging one inbound enquiry for a small business.

A deterministic rubric has already scored it on things that can be
counted: contactability, completeness, effort, urgency. You are reading
the ONE thing it cannot read — what the person actually wrote.

Adjust the score by at most {band} points in either direction, and only
for a reason that lives in the prose. Move it UP for a specific,
concrete, ready-to-act ask. Move it DOWN for vagueness, a sales pitch
aimed at the business, an obvious mis-send, or a tyre-kick.

Say nothing about the trade the business is in. A plumber's "my
basement is flooding" and a lawyer's "I was served yesterday" are the
same signal: this person has an urgent, specific problem.

RESPOND ONLY WITH VALID JSON:
{{"delta": -10, "reasoning": "one plain sentence a busy owner can read",
  "response_type": "welcome|book_time|answer_then_offer|nurture"}}"""

RESPONSE_TYPES = {"welcome", "book_time", "answer_then_offer", "nurture"}


def _submission_digest(submission: Dict[str, Any], limit: int = 1800) -> str:
    lines = []
    for k, v in (submission or {}).items():
        key = str(k).strip().lower()
        if key in HONEYPOT_KEYS or v in (None, "", False):
            continue
        text = v if isinstance(v, str) else json.dumps(v, default=str)
        lines.append(f"- {k}: {str(text)[:400]}")
    return "\n".join(lines)[:limit]


def refine(base: LeadScore, submission: Dict[str, Any], *,
           business_id: Optional[str] = None,
           business_name: str = "", business_type: str = "") -> LeadScore:
    """Second opinion on the prose. Returns `base` UNCHANGED on any
    failure — no key, over budget, bad JSON, HTTP error. A refinement
    that cannot run is not an error condition, it is the normal
    degraded path."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return base
    free_text = _classify(submission)["free_text"]
    if len(free_text) < REFINE_MIN_FREE_TEXT:
        return base

    try:
        import spend_guard
        if spend_guard.over_budget(business_id):
            logger.info("[lead_scoring] refinement skipped — over budget")
            return base
    except Exception:
        pass  # a missing/broken guard must not block the scoring path

    try:
        import llm_call
        resp = llm_call.post(
            {
                "model": REFINE_MODEL,
                "max_tokens": 300,
                "system": REFINE_SYSTEM.format(band=REFINE_BAND),
                "messages": [{
                    "role": "user",
                    "content": (
                        f"Business: {business_name or 'a small business'}"
                        f"{f' ({business_type})' if business_type else ''}\n"
                        f"Rubric score: {base.score} "
                        f"({', '.join(base.signals)})\n\n"
                        f"What they submitted:\n"
                        f"{_submission_digest(submission)}"
                    ),
                }],
            },
            task="lead_scoring",
        )
        if resp.status_code >= 400:
            logger.warning("[lead_scoring] refine HTTP %s", resp.status_code)
            return base
        raw = llm_call.text_of(resp.json()).strip()
    except Exception as e:
        logger.warning("[lead_scoring] refine failed: %s", e)
        return base

    parsed = _parse_json(raw)
    if not parsed:
        return base

    try:
        delta = int(parsed.get("delta") or 0)
    except (TypeError, ValueError):
        delta = 0
    delta = max(-REFINE_BAND, min(REFINE_BAND, delta))
    score = max(0, min(100, base.score + delta))

    rtype = str(parsed.get("response_type") or "").strip()
    reasoning = str(parsed.get("reasoning") or "").strip()[:400]

    signals = list(base.signals)
    if delta:
        signals.append(f"read as {'stronger' if delta > 0 else 'weaker'} "
                       f"than the rubric ({delta:+d})")

    return LeadScore(
        score=score,
        signals=signals,
        priority=priority_for(score),
        response_type=rtype if rtype in RESPONSE_TYPES else base.response_type,
        reasoning=reasoning or base.reasoning,
        refined=True,
        model=REFINE_MODEL,
    )


def _parse_json(raw: str) -> Dict[str, Any]:
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        out = json.loads(clean)
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        start, end = clean.find("{"), clean.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                out = json.loads(clean[start:end])
                return out if isinstance(out, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}


# ─── storage ──────────────────────────────────────────────────────────

def store(business_id: str, contact_id: str, result: LeadScore,
          source: str = "") -> bool:
    """Write the score to the contact and drop the reasoning on the
    spine. Best-effort: a scoring failure must never break a capture.

    The trail goes to `events`, NOT into contacts.metadata — patching a
    JSON blob read-modify-write would race the capture path that is
    still assembling that same blob, and silently drop whichever keys
    lost the race.
    """
    if not business_id or not contact_id:
        return False

    # HIGH-WATER MARK, not last-reading. lead_score answers "how
    # promising is this prospect", which is a property of their best
    # enquiry — someone who wrote three detailed paragraphs last week
    # and "any update?" today has not become a colder lead. Storing the
    # latest reading would let a terse follow-up demote them out of the
    # Hot Leads list, which is the opposite of what a follow-up means.
    ok = False
    previous: Optional[int] = None
    try:
        import sb_clients
        rows = sb_clients.sb_get_as_service(
            f"/contacts?id=eq.{contact_id}&business_id=eq.{business_id}"
            f"&select=lead_score&limit=1") or []
        if rows and rows[0].get("lead_score") is not None:
            previous = int(rows[0]["lead_score"])
        effective = max(result.score, previous) if previous is not None else result.score
        if previous is None or effective != previous:
            sb_clients.sb_patch_as_service(
                f"/contacts?id=eq.{contact_id}&business_id=eq.{business_id}",
                {"lead_score": effective})
        ok = True
    except Exception as e:
        logger.warning("[lead_scoring] score write failed for %s: %s",
                       contact_id, e)

    try:
        import event_spine
        data = dict(result.as_event_data(), source=source)
        if previous is not None:
            data["previous_score"] = previous
        event_spine.emit("lead_scored", business_id, data,
                         contact_id=contact_id, source=source or "lead_scoring")
    except Exception as e:
        logger.warning("[lead_scoring] spine emit failed: %s", e)
    return ok


def score_and_store(business_id: str, contact_id: str,
                    submission: Dict[str, Any], *, source: str = "",
                    email: str = "", phone: str = "",
                    business_name: str = "", business_type: str = "",
                    refine_with_ai: bool = True) -> LeadScore:
    """Rubric, then optional refinement, then persist. Synchronous."""
    result = score_lead(submission, source=source, email=email, phone=phone)
    if refine_with_ai:
        result = refine(result, submission, business_id=business_id,
                        business_name=business_name,
                        business_type=business_type)
    store(business_id, contact_id, result, source=source)
    return result


def score_in_background(business_id: str, contact_id: str,
                        submission: Dict[str, Any], **kwargs) -> None:
    """Fire-and-forget for the capture paths a visitor is waiting on.

    The visitor's form submit must not wait on an LLM round trip, and a
    slow score is worth far less than a fast page. Nothing downstream
    reads the score inside the request, so there is nothing to await.

    LEAD_SCORING_MODE controls dispatch:
      unset   pool     production — a worker thread, request returns now
      "sync"  inline   deterministic; what the wiring tests assert on
      "off"   skip     unit tests, which must never touch the network
    """
    def _run():
        try:
            score_and_store(business_id, contact_id, submission, **kwargs)
        except Exception as e:
            logger.warning("[lead_scoring] background scoring failed "
                           "for %s: %s", contact_id, e)

    mode = (os.environ.get("LEAD_SCORING_MODE") or "").strip().lower()
    if mode == "off":
        return
    if mode == "sync":
        _run()
        return
    try:
        _POOL.submit(_run)
    except Exception as e:      # pool shutting down mid-deploy
        logger.warning("[lead_scoring] could not queue scoring: %s", e)
