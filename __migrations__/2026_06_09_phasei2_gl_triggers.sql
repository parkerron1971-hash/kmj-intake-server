-- ═════════════════════════════════════════════════════════════════════
-- Phase I.2 — GL live-sync: enqueue triggers + versioning + divergence alarms
-- ═════════════════════════════════════════════════════════════════════
-- C+enqueue-trigger (GL-1): thin AFTER triggers on the money tables stamp a
-- row into gl_sync_queue. ALL accounting logic stays in the Python generator
-- (gl_engine). No raw Postgres connection exists in the app (PostgREST only),
-- so the generator POLLS the queue via the existing AsyncIOScheduler — there
-- is no LISTEN/NOTIFY.
--
-- journal_entries gains a status so updates/deletes are handled append-only
-- (reverse the stale entry + post a new one; never UPDATE/DELETE ledger
-- lines). The old hard UNIQUE is replaced by a partial unique on active rows.
--
-- Additive + idempotent. Rollback at bottom. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

-- ─── journal_entries: versioning ────────────────────────────────────
ALTER TABLE public.journal_entries
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'reversed'));

-- Replace the hard unique (one row per source event) with a partial unique
-- on ACTIVE rows only, so a source can be reversed + re-posted over time.
ALTER TABLE public.journal_entries
    DROP CONSTRAINT IF EXISTS journal_entries_business_id_source_type_source_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_je_active_source
    ON public.journal_entries (business_id, source_type, source_id)
    WHERE status = 'active';

-- ─── Divergence alarms ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.gl_divergence_alarms (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id   uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved')),
    summary       jsonb,
    detected_at   timestamptz NOT NULL DEFAULT now(),
    resolved_at   timestamptz
);
CREATE INDEX IF NOT EXISTS idx_gl_alarms_business
    ON public.gl_divergence_alarms (business_id, status, detected_at DESC);

ALTER TABLE public.gl_divergence_alarms ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gl_alarms_owner_read ON public.gl_divergence_alarms;
CREATE POLICY gl_alarms_owner_read ON public.gl_divergence_alarms
    FOR SELECT USING (EXISTS (SELECT 1 FROM public.businesses b
                              WHERE b.id = gl_divergence_alarms.business_id
                                AND b.owner_id = auth.uid()));

-- ─── Enqueue trigger function (thin; no accounting logic) ────────────
CREATE OR REPLACE FUNCTION public.gl_enqueue() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_biz uuid;
    v_sid text;
    v_op  text;
BEGIN
    IF (TG_OP = 'DELETE') THEN
        v_biz := OLD.business_id; v_op := 'delete';
    ELSE
        v_biz := NEW.business_id; v_op := lower(TG_OP);
    END IF;
    IF (TG_TABLE_NAME = 'plaid_transactions') THEN
        v_sid := COALESCE(NEW.transaction_id, OLD.transaction_id);
    ELSE
        v_sid := COALESCE(NEW.id::text, OLD.id::text);
    END IF;
    INSERT INTO public.gl_sync_queue (business_id, source_table, source_id, op)
    VALUES (v_biz, TG_TABLE_NAME, v_sid, v_op);
    RETURN COALESCE(NEW, OLD);
END $$;

-- ─── Triggers — INSERT/DELETE always; UPDATE only on GL-affecting cols ─
-- (Updating an invoice's notes, say, enqueues nothing → no churn; the
--  generator's converge step would no-op anyway, this just trims the queue.)

DROP TRIGGER IF EXISTS gl_enq_invoices_ins ON public.invoices;
CREATE TRIGGER gl_enq_invoices_ins AFTER INSERT OR DELETE ON public.invoices
    FOR EACH ROW EXECUTE FUNCTION public.gl_enqueue();
DROP TRIGGER IF EXISTS gl_enq_invoices_upd ON public.invoices;
CREATE TRIGGER gl_enq_invoices_upd AFTER UPDATE ON public.invoices
    FOR EACH ROW WHEN (
        OLD.total IS DISTINCT FROM NEW.total
        OR OLD.status IS DISTINCT FROM NEW.status
        OR OLD.paid_at IS DISTINCT FROM NEW.paid_at
        OR OLD.refund_amount_cents IS DISTINCT FROM NEW.refund_amount_cents
        OR OLD.sent_at IS DISTINCT FROM NEW.sent_at
    ) EXECUTE FUNCTION public.gl_enqueue();

DROP TRIGGER IF EXISTS gl_enq_expenses_ins ON public.business_expenses;
CREATE TRIGGER gl_enq_expenses_ins AFTER INSERT OR DELETE ON public.business_expenses
    FOR EACH ROW EXECUTE FUNCTION public.gl_enqueue();
DROP TRIGGER IF EXISTS gl_enq_expenses_upd ON public.business_expenses;
CREATE TRIGGER gl_enq_expenses_upd AFTER UPDATE ON public.business_expenses
    FOR EACH ROW WHEN (
        OLD.amount IS DISTINCT FROM NEW.amount
        OR OLD.category IS DISTINCT FROM NEW.category
        OR OLD.subcategory IS DISTINCT FROM NEW.subcategory
        OR OLD.date IS DISTINCT FROM NEW.date
    ) EXECUTE FUNCTION public.gl_enqueue();

DROP TRIGGER IF EXISTS gl_enq_bills_ins ON public.bills;
CREATE TRIGGER gl_enq_bills_ins AFTER INSERT OR DELETE ON public.bills
    FOR EACH ROW EXECUTE FUNCTION public.gl_enqueue();
DROP TRIGGER IF EXISTS gl_enq_bills_upd ON public.bills;
CREATE TRIGGER gl_enq_bills_upd AFTER UPDATE ON public.bills
    FOR EACH ROW WHEN (
        OLD.amount IS DISTINCT FROM NEW.amount
        OR OLD.status IS DISTINCT FROM NEW.status
        OR OLD.paid_at IS DISTINCT FROM NEW.paid_at
        OR OLD.paid_amount IS DISTINCT FROM NEW.paid_amount
        OR OLD.category IS DISTINCT FROM NEW.category
        OR OLD.due_date IS DISTINCT FROM NEW.due_date
    ) EXECUTE FUNCTION public.gl_enqueue();

DROP TRIGGER IF EXISTS gl_enq_plaid_ins ON public.plaid_transactions;
CREATE TRIGGER gl_enq_plaid_ins AFTER INSERT OR DELETE ON public.plaid_transactions
    FOR EACH ROW EXECUTE FUNCTION public.gl_enqueue();
DROP TRIGGER IF EXISTS gl_enq_plaid_upd ON public.plaid_transactions;
CREATE TRIGGER gl_enq_plaid_upd AFTER UPDATE ON public.plaid_transactions
    FOR EACH ROW WHEN (
        OLD.reconciliation_status IS DISTINCT FROM NEW.reconciliation_status
        OR OLD.business_category IS DISTINCT FROM NEW.business_category
        OR OLD.excluded_from_books IS DISTINCT FROM NEW.excluded_from_books
        OR OLD.amount IS DISTINCT FROM NEW.amount
    ) EXECUTE FUNCTION public.gl_enqueue();

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TRIGGER IF EXISTS gl_enq_invoices_ins ON public.invoices;       (×2 per table)
--   ... DROP all gl_enq_* triggers ...
--   DROP FUNCTION IF EXISTS public.gl_enqueue();
--   DROP TABLE IF EXISTS public.gl_divergence_alarms;
--   DROP INDEX IF EXISTS public.uq_je_active_source;
--   ALTER TABLE public.journal_entries DROP COLUMN IF EXISTS status;

SELECT 'phase I.2 triggers installed' AS status;
