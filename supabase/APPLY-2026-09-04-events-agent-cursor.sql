-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-09-04 — events.agent_handled_at: the standing agent's cursor
--
-- The event spine (event_spine.emit → public.events) has had writers
-- since July and exactly one scanning reader, notification_engine's
-- five-minute urgent check. There was no consumer cursor: nothing
-- could ask "what has nobody acted on yet?".
--
-- chief_agent.py asks exactly that, every ten minutes, for the
-- businesses that opted in. It stamps this column BEFORE it plans, so
-- a crash costs one run and can never double-handle a booking. Only
-- events inside a 24-hour window are ever picked up, so a business
-- that opts in today is not walked back through last month.
--
-- The code is fail-soft without the column (the fetch fails, logs the
-- file name, and the tick does nothing). Apply before or after deploy.
--
-- Additive + idempotent.
-- ══════════════════════════════════════════════════════════════════

ALTER TABLE public.events
  ADD COLUMN IF NOT EXISTS agent_handled_at timestamptz;

-- The tick's read: unhandled, recent, by type.
CREATE INDEX IF NOT EXISTS idx_events_agent_unhandled
  ON public.events (created_at)
  WHERE agent_handled_at IS NULL;

COMMENT ON COLUMN public.events.agent_handled_at IS
  'When chief_agent picked this event up (stamped before planning). NULL = not yet seen by the standing agent.';

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP INDEX IF EXISTS public.idx_events_agent_unhandled;
--   ALTER TABLE public.events DROP COLUMN IF EXISTS agent_handled_at;
