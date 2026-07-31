-- APPLY-2026-07-30-contractor-tax-profile.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Rails Arc 2: 1099-NEC drafts — the W-9 data for manually-paid
-- contractors.
--
-- Stripe Express contractors need none of this (Stripe Tax Reporting
-- owns their W-9 + 1099-NEC). These columns exist for the rows the
-- 1099 Summary flags "Manual 1099 needed": contractors paid outside
-- Stripe whose business must file a 1099-NEC itself.
--
-- THE TIN IS SSN-CLASS DATA:
--   tin_encrypted = Fernet ciphertext (key = TIN_ENCRYPTION_KEY env on
--   Railway, never in the DB). tin_last4 exists so UIs can show
--   "***-**-1234" without a decrypt round-trip. The full TIN decrypts
--   in exactly one place: the owner-gated draft-PDF endpoint.
--
-- WE ARE THE PREP TOOL, NOT THE FILER (ruling): drafts only, the
-- business files. No e-file, no TIN matching, no state filing.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

alter table public.contractors
  add column if not exists tax_name       text,
  add column if not exists tax_id_type    text
      check (tax_id_type is null or tax_id_type in ('ssn','ein')),
  add column if not exists tin_encrypted  text,
  add column if not exists tin_last4      text,
  add column if not exists tax_address    jsonb not null default '{}'::jsonb,
  add column if not exists w9_received_at timestamptz;

comment on column public.contractors.tin_encrypted is
  'Fernet ciphertext of the contractor TIN (SSN/EIN). Key = TIN_ENCRYPTION_KEY env, never stored. Decrypted only inside the owner-gated 1099 draft-PDF endpoint. Display uses tin_last4.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select count(*) as tax_columns_ok from information_schema.columns
 where table_schema='public' and table_name='contractors'
   and column_name in ('tax_name','tax_id_type','tin_encrypted','tin_last4','tax_address','w9_received_at');
