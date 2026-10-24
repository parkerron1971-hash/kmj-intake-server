-- ChurchSavvy Planning, step 4: one order of service for every team (design
-- canvas Ct88v7pxpq5a4PGYX3MuQQ, board 3 "Order of service"; Kevin
-- 2026-10-23: "This is a good build. i agree with your plan"). Server-only,
-- like the rest of serve_* (sunday_order.py reads and writes it).
--
--   serve_notes   a note on one item of one service for one team ("Bridge
--                 twice, then a soft chorus" for Worship), or for everyone
--                 serving that day (team 'all'). The items themselves stay in
--                 worship_services.items, the one plan ChurchSavvy reads for
--                 the slides; these notes live beside it so a save in
--                 ChurchSavvy never overwrites a team's note. A note on an
--                 item that was taken out of the plan just isn't shown.
-- Idempotent.
begin;

create table if not exists public.serve_notes(
  business_id uuid not null references public.businesses(id) on delete cascade,
  service_id uuid not null references public.worship_services(id) on delete cascade,
  item_id text not null check (item_id ~ '^[a-z0-9-]{1,24}$'),
  team text not null check (team = 'all' or team ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  note text not null check (char_length(note) between 1 and 300),
  updated_by text not null default '' check (char_length(updated_by) <= 80),
  updated_at timestamptz not null default now(),
  primary key (service_id, item_id, team)
);
create index if not exists serve_notes_by_church on public.serve_notes (business_id, service_id);

-- A note stays inside one church: its service is that church's, and a team
-- note is for one of that church's Sunday teams.
create or replace function public.serve_notes_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.worship_services s
                 where s.id = new.service_id and s.business_id = new.business_id) then
    raise exception 'That service is not in this business';
  end if;
  -- (A trigger runs before the table's checks: never cast what isn't an id.)
  if new.team <> 'all' then
    if new.team !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' then
      raise exception 'That team is not in this business';
    end if;
    if not exists (select 1 from public.serve_teams t
                   where t.group_id = new.team::uuid and t.business_id = new.business_id) then
      raise exception 'That team is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.serve_notes_same_business() from public, anon, authenticated;

drop trigger if exists serve_notes_same_business on public.serve_notes;
create trigger serve_notes_same_business before insert or update on public.serve_notes
  for each row execute function public.serve_notes_same_business();
alter table public.serve_notes enable row level security;
revoke all on public.serve_notes from anon, authenticated;
grant all on public.serve_notes to service_role;

commit;
