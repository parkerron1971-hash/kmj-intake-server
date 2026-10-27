-- Church Areas, step 2: keepers and keys (church_keys.py; Kevin 2026-10-23,
-- "if Pastor look at money another leader is notified and have to recieve a
-- code from that person to get into money"; artifact "Church Areas and
-- Keys"; his picks 2026-10-26: the lock binds the owner too, a tap with a
-- code as the backup, a yes opens for one hour). Two tables, server-only
-- (RLS on, no policies, browser roles revoked); church_keys.py reads and
-- writes them.
--
--   church_keepers     who keeps a guarded area. An area with no keeper has
--                      no lock. A change made by someone who isn't already a
--                      keeper waits 7 days (starts_at / ends_at) unless a
--                      keeper says yes, so nobody can make themselves a
--                      keeper, or take the keepers away, to get in.
--   church_area_keys   one ask for a key and its answer: asked, then open
--                      (until opens_until), declined, expired or closed;
--                      how: a keeper's tap, or the code a keeper read out
--                      (answered_by is null then). The code is kept only as
--                      a hash.
-- Idempotent.
begin;

create table if not exists public.church_keepers(
  business_id uuid not null references public.businesses(id) on delete cascade,
  area text not null check (area in ('giving_money', 'kids_youth', 'people_care')),
  user_id uuid not null,
  added_by uuid,
  added_at timestamptz not null default now(),
  starts_at timestamptz not null default now(),
  ends_at timestamptz,
  primary key (business_id, area, user_id)
);

create table if not exists public.church_area_keys(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  area text not null check (area in ('giving_money', 'kids_youth', 'people_care')),
  user_id uuid not null,
  reason text not null default '' check (char_length(reason) <= 300),
  status text not null default 'asked' check (status in ('asked', 'open', 'declined', 'expired', 'closed')),
  asked_at timestamptz not null default now(),
  answered_by uuid,
  answered_at timestamptz,
  how text check (how in ('tap', 'code')),
  opens_until timestamptz,
  code_hash text,
  code_tries int not null default 0
);

create index if not exists church_area_keys_person
  on public.church_area_keys(business_id, user_id, area, asked_at desc);
create index if not exists church_area_keys_waiting
  on public.church_area_keys(business_id, area, status);

alter table public.church_keepers enable row level security;
alter table public.church_area_keys enable row level security;
revoke all on public.church_keepers from anon, authenticated;
revoke all on public.church_area_keys from anon, authenticated;
grant all on public.church_keepers to service_role;
grant all on public.church_area_keys to service_role;

commit;
