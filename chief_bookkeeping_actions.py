"""
chief_bookkeeping_actions.py — P0.2, the bookkeeping verbs.

THE GAP THIS CLOSES: chief_bookkeeping.py is a substantial, working proposal
engine — it reconciles, categorizes, spots period-close candidates and GL
gaps. But it was reachable ONLY through its own router (/bookkeeping/analyze-*,
/proposals/{id}/approve), which means the practitioner had to go find a screen.
Chief could SEE the books (gather_and_format already injects a bookkeeping
block into the system prompt) and could not TOUCH them. A parallel surface,
not a callable tool.

These verbs make the existing engine conversational. They add no bookkeeping
logic of their own — every one is a thin, well-shaped wrapper over a function
in chief_bookkeeping. That is deliberate: the accounting rules have exactly one
home, and it is not here.

TRUST-LAYER DISCIPLINE (feedback_chief_trust_layer_discipline):
  • What changes? Only proposal STATUS, and only via approve/reject_proposal,
    which already own execution + the learning signal. review_books writes
    nothing but proposals (the same rows the router's analyze-* endpoints
    write).
  • Can the practitioner see it first? Yes — list_bookkeeping_proposals, and
    approve_bookkeeping_proposal names the proposal in its result.
  • Is it reversible? Approving executes a categorization/match, which the
    existing bookkeeping UI can re-edit. Rejecting is inert.
  • Is there an audit trail? chief_bookkeeping_proposals carries status +
    resolved_at, and a reject-with-reason captures a chief_learning_signals
    row (Ruling 3).

BULK APPROVAL IS DELIBERATELY NOT OFFERED. "Approve everything" over financial
records is exactly the action a practitioner cannot un-see, and Chief's
confidence is not calibrated well enough to earn it. Proposals are approved one
at a time, by id, each named in the result.

HTTPException containment: approve/reject_proposal raise FastAPI
HTTPExceptions on a bad id. Inside a Chief handler that would 500 the whole
chat turn instead of failing one action card, so every call is wrapped.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import chief_bookkeeping as cb

logger = logging.getLogger("chief_bookkeeping_actions")

# How many proposals to name in a single conversational reply before
# summarizing the remainder. A wall of twenty is not a briefing.
_NAME_LIMIT = 5


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    logger.info(f"Action {action_type} failed: {msg}")
    # "failed": True is the machine-readable seam _action_failed reads —
    # without it a failure here is audited and narrated as a success.
    return {
        "type": action_type,
        "result": msg,
        "label": action_type,
        "nav": None,
        "failed": True,
    }


def _nav_books() -> Dict[str, Any]:
    return {"tab": "operate", "sub": "bookkeeping"}


def _describe(p: Dict[str, Any]) -> str:
    """One human line for a proposal. The `proposed` payload shape differs per
    type, so read defensively — a missing key must degrade to something
    readable, never raise."""
    ptype = (p.get("proposal_type") or "").replace("propose_", "")
    proposed = p.get("proposed") or {}
    if ptype == "categorize":
        cat = proposed.get("business_category") or "a category"
        sub = proposed.get("business_subcategory")
        return f"categorize as {cat}" + (f" / {sub}" if sub else "")
    if ptype == "match":
        return "match to " + str(proposed.get("matched_to") or "an existing record")
    if ptype == "exclude":
        return "exclude from the books"
    return ptype or "a change"


# ─── review_books ─────────────────────────────────────────────────────

def _review_books_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    business_id = biz["id"]

    counts = cb.bookkeeping_counts(business_id)
    if not counts.get("linked"):
        return {
            "type": "review_books",
            "result": "no bank account is linked yet, so there's nothing to reconcile",
            "label": "Bookkeeping",
            "nav": _nav_books(),
        }

    # Which analyzers to run. Default is everything; a practitioner who says
    # "check my uncategorized transactions" gets just that one.
    scope = (action.get("scope") or "all").lower().strip()
    made: List[Dict[str, Any]] = []
    ran: List[str] = []
    for name, fn in (
        ("unmatched", cb.analyze_unmatched),
        ("uncategorized", cb.analyze_uncategorized),
        ("period_close", cb.analyze_period_close),
        ("gl", cb.analyze_gl),
    ):
        if scope not in ("all", name):
            continue
        try:
            made.extend(fn(business_id) or [])
            ran.append(name)
        except Exception as e:
            # One analyzer failing must not lose the others' findings.
            logger.warning(f"[books] analyzer {name} failed soft: {e}")

    if not ran:
        return _fail("review_books",
                     f"I don't have a check called '{scope}'. "
                     "Try unmatched, uncategorized, period_close, or gl.")

    pending = cb.list_proposals(business_id, status="pending")
    bits = []
    if counts.get("unmatched"):
        bits.append(f"{counts['unmatched']} unmatched (${counts.get('unmatched_total', 0):,.2f})")
    if counts.get("uncategorized"):
        bits.append(f"{counts['uncategorized']} uncategorized")
    state = ", ".join(bits) if bits else "nothing outstanding"

    return {
        "type": "review_books",
        "result": f"{state}; {len(pending)} proposal(s) waiting"
                  + (f", {len(made)} new" if made else ""),
        "label": "Bookkeeping review",
        "counts": counts,
        "pending": len(pending),
        "new_proposals": len(made),
        "nav": _nav_books(),
    }


async def handle_review_books(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_review_books_sync, biz, action)


# ─── list_bookkeeping_proposals ───────────────────────────────────────

def _list_proposals_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    business_id = biz["id"]
    status = (action.get("status") or "pending").lower().strip()

    rows = cb.list_proposals(business_id, status=status)
    if not rows:
        return {
            "type": "list_bookkeeping_proposals",
            "result": f"no {status} proposals",
            "label": "Bookkeeping",
            "proposals": [],
            "nav": _nav_books(),
        }

    named = [{"id": r.get("id"), "summary": _describe(r),
              "confidence": r.get("confidence"), "reasoning": r.get("reasoning")}
             for r in rows[:_NAME_LIMIT]]
    more = len(rows) - len(named)
    return {
        "type": "list_bookkeeping_proposals",
        "result": f"{len(rows)} {status}" + (f" (showing {len(named)})" if more > 0 else ""),
        "label": "Bookkeeping proposals",
        "proposals": named,
        "total": len(rows),
        "nav": _nav_books(),
    }


async def handle_list_bookkeeping_proposals(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_list_proposals_sync, biz, action)


# ─── approve / reject ─────────────────────────────────────────────────

def _resolve_proposal_id(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """An explicit id wins. Otherwise, resolve to THE single pending proposal —
    but only if there is exactly one. With several open, "approve it" is
    ambiguous over financial records, so we ask rather than pick."""
    pid = (action.get("proposal_id") or action.get("id") or "").strip()
    if pid:
        return {"id": pid}
    pending = cb.list_proposals(business_id, status="pending")
    if not pending:
        return {"error": "There are no proposals waiting."}
    if len(pending) > 1:
        listing = "; ".join(_describe(p) for p in pending[:_NAME_LIMIT])
        return {"error": f"There are {len(pending)} proposals waiting — "
                         f"which one? {listing}"}
    return {"id": pending[0].get("id"), "proposal": pending[0]}


def _approve_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    business_id = biz["id"]

    res = _resolve_proposal_id(business_id, action)
    if res.get("error"):
        return _fail("approve_bookkeeping_proposal", res["error"])
    pid = res["id"]

    proposal = res.get("proposal") or cb._get_proposal(business_id, pid)
    if not proposal:
        return _fail("approve_bookkeeping_proposal", "I couldn't find that proposal.")
    summary = _describe(proposal)

    try:
        out = cb.approve_proposal(business_id, pid,
                                  approved_by=str(action.get("approved_by") or "chief"))
    except Exception as e:
        # Includes the HTTPException(404) path — contained so one bad id fails
        # this action card, not the whole chat turn.
        logger.warning(f"[books] approve failed: {e}")
        return _fail("approve_bookkeeping_proposal",
                     "I couldn't apply that just now — try again in a moment.")

    if out.get("already"):
        return {
            "type": "approve_bookkeeping_proposal",
            "result": f"already {out['already']}",
            "label": summary,
            "proposal_id": pid,
            "nav": _nav_books(),
        }
    return {
        "type": "approve_bookkeeping_proposal",
        "result": f"applied — {summary}",
        "label": summary,
        "proposal_id": pid,
        "nav": _nav_books(),
    }


async def handle_approve_bookkeeping_proposal(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_approve_sync, biz, action)


def _reject_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    business_id = biz["id"]

    res = _resolve_proposal_id(business_id, action)
    if res.get("error"):
        return _fail("reject_bookkeeping_proposal", res["error"])
    pid = res["id"]

    proposal = res.get("proposal") or cb._get_proposal(business_id, pid)
    summary = _describe(proposal) if proposal else "proposal"

    # A correction is worth more than a rejection: when the practitioner says
    # what it SHOULD have been, that becomes a chief_learning_signals row and
    # the next proposal is better. This is the whole point of Ruling 3.
    override = action.get("override") if isinstance(action.get("override"), dict) else None
    reason = action.get("reason") or action.get("override_reason")

    try:
        cb.reject_proposal(business_id, pid, override=override, override_reason=reason)
    except Exception as e:
        logger.warning(f"[books] reject failed: {e}")
        return _fail("reject_bookkeeping_proposal",
                     "I couldn't reject that just now — try again in a moment.")

    return {
        "type": "reject_bookkeeping_proposal",
        "result": "rejected" + (" — noted for next time" if (override or reason) else ""),
        "label": summary,
        "proposal_id": pid,
        "nav": _nav_books(),
    }


async def handle_reject_bookkeeping_proposal(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_reject_sync, biz, action)
