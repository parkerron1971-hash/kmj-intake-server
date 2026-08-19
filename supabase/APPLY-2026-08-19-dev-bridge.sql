-- Dev Bridge (2026-08-19): Mission Control's Dev Desk dispatches dev tasks.
-- The local lane is polled by Solution Space (Kevin's Electron app), which
-- opens a Claude Code session for each task and reports status back. The
-- cloud lane records @claude build issues so both kinds of build live in one
-- list. Service-role only, like platform_changelog: RLS on, no policies.
-- Idempotent; apply after merge.

create table if not exists public.dev_tasks (
  id           uuid primary key default gen_random_uuid(),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  lane         text not null check (lane in ('local', 'cloud')),
  status       text not null default 'queued'
               check (status in ('queued', 'dispatched', 'picked_up', 'opened',
                                 'working', 'done', 'failed', 'cancelled')),
  title        text not null,
  details      text,
  repo         text,
  project_path text,
  issue_url    text,
  -- Lets the session working the task post its own completion report without
  -- holding a device token; scoped to this one task.
  report_key   text,
  -- Conversation on the task: [{"from": "kevin"|"device"|"dev", "text", "at"}]
  notes        jsonb not null default '[]'::jsonb,
  picked_up_at timestamptz,
  finished_at  timestamptz
);

create index if not exists dev_tasks_queue_idx
  on public.dev_tasks (created_at desc)
  where status = 'queued';

alter table public.dev_tasks enable row level security;

create table if not exists public.dev_bridge_devices (
  id           uuid primary key default gen_random_uuid(),
  created_at   timestamptz not null default now(),
  name         text not null,
  -- sha256 hex of the device token; the plaintext is shown once at pairing.
  token_hash   text not null unique,
  last_seen_at timestamptz,
  revoked      boolean not null default false
);

alter table public.dev_bridge_devices enable row level security;
