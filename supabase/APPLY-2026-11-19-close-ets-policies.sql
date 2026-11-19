-- APPLY-2026-11-19-close-ets-policies.sql
--
-- The Embrace the Shift tables (ets_*) are open to anyone. Read from
-- production's catalog on 2026-11-19: RLS is on for all ten, but four carry
-- a PERMISSIVE "Allow all for anon" policy (USING true, every command, TO
-- public), the other six carry a SELECT USING (true) policy, every one of
-- the ten carries an ALL policy USING (auth.uid() IS NOT NULL), and `anon`
-- holds SELECT/INSERT/UPDATE/DELETE on all ten. The anon key ships in the
-- public site's bundle (embracetheshift.live) and in the app's, so anyone
-- holding it could read, change and delete every inquiry, registration,
-- engagement, email, agent note, signature and session row, and ANY signed-in
-- Solutionist login could do the same. None of the ten has a business_id: it
-- is the platform owner's own business data. The same class as
-- APPLY-2026-11-18-close-allow-all-policies.sql, which left these ten for
-- their own pass.
--
-- WHO USES THESE TABLES:
--   * The public site embracetheshift.live (repo ets-web, anon key, nobody
--     signs in): lists published and sold-out events with their tiers and
--     files, inserts an inquiry, inserts a registration, and shows a
--     registration back on its confirmation page.
--   * The Solutionist app's Embrace the Shift pages (only the platform owner
--     uses them), signed in, with the owner's JWT: reads and writes all ten.
--   * Nothing in this backend touches them. Nothing confirms a paid
--     registration either: there is no Stripe webhook for them, so a paid
--     one stays "pending" (an existing gap, not changed here).
--
-- WHAT THIS DOES, in one transaction:
--   0. Refuses to run (and changes nothing) on a database that is not the one
--      this was written for: the owner helper, the defaults of the columns
--      the public must not set, and the triggers on the two tables the public
--      writes to are checked first.
--   1. Drops 25 policies by their exact names: every policy on the ten
--      except ets_public_read_events, which stays as it is.
--   2. The owner: one policy ets_owner_all on each of the ten, FOR ALL TO
--      authenticated, through public.is_platform_owner() (SECURITY DEFINER,
--      the verified JWT's email against the platform owner's).
--   3. The public (TO anon, authenticated):
--        read  ets_events       published or sold out (ets_public_read_events, kept)
--        read  ets_event_tiers  visible, of a published or sold-out event
--        read  ets_event_files  of a published or sold-out event
--        add   ets_inquiries    with none of the internal fields set
--        add   ets_registrations to a published event, on a visible tier of
--              that event, pending (or confirmed when the tier is free), for
--              the tier's price (0 when free), nothing staff-only set
--      and nothing else: no read of an inquiry or a registration, nothing on
--      the five staff tables, no update or delete anywhere.
--   4. ets_registration_confirmation(p_ref): the confirmation page's one way
--      to read a registration back, by its id or its Stripe session id,
--      answering only what that page shows.
--   5. The two count triggers on ets_registrations run as their owner
--      (SECURITY DEFINER, search_path = public), so a registration added by
--      the public still updates the event's and the tier's counts.
--   6. Views that read these tables run as the caller (security_invoker), so
--      they no longer read past the policies, and anon loses them.
--   7. anon's grants: nothing on the five staff tables; SELECT only on
--      events, tiers and files; INSERT only on inquiries and registrations.
--      The policies decide; the grants are belt and braces.
--
-- AFTER IT:
--   anon (the public site): published / sold-out events, their visible
--     tiers and their files; may add an inquiry and a registration; reads a
--     registration only through ets_registration_confirmation.
--   a signed-in login that is not the platform owner: the same as anon.
--   the platform owner, signed in (the app): everything, on all ten.
--   the server (service role): bypasses RLS. Unchanged.
--
-- No policy here can recurse (docs/RLS_MODEL.md, the 42P17 rule): the tiers,
-- files and registration policies read ets_events (and the registration one
-- ets_event_tiers), and no policy on ets_events or ets_event_tiers reads
-- tiers, files or registrations. ets_owner_all reads only the JWT.
--
-- ORDER: DEPLOY THE SITE FIRST. The site's new build (ets-web, branch
-- close-public-reads) inserts without asking for the row back and reads the
-- confirmation through the function; it works before and after this file.
-- The live build does not work after it:
--   * the inquiry form fails with an error on the page ("permission denied
--     for table ets_inquiries"): its INSERT asks for the new row back, which
--     needs a read the public no longer has;
--   * registering fails the same way, for free and paid tiers alike, so
--     nobody can register and nobody is sent to Stripe;
--   * the confirmation page says "Registration Not Found" for everyone.
--   The events list and the event pages keep working either way.
-- The app's realtime hooks (solutionist-studio, branch
-- ets-realtime-signed-in) should be live by then too, before or after the
-- site: they join realtime with the owner's sign-in, which works under the
-- old policies and the new. Without them, joined as anon, the owner's live
-- new-inquiry, engagement, agent and registration alerts go quiet under these
-- policies. The app's pages themselves need no change.
--
-- One transaction, safe to run twice (each policy is dropped by name before
-- it is created; CREATE OR REPLACE for the function; ALTER, REVOKE and GRANT
-- are the same the second time). Nothing but policies, one function, two
-- function attributes, view options and anon's grants is touched; no table is
-- rewritten or scanned, no row is changed. Each DROP/CREATE POLICY takes a
-- brief ACCESS EXCLUSIVE lock on its table (catalog only); lock_timeout makes
-- the file fail cleanly rather than queue behind a long transaction.
--
-- Rollback: supabase/ROLLBACK-2026-11-19-close-ets-policies.sql (REOPENS the
-- hole; it keeps the function, which the new site build reads).
--
-- Check before applying (read-only):
--   -- 1. The policies on the ten. Expect 26 rows: on ets_events "Allow all for
--   --    anon", ets_auth_events, ets_public_read_events; on ets_event_tiers
--   --    "Allow all for anon", ets_auth_tiers, ets_public_read_tiers; on
--   --    ets_event_files "Allow all for anon", ets_auth_files,
--   --    ets_public_read_files; on ets_registrations "Allow all for anon",
--   --    ets_auth_registrations, ets_public_insert_registration,
--   --    ets_public_read_own_registration; on ets_inquiries ets_auth_inquiries,
--   --    ets_public_insert, ets_public_read; and ets_auth_<x> + ets_read_<x> on
--   --    ets_engagements, ets_emails, ets_agent_log, ets_signatures,
--   --    ets_sessions_log (<x> = engagements, emails, agent_log, signatures,
--   --    sessions). Any other row: stop, and add it to this file first.
--   select tablename, policyname, cmd, roles, qual, with_check
--     from pg_policies
--    where schemaname = 'public'
--      and tablename in ('ets_events', 'ets_event_tiers', 'ets_event_files', 'ets_registrations',
--                        'ets_inquiries', 'ets_engagements', 'ets_emails', 'ets_agent_log',
--                        'ets_signatures', 'ets_sessions_log')
--    order by 1, 2;
--
--   -- 2. The columns the new policies and the function read. Expect 43 rows,
--   --    every one present. processed, converted_to_engagement and
--   --    checked_in: boolean, default false or none. lead_score: default
--   --    'warm' or none. processed_at, agent_notes, checked_in_at,
--   --    stripe_session_id, stripe_payment_intent, notes: no default. (The
--   --    file checks the defaults itself and stops if they differ.)
--   select table_name, column_name, data_type, column_default
--     from information_schema.columns
--    where table_schema = 'public'
--      and (table_name, column_name) in (
--        ('ets_events', 'id'), ('ets_events', 'status'), ('ets_events', 'title'),
--        ('ets_events', 'event_date'), ('ets_events', 'start_time'), ('ets_events', 'end_time'),
--        ('ets_events', 'venue_name'), ('ets_events', 'address'), ('ets_events', 'city'),
--        ('ets_events', 'state'), ('ets_events', 'format'), ('ets_events', 'virtual_link'),
--        ('ets_events', 'confirmation_message'), ('ets_events', 'timezone'), ('ets_events', 'cover_image'),
--        ('ets_event_tiers', 'id'), ('ets_event_tiers', 'event_id'), ('ets_event_tiers', 'name'),
--        ('ets_event_tiers', 'price'), ('ets_event_tiers', 'is_free'), ('ets_event_tiers', 'is_visible'),
--        ('ets_event_files', 'event_id'), ('ets_event_files', 'file_url'), ('ets_event_files', 'is_cover'),
--        ('ets_event_files', 'sort_order'),
--        ('ets_registrations', 'id'), ('ets_registrations', 'event_id'), ('ets_registrations', 'tier_id'),
--        ('ets_registrations', 'first_name'), ('ets_registrations', 'last_name'),
--        ('ets_registrations', 'email'),
--        ('ets_registrations', 'status'), ('ets_registrations', 'amount_paid'),
--        ('ets_registrations', 'checked_in'), ('ets_registrations', 'checked_in_at'),
--        ('ets_registrations', 'stripe_session_id'), ('ets_registrations', 'stripe_payment_intent'),
--        ('ets_registrations', 'notes'),
--        ('ets_inquiries', 'processed'), ('ets_inquiries', 'processed_at'), ('ets_inquiries', 'lead_score'),
--        ('ets_inquiries', 'agent_notes'), ('ets_inquiries', 'converted_to_engagement'))
--    order by 1, 2;
--
--   -- 3. The registration statuses and event statuses. Expect the first to
--   --    hold pending and confirmed, the second published and sold_out.
--   select enum_range(null::public.ets_registration_status) as registration_statuses,
--          enum_range(null::public.ets_event_status) as event_statuses;
--
--   -- 4. Triggers on the two tables the public writes to. Expect 2 rows, both
--   --    on ets_registrations: ets_reg_count_trigger and ets_tier_sold_trigger.
--   --    Any other: stop (it would run as anon; the file refuses to run).
--   select tgrelid::regclass as on_table, tgname, tgfoid::regprocedure as runs
--     from pg_trigger
--    where not tgisinternal
--      and tgrelid in ('public.ets_inquiries'::regclass, 'public.ets_registrations'::regclass)
--    order by 1, 2;
--
--   -- 5. The two count functions run as the caller today. Expect 2 rows, both
--   --    security_definer false and settings null.
--   select p.oid::regprocedure as function, p.prosecdef as security_definer, p.proconfig as settings
--     from pg_proc p
--    where p.oid in ('public.ets_update_registration_count()'::regprocedure,
--                    'public.ets_update_tier_sold_count()'::regprocedure);
--
--   -- 6. The owner helper. Expect 1 row: security_definer true, authenticated_may_call true.
--   select p.oid::regprocedure as function, p.prosecdef as security_definer,
--          has_function_privilege('authenticated', p.oid, 'execute') as authenticated_may_call
--     from pg_proc p
--    where p.oid = 'public.is_platform_owner()'::regprocedure;
--
--   -- 7. Views that read the ten. Expect at most ets_pipeline_summary,
--   --    ets_revenue_summary and ets_pending_agent_actions (the frontend's
--   --    supabase/ets-schema.sql makes them); each reads past the policies
--   --    today, as its owner.
--   select distinct v.oid::regclass as view, v.relkind, v.reloptions
--     from pg_depend d
--     join pg_rewrite rw on rw.oid = d.objid
--     join pg_class v on v.oid = rw.ev_class
--    where d.refobjid in ('public.ets_events'::regclass, 'public.ets_event_tiers'::regclass,
--                         'public.ets_event_files'::regclass, 'public.ets_registrations'::regclass,
--                         'public.ets_inquiries'::regclass, 'public.ets_engagements'::regclass,
--                         'public.ets_emails'::regclass, 'public.ets_agent_log'::regclass,
--                         'public.ets_signatures'::regclass, 'public.ets_sessions_log'::regclass)
--      and v.oid <> d.refobjid
--    order by 1;
--
--   -- 8. anon's grants on the ten (and on the views of check 7). Expect
--   --    DELETE, INSERT, SELECT, UPDATE (and perhaps REFERENCES, TRIGGER,
--   --    TRUNCATE) on each of the ten.
--   select table_name, string_agg(privilege_type, ', ' order by privilege_type) as anon_may
--     from information_schema.role_table_grants
--    where grantee = 'anon' and table_schema = 'public' and table_name like 'ets\_%'
--    group by 1
--    order by 1;

