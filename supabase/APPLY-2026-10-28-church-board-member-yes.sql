-- A board member's yes from the member app (church_money_levels.py,
-- member_portal_board.py). Kevin 2026-10-28: "the 7 office logins are for
-- the office only ... Everyone else uses the member app, by role", and
-- "build step 2 (the board member's yes from the member app, with a fresh
-- code on every approval)". Board members are matched by their person
-- (church_board_members.contact_id), not a login, so:
--
--   church_check_approvals       a yes may come from a person (contact_id)
--                                as well as a login (user_id); one yes a
--                                person, the same as one a login
--   church_check_approval_codes  the code a board member is sent to give a
--                                yes: one request, one person, a hash of the
--                                6 digits, its tries, when it was sent and
--                                used. Server-only, like the yeses
--
-- A yes's person and a code's person are their request's church's (checked
-- by triggers). A person who leaves keeps the yes they gave, with no one
-- named. Idempotent, and nothing here drops anything.
begin;

alter table public.church_check_approvals alter column user_id drop not null;
alter table public.church_check_approvals
  add column if not exists contact_id uuid references public.contacts(id) on delete set null;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'church_check_approvals_one_a_member') then
    alter table public.church_check_approvals
      add constraint church_check_approvals_one_a_member unique (request_id, contact_id);
  end if;
end $$;

-- A yes is on its own church's request, from its own church's person.
create or replace function public.church_check_approval_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (
      select 1 from public.church_check_requests r where r.id = new.request_id and r.business_id = new.business_id) then
    raise exception 'That request is not in this church';
  end if;
  if new.contact_id is not null and not exists (
      select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this church';
  end if;
  return new;
end $$;
create or replace trigger church_check_approval_same_business
  before insert or update of request_id, business_id, contact_id
  on public.church_check_approvals for each row execute function public.church_check_approval_same_business();
revoke all on function public.church_check_approval_same_business() from public, anon, authenticated;

create table if not exists public.church_check_approval_codes(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  request_id uuid not null references public.church_check_requests(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  code_hash text not null check (char_length(code_hash) = 64),
  tries int not null default 0 check (tries between 0 and 10),
  created_at timestamptz not null default now(),
  used_at timestamptz
);
create index if not exists church_check_approval_codes_recent
  on public.church_check_approval_codes(business_id, contact_id, created_at desc);
create or replace trigger church_check_approval_code_same_business
  before insert or update of request_id, business_id, contact_id
  on public.church_check_approval_codes for each row execute function public.church_check_approval_same_business();

alter table public.church_check_approval_codes enable row level security;
revoke all on public.church_check_approval_codes from anon, authenticated;
grant all on public.church_check_approval_codes to service_role;

commit;

-- Check after applying:
--   select (select is_nullable from information_schema.columns
--            where table_name = 'church_check_approvals' and column_name = 'user_id') as user_id_nullable,
--          (select count(*) from information_schema.columns
--            where table_name = 'church_check_approvals' and column_name = 'contact_id') as contact_column,
--          (select relrowsecurity from pg_class where relname = 'church_check_approval_codes') as codes_rls,
--          (select count(*) from pg_policies where tablename = 'church_check_approval_codes') as codes_policies;
