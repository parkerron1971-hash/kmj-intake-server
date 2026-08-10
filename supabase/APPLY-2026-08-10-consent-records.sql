-- APPLY 2026-08-10 — versioned AI-disclosure consent, append-only.
-- version alone is not evidence (files change); text_hash pins the bytes.

create table if not exists public.consent_records (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid references public.businesses(id) on delete cascade,
  user_id      uuid,
  audience     text not null check (audience in ('practitioner','client')),
  document     text not null default 'ai_disclosure',
  version      text not null,
  text_hash    text not null,
  accepted_at  timestamptz not null default now(),
  ip           text,
  user_agent   text,
  subject_ref  text
);
comment on table public.consent_records is
  'What a person agreed to, and PROOF of the exact words. version alone '
  'is not evidence — files change — so text_hash pins the bytes. '
  'Append-only: acceptance is a historical fact, and a consent record '
  'that can be edited is not consent.';
create index if not exists consent_records_biz_idx
  on public.consent_records (business_id, audience, accepted_at desc);
create index if not exists consent_records_user_idx
  on public.consent_records (user_id, audience, accepted_at desc)
  where user_id is not null;

alter table public.consent_records enable row level security;

drop policy if exists "consent: read own business" on public.consent_records;
create policy "consent: read own business" on public.consent_records
  for select to authenticated
  using (public.user_can_access_business(business_id));

-- Append-only for real, the same posture as audit_log: no update or
-- delete policy exists, and these triggers refuse even for a role that
-- bypasses RLS. A record of what someone agreed to that we can rewrite
-- is worth nothing in the argument it exists to settle.
create or replace function public.consent_records_immutable()
returns trigger language plpgsql as $$
begin
  raise exception 'consent_records is append-only (attempted % on %)',
    tg_op, tg_table_name;
end $$;

drop trigger if exists consent_records_no_update on public.consent_records;
create trigger consent_records_no_update before update on public.consent_records
  for each row execute function public.consent_records_immutable();

drop trigger if exists consent_records_no_delete on public.consent_records;
create trigger consent_records_no_delete before delete on public.consent_records
  for each row execute function public.consent_records_immutable();
