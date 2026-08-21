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

THE REORDER BRAIN (2026-08-18 — sweep + composition in reorder_engine)
  set_reorder_plan       — class A write: sets reorder_at / reorder_qty
                           / supplier on ONE offering. Arms only a
                           notification and a draft, never a send.
  draft_purchase_order   — read: composes the PO preview from the
                           offering + plan. Writes nothing; the same
                           composer renders the real send, so the
                           preview IS what would go out.
  send_purchase_order    — class C, CLIENT_FACING: emails the PO to the
                           supplier under the business identity and
                           stamps reorder_pending_at (the duplicate-
                           order guard). The practitioner's "send it"
                           is the approval; never fired unprompted.

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
    from reorder_engine import REORDER_FIELDS
    from store_router import SELLABLE_CATEGORIES
    rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/offerings?business_id=eq.{biz_id}&is_active=eq.true"
        f"&select=id,name,sku,category,inventory_qty,{REORDER_FIELDS}"
        "&order=created_at.asc&limit=200") or []
    return [o for o in rows
            if (o.get("category") or "") in SELLABLE_CATEGORIES]


async def _resolve_sellable(client, biz, action,
                            action_type: str) -> Optional[Dict[str, Any]]:
    """Offering resolution shared by the reorder verbs: explicit id wins,
    else unique-ish name match — then a fresh fetch that carries the
    reorder columns, whatever the name-matcher selected."""
    offering_id = (action.get("offering_id") or "").strip()
    if not offering_id:
        name = (action.get("name") or action.get("offering_name") or "").strip()
        if name:
            from chief_of_staff import _find_offering_by_name
            found = await _find_offering_by_name(client, biz["id"], name)
            offering_id = str(found.get("id")) if found else ""
    if not offering_id:
        return None
    from reorder_engine import REORDER_FIELDS
    rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/offerings?id=eq.{offering_id}&business_id=eq.{biz['id']}"
        f"&select=id,name,sku,category,inventory_qty,{REORDER_FIELDS}&limit=1")
    return (rows or [None])[0]


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
    reorderable: List[str] = []
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
        if o.get("reorder_pending_at"):
            mark += " (PO sent, restock on order)"
        elif (o.get("reorder_at") is not None and qty <= int(o["reorder_at"])
                and (o.get("supplier_email") or "").strip()):
            reorderable.append(o.get("name") or "?")
        lines.append(f"{o.get('name')}{sku}: {qty}{mark}")

    bits = [f"{len(tracked)} tracked product{'s' if len(tracked) != 1 else ''}"]
    if untracked:
        bits.append(f"{len(untracked)} untracked")
    summary = "; ".join(lines) if lines else "nothing tracked yet"
    tail = ""
    if untracked and not tracked:
        tail = (" None carry a stock count yet — adjust_stock with a "
                "starting quantity turns tracking on.")
    if reorderable:
        tail += (f" {', '.join(reorderable[:3])} "
                 f"{'have' if len(reorderable) != 1 else 'has'} a supplier "
                 f"on file — say 'order more' and the purchase order "
                 f"drafts itself.")

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

    # A restock that lifts stock past the reorder point closes out the
    # outstanding-PO marker, re-arming the reorder sweep.
    from reorder_engine import clear_reorder_pending_if_restocked
    await asyncio.to_thread(clear_reorder_pending_if_restocked,
                            str(biz["id"]), str(offering["id"]), new_qty)

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


# ─── THE REORDER BRAIN — set_reorder_plan / draft / send PO ──────────

def _describe_plan(o: Dict[str, Any]) -> str:
    bits = []
    if o.get("reorder_at") is not None:
        bits.append(f"reorder point {int(o['reorder_at'])}")
    if o.get("reorder_qty") is not None:
        bits.append(f"order {int(o['reorder_qty'])} at a time")
    supplier = (o.get("supplier_name") or "").strip()
    email = (o.get("supplier_email") or "").strip()
    if supplier or email:
        bits.append(f"supplier {supplier or email}"
                    + (f" ({email})" if supplier and email else ""))
    return ", ".join(bits) if bits else "no reorder plan"


def _po_qty(action: Dict[str, Any],
            offering: Dict[str, Any]) -> Optional[int]:
    """Explicit qty wins; else the plan's reorder_qty. None = ask."""
    raw = action.get("qty")
    if raw is None:
        raw = offering.get("reorder_qty")
    try:
        qty = int(raw)
    except (TypeError, ValueError):
        return None
    return qty if qty > 0 else None


