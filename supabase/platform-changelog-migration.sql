-- platform-changelog-migration.sql
-- The Business Chief's memory of the business itself (2026-07-04,
-- Kevin: "I will forget a lot of things — Chief knowing changes helps
-- maintain the function of the business").
--
-- platform_changelog = the operator's log: config flips, migrations
-- run, decisions made, pending follow-ups. Written by the Business
-- Chief (log_platform_note action) when Kevin tells it things, or via
-- the Mission Control endpoint. Shipped-code history comes free from
-- the GitHub merged-PR feed (no table needed).
--
-- Service-role only (RLS enabled, no policies) — operator data.

create table if not exists public.platform_changelog (
  id         bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  category   text not null default 'note'
             check (category in ('shipped', 'config', 'decision', 'pending', 'note')),
  title      text not null,
  detail     text,
  status     text not null default 'done'
             check (status in ('done', 'pending')),
  resolved_at timestamptz
);
create index if not exists platform_changelog_created_idx
  on public.platform_changelog (created_at desc);
create index if not exists platform_changelog_pending_idx
  on public.platform_changelog (status) where status = 'pending';

alter table public.platform_changelog enable row level security;

comment on table public.platform_changelog is
  'Operator log for the Business Chief: config changes, decisions, pending items. Chief reads it in every snapshot and writes via log_platform_note.';
