"""Explicit, tenant-scoped invoice lifecycle actions. No payment or GL deletion.

Chief's void_invoice and the invoice drawer's Void button (POST
/invoices/{id}/void) run the same _change, so neither can skip the
pay-link cleanup."""
import asyncio
import logging
import time
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import sb_clients
from auth_supabase import UserSession
from invoice_payment_links import UnverifiedLink
from sb_clients import sb_as_current_context

logger = logging.getLogger('chief_invoice_actions')


def _fail(verb, message, code=None):
    out = {"type": verb, "result": message, "label": message, "failed": True, "nav": None}
    if code:
        out["code"] = code
    return out


# The owner's "void anyway" for a pay link that couldn't be verified counts
# only as an answer to that refusal: recorded per invoice here, honoured from
# 1 second (a person read it; not the same Chief turn, which runs its
# actions milliseconds apart) to 30 minutes later.
_UNVERIFIED_REFUSALS = {}
_ANSWER_WINDOW = (1.0, 1800.0)


def _answers_a_refusal(biz, inv):
    at = _UNVERIFIED_REFUSALS.get((str(biz['id']), str(inv['id'])))
    return at is not None and _ANSWER_WINDOW[0] <= time.monotonic() - at <= _ANSWER_WINDOW[1]


def owner_confirms_link_off(action, *, prompted, user_id, biz, owner_text):
    """Chief's side of the owner's word: the model's link_off_confirmed counts
    only on a turn the owner actually typed. Set by the dispatcher, never read
    from the payload (the same rule as _owner_text)."""
    said = str(action.get('link_off_confirmed')).strip().lower() in ('true', 'yes', '1')
    return bool(said and prompted and owner_text and str(user_id) == str(biz.get('owner_id')))


def _literal(value):
    return quote('"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"', safe='')


async def _invoice(client, biz, action):
    owner = str(UUID(str(biz['id'])))
    query = f"/invoices?business_id=eq.{owner}&select=*&limit=2"
    if action.get('invoice_id'):
        query += f"&id=eq.{UUID(str(action['invoice_id']))}"
    elif action.get('invoice_number'):
        query += f"&invoice_number=eq.{_literal(action['invoice_number'])}"
    else:
        raise ValueError('Specify the invoice number or exact invoice ID. I will not guess which invoice to change.')
    rows = await sb_as_current_context(client, 'GET', query) or []
    if len(rows) != 1:
        raise ValueError('Invoice not found in this business.' if not rows else 'More than one invoice has that number. Specify its exact ID.')
    return rows[0]


async def _change(client, biz, action, verb):
    try:
        inv = await _invoice(client, biz, action)
        status = inv.get('status')
        number = inv.get('invoice_number') or inv['id']
        if verb == 'delete_invoice' and (status != 'draft' or inv.get('sent_at') or inv.get('paid_at')):
            return _fail(verb, 'Only unsent draft invoices can be deleted. Void an unpaid invoice or archive it instead.')
        if verb in ('delete_invoice', 'void_invoice'):
            from financial_policy import require_operational_write
            require_operational_write(biz['id'])
            if status == 'paid' or inv.get('paid_at') or float(inv.get('amount_paid_cents') or 0) > 0:
                return _fail(verb, 'This invoice has a payment. Archive it to retain the payment record; voiding is not a refund.')
            if inv.get('stripe_invoice_id'):
                return _fail(verb, 'This is a Stripe-hosted invoice. Void it in Stripe first; I cannot cancel it by changing the local record alone.')
        if verb == 'void_invoice' and status not in ('draft', 'sent', 'viewed', 'overdue', 'cancelled'):
            return _fail(verb, 'This invoice is not in a state that can be voided.')
        link = None
        if verb in ('delete_invoice', 'void_invoice'):
            from invoice_payment_links import disable_invoice_payment_link
            confirmed = action.get('_owner_confirms_link_off') is True and _answers_a_refusal(biz, inv)
            try:
                link = await disable_invoice_payment_link(client, biz, inv, link_off_confirmed=confirmed)
            except UnverifiedLink:
                _UNVERIFIED_REFUSALS[(str(biz['id']), str(inv['id']))] = time.monotonic()
                raise
        patch = {}
        if verb == 'void_invoice':
            patch = {'status': 'cancelled', 'stripe_payment_url': None}
            if inv.get('is_recurring'):
                patch['recurrence_paused'] = True
        elif verb in ('archive_invoice', 'restore_invoice'):
            patch = {'archived_at': datetime.now(timezone.utc).isoformat() if verb == 'archive_invoice' else None}
        path = f"/invoices?id=eq.{UUID(str(inv['id']))}&business_id=eq.{UUID(str(biz['id']))}"
        # A concurrently paid/sent/edited invoice must not be removed or voided.
        path += f"&status=eq.{_literal(status)}"
        if inv.get('updated_at'):
            path += f"&updated_at=eq.{_literal(inv['updated_at'])}"
        if verb in ('delete_invoice', 'void_invoice'):
            path += '&paid_at=is.null'
        if verb == 'delete_invoice':
            path += '&sent_at=is.null'
        changed = await sb_as_current_context(client, 'DELETE' if verb == 'delete_invoice' else 'PATCH', path, patch or None)
        if not changed:
            # The link is switched off before this write, so a lost race leaves
            # an open invoice with a dead pay link. Say that plainly.
            if link == 'disabled':
                return _fail(verb, f'Invoice {number} changed while I was updating it, so it is still open, but its pay link is now switched off. Review it and try again.')
            return _fail(verb, 'The invoice changed while I was updating it. Review its current state and try again.')
        word = {'delete_invoice': 'deleted', 'void_invoice': 'voided', 'archive_invoice': 'archived', 'restore_invoice': 'restored'}[verb]
        result = f'Invoice {number} {word}.'
        if verb == 'void_invoice' and link == 'shared':
            result += ' Your business pay link stays on for your other invoices; it is no longer on this one.'
        elif verb == 'void_invoice' and link == 'confirmed_off':
            result += ' You said its old pay link is off in Stripe; it is no longer on the invoice either.'
        return {'type': verb, 'result': result, 'label': f'Invoice {number} {word}',
                'invoice_id': inv['id'], 'invoice_number': number, 'nav': {'tab': 'operate', 'sub': 'invoices'}}
    except UnverifiedLink as exc:
        return _fail(verb, str(exc), code='link_unverified')
    except ValueError as exc:
        return _fail(verb, str(exc))
    except HTTPException as exc:
        return _fail(verb, str(exc.detail))
    except Exception as exc:
        logger.warning('invoice %s failed: %s %s', verb, type(exc).__name__,
                       getattr(getattr(exc, 'response', None), 'status_code', ''))
        note = ' Its payment link may already be disabled; check its current state before retrying.' if verb in ('delete_invoice', 'void_invoice') else ' Please try again after invoice storage is available.'
        return _fail(verb, 'The invoice change could not be completed.' + note)


