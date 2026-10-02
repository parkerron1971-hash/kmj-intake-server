-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-09-04 — chief_assignments: an outcome Chief works over days
--
-- "Fill Thursday." Said once in chat; from then on the standing agent
-- (chief_agent, same switch) measures it with a plain read every
-- fifteen minutes and thinks — a model turn — only when the picture
-- changed or hours have passed. Different from chief_missions, which
-- is a fixed step list the practitioner approved: an assignment has a
-- TARGET the code can measure, a DEADLINE, and a log of the moves Chief
-- made toward it, reasoning written before each one.
--
-- Service-role only: RLS on, no policies (first_run_arc / dev_tasks
-- precedent). Every read and write goes through the backend after the
-- owner check; the app's card reads GET /agents/chief/assignments.
--
-- The code is fail-soft without the table: the tick logs this file
-- name and does nothing; the chat verb says assignments are not set
-- up yet. Apply before or after deploy.
--
-- Additive + idempotent.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.chief_assignments (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id    uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  title          text NOT NULL,
  ask            text NOT NULL DEFAULT '',            -- the practitioner's words, verbatim
  target         jsonb NOT NULL DEFAULT '{}'::jsonb,  -- {kind, from, to, count | amount | invoice_id}
  deadline       timestamptz NOT NULL,
  status         text NOT NULL DEFAULT 'active',      -- active | completed | expired | stopped
  progress       jsonb,                               -- {value, target, met, label, checked_at}
  moves          jsonb NOT NULL DEFAULT '[]'::jsonb,  -- [{at, reasoning, actions[], proposed[], recap, idle}]
  report         text NOT NULL DEFAULT '',
  origin         text NOT NULL DEFAULT 'chat',        -- chat | app | agent
  created_by     text,
  last_worked_at timestamptz,                         -- last time the model thought about it
  next_check_at  timestamptz,                         -- the tick's cursor; NULL when closed
  thinks_day     date,                                -- the day thinks_today counts
  thinks_today   integer NOT NULL DEFAULT 0,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

-- Deliberately no CHECK on status or target->>'kind': the archetype
-- CHECK went out of step with the app's own list in August and
-- Postgres silently rejected writes the app had called successful.
-- The code validates kinds at creation and treats an unknown status
-- as closed.

-- The tick's read: open rows whose next look is due.
CREATE INDEX IF NOT EXISTS idx_chief_assignments_due
  ON public.chief_assignments (next_check_at)
  WHERE status = 'active';

-- The card's and the cap's read: a business's rows, newest first.
CREATE INDEX IF NOT EXISTS idx_chief_assignments_biz
  ON public.chief_assignments (business_id, status, updated_at DESC);

ALTER TABLE public.chief_assignments ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.chief_assignments FROM anon, authenticated;

COMMENT ON TABLE public.chief_assignments IS
  'An outcome the standing agent works over days: a measurable target, a deadline, and the log of moves (reasoning first). Service-role only; see APPLY-2026-09-04-chief-assignments.sql.';

-- ─── Verify ──────────────────────────────────────────────────────────
--   SELECT to_regclass('public.chief_assignments') IS NOT NULL;            -- t
--   SELECT relrowsecurity FROM pg_class WHERE relname='chief_assignments'; -- t
--   SELECT count(*) FROM pg_policies WHERE tablename='chief_assignments';  -- 0

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.chief_assignments;
