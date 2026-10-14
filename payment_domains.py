"""Apple Pay and Google Pay inside a church's own give page.

Stripe's hosted Checkout page shows the wallet buttons on Stripe's own
domain. Once the payment form is embedded in the church's page
(giving_router, embedded Checkout), the wallets appear only on domains
registered as Payment Method Domains on the account that runs the
charge. Gifts are direct charges, so that is the church's own connected
account, and Connect platforms must register through the API
(https://docs.stripe.com/payments/payment-methods/pmd-registration).
Apple also fetches a domain-association file from each domain.

- give_domains(): the addresses a business's give page is served at,
  meaning its platform subdomain plus its custom domain (stored as the
  apex) and that domain's www twin.
- register_give_domains(): POST /v1/payment_method_domains on the
  connected account, once per domain. "Already registered" counts as
  done, so re-running is safe.
- APPLE_ASSOCIATION_PATH / apple_association(): the file every served
  site answers at /.well-known/. It is vendored from
  https://stripe.com/files/apple-pay/apple-developer-merchantid-domain-association
  so Apple's check never depends on a live fetch from Stripe.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from business_sites_helpers import PUBLIC_DOMAIN

logger = logging.getLogger(__name__)

STRIPE_API_BASE = "https://api.stripe.com/v1"
APPLE_ASSOCIATION_PATH = "/.well-known/apple-developer-merchantid-domain-association"
_ASSOCIATION_FILE = Path(__file__).parent / "assets" / "apple-developer-merchantid-domain-association"
_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_association_cache: Optional[str] = None


def apple_association() -> Optional[str]:
    """Stripe's Apple Pay domain-association file, or None if the vendored
    copy is missing (the caller then 404s instead of serving junk)."""
    global _association_cache
    if _association_cache is None:
        try:
            _association_cache = _ASSOCIATION_FILE.read_text(encoding="ascii").strip()
        except OSError as e:
            logger.warning(f"[payment_domains] association file unreadable: {e}")
            return None
    return _association_cache or None


def give_domains(slug: Optional[str], custom_domain: Optional[str]) -> List[str]:
    """Every host a business's /give page is served on. A custom domain is
    stored as the apex (connect strips www) and the www host serves the
    same site, so both are registered."""
    out: List[str] = []
    s = str(slug or "").strip().lower()
    if s:
        out.append(f"{s}.{PUBLIC_DOMAIN}")
    cd = str(custom_domain or "").strip().lower().strip("/")
    if cd.startswith("www."):
        cd = cd[4:]
    if cd:
        out += [cd, f"www.{cd}"]
    seen, clean = set(), []
    for d in out:
        if _DOMAIN_RE.match(d) and d not in seen:
            seen.add(d)
            clean.append(d)
    return clean


def _already_registered(resp: httpx.Response) -> bool:
    if resp.status_code != 400:
        return False
    try:
        msg = str(((resp.json() or {}).get("error") or {}).get("message") or "").lower()
    except ValueError:
        return False
    return "already" in msg


def register_give_domains(stripe_account_id: str, domains: List[str]) -> Dict[str, str]:
    """Register each domain on the church's connected account. Returns
    {domain: 'registered' | 'already' | 'failed'}. Never raises: a wallet
    button that doesn't show is not worth failing a settings save over,
    and the result says which domains still need a look."""
    key = os.environ.get("STRIPE_SECRET_KEY") or ""
    results: Dict[str, str] = {}
    if not key or not re.fullmatch(r"acct_[A-Za-z0-9]+", str(stripe_account_id or "")):
        return {d: "failed" for d in domains}
    with httpx.Client(timeout=15.0) as client:
        for d in domains:
            try:
                resp = client.post(
                    f"{STRIPE_API_BASE}/payment_method_domains",
                    auth=(key, ""),
                    headers={"Stripe-Account": stripe_account_id},
                    data={"domain_name": d},
                )
            except httpx.HTTPError as e:
                logger.warning(f"[payment_domains] {d} on {stripe_account_id}: {e}")
                results[d] = "failed"
                continue
            if resp.status_code < 400:
                results[d] = "registered"
            elif _already_registered(resp):
                results[d] = "already"
            else:
                logger.warning(f"[payment_domains] {d} on {stripe_account_id}: "
                               f"{resp.status_code} {resp.text[:200]}")
                results[d] = "failed"
    return results


def register_for_business(business: Dict[str, Any], sites: List[Dict[str, Any]]) -> Dict[str, str]:
    """All give-page domains of one business, registered on its account.
    `sites` are business_sites rows with slug and custom_domain."""
    domains: List[str] = []
    for s in sites or []:
        for d in give_domains(s.get("slug"), s.get("custom_domain")):
            if d not in domains:
                domains.append(d)
    if not domains:
        return {}
    return register_give_domains(str(business.get("stripe_account_id") or ""), domains)
