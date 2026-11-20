-- APPLY-2026-11-21-church-meetings.sql
--
-- The leaders schedule, step 3: meetings and one calendar, the tables only
-- (docs/CHURCH_SCHEDULE.md section 10, PR S3-1). Nothing reads them yet;
-- church_meetings.py and the pages come in the PRs after this one. The pastor
-- approved the mock and its five calls on 2026-11-20: one home for every
-- meeting (Board & minutes becomes Meetings & minutes); a meeting for every
-- leader keeps itself up to date with the leaders list, and so does one for
-- the office; "I can't" needs no yes, with a short note only whoever set the
-- meeting, the owner and whoever oversees the office read; a reminder the day
-- before, in the app; and a private link for a phone's calendar that the
-- person can make again at any time, the old one stopping.
--
-- Board & minutes' six tables (APPLY-2026-10-27-church-board.sql) stay the one
-- home of every meeting: a group that meets is a church_boards row, a meeting
-- is a church_board_meetings row, and its agenda, attendance, decisions and
-- minutes are what they are today. What is new:
--
--   church_boards.kind      board (it governs: its people give the board's yes
--                           on money and are a board on the leaders map) or
--                           meeting (it only meets: the huddle, the leaders
--                           meeting, check-ins). Every group there is a board.
--   church_boards.audience  who comes: members (the group's own people, as
--                           every board has them), leaders (everyone on the
--                           leaders list) or office (the office on it). A
--                           group for the list is always a meeting, never a
--                           board, keeps who it is for, and is the one open
--                           group of its name.
--   church_board_members.from_list
--                           a row the server keeps in step with the leaders
--                           list. On a group for the list every row is; on any
--                           other group none is, so nobody adds a person to it
--                           by hand and the list never adds one to a board.
--   church_meeting_series   a meeting that repeats: its group, a weekday, every
--                           week / every other week / the nth such day of the
--                           month (the rule church_away_commitments uses), the
--                           time on the church's clock, how long, where, the
--                           room, and how far ahead its meetings are made.
--   church_board_meetings   gains series_id and series_day (the series and the
--                           day of it a meeting stands for; one a day),
--                           length_minutes, space_id and booking_id (the room,
--                           and the booking made for it in Rooms & spaces),
--                           cancelled_at / cancelled_by (called off, or one of
--                           a series skipped; only a meeting not yet held) and
--                           changed_alone_at (changed by itself: the series'
--                           later changes leave it alone).
--   church_meeting_answers  "I'll be there" or "I can't", one a person a
--                           meeting, keyed by their member row as attendance
--                           is; the time it was given for (a meeting moved
--                           since reads as not answered); a private note with
--                           "I can't" only.
--   church_meeting_notices  the reminders' claim-before-send ledger: the day
--                           before, "Remind the ones who haven't answered",
--                           and "moved" (the time changed after the day-before
--                           reminder went); one a person a meeting a kind a day.
--   church_calendar_links   a person's private link for their phone's
--                           calendar: only a hash of its key is kept; one
--                           working link a person; a stopped link stays
--                           stopped.
--   church_space_bookings   gains one trigger and nothing else: a booking a
--                           meeting names keeps its room (the room changes from
--                           the meeting, with a new booking).
--
-- The unique indexes the server writes against are plain where PostgREST must
-- name them (one meeting a day of a series: on_conflict=series_id,series_day).
-- The partial ones (one list seat a person, one open list group a name, one
-- working calendar link a person) are never named in on_conflict: the server
-- inserts one row and reads a 409 (23505) as "already there", then reads again.
--
-- Server-only: every new table RLS on with no policies, anon and
-- authenticated revoked, service_role granted; every function revoked from
-- public, anon and authenticated. One transaction, lock_timeout 5s, safe to
-- run twice. Additive: no table, column, row or existing constraint is
-- dropped or rewritten (this file's own triggers are dropped and made again,
-- as every file here does). The new columns are null, false, 'board' or
-- 'members' by a constant default on every row that exists, so no row is
-- rewritten, and every existing board, member, meeting, item, attendance mark
-- and decision reads and writes exactly as it did. The constraints and
-- foreign keys on the three board tables are checked as they go in: the tables
-- are small (a church has a few boards and some dozens of meetings) and every
-- row passes. Ends with NOTIFY pgrst so the API sees the tables at once.
--
-- Safe before the code that reads it: the deployed code names every column it
-- reads and never sends the new ones, so a board, a member, a meeting, the
-- agenda, attendance, decisions, minutes and the member app's Board tab all
-- work as they did the moment this runs. Nothing writes a kind 'meeting' row
-- before S3-2, which must, in the same pull request, make every reader that
-- means "a board" read kind = 'board' (docs/CHURCH_SCHEDULE.md 10.2).
begin;

