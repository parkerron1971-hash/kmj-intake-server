"""
giving_router.py — online giving for ministry / nonprofit verticals.

THE GAP THIS CLOSES
  A congregant could not give online. The vertical-readiness audit scored
  ministries launchable-except-for-this: statements, donor reports and 990
  prep all existed, but the money they report on could only arrive by
  check or by the operator hand-writing an invoice. This adds the public
  give page (https://<slug>.mysolutionist.app/give), one-time and monthly
  gifts through Stripe Connect Checkout, designated funds, and the
  Pub 1771 acknowledgment email.

ARCHITECTURE (load-bearing — do not "improve" these without reading
giving_statements.py's DATA SOURCE, HONESTLY note):

  1. GIVING RIDES THE INVOICES TABLE. A completed online gift lands as a
     PAID invoices row (status='paid', paid_at, payment_method='stripe').
     That single fact is what keeps every downstream surface working
     unchanged: giving_statements (IRS Pub 1771), gl_reports_t4
     .donor_report, prep_990, and gl_engine's restricted-fund routing all
     read paid invoices. Migrating giving off invoices is a future arc.

  2. DESIGNATED FUNDS map onto invoices.category. A gift to any fund
     other than the general fund gets category='restricted' — the EXACT
     token gl_engine._RESTRICTED_HINTS matches, so nonprofit-family
     businesses route it to 4200 Restricted Contributions. The fund's
     NAME travels in the line-item description + notes so donor-facing
     documents can show it. General-fund gifts leave category empty,
     which giving_statements renders as "General".

  3. DONATIONS ARE NOT AN OFFERING. offerings-migration.sql +
     module_spec_generator deliberately exclude a 'donation' category —
     the give surface is its own thing, never a store item.

  4. STRIPE DISCIPLINE: sessions are created through payments_core (the
     adapter seam) with metadata {source_type:'gift', source_id:<minted
     uuid>} + business/fund/giver keys mirrored onto the payment intent
     (one-time) or subscription (monthly). The Connect webhook
     (stripe_connect_router) turns those events into paid invoices via
     record_gift_* below; stripe_webhook_events dedupes deliveries and
     the deterministic invoice_number ('GIVE-<stripe ref>') dedupes
     re-processing.

RECURRING GIFTS — the mechanics chosen (documented because it is an
ADR-level choice):
  Monthly gifts use Checkout mode=subscription with an inline price
  (price_data + recurring[interval]=month) created on the CONNECTED
  account — no pre-created Price objects to manage. Attribution rides
  subscription metadata: Stripe copies subscription_data.metadata onto
  the Subscription, and every cycle's invoice.paid event carries it back
  in invoice.subscription_details.metadata. That means NO linkage table:
  each cycle self-describes (business_id, fund, giver email) and lands
  as its own paid invoice keyed GIVE-<stripe invoice id>. The first
  cycle is recorded ONLY from invoice.paid (billing_reason=
  subscription_create) — checkout.session.completed for subscription
  sessions is deliberately a no-op so the same dollar can't post twice.
  customer.subscription.deleted is handled gracefully (operator
  notification; nothing to unwind — past cycles are real gifts).

SENSITIVITY: giving data is access-isolated by design. This module
writes invoices + contacts and posts an operator notification that
deliberately does NOT name the giver. Individual giving stays on the
existing Donors report + statements surfaces.

Chief-verb candidates deliberately NOT added this wave (action_registry
untouched): enable_giving / configure_funds / share_give_link.
"""
from __future__ import annotations

import asyncio
import html as _html_mod
import json
import logging
import re
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

import church_keys
import sb_clients
from auth_supabase import AuthedUser, require_user
from business_sites_helpers import PUBLIC_DOMAIN, ensure_business_site

logger = logging.getLogger("giving_router")

router = APIRouter(tags=["giving"])

# ─── Config constants ────────────────────────────────────────────────

# Per-gift bounds. The floor blocks card-testing $0.50 sprays; the
# ceiling blocks a typo'd $250,000 that would only ever be reversed.
MIN_GIFT_CENTS = 100            # $1
MAX_GIFT_CENTS = 2_500_000      # $25,000

MAX_FUNDS = 12
MAX_FUND_NAME_LEN = 40
MAX_PRESETS = 6
DEFAULT_PRESETS = [25, 50, 100, 250]
DEFAULT_FUNDS = ["General"]

# The category token gl_engine._RESTRICTED_HINTS matches EXACTLY —
# designated gifts must carry it or restricted-fund GL routing (4200)
# silently stops firing. Pinned by test_online_giving.
RESTRICTED_CATEGORY = "restricted"

_FREQUENCIES = ("once", "weekly", "biweekly", "monthly")

# How each recurring frequency repeats in Stripe: (interval, interval_count).
# "Twice a month" (1st and 15th) has no Stripe interval, so it isn't
# offered; every two weeks is the honest nearest.
RECURRING = {"weekly": ("week", 1), "biweekly": ("week", 2), "monthly": ("month", 1)}
_FREQUENCY_WORDS = {"weekly": "weekly", "biweekly": "every-two-weeks", "monthly": "monthly"}

# "Cover the fee": the gift is grossed up so the church receives the
# amount the giver chose. Stripe's standard US card price; a church's own
# rate (or a bank payment, 0.8% capped at $5) can be lower, which is why
# the page says "about".
CARD_FEE_PERCENT = 0.029
CARD_FEE_FIXED_CENTS = 30


def frequency_word(frequency: Optional[str]) -> str:
    """'weekly' | 'every-two-weeks' | 'monthly' — the words receipts,
    notes and notifications use. Anything unknown reads as monthly, the
    only recurring gift that existed before."""
    return _FREQUENCY_WORDS.get(str(frequency or "").lower(), "monthly")


def covered_fee_cents(amount_cents: int) -> int:
    """What to add so the church nets `amount_cents` after the card fee."""
    import math
    amount_cents = int(amount_cents or 0)
    if amount_cents <= 0:
        return 0
    gross = math.ceil((amount_cents + CARD_FEE_FIXED_CENTS) / (1 - CARD_FEE_PERCENT))
    return gross - amount_cents


# ─── Small helpers ───────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def giving_settings(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """settings.giving sub-dict; tolerate missing/malformed."""
    raw = (settings or {}).get("giving") or {}
    return raw if isinstance(raw, dict) else {}


def configured_funds(cfg: Dict[str, Any]) -> List[str]:
    funds = cfg.get("funds")
    if isinstance(funds, list):
        clean = [str(f).strip() for f in funds if str(f or "").strip()]
        if clean:
            return clean[:MAX_FUNDS]
    return list(DEFAULT_FUNDS)


def preset_amounts(cfg: Dict[str, Any]) -> List[int]:
    raw = cfg.get("preset_amounts")
    if isinstance(raw, list):
        out: List[int] = []
        for v in raw:
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if 1 <= n <= MAX_GIFT_CENTS // 100 and n not in out:
                out.append(n)
        if out:
            return out[:MAX_PRESETS]
    return list(DEFAULT_PRESETS)


# A church's general fund often goes by what the gift is, not "General":
# tithes and offerings are unrestricted giving (Love City's Subsplash funds
# were Tithes and Offering, 2026-10-14). Filing them as donor-restricted
# would post every Sunday gift to restricted income.
_GENERAL_FUND_NAMES = {"", "general", "tithe", "tithes", "offering", "offerings",
                       "tithes and offerings", "tithes & offerings", "tithe and offering"}


def is_designated(fund: Optional[str]) -> bool:
    """A gift to any fund other than the general fund is donor-DESIGNATED
    (restricted) by definition — the giver constrained its use. Rubric,
    not a lookup table: the general fund in any casing/spacing (with or
    without the word Fund, and by its church names, tithes and offerings)
    is the unrestricted default; everything else is designated."""
    norm = " ".join(str(fund or "").lower().split())
    if norm.endswith(" fund"):
        norm = norm[: -len(" fund")]
    return norm not in _GENERAL_FUND_NAMES


def fund_label(fund: Optional[str]) -> str:
    """Display label: 'General' → 'General Fund', 'Building Fund' stays,
    'Tithes' and 'Offering' stay as they are (nobody says 'Tithes Fund').
    Used in line descriptions ('Gift — Building Fund') and receipts."""
    name = str(fund or "General").strip() or "General"
    norm = " ".join(name.lower().split())
    if "fund" in norm or (norm in _GENERAL_FUND_NAMES and norm != "general"):
        return name
    return f"{name} Fund"


def giving_is_active(biz: Dict[str, Any]) -> bool:
    """The ONE activation rubric, used by the page, the checkout endpoint
    and the composer connection: nonprofit-family vertical + operator
    enabled it + Stripe connected (a give page that can't take a gift is
    dead weight)."""
    import vertical_family
    if not vertical_family.is_nonprofit_like(biz.get("type")):
        return False
    if not giving_settings(biz.get("settings")).get("enabled"):
        return False
    return bool(biz.get("stripe_account_id"))


def give_url_for_site(site: Dict[str, Any]) -> str:
    """Canonical public give URL — same shape as booking_url_for_site."""
    slug = (site or {}).get("slug") or "business"
    return f"https://{slug}.{PUBLIC_DOMAIN}/give"


# ─── Rate limiting (public endpoint) ─────────────────────────────────
# Same in-process sliding-window pattern as public_site's contact form.
# Checked BEFORE any read or write — the limiter is the first line of
# the checkout endpoint by contract (pinned in tests). 10/min per IP:
# generous for a family device, hostile to a card-testing script.

_give_rate: Dict[str, List[float]] = {}
GIVE_RATE_MAX_PER_MIN = 10


