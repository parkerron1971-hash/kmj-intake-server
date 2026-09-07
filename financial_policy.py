"""Durable business financial lockout, independent of prompts and settings JSON.

Every operational provider write checks this store immediately before dispatch.
Reads and the platform subscription billing path remain separate. A lock does
not cancel arrangements already issued to an external provider.
"""
from urllib.parse import quote

from fastapi import HTTPException
import sb_clients


def _rows(path):
    result = sb_clients.sb_get_as_service(path)
    if not isinstance(result, list):
        raise HTTPException(503, 'Financial policy could not be verified. No financial action was sent.')
    return result


def policy_for(business_id):
    if not business_id:
        raise HTTPException(409, 'A business is required for this financial action.')
    rows = _rows('/business_financial_policies?business_id=eq.' + quote(str(business_id), safe='') + '&select=*&limit=1')
    return rows[0] if rows else {'business_id': str(business_id), 'mode': 'standard', 'provider_review_required': False}


def require_operational_write(business_id):
    policy = policy_for(business_id)
    if policy.get('mode') != 'standard':
        raise HTTPException(403, 'This business is view-only for finances. Charges, refunds, transfers, payment links, and external accounting writes are disabled.')


def require_stripe_write(account_id):
    """Resolve persisted ownership, never caller-supplied metadata alone."""
    if not account_id:
        raise HTTPException(409, 'A connected account is required.')
    encoded = quote(str(account_id), safe='')
    businesses = _rows('/businesses?stripe_account_id=eq.' + encoded + '&select=id')
    # Historical bindings remain protected after disconnect or account changes.
    bindings = _rows('/business_financial_account_locks?stripe_account_id=eq.' + encoded + '&select=business_id')
    ids = {str(row['id']) for row in businesses} | {str(row['business_id']) for row in bindings}
    if not ids:
        raise HTTPException(409, 'The payment account is not associated with a business.')
    for business_id in ids:
        require_operational_write(business_id)
