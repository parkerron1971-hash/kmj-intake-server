"""
event_spine.py — Rails Arc 3 — the internal event spine.

One catalog, one write path. Payment lands, document signs, payroll
runs — every rail speaks by dropping a row in the `events` table, and
everything downstream (the workflow engine's trigger matching, Chief's
timeline readers, future integrations) listens there instead of being
hand-wired to each webhook.

THE CATALOG IS DATA (the action_registry pattern): every event type
this codebase emits through the spine is declared below with its
source and payload shape. A drift test scans the source tree — an
emit() call with an uncataloged type fails CI, so the catalog cannot
rot into fiction. Legacy writers that post to /events directly are
documented here too (marked legacy) and migrate opportunistically.

emit() is BEST-EFFORT BY DESIGN: an event is a signal, not the work
itself. A failed insert logs loudly and returns False — it must never
break the payment/webhook/handler that emitted it.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import sb_clients

logger = logging.getLogger("event_spine")


# ─── The catalog ─────────────────────────────────────────────────────
# key: event_type as stored in events.event_type
# source: which subsystem emits it
# payload: documented data keys (informative, not enforced)
# legacy: True = written by pre-spine code paths directly to /events;
#         kept under its historical name because consumers filter on it.

EVENT_CATALOG: Dict[str, Dict[str, Any]] = {
    # ── Money in ─────────────────────────────────────────────────
    "invoice_paid_auto": {
        "source": "stripe webhooks (payment link match + Connect checkout)",
        "payload": ["invoice_id", "invoice_number", "total", "payment_method"],
        "legacy": True,  # name predates the spine; chief revenue readers filter on it
    },
    "hand_run_completed": {
        "source": "chief_jobs kind=browser_hand (browser_hand.run) — one per run, "
                  "whatever stopped it",
        "payload": ["job_id", "queue_id", "task", "ok", "stopped", "summary",
                    "frames", "steps"],
    },
    "booking_paid": {
        "source": "stripe_connect_router checkout/payment_intent",
        "payload": ["booking_id", "payment_intent_id"],
    },
    "order_paid": {
        "source": "stripe_connect_router checkout (store orders)",
        "payload": ["order_id", "payment_intent_id"],
    },
    "order_download": {
        "source": "store_files public download (digital delivery)",
        "payload": ["order_id", "offering_id", "filename"],
    },
    "stock_adjusted": {
        "source": ("store_router mark_order_paid (sale decrement, actor "
                   "'sale') + /store/inventory adjust endpoint + "
                   "chief_inventory_actions adjust_stock — the movement "
                   "history for physical inventory, spine rows instead of "
                   "a new table"),
        "payload": ["offering_id", "offering_name", "delta", "new_qty",
                    "reason", "actor"],
    },
    "stock_counted": {
        "source": ("inventory_count finish_count — ONE row per closed "
                   "stocktake, carrying every counted line INCLUDING the "
                   "ones that matched. It is the audit trail (\"we counted "
                   "it and it was right\") and the only reason repeat-"
                   "variance detection works with no extra table; the "
                   "lines that actually moved also get their own "
                   "stock_adjusted rows"),
        "payload": ["counted", "off", "units_short", "units_over",
                    "value_short", "note", "actor", "finished_at", "items"],
    },
    "stock_received": {
        "source": ("inventory_receive receive_stock — ONE row per booked-in "
                   "delivery. Distinct from stock_counted on purpose: a "
                   "count SETS (the shelf was right, the book was wrong), a "
                   "receive ADDS (the shelf was right and more arrived), and "
                   "the history has to be able to tell a delivery from a "
                   "stocktake forever after. Each line also gets its own "
                   "stock_adjusted row"),
        "payload": ["lines", "units", "orders_closed", "note", "actor",
                    "received_at"],
    },
    "product_replaced": {
        "source": ("inventory_scan mark_replacement — a new product takes "
                   "over a discontinued one's slot on the shelf. Records "
                   "WHAT carried (reorder point, order qty, supplier, "
                   "threshold) and whether the predecessor was archived, "
                   "so a catalog that changed shape can be explained "
                   "later without guessing"),
        "payload": ["offering_id", "offering_name", "predecessor_id",
                    "predecessor_name", "carried", "archived_predecessor",
                    "actor"],
    },
    "payment_received": {
        "source": "chief_of_staff manual marks",
        "payload": ["invoice_id", "amount"],
        "legacy": True,
    },
    "giving_received": {
        "source": ("chief_of_staff (church vertical manual mark) + "
                   "giving_router.record_gift (online gifts via the "
                   "Connect webhook)"),
        "payload": ["amount", "fund", "invoice_id", "recurring"],
        "legacy": True,
    },
    "payment_refunded": {
        "source": "stripe_connect_router charge.refunded",
        "payload": ["source_type", "source_id", "refunded_cents", "fully_refunded"],
    },
    # ── Platform billing ─────────────────────────────────────────
    "subscription_updated": {
        "source": "stripe_billing webhook (created/updated/deleted/payment_failed)",
        "payload": ["stripe_event", "status"],
    },
    "credits_granted": {
        "source": "stripe_billing webhook (credit packs)",
        "payload": ["credit_pack"],
    },
    # ── The books ────────────────────────────────────────────────
    "bank_transactions_synced": {
        "source": "plaid_router webhook",
        "payload": ["item_id"],
    },
    "bank_connection_broken": {
        "source": "plaid_router ITEM events",
        "payload": ["item_id", "status", "webhook_code"],
    },
    # ── Comms ────────────────────────────────────────────────────
    "sms_received": {
        "source": "sms_service.record_inbound_sms (already spine-shaped)",
        "payload": ["from", "preview"],
        "legacy": True,
    },
    "sms_sent": {
        "source": "sms_service outbound",
        "payload": ["to", "preview"],
        "legacy": True,
    },
    "email_replied": {
        "source": "email_sender inbound",
        "payload": ["from", "subject", "reply_id"],
        "legacy": True,
    },
    "agent_message_sent": {
        "source": "chief_of_staff / agents",
        "payload": ["channel", "subject"],
        "legacy": True,
    },
    # ── Workflow / lifecycle ─────────────────────────────────────
    "contact_form_submitted": {
        "source": "public_site contact_submit_endpoint (composed-site contact form)",
        "payload": ["name", "email", "message_preview", "new_contact"],
    },
    # 2026-09-04: bookings reached the rules engine (rules_engine.on_event)
    # and the practitioner's notification, but never the spine — so the
    # standing agent, whose only cursor is this table, could not see the
    # single event it is most useful for. Emitted by
    # booking_widget_router._create_appointment for every path that
    # books (widget, walk-in, Chief).
    "booking_created": {
        "source": "booking_widget_router._create_appointment",
        "payload": ["booking_id", "contact_name", "offering", "starts_at", "created_by"],
    },
    "lead_scored": {
        "source": ("lead_scoring.store — every capture door (intake form, "
                   "composed-site contact form, site concierge, booking "
                   "widget) scores through one rubric and drops the "
                   "reasoning here rather than into contacts.metadata, "
                   "which the capture path is still assembling"),
        "payload": ["score", "priority", "signals", "response_type",
                    "reasoning", "refined", "model", "source"],
    },
    "contact_status_changed": {
        "source": "chief_of_staff",
        "payload": ["from_status", "to_status"],
        "legacy": True,
    },
    "chief_auto_approved": {
        "source": "rules_engine / autopilot",
        "payload": ["action_type"],
        "legacy": True,
    },
    "contract_signed": {
        "source": "docuseal_router refresh (a completed signature)",
        "payload": ["contract_ref", "title", "signer_email"],
    },
    "document_uploaded": {
        "source": "DocumentsPanel (frontend insert)",
        "payload": ["file_name", "folder"],
        "legacy": True,
    },
    # ── Site Concierge (customer-facing website chat) ────────────
    "concierge_lead_captured": {
        "source": "site_concierge /public/concierge/{slug}/lead "
                  "(widget lead-capture form)",
        "payload": ["name", "email", "message_preview", "conversation_id",
                    "new_contact"],
    },
    "concierge_escalated": {
        "source": "site_concierge guardrail deflection (crisis/clinical "
                  "ask on a visitor conversation)",
        "payload": ["conversation_id", "reason"],
    },
}


def emit(event_type: str, business_id: Optional[str],
         data: Optional[Dict[str, Any]] = None,
         contact_id: Optional[str] = None,
         source: str = "system") -> bool:
    """Drop one event on the spine. Best-effort: never raises.

    Uncataloged types are written anyway (an event lost is worse than a
    catalog gap) but logged as errors so the drift shows up in Railway
    logs even before the CI test catches the commit.
    """
    if event_type not in EVENT_CATALOG:
        logger.error(f"[spine] UNCATALOGED event type '{event_type}' — "
                     f"add it to event_spine.EVENT_CATALOG")
    if not business_id:
        logger.warning(f"[spine] {event_type} emitted without business_id — dropped")
        return False
    row: Dict[str, Any] = {
        "business_id": business_id,
        "event_type": event_type,
        "data": data or {},
        "source": source,
    }
    if contact_id:
        row["contact_id"] = contact_id
    try:
        sb_clients.sb_post_as_service("/events", row, prefer=None)
    except Exception as e:
        logger.error(f"[spine] emit({event_type}) failed: {e}")
        return False
    # The standing agent's fast lane (2026-09-04): a lead or a booking
    # wakes it within a minute instead of waiting for the sweep. After
    # the row is safely written, best-effort, never able to fail the emit.
    try:
        import chief_agent
        chief_agent.nudge(business_id, event_type)
    except Exception as e:  # pragma: no cover
        logger.debug(f"[spine] nudge skipped: {e}")
    return True
