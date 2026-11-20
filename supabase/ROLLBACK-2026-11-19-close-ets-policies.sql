-- ROLLBACK-2026-11-19-close-ets-policies.sql
--
-- THIS REOPENS THE HOLE. Run it only if APPLY-2026-11-19-close-ets-policies.sql
-- broke something that cannot wait for a fix. Afterwards anyone holding the
-- public anon key, and any signed-in Solutionist login, can again read,
-- change and delete every Embrace the Shift inquiry, registration,
-- engagement, email, agent note, signature and session row, read every
-- event's virtual link, and any signed-in login can again upload to and
-- delete from the ets-event-files bucket.
--
-- WHAT THIS DOES, in one transaction:
--   1. Drops the 14 policies the apply file made on the ten (ets_owner_all on
--      each, ets_public_read_live_tiers, ets_public_read_live_files,
--      ets_public_send_inquiry, ets_public_register).
--   2. Recreates the 25 policies the apply file dropped, exactly as
--      production had them on 2026-11-19 (all permissive, all TO public),
--      and puts ets_public_read_events back TO public.
--   3. The two count functions run as the caller again, with no search_path
--      of their own (their bodies were never touched).
--   4. ets_event_summary and ets_pending_agent_actions run as their owner
--      again and anon may read them. Only these two, by name: they had no
--      options on production on 2026-11-19 (the apply file's check 10). Any
--      other view the apply file set to run as the caller stays that way (it
--      may have been so before), and stays closed to anon.
--   5. Grants as they were: anon SELECT, INSERT, UPDATE, DELETE on all ten
--      (ets_events whole again, virtual_link included); authenticated
--      TRUNCATE, TRIGGER, REFERENCES on all ten.
--   6. The bucket's insert and delete policies as
--      APPLY-2026-08-09-storage-write-lockdown.sql made them (any signed-in
--      login). "Allow public read" was never touched.
--
-- KEPT: public.ets_registration_confirmation. The site's new build reads the
-- confirmation page through it, and it shows only one registration to
-- whoever holds that registration's id. To drop it as well (only once the
-- site's old build is back), run the commented line at the end.
--
-- Safe to run twice, and after it the apply file can be run again.

begin;
set local lock_timeout = '5s';

-- ─── 1. The apply file's policies ─────────────────────────────────────────
drop policy if exists ets_owner_all on public.ets_events;
drop policy if exists ets_owner_all on public.ets_event_tiers;
drop policy if exists ets_owner_all on public.ets_event_files;
drop policy if exists ets_owner_all on public.ets_registrations;
drop policy if exists ets_owner_all on public.ets_inquiries;
drop policy if exists ets_owner_all on public.ets_engagements;
drop policy if exists ets_owner_all on public.ets_emails;
drop policy if exists ets_owner_all on public.ets_agent_log;
drop policy if exists ets_owner_all on public.ets_signatures;
drop policy if exists ets_owner_all on public.ets_sessions_log;
drop policy if exists ets_public_read_live_tiers on public.ets_event_tiers;
drop policy if exists ets_public_read_live_files on public.ets_event_files;
drop policy if exists ets_public_send_inquiry on public.ets_inquiries;
drop policy if exists ets_public_register on public.ets_registrations;

-- ─── 2. The 25 policies as production had them ────────────────────────────
alter policy ets_public_read_events on public.ets_events to public;

drop policy if exists "Allow all for anon" on public.ets_events;
create policy "Allow all for anon" on public.ets_events for all using (true) with check (true);
drop policy if exists ets_auth_events on public.ets_events;
create policy ets_auth_events on public.ets_events for all using (auth.uid() is not null);

drop policy if exists "Allow all for anon" on public.ets_event_tiers;
create policy "Allow all for anon" on public.ets_event_tiers for all using (true) with check (true);
drop policy if exists ets_auth_tiers on public.ets_event_tiers;
create policy ets_auth_tiers on public.ets_event_tiers for all using (auth.uid() is not null);
drop policy if exists ets_public_read_tiers on public.ets_event_tiers;
create policy ets_public_read_tiers on public.ets_event_tiers for select using (is_visible = true);

drop policy if exists "Allow all for anon" on public.ets_event_files;
create policy "Allow all for anon" on public.ets_event_files for all using (true) with check (true);
drop policy if exists ets_auth_files on public.ets_event_files;
create policy ets_auth_files on public.ets_event_files for all using (auth.uid() is not null);
drop policy if exists ets_public_read_files on public.ets_event_files;
create policy ets_public_read_files on public.ets_event_files for select using (true);

drop policy if exists "Allow all for anon" on public.ets_registrations;
create policy "Allow all for anon" on public.ets_registrations for all using (true) with check (true);
drop policy if exists ets_auth_registrations on public.ets_registrations;
create policy ets_auth_registrations on public.ets_registrations for all using (auth.uid() is not null);
drop policy if exists ets_public_insert_registration on public.ets_registrations;
create policy ets_public_insert_registration on public.ets_registrations for insert with check (true);
drop policy if exists ets_public_read_own_registration on public.ets_registrations;
create policy ets_public_read_own_registration on public.ets_registrations for select using (true);

drop policy if exists ets_auth_inquiries on public.ets_inquiries;
create policy ets_auth_inquiries on public.ets_inquiries for all using (auth.uid() is not null);
drop policy if exists ets_public_insert on public.ets_inquiries;
create policy ets_public_insert on public.ets_inquiries for insert with check (true);
drop policy if exists ets_public_read on public.ets_inquiries;
create policy ets_public_read on public.ets_inquiries for select using (true);

drop policy if exists ets_auth_engagements on public.ets_engagements;
create policy ets_auth_engagements on public.ets_engagements for all using (auth.uid() is not null);
drop policy if exists ets_read_engagements on public.ets_engagements;
create policy ets_read_engagements on public.ets_engagements for select using (true);

drop policy if exists ets_auth_emails on public.ets_emails;
create policy ets_auth_emails on public.ets_emails for all using (auth.uid() is not null);
drop policy if exists ets_read_emails on public.ets_emails;
create policy ets_read_emails on public.ets_emails for select using (true);

drop policy if exists ets_auth_agent_log on public.ets_agent_log;
create policy ets_auth_agent_log on public.ets_agent_log for all using (auth.uid() is not null);
drop policy if exists ets_read_agent_log on public.ets_agent_log;
create policy ets_read_agent_log on public.ets_agent_log for select using (true);

drop policy if exists ets_auth_signatures on public.ets_signatures;
create policy ets_auth_signatures on public.ets_signatures for all using (auth.uid() is not null);
drop policy if exists ets_read_signatures on public.ets_signatures;
create policy ets_read_signatures on public.ets_signatures for select using (true);

drop policy if exists ets_auth_sessions on public.ets_sessions_log;
create policy ets_auth_sessions on public.ets_sessions_log for all using (auth.uid() is not null);
drop policy if exists ets_read_sessions on public.ets_sessions_log;
create policy ets_read_sessions on public.ets_sessions_log for select using (true);

-- ─── 3. The count functions run as the caller again ───────────────────────
alter function public.ets_update_registration_count() security invoker reset search_path;
alter function public.ets_update_tier_sold_count() security invoker reset search_path;

-- ─── 4. Production's two views run as their owner again ───────────────────
-- By name only, and only where they exist. If APPLY-2026-09-01-rls-advisor-
-- errors.sql has been applied since (it sets these same two), leave this
-- section out: they should stay as the caller.
do $$
declare
  v text;
begin
  foreach v in array array['public.ets_event_summary', 'public.ets_pending_agent_actions'] loop
    if to_regclass(v) is not null then
      if current_setting('server_version_num')::int >= 150000 then
        execute format('alter view %s reset (security_invoker)', v);
      end if;
      execute format('grant select on %s to anon', v);
    end if;
  end loop;
end
$$;

-- ─── 5. Grants as they were ───────────────────────────────────────────────
-- REVOKE ALL first takes anon's column grants on ets_events with it.
revoke all on public.ets_events from anon;
grant select, insert, update, delete on public.ets_events, public.ets_event_tiers, public.ets_event_files,
      public.ets_registrations, public.ets_inquiries, public.ets_engagements, public.ets_emails,
      public.ets_agent_log, public.ets_signatures, public.ets_sessions_log to anon;
grant truncate, trigger, references on public.ets_events, public.ets_event_tiers, public.ets_event_files,
      public.ets_registrations, public.ets_inquiries, public.ets_engagements, public.ets_emails,
      public.ets_agent_log, public.ets_signatures, public.ets_sessions_log to authenticated;

-- ─── 6. The bucket as 2026-08-09 left it ──────────────────────────────────
drop policy if exists "ets write: ets-event-files insert" on storage.objects;
create policy "ets write: ets-event-files insert" on storage.objects
  for insert to authenticated with check (bucket_id = 'ets-event-files');
drop policy if exists "ets write: ets-event-files delete" on storage.objects;
create policy "ets write: ets-event-files delete" on storage.objects
  for delete to authenticated using (bucket_id = 'ets-event-files');

-- Only once the site's old build is live again:
-- drop function if exists public.ets_registration_confirmation(text);

commit;
notify pgrst, 'reload schema';
