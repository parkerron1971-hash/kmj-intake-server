"""margin.py — revenue minus what it cost to serve.

Nobody has ever computed this. pricing_config knows every price and
pack_economics checks that the prices are internally consistent with one
another; api_usage knows what every AI call cost. Nothing subtracted the
second from the first, so the platform has been priced against its own
price list rather than against its bill.

The audit put a number on why that matters: a Chief turn sells for
between 1.490c (founder) and 2.633c (starter) and costs 7.16c at the
mean, 19.84c at p95. Every tier loses money on conversation and makes it
back on builds. That is a decision to take deliberately or not at all,
and it cannot be taken while the number is invisible.

WHAT IS AND IS NOT COUNTED

Revenue is subscriptions PLUS credit-pack purchases. Packs used to be
missing entirely: credit_ledger recorded how many units moved and never
how much money did, so the panel understated real margin by the value of
every pack ever sold. credit_ledger.cents (2026-08-09) captures the
amount charged at purchase, and it is captured rather than derived on
purpose — `source` names the pack and pricing_config knows what that
pack costs TODAY, but the packs have been repriced once already, and
pricing off the current list would silently restate past months every
time they are repriced again.

Purchases predating that column cannot be back-filled with a fact nobody
recorded. They are priced from the current list and reported under
`pack_revenue_estimated_cents`, kept SEPARATE from the measured figure
rather than added to it. Mixing them would produce one number that is
partly measured and partly inferred, and nothing downstream could tell
which parts.

COGS is api_usage.cost_cents, which as of the seam-metering change
includes the 23 modules that never used to write a row. Numbers from
before 2026-08-09 undercount; do not compare across that boundary.

Everything is cents, integers where possible, and every function
degrades to zeros rather than raising — a billing panel that 500s tells
you less than one that shows a zero next to a label.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pricing_config
import sb_clients

logger = logging.getLogger("margin")

DEFAULT_WINDOW_DAYS = 30
# Subscription prices are monthly; a window of a different length is
# prorated against this so a 7-day view is not compared with a 30-day bill.
DAYS_PER_MONTH = 30.0

ACTIVE_STATUSES = ("active", "trialing", "past_due")


def _window_start_iso(days: int) -> str:
    # Z form, never isoformat's +00:00 — PostgREST silently returns zero
    # rows for the latter in a query string.
    start = datetime.now(timezone.utc) - timedelta(days=days)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def _monthly_cents_for_plan(plan: Optional[str]) -> int:
    prices = pricing_config.tier_price_cents()
    return int(prices.get((plan or "").strip().lower(), 0))


def _cogs_by_business(days: int) -> Dict[str, float]:
    """Sum api_usage.cost_cents per business over the window."""
    out: Dict[str, float] = defaultdict(float)
    try:
        rows = sb_clients.sb_get_as_service(
            f"/api_usage?created_at=gte.{_window_start_iso(days)}"
            f"&select=business_id,cost_cents&limit=100000") or []
    except Exception as e:
        logger.warning("[margin] api_usage read failed: %s", e)
        return out
    for r in rows:
        try:
            out[str(r.get("business_id") or "unattributed")] += float(
                r.get("cost_cents") or 0)
        except (TypeError, ValueError):
            continue
    return out


def _pack_revenue(days: int) -> Dict[str, Dict[str, float]]:
    """Pack revenue per business over the window, split by provenance.

    Returns {business_id: {"captured": cents, "estimated": cents}}.

    CAPTURED is what the row says it was charged. ESTIMATED is a row
    written before credit_ledger.cents existed, priced from today's list
    — a guess, kept in its own bucket so a caller can decide whether to
    trust it instead of being handed a blended total that hides the
    question.
    """
    out: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"captured": 0.0, "estimated": 0.0})
    try:
        rows = sb_clients.sb_get_as_service(
            f"/credit_ledger?kind=eq.purchase"
            f"&created_at=gte.{_window_start_iso(days)}"
            f"&select=business_id,cents,source&limit=100000") or []
    except Exception as e:
        logger.warning("[margin] pack revenue read failed: %s", e)
        return out

    packs = {}
    try:
        packs = pricing_config.credit_packs() or {}
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[margin] pack price list unavailable: %s", e)

    for r in rows:
        biz = str(r.get("business_id") or "")
        if not biz:
            continue
        cents = r.get("cents")
        if cents:
            out[biz]["captured"] += float(cents)
            continue
        # Pre-column row: recover the pack name from 'stripe:pack_medium'
        # and price it from the list as it stands now.
        source = str(r.get("source") or "")
        name = source.split("pack_", 1)[1].strip() if "pack_" in source else ""
        p = packs.get(name)
        if p and p.get("cents"):
            out[biz]["estimated"] += float(p["cents"])
        else:
            # A purchase whose pack no longer exists in the catalogue.
            # Silently dropping it would understate revenue with no sign
            # that anything was skipped.
            logger.warning(
                "[margin] purchase row for %s names pack %r, which is not in "
                "the current catalogue — excluded from revenue",
                biz[:8], name or source)
    return out


def _businesses() -> List[Dict[str, Any]]:
    try:
        return sb_clients.sb_get_as_service(
            "/businesses?select=id,name,subscription_plan,subscription_status"
            "&limit=10000") or []
    except Exception as e:
        logger.warning("[margin] businesses read failed: %s", e)
        return []


def business_margin(business_id: str, days: int = DEFAULT_WINDOW_DAYS
                    ) -> Dict[str, Any]:
    """Revenue, COGS and margin for one business over `days`."""
    rows = []
    try:
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}"
            f"&select=id,name,subscription_plan,subscription_status&limit=1") or []
    except Exception as e:
        logger.warning("[margin] business read failed: %s", e)
    biz = rows[0] if rows else {}
    cogs = _cogs_by_business(days).get(str(business_id), 0.0)
    packs = _pack_revenue(days).get(str(business_id),
                                    {"captured": 0.0, "estimated": 0.0})
    return _shape(biz, cogs, days, packs)


def _shape(biz: Dict[str, Any], cogs_cents: float, days: int,
           packs: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    plan = (biz.get("subscription_plan") or "").strip().lower() or None
    active = (biz.get("subscription_status") or "").strip().lower() in ACTIVE_STATUSES
    monthly = _monthly_cents_for_plan(plan) if active else 0
    subscription = monthly * (days / DAYS_PER_MONTH)

    packs = packs or {"captured": 0.0, "estimated": 0.0}
    pack_captured = float(packs.get("captured") or 0.0)
    pack_estimated = float(packs.get("estimated") or 0.0)

    # Only the MEASURED pack revenue enters the headline number. The
    # estimated part is reported beside it and deliberately excluded:
    # margin is a figure decisions get made on, and a decision taken on
    # a number that is quietly part guess is worse than one taken on a
    # number that is honestly short.
    revenue = subscription + pack_captured
    margin = revenue - cogs_cents

    # A pack sale is revenue from a business whose SUBSCRIPTION may be
    # cancelled — prepaid credits outlive the plan that bought them, and
    # they never expire (Kevin's ruling). So "has revenue" is no longer
    # the same question as "is active".
    has_revenue = revenue > 0
    return {
        "business_id": biz.get("id"),
        "name": biz.get("name"),
        "plan": plan,
        "active": active,
        "window_days": days,
        "revenue_cents": round(revenue, 2),
        "subscription_revenue_cents": round(subscription, 2),
        "pack_revenue_cents": round(pack_captured, 2),
        "pack_revenue_estimated_cents": round(pack_estimated, 2),
        "cogs_cents": round(cogs_cents, 2),
        "margin_cents": round(margin, 2),
        # None, not 0: a business with no revenue has no margin PERCENTAGE,
        # and reporting 0% would read as break-even rather than undefined.
        "margin_pct": (round(margin / revenue * 100, 1) if revenue > 0 else None),
        # Was `margin < 0 and active`. A business on a cancelled plan can
        # still be burning through prepaid credits, and that is exactly a
        # customer being served at a loss — the case the flag exists for.
        "underwater": margin < 0 and (active or has_revenue),
    }


def platform_margin(days: int = DEFAULT_WINDOW_DAYS) -> Dict[str, Any]:
    """Every business, plus per-tier and platform totals.

    `unattributed_cogs_cents` is the part that matters most on first
    read: AI spend whose api_usage row carried no business_id. It is
    real money with no customer attached to it, and because the seam
    meters without knowing the business, it is expected to be large
    until per-call attribution lands.
    """
    cogs = _cogs_by_business(days)
    packs = _pack_revenue(days)
    rows = [_shape(b, cogs.get(str(b.get("id")), 0.0), days,
                   packs.get(str(b.get("id"))))
            for b in _businesses()]

    by_tier: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        # Was `if not r["active"]: continue`. A cancelled business still
        # spending prepaid credits has real revenue and real COGS, and
        # skipping it dropped both out of the tier totals — so the tier
        # looked more profitable than it was.
        if not r["active"] and r["revenue_cents"] <= 0 and r["cogs_cents"] <= 0:
            continue
        t = by_tier.setdefault(r["plan"] or "none", {
            "businesses": 0, "revenue_cents": 0.0,
            "cogs_cents": 0.0, "margin_cents": 0.0, "underwater": 0})
        t["businesses"] += 1
        t["revenue_cents"] += r["revenue_cents"]
        t["cogs_cents"] += r["cogs_cents"]
        t["margin_cents"] += r["margin_cents"]
        t["underwater"] += 1 if r["underwater"] else 0
    for t in by_tier.values():
        t["margin_pct"] = (round(t["margin_cents"] / t["revenue_cents"] * 100, 1)
                           if t["revenue_cents"] > 0 else None)
        for k in ("revenue_cents", "cogs_cents", "margin_cents"):
            t[k] = round(t[k], 2)

    attributed = sum(v for k, v in cogs.items() if k != "unattributed")
    revenue = sum(r["revenue_cents"] for r in rows)
    total_cogs = sum(cogs.values())
    return {
        "window_days": days,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "totals": {
            "businesses": len(rows),
            "active": sum(1 for r in rows if r["active"]),
            "underwater": sum(1 for r in rows if r["underwater"]),
            "revenue_cents": round(revenue, 2),
            "subscription_revenue_cents": round(
                sum(r["subscription_revenue_cents"] for r in rows), 2),
            "pack_revenue_cents": round(
                sum(r["pack_revenue_cents"] for r in rows), 2),
            "cogs_cents": round(total_cogs, 2),
            "margin_cents": round(revenue - total_cogs, 2),
            "margin_pct": (round((revenue - total_cogs) / revenue * 100, 1)
                           if revenue > 0 else None),
        },
        # Outside `totals` on purpose: this is the part that is inferred
        # rather than measured, and burying it inside the headline block
        # would invite it being summed with the rest.
        "pack_revenue_estimated_cents": round(
            sum(r["pack_revenue_estimated_cents"] for r in rows), 2),
        "by_tier": by_tier,
        "unattributed_cogs_cents": round(cogs.get("unattributed", 0.0), 2),
        "attributed_cogs_cents": round(attributed, 2),
        "worst": sorted([r for r in rows if r["active"]],
                        key=lambda r: r["margin_cents"])[:20],
        "caveats": [
            "Revenue is subscriptions plus MEASURED credit-pack sales "
            "(credit_ledger.cents, captured at purchase from 2026-08-09).",
            "pack_revenue_estimated_cents covers purchases predating that "
            "column, priced from today's list. It is NOT in the totals — it "
            "is a guess, and margin should not be part guess.",
            "COGS is api_usage.cost_cents. Before 2026-08-09 that undercounted "
            "by 23 modules that never wrote a row; do not compare across it.",
            "Unattributed COGS is AI spend with no business_id on the row — "
            "real money with no customer attached.",
        ],
    }
