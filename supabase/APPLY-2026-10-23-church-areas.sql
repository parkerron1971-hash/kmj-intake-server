-- The church's own picks on the map (church_areas.py; Kevin 2026-10-23,
-- artifact "Church Areas and Keys", step 1). One table, server-only (RLS
-- on, no policies, browser roles revoked); church_areas.py reads and
-- writes it.
--
--   church_area_places   which area a role (by its key in church_role_defs)
--                        or a Serve team (by its name, lowercased) belongs
--                        to, when the church changed Chief's guess. No row
--                        means the guess stands. It names no contact and
--                        grants nothing in this step: the areas only read
--                        who already reaches them.
-- Idempotent.
begin;

create table if not exists public.church_area_places(
  business_id uuid not null references public.businesses(id) on delete cascade,
  kind text not null check (kind in ('role', 'team')),
  key text not null check (char_length(key) between 1 and 80),
  area text not null check (area in ('worship_media', 'people_care', 'giving_money', 'kids_youth',
                                     'groups_classes', 'messages_safety', 'website_outreach', 'office')),
  updated_at timestamptz not null default now(),
  primary key (business_id, kind, key)
);

alter table public.church_area_places enable row level security;
revoke all on public.church_area_places from anon, authenticated;
grant all on public.church_area_places to service_role;

commit;
