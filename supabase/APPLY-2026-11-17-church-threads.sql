-- APPLY-2026-11-17-church-threads.sql
--
-- Church threads: the member app's notes read like texts, and members can
-- write back (church_threads.py, member_portal_threads.py). Kevin,
-- 2026-11-17: "the goal is not be a text message itself but using the app
-- to push through as like a text", members "can respond and it not be an
-- issue", and "group notifications for groups people are in specifically".
--
--   church_thread_notes   one row per note in a member's inbox:
--                           a church note member_push sent (direction
--                           'church', kind = its kind), one row per person,
--                           or one row with contact_id null for everyone;
--                           a member's message to the office (direction
--                           'member', kind 'message', held when the screen
--                           said harm); the office's reply (direction
--                           'church', kind 'reply', with its writer).
--                           thread is 'church' or 'group:<uuid>'.
--                           read_at: when the office read a member's message.
--   church_thread_reads   when each member last opened each conversation
--                           (their unread counts).
--
-- Server only: RLS on with NO policies, nothing granted to anon or
-- authenticated (the server reads and writes them with the service role).
-- New tables only, one transaction, safe to run twice. Safe before or after
-- the code: the code goes quiet while these are missing (nothing recorded,
-- the pages go back to /my, the office's status says open:false).
begin;

set local lock_timeout = '5s';

create table if not exists public.church_thread_notes (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  -- No foreign key on purpose: a note is recorded for every person a push
  -- names in one bulk insert, and one stale id (an event sign-up kept in
  -- JSON after its contact went) would fail the whole chunk.
  contact_id uuid null,
  thread text not null default 'church',
  direction text not null default 'church',
  kind text not null,
  title text,
  body text,
  url text,
  ref_id text,
  author_user_id uuid null references auth.users(id) on delete set null,
  author_name text,
  held boolean not null default false,
  created_at timestamptz not null default now(),
  read_at timestamptz null,
  constraint church_thread_notes_direction_check check (direction in ('church', 'member')),
  constraint church_thread_notes_thread_check check (
    thread = 'church' or thread ~ '^group:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  constraint church_thread_notes_body_check check (body is null or char_length(body) <= 4000)
);

create index if not exists church_thread_notes_person
  on public.church_thread_notes (business_id, contact_id, created_at desc);
create index if not exists church_thread_notes_thread
  on public.church_thread_notes (business_id, thread, created_at desc);

create table if not exists public.church_thread_reads (
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  thread text not null,
  read_at timestamptz not null default now(),
  primary key (business_id, contact_id, thread)
);

alter table public.church_thread_notes enable row level security;
revoke all on public.church_thread_notes from anon, authenticated;
grant all on public.church_thread_notes to service_role;
alter table public.church_thread_reads enable row level security;
revoke all on public.church_thread_reads from anon, authenticated;
grant all on public.church_thread_reads to service_role;

comment on table public.church_thread_notes is
  'From your church (church_threads.py): church notes in members'' inboxes, members'' messages to the office, and the office''s replies. Server only.';
comment on column public.church_thread_notes.contact_id is
  'The member it is for (or from); null = everyone at the church (a church-wide note).';
comment on column public.church_thread_notes.thread is
  '''church'' (the member''s conversation with the church) or ''group:<uuid>'' (a group''s notes).';
comment on column public.church_thread_notes.held is
  'A member''s message the screen held (msg_screen harm): only the writer and the reviewers see it.';
comment on table public.church_thread_reads is
  'When each member last opened each conversation in From your church (unread counts). Server only.';

commit;

notify pgrst, 'reload schema';

-- Check:
--   select table_name from information_schema.tables where table_schema = 'public'
--     and table_name in ('church_thread_notes', 'church_thread_reads');
--   -- 2 rows
--   select indexname from pg_indexes where tablename = 'church_thread_notes'
--     and indexname in ('church_thread_notes_person', 'church_thread_notes_thread');
--   -- 2 rows
--   select relname, relrowsecurity from pg_class where relname in ('church_thread_notes', 'church_thread_reads');
--   -- both true
--   select count(*) from pg_policies where tablename in ('church_thread_notes', 'church_thread_reads');
--   -- 0
--
-- Rollback (loses every inbox note, message and reply):
--   drop table if exists public.church_thread_reads;
--   drop table if exists public.church_thread_notes;
