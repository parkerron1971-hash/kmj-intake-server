-- Check requests (church_checks.py; Kevin 2026-10-27 on the Church Office
-- Prototypes, "Check requests" tab: "lets go with your list"). Money going
-- out: a volunteer asks to be paid back with a receipt photo, or the office
-- asks to pay someone directly; the treasurer says yes up to a limit, a
-- keeper above it, and the office marks it paid. Two tables, server-only
-- (RLS on, no policies, browser roles revoked); church_checks.py reads and
-- writes them.
--
--   church_check_settings   one row per church: the limit in cents ($250
--                           unless set) and the budget lines, a JSON list of
--                           {name, budget_cents}: each ministry and this
--                           year's budget. Spent is the books' own expenses
--                           with that ministry as their subcategory
--   church_check_requests   who asked (a contact, a name, or the office), who
--                           gets paid, what it was for, the ministry, the
--                           amount, the receipt (a path in the private
--                           business-documents bucket), the status (new,
--                           approved, paid, declined), the reason a decline
--                           gives the asker, and once paid: by check (its
--                           number) or transfer, the day, and the one
--                           business_expenses row it wrote (expense_id),
--                           which the GL triggers post
--
-- A request's person is its own church's (checked by a trigger); a paid
-- request says how and when; a decline says why. Idempotent, and nothing
-- here drops anything.
begin;

create table if not exists public.church_check_settings(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  limit_cents int not null default 25000 check (limit_cents between 0 and 10000000),
  lines jsonb not null default '[]'::jsonb check (jsonb_typeof(lines) = 'array'),
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table if not exists public.church_check_requests(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid references public.contacts(id) on delete set null,
  asker_name text check (asker_name is null or char_length(asker_name) <= 120),
  payee text check (payee is null or char_length(payee) <= 120),
  ministry text not null check (char_length(ministry) between 1 and 60),
  about text not null check (char_length(about) between 1 and 200),
  amount_cents int not null check (amount_cents between 1 and 10000000),
  receipt_path text check (receipt_path is null or char_length(receipt_path) <= 200),
  receipt_type text check (receipt_type is null or receipt_type in ('image', 'pdf')),
  status text not null default 'new' check (status in ('new', 'approved', 'paid', 'declined')),
  source text not null default 'office' check (source in ('app', 'office')),
  decline_reason text check (decline_reason is null or char_length(decline_reason) <= 300),
  decided_by uuid,
  decided_at timestamptz,
  paid_how text check (paid_how is null or paid_how in ('check', 'transfer')),
  check_number text check (check_number is null or char_length(check_number) <= 20),
  paid_on date,
  expense_id uuid references public.business_expenses(id) on delete set null,
  paid_by uuid,
  paid_at timestamptz,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  -- Paid says how and when; a check says its number; a decline says why.
  constraint church_check_requests_paid check (
    status <> 'paid' or (paid_how is not null and paid_on is not null)),
  constraint church_check_requests_check_number check (
    paid_how is distinct from 'check' or check_number is not null),
  constraint church_check_requests_declined check (
    status <> 'declined' or decline_reason is not null)
);

create index if not exists church_check_requests_open
  on public.church_check_requests(business_id, status, created_at desc);
create index if not exists church_check_requests_asker
  on public.church_check_requests(business_id, contact_id, created_at desc);

-- A request's person belongs to its own church, whatever the caller passes.
create or replace function public.church_check_request_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.contact_id is not null and not exists (
      select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this church';
  end if;
  return new;
end $$;
create or replace trigger church_check_request_same_business
  before insert or update of contact_id, business_id
  on public.church_check_requests for each row execute function public.church_check_request_same_business();
revoke all on function public.church_check_request_same_business() from public, anon, authenticated;

alter table public.church_check_settings enable row level security;
alter table public.church_check_requests enable row level security;
revoke all on public.church_check_settings from anon, authenticated;
revoke all on public.church_check_requests from anon, authenticated;
grant all on public.church_check_settings to service_role;
grant all on public.church_check_requests to service_role;

commit;

-- Check after applying (two rows, RLS on, no policies):
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.tablename = c.relname) as policies
--     from pg_class c where c.relname in ('church_check_settings', 'church_check_requests');
