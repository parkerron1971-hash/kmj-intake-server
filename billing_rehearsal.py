"""
billing_rehearsal.py — what BILLING_ENFORCE=on would do, today, to every
business, without turning it on.

WHY. Enforcement has been "one env flip" since July. Nobody flips a
switch that could lock paying customers out of their books without
knowing who it would lock, and until now the only way to know was to
flip it and watch. Every gate in feature_gates / billing_limits /
usage_metering short-circuits on enforcement_on(), so the decisions
could not be asked hypothetically either.

HOW. feature_gates.rehearsal() is a contextvar override: inside it,
enforcement_on() answers True for THIS task only — other requests on
the same process keep the real value. Under it, this module asks the
same pure decisions the gates ask (access_state, limit_for,
has_feature) with the same inputs, and adds the numeric picture
(units used against the allotment, credits on hand, seats, bank
connections, businesses per owner) computed READ-ONLY: it never calls
usage_summary, whose credit reconciliation writes the ledger.

WHAT IT ANSWERS, per business
  access        full | grace | locked, and why (the words the paywall
                would use)
  units         weighted usage this month or this trial, the allotment
                it would be held to, credits on hand, and whether the
                AI surfaces would 402 as out of units right now
  seats / banks / businesses
                the count against the plan's cap, and whether the next
                add would be refused
  features_lost the gated features this plan does not include, so a
                Professional business using Trust reports today can be
                seen before it is refused

and in aggregate: how many businesses would lock, would be in grace,
would be out of units, and would be over a cap. The platform owner
reads it at GET /platform/billing/rehearsal; `python billing_rehearsal.py`
prints the same table.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

import feature_gates
import sb_clients

logger = logging.getLogger("billing_rehearsal")

router = APIRouter(prefix="/platform/billing", tags=["platform-billing"])

_BIZ_SELECT = ("id,name,owner_id,is_active,subscription_status,subscription_plan,"
               "comp_tier,trial_ends_at,settings,created_at")


def _plan_rank(plan: Optional[str]) -> int:
    return feature_gates._PLAN_RANK.get(plan or "", 0)


def _units_picture(business_id: str, row: Dict[str, Any], plan: Optional[str],
                   grandfathered: bool) -> Dict[str, Any]:
    """usage_summary without the ledger write. Same arithmetic."""
    import credit_ledger
    import pricing_config
    import usage_metering as um
    trial_start = um.trial_window_start(row)
    on_trial = trial_start is not None
    used = (um.weighted_usage_since(business_id, trial_start) if on_trial
            else um.weighted_usage_this_month(business_id))
    allotment: Optional[int] = None
    if on_trial:
        allotment = pricing_config.trial_credits()
    elif plan:
        allotment = (feature_gates.plan_limits().get(plan) or {}).get("chief_messages_monthly")
    if allotment is not None:
        bonus = um.grant_units_this_month(business_id)
        if bonus > 0:
            allotment += bonus
    balance = credit_ledger.balance(business_id)
    hard_cap = bool(((row.get("settings") or {}) if isinstance(row.get("settings"), dict) else {}).get("usage_hard_cap"))
    out = False
    reason = None
    if not grandfathered and allotment is not None:
        if hard_cap and used >= allotment:
            out, reason = True, "hard_cap"
        elif used >= allotment and balance <= 0:
            out, reason = True, "out_of_units"
    return {"on_trial": on_trial, "used": used,
            "allotment": None if grandfathered else allotment,
            "credits_balance": balance, "hard_cap": hard_cap,
            "out_of_units": out, "reason": reason}


def rehearse_business(row: Dict[str, Any], *, owner_business_count: Optional[int] = None,
                      owner_best_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One business, as the gates would see it with enforcement on.
    Must be called inside feature_gates.rehearsal()."""
    import billing_limits
    import usage_metering as um
    business_id = str(row.get("id") or "")
    plan = feature_gates.plan_of(row)
    grandfathered = um.is_grandfathered_business(business_id, row)
    units = _units_picture(business_id, row, plan, grandfathered)
    trial_spent = bool(units["on_trial"] and not grandfathered
                       and units["allotment"] is not None
                       and units["used"] >= units["allotment"]
                       and units["credits_balance"] <= 0)
    access = feature_gates.access_state(row, grandfathered, trial_spent)

    seats = billing_limits.seat_count(business_id)
    banks = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{business_id}&deleted_at=is.null"
        f"&select=account_id&limit=200") or []
    # The caps bypass grandfathered accounts entirely (can_create_business,
    # can_connect_account both return unlimited for them); the first real
    # run flagged every beta business "over" because this read the plan's
    # limit without asking. Unlimited is the truth for them.
    if grandfathered:
        seat_limit = bank_limit = biz_limit = None
    else:
        seat_limit = feature_gates.limit_for(row, "max_seats")
        bank_limit = feature_gates.limit_for(row, "plaid_connections")
        biz_limit = feature_gates.limit_for(owner_best_row or row, "max_businesses")

    rank = _plan_rank(plan)
    lost = sorted(f for f, mp in feature_gates.FEATURE_MIN_PLAN.items()
                  if _plan_rank(mp) > rank) if not grandfathered else []

    return {
        "id": business_id, "name": row.get("name"), "owner_id": row.get("owner_id"),
        "plan": plan, "plan_display": billing_limits.PLAN_DISPLAY.get(plan or "", None),
        "subscription_status": row.get("subscription_status"),
        "comp_tier": row.get("comp_tier") or None,
        "grandfathered": grandfathered,
        "access": access,
        "units": units,
        "seats": {"count": seats, "limit": seat_limit,
                  "over": seat_limit is not None and seats > seat_limit,
                  "next_add_refused": seat_limit is not None and seats >= seat_limit},
        "banks": {"count": len(banks), "limit": bank_limit,
                  "over": bank_limit is not None and len(banks) > bank_limit},
        "businesses": {"count": owner_business_count, "limit": biz_limit,
                       "over": (biz_limit is not None and owner_business_count is not None
                                and owner_business_count > biz_limit)},
        "features_lost": lost,
    }


