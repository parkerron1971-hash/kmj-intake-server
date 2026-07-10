-- APPLY-2026-07-10-chief-scheduled-actions.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- "Schedule anything" (Kevin's adaptive-Chief directive): Chief can now
-- defer ANY of its own actions to a future time — one-shot or
-- recurring. "Remind me about the task tomorrow at 9" = a scheduled
-- notify_practitioner; "text Marcus Friday morning" = a scheduled
-- send_sms. One primitive x the whole action toolkit.

create table if not exists public.chief_scheduled_actions (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid not null references public.businesses(id),
  owner_id     uuid,
  label        text not null,          -- human description ("Remind: send invoice")
  action       jsonb not null,         -- the [ACTION:{...}] payload to execute
  run_at       timestamptz not null,
  recurrence   text,                   -- null | 'daily' | 'weekdays' | 'weekly'
  status       text not null default 'queued',  -- queued|done|failed|cancelled
  last_error   text,
  last_run_at  timestamptz,
  created_at   timestamptz not null default now()
);

create index if not exists idx_csa_due
  on public.chief_scheduled_actions (run_at) where status = 'queued';
create index if not exists idx_csa_biz
  on public.chief_scheduled_actions (business_id, status);

alter table public.chief_scheduled_actions enable row level security;

-- Chief writes + the scheduler executes server-side (service role
-- bypasses RLS). The owner can SEE their schedule (future UI).
drop policy if exists csa_owner_select on public.chief_scheduled_actions;
create policy csa_owner_select on public.chief_scheduled_actions
  for select to authenticated
  using (exists (
    select 1 from public.businesses b
    where b.id = chief_scheduled_actions.business_id
      and b.owner_id = auth.uid()
  ));

comment on table public.chief_scheduled_actions is
  'Chief''s deferred actions: any ACTION_HANDLERS verb scheduled for later (one-shot or recurring). Executed by chief_scheduler.due_tick.';

notify pgrst, 'reload schema';
select count(*) as chief_scheduled_actions_ok from public.chief_scheduled_actions;
