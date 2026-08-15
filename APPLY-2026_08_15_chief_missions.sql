-- APPLY-2026_08_15_chief_missions.sql
-- ─────────────────────────────────────────────────────────────────────
-- THE MISSION OBJECT (Jarvis arc step 3, Kevin 8/14/15).
--
-- "Get my unpaid invoices collected" is not one action — it is a PLAN:
-- list → draft reminders → the practitioner approves → send → schedule
-- follow-ups → report back. Until now Chief could only do one move per
-- ask and forgot everything between turns. A mission is the persistent
-- plan: proposed as a draft, started on approval, executed step by step
-- THROUGH the existing action machinery (every step dispatches through
-- _execute_actions, so the Class-C trust gate, the per-turn cap and the
-- ledger all apply), pausing at consequential steps until the
-- practitioner says go — across turns, across days.
--
-- Steps live as JSONB, not child rows: a mission is read and written as
-- one object by one engine, never queried per-step, and the shape is
-- versioned by the engine that owns it (chief_missions.py). Same
-- reasoning as businesses.settings.
--
-- RLS mirrors the invoices trio exactly: owner ALL via businesses,
-- seat-member read, seat-writer write. Missions are everyday operational
-- surface — the same people who can see the queue can see the plan.
-- (The new-table-owner-RLS-gap class: the OWNER policy is the one that
-- must exist or every new signup is locked out.)

create table if not exists public.chief_missions (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references public.businesses(id) on delete cascade,

  title         text not null,
  -- The practitioner's ask, verbatim — the mission's contract. The
  -- report at the end answers THIS, not the steps.
  goal          text not null default '',

  -- draft → active → awaiting_approval ⇄ active → completed
  --                         └→ paused (a step failed)   └→ abandoned
  status        text not null default 'draft'
                check (status in ('draft','active','awaiting_approval',
                                  'paused','completed','abandoned')),

  -- [{id, title, action:{type,...}, gate:bool, status, result_label}, ...]
  steps         jsonb not null default '[]'::jsonb,
  current_step  int not null default 0,

  -- What happened, written when the mission ends (any terminal status).
  report        text not null default '',

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists chief_missions_business_status_idx
  on public.chief_missions (business_id, status);

alter table public.chief_missions enable row level security;

drop policy if exists business_member_access on public.chief_missions;
create policy business_member_access on public.chief_missions
  for all
  using (business_id in (select id from public.businesses
                         where owner_id = auth.uid()))
  with check (business_id in (select id from public.businesses
                              where owner_id = auth.uid()));

drop policy if exists tenant_member_read on public.chief_missions;
create policy tenant_member_read on public.chief_missions
  for select
  using (is_business_member(business_id));

drop policy if exists tenant_writer_write on public.chief_missions;
create policy tenant_writer_write on public.chief_missions
  for all
  using (is_business_writer(business_id))
  with check (is_business_writer(business_id));

comment on table public.chief_missions is
  'Chief''s multi-step plans (Jarvis arc). Steps execute through '
  'chief_of_staff._execute_actions so the Class-C trust gate and ledger '
  'apply; class-C steps pause as awaiting_approval until the practitioner '
  'advances the mission.';
