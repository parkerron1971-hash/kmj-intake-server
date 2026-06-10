-- ═════════════════════════════════════════════════════════════════════
-- Phase I.3 PR3 — accountant collaborator role (R4)
-- ═════════════════════════════════════════════════════════════════════
-- Owner invites an accountant by email → token link → invitee accepts. v1
-- ships the collaborator infrastructure + owner-facing management. The full
-- accountant-logs-in-and-operates experience (cross-business access, curated
-- CPA dashboard) is the v2 accountant arc (held list) — this is its data
-- layer.
--
-- Additive/idempotent. Clean DROP rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.business_collaborators (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id     uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    user_id         uuid,                          -- null until the invitee accepts
    invited_email   text NOT NULL,
    role            text NOT NULL DEFAULT 'accountant'
                      CHECK (role IN ('accountant', 'viewer', 'editor')),
    status          text NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'active', 'revoked', 'expired')),
    token           uuid NOT NULL DEFAULT gen_random_uuid(),
    invited_by      uuid,
    invited_at      timestamptz NOT NULL DEFAULT now(),
    accepted_at     timestamptz,
    revoked_at      timestamptz,
    expiration_at   timestamptz NOT NULL DEFAULT now() + interval '7 days'
);

CREATE INDEX IF NOT EXISTS idx_collaborators_business
    ON public.business_collaborators (business_id, status);
CREATE INDEX IF NOT EXISTS idx_collaborators_user
    ON public.business_collaborators (user_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_collaborators_token
    ON public.business_collaborators (token);

ALTER TABLE public.business_collaborators ENABLE ROW LEVEL SECURITY;

-- Owner manages collaborators for their businesses.
DROP POLICY IF EXISTS collaborators_owner_read ON public.business_collaborators;
CREATE POLICY collaborators_owner_read ON public.business_collaborators
    FOR SELECT USING (EXISTS (SELECT 1 FROM public.businesses b
                              WHERE b.id = business_collaborators.business_id
                                AND b.owner_id = auth.uid()));

-- Invitee reads their own (accepted) row.
DROP POLICY IF EXISTS collaborators_self_read ON public.business_collaborators;
CREATE POLICY collaborators_self_read ON public.business_collaborators
    FOR SELECT USING (user_id = auth.uid());

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.business_collaborators;

SELECT 'phase I.3 PR3 business_collaborators ready' AS status;
