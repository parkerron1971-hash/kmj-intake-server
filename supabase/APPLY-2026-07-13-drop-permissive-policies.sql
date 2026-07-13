-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-07-13 — remove the "allow-all" RLS policies that defeat
-- tenant isolation on four tables.
--
-- Beta-readiness audit (adversarial + a live pg_policies check): these
-- four tables have RLS ON and a correct owner-scoped policy
-- (business_member_access / owner-scoped), BUT ALSO a leftover
-- permissive `USING (true)` policy from the early permissive-RLS era.
-- Postgres combines permissive policies with OR, so the `true` policy
-- cancels the owner scoping — and because the public anon key ships in
-- the app bundle, ANYONE could read these tables across all tenants via
-- PostgREST directly. Worst exposure: invoices (financials) and
-- social_accounts (holds plaintext Meta page tokens).
--
-- ORDER OF OPERATIONS (already done in the paired backend PR): every
-- SERVER path that touched these tables with the anon key was first
-- switched to the service-role key (service-role bypasses RLS, so it is
-- unaffected by this drop) — email_sender, meta_oauth,
-- business_profile_agent, and stripe_proxy. After this migration:
--   • frontend (authenticated user JWT) → owner-scoped policy: sees only
--     its own business's rows. Correct.
--   • backend (service-role) → bypasses RLS: unaffected. Correct.
--   • attacker with the public anon key → no permissive policy, no
--     auth.uid(): blocked. Fixed.
--
-- Idempotent: DROP POLICY IF EXISTS. The owner-scoped policies are left
-- untouched.
-- ══════════════════════════════════════════════════════════════════

DROP POLICY IF EXISTS invoices_all           ON public.invoices;
DROP POLICY IF EXISTS social_accounts_all    ON public.social_accounts;
DROP POLICY IF EXISTS email_replies_all      ON public.email_replies;
DROP POLICY IF EXISTS business_profiles_all  ON public.business_profiles;

-- Verify (optional — run manually): each table should now show ONLY its
-- owner-scoped policy, and no policy with qual = 'true'.
-- SELECT tablename, policyname, qual FROM pg_policies
--   WHERE tablename IN ('invoices','social_accounts','email_replies','business_profiles')
--   ORDER BY tablename;
