"""
chief_bookkeeping.py — Phase G — Chief Bookkeeping Intelligence.

Isolated from the 12k-line chief_of_staff.py to keep blast radius tiny. All
reads/writes use sb_clients service-role with an explicit business_id filter
(Ruling 4 α). Proposals live in chief_bookkeeping_proposals; practitioner
overrides are captured in chief_learning_signals (Ruling 3).

Storage deviation from Ruling 1 (surfaced): chief_actions has no action_type
CHECK to extend (it's an append-only audit log), so proposals use a
dedicated table with their own proposal_type CHECK + status lifecycle. Inbox
routing reuses the existing agent_queue 'proposal' type — no constraint
surgery.

Trust-layer 4-question discipline (per feedback_chief_trust_layer_discipline)
is answered in comments on each proposal handler below.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta, date as _date
from typing import Any, Dict, List, Optional

import sb_clients
import plaid_categorization
import plaid_reconciliation

logger = logging.getLogger("chief_bookkeeping")

# Suggestion tolerance mirrors the Reconciliation UI (F.2 v1.6).
_SUGGEST_DAYS = 5
_SUGGEST_AMOUNT_PCT = 0.05

# HOME / Inbox proactive thresholds (Ruling 5: unmatched > 0 OR uncategorized > 5).
UNMATCHED_THRESHOLD = 0
UNCATEGORIZED_THRESHOLD = 5

_PROPOSAL_TYPES = ("propose_match", "propose_categorize", "propose_exclude")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Ownership (service-role + explicit business_id, Ruling 4 α) ──────

def owner_business(business_id: str, user_id: str) -> Dict[str, Any]:
    """Return the business row iff user_id owns it; else raise. Mirrors the
    plaid_router owner gate."""
    from fastapi import HTTPException
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type,owner_id&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user_id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _included_account_ids(business_id: str) -> List[str]:
    rows = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{business_id}"
        f"&included_in_bookkeeping=eq.true&deleted_at=is.null&select=account_id"
    ) or []
    return [r["account_id"] for r in rows if r.get("account_id")]


def _has_linked_items(business_id: str) -> bool:
    rows = sb_clients.sb_get_as_service(
        f"/plaid_items?business_id=eq.{business_id}&status=eq.active&select=item_id&limit=1"
    ) or []
    return bool(rows)


# ─── Counts + context (for HOME nudge + Chief system prompt) ──────────

def bookkeeping_counts(business_id: str) -> Dict[str, Any]:
    """Cheap counts driving the HOME/Inbox nudge + the prompt block."""
    included = _included_account_ids(business_id)
    if not included:
        return {"linked": _has_linked_items(business_id), "unmatched": 0,
                "unmatched_total": 0.0, "uncategorized": 0}
    acct = "account_id=in.(" + ",".join(included) + ")"

    unmatched = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{business_id}&{acct}"
        f"&excluded_from_books=eq.false&pending=eq.false"
        f"&reconciliation_status=eq.unmatched&amount=lt.0&select=amount&limit=2000"
    ) or []
    # Uncategorized = no bucket, or the 'other' catch-all (Plaid couldn't place it).
    uncat = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{business_id}&{acct}"
        f"&excluded_from_books=eq.false&pending=eq.false"
        f"&or=(business_category.is.null,business_category.eq.other)&select=transaction_id&limit=2000"
    ) or []
    return {
        "linked": True,
        "unmatched": len(unmatched),
        "unmatched_total": round(sum(abs(float(u.get("amount") or 0)) for u in unmatched), 2),
        "uncategorized": len(uncat),
    }


def needs_attention(counts: Dict[str, Any]) -> bool:
    return bool(counts.get("linked")) and (
        counts.get("unmatched", 0) > UNMATCHED_THRESHOLD
        or counts.get("uncategorized", 0) > UNCATEGORIZED_THRESHOLD
    )


def gather_and_format(business_id: str, business_type: Optional[str] = None) -> str:
    """Build the conditional bookkeeping section for Chief's system prompt.
    Returns '' when the business has no linked bank (keeps the prompt clean).
    Stays well under ~600 tokens so it can't bloat the prompt (stop cond)."""
    try:
        if not _has_linked_items(business_id):
            return ""
        counts = bookkeeping_counts(business_id)
        included = _included_account_ids(business_id)
        cash = 0.0
        if included:
            accts = sb_clients.sb_get_as_service(
                f"/plaid_accounts?business_id=eq.{business_id}&type=eq.depository"
                f"&included_in_bookkeeping=eq.true&deleted_at=is.null&select=last_balance"
            ) or []
            cash = round(sum(float(a.get("last_balance") or 0) for a in accts), 2)

        # 30-day income / expense.
        income = expense = 0.0
        if included:
            acct = "account_id=in.(" + ",".join(included) + ")"
            since = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
            txs = sb_clients.sb_get_as_service(
                f"/plaid_transactions?business_id=eq.{business_id}&{acct}"
                f"&excluded_from_books=eq.false&pending=eq.false&date=gte.{since}"
                f"&select=amount,plaid_category_primary,plaid_category_detail&limit=3000"
            ) or []
            for t in txs:
                a = float(t.get("amount") or 0)
                if a < 0:
                    income += -a
                elif not plaid_categorization.is_income_category(
                    t.get("plaid_category_primary"), t.get("plaid_category_detail")):
                    expense += a

        signals = recent_learning_signals(business_id, days=30)
        vbk = _vertical_bookkeeping(business_type)

        lines = [
            "BOOKKEEPING (live bank data — answer money questions from this):",
            f"  Cash on hand: ${cash:,.2f}",
            f"  Last 30 days: +${income:,.2f} in / -${expense:,.2f} out",
            f"  Unreconciled deposits: {counts['unmatched']} (${counts['unmatched_total']:,.2f})",
            f"  Needs categorization: {counts['uncategorized']}",
        ]
        if signals:
            lines.append(f"  Recent practitioner overrides of your proposals: {len(signals)} "
                         "(respect their preferences when proposing).")
        if vbk.get("category_note"):
            lines.append(f"  Vertical note: {vbk['category_note']}")
        if vbk.get("nudges"):
            lines.append(f"  Seasonal nudges to weave in when relevant: {'; '.join(vbk['nudges'])}")
        lines += _gl_context_lines(business_id)
        lines.append("  Voice: warm, precise, practical. Cite real numbers. Offer to walk through "
                     "unreconciled or uncategorized items; never auto-change books without approval.")
        return "\n".join(lines)
    except Exception as e:  # never break the prompt
        logger.warning(f"[chief_bk] gather_and_format failed: {e}")
        return ""


