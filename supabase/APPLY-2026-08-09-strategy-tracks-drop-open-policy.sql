-- APPLY-2026-08-09-strategy-tracks-drop-open-policy.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- SECURITY: strategy_tracks was readable and writable by every
-- authenticated user, across every tenant.
--
-- Found while fixing the business_tracks owner-RLS hole (the sibling
-- fork, APPLY-2026-08-09-business-tracks-owner-rls.sql). The table
-- carried four policies:
--
--   business_member_access  ALL     business_id in (select id from
--                                     businesses where owner_id = auth.uid())
--   tenant_member_read      SELECT  is_business_member(business_id)
--   tenant_writer_write     ALL     is_business_writer(business_id)
--   strategy_tracks_all     ALL     using (true) with check (true)   <-- TO PUBLIC
--
-- RLS policies combine with permissive OR. `using (true)` therefore
-- satisfied every row for every caller, and the three scoped policies
-- beside it decided nothing. A leftover from before the table was
-- scoped; the tightening passes added policies next to it instead of
-- removing it, so each pass looked correct while changing nothing.
--
-- Measured before the drop, impersonating a real owner who has exactly
-- one strategy track: 9 of 9 rows visible — 8 of them another tenant's
-- discovery answers, positioning and pricing.
--
-- WHY ONLY A DROP.  The three remaining policies already express the
-- intended access (owner via businesses.owner_id, plus read/write for
-- active seats). Nothing is added here. Verified by rehearsing the drop
-- inside a rolled-back transaction under `set local role authenticated`
-- + a forged request.jwt.claims sub, for four cases:
--
--   owner_B (owns 1)  -> sees 1     (was 9)
--   owner_A (owns 8)  -> sees 8     (was 9)
--   stranger (owns 0) -> sees 0     (was 9)
--   owner INSERT + UPDATE on own business -> still succeed
--   stranger INSERT into another tenant's business -> 42501 denied
--
-- That last pair is the point: the business_tracks bug was an owner
-- locked OUT by policies that only knew seats. The inverse mistake here
-- would be dropping the open policy and stranding every owner. Both
-- directions were proven before this ran.
--
-- Service-role paths are unaffected (service_role bypasses RLS). The
-- user-JWT paths that DO depend on these policies are the direct
-- PostgREST calls in StrategySession.tsx / StrategyTrack.tsx /
-- OnboardingFlow.tsx / BusinessProfileReview.tsx, and chief_of_staff's
-- _sb when a user JWT is bound to the context.
--
-- NON-DESTRUCTIVE to data: drops a policy, never a row. All 9 rows
-- confirmed present afterwards.

drop policy if exists strategy_tracks_all on public.strategy_tracks;

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────

-- 1. Expected: exactly 3 rows, all TO authenticated, none with a
--    `true` predicate. If any row shows qual = 'true', stop.
select policyname, cmd, qual, with_check
  from pg_policies
 where schemaname = 'public'
   and tablename = 'strategy_tracks'
 order by policyname;

-- 2. No blanket-true policy survives anywhere on the two track tables.
--    Expected: 0 rows.
select tablename, policyname
  from pg_policies
 where schemaname = 'public'
   and tablename in ('strategy_tracks', 'business_tracks')
   and (btrim(coalesce(qual, '')) = 'true'
        or btrim(coalesce(with_check, '')) = 'true');

-- 3. The same audit across EVERY table with a business_id — this class
--    is not worth finding one table at a time. Any row returned is a
--    tenant table whose scoping is nullified by a permissive-true
--    policy sitting beside it. Review each before dropping: a table
--    may legitimately be public (marketing/catalog surfaces).
select c.relname as tablename, p.polname as policyname,
       pg_get_expr(p.polqual, p.polrelid)      as using_expr,
       pg_get_expr(p.polwithcheck, p.polrelid) as check_expr
  from pg_policy p
  join pg_class c on c.oid = p.polrelid
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public'
   and p.polpermissive
   and exists (select 1 from pg_attribute a
                where a.attrelid = c.oid and a.attname = 'business_id'
                  and a.attnum > 0 and not a.attisdropped)
   and (coalesce(pg_get_expr(p.polqual, p.polrelid), 'true') = 'true'
        and coalesce(pg_get_expr(p.polwithcheck, p.polrelid), 'true') = 'true')
 order by c.relname, p.polname;
