"""Verify discounted Checkout totals before they reach receipts or the ledger."""
from urllib.parse import quote

import sb_clients


def verify_checkout_account(session, account_id):
    md = session.get("metadata") or {}
    table = {"order": "orders", "booking": "module_entries"}.get(md.get("source_type"))
    if not table or not account_id or not md.get("source_id"):
        raise ValueError("Discount checkout has no verified payment account/source")
    rows = sb_clients.sb_get_as_service(
        f"/{table}?id=eq.{quote(str(md['source_id']), safe='')}&select=business_id&limit=1") or []
    if not rows:
        raise ValueError("Discount checkout source does not exist")
    businesses = sb_clients.sb_get_as_service(
        "/businesses?id=eq." + quote(str(rows[0]["business_id"]), safe="") +
        "&select=stripe_account_id&limit=1") or []
    if not businesses or businesses[0].get("stripe_account_id") != account_id:
        raise ValueError("Discount checkout belongs to a different payment account")


def order_settlement(order, session):
    if order.get("stripe_checkout_session_id") != session.get("id"):
        raise ValueError("Checkout does not match this order")
    if (session.get("currency") or "").lower() != (order.get("currency") or "usd").lower():
        raise ValueError("Checkout currency does not match the order")
    details = session.get("total_details") or {}
    amounts = [session.get("amount_total"), session.get("amount_subtotal"),
               details.get("amount_tax"), details.get("amount_shipping"), details.get("amount_discount")]
    if any(type(value) is not int or value < 0 for value in amounts):
        raise ValueError("Checkout is missing valid settlement totals")
    total, gross, tax, shipping, discount = amounts
    if discount > gross or total != gross - discount + tax + shipping:
        raise ValueError("Checkout totals do not balance")
    if gross != order.get("subtotal_cents") and not order.get("paid_at"):
        raise ValueError("Checkout merchandise does not match the order")
    if shipping != order.get("shipping_cents", 0):
        raise ValueError("Checkout shipping does not match the order")
    # Receipts derive the discount from order_items minus net subtotal.
    return {"subtotal_cents": gross - discount, "tax_cents": tax,
            "shipping_cents": shipping, "total_cents": total}
