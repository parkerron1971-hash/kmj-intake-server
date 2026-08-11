"""mailbox_policy.py — the single definition of what Chief may read.

WHY THIS IS ITS OWN MODULE
  The rule was written once in chief_of_staff (the gate that filters the
  prompt) and then approximated a second time in the Email Hub, which
  labelled each message "Chief can read" / "Not shown to Chief" using
  the stored contact_id.

  Those two answers agree right up until they don't. contact_id is
  resolved once, when the message is ingested. The gate matches the
  sender's address against the CURRENT contact list on every turn. So
  the moment someone emails you and then becomes a contact, the gate
  starts letting their earlier mail through while the Hub still says
  "Not shown to Chief" — a label whose entire job is explaining the rule,
  quietly contradicting it.

  A stored proxy for a live rule is a bug with a delay on it. One
  definition, imported by both callers, is the fix.

WHAT THE RULE IS
  Mail that came back through our own inbound path is provoked mail: we
  sent first, so the sender set is bounded by who we mailed. Mail from a
  connected mailbox or a forwarding rule has no such bound — every
  newsletter, cold pitch and phishing attempt arrives the same way, and
  some of that text is written to read as an instruction to an agent
  holding write verbs.

  So unsolicited mail is prompt-eligible only when the sender is already
  a contact. Everything else is stored and shown to the practitioner,
  and never handed to the model.

  Storage and prompt-eligibility stay two separate decisions. This
  module answers only the second one.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set

# Sources that did NOT come back through our own inbound path, and so
# carry no implicit "we mailed them first" scoping.
UNSOLICITED_SOURCES = {"mailbox", "forward"}

# How many eligible messages reach the prompt. The renderer caps at 6;
# this is the ceiling on what it may choose from.
PROMPT_REPLY_CAP = 10


def reply_source(reply: Dict[str, Any]) -> str:
    """Which pipe did this row arrive through?

    Rows written before the discriminator existed have no source key and
    are all replies-to-us by construction — there was no other way in.
    Defaulting them to "reply" is a statement about history, not a guess.
    """
    metadata = reply.get("metadata")
    if isinstance(metadata, dict):
        source = metadata.get("source")
        if isinstance(source, str) and source.strip():
            return source.strip().lower()
    return "reply"


def known_sender_emails(contacts: Iterable[Dict[str, Any]]) -> Set[str]:
    """Lowercased addresses of everyone already in the contact list.

    An empty set is a CLOSED gate, not a disabled one — a brand-new
    business with no contacts must not be a wide-open door.
    """
    return {
        (c.get("email") or "").strip().lower()
        for c in (contacts or [])
        if isinstance(c, dict) and (c.get("email") or "").strip()
    }


def is_prompt_eligible(row: Dict[str, Any], known: Set[str]) -> bool:
    """THE rule. Both the prompt gate and the Email Hub's per-message
    label call this, so the label can never drift from the behaviour it
    describes."""
    if reply_source(row) not in UNSOLICITED_SOURCES:
        return True                      # provoked mail; already scoped
    sender = (row.get("from_email") or "").strip().lower()
    return bool(sender) and sender in known


def split_for_prompt(
    replies: List[Dict[str, Any]],
    contacts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Split fetched mail into what the model may read and what it may not.

    Returns both halves. The withheld COUNT matters as much as the
    eligible list: if forty messages arrived and none were from a
    contact, Chief must be able to say "nothing from anyone you know"
    instead of "nothing arrived" — the second is false.
    """
    known = known_sender_emails(contacts)
    eligible: List[Dict[str, Any]] = []
    withheld = 0

    for reply in (replies or []):
        if is_prompt_eligible(reply, known):
            eligible.append(reply)
        else:
            withheld += 1

    return {
        "email_replies": eligible[:PROMPT_REPLY_CAP],
        "email_replies_withheld": withheld,
    }
