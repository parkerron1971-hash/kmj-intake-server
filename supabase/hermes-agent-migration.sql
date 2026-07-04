-- hermes-agent-migration.sql
-- The watcher fleet's visible trail (2026-07-04): one brain (Business
-- Chief), many senses (watchers). Every watcher tick writes a run row
-- here; findings go to platform_changelog tagged with the agent name —
-- so Mission Control -> Agents shows exactly who saw what, when, and
-- how it flowed to Chief.

create table if not exists public.platform_agent_runs (
  id          bigint generated always as identity primary key,
  agent       text not null,                -- 'hermes' | future watchers
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  ok          boolean not null default true,
  findings    integer not null default 0,
  summary     text,
  details     jsonb not null default '{}'::jsonb
);
create index if not exists platform_agent_runs_agent_idx
  on public.platform_agent_runs (agent, started_at desc);

alter table public.platform_agent_runs enable row level security;

-- Findings carry their author: which agent wrote this log entry.
alter table public.platform_changelog
  add column if not exists agent text;

comment on table public.platform_agent_runs is
  'Watcher tick history (Hermes etc.). Findings land in platform_changelog with agent set; the Business Chief reads both.';
