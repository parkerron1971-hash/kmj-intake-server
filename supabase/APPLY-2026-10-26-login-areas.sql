-- APPLY-2026-10-26-login-areas.sql
--
-- Who sees what (Kevin, 2026-10-26; canvas 99aFvCSRXU1x9pmqUcncoP): a
-- church's office login sees only the areas it works in. business_users.areas
-- holds the church's own pick, from the eight areas in church_areas.AREAS.
-- Null means no pick: the login is shown Chief's guess from the roles and
-- teams its person holds, or the whole church, as every login was before.
-- The owner and admins always see everything, whatever this says.
--
-- This shapes what the app shows. It grants and walls nothing: every
-- router still checks its own role. The walls are steps 2 and 3 of
-- Church Areas and Keys.
--
-- Additive and safe to run twice. The code reads it on its own and treats
-- a failed read as no pick, so this can go in before or after it deploys;
-- picking a login's areas answers "didn't save" until it's applied.

alter table public.business_users
  add column if not exists areas text[];

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'business_users_areas_known') then
    alter table public.business_users
      add constraint business_users_areas_known
      check (areas is null or (cardinality(areas) between 1 and 8 and areas <@ array[
        'worship_media', 'people_care', 'giving_money', 'kids_youth', 'groups_classes',
        'messages_safety', 'website_outreach', 'office']::text[]));
  end if;
end $$;

comment on column public.business_users.areas is
  'Who sees what (church_areas.py): the areas a church office login works in, picked by the church. Null = Chief''s guess or the whole church. Shapes the app; grants nothing.';
