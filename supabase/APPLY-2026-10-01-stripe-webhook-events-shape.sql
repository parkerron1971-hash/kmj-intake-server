-- APPLY 2026-10-01 — stripe_webhook_events gets the shape its writers use
--
-- WHY: three webhook handlers write this table with `id` = the Stripe
-- event id ('evt_...'): stripe_billing._record_webhook (subscriptions),
-- stripe_connect_router (Connect payments) and stripe_proxy (checkout,
-- digital products). That is the PR3 design in
-- __migrations__/2026_06_05_pr3_payments_tables.sql. But production
-- already had an OLDER table by the same name (id uuid DEFAULT
-- gen_random_uuid(), stripe_id text NOT NULL, payload jsonb NOT NULL), so
-- PR3's CREATE TABLE IF NOT EXISTS was a no-op and every insert since has
-- failed: 'evt_...' is not a uuid, and stripe_id/payload were missing.
--
-- Found 2026-10-01 while building the money auditor. The table holds 0
-- rows, ever. What that broke:
--   * Replay protection. stripe_proxy and stripe_connect_router look an
--     event up by id before acting, so a Stripe retry (sent whenever the
--     endpoint is slow) of checkout.session.completed was processed
--     again: a digital product could be re-delivered, a Connect payment
--     handled twice.
--   * The audit trail: no record of any billing event.
--   * The watchdog's "Stripe webhook backlog" check, which counted 0
--     unprocessed events because nothing ever landed.
--
-- WHAT: make `id` text (the Stripe event id) and relax the two legacy
-- NOT NULLs no writer fills. The primary key stays on `id`, so a replay
-- collides with 409, which every writer already treats as "seen".
-- RLS, grants and the business_id foreign key are untouched. Safe on an
-- empty table; on a non-empty one the uuids simply become text.

ALTER TABLE public.stripe_webhook_events
  ALTER COLUMN id DROP DEFAULT,
  ALTER COLUMN id TYPE text USING id::text,
  ALTER COLUMN stripe_id DROP NOT NULL,
  ALTER COLUMN payload DROP NOT NULL;

COMMENT ON COLUMN public.stripe_webhook_events.id IS
  'Stripe event id (evt_...). Primary key: a replayed delivery collides and is skipped.';

NOTIFY pgrst, 'reload schema';

-- VERIFY:
--   SELECT column_name, data_type, is_nullable, column_default
--     FROM information_schema.columns
--    WHERE table_schema = 'public' AND table_name = 'stripe_webhook_events'
--      AND column_name IN ('id', 'stripe_id', 'payload');
--   -- id: text, NO, null default · stripe_id: YES · payload: YES
--   Then the next Stripe event lands as a row: SELECT id, type, received_at
--   FROM public.stripe_webhook_events ORDER BY received_at DESC LIMIT 5;
--
-- ROLLBACK (only while every id is still a uuid string):
--   ALTER TABLE public.stripe_webhook_events
--     ALTER COLUMN id TYPE uuid USING id::uuid,
--     ALTER COLUMN id SET DEFAULT gen_random_uuid();
--   NOTIFY pgrst, 'reload schema';