def _check_give_rate(ip: str) -> bool:
    now = time.time()
    cutoff = now - 60
    bucket = [t for t in _give_rate.get(ip, []) if t > cutoff]
    if len(bucket) >= GIVE_RATE_MAX_PER_MIN:
        _give_rate[ip] = bucket
        return False
    bucket.append(now)
    _give_rate[ip] = bucket
    return True


# ─── Owner config endpoints ──────────────────────────────────────────


def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    """Owner gate — same shape as booking_page_router._require_owner.
    Giving config is owner-only on purpose (restricted-modules
    discipline: giving is pastoral-sensitivity data)."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        f"&select=id,name,type,owner_id,settings,stripe_account_id&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")
    return rows[0]


def _config_payload(biz: Dict[str, Any], site: Dict[str, Any]) -> Dict[str, Any]:
    import vertical_family
    cfg = giving_settings(biz.get("settings"))
    return {
        "ok": True,
        "business_id": biz.get("id"),
        # eligible = the vertical can have giving at all; the frontend
        # hides the surface entirely when False.
        "eligible": vertical_family.is_nonprofit_like(biz.get("type")),
        "enabled": bool(cfg.get("enabled")),
        "stripe_connected": bool(biz.get("stripe_account_id")),
        "active": giving_is_active(biz),
        "funds": configured_funds(cfg),
        "preset_amounts": preset_amounts(cfg),
        "message": cfg.get("message") or "",
        "slug": site.get("slug"),
        "url": give_url_for_site(site),
        **_ways_payload(biz, cfg),
    }


def _ways_payload(biz: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """The ways people give and card-or-bank, where they're switched on
    (giving_ways). `bank_possible`: the platform's giving payment set
    exists, so the church can turn bank payments on."""
    import giving_ways
    if not giving_ways.switched_on(biz.get("id")):
        return {"ways_on": False}
    return {"ways_on": True,
            "ways": giving_ways.stored_ways(cfg),
            "apps": [{"app": k, "label": v["label"], "handle": v["handle"]}
                     for k, v in giving_ways.APPS.items()],
            "bank_payments": giving_ways.bank_ready(biz, cfg),
            "bank_possible": bool(giving_ways.giving_config_id())}


@router.get("/giving/{business_id}")
def get_giving_config(
    business_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Current giving config + the canonical give URL (lazy-creates the
    business_sites row, mirroring booking-page, so the ministry always
    has a URL to share)."""
    biz = _require_owner(business_id, user)
    site, _ = ensure_business_site(biz)
    return _config_payload(biz, site)


