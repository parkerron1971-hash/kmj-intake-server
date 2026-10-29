-- Help requests (benevolence) (church_help.py; Kevin 2026-10-27 on the
-- Church Office Prototypes, "Help requests" tab: "lets go with your list").
-- Someone asks for help with food, a bill or a ride; the office keeps a
-- fund, a limit, a yes and a record. Three tables, server-only (RLS on, no
-- policies, browser roles revoked); church_help.py reads and writes them.
--
--   church_help_settings   one row per church: the fund's name (one of its
--                          giving funds, or its own), a monthly budget and
--                          the single-gift limit, in cents ($150 unless set)
--   church_help_requests   who asked (a contact, a name, or no one; private
--                          hides who from all but the owner and admins;
--                          pastors_only is a youth's ask), the need, the
--                          amount asked and approved, the story, the status
--                          and where it came from. An ask from the member
--                          app (Prayer & care, submission.kind 'help') gets
--                          a row once: care_request_id is unique
--   church_help_given      how the church helped: cash, a check, a gift card,
--                          groceries, a ride, other; an amount and a day.
--                          Money given is also one business_expenses row
--                          (expense_id), which the GL triggers post
--
-- A request's person and Prayer & care row are its own church's (checked by
-- a trigger), and a record of help is its request's church's (a foreign key
-- on (business_id, request_id)).
-- Idempotent.
begin;

create table if not exists public.church_help_settings(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  fund text not null default 'Benevolence' check (char_length(fund) between 1 and 80),
  monthly_budget_cents int not null default 0 check (monthly_budget_cents between 0 and 10000000),
  gift_limit_cents int not null default 15000 check (gift_limit_cents between 0 and 10000000),
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table if not exists public.church_help_requests(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid references public.contacts(id) on delete set null,
  name text check (name is null or char_length(name) <= 120),
  anonymous boolean not null default false,
  pastors_only boolean not null default false,
  wants_call boolean not null default false,
  need text not null check (need in ('food', 'bill', 'ride', 'other')),
  amount_cents int check (amount_cents is null or amount_cents between 0 and 10000000),
  approved_cents int check (approved_cents is null or approved_cents between 0 and 10000000),
  notes text not null default '' check (char_length(notes) <= 2000),
  status text not null default 'new' check (status in ('new', 'approved', 'helped', 'declined')),
  source text not null default 'phone' check (source in ('app', 'phone', 'walk_in', 'other')),
  care_request_id uuid references public.ministry_care_requests(id) on delete set null,
  created_by uuid,
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint church_help_requests_one_ask unique (care_request_id),
  unique (business_id, id)
);

create table if not exists public.church_help_given(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  request_id uuid not null,
  how text not null check (how in ('cash', 'check', 'gift_card', 'groceries', 'ride', 'other')),
  amount_cents int not null default 0 check (amount_cents between 0 and 10000000),
  given_on date not null,
  payee text check (payee is null or char_length(payee) <= 120),
  note text not null default '' check (char_length(note) <= 500),
  expense_id uuid references public.business_expenses(id) on delete set null,
  recorded_by uuid,
  created_at timestamptz not null default now(),
  constraint church_help_given_request foreign key (business_id, request_id)
    references public.church_help_requests(business_id, id) on delete cascade
);

create index if not exists church_help_requests_open
  on public.church_help_requests(business_id, status, created_at desc);
create index if not exists church_help_given_request_day
  on public.church_help_given(business_id, request_id);
create index if not exists church_help_given_day
  on public.church_help_given(business_id, given_on);

-- A request's person and its Prayer & care row belong to its own church,
-- whatever the caller passes.
create or replace function public.church_help_request_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.contact_id is not null and not exists (
      select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this church';
  end if;
  if new.care_request_id is not null and not exists (
      select 1 from public.ministry_care_requests r
      where r.id = new.care_request_id and r.business_id = new.business_id) then
    raise exception 'That request is not in this church';
  end if;
  return new;
end $$;
drop trigger if exists church_help_request_same_business on public.church_help_requests;
create trigger church_help_request_same_business before insert or update of contact_id, care_request_id, business_id
  on public.church_help_requests for each row execute function public.church_help_request_same_business();
revoke all on function public.church_help_request_same_business() from public, anon, authenticated;

alter table public.church_help_settings enable row level security;
alter table public.church_help_requests enable row level security;
alter table public.church_help_given enable row level security;
revoke all on public.church_help_settings from anon, authenticated;
revoke all on public.church_help_requests from anon, authenticated;
revoke all on public.church_help_given from anon, authenticated;
grant all on public.church_help_settings to service_role;
grant all on public.church_help_requests to service_role;
grant all on public.church_help_given to service_role;

commit;

-- Check after applying (three rows, RLS on, no policies):
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.tablename = c.relname) as policies
--     from pg_class c where c.relname in ('church_help_settings', 'church_help_requests', 'church_help_given');
