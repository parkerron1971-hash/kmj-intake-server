-- APPLY-2026-11-17-settings-server-keys.sql
--
-- The server's keys in businesses.settings stay the server's, and a write
-- touches only the keys it names (business_settings.py; Kevin, 2026-11-16:
-- "top tier, no cut corners").
--
-- Why: the first paying church's founding place (settings.founding_church,
-- written when its first payment landed) was gone two hours later. Every
-- writer of this column read the whole object, changed one key and wrote the
-- whole object back, and one of them wrote back a copy read before the
-- payment. The app does it from the copy it loaded at sign-in (one write per
-- room a young business opens, RoomOrientationStrip), and so do about eighty
-- server paths. The reverse was a hole: an owner or admin may UPDATE their
-- own businesses row through RLS (businesses_admin_update), so the app's
-- login could write the founding place, seats, a trial marker or Chief's
-- spending limits, or drop churchsavvy_only and open everything.
--
--   business_settings_server_keys()   the keys only the server writes (the
--                    same list as business_settings.SERVER_KEYS; a test pins
--                    them equal). IMMUTABLE, reads nothing.
--   business_settings_birth_keys()    the ones the app may set when it makes
--                    a business and never after (churchsavvy_only).
--   trigger businesses_guard_server_settings   BEFORE INSERT OR UPDATE OF
--                    settings. For the app's own logins (anon, authenticated)
--                    only: an UPDATE keeps every server key exactly as it was
--                    (set, changed or dropped, the old value stays) and lets
--                    every other key land as sent; an INSERT leaves out every
--                    server key but the birth keys. The service role and the
--                    SQL editor are not held. Same test as the repo's other
--                    client guards (businesses_guard_sample,
--                    protect_gift_classification): current_user, which a
--                    client JWT cannot change. SECURITY INVOKER, reads no
--                    table, is no policy: nothing here can recurse
--                    (docs/RLS_MODEL.md, the 42P17 rule). It keeps rather than
--                    refuses, because the app's whole-object writes carry
--                    stale copies of these keys today, and refusing would
--                    break every one of them.
--   business_settings_merge_at(doc, under, set, drop)   the merge, pure:
--                    at the object `under` points to (made when missing),
--                    remove `drop`, lay `set` over it.
--   merge_business_settings(p_business, p_set, p_drop, p_under)   one UPDATE:
--                    settings = merge_at(settings, p_under, p_set, p_drop),
--                    returning the settings after it (null: no row this caller
--                    may change). SECURITY INVOKER, so RLS and the guard still
--                    apply to the app's logins; for them a key the server owns
--                    is refused out loud (42501) rather than quietly kept.
--                    Executable by authenticated and service_role only.
--
-- Additive: functions and a trigger, no table change, no data rewritten, one
-- transaction, lock_timeout 5s, safe to run twice. The code works before it
-- (business_settings.merge falls back to a fresh read and a whole write and
-- prints that it did), so it can be applied any time after the backend PR.
begin;

set local lock_timeout = '5s';

create or replace function public.business_settings_server_keys() returns text[]
language sql immutable parallel safe set search_path = public as $$
  select array[
    -- money, plans and offers
    'founding_church', 'no_card_trial', 'sample_church', 'church_move', 'extra_logins',
    'church_texts_bill', 'stripe', 'churchsavvy_only', 'platform_books',
    -- gates the API holds behind the owner, a role or a step-up unlock
    'computer', 'email_domain', 'autonomy', 'content_autonomy', 'automations_paused',
    'church_owner_contact_id',
    -- the server's own records
    'lifecycle_emails', 'chief_insights', 'chief_playbook', 'maturity',
    'church_leaders_note', 'church_team_rollup', 'interview_events',
    -- settings with their own checked endpoint
    'availability', 'booking_page', 'business_picture', 'church_serving', 'churchsavvy',
    'client_sources', 'concierge', 'doc_defaults', 'giving', 'journeys', 'member_portal',
    'messaging', 'new_here', 'news', 'reading_plan', 'site_prefs', 'sms_replies', 'studio',
    'superbill', 'texting_hours'
  ]::text[]
$$;

create or replace function public.business_settings_birth_keys() returns text[]
language sql immutable parallel safe set search_path = public as $$
  select array['churchsavvy_only']::text[]
$$;

comment on function public.business_settings_server_keys() is
  'The keys of businesses.settings only the server writes (business_settings.SERVER_KEYS). The app''s logins can''t set, change or drop them (trigger businesses_guard_server_settings).';
comment on function public.business_settings_birth_keys() is
  'Server keys the app may set when it makes a business, never after (business_settings.BIRTH_KEYS).';

create or replace function public.businesses_guard_server_settings() returns trigger
language plpgsql set search_path = public as $$
declare
  k text;
  incoming jsonb;
  kept jsonb := '{}'::jsonb;
begin
  if current_user not in ('anon', 'authenticated') then
    return new;
  end if;
  if tg_op = 'UPDATE' and new.settings is not distinct from old.settings then
    return new;
  end if;
  incoming := case when jsonb_typeof(new.settings) = 'object' then new.settings else '{}'::jsonb end;
  if tg_op = 'INSERT' then
    foreach k in array public.business_settings_server_keys() loop
      if not (k = any (public.business_settings_birth_keys())) then
        incoming := incoming - k;
      end if;
    end loop;
    new.settings := incoming;
    return new;
  end if;
  if jsonb_typeof(old.settings) = 'object' then
    foreach k in array public.business_settings_server_keys() loop
      if old.settings ? k then
        kept := kept || jsonb_build_object(k, old.settings -> k);
      end if;
    end loop;
  end if;
  new.settings := (incoming - public.business_settings_server_keys()) || kept;
  return new;