async def handle_set_reorder_plan(client, biz, action) -> Dict[str, Any]:
    offering = await _resolve_sellable(client, biz, action, "set_reorder_plan")
    if not offering:
        return _fail("set_reorder_plan",
                     "couldn't find that product — check_inventory lists "
                     "what's on file")
    from store_router import SELLABLE_CATEGORIES
    if (offering.get("category") or "") not in SELLABLE_CATEGORIES:
        return _fail("set_reorder_plan",
                     f"{offering.get('name')} isn't a store product — "
                     f"reorder plans track products, courses and packages")

    patch: Dict[str, Any] = {}
    for key in ("reorder_at", "reorder_qty"):
        if key in action:
            val = action.get(key)
            if val is None:
                patch[key] = None
                continue
            try:
                patch[key] = max(0, int(val))
            except (TypeError, ValueError):
                return _fail("set_reorder_plan",
                             f"{key} must be a whole number")
    for key in ("supplier_name", "supplier_email"):
        if key in action:
            val = (str(action.get(key) or "")).strip()
            patch[key] = val or None
    email = patch.get("supplier_email")
    if email and "@" not in email:
        return _fail("set_reorder_plan",
                     "that supplier email doesn't look like an address")
    if not patch:
        return _fail("set_reorder_plan",
                     "nothing to set — pass reorder_at, reorder_qty, "
                     "supplier_name, and/or supplier_email")
    # Removing the reorder point retires any outstanding-order marker
    # with it — no point, nothing to re-arm.
    if patch.get("reorder_at", "keep") is None:
        patch["reorder_pending_at"] = None

    res = await asyncio.to_thread(
        sb_clients.sb_patch_as_service,
        f"/offerings?id=eq.{offering['id']}&business_id=eq.{biz['id']}",
        patch)
    if res is None:
        return _fail("set_reorder_plan", "update failed")

    merged = {**offering, **patch}
    name = offering.get("name") or "product"
    return {
        "type": "set_reorder_plan",
        "offering_id": offering["id"],
        "result": (f"Reorder plan for {name}: {_describe_plan(merged)}. "
                   f"When stock hits the reorder point I'll flag it and "
                   f"have the purchase order drafted — nothing sends "
                   f"without your say-so."),
        "label": f"Reorder plan saved — {name}"[:120],
        "nav": _nav_catalog(),
    }


def _primary_supplier(business_id: str, offering_id: str):
    """The vendor ENTITY behind this product, when there is one.

    offerings.supplier_name/email are a cache of the primary link and are
    enough to ADDRESS the order; they cannot carry the trade account
    number, which lives on the vendor. Best-effort on purpose — a PO
    without an account line is still a valid PO, so a lookup failure must
    never stop somebody ordering stock.
    """
    try:
        links = sb_clients.sb_get_as_service(
            f"/offering_suppliers?offering_id=eq.{offering_id}"
            f"&business_id=eq.{business_id}&is_primary=is.true"
            f"&select=supplier_id&limit=1") or []
        if not links:
            return None
        sup = sb_clients.sb_get_as_service(
            f"/suppliers?id=eq.{links[0]['supplier_id']}&select=*&limit=1") or []
        return sup[0] if sup else None
    except Exception as e:
        logger.warning(f"[inventory] supplier lookup failed (non-fatal): {e}")
        return None


