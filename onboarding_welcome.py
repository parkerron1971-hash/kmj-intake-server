"""
onboarding_welcome.py — the welcome note is not a draft waiting on anyone.

Onboarding (the frontend's OnboardingFlow) used to insert one agent_queue
row for every new business: agent 'system', status 'draft', subject
"Welcome to The Solutionist System, <name>!". It sits in the draft queue
like work, so everything that counts drafts counted it. Chief's first
greeting to a brand-new practitioner read its daily priorities ("1
waiting for your review"), followed the greeting rule "if there are
pending drafts, mention the count", and opened by pointing a new person
at a system note. The morning brief said "1 draft waiting" the next day.

The frontend stops creating the row; businesses that already have one
keep it. Every backend read that COUNTS or SHOWS drafts filters it out
with this module, and the filter is deliberately exact: both columns,
both values, the same pair the frontend uses. A real draft from any
agent, or a system row with any other reasoning, is never hidden.

Nothing is deleted or rewritten. The row stays in the table and in the
Approvals page; it just stops being counted as work.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

AGENT = "system"
REASONING = "Standard welcome message created at onboarding."

# Add to a PostgREST select so a row can be recognised. `ai_reasoning` is
# not otherwise read by the callers, so without_welcome drops it again.
SELECT_COLUMNS = "agent,ai_reasoning"


def is_welcome(row: Any) -> bool:
    """True only for the onboarding welcome row: agent 'system' AND the
    onboarding reasoning, compared exactly."""
    return (isinstance(row, dict)
            and row.get("agent") == AGENT
            and row.get("ai_reasoning") == REASONING)


def without_welcome(rows: Optional[List[Dict[str, Any]]], *,
                    keep_reasoning: bool = False) -> Optional[List[Dict[str, Any]]]:
    """`rows` minus the welcome row.

    None stays None: a failed read is not an empty queue, and callers that
    tell the two apart keep doing so. `ai_reasoning`, fetched only to
    recognise the row, is dropped from the rows kept unless the caller
    selected it for its own use — it is agent-written prose and has no
    business riding into a prompt or a review because of this filter.
    """
    if rows is None:
        return None
    if not isinstance(rows, list):
        return rows
    kept: List[Dict[str, Any]] = []
    for row in rows:
        if is_welcome(row):
            continue
        if not keep_reasoning and isinstance(row, dict) and "ai_reasoning" in row:
            row = {k: v for k, v in row.items() if k != "ai_reasoning"}
        kept.append(row)
    return kept