def _gl_context_lines(business_id: str) -> List[str]:
    """Phase I.5 — a tight GL block (~5 lines, well within the prompt budget)
    so Chief can answer ledger questions (account balances, trial balance,
    recent activity). Empty when the business has no GL."""
    try:
        import gl_reports
        if not gl_reports.gl_active(business_id):
            return []
        lines_ = gl_reports.effective_lines(business_id)
        import gl_engine
        cash = gl_engine.gl_cash(lines_)
        ar = gl_engine.gl_ar(lines_)
        ap = gl_engine.gl_ap(lines_)
        clearing = gl_engine.gl_clearing(lines_)
        tb = gl_engine.trial_balance(lines_)
        recent = sb_clients.sb_get_as_service(
            f"/journal_entries?business_id=eq.{business_id}&status=eq.active"
            f"&order=created_at.desc&limit=3&select=entry_date,description") or []
        diff = tb["difference"]
        tb_status = "balanced" if abs(diff) < 0.01 else f"OFF by ${abs(diff):,.2f} — flag this"
        out = [
            "  GENERAL LEDGER (double-entry; the authoritative books):",
            f"    Cash ${cash:,.2f} · AR ${ar:,.2f} · AP ${ap:,.2f} · Stripe Clearing ${clearing:,.2f}",
            f"    Trial balance: {tb_status}",
        ]
        if recent:
            out.append("    Recent entries: " + "; ".join(
                f"{r.get('entry_date')} {(r.get('description') or '')[:40]}" for r in recent))
        return out
    except Exception as e:
        logger.warning(f"[chief_bk] GL context failed: {e}")
        return []


