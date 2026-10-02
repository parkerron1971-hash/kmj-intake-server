-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-09-04 — proposals with a life: agent_queue.expires_at,
-- agent_queue.reminded_at, and `expired` as a status
--
-- action_proposals files a class-C verb (a text, an invoice, a payment
-- link…) into agent_queue for the practitioner's approval. Until now a
-- proposal never expired: a reply Chief drafted for a lead on Monday
-- was still "waiting" a month later, and approving it then would have
-- sent a stale message. Nothing reminded anyone either.
--
-- proposal_life.py (hourly tick) flips overdue drafts to `expired` and
-- reminds about the rest once. It probes for these columns and is
-- fail-soft without them: proposals file without an expiry, and the
-- tick does nothing. If the CHECK below is not widened, an overdue
-- draft is dismissed with the reason in ai_reasoning instead.
--
-- Additive + idempotent. Apply before or after deploy.
-- ══════════════════════════════════════════════════════════════════

ALTER TABLE public.agent_queue
  ADD COLUMN IF NOT EXISTS expires_at  timestamptz,
  ADD COLUMN IF NOT EXISTS reminded_at timestamptz;

-- The status CHECK was created inline in solutionist-system-migration
-- (draft | approved | sent | dismissed | failed) under an auto-generated
-- name. Find it by its definition rather than guessing the name.
DO $$
DECLARE
  con record;
BEGIN
  FOR con IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'public.agent_queue'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%status%'
      AND pg_get_constraintdef(oid) ILIKE '%draft%'
  LOOP
    EXECUTE format('ALTER TABLE public.agent_queue DROP CONSTRAINT %I', con.conname);
  END LOOP;
  ALTER TABLE public.agent_queue
    ADD CONSTRAINT agent_queue_status_check
    CHECK (status IN ('draft', 'approved', 'sent', 'dismissed', 'failed', 'expired'));
EXCEPTION WHEN duplicate_object THEN
  NULL;  -- already widened on a previous run
END $$;

-- The tick's two reads: overdue drafts; drafts not yet reminded.
CREATE INDEX IF NOT EXISTS idx_agent_queue_expiring
  ON public.agent_queue (expires_at)
  WHERE status = 'draft' AND channel = 'action';

COMMENT ON COLUMN public.agent_queue.expires_at IS
  'When an unapproved proposal is let go (proposal_life). NULL = never expires (drafts that predate this, and non-proposal drafts).';
COMMENT ON COLUMN public.agent_queue.reminded_at IS
  'When proposal_life reminded the practitioner about this draft. One reminder per draft.';

-- ─── Verify ──────────────────────────────────────────────────────────
--   SELECT column_name FROM information_schema.columns
--     WHERE table_name='agent_queue' AND column_name IN ('expires_at','reminded_at');   -- 2 rows
--   SELECT pg_get_constraintdef(oid) FROM pg_constraint
--     WHERE conrelid='public.agent_queue'::regclass AND conname='agent_queue_status_check';  -- includes 'expired'

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP INDEX IF EXISTS public.idx_agent_queue_expiring;
--   ALTER TABLE public.agent_queue DROP COLUMN IF EXISTS expires_at, DROP COLUMN IF EXISTS reminded_at;
--   (and restore the five-value CHECK)