set local lock_timeout = '5s';

-- ─── A group that meets: a board or a meeting, and who comes ────────────

alter table public.church_boards
  add column if not exists kind text not null default 'board',
  add column if not exists audience text not null default 'members';

alter table public.church_board_members
  add column if not exists from_list boolean not null default false;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'church_boards_kind'
                   and conrelid = 'public.church_boards'::regclass) then
    alter table public.church_boards add constraint church_boards_kind
      check (kind in ('board', 'meeting'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_boards_audience'
                   and conrelid = 'public.church_boards'::regclass) then
    alter table public.church_boards add constraint church_boards_audience
      check (audience in ('members', 'leaders', 'office'));
  end if;
  -- A group that follows the list only meets: it never gives the board's yes.
  if not exists (select 1 from pg_constraint where conname = 'church_boards_list_is_meeting'
                   and conrelid = 'public.church_boards'::regclass) then
    alter table public.church_boards add constraint church_boards_list_is_meeting
      check (audience = 'members' or kind = 'meeting');
  end if;
end $$;

-- One open group for the list a name (whatever its case), so Set a meeting
-- pressed twice for "Leaders meeting" finds or makes one. Boards are not
-- touched: two of a church's boards may share a name, as they always could.
-- PostgREST can't name a partial or an expression index in on_conflict, so
-- the server inserts, reads a 409 (23505) as "made just now", and reads again.
create unique index if not exists church_boards_one_list_name
  on public.church_boards (business_id, audience, lower(name)) where audience <> 'members' and not archived;

-- One row a person on a group that follows the list, so two replicas keeping
-- it in step at once never add someone twice. A person deleted leaves their
-- row (the board's own rule, for old minutes) with no person, and two such
-- rows never clash. Partial, so the server seats one person a request and
-- reads a 409 (23505) as "already seated", never on_conflict.
create unique index if not exists church_board_members_one_from_list
  on public.church_board_members (board_id, contact_id) where from_list;

-- A group keeps who it is for: a group for the list holds only the list's
-- rows, which a change of audience would leave wrong.
create or replace function public.church_boards_audience_kept() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.audience is distinct from old.audience then
    raise exception 'A meeting keeps who it is for: make a new one';
  end if;
  return new;
end $$;
revoke all on function public.church_boards_audience_kept() from public, anon, authenticated;

drop trigger if exists church_boards_audience_kept on public.church_boards;
create trigger church_boards_audience_kept
  before update of audience on public.church_boards
  for each row execute function public.church_boards_audience_kept();

-- A member row is the list's exactly when its group follows the list, and a
-- row the list adds is one of the church's people and stays that person's.
-- Checked when a row is added, or moved to another group, or marked, or its
-- person changed; a person deleted (their contact set null by the board's own
-- key) checks nothing. What it can't see (a hand write that marks a row the
-- list's, or seats someone again) the server refuses: on a group for the list
-- only the keeping in step writes seats (docs/CHURCH_SCHEDULE.md 10.2).
create or replace function public.church_board_members_follow_list() returns trigger
language plpgsql set search_path = public as $$
declare
  a text;
begin
  if tg_op = 'UPDATE' and new.from_list and new.contact_id is not null
     and new.contact_id is distinct from old.contact_id then
    raise exception 'A seat from the list stays its person''s';
  end if;
  if tg_op = 'INSERT' or new.from_list is distinct from old.from_list
     or new.board_id is distinct from old.board_id or new.business_id is distinct from old.business_id then
    select b.audience into a from public.church_boards b
     where b.id = new.board_id and b.business_id = new.business_id;
    if not found then
      return new;    -- the row's own foreign key refuses it
    end if;
    if new.from_list and a = 'members' then
      raise exception 'Only a meeting for every leader or the office follows the list';
    end if;
    if not new.from_list and a <> 'members' then
      raise exception 'This meeting follows the leaders list: add them there';
    end if;
    if new.from_list and new.contact_id is null then
      raise exception 'Someone the list adds is one of the church''s people';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.church_board_members_follow_list() from public, anon, authenticated;

drop trigger if exists church_board_members_follow_list on public.church_board_members;
create trigger church_board_members_follow_list
  before insert or update of from_list, board_id, business_id, contact_id on public.church_board_members
  for each row execute function public.church_board_members_follow_list();

-- ─── A meeting that repeats ─────────────────────────────────────────────

-- weekday, pattern, nth, starts_on and until_on are church_away_commitments'
-- own (APPLY-2026-11-19-church-schedule.sql), so church_schedule_repeats.
-- days_of works out a series' days as it does a commitment's.
create table if not exists public.church_meeting_series(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  board_id uuid not null,
  title text not null default '' check (char_length(title) <= 120),
  weekday smallint not null check (weekday between 1 and 7),          -- 1 Monday … 7 Sunday
  pattern text not null check (pattern in ('weekly', 'every_other', 'month_nth')),
  nth smallint check (nth between 1 and 5),                           -- 5 = the last one of the month
  starts_on date not null,
  until_on date,
  at_time time not null,                                              -- on the church's clock
  length_minutes smallint not null default 60 check (length_minutes between 5 and 720),
  place text not null default '' check (char_length(place) <= 160),
  video_url text not null default '' check (char_length(video_url) <= 500),
  space_id uuid references public.church_spaces(id) on delete set null,
  made_through date,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint church_meeting_series_group foreign key (business_id, board_id)
    references public.church_boards(business_id, id) on delete cascade,
  constraint church_meeting_series_nth check ((pattern = 'month_nth') = (nth is not null)),
  constraint church_meeting_series_until check (until_on is null or until_on >= starts_on),
  -- every other week counts from starts_on, so starts_on is one of its days
  constraint church_meeting_series_anchor
    check (pattern <> 'every_other' or extract(isodow from starts_on) = weekday)
);
create index if not exists church_meeting_series_by_group
  on public.church_meeting_series (business_id, board_id);

-- ─── A meeting: its series, its length, its room, called off ────────────

alter table public.church_board_meetings
  add column if not exists series_id uuid,
  add column if not exists series_day date,
  add column if not exists length_minutes smallint,
  add column if not exists space_id uuid,
  add column if not exists booking_id uuid,
  add column if not exists cancelled_at timestamptz,
  add column if not exists cancelled_by uuid,
  add column if not exists changed_alone_at timestamptz;

do $$
begin
  -- A series deleted leaves its meetings, as one-off meetings that keep the
  -- day they were made for.
  if not exists (select 1 from pg_constraint where conname = 'church_board_meetings_series_id_fkey'
                   and conrelid = 'public.church_board_meetings'::regclass) then
    alter table public.church_board_meetings add constraint church_board_meetings_series_id_fkey
      foreign key (series_id) references public.church_meeting_series(id) on delete set null;
  end if;
  -- A room deleted, or its booking, leaves the meeting with no room or no booking.
  if not exists (select 1 from pg_constraint where conname = 'church_board_meetings_space_id_fkey'
                   and conrelid = 'public.church_board_meetings'::regclass) then
    alter table public.church_board_meetings add constraint church_board_meetings_space_id_fkey
      foreign key (space_id) references public.church_spaces(id) on delete set null;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_board_meetings_booking_id_fkey'
                   and conrelid = 'public.church_board_meetings'::regclass) then
    alter table public.church_board_meetings add constraint church_board_meetings_booking_id_fkey
      foreign key (booking_id) references public.church_space_bookings(id) on delete set null;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_board_meetings_cancelled_by_fkey'
                   and conrelid = 'public.church_board_meetings'::regclass) then
    alter table public.church_board_meetings add constraint church_board_meetings_cancelled_by_fkey
      foreign key (cancelled_by) references auth.users(id) on delete set null;
  end if;
  -- A meeting of a series names the day of it that it stands for.
  if not exists (select 1 from pg_constraint where conname = 'church_board_meetings_series_day'
                   and conrelid = 'public.church_board_meetings'::regclass) then
    alter table public.church_board_meetings add constraint church_board_meetings_series_day
      check (series_id is null or series_day is not null);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_board_meetings_length'
                   and conrelid = 'public.church_board_meetings'::regclass) then
    alter table public.church_board_meetings add constraint church_board_meetings_length
      check (length_minutes is null or length_minutes between 5 and 720);
  end if;
  -- Only a meeting not yet held is called off, and who called it off goes with when.
  if not exists (select 1 from pg_constraint where conname = 'church_board_meetings_called_off'
                   and conrelid = 'public.church_board_meetings'::regclass) then
    alter table public.church_board_meetings add constraint church_board_meetings_called_off
      check ((cancelled_at is null or status = 'planned')
             and (cancelled_by is null or cancelled_at is not null));
  end if;
  -- "Changed by itself" means something only for a meeting made from a series.
  if not exists (select 1 from pg_constraint where conname = 'church_board_meetings_alone'
                   and conrelid = 'public.church_board_meetings'::regclass) then
    alter table public.church_board_meetings add constraint church_board_meetings_alone
      check (changed_alone_at is null or series_day is not null);
  end if;