def _vertical_bookkeeping(business_type: Optional[str]) -> Dict[str, Any]:
    try:
        import vertical_intelligence
        return vertical_intelligence.get_bookkeeping(business_type) or {}
    except Exception:
        return {}


# ─── Learning signals (Ruling 3 — capture only in v1) ────────────────

def capture_learning_signal(business_id: str, proposal_type: str,
                            original: Dict[str, Any],
                            override: Optional[Dict[str, Any]],
                            reason: Optional[str]) -> None:
    """Synchronous small write (Ruling: synchronous). Best-effort — a failed
    capture must never block the reject flow."""
    try:
        sb_clients.sb_post_as_service("/chief_learning_signals", {
            "business_id": business_id,
            "proposal_type": proposal_type,
            "original_proposal": original,
            "practitioner_override": override,
            "override_reason": reason,
            "created_at": _now_iso(),
        }, prefer=None)
    except Exception as e:
        logger.warning(f"[chief_bk] learning signal capture failed: {e}")


def recent_learning_signals(business_id: str, *, days: int = 30) -> List[Dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return sb_clients.sb_get_as_service(
        f"/chief_learning_signals?business_id=eq.{business_id}"
        f"&created_at=gte.{since}&order=created_at.desc&limit=50"
        f"&select=proposal_type,original_proposal,practitioner_override,override_reason,created_at"
    ) or []


# ─── Proposal storage ────────────────────────────────────────────────

def _insert_proposal(business_id: str, ptype: str, *, plaid_transaction_id=None,
                     stripe_payout_id=None, proposed: Dict[str, Any],
                     confidence=None, reasoning="") -> Optional[Dict[str, Any]]:
    res = sb_clients.sb_post_as_service("/chief_bookkeeping_proposals", {
        "business_id": business_id,
        "proposal_type": ptype,
        "status": "pending",
        "plaid_transaction_id": plaid_transaction_id,
        "stripe_payout_id": stripe_payout_id,
        "proposed": proposed,
        "confidence": confidence,
        "reasoning": reasoning,
    })
    return (res or [None])[0] if isinstance(res, list) else res


def _existing_pending_for_tx(business_id: str, tx_id: str) -> bool:
    rows = sb_clients.sb_get_as_service(
        f"/chief_bookkeeping_proposals?business_id=eq.{business_id}"
        f"&plaid_transaction_id=eq.{tx_id}&status=eq.pending&select=id&limit=1"
    ) or []
    return bool(rows)


def list_proposals(business_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    parts = [f"business_id=eq.{business_id}"]
    if status:
        parts.append(f"status=eq.{status}")
    parts.append("order=created_at.desc&limit=200&select=*")
    return sb_clients.sb_get_as_service(
        f"/chief_bookkeeping_proposals?{'&'.join(parts)}") or []


def _get_proposal(business_id: str, proposal_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/chief_bookkeeping_proposals?id=eq.{proposal_id}"
        f"&business_id=eq.{business_id}&select=*&limit=1"
    ) or []
    return rows[0] if rows else None


# ═══════════════════════════════════════════════════════════════════
# Analyzers — generate proposals
# ═══════════════════════════════════════════════════════════════════

def analyze_unmatched(business_id: str, *, limit: int = 25) -> List[Dict[str, Any]]:
    """propose_match — Chief suggests a Stripe payout for an unmatched deposit.

    Trust-layer 4 questions:
      1. Narration: Chief says "I found a Stripe payout that matches this
         $X deposit within N days — want me to link them?" (reasoning field).
      2. Action returns: a pending proposal row; nothing changes until the
         practitioner approves (hybrid inline/Inbox flow).
      3. Second pass: on approve, the deposit flips to manual_matched and the
         Reconciliation UI/Cash Flow reflect it immediately.
      4. Deflection: if no candidate is within ±5d/±5%, NO proposal is made
         (Chief doesn't guess); the row stays unmatched for manual handling.
    """
    included = _included_account_ids(business_id)
    if not included:
        return []
    acct = "account_id=in.(" + ",".join(included) + ")"
    deposits = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{business_id}&{acct}"
        f"&excluded_from_books=eq.false&pending=eq.false"
        f"&reconciliation_status=eq.unmatched&amount=lt.0"
        f"&order=date.desc&limit={int(limit)}"
        f"&select=transaction_id,amount,date,name,merchant_name"
    ) or []
    if not deposits:
        return []

    stripe_acct = plaid_reconciliation.stripe_account_for_business(business_id)
    if not stripe_acct:
        return []

    # Already-matched payout ids (don't double-propose).
    matched = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{business_id}"
        f"&reconciled_to_payout_id=not.is.null&select=reconciled_to_payout_id"
    ) or []
    used = {r["reconciled_to_payout_id"] for r in matched if r.get("reconciled_to_payout_id")}

    created: List[Dict[str, Any]] = []
    for d in deposits:
        if _existing_pending_for_tx(business_id, d["transaction_id"]):
            continue
        dep_amt = abs(float(d.get("amount") or 0))
        try:
            y, m, dd = (int(p) for p in (d.get("date") or "").split("-"))
            anchor = _date(y, m, dd)
        except Exception:
            continue
        payouts = plaid_reconciliation.fetch_stripe_payouts_range(
            stripe_acct, anchor - timedelta(days=_SUGGEST_DAYS), anchor + timedelta(days=_SUGGEST_DAYS))
        tol = dep_amt * _SUGGEST_AMOUNT_PCT
        best = None
        for po in payouts:
            if po.get("id") in used:
                continue
            po_amt = (po.get("amount") or 0) / 100.0
            delta = abs(po_amt - dep_amt)
            if delta <= tol:
                if best is None or delta < best[1]:
                    best = (po, delta)
        if not best:
            continue
        po, delta = best
        po_amt = (po.get("amount") or 0) / 100.0
        po_date = plaid_reconciliation._payout_arrival_iso(po)
        day_delta = abs((anchor - _date(*map(int, (po_date or anchor.isoformat()).split("-")))).days)
        confidence = round(max(0.0, 1.0 - (delta / (tol or 1)) * 0.4 - (day_delta / _SUGGEST_DAYS) * 0.3), 2)
        reasoning = (f"This ${dep_amt:,.2f} deposit on {d.get('date')} matches Stripe payout "
                     f"{(po.get('id') or '')[:14]}… of ${po_amt:,.2f} (arrived {po_date}, "
                     f"{day_delta} day(s) apart). Link them?")
        row = _insert_proposal(
            business_id, "propose_match",
            plaid_transaction_id=d["transaction_id"], stripe_payout_id=po.get("id"),
            proposed={"plaid_transaction_id": d["transaction_id"], "stripe_payout_id": po.get("id"),
                      "payout_amount": round(po_amt, 2), "payout_date": po_date},
            confidence=confidence, reasoning=reasoning)
        used.add(po.get("id"))
        if row:
            created.append(row)
    return created


