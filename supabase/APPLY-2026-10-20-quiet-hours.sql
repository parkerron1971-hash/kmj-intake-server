-- Quiet hours and the after-hours alert (Kevin, 2026-10-20: phone alerts
-- for group news "and allow for group to send message with an (after hours
-- alert) which allows them to still send a message just incase they might
-- have a prayer time outside of the hours"; the approved canvas "Church
-- Groups, Together", boards Notify, Post and Chat). Idempotent.
--
--   member_push_prefs.quiet        9 PM to 7 AM, group news and messages
--                                  wait until morning (on unless turned off)
--   member_push_prefs.after_hours  an after-hours alert still rings
--   member_push_held               what waited, delivered after 7 AM
--   msg_messages.after_hours       this message was sent as an alert
--   group_posts.after_hours        this Board post was sent as an alert
begin;

alter table public.member_push_prefs add column if not exists quiet boolean not null default true;
alter table public.member_push_prefs add column if not exists after_hours boolean not null default true;

alter table public.msg_messages add column if not exists after_hours boolean not null default false;
alter table public.group_posts add column if not exists after_hours boolean not null default false;

-- One waiting note per person per thing (a busy chat waits as one note).
create table if not exists public.member_push_held(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  kind text not null check (kind in ('groups','messages')),
  title text not null default '' check (length(title) <= 60),
  body text not null default '' check (length(body) <= 180),
  url text not null default '/my' check (length(url) <= 300),
  tag text not null default '' check (length(tag) <= 60),
  created_at timestamptz not null default now(),
  unique (business_id, contact_id, tag)
);
create index if not exists member_push_held_business on public.member_push_held(business_id, created_at);

-- Server-only, like the rest of members' notifications.
alter table public.member_push_held enable row level security;
revoke all on public.member_push_held from anon, authenticated;
grant all on public.member_push_held to service_role;

-- A held note is this church's own person.
create or replace function public.member_push_held_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this business';
  end if;
  return new;
end $$;
revoke all on function public.member_push_held_same_business() from public, anon, authenticated;
drop trigger if exists member_push_held_same_business on public.member_push_held;
create trigger member_push_held_same_business before insert or update on public.member_push_held
  for each row execute function public.member_push_held_same_business();

commit;
