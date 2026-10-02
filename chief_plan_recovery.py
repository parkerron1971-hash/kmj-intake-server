"""Recover proposed plan steps without treating model-authored text as records."""
from __future__ import annotations

import re

# Only closed, generic proposal shapes recover without record evidence. A verb
# prefix alone cannot clear "Review the unpaid balance from Acme".
_PREFIX = re.compile(r"^\s*(?:(?:step\s*)?\d+[.):]\s*|[-*]\s+)", re.I)
_RELATIVE_WHEN = {'today': 'Today', 'tomorrow': 'Tomorrow', 'day 1': 'Day 1',
                  'day one': 'Day 1', 'day 2': 'Day 2', 'day two': 'Day 2'}
_DETERMINER = r"(?:(?:a|an|the|your|one|two|three|[1-3]) )?"
_GENERIC_STEP = re.compile(
    r"(?:"
    r"(?:review|check|reconcile|organize) (?:the |your )?"
    r"(?:invoice list|invoices|open invoices|overdue invoices|unpaid invoices|payment records|financial records)"
    rf"|(?:draft|write|prepare|outline|create|review|refine|update) {_DETERMINER}"
    r"(?:follow-up messages?|emails?|messages?|customer feedback questions?|feedback questions?|"
    r"testimonial requests?|offer|offer description|website copy|outreach messages?|reminders?)"
    rf"|(?:choose|pick|identify|list|prioritize) {_DETERMINER}"
    r"(?:priorities|next steps|ideas|options|tasks|main priority)"
    r"|(?:ask for|request|gather|collect) (?:a |some )?(?:customer )?(?:feedback|testimonials?|reviews?)"
    r"|(?:plan|schedule|set aside) (?:a |some )?time for (?:outreach|follow-up|review|planning)"
    r")", re.I)


def _plan(receipt):
    steps = receipt.get('steps')
    return (receipt.get('type') == 'show_plan' and receipt.get('authored') == 'chief'
            and not receipt.get('failed') and not receipt.get('needs_confirmation')
            and isinstance(steps, list) and 0 < len(steps) <= 8
            and all(isinstance(s, dict) and isinstance(s.get('step'), str) for s in steps))


def plan_receipt_evidence(receipt):
    """The UI execution proves display/count, not the plan's factual premises."""
    if not _plan(receipt):
        return None
    return {'type': 'show_plan', 'result': 'A proposed plan is on screen.',
            'step_count': len(receipt['steps']), 'authored': 'chief'}


def _verified_invoice_step(text, sources):
    # Use the same bounded current records supplied to the reviewer, never plan
    # title/why/speak or old assistant prose. A reminder still is only proposed.
    import json
    source = (sources or {}).get('context:open_invoices') or {}
    if source.get('kind') != 'context' or source.get('unread'):
        return False
    try:
        rows = json.loads(source.get('text', ''))
    except (ValueError, TypeError):
        return False
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict) or row.get('status') not in ('sent', 'viewed', 'overdue'):
            continue
        name, number = row.get('client'), row.get('number')
        if not isinstance(name, str) or not isinstance(number, str) or not name or not number:
            continue
        if name.startswith('(') or number.startswith('('):
            continue
        from chief_speech_boundary import internal_scaffolding
        from untrusted_text import detect_injection, ACTION_TAGLIKE_RE
        if any(re.search(r'[\x00-\x1f\x7f\u2028\u2029]', value)
               or internal_scaffolding(value) or detect_injection(value)
               or ACTION_TAGLIKE_RE.search(value) for value in (name, number)):
            continue
        name, number = re.escape(name), re.escape(number)
        if re.fullmatch(rf"(?:send|draft) {name} a reminder (?:on|about|for) {number}"
                        rf"|follow up with {name} about {number}", text, re.I):
            return True
    return False


def _safe_step(value, sources=None):
    text = _PREFIX.sub('', value.strip()).rstrip('.').strip()
    if not text or len(text) > 220:
        return None
    return text if _GENERIC_STEP.fullmatch(text) or _verified_invoice_step(text, sources) else None


def proposed_plan_answer(taken, message='', sources=None):
    if len(taken) != 1 or not _plan(taken[0]):
        return None
    plan = taken[0]
    lines = []
    for step in plan['steps']:
        text = _safe_step(step['step'], sources)
        if not text:
            continue
        when = _RELATIVE_WHEN.get(str(step.get('when') or '').strip().lower())
        lines.append(f"- {when + ': ' if when else ''}{text}.")
    if not lines:
        return 'Your proposed plan is on screen.'
    horizon = ' for the next two days' if re.search(r'\bnext (?:two|2) days\b', message, re.I) else ''
    heading = (f'Here are suggested steps{horizon}:' if len(lines) == len(plan['steps'])
               else f'Here are suggested starting points{horizon}:')
    return heading + '\n' + '\n'.join(lines)
