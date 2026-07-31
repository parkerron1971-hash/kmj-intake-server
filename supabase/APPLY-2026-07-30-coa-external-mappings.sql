-- APPLY-2026-07-30-coa-external-mappings.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Rails Arc 1: the QuickBooks bridge's mapping layer.
--
-- THE ONE THING TO BUILD WELL (per the rails ruling): our chart of
-- accounts → THEIR chart of accounts, configured once per business.
-- Everything the bridge exports — IIF today, QBO API journal pushes in
-- Arc 1b — reads account names through this table, so a business whose
-- accountant calls 5100 "Subcontractor Expense" exports under that name
-- everywhere without renaming the internal COA.
--
-- provider is a column (not hardcoded) so Xero/Wave slot in later
-- without a schema change — same philosophy as the payment adapter.
-- external_id/external_type stay NULL until Arc 1b fetches the real
-- QBO account list; file exports only need external_name.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

create table if not exists public.coa_external_mappings (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references public.businesses(id) on delete cascade,
  provider      text not null default 'quickbooks',
  account_code  text not null,

  -- What this account is called in THEIR books.
  external_name text not null,
  -- Set by Arc 1b when a live QBO connection fetches their real COA.
  external_id   text,
  external_type text,

  updated_at    timestamptz not null default now(),

  unique (business_id, provider, account_code)
);

create index if not exists idx_coa_ext_map_biz
  on public.coa_external_mappings (business_id, provider);

alter table public.coa_external_mappings enable row level security;

-- Owner read as backstop; all writes go through the owner-gated backend
-- endpoints with the service role.
drop policy if exists coa_ext_map_owner_select on public.coa_external_mappings;
create policy coa_ext_map_owner_select on public.coa_external_mappings
  for select to authenticated
  using (exists (
    select 1 from public.businesses b
    where b.id = coa_external_mappings.business_id and b.owner_id = auth.uid()
  ));

comment on table public.coa_external_mappings is
  'Per-business mapping: our chart_of_accounts.code -> the name (and, once connected, id) of the matching account in an external accounting system. The QuickBooks bridge reads every exported account name through this table. Provider column keeps it accounting-package-agnostic.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select
  (select count(*) from information_schema.tables
    where table_schema='public' and table_name='coa_external_mappings') as table_ok,
  (select count(*) from pg_policies
    where schemaname='public' and tablename='coa_external_mappings') as policies;