def analyze_uncategorized(business_id: str, *, limit: int = 25) -> List[Dict[str, Any]]:
    """propose_categorize — Chief suggests a 5-bucket for an uncategorized tx.

    Trust-layer 4 questions:
      1. Narration: "This $X from {merchant} looks like {bucket} — recategorize?"
      2. Action returns: a pending proposal; books unchanged until approved.
      3. Second pass: on approve, business_category updates; Cash Flow buckets
         + Tax Set-Aside recompute.
      4. Deflection: only proposes when the Plaid-derived bucket differs from
         the current one AND isn't itself 'other' — otherwise stays silent.
    """
    included = _included_account_ids(business_id)
    if not included:
        return []
    acct = "account_id=in.(" + ",".join(included) + ")"
    rows = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{business_id}&{acct}"
        f"&excluded_from_books=eq.false&pending=eq.false"
        f"&or=(business_category.is.null,business_category.eq.other)"
        f"&order=date.desc&limit={int(limit)}"
        f"&select=transaction_id,amount,date,name,merchant_name,business_category,"
        f"plaid_category_primary,plaid_category_detail"
    ) or []
    # G v1.5 — learning loop: stop proposing buckets the practitioner has
    # repeatedly rejected (signals now feed BACK into generation).
    try:
        import chief_llm
        suppressed = chief_llm.suppressed_categorizations(business_id)
    except Exception:
        suppressed = set()
    created: List[Dict[str, Any]] = []
    for t in rows:
        if _existing_pending_for_tx(business_id, t["transaction_id"]):
            continue
        suggested = plaid_categorization.map_plaid_to_bucket(
            t.get("plaid_category_primary"), t.get("plaid_category_detail"))
        current = t.get("business_category")
        if not suggested or suggested == "other" or suggested == current:
            continue
        if suggested in suppressed:
            continue
        merchant = t.get("merchant_name") or t.get("name") or "this transaction"
        amt = abs(float(t.get("amount") or 0))
        reasoning = (f"${amt:,.2f} from {merchant} (Plaid: "
                     f"{t.get('plaid_category_primary') or '—'}) looks like "
                     f"{suggested.replace('_', ' ')} rather than '{current or 'uncategorized'}'.")
        row = _insert_proposal(
            business_id, "propose_categorize",
            plaid_transaction_id=t["transaction_id"],
            proposed={"plaid_transaction_id": t["transaction_id"],
                      "business_category": suggested, "business_subcategory": None},
            confidence=0.7, reasoning=reasoning)
        if row:
            created.append(row)
    return created