begin;
set local lock_timeout = '5s';

-- ─── 0. Refuse to run on a database this was not written for ─────────────
-- Read-only. Each RAISE stops the whole file with nothing changed.
--   * The owner helper must exist: without it the owner's own pages go dark.
--   * The public may add an inquiry or a registration only with the internal
--     fields left alone (section 3). The site never sends them, so the row
--     carries each column's default; if a default here is not the one this
--     file was written for, every public insert would be refused and the
--     forms would break. So the defaults are checked first.
--   * A trigger on ets_inquiries or ets_registrations runs as whoever
--     inserts, which is now anon with almost no grants. The two count
--     triggers are made SECURITY DEFINER below; any other trigger there could
--     fail every public insert, so the file stops instead.
do $$
declare
  r record;
  bad text := '';
begin
  if to_regprocedure('public.is_platform_owner()') is null then
    raise exception 'close-ets-policies: public.is_platform_owner() is missing; nothing was changed';
  end if;

  for r in
    select want.table_name, want.column_name, want.rule, c.data_type, c.column_default
      from (values
        ('ets_inquiries', 'processed', 'false'),
        ('ets_inquiries', 'converted_to_engagement', 'false'),
        ('ets_inquiries', 'processed_at', 'none'),
        ('ets_inquiries', 'agent_notes', 'none'),
        ('ets_inquiries', 'lead_score', 'warm'),
        ('ets_registrations', 'checked_in', 'false'),
        ('ets_registrations', 'checked_in_at', 'none'),
        ('ets_registrations', 'stripe_session_id', 'none'),
        ('ets_registrations', 'stripe_payment_intent', 'none'),
        ('ets_registrations', 'notes', 'none')
      ) as want(table_name, column_name, rule)
      left join information_schema.columns c
        on c.table_schema = 'public' and c.table_name = want.table_name and c.column_name = want.column_name
  loop
    if r.data_type is null then
      bad := bad || format(' %s.%s is missing;', r.table_name, r.column_name);
    elsif r.rule = 'false' and (r.data_type <> 'boolean' or coalesce(r.column_default, 'false') <> 'false') then
      bad := bad || format(' %s.%s is %s default %s (expected boolean, default false or none);',
                           r.table_name, r.column_name, r.data_type, coalesce(r.column_default, 'none'));
    elsif r.rule = 'none' and r.column_default is not null then
      bad := bad || format(' %s.%s has default %s (expected none);', r.table_name, r.column_name, r.column_default);
    elsif r.rule = 'warm' and r.column_default is not null
          and r.column_default !~ '^''warm''(::[a-z_ ."]+)?$' then
      bad := bad || format(' %s.%s has default %s (expected ''warm'' or none);',
                           r.table_name, r.column_name, r.column_default);
    end if;
  end loop;

  for r in
    select tgrelid::regclass::text as on_table, tgname
      from pg_trigger
     where not tgisinternal
       and tgrelid in ('public.ets_inquiries'::regclass, 'public.ets_registrations'::regclass)
       and (tgrelid, tgname) not in (('public.ets_registrations'::regclass, 'ets_reg_count_trigger'),
                                     ('public.ets_registrations'::regclass, 'ets_tier_sold_trigger'))
  loop
    bad := bad || format(' trigger %s on %s is not one this file knows;', r.tgname, r.on_table);
  end loop;

  if bad <> '' then
    raise exception 'close-ets-policies: this database is not the one the file was written for; nothing was changed:%', bad;
  end if;
