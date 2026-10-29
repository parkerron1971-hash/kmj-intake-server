-- ChurchSavvy Planning, step 3: asks and reminders reach people (design
-- canvas Ct88v7pxpq5a4PGYX3MuQQ, board 6 "Nobody forgets their Sunday" and
-- board 8's "How I hear"). Server-only, like the rest of serve_*.
--
--   serve_prefs.email            an email copy of every ask and the day-before
--                                reminder (board 8, on by default). A member
--                                with no phone alerts gets the email anyway:
--                                "An ask always reaches you one way or another."
--   serve_prefs.often            may now be empty: a member who only set How
--                                I hear hasn't said how often.
--   serve_assignments.leader_told_at   no answer five days before Sunday: the
--                                team's leader was told, with who else could
--                                take it.
--   serve_assignments.week_sent_at / day_sent_at / morning_sent_at
--                                the three reminders before a Sunday they said
--                                yes to (a week before, Saturday 6 PM, that
--                                morning), each once.
--   serve_assignments.swap_told_at   the person asked to cover was told
--                                (once per ask: asking someone else clears it).
-- notified_at and nudged_at were already there (step 1). Idempotent.
begin;

alter table public.serve_prefs add column if not exists email boolean not null default true;
alter table public.serve_prefs alter column often drop not null;

alter table public.serve_assignments add column if not exists leader_told_at timestamptz;
alter table public.serve_assignments add column if not exists week_sent_at timestamptz;
alter table public.serve_assignments add column if not exists day_sent_at timestamptz;
alter table public.serve_assignments add column if not exists morning_sent_at timestamptz;
alter table public.serve_assignments add column if not exists swap_told_at timestamptz;

-- The sweep reads what's still to say for the coming weeks, church by church.
create index if not exists serve_assignments_to_remind on public.serve_assignments (business_id, service_id)
  where status in ('asked', 'yes');

commit;
