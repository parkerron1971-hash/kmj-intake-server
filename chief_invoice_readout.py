"""Invoice visual scope and recovery from server-authored display rows."""
from __future__ import annotations

from collections import defaultdict
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