# ═══════════════════════════════════════════════════════════════════
# Resolve proposals — approve / reject / send-to-inbox
# ═══════════════════════════════════════════════════════════════════

_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _period_label(p: Dict[str, Any]) -> str:
    try:
        y, m, _ = (int(x) for x in (p.get("period_start") or "").split("-"))
    except Exception:
        return p.get("period_type", "period")
    if p.get("period_type") == "month":
        return f"{_MONTHS[m]} {y}"
    if p.get("period_type") == "quarter":
        return f"Q{(m - 1) // 3 + 1} {y}"
    return f"{y}"


def _to_date(s: Optional[str]):
    try:
        return _date(*(int(x) for x in (s or "")[:10].split("-")))
    except Exception:
        return None


def period_close_candidate(business_id: str) -> Optional[Dict[str, Any]]:
    """The OPEN, fully-reconciled period at/near its end and ready to close.
    Prefers year > quarter > month when several end together."""
    import gl_engine
    today = datetime.now(timezone.utc).date()
    for ptype in ("year", "quarter", "month"):
        p = gl_engine.period_covering(business_id, today.isoformat(), ptype)
        if not p or p.get("status") != "open":
            continue
        end = _to_date(p.get("period_end"))
        if not end or (end - today).days > 2 or (end - today).days < 0:
            continue                              # only within the last ~3 days
        counts = gl_engine.period_counts(business_id, p["period_start"], p["period_end"])
        if counts.get("transactions", 0) > 0 and counts.get("unmatched", 0) == 0:
            p["_counts"] = counts
            return p
    return None


