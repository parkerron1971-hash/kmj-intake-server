-- Safety officers from a church's pastoral leaders (Kevin, 2026-10-20: yes
-- to "pick from the Pastors and Elders you've already named", part 2 of
-- the approved "Church Groups, Together" canvas). Until now an officer had
-- to be a team login (msg_safety_officers.user_id); a pastor or an elder
-- who only uses the member app can now be one too, and works the Safety
-- room from their Lead tab. Idempotent.
--
--   msg_member_officers   a church member (contact) the owner named an officer
--   msg_staff_views       who opened a whole chat: a team login (user_id) OR
--                         a member officer (contact_id); never neither
begin;

create table if not exists public.msg_member_officers(
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  added_by uuid,
  created_at timestamptz not null default now(),
  primary key (business_id, contact_id)
);

-- Seats read (the Messaging page lists them); only the server writes, after
-- checking the person holds an active pastoral role.
alter table public.msg_member_officers enable row level security;
drop policy if exists tenant_member_read on public.msg_member_officers;
create policy tenant_member_read on public.msg_member_officers for select to authenticated
  using (public.is_business_member(business_id));
drop policy if exists business_owner_read on public.msg_member_officers;
create policy business_owner_read on public.msg_member_officers for select to authenticated
  using (business_id in (select id from public.businesses where owner_id = auth.uid()));
revoke all on public.msg_member_officers from anon, authenticated;
grant select on public.msg_member_officers to authenticated;
grant all on public.msg_member_officers to service_role;

-- A whole chat opened by a member officer is logged with their contact.
alter table public.msg_staff_views add column if not exists contact_id uuid references public.contacts(id) on delete set null;
alter table public.msg_staff_views alter column user_id drop not null;
alter table public.msg_staff_views drop constraint if exists msg_staff_views_who;
alter table public.msg_staff_views add constraint msg_staff_views_who check (user_id is not null or contact_id is not null);

-- An officer and a logged look must be this church's own person.
create or replace function public.msg_officer_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'msg_member_officers' then
    if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  elsif tg_table_name = 'msg_staff_views' then
    if new.contact_id is not null then
      if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
        raise exception 'That person is not in this business';
      end if;
    end if;
  end if;
  return new;
end $$;
revoke all on function public.msg_officer_same_business() from public, anon, authenticated;
do $$ declare t text; begin
  foreach t in array array['msg_member_officers','msg_staff_views'] loop
    execute format('drop trigger if exists msg_officer_same_business on public.%I', t);
    execute format('create trigger msg_officer_same_business before insert or update on public.%I
      for each row execute function public.msg_officer_same_business()', t);
  end loop;
end $$;

commit;
