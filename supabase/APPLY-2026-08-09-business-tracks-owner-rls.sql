-- APPLY-2026-08-09-business-tracks-owner-rls.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- HOTFIX: a brand-new business could not start its Business Track.
--
--   Supabase error 403 {"code":"42501", "message":"new row violates
--   row-level security policy for table \"business_tracks\""}
--
-- WHY.  business_tracks (APPLY-2026-08-04-business-track.sql) shipped with
-- exactly two policies, both borrowed from the seat-access data plane:
--
--   tenant_member_read   using (is_business_member(business_id))
--   tenant_writer_write  using/check (is_business_writer(business_id))
--
-- Both helpers read public.business_users ONLY. An OWNER is not a
-- business_users row — ownership lives on businesses.owner_id, which is
-- why business_users_router.role_of resolves 'owner' from the businesses
-- table before it ever looks at a seat. On the older tables that didn't
-- matter: the seat-access file was additive over each table's
-- pre-existing owner policy. business_tracks was created three days
-- later and had no such policy to lean on, so the owner — the only
-- person who exists at onboarding, before a single seat is invited —
-- matched neither policy.
--
-- Result: the two direct PostgREST writes both 403'd for every new
-- business (the double error in the report is these two):
--   OnboardingFlow.tsx     POST /business_tracks   (track creation)
--   BusinessSession.tsx    POST /business_tracks   (create-on-demand)
-- and the SELECT returned an empty set, so the session's greeting gate
-- had nothing to wait on. The established-business fork dead-ended at
-- the end of onboarding.
--
-- This is precisely the trap APPLY-2026-08-01-concierge.sql called out
-- three days earlier: "new tables have no pre-existing owner policy to
-- lean on, unlike the trust surfaces." This file applies that same
-- pattern to business_tracks.
--
-- public.is_business_owner is the SECURITY DEFINER helper from
-- 2026_06_10_hotfix_rls_recursion.sql — never an inline cross-table
-- EXISTS in the policy body (that is the 42P17 recursion outage class).
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE. Widens access to the owner
-- only; seat behaviour is unchanged.

-- ─── business_tracks: let the owner in ──────────────────────────────

drop policy if exists tenant_member_read on public.business_tracks;
create policy tenant_member_read on public.business_tracks
  for select to authenticated
  using (public.is_business_owner(business_id)
         or public.is_business_member(business_id));

drop policy if exists tenant_writer_write on public.business_tracks;
create policy tenant_writer_write on public.business_tracks
  for all to authenticated
  using (public.is_business_owner(business_id)
         or public.is_business_writer(business_id))
  with check (public.is_business_owner(business_id)
              or public.is_business_writer(business_id));

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────

-- 1. Both policies exist and both mention is_business_owner.
--    Expected: 2 rows, owner_covered = true on each.
select policyname,
       cmd,
       (coalesce(qual, '') like '%is_business_owner%')             as owner_in_using,
       (coalesce(with_check, qual, '') like '%is_business_owner%') as owner_in_check
  from pg_policies
 where schemaname = 'public'
   and tablename = 'business_tracks'
 order by policyname;

-- 2. The sibling fork, for contrast — strategy_tracks predates seat
--    access and should already carry an owner policy of its own.
--    Expected: at least one policy whose predicate names owner_id or
--    is_business_owner. If this returns NOTHING, the "I have an idea"
--    fork has the identical hole and needs the same two statements.
select policyname, cmd
  from pg_policies
 where schemaname = 'public'
   and tablename = 'strategy_tracks'
   and (coalesce(qual, '') || coalesce(with_check, ''))
         ~ '(owner_id|is_business_owner)'
 order by policyname;
