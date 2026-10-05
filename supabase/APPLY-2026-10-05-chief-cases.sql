-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-10-05 — chief_cases: the open-problem record
--
-- Solutionist Intelligence, step one. When Chief diagnoses a real
-- problem ("Tuesdays are empty: your booking page shows you open around
-- the clock") and the owner agrees to a fix, Chief opens a case: the
-- symptom in their words, the cause it found, the record it found it
-- in, the fix, and a forecast the code can check (a measure, the number
-- BEFORE, the number EXPECTED, the day it will look). On that day a
-- tick measures with a plain read, records what the records show and a
-- verdict, and tells the owner once.
--
-- Different from chief_assignments (a target Chief WORKS toward between
-- conversations) and from chief_moves (whether the owner took Chief's
-- move). A case is a diagnosis with a forecast; it grants no permission
-- and starts no work.
--
-- Service-role only: RLS on, no policies (chief_assignments precedent).
-- Every read and write goes through the backend after the owner check;
-- the app's card reads GET /agents/chief/cases.
--
-- The code is fail-soft without the table: the verbs say cases are not
-- available, the tick logs this file name and does nothing. Apply
-- before or after deploy.
--
-- Additive + idempotent.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.chief_cases (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id  uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  status       text NOT NULL DEFAULT 'open',          -- open | checked | closed
  symptom      text NOT NULL,                         -- the problem in the owner's words
  cause        text NOT NULL,                         -- what Chief found
  evidence     text NOT NULL DEFAULT '',              -- the record it found it in
  fix          text NOT NULL,                         -- what is being done
  measure      jsonb NOT NULL DEFAULT '{}'::jsonb,    -- {kind, weekdays?, invoice_id?}
  baseline     jsonb NOT NULL DEFAULT '{}'::jsonb,    -- {value, from, to, window_from, window_to}
  expected     numeric NOT NULL,                      -- the forecast for the window
  check_on     date NOT NULL,                         -- the business's day after the window
  result       jsonb,                                 -- {value, checked_at}
  verdict      text,                                  -- met | partly | not_met | unmeasured
  outcome      text,                                  -- the owner's close: solved | dropped
  note         text NOT NULL DEFAULT '',
  attempts     integer NOT NULL DEFAULT 0,            -- failed checks so far
  origin       text NOT NULL DEFAULT 'chat',
  created_by   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  checked_at   timestamptz,
  closed_at    timestamptz
);

-- Deliberately no CHECK on status, verdict or measure->>'kind' (the
-- chief_assignments note: a CHECK that drifts from the app's list makes
-- Postgres reject writes the app called successful). The code validates
-- at opening and treats an unknown status as closed.

-- The tick's read: open cases whose check day has come.
CREATE INDEX IF NOT EXISTS idx_chief_cases_due
  ON public.chief_cases (check_on)
  WHERE status = 'open';

-- The card's and the context's read: a business's cases, newest first.
CREATE INDEX IF NOT EXISTS idx_chief_cases_biz
  ON public.chief_cases (business_id, status, updated_at DESC);

ALTER TABLE public.chief_cases ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.chief_cases FROM anon, authenticated;

COMMENT ON TABLE public.chief_cases IS
  'A problem Chief diagnosed: symptom, cause, evidence, fix, and a forecast (measure, number before, number expected, check day) checked by a plain read. Service-role only; see APPLY-2026-10-05-chief-cases.sql.';

NOTIFY pgrst, 'reload schema';

-- ─── Verify ──────────────────────────────────────────────────────────
--   SELECT to_regclass('public.chief_cases') IS NOT NULL;              -- t
--   SELECT relrowsecurity FROM pg_class WHERE relname='chief_cases';   -- t
--   SELECT count(*) FROM pg_policies WHERE tablename='chief_cases';    -- 0

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.chief_cases;
