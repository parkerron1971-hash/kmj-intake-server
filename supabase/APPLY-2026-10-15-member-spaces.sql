-- Youth and Kids spaces in the member app (Kevin, 2026-10-15: teens and
-- kids "should have their own access point", and adult group leaders "the
-- ability to access each side"; he approved the concept and its five calls
-- the same day). Idempotent.
--
--   space_leaders  who the church office approved to lead Youth or Kids,
--                  with the date of their background check, and (Kids)
--                  the rooms they lead. Leaders must be adults.
--   space_posts    what leaders post: a note to Youth, or a Kids lesson
--                  (the story, the verse, questions for dinner) that parents
--                  see in their Kids space.
--
-- Server-only, like the kids and family tables: no browser role reads or
-- writes them. member_spaces.py is the one door — leaders post through the
-- member app, the office approves leaders through /member-portal/{biz}/leaders
-- (admin seats and the owner).
begin;

create table if not exists public.space_leaders(
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  space text not null check (space in ('youth','kids')),
  -- Kids rooms they lead ("Room 2", "Nursery"), as the church names them;
  -- empty means every room.
  rooms text[] not null default '{}',
  background_check_on date not null check (background_check_on between date '2000-01-01' and date '2100-01-01'),
  approved_by uuid,
  approved_at timestamptz not null default now(),
  primary key (business_id, contact_id, space)
);
create index if not exists space_leaders_contact on public.space_leaders(contact_id);

create table if not exists public.space_posts(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  space text not null check (space in ('youth','kids')),
  kind text not null default 'post' check (kind in ('post','lesson')),
  -- A Kids lesson's room ('' = every room); unused for Youth.
  room text not null default '' check (length(room) <= 60),
  title text not null default '' check (length(title) <= 120),
  body text not null default '' check (length(body) <= 2000),
  scripture text not null default '' check (length(scripture) <= 160),
  verse text not null default '' check (length(verse) <= 400),
  questions text not null default '' check (length(questions) <= 1000),
  video_url text not null default '' check (video_url = '' or (length(video_url) <= 500 and video_url ~ '^https://')),
  posted_by uuid references public.contacts(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists space_posts_recent on public.space_posts(business_id, space, created_at desc);

do $$ declare t text; begin
  foreach t in array array['space_leaders','space_posts'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- A leader and a post's author must be this church's own people.
create or replace function public.space_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'space_leaders' then
    if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  elsif new.posted_by is not null then
    if not exists (select 1 from public.contacts c where c.id = new.posted_by and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.space_same_business() from public, anon, authenticated;

do $$ declare t text; begin
  foreach t in array array['space_leaders','space_posts'] loop
    execute format('drop trigger if exists space_same_business on public.%I', t);
    execute format('create trigger space_same_business before insert or update on public.%I
      for each row execute function public.space_same_business()', t);
  end loop;
end $$;

commit;
