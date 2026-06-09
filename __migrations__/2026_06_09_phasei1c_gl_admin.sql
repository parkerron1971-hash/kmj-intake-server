-- ═════════════════════════════════════════════════════════════════════
-- Phase I.1c precursor — GL admin actions log
-- ═════════════════════════════════════════════════════════════════════
-- Lightweight audit of GL admin operations (backfill / verify / reverse).
-- Distinct from chief_learning_signals + agent_queue (different concern:
-- operator actions, not Chief proposals). Additive + idempotent; clean
-- DROP rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.gl_admin_actions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id     uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    action_type     text NOT NULL,          -- backfill | verify | reverse | status
    result_summary  jsonb,
    performed_by    uuid,
    performed_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gl_admin_actions_user
    ON public.gl_admin_actions (performed_by, performed_at DESC);

ALTER TABLE public.gl_admin_actions ENABLE ROW LEVEL SECURITY;

-- v1: a practitioner sees their OWN actions (cross-user audit is future).
DROP POLICY IF EXISTS gl_admin_actions_self_read ON public.gl_admin_actions;
CREATE POLICY gl_admin_actions_self_read ON public.gl_admin_actions
    FOR SELECT USING (performed_by = auth.uid());

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.gl_admin_actions;

SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'gl_admin_actions';
