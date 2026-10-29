-- Board & minutes (church_board.py; Kevin 2026-10-27 on the Church Office
-- Prototypes, "Board & minutes" tab: "lets go with your list"). Elders and
-- deacons meet, decide and need a record. Six tables, server-only (RLS on,
-- no policies, browser roles revoked); church_board.py reads and writes them.
--
--   church_boards            a church's boards (Elders, Deacons, Trustees,
--                            the Church council) and each one's quorum: a
--                            majority of its members, or a count
--   church_board_members     who sits on a board: one of the church's
--                            people (contact_id), a login (user_id), or
--                            both; a title (Chair, Secretary). Leaving a
--                            board is active = false, so old minutes keep
--                            the name
--   church_board_meetings    one meeting of one board: when, where (a place
--                            or a video link), planned / in_progress /
--                            drafted (minutes drafted) / approved; when the
--                            draft went to the board, and the meeting its
--                            minutes were approved in
--   church_board_items       the agenda: a title, notes, linked Documents
--                            (paths in the church's own business-documents
--                            folder, never a new file), the minutes for the
--                            item, and open / done / tabled / follow_up. A
--                            tabled or follow-up item is carried into the
--                            board's next meeting once: carried_from is
--                            unique. A follow-up names who and by when, and
--                            the task made from it (tasks.id)
--   church_board_attendance  present / absent / excused, one row per member
--                            per meeting
--   church_board_decisions   a motion on an item: who moved and seconded
--                            (members of the board), the vote for / against
--                            / abstain, carried / failed / tabled, the day,
--                            and the item's title as it was (the decisions
--                            log searches motion and title across years)
--
-- Every row is its own church's: each child carries business_id with a
-- foreign key on (business_id, parent id), so nothing points across
-- churches; a member's person is its church's (a trigger).
-- Idempotent; no drops.
begin;

create table if not exists public.church_boards(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  quorum_kind text not null default 'majority' check (quorum_kind in ('majority', 'count')),
  quorum_count int check (quorum_count is null or quorum_count between 1 and 500),
  sort int not null default 0,
  archived boolean not null default false,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint church_boards_count_needs_number check (quorum_kind <> 'count' or quorum_count is not null),
  unique (business_id, id)
);

create table if not exists public.church_board_members(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  board_id uuid not null,
  contact_id uuid references public.contacts(id) on delete set null,
  user_id uuid,
  name text not null check (char_length(name) between 1 and 120),
  title text not null default '' check (char_length(title) <= 60),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint church_board_members_board foreign key (business_id, board_id)
    references public.church_boards(business_id, id) on delete cascade,
  unique (business_id, id)
);

create table if not exists public.church_board_meetings(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  board_id uuid not null,
  title text not null default '' check (char_length(title) <= 120),
  starts_at timestamptz not null,
  place text not null default '' check (char_length(place) <= 160),
  video_url text not null default '' check (char_length(video_url) <= 500),
  status text not null default 'planned' check (status in ('planned', 'in_progress', 'drafted', 'approved')),
  sent_at timestamptz,
  sent_by uuid,
  sent_count int not null default 0 check (sent_count between 0 and 1000),
  approved_at timestamptz,
  approved_by uuid,
  approved_in uuid,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint church_board_meetings_board foreign key (business_id, board_id)
    references public.church_boards(business_id, id) on delete cascade,
  unique (business_id, id)
);

