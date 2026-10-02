"""Deactivate only a verified invoice-owned Stripe link, never a shared pay link.

API contracts: https://docs.stripe.com/api/payment-link/update
https://docs.stripe.com/api/checkout/sessions/list
https://docs.stripe.com/api/checkout/sessions/expire
"""
from stripe_checkout_helpers import STRIPE_API_BASE, _secret_key
from financial_policy import require_stripe_write


async def disable_invoice_payment_link(client, biz, invoice):
    url = invoice.get('stripe_payment_url')
    if not url:
        return
    account = biz.get('stripe_account_id')
    if not account:
        raise ValueError('This invoice has an external payment link. Disable that link with the payment provider before deleting or voiding the invoice.')
    headers = {'Stripe-Account': account}
    auth = (_secret_key(), '')
    require_stripe_write(account)

    async def pages(resource, params):
        params = {**params, 'limit': 100}
        for _ in range(100):
            response = await client.get(f'{STRIPE_API_BASE}/{resource}', params=params, headers=headers, auth=auth)
            response.raise_for_status()
            page = response.json()
            yield page.get('data') or []
            if not page.get('has_more'):
                return
            rows = page.get('data') or []
            if not rows:
                break
            params['starting_after'] = rows[-1]['id']
        raise ValueError('Could not verify the complete payment-link history. No local invoice change was made.')

    found = None
    owned = []
    async for links in pages('payment_links', {}):
        for link in links:
            if link.get('url') == url:
                found = link
            metadata = link.get('metadata') or {}
            if metadata.get('source_type') == 'invoice' and metadata.get('source_id') == invoice['id'] and metadata.get('business_id') == biz['id']:
                owned.append(link)
    metadata = (found or {}).get('metadata') or {}
    if not found or metadata.get('source_type') != 'invoice' or metadata.get('source_id') != invoice['id'] or metadata.get('business_id') != biz['id']:
        raise ValueError('That payment link is shared or cannot be verified as belonging only to this invoice. Disable it with the provider before deleting or voiding the invoice.')
    # Deactivate first so no new checkout can be opened while existing sessions expire.
    for link in owned:
        response = await client.post(f"{STRIPE_API_BASE}/payment_links/{link['id']}", data={'active': 'false'}, headers=headers, auth=auth)
        response.raise_for_status()
    for link in owned:
        async for sessions in pages('checkout/sessions', {'payment_link': link['id']}):
            for session in sessions:
                if session.get('status') == 'complete' or session.get('payment_status') == 'paid':
                    raise ValueError('Stripe has a completed payment or payment in progress for this invoice. Its links are disabled; keep the invoice and review the payment instead of voiding or deleting it.')
                if session.get('status') == 'open':
                    response = await client.post(f"{STRIPE_API_BASE}/checkout/sessions/{session['id']}/expire", headers=headers, auth=auth)
                    response.raise_for_status()
