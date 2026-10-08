"""Deactivate only a verified invoice-owned Stripe link, never a shared pay link.

API contracts: https://docs.stripe.com/api/payment-link/update
https://docs.stripe.com/api/checkout/sessions/list
https://docs.stripe.com/api/checkout/sessions/expire
"""
import logging

import httpx

from stripe_checkout_helpers import STRIPE_API_BASE, _secret_key
from financial_policy import require_operational_write, require_stripe_write

logger = logging.getLogger('invoice_payment_links')


class UnverifiedLink(ValueError):
    """The link can't be shown to belong only to this invoice, so it can't be
    switched off from here. The owner may still void once they have turned it
    off with Stripe themselves (link_off_confirmed)."""


class _TooMany(Exception):
    """Stripe kept paging past what we read; the list may be incomplete."""


UNVERIFIED = ("I couldn't confirm this invoice's Stripe pay link as its own, so I can't switch it off "
              "from here. Turn it off in Stripe (Payment links), then void it again and say the link is off.")


def is_business_pay_link(biz, url):
    """The pay link the practitioner pasted in Integrations. Every invoice
    without its own link carries it, so it is shared by design."""
    payments = ((biz.get('settings') or {}).get('payments') or {})
    shared = str(payments.get('stripe_link') or '').strip()
    return bool(shared) and str(url or '').strip() == shared


def _owns(link, invoice, biz):
    """Tagged for this invoice. Links made before 2026-06-06 evening (D.4 PR
    3c) carry no business_id; the invoice's UUID in source_id is the proof."""
    metadata = link.get('metadata') or {}
    return (metadata.get('source_type') == 'invoice' and metadata.get('source_id') == invoice['id']
            and metadata.get('business_id') in (None, '', biz['id']))


async def _pages(client, resource, params, headers, auth):
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
    raise _TooMany(resource)


async def _switch_off(client, owned, headers, auth):
    # Deactivate first so no new checkout can be opened while existing sessions expire.
    for link in owned:
        response = await client.post(f"{STRIPE_API_BASE}/payment_links/{link['id']}", data={'active': 'false'}, headers=headers, auth=auth)
        response.raise_for_status()
    for link in owned:
        try:
            async for sessions in _pages(client, 'checkout/sessions', {'payment_link': link['id']}, headers, auth):
                for session in sessions:
                    if session.get('status') == 'complete' or session.get('payment_status') == 'paid':
                        raise ValueError("Stripe shows a payment for this invoice, so I didn't void it. Its pay link is now off. If the money arrived, mark the invoice paid.")
                    if session.get('status') == 'open':
                        response = await client.post(f"{STRIPE_API_BASE}/checkout/sessions/{session['id']}/expire", headers=headers, auth=auth)
                        response.raise_for_status()
        except _TooMany:
            # The links are already off here, so this is not "couldn't switch it off".
            raise ValueError("Its pay link is now off, but I couldn't read all of its Stripe checkouts, so I didn't void it. Check its payments in Stripe, then try again.")


async def disable_invoice_payment_link(client, biz, invoice, *, link_off_confirmed=False):
    """Returns 'shared' when the invoice carries the business's own pay link
    (it stays on for the other invoices; the caller only detaches it),
    'disabled' once the invoice's own links are off, 'confirmed_off' when the
    link can't be verified but the owner says it is off, None with no link.
    Raises UnverifiedLink when it can't be verified and nobody said so."""
    url = invoice.get('stripe_payment_url')
    if not url:
        return None
    if is_business_pay_link(biz, url):
        return 'shared'
    # Every path below can write to Stripe, the platform account included.
    require_operational_write(biz['id'])
    auth = (_secret_key(), '')
    # Where an invoice's own link can live: the business's connected account
    # (every link since D.4 PR 3c), then the platform account (KMJ's earlier ones).
    places = []
    account = biz.get('stripe_account_id')
    if account:
        require_stripe_write(account)
        places.append({'Stripe-Account': account})
    places.append({})
    for headers in places:
        found, owned = None, []
        try:
            async for links in _pages(client, 'payment_links', {}, headers, auth):
                for link in links:
                    if link.get('url') == url:
                        found = link
                    if _owns(link, invoice, biz):
                        owned.append(link)
        except (httpx.HTTPStatusError, _TooMany) as exc:
            logger.warning('pay link lookup failed: invoice=%s on=%s why=%s', invoice['id'],
                           'connected' if headers else 'platform',
                           getattr(getattr(exc, 'response', None), 'status_code', 'too many links'))
            continue
        if found and _owns(found, invoice, biz):
            await _switch_off(client, owned, headers, auth)
            return 'disabled'
    logger.info('pay link unverified: invoice=%s confirmed_off=%s', invoice['id'], bool(link_off_confirmed))
    if link_off_confirmed:
        return 'confirmed_off'
    raise UnverifiedLink(UNVERIFIED)
