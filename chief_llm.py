"""
chief_llm.py — Phase G v1.5 — LLM-in-loop Chief bookkeeping intelligence.

Cost + trust discipline:
  - Deterministic rules (chief_bookkeeping) run FIRST and stay authoritative
    for clean matches. Claude is invoked ONLY for cases the deterministic
    analyzers deflected (no Plaid bucket, ambiguous merchant), plus the
    practitioner-initiated "Ask Chief" surface.
  - One batched call per analyze-hard run (≤15 transactions). Haiku by
    default (CHIEF_LLM_MODEL overrides). max_tokens ≤ 700.
  - Prompt budget kept: archetype voice fragment (~4 lines) + the I.5
    five-line GL block + a ≤5-line learning digest + the transaction rows.
  - Kill switch: CHIEF_LLM=off. Missing ANTHROPIC_API_KEY → graceful
    {llm: "disabled"} (never a 500).
  - LLM output NEVER acts directly — it lands as pending proposals through
    the same trust-layer pipeline as the deterministic analyzers (narration,
    approve-to-act, second pass, deflection). Confidence is capped at 0.75
    so AI proposals always read as suggestions, not facts.
  - Every call logs to api_usage with the business_id — the same table
    Phase E v1.1 message metering reads.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

import sb_clients
import chief_bookkeeping
import plaid_categorization

logger = logging.getLogger("chief_llm")

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

_HARD_BATCH_LIMIT = 15
_LLM_CONFIDENCE_CAP = 0.75


def llm_capped(business_id: str) -> bool:
    """Phase E v1.1 — Starter's monthly Chief cap (dormant until
    BILLING_ENFORCE=on)."""
    try:
        import billing_limits
        return not billing_limits.chief_can_send(business_id)
    except Exception:
        return False  # metering failure must never block Chief


def llm_enabled() -> bool:
    if (os.environ.get("CHIEF_LLM") or "on").lower() == "off":
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _model() -> str:
    return (os.environ.get("CHIEF_LLM_MODEL") or "").strip() or DEFAULT_MODEL


# ─── Per-archetype voice (G v1.5) ────────────────────────────────────

def voice_fragment(business_type: Optional[str]) -> str:
    """A compact system-prompt fragment from the vertical voice profile —
    lawyer sounds precise, coach sounds warm, nonprofit stewardship-minded."""
    voice = None
    try:
        import vertical_intelligence
        bt_key = (business_type or "").lower().strip()
        if bt_key in (vertical_intelligence.list_known_verticals() or []):
            prof = vertical_intelligence.get_profile(business_type)
            voice = (prof or {}).get("voice")
    except Exception:
        voice = None
    if not voice:
        bt = (business_type or "").lower()
        if "law" in bt:
            voice = {"register": "precise, professional", "formality": "formal",
                     "hallmarks": ["uses 'Client' and 'Matter'",
                                   "treats trust funds as sacrosanct"]}
        elif "nonprofit" in bt or "non_profit" in bt or "non-profit" in bt:
            voice = {"register": "stewardship-minded, donor-aware", "formality": "balanced",
                     "hallmarks": ["uses 'Donor' and 'Gift'",
                                   "asks whether gifts are restricted"]}
        else:
            voice = {"register": "professional but warm", "formality": "balanced",
                     "hallmarks": ["clear", "no jargon"]}
    hallmarks = "; ".join((voice.get("hallmarks") or [])[:3])
    return (f"Voice: {voice.get('register', 'professional but warm')}. "
            f"Formality: {voice.get('formality', 'balanced')}. {hallmarks}.")


# ─── Learning signals (expanded in G v1.5) ───────────────────────────

def learning_digest(business_id: str, *, max_lines: int = 5) -> List[str]:
    """≤5 compact lines summarizing recent approve/reject behavior, fed into
    the LLM prompt so Chief adapts to this practitioner."""
    signals = chief_bookkeeping.recent_learning_signals(business_id)
    if not signals:
        return []
    out: List[str] = ["  PRACTITIONER PREFERENCES (recent approvals/corrections):"]
    for s in signals:
        if len(out) >= max_lines + 1:
            break
        ptype = (s.get("proposal_type") or "").replace("propose_", "")
        orig = s.get("original_proposal") or {}
        over = s.get("practitioner_override") or {}
        reason = (s.get("override_reason") or "").strip()
        if reason == "approved":
            continue  # approvals confirm defaults; corrections teach more
        frm = orig.get("business_category")
        to = over.get("business_category")
        if frm and to and frm != to:
            out.append(f"    corrected a {ptype}: {frm} → {to}"
                       + (f" ({reason[:60]})" if reason and reason != "approved" else ""))
        elif reason:
            out.append(f"    rejected a {ptype}: {reason[:70]}")
    return out if len(out) > 1 else []


def suppressed_categorizations(business_id: str) -> set:
    """Buckets the practitioner has rejected ≥2× in 30 days for
    propose_categorize — the deterministic analyzer stops proposing them.
    (G v1.5: learning signals now feed BACK into proposal generation.)"""
    signals = chief_bookkeeping.recent_learning_signals(business_id)
    counts: Dict[str, int] = {}
    for s in signals:
        if s.get("proposal_type") != "propose_categorize":
            continue
        if (s.get("override_reason") or "") == "approved":
            continue
        cat = (s.get("original_proposal") or {}).get("business_category")
        if cat:
            counts[cat] = counts.get(cat, 0) + 1
    return {c for c, n in counts.items() if n >= 2}


# ─── Claude call (logged, budget-capped) ─────────────────────────────

async def _call_claude(business_id: str, system: str, user_content: str,
                       *, max_tokens: int, endpoint: str) -> Optional[str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    model = _model()
    payload = {
        "model": model, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": user_content}],
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(ANTHROPIC_API_URL, json=payload, headers={
                "x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json"})
    except Exception as e:
        logger.warning(f"[chief_llm] call failed: {e}")
        return None
    usage = {}
    text = None
    if resp.status_code == 200:
        body = resp.json()
        usage = body.get("usage") or {}
        text = "".join(b.get("text", "") for b in body.get("content") or []
                       if b.get("type") == "text")
    else:
        logger.warning(f"[chief_llm] anthropic {resp.status_code}: {resp.text[:200]}")
    try:
        from api_usage_logger import log_api_usage
        await log_api_usage(
            endpoint=endpoint, model=model,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            business_id=business_id, task_type="chief_bookkeeping",
            ok=resp.status_code == 200,
            error=None if resp.status_code == 200 else f"http_{resp.status_code}")
    except Exception as e:
        logger.warning(f"[chief_llm] usage log failed: {e}")
    return text


def _parse_json(text: Optional[str]):
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    start = min((i for i in (t.find("{"), t.find("[")) if i >= 0), default=-1)
    if start < 0:
        return None
    try:
        return json.loads(t[start:])
    except Exception:
        # Last resort: trim to the final closing brace/bracket.
        for endch in ("}", "]"):
            end = t.rfind(endch)
            if end > start:
                try:
                    return json.loads(t[start:end + 1])
                except Exception:
                    continue
    return None


def _system_prompt(business_id: str, business_type: Optional[str]) -> str:
    buckets = ", ".join(plaid_categorization.ALL_BUCKETS)
    lines = [
        "You are Chief, the bookkeeping intelligence inside Solutionist — a",
        "practitioner's operations + accounting system. You help categorize bank",
        "transactions and answer questions about the books.",
        voice_fragment(business_type),
        f"Valid expense buckets: {buckets}. Never invent other buckets.",
        "You PROPOSE — you never act. Every suggestion becomes a pending proposal",
        "the practitioner approves or rejects. If you are not reasonably sure,",
        "say so and propose nothing (deflection is correct behavior).",
        "Respond with STRICT JSON only — no prose outside the JSON.",
    ]
    lines += chief_bookkeeping._gl_context_lines(business_id)
    lines += learning_digest(business_id)
    return "\n".join(lines)


def _tx_line(t: Dict[str, Any]) -> str:
    amt = float(t.get("amount") or 0)
    direction = "OUT" if amt > 0 else "IN"
    return (f"- id={t.get('transaction_id')} {t.get('date')} {direction} "
            f"${abs(amt):,.2f} merchant={t.get('merchant_name') or t.get('name') or '?'} "
            f"plaid={t.get('plaid_category_primary') or '—'}"
            f"/{t.get('plaid_category_detail') or '—'} "
            f"current_bucket={t.get('business_category') or 'none'}")


# ─── Ask Chief about ONE transaction (Transactions drawer) ───────────

async def ask_transaction(business_id: str, business_type: Optional[str],
                          transaction_id: str,
                          question: Optional[str]) -> Dict[str, Any]:
    if not llm_enabled():
        return {"ok": True, "llm": "disabled",
                "answer": "Chief's AI assist isn't enabled on this server yet."}
    if llm_capped(business_id):
        return {"ok": True, "llm": "capped",
                "answer": "You've used this month's included Chief messages on "
                          "your plan. Upgrade for unlimited Chief — or I'll see "
                          "you on the 1st."}
    rows = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{business_id}"
        f"&transaction_id=eq.{transaction_id}"
        f"&select=transaction_id,amount,date,name,merchant_name,business_category,"
        f"business_subcategory,plaid_category_primary,plaid_category_detail,"
        f"reconciliation_status,excluded_from_books,pending&limit=1") or []
    if not rows:
        return {"ok": False, "error": "transaction not found"}
    tx = rows[0]
    merchant = tx.get("merchant_name") or tx.get("name") or ""
    similar = []
    if merchant:
        similar = sb_clients.sb_get_as_service(
            f"/plaid_transactions?business_id=eq.{business_id}"
            f"&transaction_id=neq.{transaction_id}"
            f"&or=(merchant_name.eq.{merchant},name.eq.{merchant})"
            f"&order=date.desc&limit=5"
            f"&select=transaction_id,amount,date,name,merchant_name,business_category,"
            f"plaid_category_primary,plaid_category_detail") or []
    user = "\n".join(
        ["TRANSACTION:", _tx_line(tx)]
        + (["SAME-MERCHANT HISTORY:"] + [_tx_line(t) for t in similar] if similar else [])
        + ["QUESTION: " + (question or "What is this transaction, and how should it be categorized?"),
           'Reply as JSON: {"answer": "<2-4 sentences in your voice>",',
           ' "proposal": null OR {"business_category": "<bucket>",',
           '  "business_subcategory": "<short label or null>",',
           '  "confidence": 0.0-1.0, "reasoning": "<one sentence>"}}'])
    text = await _call_claude(business_id, _system_prompt(business_id, business_type),
                              user, max_tokens=500, endpoint="/chief/ask-transaction")
    parsed = _parse_json(text)
    if not isinstance(parsed, dict):
        return {"ok": True, "llm": "error",
                "answer": "Chief couldn't analyze this one — try again in a moment."}
    out: Dict[str, Any] = {"ok": True, "llm": "ok",
                           "answer": str(parsed.get("answer") or "")[:1200]}
    # The drawer's own Save button IS the approval step here (practitioner-
    # initiated, reviewing in place) — return an inline suggestion rather
    # than inserting a parallel pending proposal that would duplicate state.
    # Background analyze_hard is the path that feeds the proposals Inbox.
    prop = parsed.get("proposal")
    if isinstance(prop, dict) and prop.get("business_category") in plaid_categorization.ALL_BUCKETS \
            and prop.get("business_category") != tx.get("business_category"):
        out["suggestion"] = {
            "business_category": prop["business_category"],
            "business_subcategory": (prop.get("business_subcategory") or None),
            "confidence": round(min(float(prop.get("confidence") or 0.5),
                                    _LLM_CONFIDENCE_CAP), 2),
            "reasoning": str(prop.get("reasoning") or "")[:300],
        }
    return out


# ─── Hard-case batch analysis (deterministic deflections) ────────────

def _hard_candidates(business_id: str, *, limit: int = _HARD_BATCH_LIMIT) -> List[Dict[str, Any]]:
    """Uncategorized OUTFLOWS the deterministic analyzer deflected on —
    Plaid's own category maps to nothing better than 'other'."""
    included = chief_bookkeeping._included_account_ids(business_id)
    if not included:
        return []
    acct = "account_id=in.(" + ",".join(included) + ")"
    rows = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{business_id}&{acct}"
        f"&excluded_from_books=eq.false&pending=eq.false&amount=gt.0"
        f"&or=(business_category.is.null,business_category.eq.other)"
        f"&order=date.desc&limit=60"
        f"&select=transaction_id,amount,date,name,merchant_name,business_category,"
        f"plaid_category_primary,plaid_category_detail") or []
    out = []
    for t in rows:
        if chief_bookkeeping._existing_pending_for_tx(business_id, t["transaction_id"]):
            continue
        mapped = plaid_categorization.map_plaid_to_bucket(
            t.get("plaid_category_primary"), t.get("plaid_category_detail"))
        if mapped and mapped != "other" and mapped != t.get("business_category"):
            continue  # the deterministic analyzer will handle this one
        out.append(t)
        if len(out) >= limit:
            break
    return out


