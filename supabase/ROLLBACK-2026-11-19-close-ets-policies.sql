-- ROLLBACK-2026-11-19-close-ets-policies.sql
--
-- THIS REOPENS THE HOLE. Run it only if APPLY-2026-11-19-close-ets-policies.sql
-- broke something that cannot wait for a fix. Afterwards anyone holding the
-- public anon key, and any signed-in Solutionist login, can again read,
-- change and delete every Embrace the Shift inquiry, registration,
-- engagement, email, agent note, signature and session row.
--
-- WHAT THIS DOES, in one transaction:
--   1. Drops the 14 policies the apply file made (ets_owner_all on each of
--      the ten, ets_public_read_live_tiers, ets_public_read_live_files,
--      ets_public_send_inquiry, ets_public_register).
--   2. Recreates the 25 policies the apply file dropped, exactly as
--      production had them on 2026-11-19 (all permissive, all TO public).
--      ets_public_read_events was never dropped and is not touched.
--   3. The two count functions run as the caller again, with no search_path
--      of their own (their bodies were never touched).
--   4. Views that read the ten run as their owner again and anon may read
--      them.
--   5. anon gets SELECT, INSERT, UPDATE, DELETE back on all ten.
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

-- ─── 4. The views run as their owner again ────────────────────────────────
do $$
declare
  v record;
begin
  for v in
    select distinct c.oid::regclass as rel, c.relkind
      from pg_depend d
      join pg_rewrite rw on rw.oid = d.objid
      join pg_class c on c.oid = rw.ev_class
     where d.refobjid in ('public.ets_events'::regclass, 'public.ets_event_tiers'::regclass,
                          'public.ets_event_files'::regclass, 'public.ets_registrations'::regclass,
                          'public.ets_inquiries'::regclass, 'public.ets_engagements'::regclass,
                          'public.ets_emails'::regclass, 'public.ets_agent_log'::regclass,
                          'public.ets_signatures'::regclass, 'public.ets_sessions_log'::regclass)
       and c.oid <> d.refobjid
       and c.relkind in ('v', 'm')
  loop
    if v.relkind = 'v' and current_setting('server_version_num')::int >= 150000 then
      execute format('alter view %s reset (security_invoker)', v.rel);
    elsif v.relkind = 'm' then
      execute format('grant select on %s to authenticated', v.rel);
    end if;
    execute format('grant select on %s to anon', v.rel);
  end loop;
end
$$;

-- ─── 5. anon's grants as they were ────────────────────────────────────────
grant select, insert, update, delete on public.ets_events, public.ets_event_tiers, public.ets_event_files,
      public.ets_registrations, public.ets_inquiries, public.ets_engagements, public.ets_emails,
      public.ets_agent_log, public.ets_signatures, public.ets_sessions_log to anon;

-- Only once the site's old build is live again:
-- drop function if exists public.ets_registration_confirmation(text);

commit;
notify pgrst, 'reload schema';
