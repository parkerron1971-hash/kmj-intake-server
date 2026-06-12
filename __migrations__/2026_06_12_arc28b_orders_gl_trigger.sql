-- Arc 28b — orders join GL live-sync.
-- The Phase I.2 gl_enqueue() function is generic (NEW.id::text for
-- non-plaid tables), so orders only need the AFTER triggers. Without
-- this, paid store orders reach the books only on a manual
-- /gl/backfill; with it, the existing queue poller converges them like
-- invoices. Additive + idempotent.

DROP TRIGGER IF EXISTS gl_enq_orders_ins ON public.orders;
CREATE TRIGGER gl_enq_orders_ins AFTER INSERT OR DELETE ON public.orders
    FOR EACH ROW EXECUTE FUNCTION public.gl_enqueue();

DROP TRIGGER IF EXISTS gl_enq_orders_upd ON public.orders;
CREATE TRIGGER gl_enq_orders_upd AFTER UPDATE ON public.orders
    FOR EACH ROW WHEN (
        OLD.status IS DISTINCT FROM NEW.status
        OR OLD.paid_at IS DISTINCT FROM NEW.paid_at
        OR OLD.total_cents IS DISTINCT FROM NEW.total_cents
        OR OLD.refund_amount_cents IS DISTINCT FROM NEW.refund_amount_cents
    ) EXECUTE FUNCTION public.gl_enqueue();

-- Rollback:
--   DROP TRIGGER IF EXISTS gl_enq_orders_ins ON public.orders;
--   DROP TRIGGER IF EXISTS gl_enq_orders_upd ON public.orders;