end $$;

-- No revoke on the trigger function: a trigger function can't be called
-- directly, and it must fire for the app's own logins, which is its point.
drop trigger if exists businesses_guard_server_settings on public.businesses;
create trigger businesses_guard_server_settings
  before insert or update of settings on public.businesses
  for each row execute function public.businesses_guard_server_settings();

create or replace function public.business_settings_merge_at(
  p_doc jsonb, p_under text[], p_set jsonb, p_drop text[]
) returns jsonb
language plpgsql immutable set search_path = public as $$
declare
  doc jsonb := case when jsonb_typeof(p_doc) = 'object' then p_doc else '{}'::jsonb end;
begin
  if coalesce(cardinality(p_under), 0) = 0 then
    return (doc - coalesce(p_drop, '{}'::text[])) || coalesce(p_set, '{}'::jsonb);
  end if;
  return doc || jsonb_build_object(p_under[1],
    public.business_settings_merge_at(doc -> p_under[1], p_under[2:], p_set, p_drop));
end $$;

create or replace function public.merge_business_settings(
  p_business uuid,
  p_set jsonb default '{}'::jsonb,
  p_drop text[] default '{}'::text[],
  p_under text[] default '{}'::text[]
) returns jsonb
language plpgsql security invoker set search_path = public as $$
declare
  touched text[];
  result jsonb;
begin
  p_set := coalesce(p_set, '{}'::jsonb);
  p_drop := coalesce(p_drop, '{}'::text[]);
  p_under := coalesce(p_under, '{}'::text[]);
  if jsonb_typeof(p_set) <> 'object' then
    raise exception 'p_set must be a JSON object' using errcode = '22023';
  end if;
  if current_user in ('anon', 'authenticated') then
    touched := case when cardinality(p_under) > 0 then array[p_under[1]]
                    else array(select jsonb_object_keys(p_set)) || p_drop end;
    if touched && public.business_settings_server_keys() then
      raise exception 'That setting is kept by Solutionist' using errcode = '42501';
    end if;
  end if;
  update public.businesses
     set settings = public.business_settings_merge_at(settings, p_under, p_set, p_drop)
   where id = p_business
  returning settings into result;
  return result;
end $$;

comment on function public.merge_business_settings(uuid, jsonb, text[], text[]) is
  'Write some keys of one business''s settings and no other, in one UPDATE: settings = (settings - p_drop) || p_set, inside the object p_under names when given. Returns the settings after it; null when no row this caller may change. RLS and businesses_guard_server_settings apply to the app''s logins, and a server key is refused for them.';

revoke all on function public.business_settings_merge_at(jsonb, text[], jsonb, text[]) from public, anon;
grant execute on function public.business_settings_merge_at(jsonb, text[], jsonb, text[]) to authenticated, service_role;
revoke all on function public.merge_business_settings(uuid, jsonb, text[], text[]) from public, anon;
grant execute on function public.merge_business_settings(uuid, jsonb, text[], text[]) to authenticated, service_role;
revoke all on function public.business_settings_server_keys() from public, anon;
grant execute on function public.business_settings_server_keys() to authenticated, service_role;
revoke all on function public.business_settings_birth_keys() from public, anon;
grant execute on function public.business_settings_birth_keys() to authenticated, service_role;

commit;

notify pgrst, 'reload schema';

-- Check:
--   select tgname, tgenabled from pg_trigger
--    where tgrelid = 'public.businesses'::regclass and tgname = 'businesses_guard_server_settings';
--   -- 1 row, O
--   select cardinality(public.business_settings_server_keys());                -- 42
--   select proname, prosecdef from pg_proc where proname in
--     ('merge_business_settings', 'business_settings_merge_at', 'businesses_guard_server_settings',
--      'business_settings_server_keys', 'business_settings_birth_keys') order by 1;
--   -- 5 rows, prosecdef false on every one
--   select grantee, privilege_type from information_schema.routine_privileges
--    where routine_name = 'merge_business_settings' and grantee in ('anon', 'authenticated', 'service_role')
--    order by 1;
--   -- 2 rows: authenticated EXECUTE, service_role EXECUTE
--   select public.business_settings_merge_at('{"a":1,"b":{"x":1}}', '{b}', '{"y":2}', '{x}');
--   -- {"a": 1, "b": {"y": 2}}
--
-- Rollback (the server keeps working: business_settings.merge falls back to a
-- fresh read and a whole write when the function is gone):
--   drop trigger if exists businesses_guard_server_settings on public.businesses;
--   drop function if exists public.businesses_guard_server_settings();
--   drop function if exists public.merge_business_settings(uuid, jsonb, text[], text[]);
--   drop function if exists public.business_settings_merge_at(jsonb, text[], jsonb, text[]);
--   drop function if exists public.business_settings_birth_keys();
--   drop function if exists public.business_settings_server_keys();
--   notify pgrst, 'reload schema';
