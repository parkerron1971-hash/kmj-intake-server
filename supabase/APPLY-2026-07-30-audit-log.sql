-- APPLY-2026-07-30-audit-log.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Rails Arc 4: the unified audit log.
--
-- THE GAP
--   The action registry classifies 128 verbs by effect+reversibility,
--   but execution left no unified record: chief_activity keeps a
--   240-char summary and SKIPS FAILED ACTIONS entirely, chief_undo_log
--   only holds what can be inverted, gl_admin_actions and
--   period_edit_overrides cover their own corners. Nobody could answer
--   "what did Chief do, and did it work" from one table. This is that
--   table — a trust feature for the practitioner and protection for
--   the platform.
--
-- APPEND-ONLY BY CONSTRUCTION
--   Service-role INSERT only (no authenticated insert policy), owner
--   SELECT via the business, and NO update/delete policies for anyone
--   — an audit row that can be edited is a diary, not an audit.
--
-- SCOPE (v1): every action Chief executes in chat — including
--   failures and navigation. Scheduler/rules/agent writers adopt the
--   same audit_log.record() helper opportunistically.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

create table if not exists public.audit_log (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid not null references public.businesses(id) on delete cascade,

  actor_type   text not null check (actor_type in ('user','chief','agent','system')),
  actor_id     text,          -- user uuid / agent name

  verb         text not null, -- action_registry verb or endpoint verb
  target_type  text,
  target_id    text,

  ok           boolean not null default true,
  error        text,
  summary      text,          -- one human-readable line
  payload      jsonb not null default '{}'::jsonb,  -- what was asked
  result       jsonb not null default '{}'::jsonb,  -- what came back (capped)

  source       text,          -- desktop|mobile|voice|system|webhook
  created_at   timestamptz not null default now()
);

create index if not exists idx_audit_log_biz_recent
  on public.audit_log (business_id, created_at desc);

create index if not exists idx_audit_log_failures
  on public.audit_log (business_id, created_at desc)
  where ok = false;

alter table public.audit_log enable row level security;

drop policy if exists audit_log_owner_select on public.audit_log;
create policy audit_log_owner_select on public.audit_log
  for select to authenticated
  using (exists (
    select 1 from public.businesses b
    where b.id = audit_log.business_id and b.owner_id = auth.uid()
  ));
-- No INSERT/UPDATE/DELETE policies on purpose: service-role writes,
-- nothing edits, nothing deletes (cascade on business deletion only).

comment on table public.audit_log is
  'Unified append-only audit: every executed action (Chief chat v1; other writers adopt audit_log.record()), INCLUDING failures - unlike chief_activity which skips them. Service-role insert only; owner read; no update/delete policies ever.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select
  (select count(*) from information_schema.tables
    where table_schema='public' and table_name='audit_log') as table_ok,
  (select count(*) from pg_policies
    where schemaname='public' and tablename='audit_log') as policies_should_be_one;
