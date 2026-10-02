"""Invoice delivery by SMS through the existing send_invoice approval boundary."""
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from uuid import UUID

from chief_invoice_actions import _invoice

logger = logging.getLogger(__name__)
MAX_BODY_CHARS = 1200  # Leave room for sender identity and service notices.


def invoice_text(biz, invoice):
    """Compose from saved invoice data only; never accept a model-written link."""
    try:
        total = Decimal(str(invoice['total']))
        if not total.is_finite() or total <= 0:
            raise ValueError
    except (KeyError, InvalidOperation, ValueError):
        raise ValueError('This invoice needs a valid positive total before I can text it.')
    currency = str(invoice.get('currency') or 'USD').upper()
    lines = [f"{biz.get('name') or 'Your business'} — Invoice {invoice.get('invoice_number') or invoice['id']}"]
    for item in invoice.get('items') or []:
        lines.append(f"{item.get('description') or 'Item'} (qty {item.get('quantity', 1)})")
    lines.append(f'Total: {currency} {total:,.2f}')
    if invoice.get('due_date'):
        lines.append(f"Due: {invoice['due_date']}")
    # Use only the link stored on this invoice. A generic business payment
    # link may charge a different amount; do not silently substitute it.
    link = str(invoice.get('stripe_payment_url') or '').strip()
    if link:
        parsed = urlsplit(link)
        if parsed.scheme != 'https' or not parsed.netloc or parsed.username or any(c.isspace() for c in link):
            raise ValueError('The saved invoice payment link is invalid. Correct it before texting the invoice.')
        lines.append(f'Pay: {link}')
    else:
        lines.append('Please reply for payment arrangements.')
    body = '\n'.join(lines)
    if len(body) > MAX_BODY_CHARS:
        raise ValueError('This invoice is too detailed for a text. Send it by email or shorten its item descriptions first.')
    return body


async def send_invoice_sms(client, biz, action, *, preview=False):
    import chief_of_staff as chief
    import sms_service

    def fail(message):
        return chief._fail('send_invoice', message)

    try:
        owner = str(UUID(str(biz['id'])))
        selected = dict(action)
        if selected.get('invoice_id') == 'latest':
            rows = await chief._sb(client, 'GET',
                f'/invoices?business_id=eq.{owner}&order=created_at.desc&limit=1&select=id')
            if not rows:
                return fail('No invoice was found. Which invoice would you like me to text?')
            selected['invoice_id'] = rows[0]['id']
        if not (selected.get('invoice_id') or selected.get('invoice_number')):
            return fail('Which invoice should I text? Tell me the invoice number or client name.')
        invoice = await _invoice(client, biz, selected)
        if invoice.get('status') in ('cancelled', 'void', 'voided', 'paid') or invoice.get('paid_at') or invoice.get('archived_at'):
            return fail('This invoice is paid, voided or archived. Choose an open invoice to text.')
        if not invoice.get('contact_id'):
            return fail('This invoice has no linked contact. Link the intended client before texting it.')
        contact = await chief._validate_contact(client, owner, invoice['contact_id'])
        if not contact:
            return fail('The invoice contact was not found in this business.')
        phone = str(contact.get('phone') or '').strip()
        if not phone:
            return fail(f"{contact.get('name') or 'The invoice contact'} has no phone number on file. Add one before texting the invoice.")
        body = invoice_text(biz, invoice)
    except ValueError as exc:
        return fail(str(exc))

    if preview:
        number = invoice.get('invoice_number') or invoice['id']
        currency = str(invoice.get('currency') or 'USD').upper()
        last_digits = ''.join(c for c in phone if c.isdigit())[-4:]
        prompt = (f"Text invoice {number} for {currency} {Decimal(str(invoice['total'])):,.2f} "
                  f"to {contact.get('name') or 'the invoice contact'}, phone ending {last_digits}? "
                  'Nothing has been sent. Say "send it" to confirm.')
        return {'type': 'send_invoice', 'channel': 'sms', 'failed': True,
                'needs_confirmation': True, 'result': prompt, 'label': prompt,
                'invoice_id': invoice['id'], 'nav': None}

    try:
        sent = await sms_service.send_sms_core(client, business_id=owner, to=phone,
            contact_id=contact['id'], message=body, sent_by='chief')
    except sms_service.SmsSendError as exc:
        reason = str(exc)
        if 'not configured' in reason.lower():
            reason = "Texting isn't switched on for this account yet. Nothing was sent."
        return fail(reason)
    except Exception:
        logger.exception('Invoice SMS send did not return a receipt')
        return fail("I couldn't confirm the text was sent. Check the SMS thread before trying again.")
    if not sent or sent.get('status') != 'sent' or not sent.get('telnyx_id'):
        return fail("The texting provider did not return a send receipt. Check the SMS thread before trying again.")

    # Once the provider accepted the SMS, a bookkeeping failure must never
    # imply no send occurred or invite an automatic duplicate send.
    warning = ''
    try:
        patch = {'sent_at': datetime.now(timezone.utc).isoformat()}
        if invoice.get('status') == 'draft':
            patch['status'] = 'sent'
        changed = await chief._sb(client, 'PATCH',
            f"/invoices?id=eq.{invoice['id']}&business_id=eq.{owner}&status=eq.{invoice.get('status')}", patch)
        event = await chief._sb(client, 'POST', '/events', {
            'business_id': owner, 'contact_id': contact['id'], 'event_type': 'invoice_sent',
            'data': {'invoice_id': invoice['id'], 'invoice_number': invoice.get('invoice_number'),
                     'total': invoice.get('total'), 'channel': 'sms', 'sms_id': sent.get('id'),
                     'provider_id': sent['telnyx_id']}, 'source': 'chief_of_staff'})
        if not changed or not event:
            warning = ' The text was sent, but the invoice history could not be fully updated.'
    except Exception:
        logger.exception('Invoice SMS accepted but bookkeeping failed')
        warning = ' The text was sent, but the invoice history could not be fully updated.'
    return {'type': 'send_invoice', 'result': 'sent', 'channel': 'sms', 'sms_sent': True,
            'invoice_id': invoice['id'], 'contact_id': contact['id'],
            'invoice_number': invoice.get('invoice_number'), 'total': invoice.get('total'),
            'currency': invoice.get('currency') or 'USD',
            'sms_id': sent.get('id'), 'provider_id': sent['telnyx_id'],
            'label': f"Invoice {invoice.get('invoice_number') or invoice['id']} sent by text to {contact.get('name') or 'the invoice contact'}." + warning,
            'nav': {'tab': 'operate', 'sub': 'sms'}}
