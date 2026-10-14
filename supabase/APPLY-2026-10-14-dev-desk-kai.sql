-- KAI on the phone (2026-10-14). KAI is the orchestrator inside Solution
-- Space, Kevin's desktop app: one long-lived conversation that opens, briefs
-- and watches his coding sessions. This gives it a line to the Dev Desk, so
-- Kevin can pick the conversation up on his phone, speak to it, and answer
-- the approvals its workers are stopped on.
--
--   dev_kai_messages   KAI's conversation, both ways. The desktop mirrors
--                      its own line here as it happens (via 'desktop', the
--                      desktop's own entry id, so a re-send is a no-op);
--                      what Kevin sends from the phone waits here (via
--                      'phone', delivered_at null) until the desktop types
--                      it into KAI and acks it. kind 'decision' is his
--                      answer to an approval, carried the same way.
--   dev_bridge_devices.kai_state        the desktop's live read: is KAI
--                      running or busy, is Kevin at the machine, and the
--                      approvals waiting on him.
--   dev_bridge_devices.kai_watch_until  the phone has KAI's thread open;
--                      until then the desktop checks for his messages every
--                      few seconds instead of every poll.
--
-- Service-role only, like the rest of the bridge: RLS on, no policies, no
-- browser-role grants. Additive and idempotent; old code never reads any of
-- it, and the new routes fail loud naming this file without it.
begin;

create table if not exists public.dev_kai_messages (
  id           uuid primary key default gen_random_uuid(),
  created_at   timestamptz not null default now(),
  -- Set on insert and on ack: the phone's poll reads what changed since.
  updated_at   timestamptz not null default now(),
  -- When it was said: the desktop line's own time, or the server's for a
  -- message from the phone. The conversation is ordered by it.
  at           timestamptz not null default now(),
  device_id    uuid references public.dev_bridge_devices(id) on delete cascade,
  kind         text not null
               check (kind in ('you', 'kai', 'event', 'tool', 'error', 'decision')),
  via          text not null default 'desktop' check (via in ('desktop', 'phone')),
  text         text not null default '',
  -- What Kevin said aloud, so KAI answers the way it would speak.
  spoken       boolean not null default false,
  -- A phone message the desktop has typed into KAI.
  delivered_at timestamptz,
  -- Small and kind-specific: a tool's name and whether it failed; a
  -- decision's request number and verdict.
  meta         jsonb
);

create index if not exists dev_kai_messages_at_idx
  on public.dev_kai_messages (at desc);
create index if not exists dev_kai_messages_updated_idx
  on public.dev_kai_messages (updated_at);
create index if not exists dev_kai_messages_inbox_idx
  on public.dev_kai_messages (at)
  where via = 'phone' and delivered_at is null;

alter table public.dev_kai_messages enable row level security;
revoke all on public.dev_kai_messages from anon, authenticated;

alter table public.dev_bridge_devices
  add column if not exists kai_state jsonb;
alter table public.dev_bridge_devices
  add column if not exists kai_watch_until timestamptz;

commit;
