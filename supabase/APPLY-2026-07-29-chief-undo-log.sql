-- APPLY-2026-07-29-chief-undo-log.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- The log that makes undo possible.
--
-- THE GAP
--   action_registry classifies all 128 verbs by reversibility, and class A
--   means "cleanly undoable — a wrong one is an edit away from right". That
--   was a DESIGN JUDGMENT with nothing behind it: the readiness audit found
--   that restore_previous_site is the only verb a practitioner can actually
--   press to undo anything. Class A described a property nobody could use.
--
-- WHY chief_activity COULD NOT BE REUSED
--   It stores action_type, label, summary and nav — what happened, in
--   words. To REVERSE create_contact you need the id of the contact that was
--   created, and to reverse add_block_range you need the range that was
--   added. Neither survives in a summary string. This table stores the
--   action payload and the handler's return value, which together are what
--   an inverse is built from.
--
-- WHAT IS DELIBERATELY NOT STORED
--   The PRIOR state of an updated row. Undoing update_contact_status would
--   need the status it held before, and capturing before-images for every
--   write is a much larger change with real cost on every action. So update
--   verbs are NOT undoable in this pass and action_inverse says so out loud
--   rather than half-reversing them. Creates and paired toggles are.
--
-- RETENTION
--   Undo is a short-window affordance, not an audit trail — chief_activity
--   is the audit trail and is untouched. Rows here age out; the window is
--   enforced in code (action_inverse.UNDO_WINDOW_HOURS) so it can be tuned
--   without a migration.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

create table if not exists public.chief_undo_log (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid not null references public.businesses(id) on delete cascade,
  user_id      uuid,

  action_type  text not null,
  -- The action as executed (after reference resolution), and what the
  -- handler returned. Both are needed: the payload carries what was asked
  -- for, the result carries the ids of whatever got created.
  action_json  jsonb not null default '{}'::jsonb,
  result_json  jsonb not null default '{}'::jsonb,

  status       text not null default 'undoable'
               check (status in ('undoable','undone','superseded')),

  -- Set when undone, so the same action cannot be reversed twice.
  undone_at    timestamptz,
  undo_result  text,

  created_at   timestamptz not null default now(),

  -- An undone row must record when. Without this the double-undo guard is
  -- a convention rather than a constraint.
  constraint chief_undo_log_undone_has_a_time
    check (status <> 'undone' or undone_at is not null)
);

-- The only read that matters at speed: "what is the most recent thing I
-- could undo for this business".
create index if not exists idx_chief_undo_recent
  on public.chief_undo_log (business_id, created_at desc)
  where status = 'undoable';

alter table public.chief_undo_log enable row level security;

drop policy if exists chief_undo_owner_select on public.chief_undo_log;
create policy chief_undo_owner_select on public.chief_undo_log
  for select to authenticated
  using (exists (
    select 1 from public.businesses b
    where b.id = chief_undo_log.business_id and b.owner_id = auth.uid()
  ));

comment on table public.chief_undo_log is
  'Recent reversible Chief actions: the payload AND the handler result, which together are what an inverse action is built from. NOT the audit trail (that is chief_activity) — this is a short-window undo affordance. Update verbs are absent by design: reversing one needs the prior row state, which is not captured.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select
  (select count(*) from information_schema.tables
    where table_schema='public' and table_name='chief_undo_log') as table_ok,
  (select count(*) from pg_constraint
    where conrelid='public.chief_undo_log'::regclass and contype='c') as checks;
