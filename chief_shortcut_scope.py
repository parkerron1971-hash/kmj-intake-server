"""Conservative context guard for self-contained display shortcuts."""
import re
from types import SimpleNamespace

_CONSTRAINT = re.compile(
    r"\b(?:only|focus|budget|prefer\w*|avoid|exclude|except|skip|rather than|instead of|without|"
    r"priorit(?:y|ies|ize)|limit\w*)\b|\b(?:don't|do not|never)\s+"
    r"(?:include|send|contact|show|use|add|change|schedule|create|spend|work|suggest|recommend)\b|"
    r"\bno\s+(?:calls|invoices?|reminders?|outreach|emails?|texts?|spending)\b", re.I)
_TOPICS = {
    'invoice': re.compile(r'\b(?:invoices?|bills?|clients?|customers?|paid|unpaid|overdue)\b', re.I),
    'plan': re.compile(r'\b(?:plans?|priorit\w*|focus|budget|spend|work on|reminders?|outreach|'
                       r'website|marketing|sales|calls|hours?|minutes?|tasks?|invoices?|clients?'
                       r'|next (?:two|2) days)\b', re.I),
}
_ACK = re.compile(r'(?:yes|no|ok(?:ay)?|great|thanks|thank you|all right)[.!?, ]*', re.I)
_REFERENCE = re.compile(r"^(?:i mean|the ones|those|these|make that|for (?:him|her|them))\b", re.I)


def _plain_history_request(text):
    # Whitelist the same self-contained forms as the live shortcuts. Unknown
    # relevant wording is retained for the full model, not reinterpreted here.
    from chief_invoice_readout import invoice_display_request
    from chief_quick_plan import eligible
    return invoice_display_request(text) or eligible(SimpleNamespace(message=text))


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
        if _REFERENCE.search(text.strip()):
            return True
        qualified_invoice = topic == 'invoice' and re.search(r'\b(?:paid|unpaid|draft|overdue) invoices?\b', text, re.I)
        if _ACK.fullmatch(text.strip()):
            continue
        if _plain_history_request(text.strip()) and not qualified_invoice:
            previous_relevant = relevant
            continue
        # A request to inspect a website is its own earlier operation, not a
        # constraint on future planning. Qualifiers on a PLAN still fall through.
        separate_site_read = (topic == 'plan' and re.search(r'\bscreenshot\b', text, re.I)
                              and not _CONSTRAINT.search(text)
                              and not re.search(r'\b(?:plan|next (?:two|2) days|priorit\w*)\b', text, re.I))
        if (relevant and not separate_site_read) or previous_relevant:
            return True
        previous_relevant = relevant
    return False