def rehearse_all(limit: int = 500) -> Dict[str, Any]:
    """Every active business, under rehearsal. Read-only."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?is_active=eq.true&select={_BIZ_SELECT}"
        f"&order=created_at.asc&limit={max(1, min(int(limit), 2000))}") or []
    by_owner: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_owner.setdefault(str(r.get("owner_id") or ""), []).append(r)

    out: List[Dict[str, Any]] = []
    with feature_gates.rehearsal():
        for r in rows:
            owned = by_owner.get(str(r.get("owner_id") or ""), [])
            best = max(owned, key=lambda x: _plan_rank(feature_gates.plan_of(x)), default=None)
            try:
                out.append(rehearse_business(r, owner_business_count=len(owned),
                                             owner_best_row=best))
            except Exception as e:  # one broken row must not hide the rest
                logger.warning(f"[rehearsal] {r.get('id')} failed: {e}")
                out.append({"id": r.get("id"), "name": r.get("name"),
                            "error": f"{type(e).__name__}: {str(e)[:120]}"})

    ok = [b for b in out if "error" not in b]
    summary = {
        "businesses": len(out),
        "would_lock": sum(1 for b in ok if b["access"]["state"] == "locked"),
        "in_grace": sum(1 for b in ok if b["access"]["state"] == "grace"),
        "full": sum(1 for b in ok if b["access"]["state"] == "full"),
        "out_of_units": sum(1 for b in ok if b["units"]["out_of_units"]),
        "over_seat_cap": sum(1 for b in ok if b["seats"]["over"]),
        "over_bank_cap": sum(1 for b in ok if b["banks"]["over"]),
        "over_business_cap": sum(1 for b in ok if b["businesses"]["over"]),
        "grandfathered": sum(1 for b in ok if b["grandfathered"]),
        "no_plan": sum(1 for b in ok if not b["plan"] and not b["grandfathered"]),
        "lock_reasons": _count(b["access"]["reason"] for b in ok if b["access"]["state"] == "locked"),
        "errors": len(out) - len(ok),
    }
    return {"ok": True, "enforcement_on_now": feature_gates.enforcement_on(),
            "summary": summary, "businesses": out}


def _count(items) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for i in items:
        out[str(i)] = out.get(str(i), 0) + 1
    return out


# ─── The owner's view ───────────────────────────────────────────────────

def _require_platform_owner():
    from lead_admin import require_owner
    return require_owner


@router.get("/rehearsal")
async def billing_rehearsal(limit: int = 500, _owner=Depends(_require_platform_owner())) -> Dict[str, Any]:
    """Platform owner only. What BILLING_ENFORCE=on would do right now."""
    import asyncio
    return await asyncio.to_thread(rehearse_all, limit)


def render(report: Dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        f"Billing rehearsal - enforcement is {'ON' if report['enforcement_on_now'] else 'off'} today",
        f"  businesses {s['businesses']} | would lock {s['would_lock']} | grace {s['in_grace']} | full {s['full']}",
        f"  out of units {s['out_of_units']} | over seat cap {s['over_seat_cap']} | over bank cap {s['over_bank_cap']} | over business cap {s['over_business_cap']}",
        f"  grandfathered {s['grandfathered']} | no plan {s['no_plan']} | errors {s['errors']}",
        "",
    ]
    for b in report["businesses"]:
        if "error" in b:
            lines.append(f"  ! {b.get('name')} ({str(b.get('id'))[:8]}): {b['error']}")
            continue
        a = b["access"]; u = b["units"]
        flag = "LOCK " if a["state"] == "locked" else "grace" if a["state"] == "grace" else "  ok "
        lines.append(f"  {flag} {str(b.get('name') or '')[:28]:<28} {str(b['plan'] or '-'):<12} "
                     f"{a['reason']:<22} units {u['used']}/{u['allotment'] if u['allotment'] is not None else 'unlimited'}"
                     f"{' OUT' if u['out_of_units'] else ''}"
                     f"{' seats>' if b['seats']['over'] else ''}{' banks>' if b['banks']['over'] else ''}"
                     f"{' biz>' if b['businesses']['over'] else ''}"
                     + (f"  loses {len(b['features_lost'])}" if b["features_lost"] else ""))
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    # A Windows console is cp1252 by default; the table is ASCII on
    # purpose, and stdout is widened anyway so a name with an accent
    # in it cannot crash the report either.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(render(rehearse_all()))
