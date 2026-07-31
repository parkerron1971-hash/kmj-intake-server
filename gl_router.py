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
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user
import billing_limits
import gl_engine
import reports_engine

logger = logging.getLogger("gl_router")

router = APIRouter(prefix="/gl", tags=["general_ledger"])
_EPS = 0.01


def _access(biz: str, user: AuthedUser, min_role: str = "viewer") -> Dict[str, Any]:
    """Seat-access arc (7/31): the GL gate, role-ranked. Owner always
    passes; active accountant collaborators read; team seats pass by rank
    (viewer reads, manager verifies, admin rebuilds — see the matrix in
    business_users_router). Returns the business row like _owner did."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,type,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    row = rows[0]
    if str(row.get("owner_id")) == str(user.id):
        return row
    if min_role == "viewer":
        from business_collaborators_router import is_active_accountant
        if is_active_accountant(biz, str(user.id)):
            return row
    from business_users_router import require_role
    require_role(biz, str(user.id), min_role)
    return row


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    return _access(biz, user, "viewer")


def _log_admin(biz: str, action_type: str, result: Dict[str, Any], user: AuthedUser) -> None:
    """Best-effort admin audit — never block the action on a log failure."""
    try:
        # Keep the summary small (counts/flags only, not full payloads).
        summary = {k: result.get(k) for k in (
            "journal_entries_created", "skipped_existing", "ledger_lines_created",
            "deleted_journal_entries", "all_match", "balanced", "difference") if k in result}
        sb_clients.sb_post_as_service("/gl_admin_actions", {
            "business_id": biz, "action_type": action_type,
            "result_summary": summary, "performed_by": str(user.id),
        }, prefer=None)
    except Exception as e:
        logger.warning(f"[gl] admin log failed: {e}")


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
    b = _access(biz, user, "admin")   # rebuilds the whole ledger
    billing_limits.require_feature(biz, "general_ledger")
    nonusd = _scan_non_usd(biz)
    if nonusd["non_usd_count"] > 0:
        # GL-8 stop: don't guess FX.
        raise HTTPException(409, {
            "error": "non_usd_data_present",
            "message": "Non-USD money rows found — multi-currency is deferred (v2). "
                       "Resolve or exclude these before backfill.",
            **nonusd,
        })
    out = gl_engine.backfill(biz, b.get("type"))
    _log_admin(biz, "backfill", out, user)
    return out


@router.post("/backfill/reverse")
def reverse(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _access(biz, user, "admin")       # drops the whole ledger
    billing_limits.require_feature(biz, "general_ledger")
    out = gl_engine.reverse_backfill(biz)
    _log_admin(biz, "reverse", out, user)
    return out


@router.get("/trial-balance")
def trial_balance(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    billing_limits.require_feature(biz, "general_ledger")
    lines = gl_engine.read_ledger(biz)
    tb = gl_engine.trial_balance(lines)
    tb["ok"] = True
    tb["balanced"] = abs(tb["difference"]) < _EPS
    tb["ledger_lines"] = len(lines)
    return tb


# These two endpoints depend on the Phase I.2 migration (journal_entries.status
# + gl_divergence_alarms). Convert any internal failure into a clean
# HTTPException — an UNHANDLED exception escapes Starlette's CORSMiddleware and
# the browser then reports it as a CORS error rather than the real 500.
_I2_MIGRATION_HINT = ("GL live-sync failed. If this just started, apply the "
                      "Phase I.2 migration (2026_06_09_phasei2_gl_triggers.sql) — "
                      "it adds journal_entries.status + gl_divergence_alarms.")


@router.post("/process-queue")
def process_queue(biz: Optional[str] = None,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Manual / cron drain (Admin 'Force re-sync'). Owner-gated when biz given."""
    if biz:
        _owner(biz, user)
    try:
        out = gl_engine.process_queue(biz)
    except Exception as e:
        logger.warning(f"[gl] process-queue failed: {e}")
        raise HTTPException(500, f"{_I2_MIGRATION_HINT} ({e})")
    if biz:
        _log_admin(biz, "process_queue", out, user)
    return out