end
$$;

-- ─── 1. Drop the 25 policies, by name ─────────────────────────────────────
-- Every policy production showed on the ten, except ets_public_read_events
-- (SELECT USING status published or sold_out), which is already what the
-- public should read and stays as it is.
drop policy if exists "Allow all for anon" on public.ets_events;
drop policy if exists ets_auth_events on public.ets_events;

drop policy if exists "Allow all for anon" on public.ets_event_tiers;
drop policy if exists ets_auth_tiers on public.ets_event_tiers;
drop policy if exists ets_public_read_tiers on public.ets_event_tiers;

drop policy if exists "Allow all for anon" on public.ets_event_files;
drop policy if exists ets_auth_files on public.ets_event_files;
drop policy if exists ets_public_read_files on public.ets_event_files;

drop policy if exists "Allow all for anon" on public.ets_registrations;
drop policy if exists ets_auth_registrations on public.ets_registrations;
drop policy if exists ets_public_insert_registration on public.ets_registrations;
drop policy if exists ets_public_read_own_registration on public.ets_registrations;

drop policy if exists ets_auth_inquiries on public.ets_inquiries;
drop policy if exists ets_public_insert on public.ets_inquiries;
drop policy if exists ets_public_read on public.ets_inquiries;

drop policy if exists ets_auth_engagements on public.ets_engagements;
drop policy if exists ets_read_engagements on public.ets_engagements;

