-- ChurchSavvy Planning, the member's side (design canvas Ct88v7pxpq5a4PGYX3MuQQ,
-- boards 7 "The ask" and 8 "My serving"; Kevin 2026-10-23: "This is a good
-- build. i agree with your plan"). Server-only, like the office's tables
-- (APPLY-2026-10-23-sunday-planning.sql).
--
--   serve_prefs                 how often a member would like to serve: once a
--                               month, twice, or every week they can. A wish
--                               the office sees, not a rule.
--   serve_assignments.swap_to   someone they asked to cover a Sunday they
--                               said yes to. They stay on until that person
--                               says yes, so the place is never empty.
--   serve_assignments.swap_asked_at   when they asked.
-- Idempotent.
begin;

create table if not exists public.serve_prefs(
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  often text not null check (often in ('one', 'two', 'every')),
  updated_at timestamptz not null default now(),
  primary key (business_id, contact_id)
);

alter table public.serve_assignments add column if not exists swap_to uuid references public.contacts(id) on delete set null;
alter table public.serve_assignments add column if not exists swap_asked_at timestamptz;
create index if not exists serve_assignments_swap_to on public.serve_assignments (swap_to) where swap_to is not null;

-- The same one-church check as before, now also for the person asked to
-- cover and for serve_prefs. Each check is nested under its own table test:
-- PL/pgSQL does not short-circuit `and`, and a field one table lacks would
-- error (42703).
create or replace function public.serve_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'serve_teams' then
    if not exists (select 1 from public.groups g
                   where g.id = new.group_id and g.business_id = new.business_id and g.kind = 'team') then
      raise exception 'That serving team is not in this business';
    end if;
  end if;
  if tg_table_name = 'serve_positions' then
    if not exists (select 1 from public.serve_teams t
                   where t.group_id = new.group_id and t.business_id = new.business_id) then
      raise exception 'That team is not in this business';
    end if;
  end if;
  if tg_table_name in ('serve_trained', 'serve_assignments') then
    if not exists (select 1 from public.serve_positions p
                   where p.id = new.position_id and p.business_id = new.business_id) then
      raise exception 'That place is not in this business';
    end if;
  end if;
  if tg_table_name = 'serve_assignments' then
    if not exists (select 1 from public.worship_services s
                   where s.id = new.service_id and s.business_id = new.business_id) then
      raise exception 'That service is not in this business';
    end if;
    if new.swap_to is not null and not exists (select 1 from public.contacts c
                   where c.id = new.swap_to and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  if tg_table_name in ('serve_trained', 'serve_assignments', 'serve_away', 'serve_prefs') then
    if new.contact_id is not null and not exists (select 1 from public.contacts c
                   where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.serve_same_business() from public, anon, authenticated;

drop trigger if exists serve_same_business on public.serve_prefs;
create trigger serve_same_business before insert or update on public.serve_prefs
  for each row execute function public.serve_same_business();
alter table public.serve_prefs enable row level security;
revoke all on public.serve_prefs from anon, authenticated;
grant all on public.serve_prefs to service_role;

commit;
