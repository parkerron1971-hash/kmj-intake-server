"""
concierge_qualify.py — the Site Concierge's LEAD QUALIFICATION rubric.

WHY THIS EXISTS
  Until 2026-09-05 the concierge captured a lead and stopped: a name, an
  email, and whatever the visitor typed into the fallback form. The
  practitioner then read the transcript to work out whether the person
  wanted a $40 trim next Tuesday or was "just looking". This module does
  that reading, once, the moment the lead lands — from the conversation
  the visitor already had — and hands the practitioner a tier (hot /
  warm / cold), the reasons in words, and the answers to the questions
  they asked the concierge to ask.

TWO PASSES, LIKE lead_scoring
  1. The RUBRIC (pure, deterministic, never raises, no network). Signals
     are behaviours, not verticals — a barber's hot lead and a lawyer's
     hot lead both named a service, gave a way to be reached, and said
     when. This is the pass the tests pin.
  2. EXTRACTION (optional, one cheap model call, failure-tolerant). The
     practitioner's qualifying questions are free text ("What are you
     hoping to fix?"); matching a visitor's answer to a question is a
     language problem. The model reads the SAME visitor turns the
     concierge already saw — nothing new enters its world — and returns
     JSON. When it fails, the rubric's verdict stands and `answers` is
     empty. The tier NEVER comes from the model; only the answers do.

THIS IS NOT CHIEF. Zero imports from Chief action modules. lead_scoring
is a shared rubric library (the contact-form scorer), not a Chief verb.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import lead_scoring

logger = logging.getLogger("concierge_qualify")

MAX_QUESTIONS = 5
MAX_QUESTION_CHARS = 160
MAX_ANSWER_CHARS = 300

# ─── the signals ──────────────────────────────────────────────────────
# Weights sum past 100 on purpose; the total is clamped. Calibration:
# named a service + said when + reachable by mail AND phone = 70 → HOT,
# exactly at the line: that person is a booking waiting for a call.
# Add the practitioner's questions answered and it is 92. Someone who
# asked one price question and left an email is 8 + 12 = 20 → COLD,
# correctly: curiosity, not intent.

W_NAMED_SERVICE = 26     # mentioned an offering the business actually sells
W_TIMING = 18            # said when (urgency words or a day/date)
W_ASKED_PRICE = 8        # asked what it costs — shopping, not browsing
W_PHONE = 14             # can be reached by voice (lead_scoring.W_PHONE)
W_EMAIL = 12             # can be reached by mail
W_ANSWERED_ALL = 22      # answered every qualifying question
W_ANSWERED_SOME = 10     # answered at least half
W_ENGAGED = 8            # three or more visitor turns: they stayed
W_BOOKED = 70            # picked a time in the chat — HOT on its own, always

HOT = 70
WARM = 40

PRICE_RE = re.compile(r"\b(price|pricing|cost|costs|how much|rate|rates|fee|fees|quote|estimate)\b",
                      re.IGNORECASE)
# A concrete day or date, on top of lead_scoring.URGENCY (asap/today/…).
WHEN_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|next week|"
    r"this weekend|next month|morning|afternoon|evening|"
    r"\d{1,2}(?::\d{2})?\s?(?:am|pm)|\d{1,2}/\d{1,2})\b",
    re.IGNORECASE)


@dataclass
class Qualification:
    tier: str                       # hot | warm | cold
    score: int
    signals: List[str] = field(default_factory=list)
    answers: Dict[str, str] = field(default_factory=dict)
    service: Optional[str] = None
    booked: bool = False
    extracted: bool = False         # the model pass contributed answers

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "score": self.score,
            "signals": list(self.signals),
            "answers": dict(self.answers),
            "service": self.service,
            "booked": self.booked,
            "extracted": self.extracted,
        }


def tier_for(score: int) -> str:
    return "hot" if score >= HOT else ("warm" if score >= WARM else "cold")


def clean_questions(raw: Any) -> List[str]:
    """The practitioner's qualifying questions, as the settings store
    them: ≤5 non-empty strings, ≤160 chars, order kept, blanks dropped."""
    out: List[str] = []
    for item in (raw or []) if isinstance(raw, list) else []:
        q = str(item or "").strip()[:MAX_QUESTION_CHARS]
        if q and q not in out:
            out.append(q)
        if len(out) >= MAX_QUESTIONS:
            break
    return out


def visitor_text(transcript: List[Dict[str, Any]]) -> str:
    """Only what the VISITOR said, joined. The concierge's own replies
    must never count as evidence of the visitor's intent."""
    parts = [str(m.get("body") or "").strip() for m in (transcript or [])
             if m.get("role") == "visitor"]
    return "\n".join(p for p in parts if p)


def _named_service(haystack: str, offerings: List[Dict[str, Any]]) -> Optional[str]:
    """The first offering whose name (or a distinctive word of it)
    appears in the visitor's words. Whole-word, case-insensitive; words
    shorter than four letters are too common to count ("cut" is in
    "haircut" and in "shortcut")."""
    low = haystack.lower()
    for o in offerings or []:
        name = str((o or {}).get("name") or "").strip()
        if not name:
            continue
        if re.search(r"\b" + re.escape(name.lower()) + r"\b", low):
            return name
    for o in offerings or []:
        name = str((o or {}).get("name") or "").strip()
        for word in re.findall(r"[a-z][a-z'-]{3,}", name.lower()):
            if word in ("with", "from", "your", "session", "package", "service"):
                continue
            if re.search(r"\b" + re.escape(word) + r"\b", low):
                return name
    return None


