-- Pledges and campaigns (church_pledges.py; Kevin 2026-10-27, "lets start
-- building this": the gap check of a church's staff menu, Giving card).
-- Two tables, server-only (RLS on, no policies, browser roles revoked);
-- church_pledges.py reads and writes them as the server, after its own
-- finance check (owner, admins, the accountant).
--
--   church_campaigns   a building fund, a missions push: a name, a goal,
--                      start and end dates, and one of the church's funds
--                      (by name, as gifts carry it in invoices.gift_fund).
--                      Progress is never stored: it is read from the paid
--                      gifts to that fund inside those dates.
--   church_pledges     one giver's pledge to one campaign, from a pledge
--                      card: a total, or an amount per week / two weeks /
--                      month for so many periods (total = per x periods).
--                      One pledge per giver per campaign. request_id makes
--                      a retried save land once.
--
-- Additive. Grants nothing by itself: the pages stay off until this is
-- applied, and behind CHURCH_PLEDGES (off | owner | on) after.
-- Idempotent.
begin;

create table if not exists public.church_campaigns(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  goal_cents bigint not null check (goal_cents between 1 and 10000000000),
  fund text not null check (char_length(fund) between 1 and 40),
  starts_on date not null,
  ends_on date not null,
  note text not null default '' check (char_length(note) <= 500),
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint church_campaigns_dates check (ends_on >= starts_on),
  constraint church_campaigns_id_business unique (id, business_id)
);

create table if not exists public.church_pledges(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  campaign_id uuid not null,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  total_cents bigint not null check (total_cents between 1 and 1000000000),
  per_period_cents bigint check (per_period_cents is null or per_period_cents > 0),
  period text check (period is null or period in ('weekly', 'biweekly', 'monthly')),
  periods int check (periods is null or periods between 1 and 520),
  note text not null default '' check (char_length(note) <= 500),
  recorded_by uuid,
  recorded_at timestamptz not null default now(),
  request_id uuid,
  -- A pledge belongs to a campaign of the same church.
  constraint church_pledges_campaign foreign key (campaign_id, business_id)
    references public.church_campaigns(id, business_id) on delete cascade,
  constraint church_pledges_one_per_giver unique (campaign_id, contact_id),
  constraint church_pledges_amount check (
    (per_period_cents is null and period is null and periods is null)
    or (per_period_cents is not null and period is not null and periods is not null
        and total_cents = per_period_cents * periods))
);

create index if not exists church_campaigns_business
  on public.church_campaigns(business_id, starts_on desc);
create index if not exists church_pledges_business
  on public.church_pledges(business_id, campaign_id);
create index if not exists church_pledges_contact
  on public.church_pledges(contact_id);
create unique index if not exists church_pledges_request
  on public.church_pledges(business_id, request_id) where request_id is not null;

alter table public.church_campaigns enable row level security;
alter table public.church_pledges enable row level security;
revoke all on public.church_campaigns from anon, authenticated;
revoke all on public.church_pledges from anon, authenticated;
grant all on public.church_campaigns to service_role;
grant all on public.church_pledges to service_role;

commit;

-- Check after applying:
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.tablename = c.relname) as policies
--     from pg_class c join pg_namespace n on n.oid = c.relnamespace
--    where n.nspname = 'public' and c.relname in ('church_campaigns', 'church_pledges');
--   -- expect two rows, relrowsecurity true, 0 policies