@router.patch("/giving/{business_id}")
def patch_giving_config(
    business_id: str,
    body: Dict[str, Any],
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Update settings.giving. Owner-gated; only present keys touched.

    Body fields (all optional):
      enabled          bool
      funds            [str] — the designated-fund list the give page
                       offers. Validated: 1..12 entries, each 1..40
                       chars, deduped case-insensitively.
      preset_amounts   [int dollars] — the quick buttons (1..6 entries)
      message          str — optional line under the page heading
    """
    import vertical_family
    biz = _require_owner(business_id, user)
    if not vertical_family.is_nonprofit_like(biz.get("type")):
        # Not silently writable for other verticals — the surface is
        # gated everywhere else too; a mismatch here means a bug or a
        # hand-crafted request.
        raise HTTPException(409, "giving is available to ministry and "
                                 "nonprofit organizations")
    site, _ = ensure_business_site(biz)
    settings = dict(biz.get("settings") or {})
    cfg = dict(giving_settings(settings))

    if "enabled" in body:
        cfg["enabled"] = bool(body["enabled"])

    if "funds" in body:
        raw = body.get("funds")
        if not isinstance(raw, list):
            raise HTTPException(400, "funds must be a list of names")
        clean: List[str] = []
        seen = set()
        for f in raw:
            name = str(f or "").strip()
            if not name:
                continue
            if len(name) > MAX_FUND_NAME_LEN:
                raise HTTPException(400, f"fund name too long (max {MAX_FUND_NAME_LEN})")
            key = " ".join(name.lower().split())
            if key in seen:
                continue
            seen.add(key)
            clean.append(name)
        if not clean:
            raise HTTPException(400, "at least one fund required")
        if len(clean) > MAX_FUNDS:
            raise HTTPException(400, f"too many funds (max {MAX_FUNDS})")
        cfg["funds"] = clean

    if "preset_amounts" in body:
        raw = body.get("preset_amounts")
        if not isinstance(raw, list):
            raise HTTPException(400, "preset_amounts must be a list")
        amounts: List[int] = []
        for v in raw:
            try:
                n = int(v)
            except (TypeError, ValueError):
                raise HTTPException(400, "preset amounts must be whole dollars")
            if n < 1 or n > MAX_GIFT_CENTS // 100:
                raise HTTPException(400, "preset amounts must be between $1 and $25,000")
            if n not in amounts:
                amounts.append(n)
        if not amounts or len(amounts) > MAX_PRESETS:
            raise HTTPException(400, f"1 to {MAX_PRESETS} preset amounts")
        cfg["preset_amounts"] = amounts

    if "message" in body:
        cfg["message"] = str(body.get("message") or "").strip()[:200] or None

    if "ways" in body or "bank_payments" in body:
        import giving_ways
        if not giving_ways.switched_on(business_id):
            raise HTTPException(409, "Ways to give aren't switched on here yet")
        if "ways" in body:
            try:
                cfg["ways"] = giving_ways.clean_ways(body.get("ways"))
            except giving_ways.WayError as e:
                raise HTTPException(400, str(e))
        if "bank_payments" in body:
            want = body.get("bank_payments") is True
            if want:
                if not giving_ways.giving_config_id():
                    raise HTTPException(409, "Bank payments for giving aren't set up on the platform yet")
                ok = giving_ways.bank_available(str(biz.get("stripe_account_id") or ""))
                if ok is None:
                    raise HTTPException(503, "Stripe couldn't be checked just now. Please try again.")
                if not ok:
                    raise HTTPException(409, "Your Stripe account can't take bank payments yet. "
                                             "Stripe has to approve ACH Direct Debit for the church first.")
            cfg["bank_payments"] = want

    settings["giving"] = cfg
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{business_id}", {"settings": settings},
    )
    biz = {**biz, "settings": settings}
    if body.get("enabled") is True and biz.get("stripe_account_id"):
        _schedule_wallet_domains(biz)
    return _config_payload(biz, site)


# ─── Apple Pay / Google Pay on the give page's own domains ──────────


def _wallet_domain_sites(business_id: str) -> List[Dict[str, Any]]:
    return sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        f"&select=slug,custom_domain:site_config->>custom_domain"
    ) or []


def _register_wallet_domains(biz: Dict[str, Any]) -> Dict[str, str]:
    import payment_domains
    out = payment_domains.register_for_business(biz, _wallet_domain_sites(str(biz["id"])))
    logger.info(f"[giving] wallet domains biz={str(biz['id'])[:8]}: {out}")
    return out


def _schedule_wallet_domains(biz: Dict[str, Any]) -> None:
    """Off the request: turning giving on shouldn't wait on one Stripe
    call per domain, and a failure here only hides the wallet buttons."""
    import threading

    def run():
        try:
            _register_wallet_domains(biz)
        except Exception as e:
            logger.warning(f"[giving] wallet domains biz={str(biz.get('id'))[:8]} failed: {e}")

    threading.Thread(target=run, daemon=True).start()


@router.post("/giving/{business_id}/wallet-domains")
def register_wallet_domains(
    business_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Register the give page's addresses (platform subdomain, custom
    domain and its www) on the church's Stripe account, so Apple Pay and
    Google Pay show inside the page. Turning giving on does this already;
    re-run it after connecting a custom domain. Safe to repeat."""
    biz = _require_owner(business_id, user)
    if not biz.get("stripe_account_id"):
        raise HTTPException(409, "connect Stripe first")
    return {"ok": True, "domains": _register_wallet_domains(biz)}


def app_return_base(slug: str, site_config: Optional[Dict[str, Any]], origin: str) -> str:
    """Where a gift made inside the member app (/my/give) comes back to:
    the church's own address the member is on, so their sign-in cookie is
    there. The page's Origin is used only when it IS one of the church's
    addresses (its custom domain, with or without www., or its
    mysolutionist.app address); anything else gets the mysolutionist.app
    address. Never an address a caller made up."""
    from urllib.parse import urlparse
    home = f"{slug}.{PUBLIC_DOMAIN}"
    hosts = {home}
    dom = str((site_config or {}).get("custom_domain") or "").strip().lower()
    if dom:
        bare = dom[4:] if dom.startswith("www.") else dom
        hosts |= {bare, f"www.{bare}"}
    host = (urlparse(origin or "").hostname or "").lower()
    return f"https://{host if host in hosts else home}"


# ─── Public checkout endpoint ────────────────────────────────────────


@router.post("/public/giving/{slug}/checkout")
async def public_giving_checkout(
    slug: str, body: Dict[str, Any], request: Request,
) -> Dict[str, Any]:
    """Anonymous: create the Stripe Checkout session for a gift.

    Body: { amount_cents: int, fund?: str,
            frequency?: 'once'|'weekly'|'biweekly'|'monthly',
            cover_fee?: bool, name?: str, email?: str, embedded?: bool,
            return_to?: 'app' | 'site' }
    `return_to: 'app'` (the member app's give screen) brings the giver
    back to /my/give on the church address they're on (app_return_base);
    'site' (a hand-built site's own give page) brings them back to /give
    there.
    Returns { ok, url } — the Stripe-hosted payment page — or, when the
    page asked for embedded and the platform's publishable key is set,
    { ok, embedded: true, client_secret } for the form that mounts
    inside the give page.
    """
    # Rate limit FIRST — before any read or write (pinned in tests).
    # The trusted (last) hop, not the first: this creates Stripe sessions
    # for amounts up to $25k, and a limiter keyed on a caller-typed
    # header is decorative (2026-09-04).
    from rate_limit import trusted_client_ip
    ip = trusted_client_ip(request)
    if not _check_give_rate(ip):
        raise HTTPException(429, "Too many attempts. Please try again in a minute.")

    body = body or {}

    # ── Validate input before touching the database ──
    try:
        amount_cents = int(body.get("amount_cents") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "amount_cents must be a number")
    if amount_cents < MIN_GIFT_CENTS:
        raise HTTPException(400, "minimum gift is $1")
    if amount_cents > MAX_GIFT_CENTS:
        raise HTTPException(400, "for gifts over $25,000, please contact the organization directly")

    frequency = str(body.get("frequency") or "once").strip().lower()
    if frequency not in _FREQUENCIES:
        raise HTTPException(400, "frequency must be once, weekly, biweekly or monthly")
    pay_with = str(body.get("pay_with") or "card").strip().lower()
    if pay_with not in ("card", "bank"):
        raise HTTPException(400, "pay_with must be card or bank")
    fee_cents = covered_fee_cents(amount_cents) if body.get("cover_fee") is True else 0

    giver_name = str(body.get("name") or "").strip()[:120]
    giver_email = str(body.get("email") or "").strip().lower()[:200]
    if giver_email and ("@" not in giver_email or "." not in giver_email):
        raise HTTPException(400, "that email doesn't look right")
    if frequency in RECURRING and not giver_email:
        # Stripe needs an email to create the subscription customer, and
        # a recurring giver with no identity could never be attributed.
        raise HTTPException(400, "email is required for a recurring gift")

    # ── Resolve slug → business ──
    sites = sb_clients.sb_get_as_service(
        f"/business_sites?slug=eq.{urllib.parse.quote(slug, safe='')}"
        f"&order=updated_at.desc&limit=1&select=business_id,slug,site_config"
    ) or []
    if not sites:
        raise HTTPException(404, "not found")
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{sites[0]['business_id']}"
        f"&select=id,name,type,settings,stripe_account_id&limit=1"
    ) or []
    if not biz_rows:
        raise HTTPException(404, "not found")
    biz = biz_rows[0]

    if not giving_is_active(biz):
        raise HTTPException(404, "online giving isn't available here")

    cfg = giving_settings(biz.get("settings"))
    funds = configured_funds(cfg)
    fund_raw = str(body.get("fund") or "").strip()
    if fund_raw:
        match = next((f for f in funds
                      if " ".join(f.lower().split()) == " ".join(fund_raw.lower().split())),
                     None)
        if not match:
            raise HTTPException(400, "unknown fund")
        fund = match
    else:
        fund = funds[0]

    # Card or bank, never pay-later (giving_ways), where switched on.
    import giving_ways
    ways_on = giving_ways.switched_on(biz.get("id"))
    if pay_with == "bank" and not giving_ways.bank_ready(biz, cfg):
        raise HTTPException(400, "bank payments aren't available here")
    if ways_on and body.get("cover_fee") is True:
        fee_cents = giving_ways.fee_cents(amount_cents, pay_with)
    extras = giving_ways.checkout_extras(pay_with) if ways_on else None

    canonical = f"https://{sites[0].get('slug') or slug}.{PUBLIC_DOMAIN}/give"
    if body.get("return_to") in ("app", "site"):
        # The member app's give screen, or a hand-built site's own give
        # page (render_give_embed): back to it on the church address the
        # giver is on.
        canonical = app_return_base(sites[0].get("slug") or slug, sites[0].get("site_config"),
                                    request.headers.get("origin") or "") + (
            "/my/give" if body.get("return_to") == "app" else "/give")
    gift_id = str(uuid.uuid4())

    from payments_core import provider_for
    from stripe_checkout_helpers import embedded_checkout_publishable_key
    adapter = provider_for(biz)
    embedded = (body.get("embedded") is True
                and getattr(adapter, "id", "stripe") == "stripe"
                and bool(embedded_checkout_publishable_key()))
    try:
        session = await adapter.create_giving_checkout(
            biz,
            gift_id=gift_id,
            business_id=str(biz["id"]),
            amount_cents=amount_cents,
            fund=fund,
            fund_label=fund_label(fund),
            fund_kind="restricted" if is_designated(fund) else "general",
            monthly=(frequency in RECURRING),
            frequency=frequency,
            cover_fee_cents=fee_cents,
            giver_name=giver_name or None,
            giver_email=giver_email or None,
            success_url=f"{canonical}?thanks=1" + ("&bank=1" if pay_with == "bank" else ""),
            cancel_url=f"{canonical}?canceled=1",
            embedded=embedded,
            **({"extra_form": extras} if extras else {}),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[giving] checkout create failed biz={str(biz['id'])[:8]}: {e}")
        raise HTTPException(502, "we couldn't start the payment — please try again")

    if embedded:
        secret = (session or {}).get("client_secret")
        if not secret:
            raise HTTPException(502, "we couldn't start the payment — please try again")
        return {"ok": True, "embedded": True, "client_secret": secret}
    url = (session or {}).get("url")
    if not url:
        raise HTTPException(502, "we couldn't start the payment — please try again")
    return {"ok": True, "url": url}


# ─── Recording gifts (called by the Connect webhook) ─────────────────


def _escape_ilike(value: str) -> str:
    return (value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_"))


def _find_or_create_giver(business_id: str, name: str, email: str) -> Optional[str]:
    """Find-or-create the giver's contact row. Dedup by email
    (case-insensitive, LIKE wildcards escaped) WITHIN the business —
    the same discipline as public_site._capture_contact_from_form. No
    email → None (the gift still records; statements count it as
    unattributed rather than inventing an identity)."""
    email_clean = (email or "").strip().lower()
    if not email_clean:
        return None
    try:
        pattern = urllib.parse.quote(_escape_ilike(email_clean), safe="")
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{business_id}"
            f"&email=ilike.{pattern}&select=id&limit=1") or []
        if rows:
            sb_clients.sb_patch_as_service(
                f"/contacts?id=eq.{rows[0]['id']}&business_id=eq.{business_id}",
                {"last_interaction": _now_iso()})
            return rows[0]["id"]
        created = sb_clients.sb_post_as_service("/contacts", {
            "business_id": business_id,
            "name": (name or "").strip() or email_clean.split("@")[0],
            "email": email_clean,
            "status": "lead",
            "source": "online_giving",
            "last_interaction": _now_iso(),
        })
        if isinstance(created, list) and created:
            return created[0]["id"]
        logger.warning(f"[giving] contact create failed biz={business_id[:8]}")
    except Exception as e:
        logger.warning(f"[giving] contact find-or-create failed: {e}")
    return None


def record_gift(
    business_id: str,
    *,
    amount_cents: int,
    fund: str,
    giver_name: str = "",
    giver_email: str = "",
    stripe_ref: str,
    recurring: bool = False,
    received_at: Optional[str] = None,
    frequency: Optional[str] = None,
) -> Optional[str]:
    """Turn a completed Stripe gift payment into the PAID invoices row
    every downstream giving surface reads. Returns the invoice id (or
    None when skipped/failed).

    Idempotent by construction: invoice_number is the deterministic
    'GIVE-<stripe ref>' (payment intent id for one-time gifts, Stripe
    invoice id for subscription cycles), checked before insert — webhook
    retries and double-delivery re-process to a no-op.

    Shape contract (pinned in tests — every field is load-bearing):
      status='paid' + paid_at     → giving_statements/_paid_gifts,
                                    donor_report, prep_990 all see it
      payment_method='stripe'     → gl_engine debits 1150 Stripe
                                    Clearing, not direct cash
      category='restricted'       → designated funds only; the exact
                                    gl_engine._RESTRICTED_HINTS token
      items[0].description        → 'Gift — <Fund>' (giving language;
                                    a ministry never says 'Invoice')
    """
    amount_cents = int(amount_cents or 0)
    if amount_cents <= 0 or not stripe_ref:
        return None

    invoice_number = f"GIVE-{stripe_ref}"[:64]
    existing = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{business_id}"
        f"&invoice_number=eq.{urllib.parse.quote(invoice_number, safe='')}"
        f"&select=id&limit=1") or []
    if existing:
        logger.info(f"[giving] gift {invoice_number} already recorded — skipping")
        return existing[0]["id"]

    contact_id = _find_or_create_giver(business_id, giver_name, giver_email)
    designated = is_designated(fund)
    label = fund_label(fund)
    amount = round(amount_cents / 100.0, 2)
    description = f"Gift — {label}"
    every = frequency_word(frequency) if recurring else ""
    notes = (f"Online gift · {label}"
             + (f" · {every}" if recurring else "")
             + (f" · {giver_email}" if giver_email else ""))

    payload: Dict[str, Any] = {
        "business_id": business_id,
        "contact_id": contact_id,
        "invoice_number": invoice_number,
        "status": "paid",
        "paid_at": received_at or _now_iso(),
        "is_gift": True,
        "gift_fund": fund,
        "payment_method": "stripe",   # load-bearing: GL clearing routing
        "items": [{"description": description, "quantity": 1,
                   "unit_price": amount, "total": amount}],
        "subtotal": amount,
        "tax_rate": 0,
        "tax_amount": 0,
        "total": amount,
        "currency": "USD",
        # Designated gifts carry the exact restricted token; general-fund
        # gifts leave category empty so statements show "General".
        "category": RESTRICTED_CATEGORY if designated else None,
        "due_date": _now_iso()[:10],
        "notes": notes,
    }
    created = sb_clients.sb_post_as_service("/invoices", payload)
    if not (isinstance(created, list) and created):
        logger.warning(f"[giving] gift invoice insert failed biz={business_id[:8]} "
                       f"ref={stripe_ref}")
        return None
    invoice_id = created[0].get("id")
    logger.info(f"[giving] recorded gift ${amount:,.2f} ({label}"
                f"{', ' + every if recurring else ''}) biz={business_id[:8]} "
                f"as {invoice_number}")

    # ── Spine event + operator notification (fail-soft) ──
    try:
        import event_spine
        # Reuses the cataloged 'giving_received' type (chief's church-
        # vertical manual mark) — same semantic event, so existing
        # consumers see online gifts without a new filter.
        event_spine.emit("giving_received", business_id,
                         {"invoice_id": invoice_id, "amount": amount,
                          "fund": fund, "recurring": recurring},
                         contact_id=contact_id, source="stripe_webhook")
    except Exception as e:
        logger.warning(f"[giving] spine emit failed (fail-soft): {e}")
    try:
        # Sensitivity: the notification deliberately does NOT name the
        # giver — individual giving stays on the Donors report +
        # statements surfaces.
        sb_clients.sb_post_as_service("/chief_notifications", {
            "business_id": business_id,
            "type": "success",
            "title": f"Gift received — ${amount:,.2f}",
            "body": (f"A {every + ' ' if recurring else ''}gift to the "
                     f"{label} just arrived online."),
            "status": "unread",
            "data": {"kind": "gift_received", "invoice_id": invoice_id,
                     "fund": fund, "recurring": recurring, "amount": amount},
        })
    except Exception as e:
        logger.warning(f"[giving] notification failed (fail-soft): {e}")

    # ── Acknowledgment email (Pub 1771 language; fail-soft) ──
    if giver_email:
        _schedule_gift_receipt(
            business_id, giver_email=giver_email, giver_name=giver_name,
            amount=amount, fund_display=label, recurring=recurring,
            every=every or "monthly")
    return invoice_id


