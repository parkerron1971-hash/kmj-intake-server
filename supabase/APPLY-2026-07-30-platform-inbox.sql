-- APPLY-2026-07-30-platform-inbox.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- The platform owner's inbox — mail for the business OF the platform.
--
-- THE GAP
--   MX for mysolutionist.app already delivers every address at the domain
--   to Resend, and /email/inbound routes contact replies to each business's
--   Email Hub. But mail addressed to the PLATFORM itself — kevin@, support@,
--   hello@ — matched no contact and was dropped with "unknown_sender".
--   Kevin literally could not receive a vendor's account-verification email
--   at his own domain. This table is where that mail now lands; Mission
--   Control reads it.
--
-- WHY NOT email_replies
--   email_replies is business-scoped (business_id NOT NULL, owner RLS) and
--   truncates HTML to 5 KB. Platform mail belongs to no business, and a
--   verification email's click-through link routinely lives past 5 KB of
--   HTML — truncation would break the one thing the inbox exists to do.
--
-- ACCESS MODEL
--   Service-role only: RLS is enabled with NO policies on purpose. The
--   frontend never touches this table over PostgREST — reads go through the
--   owner-gated /platform/inbox endpoints (require_owner, same as every
--   other Mission Control surface).
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

create table if not exists public.platform_emails (
  id           uuid primary key default gen_random_uuid(),

  to_address   text not null,
  from_email   text not null,
  from_name    text not null default '',
  subject      text not null default '',

  body_text    text not null default '',
  -- Full HTML, not a preview: verification links must survive intact.
  body_html    text,

  message_id   text,
  in_reply_to  text,

  -- true = landed here because nothing else claimed it (unknown sender,
  -- unrecognized address); false = explicitly addressed to a named
  -- platform address (kevin@, support@, ...).
  catchall     boolean not null default false,

  read         boolean not null default false,
  received_at  timestamptz not null default now()
);

create index if not exists idx_platform_emails_recent
  on public.platform_emails (received_at desc);

create index if not exists idx_platform_emails_unread
  on public.platform_emails (received_at desc)
  where read = false;

alter table public.platform_emails enable row level security;
-- No policies: service-role only, by design (see ACCESS MODEL above).

comment on table public.platform_emails is
  'Mission Control inbox: inbound mail addressed to the platform itself (kevin@/support@/hello@ at the inbound domain) plus catch-all for otherwise-unresolved mail. Service-role only — read through the owner-gated /platform/inbox endpoints, never PostgREST. Full body_html kept on purpose: verification links must survive.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select
  (select count(*) from information_schema.tables
    where table_schema='public' and table_name='platform_emails') as table_ok,
  (select count(*) from pg_indexes
    where schemaname='public' and tablename='platform_emails') as indexes,
  (select count(*) from pg_policies
    where schemaname='public' and tablename='platform_emails') as policies_should_be_zero;
