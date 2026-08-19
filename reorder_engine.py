"""reorder_engine.py — THE REORDER BRAIN (2026-08-18).

THE GAP THIS CLOSES
  Stock tracking existed (offerings.inventory_qty, the Stock UI, the
  crossing alert in store_router) but nothing WATCHED it, and when it
  ran low the practitioner still had to remember who supplies the thing
  and write the email themselves. This module is rung one of the ladder:
  Chief notices, Chief drafts the purchase order, the practitioner's
  one word sends it. Chief never spends money unattended — the send is
  a class-C verb and the practitioner's "send it" IS the approval.

THE PIECES
  • offerings.reorder_at / reorder_qty / supplier_name / supplier_email
    — the per-offering reorder plan (APPLY-2026_08_18_reorder.sql).
  • low_stock_reorder_sweep() — hourly worker job. ONE alert per
    business (the lead-sweep doctrine: thirty low products need one
    notification that says thirty, not thirty notifications). The
    alert's action_payload is a draft_purchase_order, so the existing
    /agents/notifications/{id}/act rail gives one-tap drafting.
  • compose_purchase_order() — the PO email, one honest plain-text
    format used by both the draft preview and the real send.
  • reorder_pending_at — the duplicate-order guard. A low-stock
    condition STANDS until the restock arrives; without the stamp the
    sweep would re-raise (and a chat "order more" could double-send)
    every pass. Stamped by send_purchase_order, cleared by
    clear_reorder_pending_if_restocked() from every stock-raising path.

Verbs live in chief_inventory_actions.py; this module owns the sweep,
the composition, and the guard so the logic exists exactly once.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

import sb_clients

logger = logging.getLogger("reorder_engine")

# Re-raise cadence for an IGNORED reorder alert. The standing condition
# persists until either the PO goes out (reorder_pending_at silences the
# sweep) or stock is corrected — re-raising hourly is how a notification
# surface gets muted, so an unacted alert repeats every three days.
REORDER_DEDUP_HOURS = 72

REORDER_FIELDS = ("reorder_at,reorder_qty,supplier_name,supplier_email,"
                  "reorder_pending_at")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tripped(offerings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The offerings whose reorder point is tripped and not already on
    order. Pure — PostgREST cannot compare column to column, so the
    qty<=reorder_at comparison happens here."""
    out: List[Dict[str, Any]] = []
    for o in offerings:
        try:
            qty = int(o["inventory_qty"])
            point = int(o["reorder_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if o.get("reorder_pending_at"):
            continue
        if qty <= point:
            out.append(o)
    return out


def compose_purchase_order(biz: Dict[str, Any], offering: Dict[str, Any],
                           qty: int) -> Dict[str, Any]:
    """The PO email. One format for preview and send, so what the
    practitioner approved is exactly what goes out."""
    biz_name = (biz.get("name") or "our business").strip()
    name = (offering.get("name") or "product").strip()
    sku = (offering.get("sku") or "").strip()
    supplier_name = (offering.get("supplier_name") or "").strip()
    supplier_email = (offering.get("supplier_email") or "").strip()
    po_number = (f"PO-{datetime.now(timezone.utc):%Y%m%d}"
                 f"-{str(offering.get('id') or '')[:6].upper()}")

    sku_line = f"\n  SKU: {sku}" if sku else ""
    greeting = f"Hello {supplier_name}," if supplier_name else "Hello,"
    body = (
        f"{greeting}\n\n"
        f"{biz_name} would like to place the following order:\n\n"
        f"  {po_number}\n"
        f"  Item: {name}{sku_line}\n"
        f"  Quantity: {qty}\n\n"
        f"Please reply to this email to confirm availability, pricing, "
        f"and the expected delivery date.\n\n"
        f"Thank you,\n"
        f"{biz_name}"
    )
    return {
        "po_number": po_number,
        "subject": f"{po_number} — {qty} x {name} ({biz_name})",
        "body": body,
        "to_email": supplier_email,
        "to_name": supplier_name or None,
        "qty": qty,
    }


def clear_reorder_pending_if_restocked(business_id: str, offering_id: str,
                                       new_qty: Optional[int]) -> bool:
    """Called from every stock-RAISING path (manual adjust, Chief's
    adjust_stock). When the restock lifts stock back above the reorder
    point, the outstanding-order stamp comes off — the guard's whole
    lifecycle, closed. Best-effort by design: a missed clear means one
    suppressed alert, never a wrong send."""
    if new_qty is None:
        return False
    try:
        rows = sb_clients.sb_get_as_service(
            f"/offerings?id=eq.{offering_id}&business_id=eq.{business_id}"
            "&select=id,reorder_at,reorder_pending_at&limit=1") or []
        if not rows:
            return False
        o = rows[0]
        if not o.get("reorder_pending_at") or o.get("reorder_at") is None:
            return False
        if int(new_qty) > int(o["reorder_at"]):
            sb_clients.sb_patch_as_service(
                f"/offerings?id=eq.{offering_id}&business_id=eq.{business_id}",
                {"reorder_pending_at": None})
            return True
    except Exception as e:
        logger.warning(f"[reorder] pending-clear failed (non-fatal): {e}")
    return False


async def low_stock_reorder_sweep(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Hourly worker job: raise ONE reorder alert per business whose
    tracked products have fallen to/below their reorder point.

    Only offerings with an explicit reorder plan participate — a
    reorder_at nobody set cannot trip. The alert carries a
    draft_purchase_order action_payload for the item furthest below its
    point, so the notification's one tap produces the PO preview.
    """
    from notification_engine import (_within_waking_hours,
                                     _all_active_business_ids,
                                     create_urgent_alert)
    now = now or datetime.now(timezone.utc)
    if not _within_waking_hours(now):
        return {"skipped": "quiet_hours", "hour_utc": now.hour}

    rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        "/offerings?reorder_at=not.is.null&inventory_qty=not.is.null"
        "&is_active=eq.true&archived_at=is.null"
        f"&select=id,business_id,name,sku,inventory_qty,{REORDER_FIELDS}"
        "&limit=1000") or []
    low = tripped(rows)
    if not low:
        return {"candidates": len(rows), "alerts": 0}

    by_biz: Dict[str, List[Dict[str, Any]]] = {}
    for o in low:
        bid = str(o.get("business_id") or "")
        if bid:
            by_biz.setdefault(bid, []).append(o)

    alerts = 0
    async with httpx.AsyncClient() as client:
        active = set(await _all_active_business_ids(client))
        for bid, items in by_biz.items():
            if bid not in active:
                continue
            try:
                # Worst first: furthest below its reorder point.
                items.sort(key=lambda o: int(o["inventory_qty"]) - int(o["reorder_at"]))
                worst = items[0]
                w_name = worst.get("name") or "A product"
                w_qty = int(worst["inventory_qty"])
                left = f"{w_qty} left" if w_qty > 0 else "sold out"
                has_supplier = bool((worst.get("supplier_email") or "").strip())

                if len(items) == 1:
                    title = f"{w_name}: {left} — time to reorder"
                    body = (f"Stock hit your reorder point of "
                            f"{int(worst['reorder_at'])}.")
                else:
                    names = ", ".join((o.get("name") or "?") for o in items[:3])
                    more = f" and {len(items) - 3} more" if len(items) > 3 else ""
                    title = f"{len(items)} products hit their reorder point"
                    body = (f"{names}{more} are at or below their reorder "
                            f"points. {w_name} is furthest down ({left}).")
                body += (" Tap and Chief drafts the purchase order — "
                         "nothing sends without your say-so."
                         if has_supplier else
                         " Add a supplier on the product (or tell Chief) "
                         "and the purchase order drafts itself.")

                alert = await create_urgent_alert(
                    client, bid, title=title, body=body,
                    dedup_key=f"reorder:{bid}",
                    dedup_hours=REORDER_DEDUP_HOURS,
                    priority="high",
                    suggested_action=f"Draft the PO for {w_name}",
                    action_payload={"type": "draft_purchase_order",
                                    "offering_id": str(worst.get("id"))},
                )
                if alert:
                    alerts += 1
            except Exception as e:
                logger.exception(f"[reorder] sweep failed for {bid}: {e}")

    return {"candidates": len(rows), "low": len(low),
            "businesses": len(by_biz), "alerts": alerts}
