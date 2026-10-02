-- Kids' check-in (Kevin, 2026-09-29: pickup security = BOTH a code on
-- screen texted to the parent AND printed name tags). Idempotent.
--
-- One row per child per occasion. Server-only like the rest of the
-- families tables: a view-only seat can read `attendance`, and a child's
-- name, room and pickup code are not for every seat. kids_router.py is
-- the one door (member+ checks in and out; custody detail stays manager+).
--
-- The pickup code is shared by a family's children at one occasion and
-- is only ever shown to the check-in team, printed on the tags, and texted
-- straight to the parent — never kept in the church's text history.
begin;

create table if not exists public.child_checkins(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  entry_id uuid not null references public.module_entries(id) on delete cascade,
  child_id uuid not null references public.children(id) on delete cascade,
  household_id uuid not null references public.households(id) on delete cascade,
  room text not null default '' check (length(room) <= 60),
  code text not null check (code ~ '^[A-Z0-9]{4}$'),
  -- Who brought them (a household adult), for the record and the text.
  dropped_off_by uuid references public.contacts(id) on delete set null,
  method text not null default 'staff' check (method in ('staff','station','self')),
  checked_in_at timestamptz not null default now(),
  checked_in_by uuid,
  checked_out_at timestamptz,
  checked_out_by uuid,
  -- The name of the person the child went home with.
  released_to text check (released_to is null or length(btrim(released_to)) between 1 and 120),
  unique (entry_id, child_id)
);
create index if not exists child_checkins_entry_code on public.child_checkins(entry_id, code);
create index if not exists child_checkins_business_time on public.child_checkins(business_id, checked_in_at desc);

alter table public.child_checkins enable row level security;
revoke all on public.child_checkins from anon, authenticated;
grant all on public.child_checkins to service_role;

create or replace function public.child_checkin_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.module_entries e
                 where e.id = new.entry_id and e.business_id = new.business_id) then
    raise exception 'That occasion is not in this business';
  end if;
  if not exists (select 1 from public.children k
                 where k.id = new.child_id and k.business_id = new.business_id
                   and k.household_id = new.household_id) then
    raise exception 'That child is not in this family';
  end if;
  if new.dropped_off_by is not null and not exists (
       select 1 from public.household_adults a
       where a.contact_id = new.dropped_off_by and a.household_id = new.household_id) then
    raise exception 'That person is not one of this family''s adults';
  end if;
  return new;
end $$;
revoke all on function public.child_checkin_same_business() from public, anon, authenticated;
drop trigger if exists child_checkin_same_business on public.child_checkins;
create trigger child_checkin_same_business before insert or update on public.child_checkins
  for each row execute function public.child_checkin_same_business();

commit;
