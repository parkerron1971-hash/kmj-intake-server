-- ROLLBACK-2026-11-18-close-allow-all-policies.sql
--
-- THIS REOPENS THE HOLE. It puts back the allow-all policies that
-- APPLY-2026-11-18-close-allow-all-policies.sql dropped, after which anyone
-- holding the public anon key (it ships in the app bundle) can again read,
-- change and delete every business's rows in these twenty tables. Run it
-- only to get a broken screen working again while the real fix is made, and
-- re-apply the APPLY file as soon as that is done.
--
-- Before reaching for this, the narrower stops:
--   * a public site lost its products: the server is not on the paired code
--     (public_site reads products as the server). Deploy it; do not roll back.
--   * one table misbehaves: recreate that ONE policy from the list below.
--
-- Each policy is recreated as its original migration wrote it (TO public,
-- FOR ALL, USING true WITH CHECK true). The eight per-command policies on
-- site_chat_history and site_content_overrides were made in the dashboard
-- and no file holds their text; they are recreated in the dashboard
-- template's shape (the read and the delete USING true, the insert WITH
-- CHECK true, the update both), which is what pg_policies showed on
-- 2026-11-18 as far as it was read (each had a literal true).
--
-- The nine scoped policies the APPLY file added are LEFT IN PLACE: they are
-- correct with or without the allow-all ones, and dropping them is the
-- commented block at the bottom.
--
-- One transaction, safe to run twice.
begin;

set local lock_timeout = '5s';

drop policy if exists business_expenses_all on public.business_expenses;
create policy business_expenses_all on public.business_expenses for all using (true) with check (true);
drop policy if exists patterns_all on public.chief_patterns;
create policy patterns_all on public.chief_patterns for all using (true) with check (true);
drop policy if exists cal_all on public.connector_action_log;
create policy cal_all on public.connector_action_log for all using (true) with check (true);
drop policy if exists connectors_all on public.connectors;
create policy connectors_all on public.connectors for all using (true) with check (true);
drop policy if exists foundation_documents_all on public.foundation_documents;
create policy foundation_documents_all on public.foundation_documents for all using (true) with check (true);
drop policy if exists foundation_progress_all on public.foundation_progress;
create policy foundation_progress_all on public.foundation_progress for all using (true) with check (true);
drop policy if exists growth_ms_all on public.growth_milestones;
create policy growth_ms_all on public.growth_milestones for all using (true) with check (true);
drop policy if exists growth_obj_all on public.growth_objectives;
create policy growth_obj_all on public.growth_objectives for all using (true) with check (true);
drop policy if exists marketing_leads_all on public.marketing_leads;
create policy marketing_leads_all on public.marketing_leads for all using (true) with check (true);
drop policy if exists specs_all on public.module_specs;
create policy specs_all on public.module_specs for all using (true) with check (true);
drop policy if exists practitioner_profiles_all on public.practitioner_profiles;
create policy practitioner_profiles_all on public.practitioner_profiles for all using (true) with check (true);
drop policy if exists products_all on public.products;
create policy products_all on public.products for all using (true) with check (true);

drop policy if exists "Allow all deletes on site_chat_history" on public.site_chat_history;
create policy "Allow all deletes on site_chat_history" on public.site_chat_history for delete using (true);
drop policy if exists "Allow all inserts on site_chat_history" on public.site_chat_history;
create policy "Allow all inserts on site_chat_history" on public.site_chat_history for insert with check (true);
drop policy if exists "Allow all reads on site_chat_history" on public.site_chat_history;
create policy "Allow all reads on site_chat_history" on public.site_chat_history for select using (true);
drop policy if exists "Allow all updates on site_chat_history" on public.site_chat_history;
create policy "Allow all updates on site_chat_history" on public.site_chat_history for update using (true) with check (true);

drop policy if exists "Allow all deletes on site_content_overrides" on public.site_content_overrides;
create policy "Allow all deletes on site_content_overrides" on public.site_content_overrides for delete using (true);
drop policy if exists "Allow all inserts on site_content_overrides" on public.site_content_overrides;
create policy "Allow all inserts on site_content_overrides" on public.site_content_overrides for insert with check (true);
drop policy if exists "Allow all reads on site_content_overrides" on public.site_content_overrides;
create policy "Allow all reads on site_content_overrides" on public.site_content_overrides for select using (true);
drop policy if exists "Allow all updates on site_content_overrides" on public.site_content_overrides;
create policy "Allow all updates on site_content_overrides" on public.site_content_overrides for update using (true) with check (true);

drop policy if exists sms_bindings_all on public.sms_bindings;
create policy sms_bindings_all on public.sms_bindings for all using (true) with check (true);
drop policy if exists sms_keywords_all on public.sms_keywords;
create policy sms_keywords_all on public.sms_keywords for all using (true) with check (true);
drop policy if exists sms_opt_outs_all on public.sms_opt_outs;
create policy sms_opt_outs_all on public.sms_opt_outs for all using (true) with check (true);
drop policy if exists tasks_all on public.tasks;
create policy tasks_all on public.tasks for all using (true) with check (true);
drop policy if exists wf_def_all on public.workflow_definitions;
create policy wf_def_all on public.workflow_definitions for all using (true) with check (true);
drop policy if exists wf_run_all on public.workflow_runs;
create policy wf_run_all on public.workflow_runs for all using (true) with check (true);

-- anon's table privileges, as Supabase gives them to a new public table.
grant select, insert, update, delete on public.chief_patterns         to anon;
grant select, insert, update, delete on public.connector_action_log   to anon;
grant select, insert, update, delete on public.connectors             to anon;
grant select, insert, update, delete on public.foundation_documents   to anon;
grant select, insert, update, delete on public.foundation_progress    to anon;
grant select, insert, update, delete on public.growth_milestones      to anon;
grant select, insert, update, delete on public.growth_objectives      to anon;
grant select, insert, update, delete on public.marketing_leads        to anon;
grant select, insert, update, delete on public.module_specs           to anon;
grant select, insert, update, delete on public.practitioner_profiles  to anon;
grant select, insert, update, delete on public.site_chat_history      to anon;
grant select, insert, update, delete on public.site_content_overrides to anon;
grant select, insert, update, delete on public.sms_keywords           to anon;
grant select, insert, update, delete on public.sms_opt_outs           to anon;
grant select, insert, update, delete on public.workflow_definitions   to anon;
grant select, insert, update, delete on public.workflow_runs          to anon;

commit;

notify pgrst, 'reload schema';

-- To also take away the nine scoped policies the APPLY file added (not
-- needed for a rollback; the owner then has less than the owner's staff on
-- these tables as soon as the allow-all ones are dropped again):
--   drop policy if exists business_owner_access on public.growth_milestones;
--   drop policy if exists business_owner_access on public.growth_objectives;
--   drop policy if exists business_owner_access on public.module_specs;
--   drop policy if exists business_owner_access on public.site_chat_history;
--   drop policy if exists business_owner_read on public.connectors;
--   drop policy if exists business_owner_read on public.sms_keywords;
--   drop policy if exists business_owner_read on public.sms_opt_outs;
--   drop policy if exists business_owner_read on public.sms_bindings;
--   drop policy if exists tenant_member_read on public.sms_bindings;
