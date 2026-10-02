"""Invoice visual scope and recovery from server-authored display rows."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
import re


_ALL_INVOICES = re.compile(r"\b(?:all|every)\s+(?:(?:of\s+)?(?:my|the|our)\s+)?invoices?\b", re.I)
_BROAD_PREFIX = re.compile(
    r"^\s*(?:can you do me a favor[?.!,]\s*)?"
    r"(?:I (?:want|would like) you to\s+)?(?:(?:can|could|would) you\s+)?"
    r"(?:please\s+)?(?:(?:show(?: me)?|list|pull up|display|open|let me see)\s+)?$", re.I)
_BROAD_TAIL = re.compile(
    r"^\s*(?:that I have\s*,?\s*)?"
    r"(?:(?:as|in) a (?:visual|chart|list|timeline)|"
    r"to show me a visual of (?:the|my|our) invoices)?"
    r"(?:\s*,?\s*so (?:that way )?I can (?:get an idea exactly |see )where things (?:are standing|stand))?"
    r"[.!?\s]*$", re.I)

_DISPLAY_ONLY = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|all right|great|thanks|now)[,.!\s]+){0,5}"
    r"(?:(?:can|could|would) you\s+)?(?:please\s+)?"
    r"(?:show(?: me)?|list|pull up|display|open|give me)\s+"
    r"(?:a (?:list|visual|chart|timeline) of\s+)?"
    r"(?:(?:all|every)\s+(?:of\s+)?)?(?:(?:my|the|our)\s+)?"
    r"(?:(?:open|paid|draft|overdue)\s+)?invoices?"
    r"(?:\s+(?:as|in) a (?:visual|chart|list|timeline))?[.!?\s]*$", re.I)


def invoice_display_request(message):
    """Whole-message display intent only; advice, mutations and filters stay modeled."""
    return bool(_DISPLAY_ONLY.fullmatch(message or ''))


def request_action(req):
    """Only an explicit, self-contained display request can skip model planning."""
    if getattr(req, 'image_ids', None) or (getattr(req, 'mode', None) or '') not in ('', 'chief'):
        return None
    from chief_shortcut_scope import constrained
    if constrained(req, 'invoice'):
        return None
    message = getattr(req, 'message', '') or ''
    if not invoice_display_request(message):
        return None
    status = re.search(r'\b(open|paid|draft|overdue)\s+invoices?\b', message, re.I)
    form = re.search(r'\b(chart|timeline|list)\b', message, re.I)
    return {'type': 'show_view', 'view': 'invoices',
            'filter': status[1].lower() if status else ('all' if _ALL_INVOICES.search(message) else 'open'),
            'form': form[1].lower() if form else 'list'}


async def serve_request(client, req, session, biz):
    """After admission/recurrence and a scoped business read, use the normal door.

    The owner equality is deliberately stricter than merely receiving an RLS
    row. Collaborator seats retain the existing full-context permission path.
    Returning None means no action has run; once attempted, never fall through
    and repeat it through a model turn.
    """
    action = request_action(req)
    owner_id = str(getattr(getattr(session, 'user', None), 'id', '') or '')
    if (action is None or not isinstance(biz, dict) or not owner_id
            or str(biz.get('id') or '') != str(req.business_id)
            or str(biz.get('owner_id') or '') != owner_id):
        return None
    import chief_of_staff as chief
    import chief_stream_replay as replay
    import chief_speech_boundary as speech
    if chief._STREAM_SINK.get() is None:
        recovered = await replay.recover_async(req, owner_id)
        if recovered is not None:
            return recovered
    taken = await chief._execute_actions(client, biz, [action], user_id=owner_id,
                                         owner_text=req.message)
    if any(chief._action_failed(row) for row in taken):
        answer = chief._deterministic_fallback_reply(taken)
        grounding = {'status': 'receipts', 'sources': []}
    else:
        # Unsafe free-text cells may disqualify the detailed readout, but its
        # validated numeric/status summary can still answer without a model.
        answer = direct_invoice_answer(req.message, taken) or invoice_view_answer(taken)
        grounding = {'status': 'records', 'sources': ['result:0']}
        if not answer:
            answer = "I couldn't read the invoice list reliably."
            grounding = {'status': 'withheld', 'sources': []}
    answer = speech.final_reply(answer, req.message)
    result = {'response': answer, 'actions_taken': taken, 'grounding': grounding}
    await chief._archive_turn(client, biz, req.message, answer, taken)
    await chief._log_chief_activity(client, user_id=owner_id, business_id=biz['id'],
                                    source=req.client_surface, taken=taken)
    try:
        import audit_log
        await asyncio.to_thread(audit_log.record_chief_turn, user_id=owner_id,
            business_id=biz['id'], source=req.client_surface, taken=taken,
            action_failed=chief._action_failed)
    except Exception as exc:
        chief.logger.warning('Invoice readout audit hook unavailable: %s', type(exc).__name__)
    if chief._STREAM_SINK.get() is not None:
        replay.remember(req, owner_id, result)
    return result


def invoice_display_evidence(taken):
    """A bounded typed view, without trusting model labels, totals or speak prose."""
    if not invoice_view_answer(taken):
        return None
    view = taken[0]
    if len(view['rows']) > 25:
        return None
    rows = []
    for row in view['rows']:
        if any(not isinstance(row.get(key), str) or len(row[key]) > 160
               or re.search(r'[\x00-\x1f\x7f]', row[key]) for key in ('number', 'client', 'due')):
            return None
        import chief_speech_boundary
        import untrusted_text
        if any(chief_speech_boundary.internal_scaffolding(row[key])
               or untrusted_text.detect_injection(row[key])
               or untrusted_text.ACTION_TAGLIKE_RE.search(row[key]) for key in ('number', 'client')):
            return None
        if row['due']:
            try:
                date.fromisoformat(row['due'])
            except ValueError:
                return None
        rows.append({key: row[key] for key in ('number', 'client', 'amount', 'status', 'due')})
    return {'view': 'invoices', 'filter': view['filter'], 'form': view['form'],
            'limit_reached': bool(view.get('limit_reached')), 'rows': rows}


def direct_invoice_answer(message, taken):
    """Pure display answers are a readout of the actual card, not generated prose."""
    if not invoice_display_request(message):
        return None
    data = invoice_display_evidence(taken)
    if data is None:
        return None
    requested_status = re.search(r'\b(open|paid|draft|overdue)\s+invoices?\b', message, re.I)
    if requested_status and requested_status[1].lower() != data['filter']:
        return None
    if not requested_status and _ALL_INVOICES.search(message) and data['filter'] != 'all':
        return None
    requested_form = re.search(r'\b(chart|timeline|list)\b', message, re.I)
    if requested_form and requested_form[1].lower() != data['form']:
        return None
    answer = invoice_view_answer(taken)
    lines = []
    for row in data['rows'][:5]:
        due = f", due {row['due']}" if row['due'] else ''
        lines.append(f"Invoice {row['number']}, client {row['client']}: ${Decimal(str(row['amount'])):,.2f}, {row['status']}{due}.")
    if lines:
        answer += '\n\n' + '\n'.join(lines)
    remaining = len(data['rows']) - len(lines)
    if remaining:
        answer += f'\nThe remaining {remaining} invoice' + ('s are' if remaining != 1 else ' is') + ' in the displayed view.'
    return answer



def owner_invoice_scope(action, owner_text):
    """An explicit full list must not silently become the default open list.

    Ambiguous, negated, and status-qualified requests keep model-selected scope.
    This only changes a display read, never a billing or sending action.
    """
    match = _ALL_INVOICES.search(owner_text or '')
    prefix = (owner_text or '')[:match.start()] if match else ''
    tail = (owner_text or '')[match.end():] if match else ''
    if (action.get('type') == 'show_view' and action.get('view') == 'invoices'
            and match and _BROAD_PREFIX.fullmatch(prefix) and _BROAD_TAIL.fullmatch(tail)):
        return {**action, 'filter': 'all'}
    return action


def invoice_view_answer(taken):
    """Recover one invoice visual without trusting draft prose or receipt labels.

    The handler's bounded rows are the authority; never present a sample's total
    as the whole receivables balance, or treat draft/paid totals as money owed.
    Mixed operations keep the normal receipt/repair path.
    """
    if len(taken) != 1:
        return None
    view = taken[0]
    if (view.get('type') != 'show_view' or view.get('view') != 'invoices'
            or view.get('failed') or view.get('needs_confirmation')):
        return None
    rows = view.get('rows')
    if not isinstance(rows, list) or not isinstance(view.get('columns'), list):
        return None
    filt = view.get('filter')
    if filt not in ('all', 'open', 'paid', 'draft', 'overdue'):
        return None
    scope = 'invoice' if filt == 'all' else f'{filt} invoice'
    if not rows:
        return f'No {scope}s match this view.'
    amounts = defaultdict(lambda: [0, Decimal(0)])
    for row in rows:
        if not isinstance(row, dict) or row.get('status') not in (
                'draft', 'sent', 'viewed', 'overdue', 'paid', 'cancelled', 'canceled', 'void'):
            return None
        try:
            amount = Decimal(str(row['amount']))
        except (KeyError, InvalidOperation, ValueError):
            return None
        if not amount.is_finite():
            return None
        status = row['status']
        amounts[status][0] += 1
        amounts[status][1] += amount
    total = sum((entry[1] for entry in amounts.values()), Decimal(0))
    form = {'chart': 'chart', 'timeline': 'timeline', 'list': 'list'}.get(view.get('form'))
    if not form:
        return None
    answer = f'The {scope} {form} shows {len(rows)} invoice' + ('s' if len(rows) != 1 else '')
    answer += f' totaling ${total:,.2f}. '
    answer += '; '.join(f'{count} {status}: ${amount:,.2f}'
                        for status, (count, amount) in amounts.items()) + '.'
    if view.get('limit_reached'):
        answer += ' This view is capped at 25 invoices; the totals cover only the invoices shown.'
    else:
        answer += ' Those totals cover the invoices shown.'
    return answer
