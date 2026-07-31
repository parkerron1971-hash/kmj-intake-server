-- APPLY-2026-07-30-quickbooks-connections.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Rails Arc 1b: the live QuickBooks Online connection.
--
-- quickbooks_connections — one row per connected business: the OAuth
--   tokens (access ~1h, refresh rotates on every refresh — Intuit
--   invalidates the old one, so the stored pair must always be the
--   latest), the realm (QBO company) id, and which Intuit environment
--   the tokens belong to. SERVICE-ROLE ONLY — RLS enabled with no
--   policies, because rows hold live tokens. Status/company_name are
--   surfaced to the owner through the gated /quickbooks/status
--   endpoint, never PostgREST.
--
-- quickbooks_pushed_entries — the push idempotency ledger: which of our
--   journal entries already exist in QBO (and as what). The push
--   endpoint skips anything recorded here, so re-running a push after
--   a partial failure re-sends only what is missing. QBO DocNumber is
--   capped at 21 chars, too short to carry our uuid — this table is
--   the real dedupe, DocNumber is just a human breadcrumb.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

create table if not exists public.quickbooks_connections (
  business_id        uuid primary key references public.businesses(id) on delete cascade,
  realm_id           text not null,
  environment        text not null default 'sandbox'
                     check (environment in ('sandbox','production')),

  access_token       text not null,
  refresh_token      text not null,
  access_expires_at  timestamptz,
  refresh_expires_at timestamptz,

  company_name       text,
  status             text not null default 'connected'
                     check (status in ('connected','disconnected','error')),
  last_error         text,

  connected_at       timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

alter table public.quickbooks_connections enable row level security;
-- No policies: tokens live here. Service-role only, by design.

create table if not exists public.quickbooks_pushed_entries (
  business_id       uuid not null references public.businesses(id) on delete cascade,
  journal_entry_id  uuid not null,
  qbo_journal_id    text not null,
  pushed_at         timestamptz not null default now(),
  primary key (business_id, journal_entry_id)
);

alter table public.quickbooks_pushed_entries enable row level security;

drop policy if exists qb_pushed_owner_select on public.quickbooks_pushed_entries;
create policy qb_pushed_owner_select on public.quickbooks_pushed_entries
  for select to authenticated
  using (exists (
    select 1 from public.businesses b
    where b.id = quickbooks_pushed_entries.business_id and b.owner_id = auth.uid()
  ));

comment on table public.quickbooks_connections is
  'Live QBO OAuth connection per business (realm + rotating token pair + environment). Service-role only - no RLS policies on purpose, rows hold tokens. Surface state via /quickbooks/status.';
comment on table public.quickbooks_pushed_entries is
  'Push idempotency ledger: our journal_entry_id -> QBO JournalEntry Id. The push endpoint skips entries recorded here; DocNumber (21-char cap) is only a breadcrumb.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select
  (select count(*) from information_schema.tables
    where table_schema='public' and table_name='quickbooks_connections') as conn_ok,
  (select count(*) from information_schema.tables
    where table_schema='public' and table_name='quickbooks_pushed_entries') as pushed_ok,
  (select count(*) from pg_policies
    where schemaname='public' and tablename='quickbooks_connections') as conn_policies_zero;
