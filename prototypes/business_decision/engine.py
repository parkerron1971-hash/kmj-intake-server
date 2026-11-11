"""Read-only routing: learned intent + deterministic checks of supplied facts.

No network clients, credentials, booking mutations, or automatic sends.
`frontier` is a recommendation for the calling application, never an API call.
The context is supplied by a trusted adapter; this prototype uses fixtures only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata

from .model import Model

MAX_MESSAGE = 2000
GUARD = re.compile(
    r"\b(refund\w*|complain\w*|disput\w*|injur\w*|bleeding|emergency|lawyer|"
    r"chargeback\w*|discount\w*|exception\w*|angry|upset|unhappy|"
    r"ignore|override|system prompt|instructions|password\w*|secret\w*|"
    r"unless|instead|either|but|if)\b|\b(?:don't|do not|never|not)\s+(?:cancel|book|reschedule|move)",
    re.I,
)


@dataclass(frozen=True)
class Policy:
    min_score: float = 0.90
    min_margin: float = 0.50
    min_coverage: float = 0.65


def demo_context(business_id: str = "demo-salon") -> dict:
    """Entirely fictional; each call returns fresh data, not shared mutable state."""
    if business_id != "demo-salon":
        raise ValueError("Unknown demo business")
    return {"business_id": business_id, "source": "fictional_fixture",
            "facts_current": True, "hours": "Monday-Friday 9am-5pm; Saturday 10am-2pm; Sunday closed.",
            "price_list": "Haircut: $30. Beard trim: $15.",
            "booking": {"id": "demo-booking-1", "business_id": business_id},
            "available_slots": ["Friday 10am", "Friday 2pm"]}


class Engine:
    def __init__(self, model: Model, policy: Policy | None = None):
        self.model = model
        self.policy = policy or Policy()

    def decide(self, message: str, *, business_id: str, context: dict) -> dict:
        if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE:
            raise ValueError(f"message must contain 1-{MAX_MESSAGE} characters")
        if not isinstance(context, dict) or not business_id:
            raise ValueError("business_id and a context object are required")
        text = unicodedata.normalize("NFKC", message).replace("\u2019", "'")
        prediction = self.model.predict(text)
        result = {"route": "frontier", "intent": prediction["intent"], "reply": None,
                  "reason": "uncertain_intent", "model": prediction,
                  "read_only": True, "paid_calls": 0, "business_id": business_id}
        if context.get("business_id") != business_id:
            return {**result, "reason": "context_business_mismatch"}
        booking = context.get("booking")
        if booking and (not isinstance(booking, dict) or booking.get("business_id") != business_id):
            return {**result, "reason": "booking_business_mismatch"}
        if context.get("facts_current") is not True:
            return {**result, "reason": "facts_not_current"}
        if GUARD.search(text):
            return {**result, "reason": "complex_or_conditional_message"}
        if (prediction["intent"] == "complex" or prediction["score"] < self.policy.min_score
                or prediction["margin"] < self.policy.min_margin
                or prediction["known_word_fraction"] < self.policy.min_coverage):
            return result
        # A second recognizable intent is not silently dropped. This complements
        # the learned whole-message classifier; it is not an authorization check.
        clauses = re.split(r"\band\b|[;!?]|\.(?:\s|$)", text, flags=re.I)
        other_intents = {self.model.predict(clause)["intent"] for clause in clauses
                         if clause.strip() and self.model.predict(clause)["score"] >= self.policy.min_score}
        if len(other_intents) > 1:
            return {**result, "reason": "multiple_intents"}
        intent = prediction["intent"]
        if intent in ("hours", "pricing"):
            key = "hours" if intent == "hours" else "price_list"
            fact = context.get(key)
            if not isinstance(fact, str) or not fact.strip():
                return {**result, "reason": "missing_business_fact"}
            return {**result, "route": "routine", "reason": "answer_from_supplied_facts", "reply": fact}
        if intent == "booking":
            return {**result, "route": "ask", "reason": "booking_details_required",
                    "reply": "Which service and appointment time would you like?"}
        if intent == "reschedule":
            if not booking:
                return {**result, "route": "ask", "reason": "booking_identity_required",
                        "reply": "Which appointment would you like to reschedule?"}
            # The adapter must supply slots already scoped to the requested day.
            # Never infer a date, fee waiver or completed booking from model intent.
            slots = context.get("available_slots")
            if not isinstance(slots, list) or not slots or any(not isinstance(s, str) for s in slots):
                return {**result, "reason": "availability_lookup_required"}
            return {**result, "route": "ask", "reason": "slot_selection_required",
                    "reply": "Available options: " + "; ".join(slots[:5]) + ". Which works for you?"}
        if intent == "cancel":
            return {**result, "route": "ask", "reason": "cancellation_review_required",
                    "reply": "Which appointment should we review for cancellation? No booking has been changed."}
        return result

    def settings(self) -> dict:
        return asdict(self.policy)