@router.get("/alarms")
def alarms(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Active divergence alarms for a business. Returns [] gracefully if the
    alarms table isn't present yet (migration not applied)."""
    _owner(biz, user)
    try:
        rows = sb_clients.sb_get_as_service(
            f"/gl_divergence_alarms?business_id=eq.{biz}&status=eq.active"
            f"&order=detected_at.desc&limit=20&select=id,summary,detected_at") or []
    except Exception as e:
        logger.warning(f"[gl] alarms read failed (treating as none): {e}")
        rows = []
    return {"ok": True, "alarms": rows}


@router.get("/verify")
def verify(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The I.1b reconciliation gate: GL (from persisted ledger) vs the current
    H.3a/H.1 engine, over all-time. All deltas must be ~0. Drains this
    business's queue first so the result reflects the latest source state."""
    _access(biz, user, "manager")     # drains the queue as a side effect
    billing_limits.require_feature(biz, "general_ledger")
    try:
        gl_engine.process_queue(biz)
    except Exception as e:
        logger.warning(f"[gl] pre-verify drain failed: {e}")
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

    out = {
        "ok": True, "business_id": biz, "all_match": all_match,
        "ledger_lines": len(lines), "checks": checks,
        "stripe_clearing_balance": gl_clearing_v,
        "clearing_note": ("Non-zero clearing = customer payments not yet matched to a bank "
                          "deposit (e.g. legacy platform-Stripe invoices). Expected; not an error."),
        "non_usd": _scan_non_usd(biz),
    }
    _log_admin(biz, "verify", out, user)
    return out


@router.get("/trust-status")
def trust_status(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """I.7 — IOLTA three-point check: GL trust cash (1200) vs the client-funds
    liability (2200) vs the bank's trust-account balance. All three equal =
    in-balance books. Ledger MECHANICS only — the formal per-client three-way
    reconciliation REPORT is I.10 + SME ruling."""
    _owner(biz, user)
    billing_limits.require_feature(biz, "vertical_ledgers")
    import gl_reports
    taccts = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{biz}&is_trust_account=is.true"
        f"&deleted_at=is.null"
        f"&select=account_id,name,mask,last_balance,included_in_bookkeeping") or []
    lines = gl_reports.effective_lines(biz)
    has_trust_lines = any(l["account_code"] in ("1200", "2200") for l in lines)
    if not taccts and not has_trust_lines:
        return {"ok": True, "has_trust_accounts": False}
    trust_cash_gl = gl_reports._net(lines, "1200", normal="debit")
    client_funds = gl_reports._net(lines, "2200", normal="credit")
    bank = round(sum(float(a.get("last_balance") or 0)
                     for a in taccts if a.get("included_in_bookkeeping")), 2)
    return {
        "ok": True, "has_trust_accounts": True,
        "accounts": [{"account_id": a.get("account_id"), "name": a.get("name"),
                      "mask": a.get("mask"), "last_balance": a.get("last_balance"),
                      "included_in_bookkeeping": a.get("included_in_bookkeeping")}
                     for a in taccts],
        "trust_cash_gl": trust_cash_gl,
        "client_funds_liability": client_funds,
        "bank_trust_balance": bank,
        "ledger_in_balance": abs(round(trust_cash_gl - client_funds, 2)) < _EPS,
        "matches_bank": abs(round(trust_cash_gl - bank, 2)) < _EPS,
    }


@router.get("/status")
def status(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Lightweight backfill state for the Admin dashboard (no full verify)."""
    _owner(biz, user)
    je = sb_clients.sb_get_as_service(
        f"/journal_entries?business_id=eq.{biz}&select=id,created_at"
        f"&order=created_at.desc&limit=20000") or []
    lines = gl_engine.read_ledger(biz)
    tb = gl_engine.trial_balance(lines)
    balanced = abs(tb["difference"]) < _EPS
    if not je:
        state = "not_backfilled"
    elif not balanced:
        state = "unbalanced"
    else:
        state = "backfilled"
    return {
        "ok": True, "business_id": biz, "state": state,
        "journal_entries": len(je), "ledger_lines": len(lines),
        "trial_balance": tb, "balanced": balanced,
        "stripe_clearing_balance": gl_engine.gl_clearing(lines),
        "last_backfill_at": (je[0].get("created_at") if je else None),
    }


@router.get("/admin-log")
def admin_log(user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Current user's last 50 GL admin actions (cross-user audit is future)."""
    rows = sb_clients.sb_get_as_service(
        f"/gl_admin_actions?performed_by=eq.{user.id}"
        f"&order=performed_at.desc&limit=50"
        f"&select=business_id,action_type,result_summary,performed_at") or []
    return {"ok": True, "actions": rows}
