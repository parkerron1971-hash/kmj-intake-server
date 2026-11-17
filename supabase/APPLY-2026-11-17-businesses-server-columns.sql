-- APPLY-2026-11-17-businesses-server-columns.sql
--
-- The app's logins change only the columns of public.businesses that are the
-- owner's to change. Plans, billing, the Stripe ids, ownership and the
-- server's own flags are the server's (Kevin, 2026-11-17: "top tier, no cut
-- corners").
--
-- Why: production (read 2026-11-17) gives `authenticated` UPDATE on all 30
-- columns of businesses, and RLS lets an owner (owner_full_access) and an
-- office admin (businesses_admin_update) update their own row. So the app's
-- login could PATCH /rest/v1/businesses?id=eq.<its own row> and set:
--   comp_tier            feature_gates.plan_of and access_state honour it:
--                        any plan, free, with no subscription
--   subscription_status, trial_ends_at, current_period_end, cancel_at_period_end
--                        access_state (full / grace / locked)
--   subscription_plan    plan_of, the founding-price checks
--   tier                 the plan mirror the app shows
--   stripe_customer_id, stripe_subscription_id, stripe_account_id
--                        whose billing, whose subscription, and where a
--                        church's giving and a business's payments go
--   owner_id             businesses_admin_update's WITH CHECK asks only
--                        whether the caller is an admin, so an office login
--                        could make itself the owner and take the church
--   in_the_clear(_at)    the public "Business In The Clear" badge
--   is_active            the business cap counts active rows
--   entity_group_id, use_composer, attribution, created_at, id
-- and it could INSERT a business itself, skipping POST /access/businesses/create
-- (the invite gate, the business cap, the paused kinds of practice, the church
-- sample, the birth settings). pg_graphql runs as the same roles, so it was the
-- same hole by another door; this closes both.
--
-- Who writes what (worklog/2026-11-17-businesses-server-columns.md has the
-- whole inventory, from main and module-system on 2026-11-17): the app's
-- logins send name, type, voice_profile and settings (BusinessIdentityEditor,
-- AboutMeReview, VoiceToneEditor, lib/businessSettings and
-- merge_business_settings); the server with the user's login sends settings
-- and voice_profile (Chief in a chat) and settings, brand_kit_history,
-- brand_kit_draft, brand_kit_draft_at and updated_at (brand_engine). From the
-- backend PR that ships this file, foundation_agent writes in_the_clear as the
-- server. No app login inserts a business: every one is made by the server.
--
-- Two layers, for the app's own logins (anon, authenticated) only. The
-- service role and the SQL editor are untouched.
--
--   1. Privileges. REVOKE INSERT, UPDATE on the table from anon and
--      authenticated, and GRANT UPDATE on the nine owner columns to
--      authenticated (owner_columns below). A PATCH or an INSERT that names
--      any other column fails with 42501 before a row is touched; a PATCH is
--      one statement, so a mixed one lands nothing. A column added later is
--      closed to the app until a migration grants it (docs/RLS_MODEL.md,
--      Rule 4): an app write to it fails out loud, never quietly.
--   2. trigger businesses_guard_server_columns, BEFORE INSERT OR UPDATE. For
--      anon and authenticated: an INSERT is refused, and an UPDATE that
--      changes any server column is refused (42501, naming the columns,
--      never their values). A server column sent back unchanged passes. It
--      is the same rule where a grant can't reach it, so a later blanket
--      GRANT (Supabase's dashboard, or a pasted GRANT ALL like the ones the
--      repo's test harnesses use) can't reopen the hole. Same test as the
--      repo's other client guards (businesses_guard_sample,
--      businesses_guard_server_settings): current_user, which a client JWT
--      cannot change. SECURITY INVOKER, reads no table, is no policy:
--      nothing here can recurse (docs/RLS_MODEL.md, the 42P17 rule). It
--      fires second of the four BEFORE triggers on businesses (they fire by
--      name): after businesses_guard_sample, before
--      businesses_guard_server_settings and trg_businesses_updated_at, none
--      of which changes a server column.
--
-- Refused, not kept: nothing the app's logins send names a server column (the
-- inventory), so a write that does is a forgery or a writer nobody knows
-- about. Keeping the old value quietly would tell that writer it had saved,
-- which is the silent loss businesses_guard_server_settings exists to stop;
-- refusing tells it at once. The privileges refuse the same write in the same
-- words (42501), so a widened grant doesn't change what a caller sees. (The
-- settings guard keeps rather than refuses because the app's whole-object
-- settings writes carry stale copies of the server's keys; nothing like that
-- happens with these columns.)
--
-- Columns left to the owner, and why: name, type, settings (its server keys
-- are businesses_guard_server_settings's), voice_profile, cdi_vocabulary (a
-- design vocabulary key derived from the type at birth; nothing gates on it),
-- brand_kit_history, brand_kit_draft, brand_kit_draft_at (the owner's brand
-- work, written by brand_engine with the user's login) and updated_at
-- (trg_businesses_updated_at sets it on every update anyway). `type` stays
-- the owner's: the app's "Kind of business" picker writes it, and the server
-- changes it with only an owner check through POST /business-profile/profile/
-- {id} (business_profiles.business_type, mirrored by sync_profile_type_trigger
-- as the service role), so a guard here would not decide who may change it.
-- What a change of type may unlock (a church relabelled as a business meeting
-- the no-card trial at GET /billing/access, a paused kind of practice chosen
-- after birth) is a server rule; the worklog lists it. is_sample and sample_of
-- are not granted, and businesses_guard_sample already refuses them.
--
-- Apply AFTER the backend PR has deployed: until it does, foundation_agent's
-- write of in_the_clear with the user's login would be refused (it logs a
-- warning and the badge waits for the next phase change). One transaction,
-- lock_timeout 5s, no table rewrite, no data changed, safe to run twice.
--
-- Before (read-only; what the rollback puts back):
--   select grantee, privilege_type from information_schema.role_table_grants
--    where table_schema = 'public' and table_name = 'businesses'
--      and grantee in ('anon', 'authenticated') and privilege_type in ('INSERT', 'UPDATE')
--    order by 1, 2;
--   -- expected: 4 rows (anon INSERT, anon UPDATE, authenticated INSERT, authenticated UPDATE)
begin;

