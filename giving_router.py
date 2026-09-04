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
import logging
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

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

_FREQUENCIES = ("once", "monthly")


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


def is_designated(fund: Optional[str]) -> bool:
    """A gift to any fund other than the general fund is donor-DESIGNATED
    (restricted) by definition — the giver constrained its use. Rubric,
    not a lookup table: 'General' in any casing/spacing (with or without
    the word Fund) is the unrestricted default; everything else is
    designated."""
    norm = " ".join(str(fund or "").lower().split())
    return norm not in ("", "general", "general fund")


def fund_label(fund: Optional[str]) -> str:
    """Display label: 'General' → 'General Fund', 'Building Fund' stays.
    Used in line descriptions ('Gift — Building Fund') and receipts."""
    name = str(fund or "General").strip() or "General"
    return name if "fund" in name.lower() else f"{name} Fund"


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
    }


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

    settings["giving"] = cfg
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{business_id}", {"settings": settings},
    )
    biz = {**biz, "settings": settings}
    return _config_payload(biz, site)


# ─── Public checkout endpoint ────────────────────────────────────────


@router.post("/public/giving/{slug}/checkout")
async def public_giving_checkout(
    slug: str, body: Dict[str, Any], request: Request,
) -> Dict[str, Any]:
    """Anonymous: create the Stripe Checkout session for a gift.

    Body: { amount_cents: int, fund?: str, frequency?: 'once'|'monthly',
            name?: str, email?: str }
    Returns { ok, url } — the Stripe-hosted payment page.
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
        raise HTTPException(400, "frequency must be 'once' or 'monthly'")

    giver_name = str(body.get("name") or "").strip()[:120]
    giver_email = str(body.get("email") or "").strip().lower()[:200]
    if giver_email and ("@" not in giver_email or "." not in giver_email):
        raise HTTPException(400, "that email doesn't look right")
    if frequency == "monthly" and not giver_email:
        # Stripe needs an email to create the subscription customer, and
        # a recurring giver with no identity could never be attributed.
        raise HTTPException(400, "email is required for monthly giving")

    # ── Resolve slug → business ──
    sites = sb_clients.sb_get_as_service(
        f"/business_sites?slug=eq.{urllib.parse.quote(slug, safe='')}"
        f"&order=updated_at.desc&limit=1&select=business_id,slug"
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

    canonical = f"https://{sites[0].get('slug') or slug}.{PUBLIC_DOMAIN}/give"
    gift_id = str(uuid.uuid4())

    from payments_core import provider_for
    adapter = provider_for(biz)
    try:
        session = await adapter.create_giving_checkout(
            biz,
            gift_id=gift_id,
            business_id=str(biz["id"]),
            amount_cents=amount_cents,
            fund=fund,
            fund_label=fund_label(fund),
            fund_kind="restricted" if is_designated(fund) else "general",
            monthly=(frequency == "monthly"),
            giver_name=giver_name or None,
            giver_email=giver_email or None,
            success_url=f"{canonical}?thanks=1",
            cancel_url=f"{canonical}?canceled=1",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[giving] checkout create failed biz={str(biz['id'])[:8]}: {e}")
        raise HTTPException(502, "we couldn't start the payment — please try again")

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
    notes = (f"Online gift · {label}"
             + (" · monthly" if recurring else "")
             + (f" · {giver_email}" if giver_email else ""))

    payload: Dict[str, Any] = {
        "business_id": business_id,
        "contact_id": contact_id,
        "invoice_number": invoice_number,
        "status": "paid",
        "paid_at": _now_iso(),
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
                f"{', monthly' if recurring else ''}) biz={business_id[:8]} "
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
            "body": (f"A {'monthly ' if recurring else ''}gift to the "
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
            amount=amount, fund_display=label, recurring=recurring)
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
    )


def gift_metadata_from_stripe_invoice(inv: Dict[str, Any]) -> Dict[str, Any]:
    """The subscription's metadata as it rides a cycle's invoice.paid
    event: invoice.subscription_details.metadata (Stripe mirrors the
    Subscription's metadata there at invoice creation). Separate helper
    so the webhook's gift check and the recorder read ONE place."""
    sub = inv.get("subscription_details") or {}
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
    )


# ─── Acknowledgment email ────────────────────────────────────────────


