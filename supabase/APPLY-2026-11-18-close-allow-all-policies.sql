-- APPLY-2026-11-18-close-allow-all-policies.sql
--
-- Twenty tenant tables carry a leftover PERMISSIVE allow-all policy
-- (USING true / WITH CHECK true, TO public) from the permissive-RLS era.
-- Postgres ORs permissive policies together, so the allow-all one cancels
-- every scoped policy beside it (docs/RLS_MODEL.md, Rule 3). `anon` holds
-- table privileges on all twenty, and the public anon key ships in the app
-- bundle: anyone holding it could read, change or delete every business's
-- rows in these tables straight through PostgREST. Found 2026-11-18 by
-- reading pg_policies on production. The same class as
-- APPLY-2026-07-13-drop-permissive-policies.sql, which closed four tables.
--
-- WHAT THIS DOES, in one transaction:
--   1. Drops the 26 allow-all policies, each by its exact name.
--   2. Adds nine scoped policies on eight tables, so the OWNER is never left with less than
--      the owner's own staff once the allow-all one is gone. (The seat
--      policies of APPLY-2026-07-31-seat-access-data-plane.sql say "the
--      owner keeps full access via each table's existing owner policies";
--      on these eight tables the only "owner policy" was the allow-all one.)
--        owner, everything (seats already hold tenant_writer_write there):
--          growth_milestones, growth_objectives, module_specs,
--          site_chat_history            -> business_owner_access
--        owner, read (seats already hold tenant_member_read there):
--          connectors, sms_keywords, sms_opt_outs -> business_owner_read
--        sms_bindings (it had NO other policy, and Messages reads it in the
--          browser): owner read + office-login read
--                                       -> business_owner_read, tenant_member_read
--      Every one goes through a SECURITY DEFINER helper that already exists
--      (is_business_owner, is_business_member: 2026_06_10_hotfix_rls_recursion),
--      never an inline cross-table EXISTS (Rule 2, the 42P17 outage).
--   3. Revokes anon's table privileges on the sixteen tables no browser
--      reads directly, signed in or out. The four the app does read with a
--      signed-in login (tasks, products, business_expenses, sms_bindings)
--      keep their grants, so a browser whose session has lapsed gets an
--      empty list from the policies, not a permission error.
--
-- AFTER IT:
--   anon (the public key, nobody signed in): nothing, on all twenty.
--   the owner: what the owner-scoped policy on each table gives (all twenty
--     either had one already or get one above), except the five that become
--     server-only.
--   an office login (a seat): what tenant_member_read / tenant_writer_write
--     already gave. Unchanged.
--   the server (service role): bypasses RLS. Unchanged.
--   server-only from here (no policy at all, no browser path reads them):
--     connector_action_log, marketing_leads, workflow_definitions,
--     workflow_runs. practitioner_profiles keeps the owner's own row.
--
-- ORDER: DEPLOY THE SERVER FIRST. Four server paths leaned on an allow-all
-- policy and are changed in the same pull request as this file:
--   * public_site.py read a site's `products` with the ANON key (six reads).
--     Without the code change, applying this empties the products on every
--     public site and storefront page.
--   * chief_of_staff._upsert_pattern wrote chief_patterns under the chat
--     user's JWT; an office login's writes would be refused and swallowed.
--   * brand_engine.get_bundle, chief_availability and booking_rehearsal read
--     the OWNER's practitioner_profiles row under the chat user's JWT; an
--     office login would lose the practitioner's name and timezone (a church
--     whose hours carry no timezone would read "unavailable" to its staff).
-- The code is safe to deploy before this file (it reads and writes the same
-- rows, as the server). This file is NOT safe before the code.
--
-- One transaction, safe to run twice (DROP POLICY IF EXISTS; each added
-- policy is dropped by its own name and created again), nothing but
-- policies and anon grants touched, no table rewritten or scanned. Each
-- DROP/CREATE POLICY takes a brief ACCESS EXCLUSIVE lock on its table
-- (catalog only); lock_timeout makes the file fail cleanly rather than queue
-- behind a long transaction.
--
-- NOT covered here (see worklog/2026-11-18-close-allow-all-policies.md):
-- the other allow-all policies on production: the ets_* tables of the
-- Embrace the Shift module, the public sol_* market tables, and four public
-- reference tables.
--
-- Check before applying (read-only):
--   -- 1. The helpers exist and a signed-in user may call them. Expect 2 rows, both true.
--   select p.proname, has_function_privilege('authenticated', p.oid, 'execute') as authenticated_may_call
--     from pg_proc p join pg_namespace n on n.oid = p.pronamespace
--    where n.nspname = 'public' and p.proname in ('is_business_owner', 'is_business_member')
--    order by 1;
--   -- 2. All twenty tables are there, RLS on, each with a business_id column
--   --    except marketing_leads (none) and practitioner_profiles (owner_id).
--   --    Expect 20 rows, rls true on every one.
--   select t.name, c.relrowsecurity as rls,
--          exists (select 1 from pg_attribute a where a.attrelid = c.oid and a.attname = 'business_id'
--                                                 and not a.attisdropped) as has_business_id
--     from unnest(array['business_expenses','chief_patterns','connector_action_log','connectors',
--                       'foundation_documents','foundation_progress','growth_milestones','growth_objectives',
--                       'marketing_leads','module_specs','practitioner_profiles','products','site_chat_history',
--                       'site_content_overrides','sms_bindings','sms_keywords','sms_opt_outs','tasks',
--                       'workflow_definitions','workflow_runs']) as t(name)
--     left join pg_class c on c.oid = to_regclass('public.' || t.name)
--    order by 1;
--   -- 3. What stands on each table today. Expect the 26 allow-all policies
--   --    (qual or with_check literally true) and, beside them, exactly the
--   --    scoped ones the worklog's table lists. If a table shows a scoped
--   --    policy the worklog does not list, or lacks one it does, stop.
--   select tablename, policyname, cmd, roles::text, qual, with_check
--     from pg_policies
--    where schemaname = 'public'
--      and tablename in ('business_expenses','chief_patterns','connector_action_log','connectors',
--                        'foundation_documents','foundation_progress','growth_milestones','growth_objectives',
--                        'marketing_leads','module_specs','practitioner_profiles','products','site_chat_history',
--                        'site_content_overrides','sms_bindings','sms_keywords','sms_opt_outs','tasks',
--                        'workflow_definitions','workflow_runs')
--    order by tablename, policyname;
--   -- 4. The server is on the paired code (products read as the server).
--   --    GET https://kmj-intake-server-production.up.railway.app/health and
--   --    confirm `version` is the commit that merged this file, or later.
--   -- 5. Nothing open long enough to trip the 5s lock_timeout. Expect 0 rows.
--   select pid, state, now() - xact_start as open_for, left(query, 80) as query
--     from pg_stat_activity
--    where xact_start is not null and pid <> pg_backend_pid() and now() - xact_start > interval '15 seconds';
begin;

