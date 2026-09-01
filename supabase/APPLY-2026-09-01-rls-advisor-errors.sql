-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-09-01 — the eleven Security Advisor errors
--
-- Supabase's linter (splinter) reports 11 ERRORS on this project. They
-- are three findings, not eleven, and this file closes all three.
--
--   2 × RLS Disabled in Public   public.leads, public.discovery_submissions
--   1 × Sensitive Columns        public.discovery_submissions (PII)
--   8 × Security Definer View    seven of them referenced nowhere
--
-- WHY THIS MATTERS MORE THAN A LINT WARNING. docs/RLS_MODEL.md says, in
-- as many words: "Verified 2026-07-13: RLS is on for all core +
-- sensitive tables." That has not been true. Both tables below sit in
-- the `public` schema, which is exposed through PostgREST, and neither
-- has ever had an RLS statement in any migration in this repo — so they
-- stand at Supabase defaults, where `anon` and `authenticated` hold
-- table grants and RLS is the only thing that would have restricted
-- rows. The anon key ships in the frontend bundle.
--
-- The doc is corrected in the same change. A verification claim that has
-- gone stale is worse than no claim, because it stops anyone looking —
-- which is the lesson vertical_registry.KNOWN_GAPS already records this
-- project learning once.
--
-- ─── 1. public.leads ──────────────────────────────────────────────
--
-- Written by exactly one code path (kmj_intake_automation, the original
-- intake automation) and READ BY NOTHING in this repo — /leads/pending
-- serves local JSON files, not this table, and lead_admin.py operates on
-- `marketing_leads`, a different table entirely.
--
-- It holds client_name, client_email, organization, business_type,
-- readiness_score, draft_email, internal_notes and the full raw_answers
-- payload. Internal qualification notes about named prospects.
--
-- The writer used the ANON key until today. That is why RLS could not
-- simply be switched on: doing so would have silently killed the insert.
-- The code now writes as service role (same commit), so RLS-on costs
-- this path nothing — service_role has rolbypassrls.
--
-- ─── 2. public.discovery_submissions ──────────────────────────────
--
-- Zero references anywhere in this repo — no Python, no SQL, no
-- migration. An orphan from a retired feature, still exposed, still
-- flagged by the linter for columns holding PII. Nothing can break.
--
-- NO POLICY IS ADDED TO EITHER TABLE, and that is the intent rather than
-- an omission. RLS enabled with no permissive policy denies every role
-- that is not service_role, which is precisely the reachability these
-- two tables should have. Adding a policy would be inventing an audience
-- neither table has. Same shape as restricted_module_entries, which this
-- project already locked down this way.
--
-- ─── 3. The eight SECURITY DEFINER views ──────────────────────────
--
-- Not to be confused with RLS_MODEL.md Rule 2, which REQUIRES SECURITY
-- DEFINER *functions* for cross-table policy checks — that rule is right
-- and untouched. A definer *view* is the inverse: it runs with the
-- view owner's privileges, so RLS on the underlying tables does not
-- apply to whoever queries it. Postgres 15 makes that the default for
-- views, which is why eight accumulated without anyone deciding to.
--
-- Seven are referenced nowhere in this codebase, including
-- trust_client_balances and trust_reconciliation_state — derived IOLTA
-- client trust balances, reachable through PostgREST, bypassing RLS,
-- with nothing watching them. api_usage_summary_30d is the only one with
-- a caller (platform_console.py), which reads as service_role and is
-- therefore unaffected either way: service_role bypasses RLS in invoker
-- mode too.
--
-- security_invoker = true is the conservative fix. Dropping the seven
-- dead views would be tidier and is deliberately NOT done here — a
-- migration that closes a security finding should not also delete
-- objects, because those are different decisions with different
-- blast radii and only one of them is urgent.
--
-- Safe to re-run.
-- ══════════════════════════════════════════════════════════════════

-- ─── 1 + 2. The two unprotected tables ────────────────────────────

alter table public.leads                  enable row level security;
alter table public.discovery_submissions  enable row level security;

-- Belt and braces, matching restricted_module_entries: RLS decides which
-- ROWS a role may see; the grant decides whether it may ask at all.
-- Revoking means a leaked anon key gets a permission error rather than
-- an empty set, and the difference shows up in logs.
revoke all on public.leads                 from anon, authenticated;
revoke all on public.discovery_submissions from anon, authenticated;

comment on table public.leads is
  'KMJ''s own prospect intake (NOT tenant-scoped, NOT practitioner '
  'client leads — that is marketing_leads). Service-role only: RLS on '
  'with no policy, grants revoked. Written by kmj_intake_automation; '
  'read by nothing as of 2026-09-01.';

comment on table public.discovery_submissions is
  'Orphan table from a retired feature — no reader, no writer anywhere '
  'in kmj-intake-server as of 2026-09-01. Holds PII. Locked to '
  'service-role until someone establishes it is still needed; if it is '
  'not, drop it in a separate change.';

-- ─── 3. The definer views ─────────────────────────────────────────

alter view public.ets_pending_agent_actions  set (security_invoker = true);
alter view public.ets_event_summary          set (security_invoker = true);
alter view public.v_approval_queue           set (security_invoker = true);
alter view public.v_contact_health           set (security_invoker = true);
alter view public.v_business_stats           set (security_invoker = true);
alter view public.api_usage_summary_30d      set (security_invoker = true);
alter view public.trust_client_balances      set (security_invoker = true);
alter view public.trust_reconciliation_state set (security_invoker = true);

-- ─── Verification ─────────────────────────────────────────────────
--
-- Expect: rls_off = 0, and definer_views = 0.

do $$
declare
  rls_off int;
  definer_views int;
begin
  select count(*) into rls_off
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = 'public'
     and c.relname in ('leads', 'discovery_submissions')
     and not c.relrowsecurity;
  raise notice 'tables still without RLS: % (expect 0)', rls_off;

  select count(*) into definer_views
    from pg_views v
   where v.schemaname = 'public'
     and v.viewname in ('ets_pending_agent_actions','ets_event_summary',
                        'v_approval_queue','v_contact_health',
                        'v_business_stats','api_usage_summary_30d',
                        'trust_client_balances','trust_reconciliation_state')
     and not exists (
       select 1 from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relname = v.viewname
          and c.reloptions @> array['security_invoker=true']);
  raise notice 'views still SECURITY DEFINER: % (expect 0)', definer_views;
end $$;
