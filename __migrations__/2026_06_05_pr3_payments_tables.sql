-- ─────────────────────────────────────────────────────────────────
-- Phase D.4 PR 3 — Payments tables (idempotency + invoices + disputes)
-- ─────────────────────────────────────────────────────────────────
-- Run via:  Supabase Studio → SQL editor → paste + Run
-- Idempotent, forward-only, additive only. No data touched.
--
-- New tables:
--
--   stripe_webhook_events
--     Idempotency log: every Stripe webhook lands as one row keyed
--     by Stripe's event.id (which Stripe guarantees is unique). The
--     handler checks existence before dispatching, so retries from
--     Stripe don't double-process. Rows are kept for 90 days for
--     audit.
--
--   invoices
--     First-class invoice records. Mirrors a subset of Stripe's
--     invoice object for fast list-views. Stripe is still the source
--     of truth — fields here are best-effort cache populated by the
--     CRUD endpoints + webhook handlers.
--     Unified-source pattern: invoices created from Solutionist carry
--     id (uuid) here that maps to the metadata.source_id we set on
--     the corresponding Stripe Invoice, so a charge with
--     metadata.source_type='invoice' / source_id=<uuid> can be
--     resolved back to a local row.
--
--   stripe_disputes_cache
--     Lightweight cache of dispute state. Stripe Dashboard remains
--     the place to upload evidence in v1 — the cache exists so the
--     Charges tab can render a "Dispute open" badge without a
--     per-row Stripe API call. Evidence upload UI is PR 3 deferred.
--
-- After this runs, the PR 3 backend can be deployed.
-- ─────────────────────────────────────────────────────────────────

-- ─── 1. Webhook idempotency log ───────────────────────────────────

CREATE TABLE IF NOT EXISTS public.stripe_webhook_events (
    id text PRIMARY KEY,                              -- Stripe event.id
    type text NOT NULL,
    livemode boolean NOT NULL DEFAULT false,
    account_id text,
    received_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    processed_ok boolean,
    processed_error text,
    raw jsonb
);

CREATE INDEX IF NOT EXISTS stripe_webhook_events_received_at_idx
    ON public.stripe_webhook_events (received_at DESC);

-- ─── 2. Invoices ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.invoices (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    -- Stripe side
    stripe_invoice_id text,                           -- "in_..." (null until sent)
    stripe_customer_id text,                          -- "cus_..."
    -- Local mirror of customer-facing fields
    customer_name text,
    customer_email text,
    description text,                                 -- top-level memo
    -- Line items as JSONB so the editor can carry arbitrary rows
    -- without a separate invoice_line_items table.
    --   [{ description: text, quantity: int, unit_amount_cents: int }, ...]
    line_items jsonb NOT NULL DEFAULT '[]',
    -- Money fields cached from Stripe for fast list-views.
    currency text NOT NULL DEFAULT 'usd',
    subtotal_cents integer,
    total_cents integer,
    amount_due_cents integer,
    amount_paid_cents integer,
    -- Lifecycle: draft | open | paid | uncollectible | void
    status text NOT NULL DEFAULT 'draft',
    due_date date,
    hosted_invoice_url text,                          -- Stripe-hosted pay page
    pdf_url text,
    -- Timestamps
    sent_at timestamptz,
    paid_at timestamptz,
    voided_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT invoices_status_check CHECK (status IN ('draft','open','paid','uncollectible','void'))
);

CREATE INDEX IF NOT EXISTS invoices_business_id_idx
    ON public.invoices (business_id);
CREATE INDEX IF NOT EXISTS invoices_stripe_invoice_id_idx
    ON public.invoices (stripe_invoice_id);
CREATE INDEX IF NOT EXISTS invoices_status_idx
    ON public.invoices (business_id, status);

-- ─── 3. Disputes cache ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.stripe_disputes_cache (
    id text PRIMARY KEY,                              -- Stripe dispute id "dp_..."
    business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    stripe_charge_id text NOT NULL,
    stripe_payment_intent_id text,
    -- Cached Stripe fields for the Charges tab badge + future
    -- evidence-upload surface.
    reason text,
    status text,                                      -- warning_needs_response | needs_response | etc.
    amount_cents integer,
    currency text,
    evidence_due_by timestamptz,
    -- Lifecycle
    opened_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    -- Full Stripe object snapshot for the rare deep-dive case.
    raw jsonb
);

CREATE INDEX IF NOT EXISTS disputes_business_id_idx
    ON public.stripe_disputes_cache (business_id);
CREATE INDEX IF NOT EXISTS disputes_stripe_charge_id_idx
    ON public.stripe_disputes_cache (stripe_charge_id);
CREATE INDEX IF NOT EXISTS disputes_status_idx
    ON public.stripe_disputes_cache (business_id, status);

-- ─── Verify ───────────────────────────────────────────────────────

SELECT table_name FROM information_schema.tables
WHERE table_schema='public'
  AND table_name IN ('stripe_webhook_events','invoices','stripe_disputes_cache')
ORDER BY table_name;
