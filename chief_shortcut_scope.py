"""Conservative context guard for self-contained display shortcuts."""
import re

_CONSTRAINT = re.compile(
    r"\b(?:only|focus|budget|prefer\w*|avoid|exclude|except|skip|rather than|instead of|without|"
    r"priorit(?:y|ies|ize)|limit\w*)\b|\b(?:don't|do not|never)\s+"
    r"(?:include|send|contact|show|use|add|change|schedule|create|spend|work|suggest|recommend)\b|"
    r"\bno\s+(?:calls|invoices?|reminders?|outreach|emails?|texts?|spending)\b", re.I)
_TOPICS = {
    'invoice': re.compile(r'\b(?:invoices?|bills?|clients?|customers?|paid|unpaid|overdue)\b', re.I),
    'plan': re.compile(r'\b(?:plans?|priorit\w*|focus|budget|spend|work on|reminders?|outreach|'
                       r'website|marketing|sales|calls|hours?|minutes?|tasks?)\b', re.I),
}


def constrained(req, topic):
    if getattr(req, 'intent', None) == 'build':
        return True
    view = getattr(req, 'current_context', None)
    if view is not None and any(getattr(view, field, None) for field in (
            'viewing_contact_id', 'viewing_module_id', 'viewing_session_id')):
        return True
    previous_relevant = False
    for message in getattr(req, 'conversation_history', None) or []:
        if getattr(message, 'role', '') != 'user':
            continue
        text = str(getattr(message, 'content', '') or '')
        # This narrows actions, not the proposed plan's subject; both shortcuts
        # already refrain from sending, creating tasks or changing records.
        text = re.sub(r'Only show the plan; do not create tasks, send messages, or change records[.!?]?',
                      '', text, flags=re.I)
        relevant = bool(_TOPICS[topic].search(text))
        if _CONSTRAINT.search(text) and (relevant or previous_relevant):
            return True
        previous_relevant = relevant
    return False
