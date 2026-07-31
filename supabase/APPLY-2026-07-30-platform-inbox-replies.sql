-- APPLY-2026-07-30-platform-inbox-replies.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Replies from the Mission Control inbox.
--
-- The inbox shipped read-only; Kevin could receive at kevin@ but not
-- answer. Replies go out through the same send_via_resend path as all
-- platform mail (suppression-gated), from the address the message was
-- addressed to, and are appended here so the thread stays visible on
-- the message row it belongs to.
--
-- jsonb array, not a table: platform reply volume is one operator's
-- correspondence, not a mail store. Each element:
--   {"body": ..., "sent_at": ..., "resend_id": ...}
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

alter table public.platform_emails
  add column if not exists replies jsonb not null default '[]'::jsonb;

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select
  (select count(*) from information_schema.columns
    where table_schema='public' and table_name='platform_emails'
      and column_name='replies') as replies_column_ok;
