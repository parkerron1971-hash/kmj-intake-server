-- The Kids space in the member app (member_spaces_kids.py; Kevin approved
-- the concept and its five calls 2026-10-15). An approved Kids leader
-- checks a pickup code and releases children from the member app, through
-- the same rules as a station (kids_checkin.do_release, never as a
-- manager). The release records which leader: released_by_contact.
-- Apply after APPLY-2026-10-15-member-spaces.sql. Idempotent.
begin;

alter table public.child_checkins
  add column if not exists released_by_contact uuid references public.contacts(id) on delete set null;

-- The leader who released a child is one of this church's people and an
-- approved Kids leader. Fires only when the column is written.
create or replace function public.child_checkin_released_by_leader() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.released_by_contact is not null and not exists (
       select 1 from public.space_leaders l
       where l.contact_id = new.released_by_contact and l.business_id = new.business_id and l.space = 'kids') then
    raise exception 'That person is not a Kids leader here';
  end if;
  return new;
end $$;
revoke all on function public.child_checkin_released_by_leader() from public, anon, authenticated;
drop trigger if exists child_checkin_released_by_leader on public.child_checkins;
create trigger child_checkin_released_by_leader before insert or update of released_by_contact on public.child_checkins
  for each row execute function public.child_checkin_released_by_leader();

commit;
