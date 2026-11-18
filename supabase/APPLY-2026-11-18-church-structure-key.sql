-- The structure draft's key joins the server's keys in businesses.settings
-- (church_structure.py; Kevin 2026-11-18: "standard start first, then giving
-- also consider adding the setup with the church planning strategy").
--
-- A church's structure draft (the standard start: a shape, proposed jobs,
-- each person's proposed login, the gaps) is kept at
-- settings.church_structure, written only by the server
-- (business_settings.merge as the service role). This adds that one key to
-- business_settings_server_keys(), so the guard from
-- supabase/APPLY-2026-11-17-settings-server-keys.sql keeps it: a write from
-- the app's own logins can neither set, change nor drop it, and a whole
-- settings object written back from an older copy no longer loses a draft.
--
-- APPLY AFTER supabase/APPLY-2026-11-17-settings-server-keys.sql. This file
-- only replaces the function that file made (the same 43 keys, plus one);
-- run before it, that file would put the list back to 43.
--
-- The code works before this is applied: the draft is read and written as
-- the server either way. Until it is applied the app's owner or Admin login
-- could write the key itself, which opens nothing (a draft grants nothing,
-- and the server cleans it again on every read), and a stale whole-object
-- settings write from the app could drop a draft, which the pastor would
-- make again.
--
-- One function replaced, no table change, no data rewritten, one
-- transaction, lock_timeout 5s, safe to run twice.
begin;

set local lock_timeout = '5s';

create or replace function public.business_settings_server_keys() returns text[]
language sql immutable parallel safe set search_path = public as $$
  select array[
    -- money, plans and offers
    'founding_church', 'no_card_trial', 'sample_church', 'church_move', 'extra_logins',
    'extra_storage', 'church_texts_bill', 'stripe', 'churchsavvy_only', 'platform_books',
    -- gates the API holds behind the owner, a role or a step-up unlock
    'computer', 'email_domain', 'autonomy', 'content_autonomy', 'automations_paused',
    'church_owner_contact_id',
    -- the server's own records
    'lifecycle_emails', 'chief_insights', 'chief_playbook', 'maturity',
    'church_leaders_note', 'church_team_rollup', 'interview_events', 'church_structure',
    -- settings with their own checked endpoint
    'availability', 'booking_page', 'business_picture', 'church_serving', 'churchsavvy',
    'client_sources', 'concierge', 'doc_defaults', 'giving', 'journeys', 'member_portal',
    'messaging', 'new_here', 'news', 'reading_plan', 'site_prefs', 'sms_replies', 'studio',
    'superbill', 'texting_hours'
  ]::text[]
$$;

revoke all on function public.business_settings_server_keys() from public, anon;
grant execute on function public.business_settings_server_keys() to authenticated, service_role;

commit;

notify pgrst, 'reload schema';

-- Check:
--   select cardinality(public.business_settings_server_keys());                       -- 44
--   select 'church_structure' = any(public.business_settings_server_keys());          -- t
--
-- Rollback (the list as it was; a draft already kept stays where it is, unguarded):
--   run the `create or replace function public.business_settings_server_keys()` statement from
--   supabase/APPLY-2026-11-17-settings-server-keys.sql again.
