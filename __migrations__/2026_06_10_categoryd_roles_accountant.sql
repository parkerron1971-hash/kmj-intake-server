-- ═════════════════════════════════════════════════════════════════════
-- Category D — multi-role v2 + cross-business accountant access
-- ═════════════════════════════════════════════════════════════════════
-- 1. business_users.role grows to viewer/member/manager/admin
--    (owner stays implicit via businesses.owner_id).
-- 2. public.business_role(uuid) — ONE function every future table policy
--    can call: returns the caller's role on a business. Operational-table
--    policies adopt it incrementally (one line each); backend routers use
--    the matching require_role() helper for backend-mediated writes.
-- 3. Active accountant collaborators get businesses SELECT — an
--    accountant invited to several businesses sees all of them in their
--    switcher on login (cross-business access; per-row scope intact).
--
-- Additive + idempotent. Clean rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

-- 1. Role ladder.
ALTER TABLE public.business_users DROP CONSTRAINT IF EXISTS business_users_role_check;
ALTER TABLE public.business_users
  ADD CONSTRAINT business_users_role_check
  CHECK (role IN ('viewer', 'member', 'manager', 'admin'));

-- 2. Shared role resolution for RLS policies.
CREATE OR REPLACE FUNCTION public.business_role(b_id uuid)
RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT CASE
    WHEN EXISTS (SELECT 1 FROM public.businesses b
                 WHERE b.id = b_id AND b.owner_id = auth.uid()) THEN 'owner'
    ELSE (SELECT bu.role FROM public.business_users bu
          WHERE bu.business_id = b_id AND bu.user_id = auth.uid()
            AND bu.status = 'active' LIMIT 1)
  END;
$$;

REVOKE ALL ON FUNCTION public.business_role(uuid) FROM anon;
GRANT EXECUTE ON FUNCTION public.business_role(uuid) TO authenticated;

-- Example adoption (PER-TABLE POLICIES ADOPT INCREMENTALLY — applied as
-- each surface is touched; documented, not mass-applied, to avoid breaking
-- existing owner policies):
--   CREATE POLICY t_member_write ON public.<table> FOR INSERT
--     WITH CHECK (public.business_role(<table>.business_id)
--                 IN ('member','manager','admin','owner'));
--   CREATE POLICY t_viewer_read ON public.<table> FOR SELECT
--     USING (public.business_role(<table>.business_id) IS NOT NULL);

-- 3. Accountant collaborators see their businesses (switcher visibility).
-- (SECURITY DEFINER helper — an inline EXISTS on business_collaborators
-- recurses with collaborators_owner_read: 42P17. See the hotfix migration.)
CREATE OR REPLACE FUNCTION public.is_business_collaborator(b_id uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.business_collaborators bc
                 WHERE bc.business_id = b_id AND bc.user_id = auth.uid()
                   AND bc.status = 'active');
$$;

DROP POLICY IF EXISTS businesses_accountant_read ON public.businesses;
CREATE POLICY businesses_accountant_read ON public.businesses
  FOR SELECT USING (public.is_business_collaborator(businesses.id));

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP POLICY IF EXISTS businesses_accountant_read ON public.businesses;
--   DROP FUNCTION IF EXISTS public.business_role(uuid);
--   ALTER TABLE public.business_users DROP CONSTRAINT IF EXISTS business_users_role_check;
--   ALTER TABLE public.business_users ADD CONSTRAINT business_users_role_check
--     CHECK (role IN ('admin', 'member'));

SELECT 'category D roles + accountant access ready' AS status;