set local lock_timeout = '5s';

-- 1. Privileges. A table-level REVOKE also takes back every column grant of
-- the same kind, so running this twice leaves the same nine grants.
revoke insert, update on public.businesses from anon, authenticated;
grant update (name, type, settings, voice_profile, cdi_vocabulary,
              brand_kit_history, brand_kit_draft, brand_kit_draft_at, updated_at)
  on public.businesses to authenticated;

-- 2. The guard.
create or replace function public.businesses_guard_server_columns() returns trigger
language plpgsql set search_path = public as $$
declare
  changed text[];
begin
  if current_user not in ('anon', 'authenticated') then
    return new;
  end if;
  if tg_op = 'INSERT' then
    raise exception 'A business is made by Solutionist (POST /access/businesses/create), not from the app'
      using errcode = '42501';
  end if;
  changed := array_remove(array[
    case when new.id                     is distinct from old.id                     then 'id' end,
    case when new.owner_id               is distinct from old.owner_id               then 'owner_id' end,
    case when new.created_at             is distinct from old.created_at             then 'created_at' end,
    -- jsonb (APPLY-2026_08_22_signup_attribution.sql); the cast keeps this
    -- working if it were ever json, which has no equality operator.
    case when new.attribution::jsonb     is distinct from old.attribution::jsonb     then 'attribution' end,
    case when new.comp_tier              is distinct from old.comp_tier              then 'comp_tier' end,
    case when new.tier                   is distinct from old.tier                   then 'tier' end,
    case when new.subscription_status    is distinct from old.subscription_status    then 'subscription_status' end,
    case when new.subscription_plan      is distinct from old.subscription_plan      then 'subscription_plan' end,
    case when new.trial_ends_at          is distinct from old.trial_ends_at          then 'trial_ends_at' end,
    case when new.current_period_end     is distinct from old.current_period_end     then 'current_period_end' end,
    case when new.cancel_at_period_end   is distinct from old.cancel_at_period_end   then 'cancel_at_period_end' end,
    case when new.stripe_customer_id     is distinct from old.stripe_customer_id     then 'stripe_customer_id' end,
    case when new.stripe_subscription_id is distinct from old.stripe_subscription_id then 'stripe_subscription_id' end,
    case when new.stripe_account_id      is distinct from old.stripe_account_id      then 'stripe_account_id' end,
    case when new.in_the_clear           is distinct from old.in_the_clear           then 'in_the_clear' end,
    case when new.in_the_clear_at        is distinct from old.in_the_clear_at        then 'in_the_clear_at' end,
    case when new.is_active              is distinct from old.is_active              then 'is_active' end,
    case when new.entity_group_id        is distinct from old.entity_group_id        then 'entity_group_id' end,
    case when new.use_composer           is distinct from old.use_composer           then 'use_composer' end
  ], null);
  if cardinality(changed) > 0 then
    raise exception 'Solutionist keeps % on a business; the app can''t change it', array_to_string(changed, ', ')
      using errcode = '42501';
  end if;
  return new;
