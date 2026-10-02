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


_DISPLAY_PLAN_REQUEST = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|all right|great|thanks|now)[,.!\s]+){0,5}"
    r"(?:(?:can|could|would) you\s+)?(?:please\s+)?"
    r"(?:show(?: me)?|give me|create|draft|outline) (?:a )?"
    r"(?:(?:short|brief|simple|suggested|proposed) ){0,3}plan"
    r"(?: for the next (?:two|2) days)?(?: of things (?:that )?I can work on)?"
    r"[.!?\s]*"
    r"(?:Only show (?:me )?the plan; (?:do not|don't) create tasks, send messages, or change records[.!?\s]*)?$",
    re.I)
_CANONICAL_PROPOSALS = {
    'review recent messages and draft a reply',
    'choose a lead to contact and draft a short message',
    'review draft messages before sending',
    'ask customers for testimonials in their own words',
}


def plan_display_request(message):
    return isinstance(message, str) and bool(_DISPLAY_PLAN_REQUEST.fullmatch(message))


def _safe_proposal_text(text):
    from chief_speech_boundary import internal_scaffolding
    from untrusted_text import detect_injection, ACTION_TAGLIKE_RE
    return (isinstance(text, str) and len(text) <= 220
            and not re.search(r'[\x00-\x1f\x7f\u2028\u2029]', text)
            and not internal_scaffolding(text) and not detect_injection(text)
            and not ACTION_TAGLIKE_RE.search(text))


def _plan_sources(ctx):
    import json
    rows = (ctx or {}).get('open_invoices')
    if not isinstance(rows, list):
        return {}
    # These are independent, business-scoped handler records, not plan content.
    return {'context:open_invoices': {'kind': 'context',
        'text': json.dumps(rows[:100], ensure_ascii=False),
        'unread': bool((ctx or {}).get('open_invoices_complete') is False and not rows)}}


def _invoice_review(text, sources):
    import json
    if not re.match(r'^review\b', text, re.I):
        return None
    numbers = list(dict.fromkeys(re.findall(r'\bINV-\d[\w-]*\b', text, re.I)))
    source = (sources or {}).get('context:open_invoices') or {}
    if not numbers or source.get('kind') != 'context' or source.get('unread'):
        return None
    try:
        rows = json.loads(source.get('text', ''))
    except (ValueError, TypeError):
        return None
    if not isinstance(rows, list):
        return None
    actual = {r.get('number', '').casefold(): r.get('number') for r in rows
              if isinstance(r, dict) and isinstance(r.get('number'), str)
              and r.get('status') in ('sent', 'viewed', 'overdue')
              and _safe_proposal_text(r['number'])}
    if not all(number.casefold() in actual for number in numbers):
        return None
    matched = [actual[number.casefold()] for number in numbers]
    return 'Review invoice' + ('s ' if len(matched) > 1 else ' ') + ' and '.join(matched) + ' for follow-up'


def _normalize_step(value, sources, ctx):
    if not _safe_proposal_text(value):
        return None
    text = _PREFIX.sub('', value.strip()).rstrip('.').strip()
    exact = _safe_step(text, sources)
    if exact:
        return exact
    if text.casefold() in _CANONICAL_PROPOSALS:
        return text
    if text.casefold() == 'prepare for your next appointment':
        from datetime import datetime, timezone
        for row in ((ctx or {}).get('sessions') or []):
            if not isinstance(row, dict) or not row.get('id') or row.get('status') in ('cancelled', 'canceled', 'completed'):
                continue
            try:
                scheduled = datetime.fromisoformat(str(row.get('scheduled_for') or '').replace('Z', '+00:00'))
                if scheduled.tzinfo and scheduled >= datetime.now(timezone.utc):
                    return text
            except ValueError:
                pass
        return None
    if re.search(r"\b(?:don't|do not|never|avoid|instead of|rather than|except|not|without)\b", text, re.I):
        return None
    invoices = _invoice_review(text, sources)
    if invoices:
        return invoices
    # Recover the proposed task, not its asserted premise. None of the model's
    # names, counts, dates, quoted messages, statuses or rationale are copied.
    # Unknown invoice references never become a generic invoice recommendation.
    if (re.match(r'^(?:reply|respond) to\b', text, re.I)
            and re.search(r'\b(?:text|message|email)\b', text, re.I)):
        return 'Review recent messages and draft a reply'
    if (re.match(r'^(?:pick|choose|select|prioritize)\b', text, re.I)
            and re.search(r'\bleads?\b', text, re.I)
            and re.search(r'\b(?:contact|reach out|follow up)\b', text, re.I)):
        return 'Choose a lead to contact and draft a short message'
    if re.match(r'^(?:ask|request)\b', text, re.I) and re.search(r'\btestimonials?\b', text, re.I):
        return 'Ask customers for testimonials in their own words'
    return None


def normalize_plan_receipt(receipt, message='', ctx=None):
    """A proposed card and spoken answer share the same independently safe steps."""
    if not _plan(receipt):
        return None
    sources = _plan_sources(ctx)
    steps = []
    for step in receipt['steps']:
        text = _normalize_step(step['step'], sources, ctx)
        if not text:
            continue
        when = _RELATIVE_WHEN.get(str(step.get('when') or '').strip().lower())
        clean = {'step': text, **({'when': when} if when else {})}
        if clean not in steps:
            steps.append(clean)
    if not steps:
        return None
    horizon = bool(re.search(r'\bnext (?:two|2) days\b', message, re.I))
    title = 'Next two days' if horizon else 'Suggested next steps'
    count = len(steps)
    return {'type': 'show_plan', 'authored': 'chief', 'title': title, 'steps': steps,
        'result': f'Proposed plan on screen with {count} steps',
        'label': f'{title}: {count} suggested steps',
        'speak': '; '.join(step['step'] for step in steps),
        'plan_partial': bool(receipt.get('plan_partial')) or len(steps) != len(receipt['steps']),
        **({'_authorized_by': receipt['_authorized_by']} if '_authorized_by' in receipt else {})}


def plan_readout(receipt, message=''):
    horizon = ' for the next two days' if re.search(r'\bnext (?:two|2) days\b', message, re.I) else ''
    heading = ('Suggested starting points' if receipt.get('plan_partial') else 'Suggested plan') + horizon + ':'
    return heading + '\n' + '\n'.join(
        f"- {step['when'] + ': ' if step.get('when') else ''}{step['step']}." for step in receipt['steps'])


def direct_plan_readout(message, taken, ctx=None):
    """Skip duplicate narration/review only for a successful single plan display."""
    if not plan_display_request(message) or len(taken) != 1:
        return None
    normalized = normalize_plan_receipt(taken[0], message, ctx)
    return (plan_readout(normalized, message), normalized) if normalized else None