async def analyze_hard(business_id: str, business_type: Optional[str]) -> Dict[str, Any]:
    """One batched Claude call over the deterministic deflections → pending
    propose_categorize proposals (same trust pipeline, confidence ≤ 0.75)."""
    if not llm_enabled():
        return {"ok": True, "llm": "disabled", "created": []}
    if llm_capped(business_id):
        return {"ok": True, "llm": "capped", "created": []}
    candidates = _hard_candidates(business_id)
    if not candidates:
        return {"ok": True, "llm": "ok", "created": [], "note": "no hard cases"}
    suppressed = suppressed_categorizations(business_id)
    user = "\n".join(
        ["These bank transactions had no clean rule-based category. Suggest a",
         "bucket ONLY where the merchant/context makes it reasonably clear;",
         "omit a transaction entirely when unsure.", "TRANSACTIONS:"]
        + [_tx_line(t) for t in candidates]
        + ['Reply as JSON: [{"transaction_id": "...", "business_category": "<bucket>",',
           '  "business_subcategory": "<short label or null>",',
           '  "confidence": 0.0-1.0, "reasoning": "<one sentence>"}]'])
    text = await _call_claude(business_id, _system_prompt(business_id, business_type),
                              user, max_tokens=700, endpoint="/chief/analyze-hard")
    parsed = _parse_json(text)
    created: List[Dict[str, Any]] = []
    valid_ids = {t["transaction_id"] for t in candidates}
    if isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue
            tid = item.get("transaction_id")
            cat = item.get("business_category")
            if tid not in valid_ids or cat not in plaid_categorization.ALL_BUCKETS:
                continue
            if cat in suppressed:
                continue  # practitioner has repeatedly rejected this bucket
            conf = min(float(item.get("confidence") or 0.5), _LLM_CONFIDENCE_CAP)
            row = chief_bookkeeping._insert_proposal(
                business_id, "propose_categorize",
                plaid_transaction_id=tid,
                proposed={"plaid_transaction_id": tid, "business_category": cat,
                          "business_subcategory": (item.get("business_subcategory") or None)},
                confidence=round(conf, 2),
                reasoning="Chief (AI): " + str(item.get("reasoning") or "")[:300])
            if row:
                created.append(row)
    return {"ok": True, "llm": "ok" if parsed is not None else "error",
            "candidates": len(candidates), "created": created}
