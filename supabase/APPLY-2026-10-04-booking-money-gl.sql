-- Booking money joins the ledger's live sync (gl_engine.desired_for_booking).
--
-- gl_enqueue() is generic (NEW.id::text for non-plaid tables), so
-- module_entries only needs triggers. They fire for MONEY rows only:
-- module_entries holds every custom-module record, and editing a note on
-- a client record must not queue ledger work.
--
-- APPLY AFTER the backend deploy that knows "module_entries"
-- (gl_engine._TABLE_SOURCE_TYPES). A queue row drained by older code is
-- marked processed and skipped, and only a /gl/backfill would post it.
-- Additive + idempotent.

DROP TRIGGER IF EXISTS gl_enq_module_entries_ins ON public.module_entries;
CREATE TRIGGER gl_enq_module_entries_ins AFTER INSERT ON public.module_entries
    FOR EACH ROW WHEN (
        NEW.stripe_payment_intent_id IS NOT NULL
        OR NEW.data ? 'no_show_fee_charged_at'
    ) EXECUTE FUNCTION public.gl_enqueue();

DROP TRIGGER IF EXISTS gl_enq_module_entries_del ON public.module_entries;
CREATE TRIGGER gl_enq_module_entries_del AFTER DELETE ON public.module_entries
    FOR EACH ROW WHEN (
        OLD.stripe_payment_intent_id IS NOT NULL
        OR OLD.data ? 'no_show_fee_charged_at'
    ) EXECUTE FUNCTION public.gl_enqueue();

DROP TRIGGER IF EXISTS gl_enq_module_entries_upd ON public.module_entries;
CREATE TRIGGER gl_enq_module_entries_upd AFTER UPDATE ON public.module_entries
    FOR EACH ROW WHEN (
        OLD.paid_at IS DISTINCT FROM NEW.paid_at
        OR OLD.stripe_payment_intent_id IS DISTINCT FROM NEW.stripe_payment_intent_id
        OR (NEW.stripe_payment_intent_id IS NOT NULL AND (
               OLD.data -> 'amount_charged_cents'  IS DISTINCT FROM NEW.data -> 'amount_charged_cents'
            OR OLD.data -> 'tip_cents'             IS DISTINCT FROM NEW.data -> 'tip_cents'
            OR OLD.data -> 'deposit_paid_cents'    IS DISTINCT FROM NEW.data -> 'deposit_paid_cents'
            OR OLD.data -> 'amount_paid_cents'     IS DISTINCT FROM NEW.data -> 'amount_paid_cents'
            OR OLD.data -> 'price_at_booking'      IS DISTINCT FROM NEW.data -> 'price_at_booking'
            OR OLD.data -> 'refunded_amount_cents' IS DISTINCT FROM NEW.data -> 'refunded_amount_cents'
        ))
        OR OLD.data -> 'no_show_fee_charged_at'     IS DISTINCT FROM NEW.data -> 'no_show_fee_charged_at'
        OR OLD.data -> 'no_show_fee_charged_cents'  IS DISTINCT FROM NEW.data -> 'no_show_fee_charged_cents'
        OR OLD.data -> 'no_show_fee_refunded_cents' IS DISTINCT FROM NEW.data -> 'no_show_fee_refunded_cents'
    ) EXECUTE FUNCTION public.gl_enqueue();

-- Verify:
--   select tgname from pg_trigger
--   where tgrelid = 'public.module_entries'::regclass and tgname like 'gl_enq_%';
--   -> gl_enq_module_entries_del, gl_enq_module_entries_ins, gl_enq_module_entries_upd
--
-- Rollback:
--   DROP TRIGGER IF EXISTS gl_enq_module_entries_ins ON public.module_entries;
--   DROP TRIGGER IF EXISTS gl_enq_module_entries_del ON public.module_entries;
--   DROP TRIGGER IF EXISTS gl_enq_module_entries_upd ON public.module_entries;
