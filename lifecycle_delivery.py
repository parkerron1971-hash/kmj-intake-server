"""Durable claims and bounded, provider-idempotent lifecycle email retries."""
from __future__ import annotations
import hashlib
import logging
from typing import Any
import sb_clients

logger = logging.getLogger(__name__)

def rpc(name: str, data: dict) -> Any:
    result = sb_clients.sb_post_as_service('/rpc/' + name, data)
    if result is None:
        raise RuntimeError('Lifecycle database operation failed: ' + name)
    return result

async def send_once(delivery_key: str, payload: dict) -> dict:
    from email_sender import send_via_resend
    claim = rpc('lifecycle_claim', {'p_key': delivery_key, 'p_payload': payload})
    if claim.get('state') == 'sent':
        return {'id': claim.get('provider_id'), 'already_sent': True}
    if claim.get('state') != 'claimed':
        raise RuntimeError('Lifecycle delivery ' + claim.get('state', 'unavailable'))
    try:
        # Freeze the message on the first claim. Retrying tomorrow must not
        # change its date, copy, recipient, or sender under the same key.
        if claim['payload'].get('to_email') != payload.get('to_email'):
            raise RuntimeError('Lifecycle recipient changed; original message held')
        result = await send_via_resend(**claim['payload'], idempotency_key=(
            'lifecycle/' + hashlib.sha256(delivery_key.encode()).hexdigest()))
        if not result.get('id'):
            raise RuntimeError('Provider did not return a message id')
        if not rpc('lifecycle_finish', {'p_key': delivery_key, 'p_token': claim['token'],
                                       'p_provider_id': result['id']}):
            raise RuntimeError('Lifecycle delivery acknowledgement failed')
        return result
    except Exception as exc:
        # Do not persist provider exception text: it can contain a recipient.
        try:
            rpc('lifecycle_fail', {'p_key': delivery_key, 'p_token': claim['token'],
                                   'p_error': type(exc).__name__})
        except Exception:
            logger.warning('Lifecycle retry recording failed; lease will expire')
        raise