async def handle_delete_invoice(client, biz, action):
    return await _change(client, biz, action, 'delete_invoice')


async def handle_void_invoice(client, biz, action):
    return await _change(client, biz, action, 'void_invoice')


async def handle_archive_invoice(client, biz, action):
    return await _change(client, biz, action, 'archive_invoice')


async def handle_restore_invoice(client, biz, action):
    return await _change(client, biz, action, 'restore_invoice')


router = APIRouter(prefix='/invoices', tags=['invoices'])


class VoidBody(BaseModel):
    # The owner says the pay link we couldn't verify is already off in Stripe.
    # Owner only, and only as an answer to that refusal (_answers_a_refusal).
    link_off_confirmed: bool = False


@router.post('/{invoice_id}/void')
async def void_invoice(invoice_id: str, body: VoidBody | None = None,
                       session: UserSession = Depends(sb_clients.authed_request)):
    """The invoice drawer's Void button. Same checks, pay-link cleanup and
    conditional write as Chief's void_invoice, run as the signed-in person
    so RLS still applies. Member+ — the rank that can write invoices."""
    try:
        invoice_id = str(UUID(invoice_id))
    except ValueError:
        raise HTTPException(404, 'Invoice not found.')
    rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service, f'/invoices?id=eq.{invoice_id}&select=business_id&limit=1') or []
    if not rows:
        raise HTTPException(404, 'Invoice not found.')
    business_id = str(rows[0]['business_id'])
    from business_users_router import require_role
    role = await asyncio.to_thread(require_role, business_id, str(session.user.id), 'member')
    override = bool(body and body.link_off_confirmed)
    if override and role != 'owner':
        return JSONResponse(status_code=409, content={
            'detail': "Only the business owner can void an invoice whose pay link I couldn't confirm.",
            'code': 'owner_only'})
    biz = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f'/businesses?id=eq.{business_id}&select=id,stripe_account_id,settings&limit=1') or []
    if not biz:
        raise HTTPException(404, 'Invoice not found.')
    async with httpx.AsyncClient(timeout=30) as client:
        out = await _change(client, biz[0], {'invoice_id': invoice_id,
                                             '_owner_confirms_link_off': override}, 'void_invoice')
    if out.get('failed'):
        # Logged, because a refusal nobody saw is otherwise invisible.
        logger.info('void refused: invoice=%s code=%s reason=%s', invoice_id, out.get('code'), out['result'])
        return JSONResponse(status_code=409, content={'detail': out['result'], 'code': out.get('code')})
    return {'ok': True, 'result': out['result'], 'invoice_id': out['invoice_id'],
            'invoice_number': out['invoice_number']}