def record_gift_from_session(session: Dict[str, Any]) -> Optional[str]:
    """checkout.session.completed with metadata.source_type='gift' and
    mode=payment (one-time). Subscription sessions are recorded from
    their invoice.paid events instead — see record_gift_from_cycle."""
    md = session.get("metadata") or {}
    business_id = md.get("business_id")
    if not business_id:
        logger.warning("[giving] gift session missing business_id metadata")
        return None
    if session.get("mode") == "subscription":
        logger.info("[giving] subscription session — cycle records via invoice.paid")
        return None
    details = session.get("customer_details") or {}
    ref = session.get("payment_intent") or session.get("id") or ""
    return record_gift(
        str(business_id),
        amount_cents=int(session.get("amount_total") or 0),
        fund=md.get("fund") or "General",
        giver_name=md.get("giver_name") or details.get("name") or "",
        giver_email=(md.get("giver_email") or details.get("email") or "").lower(),
        stripe_ref=str(ref),
        recurring=False,
        received_at=_stripe_time(session.get("created")),
    )


def _stripe_time(value) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat() if value else None
    except (ValueError, TypeError, OverflowError):
        return None


def gift_metadata_from_stripe_invoice(inv: Dict[str, Any]) -> Dict[str, Any]:
    """The subscription's metadata as it rides a cycle's invoice.paid
    event: invoice.subscription_details.metadata (Stripe mirrors the
    Subscription's metadata there at invoice creation). Separate helper
    so the webhook's gift check and the recorder read ONE place."""
    sub = inv.get("subscription_details") or (inv.get("parent") or {}).get("subscription_details") or {}
    md = sub.get("metadata") or {}
    return md if isinstance(md, dict) else {}


def record_gift_from_cycle(inv: Dict[str, Any]) -> Optional[str]:
    """invoice.paid on the connected account for a gift subscription —
    one paid local invoice per cycle (including the first: billing_reason
    subscription_create is recorded HERE, not from the checkout session,
    so a cycle can never double-post)."""
    md = gift_metadata_from_stripe_invoice(inv)
    business_id = md.get("business_id")
    if not business_id:
        logger.warning("[giving] gift cycle missing business_id metadata")
        return None
    ref = inv.get("id") or ""
    return record_gift(
        str(business_id),
        amount_cents=int(inv.get("amount_paid") or 0),
        fund=md.get("fund") or "General",
        giver_name=md.get("giver_name") or inv.get("customer_name") or "",
        giver_email=(md.get("giver_email") or inv.get("customer_email") or "").lower(),
        stripe_ref=str(ref),
        recurring=True,
        frequency=md.get("frequency") or "monthly",
        received_at=_stripe_time((inv.get("status_transitions") or {}).get("paid_at") or inv.get("created")),
    )


# ─── Acknowledgment email ────────────────────────────────────────────


def _schedule_gift_receipt(business_id: str, *, giver_email: str,
                           giver_name: str, amount: float,
                           fund_display: str, recurring: bool,
                           every: str = "monthly") -> None:
    """Fire-and-forget the receipt email when an event loop is running
    (the webhook path); never blocks or raises."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(send_gift_receipt(
            business_id, giver_email=giver_email, giver_name=giver_name,
            amount=amount, fund_display=fund_display, recurring=recurring,
            every=every))
    except RuntimeError:
        # No running loop (sync test context) — skip rather than build
        # bespoke threading for an opportunistic email.
        logger.info("[giving] no event loop — receipt email skipped")
    except Exception as e:
        logger.warning(f"[giving] receipt scheduling failed (fail-soft): {e}")


async def send_gift_receipt(business_id: str, *, giver_email: str,
                            giver_name: str, amount: float,
                            fund_display: str, recurring: bool,
                            every: str = "monthly") -> None:
    """The per-gift contemporaneous written acknowledgment (IRS Pub
    1771): organization name, amount, date, and the goods-and-services
    declaration — reusing giving_statements' exact language so the
    per-gift receipt and the January statement can never disagree.
    Best-effort: errors log and return."""
    try:
        import giving_statements as gs
        from email_sender import send_via_resend
        import os

        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}&select=name&limit=1") or []
        org = (rows[0].get("name") if rows else "") or "the organization"
        today = _now_iso()[:10]
        first = (giver_name or "").strip().split(" ")[0] or "Friend"
        monthly_line = (f"\nThis is a recurring {every} gift. Each one "
                        "will appear on your year-end statement.\n"
                        if recurring else "")
        body = (
            f"Dear {first},\n\n"
            f"Thank you for your gift to {org}.\n\n"
            f"  Amount: ${amount:,.2f}\n"
            f"  Fund:   {fund_display}\n"
            f"  Date:   {today}\n"
            f"{monthly_line}\n"
            f"{gs.NO_GOODS_LANGUAGE}\n\n"
            f"Please keep this acknowledgment with your tax records.\n\n"
            f"{gs.disclaimer()}\n\n"
            f"— {org}"
        )
        await send_via_resend(
            to_email=giver_email,
            to_name=giver_name or None,
            from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
            from_name=org,
            subject=f"Your gift to {org} — receipt",
            body=body,
            reply_to=None,
            business_id=business_id,
        )
        logger.info(f"[giving] receipt sent biz={business_id[:8]}")
    except Exception as e:
        logger.warning(f"[giving] receipt email failed (fail-soft): {e}")


# ─── SSR give page renderers (pure — unit-testable) ──────────────────


def _esc(s: Optional[str]) -> str:
    return _html_mod.escape(s or "", quote=True)


def _brand_css_vars(business: Dict[str, Any]) -> str:
    """Brand kit → CSS variables. Reuses the booking page's mapping so a
    ministry's /book and /give visually match."""
    from booking_page_renderer import _css_vars, _brand_kit
    return _css_vars(_brand_kit(business))


def _brand_font_links(business: Dict[str, Any]) -> str:
    """The brand's faces, loaded — the partner of _brand_css_vars."""
    from booking_page_renderer import _font_links, _brand_kit
    return _font_links(_brand_kit(business))


PAY_WITH_BLOCK = (
    '<label class="gv-label">Pay with</label>'
    '<div class="gv-paywith" role="group" aria-label="Pay with">'
    '<button type="button" data-pay="card" class="on" aria-pressed="true">Card, Apple Pay or Google Pay</button>'
    '<button type="button" data-pay="bank" aria-pressed="false">Bank account</button></div>'
    '<p class="gv-note" id="gv-bank-note" hidden>A bank payment costs the church less in fees. '
    'It takes a few business days to clear.</p>')


def _ways_blocks(business: Dict[str, Any]) -> tuple:
    """(the pay-with choice, "Other ways to give", their CSS) where
    giving_ways is switched on for this church; empty strings otherwise."""
    import giving_ways
    if not giving_ways.switched_on(business.get("id")):
        return "", "", ""
    cfg = giving_settings(business.get("settings"))
    pay = PAY_WITH_BLOCK if giving_ways.bank_ready(business, cfg) else ""
    ways = giving_ways.ways_html(giving_ways.stored_ways(cfg))
    return pay, ways, giving_ways.WAYS_CSS