drop policy if exists ets_auth_emails on public.ets_emails;
drop policy if exists ets_read_emails on public.ets_emails;

drop policy if exists ets_auth_agent_log on public.ets_agent_log;
drop policy if exists ets_read_agent_log on public.ets_agent_log;

drop policy if exists ets_auth_signatures on public.ets_signatures;
drop policy if exists ets_read_signatures on public.ets_signatures;

drop policy if exists ets_auth_sessions on public.ets_sessions_log;
drop policy if exists ets_read_sessions on public.ets_sessions_log;

-- ─── 2. The platform owner: everything, on all ten ────────────────────────
-- is_platform_owner() is SECURITY DEFINER and reads only the verified JWT's
-- email, so it reads no table and cannot recurse.
drop policy if exists ets_owner_all on public.ets_events;
create policy ets_owner_all on public.ets_events for all to authenticated
  using (public.is_platform_owner()) with check (public.is_platform_owner());

drop policy if exists ets_owner_all on public.ets_event_tiers;
create policy ets_owner_all on public.ets_event_tiers for all to authenticated
  using (public.is_platform_owner()) with check (public.is_platform_owner());

drop policy if exists ets_owner_all on public.ets_event_files;
create policy ets_owner_all on public.ets_event_files for all to authenticated
  using (public.is_platform_owner()) with check (public.is_platform_owner());

