"""turn_linkage.py — the writes that tie a Chief turn to what came of it.

Layer Two, step 1. Three small, sync, best-effort writes, all through the
service role and all gated on the columns existing
(APPLY-2026-10-11-layer-two-foundation.sql), so this ships before the
migration is applied and starts recording the moment it is:

  after_turn     the drafts a chat turn filed carry its turn id, and each
                 goes on the outcome ledger (surface "chat"), whose
                 six-hourly reconciler fills in approved / dismissed /
                 expired. A turn then joins to its outcome.
  keep_original  Chief's draft as first written survives the owner's edit.
                 Set once (the PATCH only matches a row whose original is
                 still empty), so a second edit never overwrites the first
                 original.
  mark_reviewed  who approved or dismissed a queue row.

None of these raise. A failed linkage write costs a join later, never a
reply or a send now.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import sb_clients
import schema_probe

logger = logging.getLogger("turn_linkage")

QUEUE_TURN_COLS = ("turn_id",)
QUEUE_ORIGINAL_COLS = ("original_subject", "original_body")
QUEUE_REVIEWER_COLS = ("reviewed_by",)


def _q(value: Any) -> str:
    # quote() keeps '+' as %2B (memory: PostgREST decodes '+' to a space).
    return quote(str(value), safe="")


# Verbs that act on a draft that already exists. Their results carry its
# queue id too, but the draft belongs to the turn that filed it.
_DRAFT_OPERATIONS = frozenset({
    "approve_draft", "dismiss_draft", "edit_draft", "save_draft", "rewrite_draft",
    "bulk_dismiss", "bulk_approve",
})


def drafted_queue_ids(taken: List[Dict[str, Any]], action_failed) -> List[str]:
    """Queue rows this turn's successful actions filed. Pure."""
    out: List[str] = []
    for t in taken or []:
        if not isinstance(t, dict) or action_failed(t):
            continue
        if str(t.get("type") or "") in _DRAFT_OPERATIONS:
            continue
        qid = str(t.get("queue_id") or "").strip()
        if qid and qid not in out:
            out.append(qid)
    return out


def after_turn(business_id: Optional[str], turn_id: Optional[str],
               taken: List[Dict[str, Any]], action_failed) -> int:
    """Stamp the turn id on the drafts the turn filed and record them as
    chat moves. Returns the number of drafts linked."""
    if not business_id or not turn_id:
        return 0
    qids = drafted_queue_ids(taken, action_failed)
    if not qids:
        return 0
    try:
        if schema_probe.has_columns("agent_queue", QUEUE_TURN_COLS):
            ids = ",".join(_q(q) for q in qids)
            sb_clients.sb_patch_as_service(
                f"/agent_queue?id=in.({ids})&business_id=eq.{_q(business_id)}&turn_id=is.null",
                {"turn_id": str(turn_id)})
    except Exception as e:
        logger.warning(f"[turn_linkage] queue turn stamp failed: {e}")
    try:
        import outcome_ledger
        moves = [t for t in taken if isinstance(t, dict) and str(t.get("queue_id") or "") in qids]
        outcome_ledger.record_moves(str(business_id), outcome_ledger.CHAT_SURFACE, moves,
                                    turn_id=str(turn_id))
    except Exception as e:
        logger.warning(f"[turn_linkage] chat moves not recorded: {e}")
    return len(qids)


def keep_original(queue_id: Optional[str], item: Dict[str, Any]) -> bool:
    """Save the row's subject/body as Chief wrote them, once."""
    if not queue_id or not isinstance(item, dict):
        return False
    try:
        if not schema_probe.has_columns("agent_queue", QUEUE_ORIGINAL_COLS):
            return False
        res = sb_clients.sb_patch_as_service(
            f"/agent_queue?id=eq.{_q(queue_id)}&original_body=is.null",
            {"original_subject": item.get("subject"), "original_body": item.get("body") or ""})
        return res is not None
    except Exception as e:
        logger.warning(f"[turn_linkage] original not kept for {queue_id}: {e}")
        return False


def mark_reviewed(queue_id: Optional[str], user_id: Optional[str]) -> bool:
    """Record the person who approved or dismissed a queue row."""
    if not queue_id or not user_id:
        return False
    try:
        if not schema_probe.has_columns("agent_queue", QUEUE_REVIEWER_COLS):
            return False
        res = sb_clients.sb_patch_as_service(
            f"/agent_queue?id=eq.{_q(queue_id)}", {"reviewed_by": str(user_id)})
        return res is not None
    except Exception as e:
        logger.warning(f"[turn_linkage] reviewer not recorded for {queue_id}: {e}")
        return False