end $$;

-- One meeting a day of a series, however many replicas make them ahead; one
-- meeting a booking; and the reminders' window. The two unique indexes are
-- plain, not partial: nulls are distinct, so one-off meetings and meetings with
-- no booking never clash, and PostgREST's on_conflict=series_id,series_day
-- (which sends no predicate) can name the first.
create unique index if not exists church_board_meetings_one_a_day
  on public.church_board_meetings (series_id, series_day);
create unique index if not exists church_board_meetings_one_booking
  on public.church_board_meetings (booking_id);
create index if not exists church_board_meetings_coming
  on public.church_board_meetings (starts_at) where status = 'planned' and cancelled_at is null;

-- ─── "I'll be there" or "I can't" ───────────────────────────────────────

create table if not exists public.church_meeting_answers(
  business_id uuid not null references public.businesses(id) on delete cascade,
  meeting_id uuid not null,
  member_id uuid not null,
  answer text not null check (answer in ('yes', 'cant')),
  note text check (note is null or char_length(btrim(note)) between 1 and 200),
  for_starts_at timestamptz not null,
  by_user_id uuid references auth.users(id) on delete set null,
  by_contact_id uuid references public.contacts(id) on delete set null,
  answered_at timestamptz not null default now(),
  primary key (meeting_id, member_id),
  constraint church_meeting_answers_meeting foreign key (business_id, meeting_id)
    references public.church_board_meetings(business_id, id) on delete cascade,
  constraint church_meeting_answers_member foreign key (business_id, member_id)
    references public.church_board_members(business_id, id) on delete cascade,
  -- A note goes with "I can't" only.
  constraint church_meeting_answers_note check (note is null or answer = 'cant'),
  constraint church_meeting_answers_by_one check (by_user_id is null or by_contact_id is null)
);
create index if not exists church_meeting_answers_member
  on public.church_meeting_answers (business_id, member_id);