def analyze_period_close(business_id: str) -> List[Dict[str, Any]]:
    """propose_period_close — at a reconciled period end, Chief offers to close.

    Trust-layer 4 questions:
      1. Narration: "All N transactions in {period} are reconciled — close it?"
      2. Action returns: a pending proposal; nothing closes until approved.
      3. Second pass: on approve, the period locks (+ year-end closing entry).
      4. Deflection: only proposes within the last ~3 days of a period AND
         only when fully reconciled; respects a rejection for 7 days.
    """
    cand = period_close_candidate(business_id)
    if not cand:
        return []
    period_id = cand["id"]
    recent = sb_clients.sb_get_as_service(
        f"/chief_bookkeeping_proposals?business_id=eq.{business_id}"
        f"&proposal_type=eq.propose_period_close"
        f"&select=status,proposed,resolved_at&limit=50") or []
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    for r in recent:
        if (r.get("proposed") or {}).get("period_id") != period_id:
            continue
        if r.get("status") == "pending":
            return []                              # already proposed
        if r.get("status") == "rejected" and (r.get("resolved_at") or "") >= since:
            return []                              # respect the practitioner's pace (7d)
    label = _period_label(cand)
    c = cand.get("_counts") or {}
    reasoning = (f"All {c.get('transactions', 0)} transactions in {label} are reconciled. "
                 f"Closing locks the period so nothing gets edited by accident. "
                 f"Want me to close {label}?")
    row = _insert_proposal(
        business_id, "propose_period_close",
        proposed={"period_id": period_id, "period_label": label,
                  "period_type": cand.get("period_type"), "summary": c},
        confidence=0.9, reasoning=reasoning)
    return [row] if row else []


def _pending_of_type(business_id: str, ptype: str) -> List[Dict[str, Any]]:
    return sb_clients.sb_get_as_service(
        f"/chief_bookkeeping_proposals?business_id=eq.{business_id}"
        f"&proposal_type=eq.{ptype}&status=eq.pending&select=id,proposed&limit=10") or []


def analyze_gl(business_id: str) -> List[Dict[str, Any]]:
    """Phase I.5 — deterministic GL analyzers (LLM-in-loop richness is Phase
    G v1.5, sequenced later). Two cases:

    propose_account_reconciliation — GL Cash has drifted from the live bank
      snapshot (stale queue / missed sync). Approve = drain the sync queue +
      re-plug the opening balance, then the books match the bank again.
      Trust-layer: narration cites both numbers; nothing changes until
      approved; deflects when GL ≡ bank.

    propose_journal_entry — after a year-end close, Opening Balance Equity
      still carries a balance. The standard accountant cleanup is a reclass
      to Owner's Equity. Approve = post that balanced manual journal entry.
      Trust-layer: only fires post-close; the exact Dr/Cr is shown in the
      reasoning; deflects when 3000 is already zero or no year is closed.
    """
    import gl_reports
    import gl_engine
    created: List[Dict[str, Any]] = []
    if not gl_reports.gl_active(business_id):
        return created
    lines_ = gl_reports.effective_lines(business_id)

    # ── account reconciliation: GL Cash vs live bank snapshot ──
    gl_cash = gl_engine.gl_cash(lines_)
    accts = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{business_id}&type=eq.depository"
        f"&included_in_bookkeeping=eq.true&deleted_at=is.null&select=last_balance") or []
    bank_cash = round(sum(float(a.get("last_balance") or 0) for a in accts), 2)
    drift = round(bank_cash - gl_cash, 2)
    if abs(drift) >= 0.01 and not _pending_of_type(business_id, "propose_account_reconciliation"):
        row = _insert_proposal(
            business_id, "propose_account_reconciliation",
            proposed={"gl_cash": gl_cash, "bank_cash": bank_cash, "drift": drift},
            confidence=0.95,
            reasoning=(f"Your ledger shows ${gl_cash:,.2f} in Cash but the bank reports "
                       f"${bank_cash:,.2f} (off by ${abs(drift):,.2f}). Want me to reconcile "
                       f"the books against the bank? I'll process any pending changes and "
                       f"true-up the opening balance."))
        if row:
            created.append(row)

    # ── journal entry: post-close Opening Balance Equity reclass ──
    closed_years = sb_clients.sb_get_as_service(
        f"/accounting_periods?business_id=eq.{business_id}&period_type=eq.year"
        f"&status=eq.closed&select=id&limit=1") or []
    if closed_years:
        import gl_reports as _glr
        obe = _glr._net(lines_, "3000", normal="credit")   # Opening Balance Equity
        if abs(obe) >= 0.01 and not _pending_of_type(business_id, "propose_journal_entry"):
            if obe > 0:
                je_lines = [{"code": "3000", "debit": round(obe, 2), "credit": 0.0},
                            {"code": "3100", "debit": 0.0, "credit": round(obe, 2)}]
                verb = f"move ${obe:,.2f} from Opening Balance Equity into Owner's Equity"
            else:
                je_lines = [{"code": "3100", "debit": round(-obe, 2), "credit": 0.0},
                            {"code": "3000", "debit": 0.0, "credit": round(-obe, 2)}]
                verb = f"clear a ${-obe:,.2f} debit in Opening Balance Equity against Owner's Equity"
            row = _insert_proposal(
                business_id, "propose_journal_entry",
                proposed={"description": "Reclass Opening Balance Equity to Owner's Equity",
                          "lines": je_lines},
                confidence=0.85,
                reasoning=(f"Your year is closed but Opening Balance Equity still carries a "
                           f"balance — the standard cleanup is to {verb}. This is the same "
                           f"reclass an accountant would post at year-end. Approve to post it."))
            if row:
                created.append(row)
    return created