set local lock_timeout = '5s';

-- ─── 1. The allow-all policies go ─────────────────────────────────────
drop policy if exists business_expenses_all        on public.business_expenses;
drop policy if exists patterns_all                 on public.chief_patterns;
drop policy if exists cal_all                      on public.connector_action_log;
drop policy if exists connectors_all               on public.connectors;
drop policy if exists foundation_documents_all     on public.foundation_documents;
drop policy if exists foundation_progress_all      on public.foundation_progress;
drop policy if exists growth_ms_all                on public.growth_milestones;
drop policy if exists growth_obj_all               on public.growth_objectives;
drop policy if exists marketing_leads_all          on public.marketing_leads;
drop policy if exists specs_all                    on public.module_specs;
drop policy if exists practitioner_profiles_all    on public.practitioner_profiles;
drop policy if exists products_all                 on public.products;
drop policy if exists "Allow all deletes on site_chat_history" on public.site_chat_history;
drop policy if exists "Allow all inserts on site_chat_history" on public.site_chat_history;
drop policy if exists "Allow all reads on site_chat_history"   on public.site_chat_history;
drop policy if exists "Allow all updates on site_chat_history" on public.site_chat_history;
drop policy if exists "Allow all deletes on site_content_overrides" on public.site_content_overrides;
drop policy if exists "Allow all inserts on site_content_overrides" on public.site_content_overrides;
drop policy if exists "Allow all reads on site_content_overrides"   on public.site_content_overrides;
drop policy if exists "Allow all updates on site_content_overrides" on public.site_content_overrides;
drop policy if exists sms_bindings_all             on public.sms_bindings;
drop policy if exists sms_keywords_all             on public.sms_keywords;
drop policy if exists sms_opt_outs_all             on public.sms_opt_outs;
drop policy if exists tasks_all                    on public.tasks;
drop policy if exists wf_def_all                   on public.workflow_definitions;
drop policy if exists wf_run_all                   on public.workflow_runs;