-- ─── The reminders' ledger ──────────────────────────────────────────────

create table if not exists public.church_meeting_notices(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  meeting_id uuid not null,
  member_id uuid not null,
  kind text not null check (kind in ('day_before', 'nudge', 'moved')),
  for_day date not null,
  made_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  claimed_at timestamptz,
  sent_at timestamptz,
  how text check (how in ('app', 'email', 'nobody')),
  tries smallint not null default 0 check (tries between 0 and 20),
  constraint church_meeting_notices_meeting foreign key (business_id, meeting_id)
    references public.church_board_meetings(business_id, id) on delete cascade,
  constraint church_meeting_notices_member foreign key (business_id, member_id)
    references public.church_board_members(business_id, id) on delete cascade,
  -- Sent is claimed first, and says how it went.
  constraint church_meeting_notices_sent
    check ((sent_at is null) = (how is null) and (sent_at is null or claimed_at is not null)),
  -- Only "Remind the ones who haven't answered" is pressed by someone.
  constraint church_meeting_notices_made_by check (kind = 'nudge' or made_by is null)
);
create unique index if not exists church_meeting_notices_once
  on public.church_meeting_notices (meeting_id, member_id, kind, for_day);
create index if not exists church_meeting_notices_unsent
  on public.church_meeting_notices (created_at) where sent_at is null;
create index if not exists church_meeting_notices_member
  on public.church_meeting_notices (business_id, member_id);

-- ─── A private link for a phone's calendar ──────────────────────────────

create table if not exists public.church_calendar_links(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  token_hash text not null check (token_hash ~ '^[0-9a-f]{64}$'),
  made_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  revoked_at timestamptz,
  last_read_at timestamptz
);
-- The feed finds a link by its key's hash alone; one working link a person.
create unique index if not exists church_calendar_links_token
  on public.church_calendar_links (token_hash);
create unique index if not exists church_calendar_links_one_live
  on public.church_calendar_links (business_id, contact_id) where revoked_at is null;

-- ─── Everything named is the church's own ───────────────────────────────