drop policy if exists ets_owner_all on public.ets_registrations;
create policy ets_owner_all on public.ets_registrations for all to authenticated
  using (public.is_platform_owner()) with check (public.is_platform_owner());

drop policy if exists ets_owner_all on public.ets_inquiries;
create policy ets_owner_all on public.ets_inquiries for all to authenticated
  using (public.is_platform_owner()) with check (public.is_platform_owner());

drop policy if exists ets_owner_all on public.ets_engagements;
create policy ets_owner_all on public.ets_engagements for all to authenticated
  using (public.is_platform_owner()) with check (public.is_platform_owner());

drop policy if exists ets_owner_all on public.ets_emails;
create policy ets_owner_all on public.ets_emails for all to authenticated
  using (public.is_platform_owner()) with check (public.is_platform_owner());

drop policy if exists ets_owner_all on public.ets_agent_log;
create policy ets_owner_all on public.ets_agent_log for all to authenticated
  using (public.is_platform_owner()) with check (public.is_platform_owner());

drop policy if exists ets_owner_all on public.ets_signatures;
create policy ets_owner_all on public.ets_signatures for all to authenticated
  using (public.is_platform_owner()) with check (public.is_platform_owner());

drop policy if exists ets_owner_all on public.ets_sessions_log;
create policy ets_owner_all on public.ets_sessions_log for all to authenticated
  using (public.is_platform_owner()) with check (public.is_platform_owner());

