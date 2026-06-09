"""
gl_router.py — Phase I.1 GL endpoints (owner-gated).

  POST /gl/backfill?biz=<id>          — idempotent backfill of all money data
  POST /gl/backfill/reverse?biz=<id>  — drop the business's GL (reversibility)
  GET  /gl/trial-balance?biz=<id>     — Σdebits, Σcredits, difference
  GET  /gl/verify?biz=<id>            — GL vs H.3a reconciliation (the I.1b gate)
"""
from __future__ import annotations

import logging
from datetime import date as _date
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user
import gl_engine
import reports_engine

logger = logging.getLogger("gl_router")

router = APIRouter(prefix="/gl", tags=["general_ledger"])
_EPS = 0.01


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,type,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _scan_non_usd(biz: str) -> Dict[str, Any]:
    """GL-8: surface any non-USD money rows before guessing FX."""
    inv = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{biz}&currency=not.is.null"
        f"&select=id,currency&limit=10000") or []
    bad_inv = [r["id"] for r in inv if (r.get("currency") or "USD").upper() not in ("USD", "")]
    px = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{biz}&iso_currency_code=not.is.null"
        f"&select=transaction_id,iso_currency_code&limit=20000") or []
    bad_px = [r["transaction_id"] for r in px if (r.get("iso_currency_code") or "USD").upper() not in ("USD", "")]
    return {"non_usd_invoices": bad_inv[:20], "non_usd_transactions": bad_px[:20],
            "non_usd_count": len(bad_inv) + len(bad_px)}


@router.post("/backfill")
def backfill(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    b = _owner(biz, user)
    nonusd = _scan_non_usd(biz)
    if nonusd["non_usd_count"] > 0:
        # GL-8 stop: don't guess FX.
        raise HTTPException(409, {
            "error": "non_usd_data_present",
            "message": "Non-USD money rows found — multi-currency is deferred (v2). "
                       "Resolve or exclude these before backfill.",
            **nonusd,
        })
    return gl_engine.backfill(biz, b.get("type"))


@router.post("/backfill/reverse")
def reverse(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    return gl_engine.reverse_backfill(biz)


@router.get("/trial-balance")
def trial_balance(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    lines = gl_engine.read_ledger(biz)
    tb = gl_engine.trial_balance(lines)
    tb["ok"] = True
    tb["balanced"] = abs(tb["difference"]) < _EPS
    tb["ledger_lines"] = len(lines)
    return tb


@router.get("/verify")
def verify(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The I.1b reconciliation gate: GL (from persisted ledger) vs the current
    H.3a/H.1 engine, over all-time. All deltas must be ~0."""
    _owner(biz, user)
    lines = gl_engine.read_ledger(biz)
    tb = gl_engine.trial_balance(lines)

    today = reports_engine._today()
    start = _date(2000, 1, 1)

    # GL side (from ledger).
    gl_pl = gl_engine.gl_pl_cash_basis(lines, start, today)
    gl_ar_v = gl_engine.gl_ar(lines)
    gl_ap_v = gl_engine.gl_ap(lines)
    gl_cash_v = gl_engine.gl_cash(lines)
    gl_clearing_v = gl_engine.gl_clearing(lines)

    # H.3a side (from source tables) — all-time custom window.
    h_pl = reports_engine.profit_and_loss(biz, "custom", None, start.isoformat(), today.isoformat())
    h_rev = h_pl["current"]["revenue"]["gross_revenue"]
    h_exp = h_pl["current"]["expenses"]["total"]
    h_net = h_pl["current"]["net_income"]
    h_ar = reports_engine.ar_aging(biz).get("total_outstanding", 0)
    h_ap = reports_engine.ap_aging(biz).get("total_outstanding", 0)
    h_bs = reports_engine.balance_sheet(biz)
    h_cash = h_bs["assets"]["cash"]

    def cmp(gl, h):
        return {"gl": round(gl, 2), "h3a": round(h, 2), "delta": round(gl - h, 2),
                "match": abs(gl - h) < _EPS}

    checks = {
        "trial_balance": {"debits": tb["debits"], "credits": tb["credits"],
                          "difference": tb["difference"], "balanced": abs(tb["difference"]) < _EPS},
        "pl_revenue": cmp(gl_pl["revenue"], h_rev),
        "pl_expenses": cmp(gl_pl["expenses"], h_exp),
        "pl_net_income": cmp(gl_pl["net_income"], h_net),
        "ar_total": cmp(gl_ar_v, h_ar),
        "ap_total": cmp(gl_ap_v, h_ap),
        "balance_sheet_cash": cmp(gl_cash_v, h_cash),
    }
    all_match = checks["trial_balance"]["balanced"] and all(
        v.get("match") for k, v in checks.items() if k != "trial_balance")

    return {
        "ok": True, "business_id": biz, "all_match": all_match,
        "ledger_lines": len(lines), "checks": checks,
        "stripe_clearing_balance": gl_clearing_v,
        "clearing_note": ("Non-zero clearing = customer payments not yet matched to a bank "
                          "deposit (e.g. legacy platform-Stripe invoices). Expected; not an error."),
        "non_usd": _scan_non_usd(biz),
    }
