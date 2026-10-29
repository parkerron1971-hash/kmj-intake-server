-- All group leaders: one room per church where everyone who leads a group
-- and the church's pastors talk together (Kevin, 2026-10-20: "yes all group
-- leaders room would be great"; part 2 of the approved canvas "Church
-- Groups, Together"). It is a messaging thread like a group's chat (every
-- message screened by msg_screen, reports, the safety officers' reviews);
-- who's in it is read live: the leaders of the church's active groups and
-- its active Pastors and Elders (member_portal_messaging.leaders_room_people).
-- Idempotent.
begin;

alter table public.msg_threads drop constraint if exists msg_threads_kind_check;
alter table public.msg_threads add constraint msg_threads_kind_check check (kind in ('group','direct','leaders'));
alter table public.msg_threads drop constraint if exists msg_threads_check;
alter table public.msg_threads add constraint msg_threads_check check (
     (kind = 'group' and group_id is not null and direct_key is null)
  or (kind = 'direct' and group_id is null and direct_key is not null)
  or (kind = 'leaders' and group_id is null and direct_key is null));

-- One leaders' room per church.
create unique index if not exists msg_threads_one_leaders_room on public.msg_threads(business_id) where kind = 'leaders';

commit;