def qualify(transcript: List[Dict[str, Any]], *,
            questions: List[str],
            offerings: List[Dict[str, Any]],
            answers: Optional[Dict[str, str]] = None,
            email: str = "", phone: str = "",
            extra_text: str = "",
            booked: bool = False,
            extracted: bool = False) -> Qualification:
    """The deterministic pass. Pure — no network, never raises.

    `answers` come from extract_answers() (or are empty); `extra_text` is
    the lead form's free message, which counts as visitor words too.
    """
    said = visitor_text(transcript)
    if extra_text:
        said = (said + "\n" + str(extra_text)).strip()
    answers = {k: v for k, v in (answers or {}).items() if str(v or "").strip()}
    signals: List[str] = []
    total = 0

    if booked:
        total += W_BOOKED
        signals.append("booked a time in the chat")

    service = _named_service(said, offerings)
    if service:
        total += W_NAMED_SERVICE
        signals.append(f"asked about {service}")

    if lead_scoring.URGENCY.search(said) or WHEN_RE.search(said):
        total += W_TIMING
        signals.append("said when")

    if PRICE_RE.search(said):
        total += W_ASKED_PRICE
        signals.append("asked about price")

    if email and lead_scoring.EMAIL_RE.match(email.strip()):
        total += W_EMAIL
        signals.append("gave a usable email")
    if str(phone or "").strip():
        total += W_PHONE
        signals.append("gave a phone number")

    if questions:
        answered = sum(1 for q in questions if str(answers.get(q) or "").strip())
        if answered and answered >= len(questions):
            total += W_ANSWERED_ALL
            signals.append("answered every qualifying question")
        elif answered * 2 >= len(questions) and answered > 0:
            total += W_ANSWERED_SOME
            signals.append(f"answered {answered} of {len(questions)} qualifying questions")

    turns = sum(1 for m in (transcript or []) if m.get("role") == "visitor")
    if turns >= 3:
        total += W_ENGAGED
        signals.append(f"stayed for {turns} messages")

    if not signals:
        signals.append("left only their details")

    score = max(0, min(100, total))
    return Qualification(tier=tier_for(score), score=score, signals=signals,
                         answers={q: str(a)[:MAX_ANSWER_CHARS] for q, a in answers.items()},
                         service=service, booked=booked, extracted=extracted)


# ─── pass 2: answer extraction (optional, model, failure-tolerant) ────

EXTRACT_SYSTEM = (
    "You read a short website chat between a visitor and a business's "
    "assistant. Answer ONLY from what the VISITOR said. For each question "
    "the business wants answered, give the visitor's answer in their own "
    "words (short), or null if they never said. Never guess, never "
    "invent. Reply with ONE JSON object: "
    '{"answers": {"<question>": "<answer or null>", ...}}')


def _extract_payload(questions: List[str], transcript: List[Dict[str, Any]],
                     extra_text: str = "") -> str:
    lines = []
    for m in (transcript or []):
        role = "Visitor" if m.get("role") == "visitor" else "Assistant"
        body = str(m.get("body") or "").strip()
        if body:
            lines.append(f"{role}: {body[:600]}")
    if extra_text:
        lines.append(f"Visitor (lead form): {str(extra_text)[:600]}")
    chat = "\n".join(lines)[-6000:]
    return ("QUESTIONS:\n" + "\n".join(f"- {q}" for q in questions)
            + "\n\nCHAT:\n" + chat)


def _parse_answers(raw: str, questions: List[str]) -> Dict[str, str]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return {}
    got = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(got, dict):
        return {}
    out: Dict[str, str] = {}
    for q in questions:
        v = got.get(q)
        if isinstance(v, str) and v.strip() and v.strip().lower() not in ("null", "none", "n/a"):
            out[q] = v.strip()[:MAX_ANSWER_CHARS]
    return out


async def extract_answers(questions: List[str], transcript: List[Dict[str, Any]],
                          *, extra_text: str = "", model: str,
                          business_id: str = "") -> Optional[Dict[str, str]]:
    """One small model call. Returns the answers dict, or None when the
    model could not be reached (the caller records `extracted=False`).
    Never raises."""
    if not questions:
        return {}
    try:
        import httpx
        import llm_call
        if not llm_call.api_key():
            return None
        payload = {
            "model": model,
            "max_tokens": 400,
            "temperature": 0,
            "system": EXTRACT_SYSTEM,
            "messages": [{"role": "user",
                          "content": _extract_payload(questions, transcript, extra_text)}],
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await llm_call.apost(client, payload, task="concierge_qualify")
        if resp.status_code != 200:
            logger.warning("[concierge_qualify] model %s: %s",
                           resp.status_code, resp.text[:200])
            return None
        return _parse_answers(llm_call.text_of(resp.json()), questions)
    except Exception as e:
        logger.warning("[concierge_qualify] extraction failed: %s", e)
        return None


def describe(q: Qualification) -> str:
    """One line for a notification body: 'HOT — asked about Deep Tissue
    Massage; said when; gave a phone number'."""
    label = q.tier.upper()
    return f"{label} — " + "; ".join(q.signals[:4])
