-- Year-end giving statements by email (Subsplash exit plan, step 2,
-- 2026-10-14). One row per giver per year once their statement has been
-- emailed, so a second run (or a retried batch) never sends it twice.
-- Server-only like the rest of giving: RLS on, no policies, browser roles
-- revoked; giving_statement_mail.py writes it after require_finance.
-- Idempotent.
begin;

create table if not exists public.giving_statement_sends(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  year integer not null check (year between 2000 and 2200),
  email text not null check (length(email) between 3 and 320),
  total numeric(12,2),
  sent_at timestamptz not null default now(),
  unique (business_id, contact_id, year)
);
create index if not exists giving_statement_sends_business_year
  on public.giving_statement_sends(business_id, year);

alter table public.giving_statement_sends enable row level security;
revoke all on public.giving_statement_sends from anon, authenticated;
grant all on public.giving_statement_sends to service_role;

commit;
