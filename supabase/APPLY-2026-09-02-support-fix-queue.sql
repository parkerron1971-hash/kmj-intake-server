-- APPLY-2026-09-02-support-fix-queue.sql
-- The fix queue: what turns a reported problem into work that gets done.
--
-- Before this, support_tickets and dev_tasks were two lists with nothing
-- between them. A practitioner reported a broken thing; someone retyped it
-- into the Dev Desk by hand; the fix shipped; and nothing walked back — not
-- to the ticket, and not to the person who reported it.
--
-- One table closes that gap. support_triage carries the operator's side of
-- a ticket: how bad it is, where it is in the fix pipeline, which dev task
-- is fixing it, and which other tickets are the same problem.
--
-- WHY A SEPARATE TABLE AND NOT COLUMNS ON support_tickets:
-- support_tickets is TENANT-READABLE (tickets_tenant_select, added by the
-- support-tickets migration in the frontend repo). A practitioner can read
-- every column of their own ticket with select=*. Operator judgement —
-- severity, "won't fix", the internal note explaining why something waits —
-- must never be on that row. Service-role only, RLS on with no policies:
-- the same posture as dev_tasks and platform_changelog.
--
-- Idempotent; apply after merge.

create table if not exists public.support_triage (
  ticket_id    uuid primary key
               references public.support_tickets(id) on delete cascade,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),

  -- How much it hurts. 'blocker' = they cannot work; 'high' = a real
  -- feature is broken or money is involved; 'normal' = everything else;
  -- 'low' = cosmetic or a nice-to-have.
  severity     text not null default 'normal'
               check (severity in ('blocker', 'high', 'normal', 'low')),

  -- Where it is in the pipeline. Deliberately NOT support_tickets.status:
  -- that column's CHECK is open/in_progress/resolved and Mission Control's
  -- panel indexes a lookup table by it (NEXT_STATUS[t.status].map(...)),
  -- so widening it would blank the panel on the first row carrying a new
  -- value. This column is additive and old UI never sees it.
  --   new      — nobody has looked at it
  --   triaged  — severity set, ready to be picked up
  --   queued   — a dev task exists and is waiting
  --   fixing   — that dev task is running
  --   shipped  — the fix is done, the practitioner has NOT been told
  --   answered — the practitioner has been told (the loop is closed)
  --   wont_fix — a decision, with the reason in note
  --   duplicate— the same problem as duplicate_of
  fix_state    text not null default 'new'
               check (fix_state in ('new', 'triaged', 'queued', 'fixing',
                                    'shipped', 'answered', 'wont_fix',
                                    'duplicate')),

  -- Normalized grouping key ('bug:booking:cancel-button'). Two tickets
  -- sharing it are the same underlying problem reported twice, which is
  -- the signal that decides what gets fixed first.
  problem_key  text,
  duplicate_of uuid references public.support_tickets(id) on delete set null,

  -- The fix. One direction only: dev_tasks stays untouched, and the walk-
  -- back (task done -> ticket shipped) reads through this column.
  dev_task_id  uuid references public.dev_tasks(id) on delete set null,

  -- Operator-only. This is the column the separate table exists for.
  note         text,
  -- 'auto' when the heuristic set it, otherwise the owner's email.
  triaged_by   text,

  queued_at         timestamptz,
  shipped_at        timestamptz,
  first_response_at timestamptz,
  closed_at         timestamptz
);

-- The queue read: everything not yet closed, worst first.
create index if not exists support_triage_open_idx
  on public.support_triage (fix_state, severity, updated_at desc);

-- Clustering repeat reports of one problem.
create index if not exists support_triage_problem_idx
  on public.support_triage (problem_key)
  where problem_key is not null;

-- The walk-back: dev task finished -> which ticket was that?
create index if not exists support_triage_dev_task_idx
  on public.support_triage (dev_task_id)
  where dev_task_id is not null;

-- updated_at trigger — set_updated_at_timestamp() is defined by the
-- support-tickets migration (frontend repo) and redefined safely there;
-- recreated here so apply order cannot matter.
create or replace function public.set_updated_at_timestamp()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_support_triage_updated on public.support_triage;
create trigger trg_support_triage_updated
  before update on public.support_triage
  for each row execute function public.set_updated_at_timestamp();

-- Service-role only. RLS on, no policies: every other role is denied,
-- which is the reachability this table should have.
alter table public.support_triage enable row level security;
revoke all on public.support_triage from anon, authenticated;

-- ────────────────────────────────────────────────────────────────────
-- VERIFICATION (run after applying)
--
--   select to_regclass('public.support_triage') is not null as exists;
--   select relname, relrowsecurity from pg_class
--    where relname = 'support_triage';                  -- expect t
--   select count(*) from pg_policies
--    where tablename = 'support_triage';                -- expect 0
--   select count(*) from public.support_triage;         -- expect 0 (the
--      server backfills a row per untriaged ticket on the first queue read)
-- ────────────────────────────────────────────────────────────────────
