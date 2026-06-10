-- ═════════════════════════════════════════════════════════════════════
-- Phase E v1.1 — multi-seat team membership (business_users)
-- ═════════════════════════════════════════════════════════════════════
-- SEPARATE from business_collaborators (accountants): team members are
-- operators. v1 access grants:
--   • active members SEE the business (businesses SELECT policy) — the
--     business switcher lists it on login (existing RLS-scoped fetch);
--   • admins can UPDATE the business row (settings et al.).
-- Role-scoped write access across every operational table is the held
-- "multi-role permission system beyond v1" (Category D) — NOT included.
--
-- Additive + idempotent. Clean rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.business_users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id   uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  user_id       uuid,
  invited_email text NOT NULL,
  role          text NOT NULL DEFAULT 'member'
                  CHECK (role IN ('admin', 'member')),
  status        text NOT NULL DEFAULT 'invited'
                  CHECK (status IN ('invited', 'active', 'revoked')),
  token         uuid NOT NULL DEFAULT gen_random_uuid(),
  invited_by    uuid,
  invited_at    timestamptz DEFAULT now(),
  joined_at     timestamptz,
  revoked_at    timestamptz
);

CREATE INDEX IF NOT EXISTS idx_business_users_business
  ON public.business_users (business_id, status);
CREATE INDEX IF NOT EXISTS idx_business_users_user
  ON public.business_users (user_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_business_users_token
  ON public.business_users (token);

ALTER TABLE public.business_users ENABLE ROW LEVEL SECURITY;

-- Owner manages the team for their businesses.
DROP POLICY IF EXISTS business_users_owner_all ON public.business_users;
CREATE POLICY business_users_owner_all ON public.business_users
  FOR ALL
  USING (EXISTS (SELECT 1 FROM public.businesses b
                 WHERE b.id = business_users.business_id AND b.owner_id = auth.uid()))
  WITH CHECK (EXISTS (SELECT 1 FROM public.businesses b
                      WHERE b.id = business_users.business_id AND b.owner_id = auth.uid()));

-- A member can read their own membership rows.
DROP POLICY IF EXISTS business_users_self_read ON public.business_users;
CREATE POLICY business_users_self_read ON public.business_users
  FOR SELECT USING (user_id = auth.uid());

-- ─── businesses access for members (additive; ORed with owner policy) ─
-- Active members see the business → it appears in their switcher.
DROP POLICY IF EXISTS businesses_member_read ON public.businesses;
CREATE POLICY businesses_member_read ON public.businesses
  FOR SELECT USING (EXISTS (
    SELECT 1 FROM public.business_users bu
    WHERE bu.business_id = businesses.id
      AND bu.user_id = auth.uid() AND bu.status = 'active'));

-- Admin members can update the business row (settings etc.).
DROP POLICY IF EXISTS businesses_admin_update ON public.businesses;
CREATE POLICY businesses_admin_update ON public.businesses
  FOR UPDATE USING (EXISTS (
    SELECT 1 FROM public.business_users bu
    WHERE bu.business_id = businesses.id
      AND bu.user_id = auth.uid() AND bu.status = 'active' AND bu.role = 'admin'))
  WITH CHECK (EXISTS (
    SELECT 1 FROM public.business_users bu
    WHERE bu.business_id = businesses.id
      AND bu.user_id = auth.uid() AND bu.status = 'active' AND bu.role = 'admin'));

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP POLICY IF EXISTS businesses_member_read ON public.businesses;
--   DROP POLICY IF EXISTS businesses_admin_update ON public.businesses;
--   DROP TABLE IF EXISTS public.business_users;

SELECT 'phase E v1.1 multi-seat ready' AS status;
