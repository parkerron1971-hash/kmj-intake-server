"""Explicit, tenant-scoped invoice lifecycle actions. No payment or GL deletion.

Chief's void_invoice and the invoice drawer's Void button (POST
/invoices/{id}/void) run the same _change, so neither can skip the
pay-link cleanup."""
import asyncio
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import UserSession
from sb_clients import sb_as_current_context


def _fail(verb, message):
    return {"type": verb, "result": message, "label": message, "failed": True, "nav": None}


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
            link = await disable_invoice_payment_link(client, biz, inv)
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
            return _fail(verb, 'The invoice changed while I was updating it. Review its current state and try again. Any invoice-specific payment link may already be disabled.')
        word = {'delete_invoice': 'deleted', 'void_invoice': 'voided', 'archive_invoice': 'archived', 'restore_invoice': 'restored'}[verb]
        result = f'Invoice {number} {word}.'
        if verb == 'void_invoice' and link == 'shared':
            result += ' Your business pay link stays on for your other invoices; it is no longer on this one.'
        return {'type': verb, 'result': result, 'label': f'Invoice {number} {word}',
                'invoice_id': inv['id'], 'invoice_number': number, 'nav': {'tab': 'operate', 'sub': 'invoices'}}
    except ValueError as exc:
        return _fail(verb, str(exc))
    except HTTPException as exc:
        return _fail(verb, str(exc.detail))
    except Exception:
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


@router.post('/{invoice_id}/void')
async def void_invoice(invoice_id: str, session: UserSession = Depends(sb_clients.authed_request)):
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
    await asyncio.to_thread(require_role, business_id, str(session.user.id), 'member')
    biz = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f'/businesses?id=eq.{business_id}&select=id,stripe_account_id,settings&limit=1') or []
    if not biz:
        raise HTTPException(404, 'Invoice not found.')
    async with httpx.AsyncClient(timeout=30) as client:
        out = await _change(client, biz[0], {'invoice_id': invoice_id}, 'void_invoice')
    if out.get('failed'):
        raise HTTPException(409, out['result'])
    return {'ok': True, 'result': out['result'], 'invoice_id': out['invoice_id'],
            'invoice_number': out['invoice_number']}