def _give_body(preset_btns: str, fund_block: str, pay_note: str, name: str = "", email: str = "",
               pay_block: str = "", ways_block: str = "") -> str:
    """The give form's markup: the thank-you and no-gift notes, the form,
    "Change my gift", and the box the payment form mounts in. Shared by
    the give page and a hand-built site's own give page. `pay_block`: the
    card-or-bank choice; `ways_block`: "Other ways to give" (giving_ways)."""
    return f"""  <div id="gv-thanks" class="gv-banner">Thank you — your gift has been received.
  If you shared your email, a receipt is on its way.</div>
  <div id="gv-canceled" class="gv-banner">No gift was made. You're welcome to
  try again whenever you're ready.</div>
  <form class="gv-card" id="gv-form">
    <label class="gv-label">Amount</label>
    <div class="gv-grid">{preset_btns}</div>
    <input type="number" inputmode="decimal" min="1" step="0.01" id="gv-custom"
           class="gv-input" placeholder="Other amount ($)">
    {fund_block}
    <label class="gv-label">Frequency</label>
    <div class="gv-freq" role="group" aria-label="How often">
      <button type="button" data-freq="once" class="on" aria-pressed="true">One time</button>
      <button type="button" data-freq="weekly" aria-pressed="false">Weekly</button>
      <button type="button" data-freq="biweekly" aria-pressed="false">Every 2 weeks</button>
      <button type="button" data-freq="monthly" aria-pressed="false">Monthly</button>
    </div>
    {pay_block}
    <label class="gv-cover"><input type="checkbox" id="gv-fee">
      <span id="gv-fee-txt">Add a little to cover the processing fee, so your whole gift arrives</span></label>
    <label class="gv-label" for="gv-nm">Name <span style="text-transform:none;font-weight:400">(optional)</span></label>
    <input type="text" id="gv-nm" class="gv-input" autocomplete="name" maxlength="120" value="{_esc(name)}">
    <label class="gv-label" for="gv-em">Email <span style="text-transform:none;font-weight:400">(for your receipt)</span></label>
    <input type="email" id="gv-em" class="gv-input" autocomplete="email" maxlength="200" value="{_esc(email)}">
    <button type="submit" class="gv-give" id="gv-go">Give</button>
    <div class="gv-error" id="gv-err"></div>
    <p class="gv-note">{pay_note}
    Add your email to receive a receipt and your year-end giving statement.</p>
  </form>
  <button type="button" class="gv-back" id="gv-back" hidden>&larr; Change my gift</button>
  <div class="gv-pay" id="gv-pay" hidden></div>
  {ways_block}
"""


def _give_script(*, api_origin: str, slug: str, embed_json: str, app: bool = False,
                 preview: bool = False, site: bool = False) -> str:
    """The give form's behaviour (amounts, frequency, the fee, embedded
    Checkout). `app`: inside the member app; `site`: on a church's own
    hand-built give page."""
    return f"""<script>
(function() {{
  var API = {api_origin!r};
  var SLUG = {slug!r};
  var cents = 0, freq = 'once', pay = 'card';
  var EVERY = {{once: '', weekly: ' weekly', biweekly: ' every 2 weeks', monthly: ' monthly'}};
  var feeBox = document.getElementById('gv-fee');
  var feeTxt = document.getElementById('gv-fee-txt');
  var feeDefault = feeTxt.textContent;
  // Same arithmetic as the server (giving_ways.fee_cents): card 2.9% + 30c,
  // bank 0.8% at most $5.
  function fee(c) {{
    if (c <= 0) return 0;
    if (pay === 'bank') return Math.min(Math.ceil(c / (1 - 0.008)) - c, 500);
    return Math.ceil((c + 30) / (1 - 0.029)) - c;
  }}
  var payWith = document.querySelector('.gv-paywith');
  var payBtns = document.querySelectorAll('.gv-paywith button');
  var bankNote = document.getElementById('gv-bank-note');
  payBtns.forEach(function(b) {{
    b.addEventListener('click', function() {{
      pay = b.getAttribute('data-pay') === 'bank' ? 'bank' : 'card';
      payBtns.forEach(function(x) {{
        var on = x === b; x.classList.toggle('on', on); x.setAttribute('aria-pressed', on ? 'true' : 'false');
      }});
      if (bankNote) bankNote.hidden = pay !== 'bank';
      label();
    }});
  }});
  // Other ways to give: Cash App and PayPal.Me links carry the amount.
  var wayLinks = document.querySelectorAll('[data-way-amt]');
  function wayAmounts() {{
    var part = cents >= 100 ? '/' + (cents % 100 ? (cents / 100).toFixed(2) : String(cents / 100)) : '';
    wayLinks.forEach(function(a) {{ a.href = a.getAttribute('data-way-base') + part; }});
  }}
  document.querySelectorAll('.gv-copy').forEach(function(b) {{
    b.addEventListener('click', function() {{
      try {{ navigator.clipboard.writeText(b.getAttribute('data-copy')); b.textContent = 'Copied'; }}
      catch (e) {{}}
    }});
  }});
  function money(c) {{ return '$' + (c / 100).toLocaleString(undefined,
    {{minimumFractionDigits: (c % 100 ? 2 : 0), maximumFractionDigits: 2}}); }}
  var q = new URLSearchParams(location.search);
  if (q.get('thanks') && q.get('bank')) document.getElementById('gv-thanks').textContent =
    'Thank you. Your bank gift is on its way: bank payments take a few business days to clear, ' +
    'and if you shared your email, your receipt comes when it does.';
  if (q.get('thanks')) document.getElementById('gv-thanks').classList.add('show');
  if (q.get('canceled')) document.getElementById('gv-canceled').classList.add('show');
  var amts = document.querySelectorAll('.gv-amt');
  var custom = document.getElementById('gv-custom');
  var go = document.getElementById('gv-go');
  var err = document.getElementById('gv-err');
  // Embedded Checkout: {{pk, acct}} when the payment form can open on
  // this page, else null (Give redirects to Stripe's page instead).
  var EMBED = {embed_json};
  // Inside the member app: come back to /my/give; in the owner's preview
  // nothing is charged. On a church's own hand-built give page (SITE):
  // come back to that page, on the address the giver is on.
  var APP = {json.dumps(app)}, PREVIEW = {json.dumps(preview)}, SITE = {json.dumps(site)};
  var form = document.getElementById('gv-form');
  var payBox = document.getElementById('gv-pay');
  var back = document.getElementById('gv-back');
  var checkout = null, noEmbed = false;
  function embedOn() {{ return !!(EMBED && window.Stripe && !noEmbed); }}
  function showForm() {{
    if (checkout) {{ try {{ checkout.destroy(); }} catch (e) {{}} checkout = null; }}
    payBox.hidden = true; back.hidden = true; form.hidden = false; go.disabled = false;
  }}
  back.addEventListener('click', showForm);
  function mount(secret) {{
    try {{
      var stripe = window.Stripe(EMBED.pk, {{stripeAccount: EMBED.acct}});
      // Stripe.js renamed initEmbeddedCheckout to createEmbeddedCheckoutPage (2026-03-25).
      var make = stripe.createEmbeddedCheckoutPage || stripe.initEmbeddedCheckout;
      return make.call(stripe, {{fetchClientSecret: function() {{ return Promise.resolve(secret); }}}})
        .then(function(c) {{
          checkout = c;
          form.hidden = true; back.hidden = false; payBox.hidden = false;
          c.mount('#gv-pay');
          back.scrollIntoView({{block: 'start'}});
        }});
    }} catch (e) {{ return Promise.reject(e); }}
  }}
  function label() {{
    var add = feeBox.checked ? fee(cents) : 0;
    feeTxt.textContent = cents > 0
      ? 'Add about ' + money(fee(cents)) + ' to cover the processing fee, so your whole gift arrives'
      : feeDefault;
    go.textContent = cents > 0 ? ('Give ' + money(cents + add) + EVERY[freq]) : 'Give';
    wayAmounts();
  }}
  feeBox.addEventListener('change', label);
  amts.forEach(function(b) {{
    b.addEventListener('click', function() {{
      amts.forEach(function(x) {{ x.classList.remove('on'); }});
      b.classList.add('on');
      custom.value = '';
      cents = parseInt(b.getAttribute('data-cents'), 10) || 0;
      label();
    }});
  }});
  custom.addEventListener('input', function() {{
    amts.forEach(function(x) {{ x.classList.remove('on'); }});
    cents = Math.round(parseFloat(custom.value || '0') * 100) || 0;
    label();
  }});
  var freqBtns = document.querySelectorAll('.gv-freq button');
  freqBtns.forEach(function(b) {{
    b.addEventListener('click', function() {{
      freq = b.getAttribute('data-freq');
      freqBtns.forEach(function(x) {{
        var on = x === b; x.classList.toggle('on', on); x.setAttribute('aria-pressed', on ? 'true' : 'false');
      }});
      label();
    }});
  }});
  document.getElementById('gv-form').addEventListener('submit', function(ev) {{
    ev.preventDefault();
    err.classList.remove('show');
    if (PREVIEW) {{ err.textContent = "This is a preview, so nothing is charged."; err.classList.add('show'); return; }}
    if (cents < 100) {{ err.textContent = 'Please choose an amount ($1 minimum).'; err.classList.add('show'); return; }}
    var email = document.getElementById('gv-em').value.trim();
    if (freq !== 'once' && !email) {{ err.textContent = 'A recurring gift needs an email so we can send your receipts.'; err.classList.add('show'); return; }}
    var fundSel = document.getElementById('gv-fund');
    go.disabled = true;
    fetch(API + '/public/giving/' + SLUG + '/checkout', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        amount_cents: cents,
        fund: fundSel ? fundSel.value : undefined,
        frequency: freq,
        cover_fee: feeBox.checked,
        pay_with: payWith ? pay : undefined,
        name: document.getElementById('gv-nm').value.trim() || undefined,
        email: email || undefined,
        embedded: embedOn() || undefined,
        return_to: APP ? 'app' : (SITE ? 'site' : undefined)
      }})
    }}).then(function(r) {{ return r.json().then(function(j) {{ return {{ok: r.ok, j: j}}; }}); }})
      .then(function(res) {{
        if (res.ok && res.j && res.j.client_secret) {{
          mount(res.j.client_secret).catch(function() {{
            // Next press uses Stripe's own page instead.
            noEmbed = true; showForm();
            err.textContent = "The payment form didn't load. Please press Give again.";
            err.classList.add('show');
          }});
          return;
        }}
        if (res.ok && res.j && res.j.url) {{ location.href = res.j.url; return; }}
        err.textContent = (res.j && res.j.detail) || 'Something went wrong — please try again.';
        err.classList.add('show');
        go.disabled = false;
      }})
      .catch(function() {{
        err.textContent = 'Network hiccup — please try again.';
        err.classList.add('show');
        go.disabled = false;
      }});
  }});
  // A link can fill the form in, so a giver moving a recurring gift over
  // taps their own link and checks it:
  //   /give?amount=50&frequency=monthly&fund=Building&cover_fee=1
  // Nothing is submitted; the giver still presses Give. No name or email
  // rides in the link: they type those (or Stripe asks).
  (function() {{
    var a = parseFloat(q.get('amount') || '');
    if (a >= 1 && a <= 25000) {{
      cents = Math.round(a * 100);
      var match = null;
      amts.forEach(function(b) {{ if (parseInt(b.getAttribute('data-cents'), 10) === cents) match = b; }});
      if (match) match.classList.add('on');
      else custom.value = (cents / 100).toFixed(cents % 100 ? 2 : 0);
    }}
    var f = q.get('frequency');
    freqBtns.forEach(function(b) {{ if (b.getAttribute('data-freq') === f) b.click(); }});
    var fund = (q.get('fund') || '').toLowerCase(), sel = document.getElementById('gv-fund');
    if (fund && sel) {{
      for (var i = 0; i < sel.options.length; i++) {{
        var o = sel.options[i];
        if (o.value.toLowerCase() === fund || o.textContent.toLowerCase() === fund) sel.value = o.value;
      }}
    }}
    if (q.get('cover_fee') === '1') feeBox.checked = true;
  }})();
  label();
}})();
</script>
"""


