-- APPLY-2026-07-31-esign-documents.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Rails demand-driven arc: e-sign via BoldSign (connect, don't build —
-- legally valid signatures carry ESIGN Act compliance, audit trails,
-- tamper-evidence; BoldSign owns all of that, we own the chain:
-- proposal → signature → payment).
--
-- One row per document sent for signature. provider is a column for
-- the same reason it is on coa_external_mappings: the seam outlives
-- the first vendor.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

create table if not exists public.esign_documents (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references public.businesses(id) on delete cascade,
  provider      text not null default 'boldsign',

  document_id   text not null,          -- BoldSign's id
  title         text not null,
  signer_name   text not null default '',
  signer_email  text not null,

  status        text not null default 'sent'
                check (status in ('sent','completed','declined','expired','revoked')),
  source_ref    text,                    -- e.g. agent_queue id the proposal came from

  sent_at       timestamptz not null default now(),
  completed_at  timestamptz,
  updated_at    timestamptz not null default now()
);

create index if not exists idx_esign_biz_recent
  on public.esign_documents (business_id, sent_at desc);

alter table public.esign_documents enable row level security;

drop policy if exists esign_owner_select on public.esign_documents;
create policy esign_owner_select on public.esign_documents
  for select to authenticated
  using (exists (
    select 1 from public.businesses b
    where b.id = esign_documents.business_id and b.owner_id = auth.uid()
  ));

comment on table public.esign_documents is
  'Documents sent for e-signature (BoldSign adapter #1). Status refreshes on demand from the provider; completion emits contract_signed on the event spine. Writes via owner-gated /esign endpoints only.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select
  (select count(*) from information_schema.tables
    where table_schema='public' and table_name='esign_documents') as table_ok,
  (select count(*) from pg_policies
    where schemaname='public' and tablename='esign_documents') as policies;