def approve_proposal(business_id: str, proposal_id: str, approved_by: str = "") -> Dict[str, Any]:
    """Execute a pending proposal, then mark it approved."""
    from fastapi import HTTPException
    p = _get_proposal(business_id, proposal_id)
    if not p:
        raise HTTPException(404, "proposal not found")
    if p.get("status") != "pending":
        # Idempotent: approving an already-resolved proposal is a no-op.
        return {"ok": True, "already": p.get("status")}

    proposed = p.get("proposed") or {}
    ptype = p.get("proposal_type")
    tx_id = p.get("plaid_transaction_id")

    if ptype == "propose_match":
        patch = {
            "reconciled_to_payout_id": proposed.get("stripe_payout_id"),
            "reconciliation_status": "manual_matched",
            "manual_match_reason": "chief_proposal",
            "ignored_at": None,
            "updated_at": _now_iso(),
        }
        if proposed.get("payout_amount") is not None:
            patch["reconciled_payout_amount"] = round(float(proposed["payout_amount"]), 2)
        if proposed.get("payout_date"):
            patch["reconciled_payout_date"] = proposed["payout_date"]
        sb_clients.sb_patch_as_service(
            f"/plaid_transactions?transaction_id=eq.{tx_id}&business_id=eq.{business_id}", patch)
    elif ptype == "propose_categorize":
        sb_clients.sb_patch_as_service(
            f"/plaid_transactions?transaction_id=eq.{tx_id}&business_id=eq.{business_id}",
            {"business_category": proposed.get("business_category"),
             "business_subcategory": proposed.get("business_subcategory"),
             "updated_at": _now_iso()})
    elif ptype == "propose_exclude":
        sb_clients.sb_patch_as_service(
            f"/plaid_transactions?transaction_id=eq.{tx_id}&business_id=eq.{business_id}",
            {"excluded_from_books": True, "updated_at": _now_iso()})
    elif ptype == "propose_period_close":
        import gl_engine
        period_id = proposed.get("period_id")
        if not period_id:
            raise HTTPException(400, "proposal missing period_id")
        gl_engine.close_period(business_id, period_id,
                               closed_by=(approved_by or "chief"), closed_via="chief_auto_close")
    elif ptype == "propose_account_reconciliation":
        import gl_engine
        # Drain pending sync work + true-up the opening balance plug.
        gl_engine.process_queue(business_id)
        coa = gl_engine.ensure_chart_of_accounts(business_id, gl_engine._biz_type(business_id))
        gl_engine.reconcile_opening_balance(business_id, coa)
    elif ptype == "propose_journal_entry":
        import gl_engine
        je_lines = proposed.get("lines") or []
        if not je_lines:
            raise HTTPException(400, "proposal missing journal lines")
        deb = round(sum(float(l.get("debit") or 0) for l in je_lines), 2)
        cred = round(sum(float(l.get("credit") or 0) for l in je_lines), 2)
        if abs(deb - cred) >= 0.01:
            raise HTTPException(400, "proposed journal entry is not balanced")
        coa = gl_engine.ensure_chart_of_accounts(business_id, gl_engine._biz_type(business_id))
        spec = gl_engine._entry(
            None, "manual", f"chief_{proposal_id}",
            proposed.get("description") or "Chief-proposed journal entry",
            [gl_engine._line(l["code"], debit=float(l.get("debit") or 0),
                             credit=float(l.get("credit") or 0),
                             memo="chief proposal") for l in je_lines])
        gl_engine._post_entry(business_id, spec, coa)
    else:
        raise HTTPException(400, f"unknown proposal_type {ptype}")

    sb_clients.sb_patch_as_service(
        f"/chief_bookkeeping_proposals?id=eq.{proposal_id}&business_id=eq.{business_id}",
        {"status": "approved", "resolved_at": _now_iso()})
    # G v1.5 — approvals are learning signals too (confirm the default).
    capture_learning_signal(business_id, ptype, proposed, None, "approved")
    return {"ok": True, "executed": ptype}


