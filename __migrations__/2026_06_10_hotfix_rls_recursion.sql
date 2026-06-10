-- ═════════════════════════════════════════════════════════════════════
-- HOTFIX — infinite recursion in businesses RLS (42P17)
-- ═════════════════════════════════════════════════════════════════════
-- ROOT CAUSE (two instances of the same A↔B policy cycle):
--   1. businesses_accountant_read (categoryd migration) did an inline
--      EXISTS on business_collaborators, whose collaborators_owner_read
--      policy does an inline EXISTS back on businesses → recursion.
--   2. businesses_member_read + businesses_admin_update (phasee11
--      multiseat migration) reference business_users, whose
--      business_users_owner_all policy references businesses → recursion.
--
-- FIX: every cross-table reference in these policies moves behind a
-- SECURITY DEFINER STABLE helper (runs as the function owner → bypasses
-- RLS during policy evaluation → the cycle cannot form). Same-table
-- checks keep using auth.uid() directly. Semantics are UNCHANGED:
--   • owner: full access via the pre-existing owner policy (untouched);
--   • active team members: SELECT their businesses;
--   • active admins: UPDATE their businesses;
--   • active accountant collaborators: SELECT their businesses;
--   • owners manage business_users / business_collaborators rows;
--   • members/invitees read their own membership rows (untouched —
--     they already used auth.uid() directly).
--
-- Apply via Supabase Studio. Idempotent. Does NOT roll back Category D.
-- ═════════════════════════════════════════════════════════════════════

-- ─── SECURITY DEFINER helpers (RLS-bypassing, read-only) ─────────────

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

CREATE OR REPLACE FUNCTION public.is_business_collaborator(b_id uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.business_collaborators bc
                 WHERE bc.business_id = b_id AND bc.user_id = auth.uid()
                   AND bc.status = 'active');
$$;

REVOKE ALL ON FUNCTION public.is_business_owner(uuid)        FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.is_business_member(uuid)       FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.is_business_admin(uuid)        FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.is_business_collaborator(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_business_owner(uuid)        TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_business_member(uuid)       TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_business_admin(uuid)        TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_business_collaborator(uuid) TO authenticated;

-- ─── businesses: recreate the three cross-table policies ────────────

DROP POLICY IF EXISTS businesses_member_read ON public.businesses;
CREATE POLICY businesses_member_read ON public.businesses
  FOR SELECT USING (public.is_business_member(businesses.id));

DROP POLICY IF EXISTS businesses_admin_update ON public.businesses;
CREATE POLICY businesses_admin_update ON public.businesses
  FOR UPDATE
  USING (public.is_business_admin(businesses.id))
  WITH CHECK (public.is_business_admin(businesses.id));

DROP POLICY IF EXISTS businesses_accountant_read ON public.businesses;
CREATE POLICY businesses_accountant_read ON public.businesses
  FOR SELECT USING (public.is_business_collaborator(businesses.id));

-- ─── business_users: owner-management policy via the helper ─────────
-- (business_users_self_read already uses auth.uid() directly — kept.)

DROP POLICY IF EXISTS business_users_owner_all ON public.business_users;
CREATE POLICY business_users_owner_all ON public.business_users
  FOR ALL
  USING (public.is_business_owner(business_users.business_id))
  WITH CHECK (public.is_business_owner(business_users.business_id));

-- ─── business_collaborators: owner-read policy via the helper ───────
-- (collaborators_self_read already uses auth.uid() directly — kept.)

DROP POLICY IF EXISTS collaborators_owner_read ON public.business_collaborators;
CREATE POLICY collaborators_owner_read ON public.business_collaborators
  FOR SELECT USING (public.is_business_owner(business_collaborators.business_id));

-- ─── Verification (run after applying) ───────────────────────────────
-- 1. No inline cross-table refs remain on the cycle tables:
--      SELECT tablename, policyname, qual FROM pg_policies
--      WHERE tablename IN ('businesses','business_users','business_collaborators');
-- 2. As an OWNER (browser session):  GET /rest/v1/businesses → 200, owned rows.
-- 3. As a TEAM MEMBER / ACCOUNTANT:  their businesses appear; nobody else's.

-- ─── Rollback (to the pre-hotfix, RECURSIVE state — don't) ───────────
--   The original policies are in 2026_06_10_phasee11_multiseat.sql and
--   2026_06_10_categoryd_roles_accountant.sql.

SELECT 'rls recursion hotfix applied' AS status;
