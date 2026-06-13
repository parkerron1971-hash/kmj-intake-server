-- 2026_06_13_chief_jobs.sql
-- Feature 2 (cross-device Chief) — queued desk jobs. From the phone you
-- tell Chief to start something heavy (rebuild my site, draft the monthly
-- report, reconcile the month); it enqueues a job that runs server-side
-- and lands FINISHED on your desktop. Completion notices ride on the
-- chief_activity recap rail (source='system'), so the desktop announces
-- "your site rebuild is ready" via the same "while you were away" card.
--
-- Writes go through the Railway service role (the job runner). RLS lets a
-- practitioner read ONLY their own jobs (own-row, no cross-table EXISTS).

create table if not exists public.chief_jobs (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null,
  business_id uuid not null,
  kind        text not null,                     -- 'rebuild_site' | (future: 'monthly_report', 'reconcile_month')
  status      text not null default 'queued',    -- queued | running | done | failed
  source      text not null default 'desktop',   -- originating device
  params      jsonb not null default '{}'::jsonb,
  result      jsonb,                             -- kind-specific success payload
  error       text,                              -- failure message, if any
  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  finished_at timestamptz
);

create index if not exists idx_chief_jobs_user on public.chief_jobs (user_id, created_at desc);
create index if not exists idx_chief_jobs_active
  on public.chief_jobs (user_id, status) where status in ('queued', 'running');

alter table public.chief_jobs enable row level security;

drop policy if exists chief_jobs_select_own on public.chief_jobs;
create policy chief_jobs_select_own on public.chief_jobs
  for select using (auth.uid() = user_id);

-- The runner writes as service_role (bypasses RLS); no insert/update
-- policy needed for authenticated. Practitioners only ever READ.
grant select, insert, update, delete on public.chief_jobs to service_role;

-- Live "Chief is working on…" / "done" updates rely on realtime; add the
-- table to the publication idempotently.
do $$
begin
  begin
    alter publication supabase_realtime add table public.chief_jobs;
  exception
    when duplicate_object then null;
    when undefined_object then null;
  end;
end $$;
