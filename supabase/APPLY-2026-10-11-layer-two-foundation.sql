-- Layer Two foundation (2026-10-11): the turn id, the business brain, the nightly pass.
--
-- Additive only. Every statement is idempotent and nothing existing is rewritten:
-- no column changes type, no policy is loosened, and audit_log is not touched
-- (its hash covers a frozen column list, ledger_canonical_v2; the AI context
-- for a ledger row rides inside `payload`, which that hash already covers).
--
-- 1. Turn linkage. The app already sends a request id with every Chief message;
--    these columns let one id join a turn's model calls, archive row, drafts and
--    outcomes. response_id is the provider's message id (msg_...).
-- 2. business_brain_versions. One row per distinct brain a business has had:
--    its operating-profile revision, the nightly digest and the model lanes,
--    hashed into a fingerprint. Ledger rows name the version that acted.
-- 3. chief_reflection_runs. One row per business per day for the nightly brain
--    pass; the unique key is what makes a retry unable to double-bill or
--    double-write.
--
-- Owner reads go through public.is_business_owner (SECURITY DEFINER), the
-- pattern docs/RLS_MODEL.md requires to avoid the 42P17 recursion. Writes are
-- service-role only: no insert/update/delete policies exist for browser roles.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '60s';

-- ── 1. Turn linkage ────────────────────────────────────────────────────────
alter table public.api_usage
  add column if not exists turn_id text,
  add column if not exists lane text,
  add column if not exists provider text,
  add column if not exists response_id text,
  add column if not exists cache_creation_1h_tokens integer;
create index if not exists idx_api_usage_turn
  on public.api_usage (turn_id) where turn_id is not null;
comment on column public.api_usage.turn_id is
  'Chief turn id (the app''s request_id). Joins model calls to chief_conversations, agent_queue and chief_moves.';
comment on column public.api_usage.response_id is
  'Provider response id (Anthropic msg_...). Proof of which call produced an output.';

alter table public.chief_conversations
  add column if not exists turn_id text;
create index if not exists idx_chief_conversations_turn
  on public.chief_conversations (turn_id) where turn_id is not null;

alter table public.agent_queue
  add column if not exists turn_id text,
  add column if not exists reviewed_by uuid,
  add column if not exists original_subject text,
  add column if not exists original_body text;
comment on column public.agent_queue.original_body is
  'Chief''s draft as first written, kept when the owner edits it before sending. Set once; never overwritten.';
comment on column public.agent_queue.reviewed_by is
  'The user who approved or dismissed this row.';

alter table public.chief_moves
  add column if not exists turn_id text;

-- ── 2. Business brain versions ─────────────────────────────────────────────
create table if not exists public.business_brain_versions (
  id               uuid primary key default gen_random_uuid(),
  business_id      uuid not null references public.businesses(id) on delete cascade,
  version          integer not null check (version >= 1),
  fingerprint      text not null check (fingerprint ~ '^[0-9a-f]{64}$'),
  profile_revision integer not null default 0,
  rules_sha        text not null default '',
  digest           text not null default '',
  digest_sha       text not null default '',
  lanes            jsonb not null default '{}'::jsonb,
  reason           text not null default '',
  created_at       timestamptz not null default now(),
  unique (business_id, version)
);
create index if not exists idx_brain_versions_latest
  on public.business_brain_versions (business_id, version desc);
comment on table public.business_brain_versions is
  'Layer Two: each distinct brain (profile revision + nightly digest + model lanes) a business has had. Append-only.';

-- Append-only: a version is evidence. Deletes stay possible so the business
-- cascade and account deletion still work.
create or replace function public.business_brain_versions_no_update()
returns trigger language plpgsql set search_path = public as $$
begin
  raise exception 'business_brain_versions is append-only';
end $$;
drop trigger if exists business_brain_versions_no_update on public.business_brain_versions;
create trigger business_brain_versions_no_update
  before update on public.business_brain_versions
  for each row execute function public.business_brain_versions_no_update();

alter table public.business_brain_versions enable row level security;
drop policy if exists business_brain_versions_owner_read on public.business_brain_versions;
create policy business_brain_versions_owner_read on public.business_brain_versions
  for select using (public.is_business_owner(business_brain_versions.business_id));

-- ── 3. Nightly brain pass runs ─────────────────────────────────────────────
create table if not exists public.chief_reflection_runs (
  id              uuid primary key default gen_random_uuid(),
  business_id     uuid not null references public.businesses(id) on delete cascade,
  run_date        date not null,
  status          text not null default 'running'
                    check (status in ('running', 'done', 'failed')),
  model           text not null default '',
  input_tokens    integer not null default 0,
  output_tokens   integer not null default 0,
  cost_cents      numeric(10, 4) not null default 0,
  proposals_filed integer not null default 0,
  brain_version   integer,
  error           text not null default '',
  started_at      timestamptz not null default now(),
  finished_at     timestamptz,
  unique (business_id, run_date)
);
create index if not exists idx_reflection_runs_recent
  on public.chief_reflection_runs (business_id, run_date desc);

alter table public.chief_reflection_runs enable row level security;
drop policy if exists chief_reflection_runs_owner_read on public.chief_reflection_runs;
create policy chief_reflection_runs_owner_read on public.chief_reflection_runs
  for select using (public.is_business_owner(chief_reflection_runs.business_id));

revoke insert, update, delete on public.business_brain_versions, public.chief_reflection_runs
  from anon, authenticated;

commit;

-- Verify (read-only):
-- select column_name from information_schema.columns
--  where table_schema='public' and table_name='api_usage'
--    and column_name in ('turn_id','lane','provider','response_id','cache_creation_1h_tokens');
-- select relname, relrowsecurity from pg_class
--  where relname in ('business_brain_versions','chief_reflection_runs');
-- select tablename, policyname, cmd from pg_policies
--  where tablename in ('business_brain_versions','chief_reflection_runs');
--
-- Rollback (only before any code depends on it):
--   drop table if exists public.chief_reflection_runs;
--   drop table if exists public.business_brain_versions;
--   drop function if exists public.business_brain_versions_no_update();
--   alter table public.chief_moves drop column if exists turn_id;
--   alter table public.agent_queue drop column if exists turn_id, drop column if exists reviewed_by,
--     drop column if exists original_subject, drop column if exists original_body;
--   alter table public.chief_conversations drop column if exists turn_id;
--   alter table public.api_usage drop column if exists turn_id, drop column if exists lane,
--     drop column if exists provider, drop column if exists response_id,
--     drop column if exists cache_creation_1h_tokens;
