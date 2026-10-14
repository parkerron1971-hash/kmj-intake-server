-- Bible reading plans (Subsplash exit plan, step 6, 2026-10-14). The
-- church's plan lives in businesses.settings.reading_plan {key, start};
-- this keeps which days each member has read. One row per member per
-- plan run (plan_key + start_date) per day. Server-only: RLS on, no
-- policies, browser roles revoked; member_portal_reading.py writes a
-- member's own ticks after the member-page sign-in. Idempotent.
begin;

create table if not exists public.reading_progress(
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  plan_key text not null check (plan_key ~ '^[a-z0-9-]{1,40}$'),
  start_date date not null,
  day integer not null check (day between 1 and 400),
  read_at timestamptz not null default now(),
  primary key (business_id, contact_id, plan_key, start_date, day)
);

alter table public.reading_progress enable row level security;
revoke all on public.reading_progress from anon, authenticated;
grant all on public.reading_progress to service_role;

commit;
