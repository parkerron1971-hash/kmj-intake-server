-- Attendance (Kevin, 2026-09-29: "attendance first", then families and
-- children's check-in on top). Who was actually THERE at an occasion (an
-- event_roster entry), as opposed to who RSVP'd, plus counted heads per
-- area for the people nobody checks in by name. Idempotent.
--
-- Access is the rest of the church's records: the owner and any writing
-- seat (member/manager/admin) record it, any active seat reads it. The
-- check-in station (a later phase) writes through a scoped backend
-- endpoint, never through a seat.
begin;

create table if not exists public.attendance(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  entry_id uuid not null references public.module_entries(id) on delete cascade,
  contact_id uuid references public.contacts(id) on delete set null,
  -- The name as it was checked in: a guest may have no record, and a
  -- record may be renamed later.
  name text not null check (length(btrim(name)) between 1 and 160),
  first_time boolean not null default false,
  -- staff (in the app) | station | self | rsvp — who recorded it.
  method text not null default 'staff' check (method in ('staff','station','self','rsvp')),
  checked_in_at timestamptz not null default now(),
  checked_in_by uuid,
  checked_out_at timestamptz,
  created_at timestamptz not null default now()
);
-- One row per person per occasion; guests without a record are named.
create unique index if not exists attendance_once_per_contact
  on public.attendance(entry_id, contact_id) where contact_id is not null;
create index if not exists attendance_business_time on public.attendance(business_id, checked_in_at desc);
create index if not exists attendance_contact on public.attendance(contact_id, checked_in_at desc) where contact_id is not null;

create table if not exists public.attendance_headcounts(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  entry_id uuid not null references public.module_entries(id) on delete cascade,
  -- "Main service", "Kids", "Online" … the church names its own areas.
  area text not null check (length(btrim(area)) between 1 and 60),
  count integer not null default 0 check (count between 0 and 100000),
  counted_by uuid,
  updated_at timestamptz not null default now(),
  unique (entry_id, area)
);
create index if not exists attendance_headcounts_business on public.attendance_headcounts(business_id, updated_at desc);

alter table public.attendance enable row level security;
alter table public.attendance_headcounts enable row level security;

do $$ declare t text; begin
  foreach t in array array['attendance','attendance_headcounts'] loop
    execute format('drop policy if exists business_member_access on public.%I', t);
    execute format('create policy business_member_access on public.%I for all to authenticated
      using (business_id in (select id from public.businesses where owner_id = auth.uid()))
      with check (business_id in (select id from public.businesses where owner_id = auth.uid()))', t);
    execute format('drop policy if exists tenant_writer_write on public.%I', t);
    execute format('create policy tenant_writer_write on public.%I for all to authenticated
      using (public.is_business_writer(business_id)) with check (public.is_business_writer(business_id))', t);
    execute format('drop policy if exists tenant_member_read on public.%I', t);
    execute format('create policy tenant_member_read on public.%I for select to authenticated
      using (public.is_business_member(business_id))', t);
    execute format('revoke all on public.%I from anon', t);
    execute format('grant select, insert, update, delete on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- The row's occasion must be this business's own entry, so a writer at
-- one church can never attach attendance to another church's occasion.
create or replace function public.attendance_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.module_entries e
                 where e.id = new.entry_id and e.business_id = new.business_id) then
    raise exception 'That occasion is not in this business';
  end if;
  -- Nested, not `and`: PL/pgSQL does not promise to short-circuit, and a
  -- headcount row has no contact_id field at all (it errored 42703).
  if tg_table_name = 'attendance' then
    if new.contact_id is not null and not exists (
         select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  return new;
end $$;
drop trigger if exists attendance_same_business on public.attendance;
create trigger attendance_same_business before insert or update on public.attendance
  for each row execute function public.attendance_same_business();
drop trigger if exists attendance_headcounts_same_business on public.attendance_headcounts;
create trigger attendance_headcounts_same_business before insert or update on public.attendance_headcounts
  for each row execute function public.attendance_same_business();

commit;