-- ─── 2. The owner is never left with less than the owner's own staff ──
-- Seats already hold tenant_writer_write on these four: the owner, everything.
drop policy if exists business_owner_access on public.growth_milestones;
create policy business_owner_access on public.growth_milestones for all to authenticated
  using (public.is_business_owner(business_id)) with check (public.is_business_owner(business_id));
drop policy if exists business_owner_access on public.growth_objectives;
create policy business_owner_access on public.growth_objectives for all to authenticated
  using (public.is_business_owner(business_id)) with check (public.is_business_owner(business_id));
drop policy if exists business_owner_access on public.module_specs;
create policy business_owner_access on public.module_specs for all to authenticated
  using (public.is_business_owner(business_id)) with check (public.is_business_owner(business_id));
drop policy if exists business_owner_access on public.site_chat_history;
create policy business_owner_access on public.site_chat_history for all to authenticated
  using (public.is_business_owner(business_id)) with check (public.is_business_owner(business_id));

-- Seats already hold tenant_member_read on these three: the owner, a read.
drop policy if exists business_owner_read on public.connectors;
create policy business_owner_read on public.connectors for select to authenticated
  using (public.is_business_owner(business_id));
drop policy if exists business_owner_read on public.sms_keywords;
create policy business_owner_read on public.sms_keywords for select to authenticated
  using (public.is_business_owner(business_id));
drop policy if exists business_owner_read on public.sms_opt_outs;
create policy business_owner_read on public.sms_opt_outs for select to authenticated
  using (public.is_business_owner(business_id));

-- sms_bindings had no policy but the allow-all one, and Messages lists who
-- texted the keyword from it in the browser: a read for the owner and for an
-- office login, and no write for either (the texting webhook writes it, as
-- the server).
drop policy if exists business_owner_read on public.sms_bindings;
create policy business_owner_read on public.sms_bindings for select to authenticated
  using (public.is_business_owner(business_id));
drop policy if exists tenant_member_read on public.sms_bindings;
create policy tenant_member_read on public.sms_bindings for select to authenticated
  using (public.is_business_member(business_id));

-- ─── 3. Nobody signed out reads these through PostgREST ───────────────
-- The sixteen no browser reads directly. tasks, products, business_expenses
-- and sms_bindings keep their grants on purpose (see the header).
revoke all on public.chief_patterns         from anon;
revoke all on public.connector_action_log   from anon;
revoke all on public.connectors             from anon;
revoke all on public.foundation_documents   from anon;
revoke all on public.foundation_progress    from anon;
revoke all on public.growth_milestones      from anon;
revoke all on public.growth_objectives      from anon;
revoke all on public.marketing_leads        from anon;
revoke all on public.module_specs           from anon;
revoke all on public.practitioner_profiles  from anon;
revoke all on public.site_chat_history      from anon;
revoke all on public.site_content_overrides from anon;
revoke all on public.sms_keywords           from anon;
revoke all on public.sms_opt_outs           from anon;
revoke all on public.workflow_definitions   from anon;
revoke all on public.workflow_runs          from anon;

