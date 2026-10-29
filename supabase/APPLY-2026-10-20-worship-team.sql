-- Who does what in a church's ChurchSavvy (design canvas TXrKfJhDkPsXfSsQjhdeoq,
-- board 30 "Team and roles"; Kevin 2026-10-20: "these are a go"). One table,
-- server-only (RLS on, no policies, browser roles revoked); worship_team.py
-- reads it on every worship route.
--
--   worship_team   one person on a church's Sunday team: their name, the
--                  email the invite went to (if any), their parts (planner,
--                  worship, booth, admin) and where the invite stands.
--                  `token` is the invite link's key; it opens nothing but
--                  joining. A volunteer is deliberately NOT a business_users
--                  seat: a seat reads the whole business through
--                  is_business_member (its people, its giving, its books).
-- Idempotent.
begin;

create table if not exists public.worship_team(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  user_id uuid references auth.users(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 80),
  email text check (email is null or char_length(email) <= 254),
  roles text[] not null check (cardinality(roles) between 1 and 4
                               and roles <@ array['planner', 'worship', 'booth', 'admin']::text[]),
  status text not null default 'invited' check (status in ('invited', 'active', 'removed')),
  token uuid not null default gen_random_uuid(),
  invited_by uuid,
  invited_at timestamptz not null default now(),
  joined_at timestamptz,
  removed_at timestamptz,
  check (status <> 'active' or user_id is not null)
);
create unique index if not exists worship_team_token on public.worship_team (token);
create unique index if not exists worship_team_one_each on public.worship_team (business_id, user_id)
  where status = 'active';
create index if not exists worship_team_by_church on public.worship_team (business_id, status, invited_at);
create index if not exists worship_team_by_person on public.worship_team (user_id, status);

alter table public.worship_team enable row level security;
revoke all on public.worship_team from anon, authenticated;
grant all on public.worship_team to service_role;

commit;
