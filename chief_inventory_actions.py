"""
chief_inventory_actions.py — Chief verbs for physical inventory.

THE GAP THIS CLOSES
  The store tracks stock (offerings.inventory_qty: null = untracked,
  checkout 409s on insufficient stock, paid orders decrement) — and had
  no verbs. "How many tees do I have left?" routed to update_offering's
  side door, and a restock could not be RECORDED as a movement: patching
  inventory_qty leaves no trail of why the number changed.

MOVEMENT HISTORY — THE SPINE, NOT A TABLE
  Every stock change here (and in store_router: the sale decrement and
  the inventory endpoints) drops a `stock_adjusted` event on the event
  spine with {offering_id, offering_name, delta, new_qty, reason,
  actor}. The inventory endpoint and the Stock UI read those rows as the
  per-item movement log. Zero new tables.

THRESHOLDS
  Low-stock alert thresholds live per offering in
  businesses.settings.store.low_stock = {offering_id: threshold}
  (settings-blob pattern, default none). check_inventory reads them; the
  crossing alert itself fires from mark_order_paid in store_router.

CLASSIFICATION
  check_inventory — read: levels + low-stock list, computed from
                    offerings + settings. Fetches, formats, writes
                    nothing.
  adjust_stock    — class C single-target write: patches
                    offerings.inventory_qty, the number that gates
                    checkout. The PATCH itself is one edit from right,
                    but stock truth diverging from the shelf silently
                    causes oversells/undersells of real customer orders
                    (the setup_store shape: reversible switch,
                    unattended downstream money effect). Proposal-only
                    unprompted; "add 10 tees" is the approval.

  House contract: every return carries `result` + `label`; failures
  carry `"failed": True`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import sb_clients

logger = logging.getLogger("chief_inventory_actions")


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    return {"type": action_type, "result": f"failed: {msg}", "label": msg[:80],
            "nav": None, "failed": True}


def _nav_catalog() -> Optional[Dict[str, Any]]:
    try:
        from chief_of_staff import _nav
        return _nav("operate", "catalog")
    except Exception:
        return None


async def _fresh_biz(biz_id: str) -> Dict[str, Any]:
    """Thresholds are edited from the Stock UI mid-conversation — read
    settings fresh rather than trusting the (possibly stale) biz row."""
    rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/businesses?id=eq.{biz_id}&select=id,settings&limit=1")
    return (rows or [{}])[0]


async def _sellable(biz_id: str) -> List[Dict[str, Any]]:
    from store_router import SELLABLE_CATEGORIES
    rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/offerings?business_id=eq.{biz_id}&is_active=eq.true"
        "&select=id,name,sku,category,inventory_qty"
        "&order=created_at.asc&limit=200") or []
    return [o for o in rows
            if (o.get("category") or "") in SELLABLE_CATEGORIES]


# ─── check_inventory (read) ──────────────────────────────────────────

async def handle_check_inventory(client, biz, action) -> Dict[str, Any]:
    from store_router import DEFAULT_LOW_STOCK_THRESHOLD, low_stock_thresholds
    items = await _sellable(biz["id"])
    if not items:
        return {
            "type": "check_inventory",
            "result": ("no sellable offerings on file — products, courses "
                       "and packages with a price appear in the store and "
                       "can carry stock."),
            "label": "No products to track",
            "nav": _nav_catalog(),
        }

    thresholds = low_stock_thresholds(await _fresh_biz(biz["id"]))
    tracked = [o for o in items if o.get("inventory_qty") is not None]
    untracked = [o for o in items if o.get("inventory_qty") is None]

    low: List[str] = []
    out_of_stock: List[str] = []
    lines: List[str] = []
    for o in tracked:
        qty = int(o["inventory_qty"])
        threshold = thresholds.get(str(o["id"]))
        effective = threshold if threshold is not None else DEFAULT_LOW_STOCK_THRESHOLD
        sku = f" [{o['sku']}]" if o.get("sku") else ""
        mark = ""
        if qty == 0:
            out_of_stock.append(o.get("name") or "?")
            mark = " — OUT OF STOCK"
        elif qty <= effective:
            low.append(f"{o.get('name')} ({qty} left)")
            mark = " — low"
        lines.append(f"{o.get('name')}{sku}: {qty}{mark}")

    bits = [f"{len(tracked)} tracked product{'s' if len(tracked) != 1 else ''}"]
    if untracked:
        bits.append(f"{len(untracked)} untracked")
    summary = "; ".join(lines) if lines else "nothing tracked yet"
    tail = ""
    if untracked and not tracked:
        tail = (" None carry a stock count yet — adjust_stock with a "
                "starting quantity turns tracking on.")

    if out_of_stock:
        label = f"⚠️ Out of stock: {', '.join(out_of_stock[:3])}"[:120]
    elif low:
        label = f"Low stock: {', '.join(n.split(' (')[0] for n in low[:3])}"[:120]
    else:
        label = f"Stock levels — {len(tracked)} tracked"

    return {
        "type": "check_inventory",
        "result": f"{', '.join(bits)}. {summary}.{tail}",
        "label": label,
        "low_stock": low,
        "out_of_stock": out_of_stock,
        "nav": _nav_catalog(),
    }


# ─── adjust_stock (class C single-target write) ──────────────────────

async def handle_adjust_stock(client, biz, action) -> Dict[str, Any]:
    # Resolve the offering: explicit id wins, else unique-ish name match.
    offering: Optional[Dict[str, Any]] = None
    offering_id = (action.get("offering_id") or "").strip()
    if offering_id:
        rows = await asyncio.to_thread(
            sb_clients.sb_get_as_service,
            f"/offerings?id=eq.{offering_id}&business_id=eq.{biz['id']}"
            "&select=id,name,category,inventory_qty&limit=1")
        offering = (rows or [None])[0]
    else:
        name = (action.get("name") or action.get("offering_name") or "").strip()
        if name:
            from chief_of_staff import _find_offering_by_name
            offering = await _find_offering_by_name(client, biz["id"], name)
    if not offering:
        return _fail("adjust_stock",
                     "couldn't find that product — check_inventory lists "
                     "what's on file")

    from store_router import SELLABLE_CATEGORIES
    if (offering.get("category") or "") not in SELLABLE_CATEGORIES:
        return _fail("adjust_stock",
                     f"{offering.get('name')} isn't a store product — stock "
                     f"tracks products, courses and packages")

    mode = (str(action.get("mode") or "delta")).strip().lower()
    if mode not in ("delta", "set"):
        return _fail("adjust_stock", "mode must be 'delta' or 'set'")
    try:
        amount = int(action.get("amount"))
    except (TypeError, ValueError):
        return _fail("adjust_stock", "amount must be a whole number")

    old = offering.get("inventory_qty")
    old_qty = int(old) if old is not None else None
    if mode == "delta":
        if old_qty is None:
            return _fail("adjust_stock",
                         f"{offering.get('name')} isn't tracked yet — use "
                         f"mode 'set' with the starting quantity to turn "
                         f"tracking on")
        new_qty = max(0, old_qty + amount)
    else:
        new_qty = max(0, amount)

    reason = (str(action.get("reason") or "")).strip() or "chief adjustment"

    res = await asyncio.to_thread(
        sb_clients.sb_patch_as_service,
        f"/offerings?id=eq.{offering['id']}&business_id=eq.{biz['id']}",
        {"inventory_qty": new_qty})
    if res is None:
        return _fail("adjust_stock", "update failed")

    # The movement row — same spine event the sale decrement writes.
    from store_router import _emit_stock_event
    await asyncio.to_thread(
        _emit_stock_event, str(biz["id"]), str(offering["id"]),
        offering.get("name") or "",
        (new_qty - old_qty) if old_qty is not None else new_qty,
        new_qty, reason, "chief")

    name = offering.get("name") or "product"
    was = f"{old_qty}" if old_qty is not None else "untracked"
    return {
        "type": "adjust_stock",
        "offering_id": offering["id"],
        "inventory_qty": new_qty,
        "result": (f"{name} stock is now {new_qty} (was {was}; "
                   f"reason: {reason}). The movement is on the record and "
                   f"the store updates immediately."),
        "label": f"📦 {name}: {was} → {new_qty}"[:120],
        "nav": _nav_catalog(),
    }