def reject_proposal(business_id: str, proposal_id: str,
                    override: Optional[Dict[str, Any]] = None,
                    override_reason: Optional[str] = None) -> Dict[str, Any]:
    """Mark rejected; if the practitioner supplied a correction, capture a
    learning signal (Ruling 3) synchronously."""
    from fastapi import HTTPException
    p = _get_proposal(business_id, proposal_id)
    if not p:
        raise HTTPException(404, "proposal not found")
    if p.get("status") == "pending" and (override or override_reason):
        capture_learning_signal(
            business_id, p.get("proposal_type"), p.get("proposed") or {}, override, override_reason)
    sb_clients.sb_patch_as_service(
        f"/chief_bookkeeping_proposals?id=eq.{proposal_id}&business_id=eq.{business_id}",
        {"status": "rejected", "resolved_at": _now_iso()})
    return {"ok": True}


def send_to_inbox(business_id: str, proposal_id: str) -> Dict[str, Any]:
    """Route a proposal to the Inbox (existing agent_queue, 'proposal' type —
    no CHECK change) for context-switched approval later."""
    from fastapi import HTTPException
    p = _get_proposal(business_id, proposal_id)
    if not p:
        raise HTTPException(404, "proposal not found")
    label = {
        "propose_match": "Chief: confirm a reconciliation match",
        "propose_categorize": "Chief: confirm a transaction category",
        "propose_exclude": "Chief: confirm excluding a transaction",
    }.get(p.get("proposal_type"), "Chief bookkeeping proposal")
    try:
        sb_clients.sb_post_as_service("/agent_queue", {
            "business_id": business_id,
            "agent": "bookkeeping",
            "action_type": "proposal",   # existing valid agent_queue type
            "subject": label,
            "body": p.get("reasoning") or "",
            "status": "draft",
            "priority": "medium",
            "ai_reasoning": "Phase G bookkeeping proposal sent to Inbox",
            "data": {"chief_bookkeeping_proposal_id": proposal_id,
                     "proposal_type": p.get("proposal_type")},
        }, prefer=None)
    except Exception as e:
        logger.warning(f"[chief_bk] inbox insert failed: {e}")
    sb_clients.sb_patch_as_service(
        f"/chief_bookkeeping_proposals?id=eq.{proposal_id}&business_id=eq.{business_id}",
        {"status": "sent_to_inbox", "resolved_at": _now_iso()})
    return {"ok": True}
