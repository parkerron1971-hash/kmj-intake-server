-- APPLY-2026-11-13-church-mail-room.sql
--
-- The Email room's church mail (church_mail_room.py). Kevin, 2026-11-13,
-- on the mock (artifact HuNVNSzCydvvzJ4vE5iu88): "this is good build it".
-- Each person reads, answers and writes church mail in the app; a shared
-- box shows who answered so nobody answers twice; each box keeps its Sent.
--
--   church_mail          + direction      'in' (came to a box, as today) or
--                                          'out' (sent from a box in the room,
--                                          or a reply by email that went out
--                                          as the box)
--                        + read_by        the logins that opened it (a
--                                          shared box's mail is read per
--                                          person)
--                        + answered_at,   who answered it, and when (from the
--                          answered_name  room, or by replying to the copy)
--                        + sent_by        the login that sent it from the room
--                        outcome          + 'sent'
--   church_mail_people   one row a login that changed its own setting:
--                        copies (false = reads church mail in the room only,
--                        no copy at their own email)
--
-- Additive only: one transaction, safe to run twice, nothing dropped. Every
-- existing row becomes direction 'in', unread, unanswered. Apply before the
-- code that reads it (until then the room's reads fail and it says so;
-- mail keeps arriving and being copied exactly as today).
begin;

set local lock_timeout = '5s';

alter table public.church_mail
  add column if not exists direction text not null default 'in',
  add column if not exists read_by uuid[] not null default '{}',
  add column if not exists answered_at timestamptz,
  add column if not exists answered_name text,
  add column if not exists sent_by uuid references auth.users(id) on delete set null;

alter table public.church_mail drop constraint if exists church_mail_direction_check;
alter table public.church_mail add constraint church_mail_direction_check check (direction in ('in', 'out'));
alter table public.church_mail drop constraint if exists church_mail_answered_name_check;
alter table public.church_mail add constraint church_mail_answered_name_check
  check (answered_name is null or char_length(answered_name) <= 200);
alter table public.church_mail drop constraint if exists church_mail_outcome_check;
alter table public.church_mail add constraint church_mail_outcome_check
  check (outcome in ('copied', 'prayer', 'held', 'failed', 'stored', 'sent'));

create index if not exists church_mail_church_direction
  on public.church_mail (business_id, direction, received_at desc);

create table if not exists public.church_mail_people(
  business_id uuid not null references public.businesses(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  copies boolean not null default true,
  updated_at timestamptz not null default now(),
  primary key (business_id, user_id)
);

alter table public.church_mail_people enable row level security;
revoke all on public.church_mail_people from anon, authenticated;
grant all on public.church_mail_people to service_role;

comment on column public.church_mail.direction is
  'in: came to a church box. out: sent as a church box (from the Email room, or a reply by email that went out as the box).';
comment on column public.church_mail.read_by is
  'The logins that opened it in the Email room. A shared box''s mail is read per person.';
comment on column public.church_mail.answered_name is
  'Who answered it (from the Email room or by replying to their copy), so nobody on a shared box answers it twice.';
comment on table public.church_mail_people is
  'A login''s own church mail setting (church_mail_room.py). copies=false: reads church mail in the Email room only. Server-only (RLS on, no policies).';

commit;

-- Check:
--   select count(*) from information_schema.columns where table_schema = 'public' and table_name = 'church_mail'
--     and column_name in ('direction', 'read_by', 'answered_at', 'answered_name', 'sent_by');
--   -- 5
--   select pg_get_constraintdef(oid) from pg_constraint where conname = 'church_mail_outcome_check';
--   -- CHECK ((outcome = ANY (ARRAY['copied'::text, 'prayer'::text, 'held'::text, 'failed'::text, 'stored'::text, 'sent'::text])))
--   select c.relrowsecurity, has_table_privilege('authenticated', c.oid, 'select') as browser_reads
--     from pg_class c where c.oid = 'public.church_mail_people'::regclass;
--   -- true, false
--
-- Rollback (loses who read and answered what, the room's Sent, and everyone's copies setting):
--   drop table if exists public.church_mail_people;
--   delete from public.church_mail where outcome = 'sent';
--   alter table public.church_mail drop constraint if exists church_mail_outcome_check;
--   alter table public.church_mail add constraint church_mail_outcome_check
--     check (outcome in ('copied', 'prayer', 'held', 'failed', 'stored'));
--   alter table public.church_mail drop constraint if exists church_mail_direction_check;
--   alter table public.church_mail drop constraint if exists church_mail_answered_name_check;
--   drop index if exists public.church_mail_church_direction;
--   alter table public.church_mail drop column if exists direction, drop column if exists read_by,
--     drop column if exists answered_at, drop column if exists answered_name, drop column if exists sent_by;