-- ─── 3. The public site ───────────────────────────────────────────────────
-- Events: ets_public_read_events (kept, above). Tiers and files only of an
-- event the public can see. These read ets_events, whose own policies read
-- no other table, so there is no loop.
drop policy if exists ets_public_read_live_tiers on public.ets_event_tiers;
create policy ets_public_read_live_tiers on public.ets_event_tiers for select to anon, authenticated
  using (
    ets_event_tiers.is_visible is true
    and exists (select 1 from public.ets_events e
                 where e.id = ets_event_tiers.event_id
                   and e.status in ('published', 'sold_out'))
  );

drop policy if exists ets_public_read_live_files on public.ets_event_files;
create policy ets_public_read_live_files on public.ets_event_files for select to anon, authenticated
  using (
    exists (select 1 from public.ets_events e
             where e.id = ets_event_files.event_id
               and e.status in ('published', 'sold_out'))
  );

-- Inquiries: the form sends contact_name, organization_name, email, phone,
-- package_interest, message and org_type, with an id it made itself. The
-- fields the owner's pipeline fills in stay at their defaults.
drop policy if exists ets_public_send_inquiry on public.ets_inquiries;
create policy ets_public_send_inquiry on public.ets_inquiries for insert to anon, authenticated
  with check (
    ets_inquiries.processed is not true
    and ets_inquiries.processed_at is null
    and ets_inquiries.agent_notes is null
    and (ets_inquiries.lead_score is null or ets_inquiries.lead_score::text = 'warm')
    and ets_inquiries.converted_to_engagement is not true
  );

-- Registrations: the form sends event_id, tier_id, first_name, last_name,
-- email, phone, organization, its own id, status 'confirmed' with
-- amount_paid 0 when the tier is free (is_free, or price 0), else 'pending'
-- with amount_paid = the tier's price, and then sends a paid one to Stripe.
-- The row must say exactly that; nobody but the owner marks one paid,
-- checked in, or attached to a Stripe session. Every column is named with
-- its table: an unqualified event_id inside the subquery would be the
-- tier's. The subquery reads events and tiers through their own policies
-- (published, visible), which read no registration.
drop policy if exists ets_public_register on public.ets_registrations;
create policy ets_public_register on public.ets_registrations for insert to anon, authenticated
  with check (
    exists (
      select 1
        from public.ets_events e
        join public.ets_event_tiers t on t.event_id = e.id
       where e.id = ets_registrations.event_id
         and e.status = 'published'
         and t.id = ets_registrations.tier_id
         and t.is_visible is true
         and (ets_registrations.status = 'pending'
              or (ets_registrations.status = 'confirmed' and (t.is_free is true or t.price = 0)))
         and (case when t.is_free is true or t.price = 0
                   then coalesce(ets_registrations.amount_paid, 0) = 0
                   else ets_registrations.amount_paid = t.price
              end)
    )
    and ets_registrations.checked_in is not true
    and ets_registrations.checked_in_at is null
    and ets_registrations.stripe_session_id is null
    and ets_registrations.stripe_payment_intent is null
    and ets_registrations.notes is null
  );

