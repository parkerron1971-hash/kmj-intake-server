-- APPLY-2026-07-31-trust-seat-visibility.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- S11 trust hardening — the "empty rooms" bug, trust-surface edition.
-- The 7/31 seat-access data plane gave working seats the operational
-- tables but deliberately parked the agent/audit surfaces. Result: an
-- invited seat opens Approvals and History and sees NOTHING — not
-- "you can't act here", just silence, which reads as a broken app.
--
-- This grants READ ONLY, to any ACTIVE seat (viewer included), on the
-- three trust surfaces:
--   agent_queue     — the approval queue (drafts agents parked)
--   audit_log       — the unified "what happened, did it work" log
--   chief_undo_log  — what Chief can still take back
--
-- WRITES ARE UNCHANGED ON PURPOSE. Approving a draft, undoing an
-- action, and appending audit rows keep their existing paths (owner
-- RLS / backend service-role with the require_role ladder). audit_log
-- and chief_undo_log remain append-only: no update/delete policies
-- exist and none are added here.
--
-- Pattern: the SECURITY DEFINER helper public.is_business_member
-- (defined in 2026_06_10_hotfix_rls_recursion.sql, reused by
-- APPLY-2026-07-31-seat-access-data-plane.sql). Inline EXISTS across
-- tables is the 42P17 recursion outage class — never that.
--
-- Policies are ADDITIVE (permissive OR): the existing owner policies
-- keep working untouched.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

do $$
declare
  t text;
begin
  foreach t in array array['agent_queue', 'audit_log', 'chief_undo_log'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists tenant_member_read on public.%I', t);
    execute format(
      'create policy tenant_member_read on public.%I for select '
      'to authenticated using (public.is_business_member(business_id))', t);
  end loop;
end $$;

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
-- Expected: 3 rows, one tenant_member_read per table, cmd = SELECT.
select tablename, policyname, cmd
  from pg_policies
 where schemaname = 'public'
   and tablename in ('agent_queue', 'audit_log', 'chief_undo_log')
   and policyname = 'tenant_member_read'
 order by tablename;

-- Expected: zero UPDATE/DELETE policies on the append-only logs.
select count(*) as should_be_zero
  from pg_policies
 where schemaname = 'public'
   and tablename in ('audit_log', 'chief_undo_log')
   and cmd in ('UPDATE', 'DELETE');