create table if not exists public.church_board_items(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  meeting_id uuid not null,
  position int not null default 0 check (position between 0 and 10000),
  title text not null check (char_length(title) between 1 and 200),
  notes text not null default '' check (char_length(notes) <= 4000),
  minutes text not null default '' check (char_length(minutes) <= 20000),
  status text not null default 'open' check (status in ('open', 'done', 'tabled', 'follow_up')),
  documents jsonb not null default '[]'::jsonb check (jsonb_typeof(documents) = 'array'),
  carried_from uuid references public.church_board_items(id) on delete set null,
  follow_up_member uuid,
  follow_up_due date,
  task_id uuid references public.tasks(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint church_board_items_meeting foreign key (business_id, meeting_id)
    references public.church_board_meetings(business_id, id) on delete cascade,
  constraint church_board_items_carried_once unique (carried_from),
  unique (business_id, id)
);

create table if not exists public.church_board_attendance(
  business_id uuid not null references public.businesses(id) on delete cascade,
  meeting_id uuid not null,
  member_id uuid not null,
  status text not null check (status in ('present', 'absent', 'excused')),
  marked_by uuid,
  marked_at timestamptz not null default now(),
  primary key (meeting_id, member_id),
  constraint church_board_attendance_meeting foreign key (business_id, meeting_id)
    references public.church_board_meetings(business_id, id) on delete cascade,
  constraint church_board_attendance_member foreign key (business_id, member_id)
    references public.church_board_members(business_id, id) on delete cascade
);

create table if not exists public.church_board_decisions(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  board_id uuid not null,
  meeting_id uuid not null,
  item_id uuid not null,
  item_title text not null default '' check (char_length(item_title) <= 200),
  motion text not null check (char_length(motion) between 1 and 1000),
  moved_by uuid,
  seconded_by uuid,
  votes_for int not null default 0 check (votes_for between 0 and 1000),
  votes_against int not null default 0 check (votes_against between 0 and 1000),
  votes_abstain int not null default 0 check (votes_abstain between 0 and 1000),
  result text not null check (result in ('carried', 'failed', 'tabled')),
  decided_on date not null,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint church_board_decisions_board foreign key (business_id, board_id)
    references public.church_boards(business_id, id) on delete cascade,
  constraint church_board_decisions_meeting foreign key (business_id, meeting_id)
    references public.church_board_meetings(business_id, id) on delete cascade,
  constraint church_board_decisions_item foreign key (business_id, item_id)
    references public.church_board_items(business_id, id) on delete cascade,
  constraint church_board_decisions_moved foreign key (business_id, moved_by)
    references public.church_board_members(business_id, id),
  constraint church_board_decisions_seconded foreign key (business_id, seconded_by)
    references public.church_board_members(business_id, id)
);

create index if not exists church_boards_business on public.church_boards(business_id, sort);
create index if not exists church_board_members_board on public.church_board_members(business_id, board_id);
create index if not exists church_board_members_login on public.church_board_members(business_id, user_id) where active;
create index if not exists church_board_meetings_board_day on public.church_board_meetings(business_id, board_id, starts_at desc);
create index if not exists church_board_items_meeting on public.church_board_items(business_id, meeting_id, position);
create index if not exists church_board_decisions_day on public.church_board_decisions(business_id, decided_on desc);

-- A member's person is one of its own church's people, whatever the caller
-- passes.
create or replace function public.church_board_member_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.contact_id is not null and not exists (
      select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this church';
  end if;
  return new;
end $$;
create or replace trigger church_board_member_same_business before insert or update of contact_id, business_id
  on public.church_board_members for each row execute function public.church_board_member_same_business();
revoke all on function public.church_board_member_same_business() from public, anon, authenticated;

alter table public.church_boards enable row level security;
alter table public.church_board_members enable row level security;
alter table public.church_board_meetings enable row level security;
alter table public.church_board_items enable row level security;
alter table public.church_board_attendance enable row level security;
alter table public.church_board_decisions enable row level security;
revoke all on public.church_boards from anon, authenticated;
revoke all on public.church_board_members from anon, authenticated;
revoke all on public.church_board_meetings from anon, authenticated;
revoke all on public.church_board_items from anon, authenticated;
revoke all on public.church_board_attendance from anon, authenticated;
revoke all on public.church_board_decisions from anon, authenticated;
grant all on public.church_boards to service_role;
grant all on public.church_board_members to service_role;
grant all on public.church_board_meetings to service_role;
grant all on public.church_board_items to service_role;
grant all on public.church_board_attendance to service_role;
grant all on public.church_board_decisions to service_role;

commit;

-- Check after applying (six rows, RLS on, no policies):
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.tablename = c.relname) as policies
--     from pg_class c where c.relname like 'church_board%' and c.relkind = 'r' order by 1;
