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

-- (Policies below use the SECURITY DEFINER helpers from
-- 2026_06_10_hotfix_rls_recursion.sql — inline cross-table EXISTS in a
-- businesses policy recurses: 42P17. Helpers bypass RLS during evaluation.)
CREATE OR REPLACE FUNCTION public.is_business_owner(b_id uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.businesses b
                 WHERE b.id = b_id AND b.owner_id = auth.uid());
$$;
CREATE OR REPLACE FUNCTION public.is_business_member(b_id uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.business_users bu
                 WHERE bu.business_id = b_id AND bu.user_id = auth.uid()
                   AND bu.status = 'active');
$$;
CREATE OR REPLACE FUNCTION public.is_business_admin(b_id uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.business_users bu
                 WHERE bu.business_id = b_id AND bu.user_id = auth.uid()
                   AND bu.status = 'active' AND bu.role = 'admin');
$$;

-- Owner manages the team for their businesses.
DROP POLICY IF EXISTS business_users_owner_all ON public.business_users;
CREATE POLICY business_users_owner_all ON public.business_users
  FOR ALL
  USING (public.is_business_owner(business_users.business_id))
  WITH CHECK (public.is_business_owner(business_users.business_id));

-- A member can read their own membership rows.
DROP POLICY IF EXISTS business_users_self_read ON public.business_users;
CREATE POLICY business_users_self_read ON public.business_users
  FOR SELECT USING (user_id = auth.uid());

-- ─── businesses access for members (additive; ORed with owner policy) ─
-- Active members see the business → it appears in their switcher.
DROP POLICY IF EXISTS businesses_member_read ON public.businesses;
CREATE POLICY businesses_member_read ON public.businesses
  FOR SELECT USING (public.is_business_member(businesses.id));

-- Admin members can update the business row (settings etc.).
DROP POLICY IF EXISTS businesses_admin_update ON public.businesses;
CREATE POLICY businesses_admin_update ON public.businesses
  FOR UPDATE
  USING (public.is_business_admin(businesses.id))
  WITH CHECK (public.is_business_admin(businesses.id));

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP POLICY IF EXISTS businesses_member_read ON public.businesses;
--   DROP POLICY IF EXISTS businesses_admin_update ON public.businesses;
--   DROP TABLE IF EXISTS public.business_users;

SELECT 'phase E v1.1 multi-seat ready' AS status;
