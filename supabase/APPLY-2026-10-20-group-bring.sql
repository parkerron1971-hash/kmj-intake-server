-- "Bring something" (the approved canvas "Church Groups, Together", boards
-- Meet and Main: "Bring a dish · 2 open"). A group's leaders list what a
-- gathering needs (a main dish, greens, drinks, plates and cups); people
-- in the group tap "I'll bring it" on one thing, or undo. One thing each,
-- so the list spreads around. Idempotent.
--
--   group_bring   one thing a gathering needs (group_id + met_on, the same
--                 date group_rsvps uses), and who is bringing it (null =
--                 still open)
begin;

create table if not exists public.group_bring(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  group_id uuid not null references public.groups(id) on delete cascade,
  met_on date not null,
  what text not null check (length(btrim(what)) between 1 and 60),
  contact_id uuid references public.contacts(id) on delete set null,
  claimed_at timestamptz,
  added_by uuid references public.contacts(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists group_bring_gathering on public.group_bring(business_id, group_id, met_on);
-- One thing each per gathering.
create unique index if not exists group_bring_one_each on public.group_bring(group_id, met_on, contact_id)
  where contact_id is not null;

-- The office reads them; only the server writes, after checking the person
-- is in the group (and, to add or remove, that they lead it).
alter table public.group_bring enable row level security;
drop policy if exists tenant_member_read on public.group_bring;
create policy tenant_member_read on public.group_bring for select to authenticated
  using (public.is_business_member(business_id));
drop policy if exists business_owner_read on public.group_bring;
create policy business_owner_read on public.group_bring for select to authenticated
  using (business_id in (select id from public.businesses where owner_id = auth.uid()));
revoke all on public.group_bring from anon, authenticated;
grant select on public.group_bring to authenticated;
grant all on public.group_bring to service_role;

create or replace function public.group_bring_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.groups g where g.id = new.group_id and g.business_id = new.business_id) then
    raise exception 'That group is not in this business';
  end if;
  if new.contact_id is not null and not exists (
       select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this business';
  end if;
  if new.added_by is not null and not exists (
       select 1 from public.contacts c where c.id = new.added_by and c.business_id = new.business_id) then
    raise exception 'That person is not in this business';
  end if;
  return new;
end $$;
revoke all on function public.group_bring_same_business() from public, anon, authenticated;
drop trigger if exists group_bring_same_business on public.group_bring;
create trigger group_bring_same_business before insert or update on public.group_bring
  for each row execute function public.group_bring_same_business();

commit;
