-- APPLY-2026-08-30-esign-docuseal.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Rails demand-driven arc: e-sign adapter #2. BoldSign → DocuSeal.
-- Cost and shape (BoldSign's Enterprise API tier starts ~$30/mo;
-- DocuSeal Cloud Pro is $20 a seat with unlimited signature requests
-- and webhooks included). `provider` was a column from day one for
-- exactly this reason: the seam outlives the first vendor.
--
-- WHAT THIS DOES NOT DO, DELIBERATELY:
--
--   * It does not rewrite existing rows. A row that says 'boldsign'
--     IS a boldsign document — it carries a boldsign document id and
--     was signed, or not, on boldsign's servers. Backfilling it to
--     'docuseal' would not make that true, it would only make the
--     table lie about where the executed copy lives. The refresh
--     endpoint reads this column and declines to ask DocuSeal about
--     another provider's id.
--
--   * It does not touch the status CHECK. Our status vocabulary did
--     not change when the provider did — that is the whole point of
--     map_provider_status — and 'revoked' stays legal because rows
--     written under adapter #1 still carry it, even though nothing
--     emits it any more.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

alter table public.esign_documents
  alter column provider set default 'docuseal';

comment on table public.esign_documents is
  'Documents sent for e-signature (DocuSeal adapter #2; rows predating 2026-08-30 carry provider=boldsign and are read-only history). document_id is the provider''s SUBMISSION id. Status refreshes on demand from the provider; completion emits contract_signed on the event spine. Writes via owner-gated /esign endpoints only.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
-- Expect: default_now = 'docuseal', and the legacy rows still counted
-- under their own provider rather than silently converted.
select
  (select column_default from information_schema.columns
    where table_schema='public' and table_name='esign_documents'
      and column_name='provider')                      as default_now,
  (select count(*) from public.esign_documents
    where provider='boldsign')                         as legacy_rows_preserved,
  (select count(*) from public.esign_documents
    where provider='docuseal')                         as docuseal_rows;
