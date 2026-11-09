"""
church_history.py: Chief's church hand-offs, on the History page.

History is the audit log (audit_log.py). Chief's chat, its jobs and its
errands already wrote to it. The church's own hand-offs did not: a card
handed to a leader, the email telling them, the late chain above them, a
shared prayer request handed to a prayer leader, and the shepherds'
emails. So the pages' "it lists what it does on your History page" was
wider than the code (the 2026-11-08 review of the church home), and the
pages were narrowed to "what you ask of it". This puts those hand-offs on
History.

What a line may say. Any active seat reads History, a viewer included
(audit_log._require_ledger_read), and the church's own rules keep prayer
with the pastors and a card's words with the office. So a line here never
carries who a card or prayer is about, what they wrote, or a family's
name. It names the leader it went to (someone who holds a church role)
and the kind of card, and links the row by its id only.

Best-effort: never raises, and never stops or slows a hand-off. A False
return is logged by audit_log.record itself.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("church_history")

# Who it was: Chief (HistoryPanel shows actor_type 'chief' as "Chief").
ACTOR_ID = "church"

VERBS = (
    "church:card_handed",      # a card's follow-up given to a leader, or to the office
    "church:leader_told",      # the leader told it's theirs (or the office told they can't be)
    "church:follow_up_late",   # a step due or late: the leader nudged, then the chain above told
    "church:prayer_handed",    # a shared prayer request given to a prayer leader
    "church:prayer_late",      # a prayer leader nudged, or the chain above told
    "church:shepherd_email",   # a shepherd or pastor emailed about the families they care for
)


def card_words(card_name: Any) -> str:
    """'a Connect card', 'a Plan your visit card', never 'a card card'."""
    name = " ".join(str(card_name or "").split())[:60]
    if not name:
        return "a card"
    return f"a {name}" if name.lower().endswith("card") else f"a {name} card"


def note(business_id: Any, verb: str, summary: str, *, target_type: Optional[str] = None,
         target_id: Any = None, payload: Optional[Dict[str, Any]] = None) -> bool:
    """One History line for a hand-off Chief made. Never raises."""
    try:
        import audit_log
        return audit_log.record(
            str(business_id), actor_type="chief", actor_id=ACTOR_ID, verb=verb,
            summary=summary, target_type=target_type,
            target_id=str(target_id) if target_id else None,
            payload=payload or {}, source="church", authorized_by="church roles")
    except Exception:
        logger.info("church history line not written (%s)", verb, exc_info=True)
        return False