commit;

notify pgrst, 'reload schema';

-- Check after:
--   -- A. No allow-all policy is left on the twenty. Expect 0 rows.
--   select tablename, policyname, cmd, roles::text
--     from pg_policies
--    where schemaname = 'public'
--      and tablename in ('business_expenses','chief_patterns','connector_action_log','connectors',
--                        'foundation_documents','foundation_progress','growth_milestones','growth_objectives',
--                        'marketing_leads','module_specs','practitioner_profiles','products','site_chat_history',
--                        'site_content_overrides','sms_bindings','sms_keywords','sms_opt_outs','tasks',
--                        'workflow_definitions','workflow_runs')
--      and (btrim(coalesce(qual, '')) = 'true' or btrim(coalesce(with_check, '')) = 'true');
--   -- B. What is left, table by table. Expect exactly:
--   --   business_expenses       business_member_access, ministry_financial_privacy (restrictive), tenant_member_read, tenant_writer_write
--   --   chief_patterns          business_member_access, tenant_member_read
--   --   connector_action_log    (none)
--   --   connectors              business_owner_read, tenant_member_read
--   --   foundation_documents    business_member_access, tenant_member_read, tenant_writer_write
--   --   foundation_progress     business_member_access, tenant_member_read, tenant_writer_write
--   --   growth_milestones       business_owner_access, tenant_member_read, tenant_writer_write
--   --   growth_objectives       business_owner_access, tenant_member_read, tenant_writer_write
--   --   marketing_leads         (none)
--   --   module_specs            business_owner_access, tenant_member_read, tenant_writer_write
--   --   practitioner_profiles   owner_full_access
--   --   products                business_member_access, tenant_member_read, tenant_writer_write
--   --   site_chat_history       business_owner_access, tenant_member_read, tenant_writer_write
--   --   site_content_overrides  business_member_access, tenant_member_read, tenant_writer_write
--   --   sms_bindings            business_owner_read, tenant_member_read
--   --   sms_keywords            business_owner_read, tenant_member_read
--   --   sms_opt_outs            business_owner_read, tenant_member_read
--   --   tasks                   business_member_access, tenant_member_read, tenant_writer_write
--   --   workflow_definitions    (none)
--   --   workflow_runs           (none)
--   select tablename, string_agg(policyname, ', ' order by policyname) as policies
--     from pg_policies
--    where schemaname = 'public'
--      and tablename in ('business_expenses','chief_patterns','connector_action_log','connectors',
--                        'foundation_documents','foundation_progress','growth_milestones','growth_objectives',
--                        'marketing_leads','module_specs','practitioner_profiles','products','site_chat_history',
--                        'site_content_overrides','sms_bindings','sms_keywords','sms_opt_outs','tasks',
--                        'workflow_definitions','workflow_runs')
--    group by tablename order by tablename;
--   -- C. anon reads none of the sixteen. Expect 16 rows, anon_reads false on every one.
--   select t.name, has_table_privilege('anon', to_regclass('public.' || t.name), 'select') as anon_reads
--     from unnest(array['chief_patterns','connector_action_log','connectors','foundation_documents',
--                       'foundation_progress','growth_milestones','growth_objectives','marketing_leads',
--                       'module_specs','practitioner_profiles','site_chat_history','site_content_overrides',
--                       'sms_keywords','sms_opt_outs','workflow_definitions','workflow_runs']) as t(name)
--    order by 1;
--   -- D. In the app, signed in as the owner: Tasks lists, a public site still
--   --    shows its products, Messages still lists who texted the keyword.
--
-- Rollback (REOPENS THE HOLE): supabase/ROLLBACK-2026-11-18-close-allow-all-policies.sql
