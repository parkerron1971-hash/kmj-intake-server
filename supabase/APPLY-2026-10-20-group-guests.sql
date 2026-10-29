-- First-time guests by name, from a leader's roll (the approved canvas
-- "Church Groups, Together", board Roll: "First name · The office welcomes
-- them as a first-time guest. Add a phone only if they said yes to hearing
-- from us."). Idempotent.
--
--   group_meeting_guests   one guest at one gathering: a first name, a
--                          phone only with their yes, and (once the office
--                          adds them) the person they became
begin;

create table if not exists public.group_meeting_guests(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  group_id uuid not null references public.groups(id) on delete cascade,
  meeting_id uuid not null references public.group_meetings(id) on delete cascade,
  first_name text not null check (length(btrim(first_name)) between 1 and 40),
  phone text not null default '' check (length(phone) <= 40),
  added_by uuid references public.contacts(id) on delete set null,
  contact_id uuid references public.contacts(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists group_meeting_guests_meeting on public.group_meeting_guests(meeting_id);
create index if not exists group_meeting_guests_new on public.group_meeting_guests(business_id, created_at)
  where contact_id is null;

-- The office reads them and, adding one to its people, links who they
-- became; a leader writes them through the server.
alter table public.group_meeting_guests enable row level security;
drop policy if exists tenant_member_read on public.group_meeting_guests;
create policy tenant_member_read on public.group_meeting_guests for select to authenticated
  using (public.is_business_member(business_id));
drop policy if exists business_owner_read on public.group_meeting_guests;
create policy business_owner_read on public.group_meeting_guests for select to authenticated
  using (business_id in (select id from public.businesses where owner_id = auth.uid()));
drop policy if exists tenant_writer_link on public.group_meeting_guests;
create policy tenant_writer_link on public.group_meeting_guests for update to authenticated
  using (public.is_business_writer(business_id) or business_id in (select id from public.businesses where owner_id = auth.uid()))
  with check (public.is_business_writer(business_id) or business_id in (select id from public.businesses where owner_id = auth.uid()));
revoke all on public.group_meeting_guests from anon, authenticated;
grant select on public.group_meeting_guests to authenticated;
grant update (contact_id) on public.group_meeting_guests to authenticated;
grant all on public.group_meeting_guests to service_role;

create or replace function public.group_meeting_guests_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.group_meetings m where m.id = new.meeting_id
                 and m.group_id = new.group_id and m.business_id = new.business_id) then
    raise exception 'That gathering is not this group''s';
  end if;
  if new.added_by is not null and not exists (
       select 1 from public.contacts c where c.id = new.added_by and c.business_id = new.business_id) then
    raise exception 'That person is not in this business';
  end if;
  if new.contact_id is not null and not exists (
       select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this business';
  end if;
  return new;
end $$;
revoke all on function public.group_meeting_guests_same_business() from public, anon, authenticated;
drop trigger if exists group_meeting_guests_same_business on public.group_meeting_guests;
create trigger group_meeting_guests_same_business before insert or update on public.group_meeting_guests
  for each row execute function public.group_meeting_guests_same_business();

commit;
