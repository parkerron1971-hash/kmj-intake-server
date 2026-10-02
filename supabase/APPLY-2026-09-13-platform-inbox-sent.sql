-- APPLY-2026-09-13-platform-inbox-sent.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Compose from the Mission Control inbox.
--
-- The inbox could receive and reply, but not start a thread: Kevin
-- could answer someone who had already written to kevin@, and could
-- not write first. Compose sends through send_via_resend like every
-- platform send (suppression-gated), from one of the platform's own
-- addresses, and the sent mail is recorded HERE so the operator can
-- see what went out.
--
-- `direction` tells the two apart. Every row that exists today is
-- inbound, which is what the default says. A sent row keeps the same
-- column meanings — to_address is who it went TO, from_email is the
-- platform address it went FROM — so a sent row reads the way the
-- envelope does, not the way the inbox list does.
--
-- Code is fail-soft without this: the inbox list retries without the
-- direction filter and compose still sends, but reports the send as
-- unrecorded until this is applied.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

alter table public.platform_emails
  add column if not exists direction text not null default 'inbound';

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'platform_emails_direction_check'
  ) then
    alter table public.platform_emails
      add constraint platform_emails_direction_check
      check (direction in ('inbound', 'sent'));
  end if;
end $$;

-- Resend's id for a sent row, so a bounce / complaint webhook can be
-- matched back to what we sent. NULL on inbound rows.
alter table public.platform_emails
  add column if not exists resend_id text;

create index if not exists idx_platform_emails_direction_recent
  on public.platform_emails (direction, received_at desc);

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select
  (select count(*) from information_schema.columns
    where table_schema='public' and table_name='platform_emails'
      and column_name in ('direction', 'resend_id')) as columns_ok,   -- expect 2
  (select count(*) from public.platform_emails where direction <> 'inbound') as sent_rows;  -- expect 0 right after apply
