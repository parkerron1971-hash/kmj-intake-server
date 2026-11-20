-- APPLY-2026-11-21-church-moments.sql
--
-- A pastor or a leader posts their own moment (the member app's new look,
-- Look 5.1, behind MEMBER_LUMEN; the pastor approved the mock on 2026-11-20:
-- "i like it lets do it"). A photo and one line at the start of their
-- church's Home, for a day, until Sunday, or for three days, seen by the
-- whole church or by one group they lead. Members see it in Home's moments
-- row (member_lumen_stories), the poster sees how many saw it and loved it,
-- never who. The tables only: member_moments.py and the pages come in the
-- next PR, and they read nothing here until this file is applied (a missing
-- table reads as "not applied yet": no circle to post from, every page as it
-- is today).
--
-- church_moments (server-only: RLS on, no policies, browser roles revoked):
-- one row a moment.
--   posted_by    the person who posted it (a pastor, a leader the church
--                picked, or a group's leader); their moments go with them
--   group_id     null = the whole church; otherwise the one group that sees
--                it (a group's leader posts only to groups they lead)
--   line         what they said, 1 to 120 characters
--   media_path   where its picture is kept (stored as News photos are)
--   media_kind   'photo' only today; the column is ready for 'video', which
--                is not built (adding it is a change to this check)
--   button_kind  the optional button, picked from this week:
--                service    Sunday's service, "I'm coming"
--                event      an event's sign-up or "I'm coming"
--                gathering  a group's gathering, "I'll be there"
--   button_ref   what the button is for: the calendar entry's id (service,
--                event) or "<group id>@<YYYY-MM-DD>" (gathering); both set
--                or both empty
--   starts_at    when it started showing
--   ends_at      when it stops showing on its own: a day, the end of the
--                church's coming Sunday on the church's clock, or three
--                days. "Until Sunday" posted on a Monday runs almost seven
--                days, so the check allows seven days and two hours (a clock
--                change), never more
--   status       shown | held (the check held it: only its poster sees it,
--                and the church's safety officers decide) | removed
--   held_reason  harm | self_harm, while the check's word stands
--   decided_at, decided_by
--                a safety officer's Let it through / Keep it hidden
--   removed_at, removed_by
--                taken down (by its poster, a pastor, the church's owner, or
--                a safety officer keeping it hidden): who, as text, the way
--                church_post_comments.removed_by records it
--
-- church_moment_marks (server-only, the same way): one row a person a
-- moment, written by the server as they see it and as they love it.
--   seen_at      when they first saw it (written once)
--   loved_at     when they loved it; null again when they take it back
-- The poster's sheet counts these rows ("Seen by 84", "31 loved it"); no
-- name is ever read for it.
--
-- Why server-only: the member app is drawn by the server, which checks who
-- may post, who may see a group's moment and whose marks are whose before it
-- reads or writes with the service role. No app login reads these tables, so
-- there is no policy (docs/RLS_MODEL.md: server code uses the service role;
-- never an allow-all).
--
-- Two new tables, two triggers that keep every row inside its own church,
-- one transaction, lock_timeout 5s, safe to run twice, nothing dropped, no
-- existing table touched. Apply any time.
begin;

set local lock_timeout = '5s';

create table if not exists public.church_moments(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  posted_by uuid not null references public.contacts(id) on delete cascade,
  group_id uuid references public.groups(id) on delete cascade,
  line text not null check (char_length(btrim(line)) between 1 and 120),
  media_path text not null check (char_length(media_path) between 1 and 1000),
  media_kind text not null default 'photo' check (media_kind in ('photo')),
  button_kind text check (button_kind is null or button_kind in ('service', 'event', 'gathering')),
  button_ref text check (button_ref is null or char_length(button_ref) between 1 and 120),
  starts_at timestamptz not null default now(),
  ends_at timestamptz not null,
  status text not null default 'shown' check (status in ('shown', 'held', 'removed')),
  held_reason text check (held_reason is null or held_reason in ('harm', 'self_harm')),
  decided_at timestamptz,
  decided_by text not null default '' check (char_length(decided_by) <= 80),
  created_at timestamptz not null default now(),
  removed_at timestamptz,
  removed_by text not null default '' check (char_length(removed_by) <= 80),
  constraint church_moments_button_whole check ((button_kind is null) = (button_ref is null)),
  constraint church_moments_ends_after check (ends_at > starts_at),
  constraint church_moments_ends_within check (ends_at <= starts_at + interval '7 days 2 hours'),
  constraint church_moments_held_has_reason check (status <> 'held' or held_reason is not null)
);

-- Home's row: this church's moments still showing (and the poster's own held
-- one), newest ends first.
create index if not exists church_moments_live on public.church_moments(business_id, ends_at)
  where status in ('shown', 'held');
create index if not exists church_moments_group on public.church_moments(group_id)
  where group_id is not null;
create index if not exists church_moments_poster on public.church_moments(posted_by);
-- The safety officers' held list.
create index if not exists church_moments_held on public.church_moments(business_id, created_at desc)
  where status = 'held';

create table if not exists public.church_moment_marks(
  moment_id uuid not null references public.church_moments(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  seen_at timestamptz,
  loved_at timestamptz,
  primary key (moment_id, contact_id)
);
create index if not exists church_moment_marks_contact on public.church_moment_marks(contact_id);

-- Every row stays inside its own church: the poster and the group are this
-- church's; a mark is on this church's moment, by this church's person.
create or replace function public.church_moments_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.contacts c where c.id = new.posted_by and c.business_id = new.business_id) then
    raise exception 'That person is not in this business';
  end if;
  if new.group_id is not null
     and not exists (select 1 from public.groups g where g.id = new.group_id and g.business_id = new.business_id) then
    raise exception 'That group is not in this business';
  end if;
  return new;
end $$;
revoke all on function public.church_moments_same_business() from public, anon, authenticated;
drop trigger if exists church_moments_same_business on public.church_moments;
create trigger church_moments_same_business before insert or update of business_id, posted_by, group_id
  on public.church_moments for each row execute function public.church_moments_same_business();

create or replace function public.church_moment_marks_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.church_moments m where m.id = new.moment_id and m.business_id = new.business_id) then
    raise exception 'That moment is not in this business';
  end if;
  if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this business';
  end if;
  return new;
end $$;
revoke all on function public.church_moment_marks_same_business() from public, anon, authenticated;
drop trigger if exists church_moment_marks_same_business on public.church_moment_marks;
create trigger church_moment_marks_same_business before insert or update of business_id, moment_id, contact_id
  on public.church_moment_marks for each row execute function public.church_moment_marks_same_business();

alter table public.church_moments enable row level security;
revoke all on public.church_moments from public, anon, authenticated;
grant all on public.church_moments to service_role;

alter table public.church_moment_marks enable row level security;
revoke all on public.church_moment_marks from public, anon, authenticated;
grant all on public.church_moment_marks to service_role;

commit;

notify pgrst, 'reload schema';

-- Check:
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('anon', c.oid, 'select') as anon_reads,
--          has_table_privilege('service_role', c.oid, 'insert') as server_writes
--     from pg_class c
--    where c.oid in ('public.church_moments'::regclass, 'public.church_moment_marks'::regclass)
--    order by c.relname;
--   -- 2 rows: church_moment_marks and church_moments, each true, 0, false, false, true
--   select conrelid::regclass, conname, contype from pg_constraint
--    where conrelid in ('public.church_moments'::regclass, 'public.church_moment_marks'::regclass)
--    order by 1, 2;
--   -- church_moments: button_whole, ends_after, ends_within, held_has_reason, the column checks
--   -- (line, media_path, media_kind, button_kind, button_ref, status, held_reason, decided_by,
--   -- removed_by), the primary key and the foreign keys to businesses, contacts and groups;
--   -- church_moment_marks: the primary key and the foreign keys to church_moments, businesses
--   -- and contacts
--   select tgname from pg_trigger
--    where tgrelid in ('public.church_moments'::regclass, 'public.church_moment_marks'::regclass)
--      and not tgisinternal order by 1;
--   -- church_moment_marks_same_business, church_moments_same_business
--   select count(*) from public.church_moments;       -- 0
--   select count(*) from public.church_moment_marks;  -- 0
--
-- Rollback (loses every moment and who saw or loved one; nothing else changes):
--   drop table if exists public.church_moment_marks;
--   drop table if exists public.church_moments;
--   drop function if exists public.church_moment_marks_same_business();
--   drop function if exists public.church_moments_same_business();