def render_give_page(
    business: Dict[str, Any],
    canonical_url: str,
    slug: str,
    *,
    api_origin: str,
    app: Optional[Dict[str, Any]] = None,
) -> str:
    """The public give page. Mobile-first by design — congregants give
    from phones: single column, ≤480px shell, 44px+ touch targets,
    16px inputs (no iOS zoom), no horizontal scroll at any width.

    `app` puts the same form inside the member app (/my/give, Kevin's
    phone design 2026-10-14): {"head": the app's fonts and stylesheet,
    "top": its header, "name"/"email": the signed-in member's (the app's
    pages are never cached), "preview": the owner's preview, where Give
    is refused}. The payment itself is unchanged."""
    name = (business.get("name") or "").strip() or "Give"
    cfg = giving_settings(business.get("settings"))
    funds = configured_funds(cfg)
    presets = preset_amounts(cfg)
    message = (cfg.get("message") or "").strip()
    brand = (business.get("settings") or {}).get("brand_kit") or {}
    logo_url = ""
    if isinstance(brand, dict):
        logo_url = (brand.get("logo_url") or brand.get("logo") or "").strip()

    title = f"Give — {name}"
    description = message or f"Give online to {name}. Secure one-time, weekly and monthly giving."
    css_vars = _brand_css_vars(business)

    # The payment form mounts inside this page (embedded Checkout on the
    # church's own Stripe account) once the platform's publishable key is
    # set. Without it, Give sends the giver to checkout.stripe.com and
    # back, as before.
    from payments_core import provider_for
    from stripe_checkout_helpers import embedded_checkout_publishable_key
    pk = embedded_checkout_publishable_key()
    acct = str(business.get("stripe_account_id") or "")
    embed = bool(pk and re.fullmatch(r"acct_[A-Za-z0-9]+", acct)
                 and provider_for(business).id == "stripe")
    embed_json = json.dumps({"pk": pk, "acct": acct}) if embed else "null"
    stripe_js = '<script src="https://js.stripe.com/v3/"></script>' if embed else ""
    pay_note = ("Your payment is handled securely by Stripe, right on this page."
                if embed else "You'll finish securely on our payment page.")

    preset_btns = "".join(
        f'<button type="button" class="gv-amt" data-cents="{p * 100}">${p:,}</button>'
        for p in presets)

    fund_block = ""
    if len(funds) > 1:
        opts = "".join(f'<option value="{_esc(f)}">{_esc(fund_label(f))}</option>'
                       for f in funds)
        fund_block = (
            '<label class="gv-label" for="gv-fund">Designate my gift to</label>'
            f'<select id="gv-fund" class="gv-input">{opts}</select>')

    logo_html = (f'<img class="gv-logo" src="{_esc(logo_url)}" alt="{_esc(name)} logo">'
                 if logo_url else "")
    message_html = (f'<p class="gv-msg">{_esc(message)}</p>' if message else "")
    app = app or None
    header_html = (app["top"] + message_html if app else
                   f'<header class="gv-header">{logo_html}<h1 class="gv-name">{_esc(name)}</h1>'
                   f'<p class="gv-title">Give</p>{message_html}</header>')
    # Precomputed (not a nested f-string) so the module parses on every
    # Python the deploy target might run.
    og_image_html = ""
    if logo_url:
        og_image_html = (f'<meta property="og:image" content="{_esc(logo_url)}">'
                         f'<link rel="icon" href="{_esc(logo_url)}">')

    pay_block, ways_block, ways_css = _ways_blocks(business)
    body_html = _give_body(preset_btns, fund_block, pay_note,
                           (app or {}).get("name") or "", (app or {}).get("email") or "",
                           pay_block=pay_block, ways_block=ways_block)
    script_html = _give_script(api_origin=api_origin, slug=slug, embed_json=embed_json, app=bool(app),
                               preview=bool((app or {}).get("preview")))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description)}">