async def handle_draft_purchase_order(client, biz, action) -> Dict[str, Any]:
    offering = await _resolve_sellable(client, biz, action,
                                       "draft_purchase_order")
    if not offering:
        return _fail("draft_purchase_order",
                     "couldn't find that product — check_inventory lists "
                     "what's on file")
    from store_router import SELLABLE_CATEGORIES
    if (offering.get("category") or "") not in SELLABLE_CATEGORIES:
        return _fail("draft_purchase_order",
                     f"{offering.get('name')} isn't a store product — "
                     f"purchase orders cover products, courses and packages")
    supplier_email = (offering.get("supplier_email") or "").strip()
    name = offering.get("name") or "product"
    if not supplier_email:
        return _fail("draft_purchase_order",
                     f"no supplier on file for {name} — tell me the "
                     f"supplier's name and email and I'll save the "
                     f"reorder plan first")
    qty = _po_qty(action, offering)
    if qty is None:
        return _fail("draft_purchase_order",
                     f"how many should the order be for? {name} has no "
                     f"default reorder quantity yet — give me a qty or "
                     f"set one with the reorder plan")

    from reorder_engine import compose_purchase_order
    supplier = await asyncio.to_thread(
        _primary_supplier, str(biz["id"]), str(offering["id"]))
    po = compose_purchase_order(biz, offering, qty, supplier=supplier)
    pending = offering.get("reorder_pending_at")
    note = (f" Heads up: a PO for {name} already went out "
            f"({str(pending)[:10]}) and the restock hasn't been recorded "
            f"yet — send another only if you mean to."
            if pending else "")
    return {
        "type": "draft_purchase_order",
        "offering_id": offering["id"],
        "po": po,
        # The MCP handoff predicate reads numbers, never prose.
        "signal": {"po_ready": 1},
        "result": (f"Here's the purchase order for {name}:\n\n"
                   f"To: {po['to_name'] or po['to_email']} <{po['to_email']}>\n"
                   f"Subject: {po['subject']}\n\n"
                   f"{po['body']}\n\n"
                   f"Say the word and I'll send it.{note}"),
        "label": f"PO drafted — {qty} x {name}"[:120],
        "nav": _nav_catalog(),
    }


async def handle_send_purchase_order(client, biz, action) -> Dict[str, Any]:
    offering = await _resolve_sellable(client, biz, action,
                                       "send_purchase_order")
    if not offering:
        return _fail("send_purchase_order",
                     "couldn't find that product — check_inventory lists "
                     "what's on file")
    from store_router import SELLABLE_CATEGORIES
    if (offering.get("category") or "") not in SELLABLE_CATEGORIES:
        return _fail("send_purchase_order",
                     f"{offering.get('name')} isn't a store product — "
                     f"purchase orders cover products, courses and packages")
    name = offering.get("name") or "product"
    supplier_email = (offering.get("supplier_email") or "").strip()
    if not supplier_email or "@" not in supplier_email:
        return _fail("send_purchase_order",
                     f"no supplier email on file for {name} — save the "
                     f"reorder plan first")
    qty = _po_qty(action, offering)
    if qty is None:
        return _fail("send_purchase_order",
                     f"how many should the order be for? Give me a qty "
                     f"or set a default reorder quantity for {name}")

    # Duplicate-order guard: an outstanding PO must be acknowledged, not
    # silently doubled. "order anyway" → force=true.
    pending = offering.get("reorder_pending_at")
    if pending and not action.get("force"):
        return _fail("send_purchase_order",
                     f"a PO for {name} already went out "
                     f"({str(pending)[:10]}) and the restock hasn't been "
                     f"recorded — say 'order anyway' if you mean a second "
                     f"order")

    import os
    import email_sender
    from reorder_engine import compose_purchase_order
    supplier = await asyncio.to_thread(
        _primary_supplier, str(biz["id"]), str(offering["id"]))
    po = compose_purchase_order(biz, offering, qty, supplier=supplier)
    reply_to = email_sender.build_routed_reply_to(str(biz["id"]), None)
    try:
        await email_sender.send_via_resend(
            to_email=po["to_email"],
            to_name=po["to_name"],
            from_email=(os.environ.get("RESEND_FROM_EMAIL")
                        or email_sender.DEFAULT_FROM_EMAIL),
            from_name=(biz.get("name") or None),
            subject=po["subject"],
            body=po["body"],
            reply_to=reply_to,
            business_id=str(biz["id"]),
        )
    except Exception as e:
        return _fail("send_purchase_order", f"send failed: {e}")

    from datetime import datetime, timezone
    stamped = await asyncio.to_thread(
        sb_clients.sb_patch_as_service,
        f"/offerings?id=eq.{offering['id']}&business_id=eq.{biz['id']}",
        {"reorder_pending_at": datetime.now(timezone.utc).isoformat()})
    stamp_note = ("" if stamped is not None else
                  " (couldn't record the outstanding-order marker — a "
                  "repeat low-stock nudge may appear)")

    return {
        "type": "send_purchase_order",
        "offering_id": offering["id"],
        "po_number": po["po_number"],
        "qty": qty,
        "result": (f"Sent. {po['po_number']} — {qty} x {name} — went to "
                   f"{po['to_name'] or po['to_email']} <{po['to_email']}> "
                   f"under your business identity; their reply routes "
                   f"back to you. When the stock arrives, tell me and "
                   f"I'll record it{stamp_note}."),
        "label": f"📦 PO sent — {qty} x {name}"[:120],
        "nav": _nav_catalog(),
    }
