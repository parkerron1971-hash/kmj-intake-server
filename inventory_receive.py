"""
inventory_receive.py — SCAN THE SHELF, rung three: RECEIVING
(2026-08-20).

WHAT THIS FINALLY CLOSES
  The reorder brain already notices stock falling, drafts the purchase
  order, and stamps reorder_pending_at when it goes out. Then the box
  arrives and the loop just... stopped. Somebody had to remember what
  was ordered, open the Stock tab, and type a number per product. So
  the stamp stayed on, the alert stayed suppressed, and the system's
  own promise ("I'll tell you when it lands") went unkept.

  Receiving is the last mile: unpack the box, scan each item, one
  submit. Every line goes UP, every outstanding order it satisfies
  closes, and the report says how the delivery compared to what was
  actually ordered — short, exact, or over.

THE TALLY, AND WHY IT IS + AND NOT =
  A count session SETS a number: the shelf is the truth and the book is
  wrong. Receiving ADDS: the shelf was right and six more just arrived.
  Those are different verbs and conflating them is how a receive wipes
  out the stock that was already there. Hence a separate endpoint with
  a separate reason string, so the movement history can tell a delivery
  from a stocktake forever after.

  Six bottles is six scans, and six scans is +6. The client tallies
  locally (free, instant, and it survives a dropped signal in a stock
  room) and submits ONE batch. Nothing is written until the human taps
  finish, so a mis-scan is a line you delete, not a movement you have
  to reverse.

WHAT IT REFUSES TO DO
  • Guess. An unrecognised code is never quietly added to the nearest
    line — that is how a scanner becomes a duplicate-product factory.
    It comes back unmatched and the practitioner decides.
  • Set. There is no way to lower stock through this door; a delivery
    that arrives short is a smaller +, not a −.

Endpoints:
  GET  /store/inventory/{business_id}/expected  — member+, what's on order
  POST /store/inventory/{business_id}/receive   — manager+, the tally
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("inventory_receive")

router = APIRouter(tags=["store"])

# A delivery is a box, not a warehouse transfer. Generous for a real
# small business, bounded enough that a runaway client cannot ask for
# ten thousand writes.
_MAX_LINES = 300
# One line of a purchase order for a small business. Above this it is
# a typo or a stuck scanner, and silently accepting 9,999 units of
# pomade is a worse outcome than a clear refusal.
_MAX_QTY = 9999

_SELLABLE = {"product", "course", "package"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReceiveLine(BaseModel):
    offering_id: str
    qty: int = Field(..., ge=1, le=_MAX_QTY)


class ReceiveBody(BaseModel):
    lines: List[ReceiveLine]
    note: Optional[str] = Field(default=None, max_length=200)


# ─── Pure helper (unit-tested; no network) ───────────────────────────


def reconcile_line(received: int, ordered: Optional[int]) -> Dict[str, Any]:
    """How this delivery compares to what was actually ordered.

    `ordered` is None when nothing was on order for this product — a
    walk-in restock, a sample, a supplier throwing in an extra. That is
    NOT a discrepancy and must never be reported as one; inventing a
    variance against an order that does not exist is the same class of
    lie as counting an untracked product as shrink.
    """
    if ordered is None or ordered <= 0:
        return {"ordered": None, "status": "unordered", "difference": 0}
    diff = received - ordered
    status = "exact" if diff == 0 else ("short" if diff < 0 else "over")
    return {"ordered": ordered, "status": status, "difference": diff}


def delivery_summary(lines: List[Dict[str, Any]], closed: int) -> str:
    """The sentence the report leads with. States the shortfall plainly
    — a delivery arriving short is the single most useful thing this
    screen can tell somebody, and softening it costs them money."""
    units = sum(int(l.get("received") or 0) for l in lines)
    if not lines:
        return "Nothing was received."
    head = (f"{units} unit{'' if units == 1 else 's'} received across "
            f"{len(lines)} product{'' if len(lines) == 1 else 's'}")
    short = [l for l in lines if l.get("status") == "short"]
    over = [l for l in lines if l.get("status") == "over"]
    bits = [head]
    if closed:
        bits.append(f"{closed} purchase order{'' if closed == 1 else 's'} closed")
    if short:
        missing = sum(-int(l["difference"]) for l in short)
        bits.append(f"{missing} short of what you ordered "
                    f"({', '.join(l['name'] for l in short[:3])})")
    if over:
        bits.append(f"{len(over)} came in over the order")
    return " — ".join(bits) + "."


# ─── What's on order ─────────────────────────────────────────────────


@router.get("/store/inventory/{business_id}/expected")
def expected_arrivals(business_id: str,
                      user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The outstanding purchase orders: what Chief sent out and has not
    seen arrive. Member+ because it is a read of the same stock picture
    the Stock tab already shows to members.
    """
    from business_users_router import require_role
    require_role(business_id, str(user.id), "member")

    rows = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
        "&reorder_pending_at=not.is.null"
        "&select=id,name,sku,barcode,category,inventory_qty,reorder_qty,"
        "reorder_at,supplier_name,reorder_pending_at"
        "&order=reorder_pending_at.asc&limit=200") or []
    expected = [{
        "offering_id": o["id"],
        "name": o.get("name"),
        "sku": o.get("sku"),
        "barcode": o.get("barcode"),
        "ordered_qty": o.get("reorder_qty"),
        "supplier_name": o.get("supplier_name"),
        "ordered_at": o.get("reorder_pending_at"),
        "on_hand": o.get("inventory_qty"),
    } for o in rows if (o.get("category") or "") in _SELLABLE]
    return {"ok": True, "expected": expected}


