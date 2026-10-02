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
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import os
import re

# Sources that did NOT come back through our own inbound path, and so
# carry no implicit "we mailed them first" scoping.
UNSOLICITED_SOURCES = {"mailbox", "forward"}

# How many eligible messages reach the prompt. The renderer caps at 6;
# this is the ceiling on what it may choose from.
PROMPT_REPLY_CAP = 10


def email_clock(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Use the snapshot's clock for both author and reviewer, with no extra reads.

    Follow the availability clock's precedence. Only expose the resolved
    clock, never the rest of the business or practitioner settings.
    """
    settings = (ctx.get('business') or {}).get('settings') or {}
    name = ((settings.get('availability') or {}).get('timezone')
            or (ctx.get('practitioner_profile_raw') or {}).get('timezone')
            or os.environ.get('PLATFORM_DEFAULT_TZ', '').strip() or 'UTC')
    try:
        tz = ZoneInfo(str(name).strip())
        label = str(tz)
    except (ValueError, ZoneInfoNotFoundError):
        tz, label = timezone.utc, 'UTC (configured timezone unavailable)'
    stamp = (ctx.get('context_quality') or {}).get('retrieved_at')
    local_date = None
    try:
        now = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
        if now.tzinfo is None:
            raise ValueError('timezone missing')
        local_date = now.astimezone(tz).date().isoformat()
        description = f"Today is {local_date} in {label}; snapshot at {now.astimezone(tz).isoformat()}."
    except (TypeError, ValueError):
        description = f"Snapshot date unavailable; do not infer today. Display timezone: {label}."
    return {'timezone': tz, 'description': description, 'date': local_date}


def client_email_today_reply(message: str, ctx: Dict[str, Any]) -> str | None:
    """Answer a narrow existence check from scoped records, never model prose.

    This is also the review-outage fallback. Do not expand it to summaries of
    message bodies, mixed instructions, or claims about the entire inbox.
    """
    question = ' '.join(re.sub(r'[^\w\s]', ' ', message.casefold()).split())
    if question not in {
        'did any client email me today', 'did any of my clients email me today',
        'have any of my clients emailed me today',
        'can you check to see if any of my clients emailed me today',
        'can you check if any of my clients emailed me today',
        'did any clients email me today',
    }:
        return None
    scope = ('This covers recent stored messages, not a full inbox search or a live mailbox sync. '
             'Open Email Hub to review your messages and mailbox connection.')
    clock = email_clock(ctx)
    if not clock['date']:
        return "I can't determine today's date for this email snapshot. " + scope
    quality = ctx.get('email_context_quality') or {}
    available = all(quality.get(key) == 'available' for key in ('platform_replies', 'connected_mailbox'))
    known = known_sender_emails(ctx.get('contacts_lookup') or [])
    # Recheck the current sender policy even though the context is already
    # filtered. A platform reply is not necessarily from a saved contact.
    messages = [row for row in (ctx.get('email_replies') or [])
                if (row.get('from_email') or '').strip().lower() in known
                and is_prompt_eligible(row, known)]
    dated = [local_received_at(row.get('received_at'), clock['timezone']) for row in messages]
    if any(stamp.startswith(clock['date'] + 'T') for stamp in dated):
        answer = 'Yes. I found client email dated today in the stored messages I can read. '
        if not available:
            answer += 'Some email sources were unavailable, so this may be incomplete. '
    elif not available:
        answer = "I couldn't retrieve all the email sources, so I can't confirm whether a client emailed you today. "
    elif any(stamp.startswith('unknown') for stamp in dated):
        answer = "Some stored client messages have missing dates, so I can't confirm whether they arrived today. "
    else:
        answer = "I don't see client email dated today in the recent stored messages I can read. "
    return answer + scope


def local_received_at(value: Any, tz) -> str:
    try:
        received = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if received.tzinfo is None:
            raise ValueError('timezone missing')
        return received.astimezone(tz).isoformat()
    except (TypeError, ValueError):
        return 'unknown (cannot determine local received date)'


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
