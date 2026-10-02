-- APPLY 2026-10-01 — agent_queue.data
--
-- WHY: three features read or write agent_queue.data, and the column was
-- never created. Every one of them has been failing quietly:
--
--   * Chief's autopilot sweep (chief_of_staff._autopilot_sweep) selects
--     `data` at the top of EVERY Chief turn. PostgREST answers 42703
--     "column agent_queue.data does not exist", the read returns nothing,
--     and autopilot never auto-approves a draft. Sentry PYTHON-FASTAPI-2,
--     43 events in its first 8 hours; it also tripped the watchdog's
--     errors:server incident (#1137).
--   * Bookkeeping "send to Inbox" (chief_bookkeeping.send_to_inbox)
--     writes `data` with the proposal link. The insert 400'd and the
--     proposal was marked sent anyway: gone from review, never in the
--     Inbox. (The code half of this fix stops marking it sent unless the
--     row lands.)
--   * Payment-reminder escalation (chief_of_staff, data->>invoice_id)
--     counted 0 reminders forever, so smart mode never escalated.
--
-- WHAT: one nullable jsonb column, defaulting to an empty object so a
-- read of an old row is `{}` rather than null. Additive and replayable;
-- existing RLS on agent_queue already covers it.

ALTER TABLE public.agent_queue
  ADD COLUMN IF NOT EXISTS data jsonb DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.agent_queue.data IS
  'Structured context for a queued draft: e.g. chief_bookkeeping_proposal_id, invoice_id. Read by the autopilot sweep and payment escalation.';

-- PostgREST caches the schema; tell it the column exists now.
NOTIFY pgrst, 'reload schema';

-- VERIFY:
--   SELECT column_name, data_type, column_default
--     FROM information_schema.columns
--    WHERE table_schema = 'public' AND table_name = 'agent_queue'
--      AND column_name = 'data';                                   -- 1 row, jsonb, '{}'::jsonb
--   Then in Sentry, PYTHON-FASTAPI-2 ("column agent_queue.data does not
--   exist") stops receiving events within a few minutes.
--
-- ROLLBACK:
--   ALTER TABLE public.agent_queue DROP COLUMN IF EXISTS data;
--   NOTIFY pgrst, 'reload schema';