def _schedule_gift_receipt(business_id: str, *, giver_email: str,
                           giver_name: str, amount: float,
                           fund_display: str, recurring: bool) -> None:
    """Fire-and-forget the receipt email when an event loop is running
    (the webhook path); never blocks or raises."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(send_gift_receipt(
            business_id, giver_email=giver_email, giver_name=giver_name,
            amount=amount, fund_display=fund_display, recurring=recurring))
    except RuntimeError:
        # No running loop (sync test context) — skip rather than build
        # bespoke threading for an opportunistic email.
        logger.info("[giving] no event loop — receipt email skipped")
    except Exception as e:
        logger.warning(f"[giving] receipt scheduling failed (fail-soft): {e}")


async def send_gift_receipt(business_id: str, *, giver_email: str,
                            giver_name: str, amount: float,
                            fund_display: str, recurring: bool) -> None:
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
        monthly_line = ("\nThis is a recurring monthly gift. Each month's "
                        "gift will appear on your year-end statement.\n"
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


def render_give_page(
    business: Dict[str, Any],
    canonical_url: str,
    slug: str,
    *,
    api_origin: str,
) -> str:
    """The public give page. Mobile-first by design — congregants give
    from phones: single column, ≤480px shell, 44px+ touch targets,
    16px inputs (no iOS zoom), no horizontal scroll at any width."""
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
    description = message or f"Give online to {name}. Secure one-time and monthly giving."
    css_vars = _brand_css_vars(business)

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
    # Precomputed (not a nested f-string) so the module parses on every
    # Python the deploy target might run.
    og_image_html = ""
    if logo_url:
        og_image_html = (f'<meta property="og:image" content="{_esc(logo_url)}">'
                         f'<link rel="icon" href="{_esc(logo_url)}">')

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
.gv-freq{{display:grid;grid-template-columns:1fr 1fr;gap:0;border:1.5px solid var(--border);
border-radius:12px;overflow:hidden;margin-top:4px;}}
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
</style>
</head>
<body>
<main class="gv-shell">
  <header class="gv-header">
    {logo_html}
    <h1 class="gv-name">{_esc(name)}</h1>
    <p class="gv-title">Give</p>
    {message_html}
  </header>
  <div id="gv-thanks" class="gv-banner">Thank you — your gift has been received.
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
    <div class="gv-freq">
      <button type="button" id="gv-once" class="on">One time</button>
      <button type="button" id="gv-monthly">Monthly</button>
    </div>
    <label class="gv-label" for="gv-nm">Name <span style="text-transform:none;font-weight:400">(optional)</span></label>
    <input type="text" id="gv-nm" class="gv-input" autocomplete="name" maxlength="120">
    <label class="gv-label" for="gv-em">Email <span style="text-transform:none;font-weight:400">(for your receipt)</span></label>
    <input type="email" id="gv-em" class="gv-input" autocomplete="email" maxlength="200">
    <button type="submit" class="gv-give" id="gv-go">Give</button>
    <div class="gv-error" id="gv-err"></div>
    <p class="gv-note">You'll finish securely on our payment page.
    Add your email to receive a receipt and your year-end giving statement.</p>
  </form>
  <footer class="gv-footer">
    Powered by <a href="https://mysolutionist.app/" target="_blank" rel="noopener">Solutionist</a>
  </footer>
</main>
<script>
(function() {{
  var API = {api_origin!r};
  var SLUG = {slug!r};
  var cents = 0, monthly = false;
  var q = new URLSearchParams(location.search);
  if (q.get('thanks')) document.getElementById('gv-thanks').classList.add('show');
  if (q.get('canceled')) document.getElementById('gv-canceled').classList.add('show');
  var amts = document.querySelectorAll('.gv-amt');
  var custom = document.getElementById('gv-custom');
  var go = document.getElementById('gv-go');
  var err = document.getElementById('gv-err');
  function label() {{
    var d = cents > 0 ? '$' + (cents / 100).toLocaleString(undefined,
      {{minimumFractionDigits: (cents % 100 ? 2 : 0)}}) : '';
    go.textContent = d ? ('Give ' + d + (monthly ? ' monthly' : '')) : 'Give';
  }}
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
  var onceBtn = document.getElementById('gv-once');
  var moBtn = document.getElementById('gv-monthly');
  onceBtn.addEventListener('click', function() {{
    monthly = false; onceBtn.classList.add('on'); moBtn.classList.remove('on'); label();
  }});
  moBtn.addEventListener('click', function() {{
    monthly = true; moBtn.classList.add('on'); onceBtn.classList.remove('on'); label();
  }});
  document.getElementById('gv-form').addEventListener('submit', function(ev) {{
    ev.preventDefault();
    err.classList.remove('show');
    if (cents < 100) {{ err.textContent = 'Please choose an amount ($1 minimum).'; err.classList.add('show'); return; }}
    var email = document.getElementById('gv-em').value.trim();
    if (monthly && !email) {{ err.textContent = 'Monthly giving needs an email so we can send your receipts.'; err.classList.add('show'); return; }}
    var fundSel = document.getElementById('gv-fund');
    go.disabled = true;
    fetch(API + '/public/giving/' + SLUG + '/checkout', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        amount_cents: cents,
        fund: fundSel ? fundSel.value : undefined,
        frequency: monthly ? 'monthly' : 'once',
        name: document.getElementById('gv-nm').value.trim() || undefined,
        email: email || undefined
      }})
    }}).then(function(r) {{ return r.json().then(function(j) {{ return {{ok: r.ok, j: j}}; }}); }})
      .then(function(res) {{
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
  label();
}})();
</script>
</body>
</html>"""


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
