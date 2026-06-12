-- Arc 29 — single-leader election for in-process scheduled jobs.
-- One singleton row; the app leases leadership via atomic PATCH (see
-- scheduler_lock.py). Until this is applied the app defaults to LEADER
-- (single-replica safe), so applying it is only required before running
-- 2+ replicas. Service-role only (no RLS policies — backend-internal).

create table if not exists public.scheduler_lease (
  id          text primary key,
  holder      text,
  expires_at  timestamptz not null,
  updated_at  timestamptz not null default now()
);

-- Seed the global row (the app also self-seeds, but this avoids a
-- first-boot race between replicas).
insert into public.scheduler_lease (id, holder, expires_at)
values ('global', null, now() - interval '1 minute')
on conflict (id) do nothing;

alter table public.scheduler_lease enable row level security;

-- Rollback: drop table public.scheduler_lease;
