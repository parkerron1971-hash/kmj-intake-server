-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-09-04 — chief_moves: what came of each of Chief's moves
--
-- The standing agent and the assignments engine leave a full trace of
-- what Chief DID and nothing about what came of it. This table is one
-- row per move (a proposal filed, a task set, a note left, a step
-- toward an assignment) with the ids the move produced, and an
-- `outcome` that outcome_ledger.py's six-hourly reconciler fills in
-- from plain reads: approved / dismissed / expired / replied /
-- completed / ignored / met / missed / no_signal. Bookkeeping moves
-- with nothing to wait for are `done` at once.
--
-- From these rows: the digest that rides every prompt ("what lands
-- with this practitioner"), the retire rule (a proposal verb dismissed
-- three times running is refused for two weeks), and the weekly
-- report's numbers.
--
-- Service-role only: RLS on, no policies. Code is fail-soft without it.
-- Additive + idempotent. Apply before or after deploy.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.chief_moves (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id    uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  surface        text NOT NULL,                       -- agent | assignment
  verb           text NOT NULL,                       -- the action type
  assignment_id  uuid,                                -- when made toward an assignment
  queue_id       uuid,                                -- the proposal / draft it filed
  target_type    text,                                -- task | invoice | session | contact | note
  target_id      text,
  contact_id     uuid,
  outcome        text NOT NULL DEFAULT 'pending',
  outcome_at     timestamptz,
  made_at        timestamptz NOT NULL DEFAULT now(),
  created_at     timestamptz NOT NULL DEFAULT now()
);

-- No CHECK on outcome: the vocabulary belongs to the code and has
-- already grown once while this file was being written.

-- The reconciler's read: what is still pending, oldest first.
CREATE INDEX IF NOT EXISTS idx_chief_moves_pending
  ON public.chief_moves (made_at)
  WHERE outcome = 'pending';

-- The digest's read: a business's last thirty days.
CREATE INDEX IF NOT EXISTS idx_chief_moves_biz_time
  ON public.chief_moves (business_id, made_at DESC);

ALTER TABLE public.chief_moves ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.chief_moves FROM anon, authenticated;

COMMENT ON TABLE public.chief_moves IS
  'One row per move Chief made on its own, and what came of it (outcome_ledger.py). Service-role only; see APPLY-2026-09-04-chief-moves.sql.';

-- ─── Verify ──────────────────────────────────────────────────────────
--   SELECT to_regclass('public.chief_moves') IS NOT NULL;            -- t
--   SELECT relrowsecurity FROM pg_class WHERE relname='chief_moves'; -- t
--   SELECT count(*) FROM pg_policies WHERE tablename='chief_moves';  -- 0

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.chief_moves;