end $$;

comment on function public.businesses_guard_server_columns() is
  'The app''s logins (anon, authenticated) can''t make a business or change its server columns: plans, billing, the Stripe ids, ownership, in_the_clear, is_active, entity_group_id, use_composer, attribution, created_at, id. Refused with 42501. The service role and the SQL editor pass. The column grants say the same (APPLY-2026-11-17-businesses-server-columns.sql).';

-- No revoke on the trigger function: a trigger function can't be called
-- directly, and it must fire for the app's own logins, which is its point.
drop trigger if exists businesses_guard_server_columns on public.businesses;
create trigger businesses_guard_server_columns
  before insert or update on public.businesses
  for each row execute function public.businesses_guard_server_columns();

commit;

notify pgrst, 'reload schema';

-- Check:
--   select a.attname,
--          has_column_privilege('authenticated', 'public.businesses'::regclass, a.attname, 'UPDATE') as app_update,
--          has_column_privilege('authenticated', 'public.businesses'::regclass, a.attname, 'INSERT') as app_insert,
--          has_column_privilege('anon', 'public.businesses'::regclass, a.attname, 'UPDATE')
--            or has_column_privilege('anon', 'public.businesses'::regclass, a.attname, 'INSERT') as anon_write
--     from pg_attribute a
--    where a.attrelid = 'public.businesses'::regclass and a.attnum > 0 and not a.attisdropped
--    order by 1;
--   -- 30 rows. app_update true on exactly nine: brand_kit_draft, brand_kit_draft_at,
--   -- brand_kit_history, cdi_vocabulary, name, settings, type, updated_at, voice_profile.
--   -- app_insert and anon_write false on every row.
--   select has_table_privilege('authenticated', 'public.businesses', 'SELECT') as app_select,
--          has_table_privilege('authenticated', 'public.businesses', 'DELETE') as app_delete,
--          has_table_privilege('service_role', 'public.businesses', 'INSERT')
--            and has_table_privilege('service_role', 'public.businesses', 'UPDATE') as server_writes;
--   -- true, true, true (reads, deletes and the server are as they were)
--   select tgname, tgenabled from pg_trigger
--    where tgrelid = 'public.businesses'::regclass and tgname = 'businesses_guard_server_columns';
--   -- 1 row, O
--   select prosecdef from pg_proc where proname = 'businesses_guard_server_columns';
--   -- false
--
-- Rollback (puts back what the "Before" query showed; the server never
-- depended on any of this):
--   begin;
--   drop trigger if exists businesses_guard_server_columns on public.businesses;
--   drop function if exists public.businesses_guard_server_columns();
--   grant insert, update on public.businesses to anon, authenticated;
--   commit;
--   notify pgrst, 'reload schema';
