"""
tin_crypto.py — Rails Arc 2 — encryption for contractor TINs.

A TIN (SSN or EIN) is the most sensitive datum this platform stores.
Rules, enforced here so every caller inherits them:

  * Fernet (AES-128-CBC + HMAC, from the `cryptography` package that
    PyJWT[crypto] already ships) with the key in TIN_ENCRYPTION_KEY —
    an env-only secret, never in the database, so a DB leak alone
    exposes nothing.
  * Ciphertext in contractors.tin_encrypted; display uses tin_last4.
  * decrypt() has exactly one production caller: the owner-gated 1099
    draft-PDF endpoint. Add another only with a reason of that weight.
  * Missing key -> loud 500, never a silent plaintext fallback.

Key generation (one-time, already done for Railway):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import os
import re

from fastapi import HTTPException


def _fernet():
    from cryptography.fernet import Fernet

    key = (os.environ.get("TIN_ENCRYPTION_KEY") or "").strip()
    if not key:
        raise HTTPException(
            500, "TIN encryption is not configured (TIN_ENCRYPTION_KEY missing).")
    try:
        return Fernet(key.encode("ascii"))
    except Exception:
        raise HTTPException(500, "TIN_ENCRYPTION_KEY is not a valid Fernet key.")


def normalize_tin(raw: str) -> str:
    """Digits only. 9 digits or it isn't a TIN."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 9:
        raise HTTPException(400, "A TIN is 9 digits (SSN or EIN).")
    return digits


def encrypt_tin(raw: str) -> tuple[str, str]:
    """(ciphertext, last4) for a raw TIN in any common format."""
    digits = normalize_tin(raw)
    token = _fernet().encrypt(digits.encode("ascii")).decode("ascii")
    return token, digits[-4:]


def decrypt_tin(ciphertext: str) -> str:
    """The 9 raw digits. See module docstring for who may call this."""
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt((ciphertext or "").encode("ascii")).decode("ascii")
    except InvalidToken:
        raise HTTPException(500, "Stored TIN cannot be decrypted (key mismatch).")


def format_tin(digits: str, tin_type: str) -> str:
    """SSN 123-45-6789 / EIN 12-3456789 formatting for the draft form."""
    d = re.sub(r"\D", "", digits or "")
    if len(d) != 9:
        return digits or ""
    return f"{d[:3]}-{d[3:5]}-{d[5:]}" if tin_type == "ssn" else f"{d[:2]}-{d[2:]}"