-- ─── 4. The confirmation page's one read ──────────────────────────────────
-- The registrant comes back to /events/<slug>/confirmation?reg=<id> (or
-- ?session_id=<Stripe session id>) and the page shows the registration. The
-- public can no longer read the table, so the page asks this function. It
-- finds ONE registration: by id (the reference must be a uuid's own text, so
-- the primary key answers; the CASE keeps anything else from being cast), or
-- else by Stripe session id when exactly one registration has it. Never a
-- pattern match; an empty or over-long reference is no registration. It
-- answers what the page shows and nothing more: name, email (the page shows
-- it back: "A confirmation has been sent to ..."), status, amount, the id
-- (the reference number), the event's details, the files (for the cover
-- picture), the tier's name and price. Not the phone, organization, notes,
-- check-in or Stripe fields. The event's virtual link only once the
-- registration is confirmed, as the page shows it: a pending (unpaid) one
-- never carries it. Null when there is no such registration.
-- SQL, not plpgsql, so a wrong column name fails this file instead of the
-- page.
create or replace function public.ets_registration_confirmation(p_ref text)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  with found as (
    select coalesce(
             (select r.id
                from ets_registrations r
               where r.id = case when p_ref ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                                 then p_ref::uuid end),
             (select (array_agg(r.id))[1]
                from ets_registrations r
               where r.stripe_session_id = p_ref
              having count(*) = 1)
           ) as id
     where p_ref is not null
       and char_length(p_ref) between 1 and 200
  )
  select jsonb_build_object(
           'id', reg.id,
           'first_name', reg.first_name,
           'last_name', reg.last_name,
           'email', reg.email,
           'status', reg.status,
           'amount_paid', reg.amount_paid,
           'ets_events', case when e.id is null then null else jsonb_build_object(
             'title', e.title,
             'event_date', e.event_date,
             'start_time', e.start_time,
             'end_time', e.end_time,
             'venue_name', e.venue_name,
             'address', e.address,
             'city', e.city,
             'state', e.state,
             'format', e.format,
             'virtual_link', case when reg.status = 'confirmed' then e.virtual_link end,
             'confirmation_message', e.confirmation_message,
             'timezone', e.timezone,
             'cover_image', e.cover_image,
             'ets_event_files', coalesce(
               (select jsonb_agg(jsonb_build_object('file_url', f.file_url, 'is_cover', f.is_cover)
                                 order by f.sort_order, f.file_url)
                  from ets_event_files f
                 where f.event_id = e.id),
               '[]'::jsonb)
           ) end,
           'ets_event_tiers', case when t.id is null then null else jsonb_build_object(
             'name', t.name,
             'price', t.price
           ) end
         )
    from found
    join ets_registrations reg on reg.id = found.id
    left join ets_events e on e.id = reg.event_id
    left join ets_event_tiers t on t.id = reg.tier_id
$$;

revoke all on function public.ets_registration_confirmation(text) from public;
grant execute on function public.ets_registration_confirmation(text) to anon, authenticated;

-- ─── 5. The count triggers run as their owner ─────────────────────────────
-- ets_reg_count_trigger and ets_tier_sold_trigger update
-- ets_events.registrations_count and ets_event_tiers.sold_count when a
-- registration is added or changed. They ran as whoever inserted; the public
-- can no longer read registrations or update events and tiers, so they
-- would fail (or count nothing) on every registration from the site. Their
-- bodies are not touched, only who they run as, with search_path pinned so
-- their unqualified table names can only mean public's.
alter function public.ets_update_registration_count() security definer set search_path = public;
alter function public.ets_update_tier_sold_count() security definer set search_path = public;

-- ─── 6. Views that read the ten run as the caller ─────────────────────────
-- A view runs as its owner unless it says otherwise, so the frontend's
-- ets_pipeline_summary, ets_revenue_summary and ets_pending_agent_actions
-- (engagement totals and revenue, the agent's pending actions with inquiry
-- and engagement contact names) read past every policy above, and anon may
-- read them. Each view (or materialized view) that reads one of the ten is
-- set to run as the caller (Postgres 15 and later), so the owner still reads
-- it whole and everyone else reads only what the policies give them, and
-- anon loses it. No code reads these views; none is dropped.
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
      execute format('alter view %s set (security_invoker = true)', v.rel);
    elsif v.relkind = 'm' then
      -- A materialized view holds its rows; only the server should read it.
      execute format('revoke all on %s from authenticated', v.rel);
    end if;
    execute format('revoke all on %s from anon', v.rel);
  end loop;