<link rel="canonical" href="{_esc(canonical_url)}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(description)}">
<meta property="og:url" content="{_esc(canonical_url)}">
<meta property="og:type" content="website">
{og_image_html}
{_brand_font_links(business)}
{stripe_js}
<style>{css_vars}</style>
<style>
html,body{{margin:0;padding:0;font-family:var(--font-body);color:var(--text-primary);
background:var(--surface);min-height:100vh;}}
*{{box-sizing:border-box;}}
.gv-shell{{max-width:480px;margin:0 auto;padding:28px 16px 48px;}}
.gv-header{{text-align:center;margin-bottom:22px;}}
.gv-logo{{max-width:88px;max-height:88px;display:block;margin:0 auto 12px;}}
.gv-name{{font-family:var(--font-heading);font-size:24px;font-weight:700;margin:0;}}
.gv-title{{font-family:var(--font-heading);font-size:15px;font-weight:600;
color:var(--text-secondary);margin:6px 0 0;letter-spacing:.06em;text-transform:uppercase;}}
.gv-msg{{font-size:14px;color:var(--text-secondary);margin:10px 0 0;line-height:1.5;}}
.gv-card{{border:1px solid var(--border);border-radius:16px;padding:20px 16px;}}
.gv-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:12px;}}
.gv-amt{{padding:14px 0;font-size:17px;font-weight:700;font-family:var(--font-body);
border:1.5px solid var(--border);border-radius:12px;background:transparent;
color:var(--text-primary);cursor:pointer;min-height:48px;}}
.gv-amt.on{{border-color:var(--accent);background:var(--accent);color:#fff;}}
.gv-label{{display:block;font-size:11px;font-weight:700;letter-spacing:.08em;
text-transform:uppercase;color:var(--text-muted);margin:14px 0 6px;}}
.gv-input{{width:100%;padding:12px 14px;font-size:16px;border:1.5px solid var(--border);
border-radius:12px;background:transparent;color:var(--text-primary);min-height:48px;}}
.gv-freq{{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border:1.5px solid var(--border);
border-radius:12px;overflow:hidden;margin-top:4px;}}
@media (max-width:420px){{.gv-freq{{grid-template-columns:1fr 1fr;}}}}
.gv-cover{{display:flex;align-items:flex-start;gap:10px;margin-top:14px;font-size:14px;
line-height:1.45;color:var(--text-secondary);cursor:pointer;min-height:44px;}}
.gv-cover input{{width:20px;height:20px;margin:1px 0 0;flex:none;accent-color:var(--accent);}}
.gv-freq button{{padding:12px 0;font-size:14px;font-weight:600;border:0;background:transparent;
color:var(--text-secondary);cursor:pointer;min-height:46px;font-family:var(--font-body);}}
.gv-freq button.on{{background:var(--accent);color:#fff;}}
.gv-give{{width:100%;margin-top:18px;padding:16px 0;font-size:17px;font-weight:700;
border:0;border-radius:12px;background:var(--accent);color:#fff;cursor:pointer;
min-height:52px;font-family:var(--font-body);}}
.gv-give:disabled{{opacity:.55;cursor:default;}}
.gv-note{{font-size:12px;color:var(--text-muted);margin-top:12px;line-height:1.5;text-align:center;}}
.gv-banner{{display:none;margin-bottom:16px;padding:14px 16px;border-radius:12px;
font-size:14px;line-height:1.5;border:1px solid var(--border);}}
.gv-banner.show{{display:block;}}
.gv-error{{display:none;margin-top:10px;font-size:13px;color:#b3261e;}}
.gv-error.show{{display:block;}}
.gv-footer{{text-align:center;font-size:11px;color:var(--text-muted);margin-top:28px;
padding-top:14px;border-top:1px solid var(--border);}}
.gv-footer a{{color:var(--text-muted);text-decoration:none;}}
.gv-back{{background:none;border:0;padding:10px 0;margin-bottom:6px;font-size:14px;font-weight:600;
color:var(--text-secondary);cursor:pointer;min-height:44px;font-family:var(--font-body);}}
.gv-pay{{border-radius:16px;overflow:hidden;}}
{ways_css}
</style>
{app["head"] if app else ""}
</head>
<body>
<main class="gv-shell">
  {header_html}
{body_html}  <footer class="gv-footer">
    Powered by <a href="https://mysolutionist.app/" target="_blank" rel="noopener">Solutionist</a>
  </footer>
</main>
{(app or {}).get("foot", "")}
{script_html}</body>
</html>"""


# ─── The form on a church's own hand-built give page ─────────────────
# Kevin, 2026-10-15: "update the website giving as well". A hand-built
# site (site_config.html_source == "manual", e.g. sites/love-city-church)
# owns /give, so the hosted give page above never shows there. Its own
# give page marks where the form goes, and the server fills it when the
# page is served (public_site._augment_html):
#   <!--solutionist:give-form-->fallback<!--/solutionist:give-form-->
#       the form, while online giving is on; else a short paused note.
#   <!--solutionist:give-funds-->fallback<!--/solutionist:give-funds-->
#       one <li> per fund the church set, while giving is on; else the
#       site's own list stays.
# The site styles the form through --gv-* variables on its wrapper; the
# church's brand colours are the defaults.
GIVE_FORM_SLOT = re.compile(r"<!--solutionist:give-form-->.*?<!--/solutionist:give-form-->", re.S)
GIVE_FUNDS_SLOT = re.compile(r"<!--solutionist:give-funds-->.*?<!--/solutionist:give-funds-->", re.S)

_GIVE_EMBED_CSS = """
.gv-embed{font-family:inherit;color:var(--gv-ink,var(--text-primary));}
.gv-embed *{box-sizing:border-box;}
.gv-embed .gv-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:12px;}
.gv-embed .gv-amt{padding:14px 0;font:inherit;font-size:18px;font-weight:700;border:1.5px solid var(--gv-line,var(--border));
  border-radius:var(--gv-radius,12px);background:transparent;color:inherit;cursor:pointer;min-height:52px;}
.gv-embed .gv-amt.on{border-color:var(--gv-accent,var(--accent));background:var(--gv-accent,var(--accent));color:var(--gv-on-accent,#fff);}
.gv-embed .gv-label{display:block;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  color:var(--gv-muted,var(--text-muted));margin:16px 0 6px;}
.gv-embed .gv-input{width:100%;padding:12px 14px;font:inherit;font-size:16px;border:1.5px solid var(--gv-line,var(--border));
  border-radius:var(--gv-radius,12px);background:var(--gv-field,transparent);color:inherit;min-height:50px;}
.gv-embed .gv-freq{display:grid;grid-template-columns:repeat(4,1fr);border:1.5px solid var(--gv-line,var(--border));
  border-radius:var(--gv-radius,12px);overflow:hidden;margin-top:4px;}
@media (max-width:480px){.gv-embed .gv-freq{grid-template-columns:1fr 1fr;}}
.gv-embed .gv-freq button{padding:12px 4px;font:inherit;font-size:14px;font-weight:600;border:0;background:transparent;
  color:var(--gv-muted,var(--text-secondary));cursor:pointer;min-height:48px;}
.gv-embed .gv-freq button.on{background:var(--gv-accent,var(--accent));color:var(--gv-on-accent,#fff);}
.gv-embed .gv-cover{display:flex;align-items:flex-start;gap:10px;margin-top:16px;font-size:15px;line-height:1.45;
  color:var(--gv-muted,var(--text-secondary));cursor:pointer;min-height:44px;}
.gv-embed .gv-cover input{width:20px;height:20px;margin:1px 0 0;flex:none;accent-color:var(--gv-accent,var(--accent));}
.gv-embed .gv-give{width:100%;margin-top:20px;padding:16px 0;font:inherit;font-size:18px;font-weight:700;border:0;
  border-radius:var(--gv-radius,12px);background:var(--gv-accent,var(--accent));color:var(--gv-on-accent,#fff);cursor:pointer;min-height:56px;}
.gv-embed .gv-give:disabled{opacity:.55;cursor:default;}
.gv-embed .gv-note{font-size:13px;color:var(--gv-muted,var(--text-muted));margin:12px 0 0;line-height:1.5;}
.gv-embed .gv-banner{display:none;margin-bottom:16px;padding:14px 16px;border-radius:var(--gv-radius,12px);font-size:15px;
  line-height:1.5;border:1.5px solid var(--gv-accent,var(--accent));}
.gv-embed .gv-banner.show{display:block;}
.gv-embed .gv-error{display:none;margin-top:10px;font-size:14px;color:#b3261e;}
.gv-embed .gv-error.show{display:block;}
.gv-embed .gv-back{background:none;border:0;padding:10px 0;margin-bottom:6px;font:inherit;font-size:15px;font-weight:600;
  color:var(--gv-muted,var(--text-secondary));cursor:pointer;min-height:44px;}
.gv-embed .gv-pay{border-radius:var(--gv-radius,12px);overflow:hidden;}
"""


def render_give_embed(business: Dict[str, Any], slug: str, *, api_origin: str) -> str:
    """The give form alone, for a church's own hand-built give page: no
    page around it, its styles scoped to .gv-embed, the brand's colours
    as defaults (a site overrides them with --gv-* on its wrapper), and a
    gift that comes back to this page on the address the giver is on
    (return_to 'site'). Same amounts, funds, fee cover, frequencies and
    embedded Checkout as the hosted page."""
    cfg = giving_settings(business.get("settings"))
    funds = configured_funds(cfg)
    presets = preset_amounts(cfg)
    from payments_core import provider_for
    from stripe_checkout_helpers import embedded_checkout_publishable_key
    pk = embedded_checkout_publishable_key()
    acct = str(business.get("stripe_account_id") or "")
    embed = bool(pk and re.fullmatch(r"acct_[A-Za-z0-9]+", acct) and provider_for(business).id == "stripe")
    embed_json = json.dumps({"pk": pk, "acct": acct}) if embed else "null"
    stripe_js = '<script src="https://js.stripe.com/v3/"></script>' if embed else ""
    pay_note = ("Your payment is handled securely by Stripe, right on this page."
                if embed else "You'll finish securely on our payment page.")
    preset_btns = "".join(f'<button type="button" class="gv-amt" data-cents="{p * 100}">${p:,}</button>'
                          for p in presets)
    fund_block = ""
    if len(funds) > 1:
        opts = "".join(f'<option value="{_esc(f)}">{_esc(fund_label(f))}</option>' for f in funds)
        fund_block = ('<label class="gv-label" for="gv-fund">Designate my gift to</label>'
                      f'<select id="gv-fund" class="gv-input">{opts}</select>')
    brand_vars = _brand_css_vars(business).replace(":root{", ".gv-embed{", 1)
    pay_block, ways_block, ways_css = _ways_blocks(business)
    return (f'<div class="gv-embed">{stripe_js}<style>{brand_vars}{_GIVE_EMBED_CSS}{ways_css}</style>'
            f'{_give_body(preset_btns, fund_block, pay_note, pay_block=pay_block, ways_block=ways_block)}'
            f'{_give_script(api_origin=api_origin, slug=slug, embed_json=embed_json, site=True)}</div>')


def fill_give_slots(html: str, business: Optional[Dict[str, Any]], slug: str, *, api_origin: str) -> str:
    """Fill a hand-built page's give slots (see GIVE_FORM_SLOT). Never
    leaves a slot's markers behind, and never blanks the page: any trouble,
    or `business` None (it couldn't be read), keeps each slot's own
    fallback — a failed read is not "giving is paused"."""
    if not html or "<!--solutionist:give-" not in html:
        return html

    def keep_inner(m: "re.Match[str]") -> str:
        inner = m.group(0)
        return inner[inner.index("-->") + 3:inner.rindex("<!--/")]
    try:
        if business is None:
            raise LookupError("business unread")
        if giving_is_active(business):
            form = render_give_embed(business, slug, api_origin=api_origin)
            funds = configured_funds(giving_settings(business.get("settings")))
            items = "".join(f'<li><span class="fund-name">{_esc(fund_label(f))}</span></li>' for f in funds)
            html = GIVE_FORM_SLOT.sub(lambda m: form, html)
            return GIVE_FUNDS_SLOT.sub(lambda m: items, html)
        paused = ('<div class="gv-paused"><p><strong>Online giving is paused right now.</strong></p>'
                  '<p>You can give in person at any service. Thank you for your generosity.</p></div>')
        html = GIVE_FORM_SLOT.sub(lambda m: paused, html)
        return GIVE_FUNDS_SLOT.sub(keep_inner, html)
    except Exception as e:
        logger.warning(f"[giving] give slots fell back for {slug}: {e}")
        html = GIVE_FORM_SLOT.sub(keep_inner, html)
        return GIVE_FUNDS_SLOT.sub(keep_inner, html)


def render_giving_unavailable_page(business: Dict[str, Any],
                                   canonical_url: str) -> str:
    """404-status page when giving isn't enabled for this business —
    brand-applied, mirroring booking's render_not_published_page."""
    name = (business.get("name") or "").strip() or "This organization"
    css_vars = _brand_css_vars(business)
    return "\n".join([
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f"<title>{_esc(name)}</title>",
        '<meta name="robots" content="noindex,nofollow">',
        f'<link rel="canonical" href="{_esc(canonical_url)}">',
        _brand_font_links(business),
        f"<style>{css_vars}</style>",
        "<style>html,body{margin:0;padding:0;font-family:var(--font-body);"
        "color:var(--text-primary);background:var(--surface);min-height:100vh;}"
        ".gv-shell{max-width:480px;margin:96px auto 0;padding:24px 16px;"
        "text-align:center;}"
        ".gv-name{font-family:var(--font-heading);font-size:22px;font-weight:700;}"
        ".gv-msg{margin-top:16px;color:var(--text-secondary);line-height:1.5;}"
        "</style>",
        "</head>",
        "<body>",
        '<main class="gv-shell">',
        f'<h1 class="gv-name">{_esc(name)}</h1>',
        '<p class="gv-msg">Online giving isn\'t available here yet.</p>',
        "</main>",
        "</body>",
        "</html>",
    ])


# The finance entry surface works without Stripe or bank linking.
@router.get("/giving/{business_id}/records")
def giving_records(business_id: str, year: Optional[int] = None, user: AuthedUser = Depends(require_user)):
    from giving_records import require_finance, read_gifts
    require_finance(business_id, user)
    church_keys.wall(business_id, user, "giving_money")
    year = year or datetime.now(timezone.utc).year
    if not 2000 <= year <= 2200:
        raise HTTPException(400, "Choose a valid year")
    rows = read_gifts(business_id, f"{year}-01-01T00:00:00Z", f"{year+1}-01-01T00:00:00Z")
    return {"rows": rows, "year": year}


# What a gift was worth, when, and to which fund: never who gave it, its
# note, or its number. The Giving keeper guards the names, not the picture,
# so this read has no wall: the church's Home, its giving goal and the
# board's year stay right for an owner the keeper hasn't let in. The same
# people as the records (owner, admin, the outside accountant).
GIFT_AMOUNT_FIELDS = ("paid_at", "total", "refund_amount_cents", "gift_fund", "category")


@router.get("/giving/{business_id}/amounts")
def giving_amounts(business_id: str, year: Optional[int] = None, user: AuthedUser = Depends(require_user)):
    from giving_records import require_finance, read_gifts
    require_finance(business_id, user)
    year = year or datetime.now(timezone.utc).year
    if not 2000 <= year <= 2200:
        raise HTTPException(400, "Choose a valid year")
    rows = read_gifts(business_id, f"{year}-01-01T00:00:00Z", f"{year+1}-01-01T00:00:00Z")
    return {"rows": [{**{k: r.get(k) for k in GIFT_AMOUNT_FIELDS},
                      "manual": str(r.get("invoice_number") or "").startswith("GIVE-manual-")} for r in rows],
            "year": year}


@router.get("/giving/{business_id}/ways")
def giving_ways_menu(business_id: str, user: AuthedUser = Depends(require_user)):
    """The treasurer's lists: "how it was given" (Cash, Check, the church's
    ways, Bank transfer, Other; `on` false: the plain four) and `funds`, the
    church's own funds as Settings, Giving lists them, so the treasurer
    picks from all of them, not only the ones already on a gift (Kevin,
    2026-11-01: "only general can be click the others are not showing up")."""
    from giving_records import require_finance
    import giving_ways
    require_finance(business_id, user)
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{business_id}&select=settings&limit=1")
    if rows is None:
        raise HTTPException(503, "The ways to give couldn't be loaded. Please retry.")
    cfg = giving_settings((rows[0] if rows else {}).get("settings"))
    funds = configured_funds(cfg)
    if not giving_ways.switched_on(business_id):
        return {"on": False, "methods": giving_ways.BASE_METHODS + giving_ways.TAIL_METHODS, "funds": funds}
    return {"on": True, "methods": giving_ways.method_menu(giving_ways.stored_ways(cfg)), "funds": funds}


def _manual_gift_fields(business_id, body, latest=None):
    """`latest`: the last day a gift may be dated (default UTC's today; a
    service count passes the church's own today)."""
    from decimal import Decimal, InvalidOperation
    from datetime import date
    try:
        cents = Decimal(str(body.get("amount_cents")))
        if not cents.is_finite() or cents != cents.to_integral_value() or not 1 <= cents <= MAX_GIFT_CENTS:
            raise ValueError()
        day = date.fromisoformat(str(body.get("received_on", "")))
        if day.year < 2000 or day > (latest or datetime.now(timezone.utc).date()):
            raise ValueError()
    except (ValueError, InvalidOperation):
        raise HTTPException(400, "Enter a valid amount and received date (not in the future)")
    import giving_ways
    method, way_name = body.get("method"), None
    if giving_ways.switched_on(business_id):
        # The church's ways (giving_ways.method_menu): Cash App, Zelle, ...,
        # or an app named under Other.
        try:
            method, way_name = giving_ways.parse_method(method)
        except giving_ways.WayError as e:
            raise HTTPException(400, str(e))
    elif method not in ("cash", "check", "bank_transfer", "other"):
        raise HTTPException(400, "Choose cash, check, bank transfer, or other")
    fund = str(body.get("fund") or "General").strip()
    if not fund or len(fund) > MAX_FUND_NAME_LEN:
        raise HTTPException(400, "Enter a fund name up to 40 characters")
    cid = body.get("contact_id") or None
    if cid:
        try: cid = str(uuid.UUID(str(cid)))
        except ValueError: raise HTTPException(400, "Choose a valid giver")
        contact = sb_clients.sb_get_as_service(f"/contacts?id=eq.{cid}&business_id=eq.{business_id}&select=id&limit=1")
        if contact is None:
            raise HTTPException(503, "Givers could not be loaded. Please retry.")
        if not contact:
            raise HTTPException(400, "Choose a giver from this business")
    amount = float(cents / 100)
    return {"_way_name": way_name,
            "contact_id": cid, "total": amount, "subtotal": amount,
            "paid_at": f"{day.isoformat()}T12:00:00Z", "due_date": day.isoformat(),
            "payment_method": method, "gift_fund": fund,
            "category": RESTRICTED_CATEGORY if is_designated(fund) else None,
            "items": [{"description": f"Gift — {fund_label(fund)}", "quantity": 1, "unit_price": amount, "total": amount}]}


@router.post("/giving/{business_id}/records")
def create_manual_gift(business_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    from giving_records import require_finance
    require_finance(business_id, user)
    church_keys.wall(business_id, user, "giving_money")
    return record_manual_gift(business_id, body, user)


def record_manual_gift(business_id: str, body: Dict[str, Any], user: AuthedUser, *,
                       extra: Optional[Dict[str, Any]] = None, notes: Optional[List[str]] = None,
                       type_checked: bool = False, latest: Optional[Any] = None) -> Dict[str, Any]:
    """The one way a gift is recorded by hand: the form above, and a service
    count (giving_services.record_gifts, which passes the count in `extra`
    and checks the business once for all its rows). The caller has checked
    who may record. `request_id` makes it safe to repeat: a second call
    with the same id answers {already: True} and records nothing."""
    from vertical_family import is_nonprofit_like
    if not type_checked:
        biz = sb_clients.sb_get_as_service(f"/businesses?id=eq.{business_id}&select=type&limit=1")
        if not biz or not is_nonprofit_like(biz[0].get("type")):
            raise HTTPException(409, "Giving is available to ministries and nonprofits")
    try: request_id = str(uuid.UUID(str(body.get("request_id"))))
    except ValueError: raise HTTPException(400, "A request identifier is required")
    number = f"GIVE-manual-{request_id}"
    fields = _manual_gift_fields(business_id, body, latest=latest)
    way_name = fields.pop("_way_name", None)
    existing = sb_clients.sb_get_as_service(f"/invoices?business_id=eq.{business_id}&invoice_number=eq.{number}&select=id&limit=1")
    if existing is None:
        raise HTTPException(503, "Giving records are temporarily unavailable")
    if existing:
        return {"ok": True, "id": existing[0]["id"], "already": True}
    lines = [f"Manual gift recorded by {user.id}"] + ([f"Given through {way_name}"] if way_name else []) + list(notes or [])
    row = {**fields, **(extra or {}), "business_id": business_id, "invoice_number": number, "is_gift": True,
           "status": "paid", "tax_rate": 0, "tax_amount": 0, "currency": "USD", "notes": "\n".join(lines)}
    saved = sb_clients.sb_post_as_service("/invoices", row)
    if not saved:
        raise HTTPException(503, "Gift could not be saved. Retry with the same request.")
    return {"ok": True, "id": saved[0]["id"]}


@router.patch("/giving/{business_id}/records/{gift_id}")
def correct_manual_gift(business_id: str, gift_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    from giving_records import require_finance
    require_finance(business_id, user)
    church_keys.wall(business_id, user, "giving_money")
    try: gift_id = str(uuid.UUID(gift_id))
    except ValueError: raise HTTPException(400, "Invalid gift")
    rows = sb_clients.sb_get_as_service(f"/invoices?id=eq.{gift_id}&business_id=eq.{business_id}&is_gift=eq.true&select=*&limit=1")
    if not rows:
        raise HTTPException(404, "Gift not found")
    original = rows[0]
    if not str(original.get("invoice_number", "")).startswith("GIVE-manual-"):
        raise HTTPException(409, "Online gifts are corrected through the payment provider")
    # A gift in a closed service count is locked with the count
    # (giving_services: the counters signed for it).
    if original.get("giving_count_id"):
        import giving_services
        closed = giving_services.gift_in_closed_count(business_id, original)
        if closed:
            raise HTTPException(409, f"This gift is in {closed}'s closed count. Reopen the count to correct it.")
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "Enter the reason for this correction")
    fields = _manual_gift_fields(business_id, body)
    way_name = fields.pop("_way_name", None)
    refund = body.get("refund_amount_cents", 0)
    if not isinstance(refund, int) or isinstance(refund, bool) or not 0 <= refund <= round(fields["total"] * 100):
        raise HTTPException(400, "Refund must be between zero and the gift amount")
    version = original.get("updated_at")
    if not version or str(body.get("updated_at")) != str(version):
        raise HTTPException(409, "This gift changed. Reload before correcting it.")
    fields.update(refund_amount_cents=refund, refunded_at=_now_iso() if refund else None)
    # Preserve the prior financial entry and reason in the existing audit trail.
    # The database trigger retains the old/new values, including manual corrections.
    fields["notes"] = ((original.get("notes") or "") + f"\nCorrection by {user.id}: " + reason[:300]
                       + (f"\nGiven through {way_name}" if way_name else ""))
    saved = sb_clients.sb_patch_as_service(f"/invoices?id=eq.{gift_id}&business_id=eq.{business_id}&updated_at=eq.{urllib.parse.quote(str(version), safe='')}", fields)
    if saved is None:
        raise HTTPException(503, "The gift could not be saved. Reload and retry.")
    if not saved:
        raise HTTPException(409, "The gift changed. Reload and retry.")
    return {"ok": True, "id": gift_id}
