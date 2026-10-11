"""Read-only Square OAuth pilot. No booking writes, imports, or customer messages."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

import sb_clients

SCOPES = (
    "APPOINTMENTS_READ", "APPOINTMENTS_ALL_READ", "MERCHANT_PROFILE_READ",
)
API_VERSION = "2026-09-16"


@dataclass(frozen=True)
class Config:
    environment: str
    app_id: str
    secret: str = field(repr=False)
    encryption_key: str = field(repr=False)
    callback: str
    app_url: str
    owners: frozenset[str]

    @property
    def base(self):
        return "https://connect.squareupsandbox.com" if self.environment == "sandbox" else "https://connect.squareup.com"


def config() -> Config:
    if os.getenv("SQUARE_ENABLED", "false").lower() != "true":
        raise HTTPException(503, "Square connection is not enabled.")
    environment = os.getenv("SQUARE_ENVIRONMENT", "sandbox")
    prefix = "SQUARE_" + environment.upper()
    values = [os.getenv(prefix + "_APPLICATION_ID", ""), os.getenv(prefix + "_APPLICATION_SECRET", ""),
              os.getenv("SQUARE_TOKEN_ENCRYPTION_KEY", ""), os.getenv("SQUARE_REDIRECT_URI", ""),
              os.getenv("SQUARE_APP_RETURN_URL", "https://system.mysolutionist.app")]
    owners = frozenset(x.strip() for x in os.getenv("SQUARE_PILOT_OWNER_IDS", "").split(",") if x.strip())
    try:
        if environment not in {"sandbox", "production"} or not all(values) or not owners:
            raise ValueError()
        Fernet(values[2].encode())
        for url in values[3:]:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError()
        if urlsplit(values[3]).path != "/connect/square/callback":
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(503, "Square connection configuration is incomplete.") from None
    return Config(environment, *values, owners)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def seal(cfg: Config, payload: dict) -> str:
    return Fernet(cfg.encryption_key.encode()).encrypt(json.dumps(payload).encode()).decode()


def unseal(cfg: Config, value: str) -> dict:
    try:
        return json.loads(Fernet(cfg.encryption_key.encode()).decrypt(value.encode()))
    except (InvalidToken, ValueError, TypeError, AttributeError):
        raise HTTPException(503, "Square credentials are unavailable.") from None


async def db(method: str, path: str, *, body=None, params=None):
    # Unlike fail-soft helpers, a failed state transaction must never look like no row.
    try:
        headers = sb_clients.sb_headers_service()
        base = sb_clients.sb_url()
        if not base:
            raise ValueError()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(method, base + "/rest/v1/" + path,
                                            headers=headers, json=body, params=params)
        if not response.is_success:
            raise ValueError()
        return response.json()
    except (httpx.HTTPError, ValueError, RuntimeError):
        # Never include upstream bodies, headers, tokens, state or callback codes.
        raise HTTPException(503, "Square connection storage is unavailable.") from None


async def rpc(name: str, **params):
    return await db("POST", "rpc/square_" + name, body=params)


async def connection(business_id: UUID | str, cfg: Config):
    rows = await db("GET", "square_connections", params={
        "business_id": "eq." + str(business_id), "environment": "eq." + cfg.environment, "select": "*", "limit": "1"})
    return rows[0] if rows else None


async def square(cfg: Config, method: str, path: str, *, token=None, body=None, params=None, revoke=False):
    headers = {"Square-Version": API_VERSION, "Content-Type": "application/json"}
    if revoke:
        headers["Authorization"] = "Client " + cfg.secret
    elif token:
        headers["Authorization"] = "Bearer " + token
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(method, cfg.base + path, headers=headers, json=body, params=params)
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Square is temporarily unavailable. Try again.") from None
    if response.status_code == 429:
        raise HTTPException(503, "Square is busy. Try again shortly.")
    if response.status_code in (401, 403):
        errors = payload.get("errors", []) if isinstance(payload, dict) else []
        # Recognize only the observed provider condition; never relay diagnostics.
        if path == "/v2/bookings" and isinstance(errors, list) and any(
            isinstance(error, dict) and error.get("code") == "UNAUTHORIZED"
            and error.get("detail") == "Merchant not onboarded to Appointments"
            for error in errors
        ):
            raise HTTPException(422, {"code": "square_appointments_setup_required"})
        raise HTTPException(409, {"code": "square_authorization_required"})
    if not response.is_success or not isinstance(payload, dict) or payload.get("errors"):
        raise HTTPException(502, "Square could not complete the request. Try again.")
    return payload


def token_payload(payload: dict) -> dict:
    try:
        if not all(isinstance(payload.get(k), str) and payload[k] for k in ("access_token", "refresh_token", "merchant_id", "expires_at")):
            raise ValueError()
        expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(502, "Square returned an incomplete authorization.") from None
    return {k: payload[k] for k in ("access_token", "refresh_token", "merchant_id", "expires_at")}


async def access_token(business_id: UUID | str, cfg: Config) -> str:
    row = await connection(business_id, cfg)
    if not row or row["status"] != "connected":
        raise HTTPException(409, "Connect Square first.")
    tokens = unseal(cfg, row["credentials"])
    if datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc) + timedelta(days=7):
        return tokens["access_token"]
    refreshed = token_payload(await square(cfg, "POST", "/oauth2/token", body={
        "client_id": cfg.app_id, "client_secret": cfg.secret, "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"]}))
    if refreshed["merchant_id"] != row["merchant_id"]:
        raise HTTPException(502, "Square returned an inconsistent authorization.")
    saved = await rpc("refresh", p_business=str(business_id), p_environment=cfg.environment,
                      p_revision=row["revision"], p_credentials=seal(cfg, refreshed), p_expires=refreshed["expires_at"])
    if saved:
        return refreshed["access_token"]
    # A concurrent disconnect must win; a concurrent refresh may have won the CAS.
    current = await connection(business_id, cfg)
    if not current or current["status"] != "connected":
        raise HTTPException(409, "Square was disconnected.")
    return unseal(cfg, current["credentials"])["access_token"]
