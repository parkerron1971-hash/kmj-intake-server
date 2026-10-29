-- A group's gatherings (part 3 of the approved canvas "Church Groups,
-- Together", boards Meet, Roll and Settings: "A real schedule, so RSVPs,
-- reminders and attendance all line up"). The office or the group's leaders
-- set when and where it meets; members say Going / Maybe / Can't, tap "I'm
-- here" at the gathering, and a leader takes the roll from their phone.
-- Attendance goes in the same group_meetings / group_meeting_attendance the
-- office already reads, so "missing lately" and the office's counts line up.
-- Idempotent.
--
--   groups.meet_day / meet_time   the regular gathering (0 = Monday ... 6 =
--                                 Sunday), the church's own clock
--   groups.meet_address           the street address: shown only to people
--                                 in the group (never on Find a group)
--   groups.meet_note              directions from the host
--   groups.meet_skips             dates with no gathering ("skip this week")
--   group_rsvps                   Going / Maybe / Can't, per gathering
--   group_meeting_attendance.how  who said they were there: the person
--                                 ("I'm here"), a leader, or the office
begin;

alter table public.groups add column if not exists meet_day smallint check (meet_day is null or meet_day between 0 and 6);
alter table public.groups add column if not exists meet_time time;
alter table public.groups add column if not exists meet_address text not null default '' check (length(meet_address) <= 200);
alter table public.groups add column if not exists meet_note text not null default '' check (length(meet_note) <= 300);
alter table public.groups add column if not exists meet_skips date[] not null default '{}';

alter table public.group_meeting_attendance add column if not exists how text not null default 'office'
  check (how in ('office','leader','self'));

create table if not exists public.group_rsvps(
  business_id uuid not null references public.businesses(id) on delete cascade,
  group_id uuid not null references public.groups(id) on delete cascade,
  met_on date not null,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  answer text not null check (answer in ('going','maybe','no')),
  updated_at timestamptz not null default now(),
  primary key (group_id, met_on, contact_id)
);
create index if not exists group_rsvps_business on public.group_rsvps(business_id, met_on);

-- The office reads them (who's coming Thursday); only the server writes,
-- after checking the person is in the group.
alter table public.group_rsvps enable row level security;
drop policy if exists tenant_member_read on public.group_rsvps;
create policy tenant_member_read on public.group_rsvps for select to authenticated
  using (public.is_business_member(business_id));
drop policy if exists business_owner_read on public.group_rsvps;
create policy business_owner_read on public.group_rsvps for select to authenticated
  using (business_id in (select id from public.businesses where owner_id = auth.uid()));
revoke all on public.group_rsvps from anon, authenticated;
grant select on public.group_rsvps to authenticated;
grant all on public.group_rsvps to service_role;

create or replace function public.group_rsvps_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.groups g where g.id = new.group_id and g.business_id = new.business_id) then
    raise exception 'That group is not in this business';
  end if;
  if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this business';
  end if;
  return new;
end $$;
revoke all on function public.group_rsvps_same_business() from public, anon, authenticated;
drop trigger if exists group_rsvps_same_business on public.group_rsvps;
create trigger group_rsvps_same_business before insert or update on public.group_rsvps
  for each row execute function public.group_rsvps_same_business();

commit;