-- A series' group is its church's (its foreign key carries the church), so
-- is its room, and a series never moves to another group or church (its
-- meetings would be left hanging off another group's series). A meeting's
-- series is the same church's and the same group's; its room is its church's;
-- its booking is its church's and is of its room, checked when the booking is
-- written and again when the room changes. An answer's or a reminder's person
-- sits on the meeting's group,
-- and the person who answered is the church's. A calendar link's person is
-- the church's, and the link never changes church, person or key, and once
-- stopped stays stopped. Each is checked only when a write names it: a
-- foreign key setting one of them null (a room, a booking, a series, a
-- person or a login deleted) checks nothing. Each table's checks sit under
-- its own table test, because the other tables' columns aren't there.
create or replace function public.church_meetings_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'church_meeting_series' then
    if tg_op = 'UPDATE' and (new.board_id is distinct from old.board_id
                             or new.business_id is distinct from old.business_id) then
      raise exception 'A series stays with its group: make a new one';
    end if;
    if new.space_id is not null
       and (tg_op = 'INSERT' or new.space_id is distinct from old.space_id
            or new.business_id is distinct from old.business_id) then
      if not exists (select 1 from public.church_spaces sp
                     where sp.id = new.space_id and sp.business_id = new.business_id) then
        raise exception 'That room is not in this church';
      end if;
    end if;
  end if;
  if tg_table_name = 'church_board_meetings' then
    if new.series_id is not null
       and (tg_op = 'INSERT' or new.series_id is distinct from old.series_id
            or new.board_id is distinct from old.board_id or new.business_id is distinct from old.business_id) then
      if not exists (select 1 from public.church_meeting_series s
                     where s.id = new.series_id and s.business_id = new.business_id and s.board_id = new.board_id) then
        raise exception 'That series is not this meeting''s';
      end if;
    end if;
    if new.space_id is not null
       and (tg_op = 'INSERT' or new.space_id is distinct from old.space_id
            or new.business_id is distinct from old.business_id) then
      if not exists (select 1 from public.church_spaces sp
                     where sp.id = new.space_id and sp.business_id = new.business_id) then
        raise exception 'That room is not in this church';
      end if;
    end if;
    -- Checked when the booking is written, and when the room changes to
    -- another: whoever moves a meeting to another room writes its booking (or
    -- none) in the same update. A room deleted sets the room to nothing, which
    -- checks nothing.
    if new.booking_id is not null
       and (tg_op = 'INSERT' or new.booking_id is distinct from old.booking_id
            or (new.space_id is not null and new.space_id is distinct from old.space_id)) then
      if not exists (select 1 from public.church_space_bookings bk
                     where bk.id = new.booking_id and bk.business_id = new.business_id
                       and bk.space_id = new.space_id) then
        raise exception 'That booking is not for this meeting''s room';
      end if;
    end if;
  end if;
  if tg_table_name in ('church_meeting_answers', 'church_meeting_notices') then
    if tg_op = 'INSERT' or new.meeting_id is distinct from old.meeting_id
       or new.member_id is distinct from old.member_id or new.business_id is distinct from old.business_id then
      if not exists (select 1 from public.church_board_meetings m
                       join public.church_board_members x on x.board_id = m.board_id and x.business_id = m.business_id
                     where m.id = new.meeting_id and m.business_id = new.business_id and x.id = new.member_id) then
        raise exception 'That person is not one of this meeting''s people';
      end if;
    end if;
  end if;
  if tg_table_name = 'church_meeting_answers' then
    if new.by_contact_id is not null
       and (tg_op = 'INSERT' or new.by_contact_id is distinct from old.by_contact_id
            or new.business_id is distinct from old.business_id) then
      if not exists (select 1 from public.contacts c
                     where c.id = new.by_contact_id and c.business_id = new.business_id) then
        raise exception 'The person who answered is not in this church';
      end if;
    end if;
  end if;
  if tg_table_name = 'church_calendar_links' then
    if tg_op = 'UPDATE' then
      if new.business_id <> old.business_id or new.contact_id <> old.contact_id
         or new.token_hash <> old.token_hash then
        raise exception 'A calendar link keeps its church, its person and its key: make a new one';
      end if;
      if old.revoked_at is not null and new.revoked_at is distinct from old.revoked_at then
        raise exception 'A calendar link that was stopped stays stopped: make a new one';
      end if;
    elsif not exists (select 1 from public.contacts c
                      where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this church';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.church_meetings_same_business() from public, anon, authenticated;

drop trigger if exists church_meetings_same_business on public.church_meeting_series;
create trigger church_meetings_same_business
  before insert or update of space_id, business_id, board_id on public.church_meeting_series
  for each row execute function public.church_meetings_same_business();
drop trigger if exists church_meetings_same_business on public.church_board_meetings;
create trigger church_meetings_same_business
  before insert or update of series_id, space_id, booking_id, board_id, business_id on public.church_board_meetings
  for each row execute function public.church_meetings_same_business();
drop trigger if exists church_meetings_same_business on public.church_meeting_answers;
create trigger church_meetings_same_business
  before insert or update of meeting_id, member_id, business_id, by_contact_id on public.church_meeting_answers
  for each row execute function public.church_meetings_same_business();
drop trigger if exists church_meetings_same_business on public.church_meeting_notices;
create trigger church_meetings_same_business
  before insert or update of meeting_id, member_id, business_id on public.church_meeting_notices
  for each row execute function public.church_meetings_same_business();
drop trigger if exists church_meetings_same_business on public.church_calendar_links;
create trigger church_meetings_same_business
  before insert or update on public.church_calendar_links
  for each row execute function public.church_meetings_same_business();

-- The other side of "a booking is of its meeting's room": Rooms & spaces may
-- approve, decline or cancel a booking a meeting names, and the meeting page
-- reads where it stands, but its room changes only from the meeting (a new
-- booking for the new room). Its times are the server's to keep in step
-- (S3-3 refuses a time change from Rooms & spaces in plain words).
create or replace function public.church_space_bookings_meeting_room() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.space_id is distinct from old.space_id
     and exists (select 1 from public.church_board_meetings m where m.booking_id = new.id) then
    raise exception 'This booking is for a meeting: change its room from the meeting';
  end if;
  return new;
end $$;
revoke all on function public.church_space_bookings_meeting_room() from public, anon, authenticated;

drop trigger if exists church_space_bookings_meeting_room on public.church_space_bookings;
create trigger church_space_bookings_meeting_room
  before update of space_id on public.church_space_bookings
  for each row execute function public.church_space_bookings_meeting_room();

-- ─── Server-only ────────────────────────────────────────────────────────

do $$ declare t text; begin
  foreach t in array array['church_meeting_series', 'church_meeting_answers', 'church_meeting_notices',
                           'church_calendar_links'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

comment on column public.church_boards.kind is
  'Meetings & minutes: board (it governs: its people give the board''s yes on money and it is a board on the leaders map) or meeting (it only meets: the huddle, the leaders meeting, check-ins). Every reader that means a board reads kind = ''board''.';
comment on column public.church_boards.audience is
  'Meetings & minutes: who comes. members = the group''s own people; leaders = everyone on the leaders list; office = the office on it. A group for the list is a meeting, keeps its audience, and its people are kept in step with the list by the server (from_list).';
comment on column public.church_board_members.from_list is
  'Meetings & minutes: a row the server keeps in step with the leaders list (a group whose audience is leaders or office), one a person, and that person''s for good. Only the keeping in step writes seats on such a group; leaving the list is active = false, as leaving a board is.';
comment on table public.church_meeting_series is
  'Meetings & minutes: a meeting that repeats (weekly, every other week from starts_on, or the nth weekday of the month; church_away_commitments'' rule), at at_time on the church''s clock. Its meetings are church_board_meetings rows made ahead through made_through. Server-only (RLS on, no policies).';
comment on column public.church_board_meetings.series_day is
  'The day of its series this meeting stands for (one a day of a series); kept when the meeting is moved by itself, and when the series is deleted.';
comment on column public.church_board_meetings.length_minutes is
  'How long the meeting is, in minutes (5 to 720). Null on meetings set before step 3: an hour wherever a length is needed.';
comment on column public.church_board_meetings.booking_id is
  'The booking made for this meeting in Rooms & spaces (church_space_bookings), of its room. Null when no room was named or the room was taken.';
comment on column public.church_board_meetings.cancelled_at is
  'Called off (a one-off) or skipped (one of a series). The row stays, so a series never makes that day again and phones drop it. Only a planned meeting.';
comment on column public.church_board_meetings.changed_alone_at is
  'This meeting of a series was changed by itself; changing the series from a day on leaves it alone.';
comment on table public.church_meeting_answers is
  'Meetings & minutes: "I''ll be there" (yes) or "I can''t" (cant), one a person a meeting, keyed by their member row as church_board_attendance is. "I can''t" needs no yes. Server-only.';
comment on column public.church_meeting_answers.note is
  'Private, with "I can''t" only. Read only by the person, the meetings'' keepers, the login that set the meeting, the owner and whoever oversees the office. Never in a notice or a calendar feed. Cleared 90 days after the meeting.';
comment on column public.church_meeting_answers.for_starts_at is
  'The meeting''s start when the answer was given. Once the meeting moves, the answer no longer counts as one for the new time.';
comment on table public.church_meeting_notices is
  'Meetings & minutes: the reminders'' ledger. day_before (the sweep, the day before, outside quiet hours), nudge ("Remind the ones who haven''t answered") and moved (the time changed after the day-before reminder went); one a person a meeting a kind a day, claimed before it is sent and let go when nothing went. Server-only.';
comment on table public.church_calendar_links is
  'Meetings & minutes: a person''s private link for their phone''s calendar. Only the sha256 of its key is kept. One working link a person; making a new one stops the old (revoked_at), and a stopped link stays stopped. Server-only.';

commit;

notify pgrst, 'reload schema';

-- Check:
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('authenticated', c.oid, 'insert,update,delete') as browser_writes,
--          has_table_privilege('anon', c.oid, 'select') as anon_reads,
--          has_table_privilege('anon', c.oid, 'insert,update,delete') as anon_writes
--     from pg_class c where c.relnamespace = 'public'::regnamespace
--      and c.relname in ('church_meeting_series','church_meeting_answers','church_meeting_notices','church_calendar_links',
--                        'church_boards','church_board_members','church_board_meetings')
--    order by c.relname;
--   -- 7 rows: true, 0, false, false, false, false
--   select table_name, column_name from information_schema.columns
--    where table_schema = 'public'
--      and ((table_name = 'church_boards' and column_name in ('kind','audience'))
--        or (table_name = 'church_board_members' and column_name = 'from_list')
--        or (table_name = 'church_board_meetings' and column_name in ('series_id','series_day','length_minutes',
--              'space_id','booking_id','cancelled_at','cancelled_by','changed_alone_at')))
--    order by table_name, column_name;
--   -- 11 rows: church_board_meetings booking_id, cancelled_at, cancelled_by, changed_alone_at, length_minutes, series_day, series_id, space_id; church_board_members from_list; church_boards audience, kind
--   select conname, convalidated from pg_constraint
--    where conname in ('church_boards_kind','church_boards_audience','church_boards_list_is_meeting',
--                      'church_board_meetings_series_id_fkey','church_board_meetings_space_id_fkey',
--                      'church_board_meetings_booking_id_fkey','church_board_meetings_cancelled_by_fkey',
--                      'church_board_meetings_series_day','church_board_meetings_length',
--                      'church_board_meetings_called_off','church_board_meetings_alone')
--    order by conname;
--   -- 11 rows, convalidated true
--   select indexname, indexdef like '% WHERE %' as partial from pg_indexes
--    where schemaname = 'public' and indexdef like 'CREATE UNIQUE%'
--      and indexname in ('church_board_meetings_one_a_day','church_board_meetings_one_booking',
--                        'church_board_members_one_from_list','church_boards_one_list_name',
--                        'church_calendar_links_one_live','church_calendar_links_token','church_meeting_notices_once')
--    order by indexname;
--   -- 7 rows: church_board_meetings_one_a_day false, church_board_meetings_one_booking false, church_board_members_one_from_list true, church_boards_one_list_name true, church_calendar_links_one_live true, church_calendar_links_token false, church_meeting_notices_once false
--   select tgrelid::regclass::text as on_table, tgname, tgenabled from pg_trigger
--    where not tgisinternal and tgname in ('church_boards_audience_kept','church_board_members_follow_list',
--                                          'church_meetings_same_business','church_space_bookings_meeting_room')
--    order by 1, 2;
--   -- 8 rows, tgenabled O: church_board_meetings church_meetings_same_business; church_board_members church_board_members_follow_list; church_boards church_boards_audience_kept; church_calendar_links, church_meeting_answers, church_meeting_notices, church_meeting_series church_meetings_same_business; church_space_bookings church_space_bookings_meeting_room
--   select p.proname,
--          has_function_privilege('authenticated', p.oid, 'execute') as browser_runs,
--          has_function_privilege('anon', p.oid, 'execute') as anon_runs
--     from pg_proc p where p.pronamespace = 'public'::regnamespace
--      and p.proname in ('church_boards_audience_kept','church_board_members_follow_list','church_meetings_same_business',
--                        'church_space_bookings_meeting_room')
--    order by p.proname;
--   -- 4 rows: false, false
--   select (select count(*) from church_boards where kind <> 'board' or audience <> 'members') as groups,
--          (select count(*) from church_board_members where from_list) as list_rows,
--          (select count(*) from church_board_meetings
--            where series_id is not null or series_day is not null or length_minutes is not null or space_id is not null
--               or booking_id is not null or cancelled_at is not null or changed_alone_at is not null) as meetings;
--   -- 0, 0, 0
--
-- Rollback (loses every series, answer, reminder mark and calendar link; every board, member, item, attendance mark and decision stays, and so does every meeting with anything recorded on it). Run it with the code that reads these columns (S3-2 on) rolled back first. Before the columns go, nothing may be left that would read wrong without them: a room held for a meeting that won't happen is let go (a meeting group's meeting not yet held, one called off, and one a series made ahead with nothing recorded); meetings that won't happen and have nothing recorded are taken out (called off, or not yet held and made by a series or a meeting group's); every meeting group is closed (archived: once kind is gone it would read as a board, and the board's money yes reads open boards only); and every seat the list gave is let go. A meeting called off with an agenda, attendance or a decision stays, and reads as planned again: delete it by hand if it should go.
--   update public.church_space_bookings b set status = 'cancelled', updated_at = now()
--     from public.church_board_meetings m, public.church_boards g
--    where m.booking_id = b.id and g.id = m.board_id and b.status in ('requested', 'booked')
--      and m.status = 'planned' and m.starts_at > now()
--      and (g.kind = 'meeting' or m.cancelled_at is not null
--           or (m.series_id is not null
--               and not exists (select 1 from public.church_board_items i where i.meeting_id = m.id)
--               and not exists (select 1 from public.church_board_attendance a where a.meeting_id = m.id)
--               and not exists (select 1 from public.church_board_decisions d where d.meeting_id = m.id)));
--   delete from public.church_board_meetings m using public.church_boards g
--    where g.id = m.board_id and m.status = 'planned'
--      and (m.cancelled_at is not null or (m.starts_at > now() and (m.series_id is not null or g.kind = 'meeting')))
--      and not exists (select 1 from public.church_board_items i where i.meeting_id = m.id)
--      and not exists (select 1 from public.church_board_attendance a where a.meeting_id = m.id)
--      and not exists (select 1 from public.church_board_decisions d where d.meeting_id = m.id);
--   update public.church_boards set archived = true where kind = 'meeting';
--   update public.church_board_members set active = false, updated_at = now() where from_list and active;
--   drop table if exists public.church_meeting_notices, public.church_meeting_answers, public.church_calendar_links;
--   drop trigger if exists church_space_bookings_meeting_room on public.church_space_bookings;
--   drop trigger if exists church_meetings_same_business on public.church_board_meetings;
--   drop trigger if exists church_board_members_follow_list on public.church_board_members;
--   drop trigger if exists church_boards_audience_kept on public.church_boards;
--   drop index if exists public.church_board_meetings_one_a_day, public.church_board_meetings_one_booking,
--                        public.church_board_meetings_coming, public.church_board_members_one_from_list,
--                        public.church_boards_one_list_name;
--   alter table public.church_board_meetings
--     drop constraint if exists church_board_meetings_series_id_fkey,
--     drop constraint if exists church_board_meetings_space_id_fkey,
--     drop constraint if exists church_board_meetings_booking_id_fkey,
--     drop constraint if exists church_board_meetings_cancelled_by_fkey,
--     drop constraint if exists church_board_meetings_series_day,
--     drop constraint if exists church_board_meetings_length,
--     drop constraint if exists church_board_meetings_called_off,
--     drop constraint if exists church_board_meetings_alone,
--     drop column if exists series_id, drop column if exists series_day, drop column if exists length_minutes,
--     drop column if exists space_id, drop column if exists booking_id, drop column if exists cancelled_at,
--     drop column if exists cancelled_by, drop column if exists changed_alone_at;
--   drop table if exists public.church_meeting_series;
--   alter table public.church_board_members drop column if exists from_list;
--   alter table public.church_boards
--     drop constraint if exists church_boards_list_is_meeting,
--     drop constraint if exists church_boards_audience,
--     drop constraint if exists church_boards_kind,
--     drop column if exists kind, drop column if exists audience;
--   drop function if exists public.church_space_bookings_meeting_room();
--   drop function if exists public.church_meetings_same_business();
--   drop function if exists public.church_board_members_follow_list();
--   drop function if exists public.church_boards_audience_kept();
--   notify pgrst, 'reload schema';
