"""
cloudflare_saas.py — Cloudflare for SaaS custom-hostname automation.

When a practitioner connects their own domain, we register it as a Cloudflare
"custom hostname" so Cloudflare issues + AUTO-RENEWS the TLS cert and proxies
the domain to our fallback origin (the Railway backend, which serves the
practitioner sites). The practitioner adds a CNAME to our Cloudflare-for-SaaS
target + the SSL-validation record Cloudflare returns; once both go active the
domain serves over HTTPS — at any scale (Railway's per-service domain cap does
not apply, because Cloudflare fronts it).

Everything FAILS OPEN: with no CF_API_TOKEN / CF_ZONE_ID configured, these
return None and the domain flow falls back to plain ownership verification
(no auto-cert). Env:
  CF_API_TOKEN          — token scoped to the zone (SSL:Edit + Custom Hostnames:Edit)
  CF_ZONE_ID            — the mysolutionist.app zone id
  CF_SAAS_CNAME_TARGET  — the hostname customers CNAME their domain to
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("cloudflare_saas")

_API = "https://api.cloudflare.com/client/v4"


def _token() -> str:
    return os.environ.get("CF_API_TOKEN", "").strip()


def _zone() -> str:
    return os.environ.get("CF_ZONE_ID", "").strip()


def cname_target() -> str:
    return os.environ.get("CF_SAAS_CNAME_TARGET", "").strip()


def enabled() -> bool:
    return bool(_token() and _zone())


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def _short_host(name: str, domain: str) -> str:
    """The record NAME as most DNS providers want it — just the part BEFORE
    the domain (Namecheap/GoDaddy/etc. append the domain automatically). The
    apex is '@'."""
    n = str(name or "").rstrip(".")
    d = str(domain or "").rstrip(".").lower()
    if d and n.lower().endswith("." + d):
        return n[:-(len(d) + 1)]
    if n.lower() == d:
        return "@"
    return n or "@"


def _dcv_records(ssl: Dict[str, Any], domain: str) -> List[Dict[str, str]]:
    """The ONE SSL-validation record the practitioner adds. We create the
    hostname with the TXT method, so we surface only the TXT record (never
    both TXT + a delegation CNAME — a CNAME can't coexist with a TXT at the
    same name, which silently breaks validation)."""
    out: List[Dict[str, str]] = []
    for rec in (ssl.get("validation_records") or []):
        if rec.get("txt_name"):
            out.append({"type": "TXT", "host": _short_host(str(rec.get("txt_name")), domain),
                        "value": str(rec.get("txt_value") or ""),
                        "note": ("Validates your SSL certificate. Enter the Name exactly "
                                 "as shown — your provider adds your domain automatically.")})
            break
        if rec.get("http_url"):
            out.append({"type": "HTTP file", "host": str(rec.get("http_url")),
                        "value": str(rec.get("http_body") or ""),
                        "note": "SSL validation file."})
            break
    return out


def _find(hostname: str) -> Optional[Dict[str, Any]]:
    try:
        r = httpx.get(f"{_API}/zones/{_zone()}/custom_hostnames",
                      headers=_headers(), params={"hostname": hostname}, timeout=12.0)
        if r.status_code >= 400:
            return None
        res = r.json().get("result") or []
        return res[0] if res else None
    except Exception as e:
        logger.info(f"[cf] lookup failed for {hostname}: {e}")
        return None


def _shape(ch: Dict[str, Any]) -> Dict[str, Any]:
    ssl = ch.get("ssl") or {}
    hostname = str(ch.get("hostname") or "")
    dns: List[Dict[str, str]] = []
    tgt = cname_target()
    if tgt:
        dns.append({"type": "CNAME", "host": "@", "value": tgt,
                    "note": "Points your domain at your site. Add a second CNAME with "
                            "Name 'www' and the same value."})
    dns += _dcv_records(ssl, hostname)
    active = ch.get("status") == "active" and ssl.get("status") == "active"
    return {
        "id": ch.get("id"),
        "cname_target": tgt,
        "hostname_status": ch.get("status"),
        "ssl_status": ssl.get("status"),
        "active": active,
        "dns": dns,
    }


def create_custom_hostname(hostname: str) -> Optional[Dict[str, Any]]:
    """Register (idempotently) a custom hostname; Cloudflare starts issuing the
    cert. Returns {id, cname_target, dns[], hostname_status, ssl_status, active}
    or None when disabled / on error (caller falls back)."""
    if not enabled() or not hostname:
        return None
    existing = _find(hostname)
    if existing:
        return _shape(existing)
    try:
        r = httpx.post(
            f"{_API}/zones/{_zone()}/custom_hostnames", headers=_headers(),
            json={"hostname": hostname,
                  "ssl": {"method": "txt", "type": "dv",
                          "settings": {"min_tls_version": "1.2"}}},
            timeout=15.0)
        if r.status_code >= 400:
            logger.warning(f"[cf] create {hostname} → {r.status_code}: {r.text[:200]}")
            return None
        return _shape(r.json().get("result") or {})
    except Exception as e:
        logger.warning(f"[cf] create failed for {hostname}: {e}")
        return None


def hostname_status(hostname: str) -> Optional[Dict[str, Any]]:
    """Poll a custom hostname's live status (hostname + SSL). None when
    disabled; {found: False} when not registered."""
    if not enabled() or not hostname:
        return None
    ch = _find(hostname)
    if not ch:
        return {"found": False}
    return {"found": True, **_shape(ch)}


def delete_custom_hostname(hostname: str) -> None:
    """Best-effort removal (on disconnect)."""
    if not enabled() or not hostname:
        return
    ch = _find(hostname)
    if not ch or not ch.get("id"):
        return
    try:
        httpx.delete(f"{_API}/zones/{_zone()}/custom_hostnames/{ch['id']}",
                     headers=_headers(), timeout=12.0)
    except Exception as e:
        logger.info(f"[cf] delete failed for {hostname}: {e}")