end
$$;

-- ─── 7. anon's grants ─────────────────────────────────────────────────────
-- Nothing on the five staff tables. SELECT only where the public reads,
-- INSERT only where it adds. REVOKE ALL then GRANT, so the end state is the
-- same whatever anon held before (on Postgres 17 that includes MAINTAIN).
-- authenticated keeps its grants: the policies above decide for it.
revoke all on public.ets_engagements, public.ets_emails, public.ets_agent_log,
              public.ets_signatures, public.ets_sessions_log from anon;
revoke all on public.ets_events, public.ets_event_tiers, public.ets_event_files,
              public.ets_inquiries, public.ets_registrations from anon;
grant select on public.ets_events, public.ets_event_tiers, public.ets_event_files to anon;
grant insert on public.ets_inquiries, public.ets_registrations to anon;

commit;
notify pgrst, 'reload schema';

-- Check after (read-only):
--   -- 1. Expect exactly 15 rows: ets_owner_all on each of the ten (ALL,
--   --    {authenticated}); ets_public_read_events (SELECT, {public});
--   --    ets_public_read_live_tiers, ets_public_read_live_files (SELECT),
--   --    ets_public_send_inquiry, ets_public_register (INSERT), each
--   --    {anon,authenticated}.
--   select tablename, policyname, cmd, roles
--     from pg_policies
--    where schemaname = 'public' and tablename like 'ets\_%'
--    order by 1, 2;
--
--   -- 2. No policy on the ten is a literal true or a bare "signed in". Expect 0.
--   select count(*) as open_policies
--     from pg_policies
--    where schemaname = 'public' and tablename like 'ets\_%'
--      and (qual = 'true' or with_check = 'true' or qual ilike '%auth.uid() IS NOT NULL%'
--           or with_check ilike '%auth.uid() IS NOT NULL%');
--
--   -- 3. anon's grants. Expect 5 rows: ets_event_files, ets_event_tiers,
--   --    ets_events SELECT; ets_inquiries, ets_registrations INSERT.
--   select table_name, string_agg(privilege_type, ', ' order by privilege_type) as anon_may
--     from information_schema.role_table_grants
--    where grantee = 'anon' and table_schema = 'public' and table_name like 'ets\_%'
--    group by 1
--    order by 1;
--
--   -- 4. The functions. Expect 3 rows, each security_definer true and
--   --    settings {search_path=public}; anon_may_call true for
--   --    ets_registration_confirmation (a trigger function cannot be called
--   --    on its own, whatever its grant says).
--   select p.oid::regprocedure as function, p.prosecdef as security_definer, p.proconfig as settings,
--          has_function_privilege('anon', p.oid, 'execute') as anon_may_call
--     from pg_proc p
--    where p.oid in ('public.ets_update_registration_count()'::regprocedure,
--                    'public.ets_update_tier_sold_count()'::regprocedure,
--                    'public.ets_registration_confirmation(text)'::regprocedure)
--    order by 1;
--
--   -- 5. The views (if any). Expect each with reloptions {security_invoker=true}
--   --    and anon_may_read false.
--   select c.oid::regclass as view, c.reloptions,
--          has_table_privilege('anon', c.oid, 'select') as anon_may_read
--     from pg_class c join pg_namespace n on n.oid = c.relnamespace
--    where n.nspname = 'public' and c.relkind in ('v', 'm') and c.relname like 'ets\_%'
--    order by 1;
--
--   -- 6. The function answers, without showing a row. Expect empty_ref true,
--   --    and finds_one true (or null when there is no registration yet).
--   select public.ets_registration_confirmation('') is null as empty_ref,
--          (select public.ets_registration_confirmation(r.id::text) ->> 'id' = r.id::text
--             from public.ets_registrations r limit 1) as finds_one;