# ─── The tally ───────────────────────────────────────────────────────


@router.post("/store/inventory/{business_id}/receive")
def receive_stock(business_id: str, body: ReceiveBody,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Book in a delivery: every line goes UP, outstanding orders close,
    and the report says how it compared to what was ordered.

    Manager+, the same ladder as every other stock write — receiving is
    a pile of adjustments and must not be a cheaper way to make one.
    """
    from business_users_router import require_role
    from store_router import _emit_stock_event
    require_role(business_id, str(user.id), "manager")

    if not body.lines:
        raise HTTPException(400, "a delivery needs at least one product")
    if len(body.lines) > _MAX_LINES:
        raise HTTPException(413, f"a delivery tops out at {_MAX_LINES} products")

    rows = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
        "&select=id,name,category,inventory_qty,reorder_qty,reorder_pending_at"
        "&limit=500") or []
    offerings = {str(o["id"]): o for o in rows
                 if (o.get("category") or "") in _SELLABLE}

    # Same product scanned in two passes is ONE line of a delivery.
    # Summed, not overwritten — the count session's last-wins rule is
    # right for a stocktake and catastrophic for a tally.
    merged: Dict[str, int] = {}
    for ln in body.lines:
        oid = str(ln.offering_id)
        if oid not in offerings:
            raise HTTPException(
                404, "one of those products isn't in this business's stock")
        merged[oid] = min(_MAX_QTY, merged.get(oid, 0) + int(ln.qty))

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    reason = f"received {stamp}"
    if body.note:
        reason = f"{reason} — {body.note.strip()[:120]}"
    actor = (getattr(user, "email", None) or str(user.id))

    result_lines: List[Dict[str, Any]] = []
    closed = 0
    for oid, qty in merged.items():
        off = offerings[oid]
        raw = off.get("inventory_qty")
        # An untracked product being received starts tracking at what
        # just arrived. There is nothing to preserve and nothing to
        # invent — the box is the only fact we have.
        old_qty = int(raw) if raw is not None else 0
        started_tracking = raw is None
        new_qty = min(_MAX_QTY * 10, old_qty + qty)

        sb_clients.sb_patch_as_service(
            f"/offerings?id=eq.{oid}&business_id=eq.{business_id}",
            {"inventory_qty": new_qty})
        _emit_stock_event(business_id, oid, off.get("name") or "",
                          delta=qty, new_qty=new_qty, reason=reason, actor=actor)

        # Reconcile against the order BEFORE clearing the stamp — once
        # reorder_pending_at is gone there is nothing left to compare to.
        was_on_order = bool(off.get("reorder_pending_at"))
        ordered = off.get("reorder_qty") if was_on_order else None
        rec = reconcile_line(qty, ordered)

        try:
            from reorder_engine import clear_reorder_pending_if_restocked
            if clear_reorder_pending_if_restocked(business_id, oid, new_qty):
                closed += 1
                rec["order_closed"] = True
        except Exception as e:
            logger.warning(f"[receive] pending-clear failed (non-fatal): {e}")

        result_lines.append({
            "offering_id": oid, "name": off.get("name") or "",
            "received": qty, "was": old_qty, "now": new_qty,
            "started_tracking": started_tracking,
            "order_closed": bool(rec.get("order_closed")),
            **{k: rec[k] for k in ("ordered", "status", "difference")},
        })

    try:
        import event_spine
        event_spine.emit("stock_received", business_id, {
            "lines": result_lines,
            "units": sum(l["received"] for l in result_lines),
            "orders_closed": closed,
            "note": (body.note or "")[:200],
            "actor": actor[:120],
            "received_at": _now_iso(),
        }, source="store")
    except Exception as e:
        logger.warning(f"[receive] delivery event emit failed (non-fatal): {e}")

    logger.info(f"[receive] biz={business_id[:8]} lines={len(result_lines)} "
                f"units={sum(l['received'] for l in result_lines)} closed={closed}")

    return {"ok": True, "lines": result_lines, "orders_closed": closed,
            "summary": delivery_summary(result_lines, closed), "reason": reason}
