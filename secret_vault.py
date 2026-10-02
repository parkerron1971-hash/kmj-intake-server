"""Chief's computer: server-only encrypted login material (arc PR1).

No route or model tool exposes this module. The later Secure Entry controller
must authenticate the owner/manager, validate the live hold and exact host, and
require danger step-up before saving/reusing a secret. Encryption is not approval.

Only login persistence is enabled. Cards, CVCs, OTPs, arbitrary custom values and
browser session snapshots cannot be saved through this first vault. The card
policy remains an owner decision; CVC/OTP must never become reusable secrets.

The authenticated envelope binds ciphertext to a business, row and exact host.
Copying ciphertext to another tenant or relabeling its host cannot grant access.
Keep VAULT_ENCRYPTION_KEY in server secret storage; never reuse the TIN key.
"""
from __future__ import annotations

import json
import os
import re
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

MAX_FIELD_CHARS = 4096
MAX_CIPHERTEXT_CHARS = 32768
METADATA_COLUMNS = (
    'id,business_id,kind,host,label,display,created_by,created_at,'
    'last_used_at,use_count,status'
)
# Only the future controller's authenticated fill path may request this column.
FILL_COLUMNS = 'id,business_id,kind,host,status,fields_ciphertext'


def _fernet() -> Fernet:
    key = (os.environ.get('VAULT_ENCRYPTION_KEY') or '').strip()
    if not key:
        raise HTTPException(500, 'Vault encryption is not configured.')
    try:
        return Fernet(key.encode('ascii'))
    except (ValueError, UnicodeError):
        raise HTTPException(500, 'Vault encryption key is invalid.') from None


def normalize_host(host: str) -> str:
    """An exact DNS host, never a URL, wildcard, port, IP or userinfo."""
    if not isinstance(host, str) or not host or host != host.strip():
        raise HTTPException(422, 'An exact supplier host is required.')
    try:
        canonical = host.removesuffix('.').encode('idna').decode('ascii').lower()
    except UnicodeError:
        raise HTTPException(422, 'An exact supplier host is required.') from None
    labels = canonical.split('.')
    if (len(canonical) > 253 or len(labels) < 2 or labels[-1].isdigit()
            or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', s) for s in labels)
            or canonical.endswith(('.localhost', '.local', '.internal'))):
        raise HTTPException(422, 'An exact supplier host is required.')
    return canonical


def _binding(business_id: str, secret_id: str, host: str, kind: str) -> dict:
    try:
        bid, sid = str(UUID(str(business_id))), str(UUID(str(secret_id)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, 'Valid business and secret identifiers are required.') from None
    if kind != 'login':
        raise HTTPException(422, 'Only saved logins are enabled for this vault.')
    return {'business_id': bid, 'secret_id': sid, 'host': normalize_host(host), 'kind': kind}


def _login_fields(fields: dict) -> dict:
    # Strict keys also refuse cvc/code/otp even when nested or differently named.
    if not isinstance(fields, dict) or set(fields) != {'username', 'password'}:
        raise HTTPException(422, 'A saved login requires only username and password.')
    if any(not isinstance(v, str) or not v or len(v) > MAX_FIELD_CHARS
           for v in fields.values()):
        raise HTTPException(422, 'Login fields must be nonempty bounded strings.')
    # Password whitespace is meaningful. Never trim or normalize secret values.
    return dict(fields)


def encrypt(fields: dict, *, business_id: str, secret_id: str, host: str,
            kind: str = 'login') -> str:
    """Create ciphertext for this row only. Returns no displayable credential."""
    binding = _binding(business_id, secret_id, host, kind)
    envelope = {'version': 1, **binding, 'fields': _login_fields(fields)}
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > 16000:
        raise HTTPException(422, 'Saved login exceeds the encrypted payload limit.')
    return _fernet().encrypt(encoded).decode('ascii')


def decrypt(ciphertext: str, *, business_id: str, secret_id: str, host: str,
            kind: str = 'login') -> dict:
    """Server fill primitive. Never return its result through an API/model tool.

    This does not check row revocation, actor role, hold lifetime or step-up.
    PR3 must check those immediately before invoking this primitive. Python
    strings cannot promise physical memory zeroization; callers minimize lifetime.
    """
    binding = _binding(business_id, secret_id, host, kind)
    cipher = _fernet()  # A configuration error is distinct from invalid storage.
    if not isinstance(ciphertext, str) or not 1 <= len(ciphertext) <= MAX_CIPHERTEXT_CHARS:
        raise HTTPException(500, 'Stored secret cannot be decrypted.')
    try:
        envelope = json.loads(cipher.decrypt(ciphertext.encode('ascii')))
        if (not isinstance(envelope, dict)
                or set(envelope) != {'version', 'fields', *binding}
                or type(envelope['version']) is not int or envelope['version'] != 1
                or any(envelope.get(k) != v for k, v in binding.items())):
            raise ValueError('invalid envelope')
        return _login_fields(envelope['fields'])
    except (InvalidToken, ValueError, UnicodeError, TypeError, KeyError, HTTPException):
        # Do not interpolate ciphertext, fields, or a provider exception into errors.
        raise HTTPException(500, 'Stored secret cannot be decrypted.') from None


def secret_metadata(row: dict) -> dict:
    """Section 7 SecretMeta allowlist. No ciphertext or arbitrary nested fields."""
    keys = ('id', 'kind', 'host', 'label', 'created_at', 'last_used_at', 'use_count')
    result = {k: row.get(k) for k in keys}
    # Do not copy a caller-controlled display object (or plaintext username).
    result['display'] = {'username_hint': '••••'} if row.get('kind') == 'login' else {}
    return result
