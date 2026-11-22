-- APPLY-2026-11-21-member-plan-prefs.sql
--
-- Plans in the member app's new look (Look 5.1, behind MEMBER_LUMEN; the
-- pastor approved the Plans design on 2026-11-21: "go ahead"), its last step:
-- read a plan with your group, and a reminder at the hour you pick. A member
-- keeps both choices per plan here. The table only: the pages and the
-- reminder sweep come in the next PR and read nothing here until this file is
-- applied (a missing table reads as "not applied yet": no Remind me row, no
-- "read with" choice, every page as it is today).
--
-- member_plan_prefs (server-only: RLS on, no policies, browser roles
-- revoked): one row a member a plan, written only by the server for the
-- signed-in member themselves.
--   plan         the plan, named as member_plan_starts names it:
--                "reading:<key>" (a reading plan or a topic plan) or
--                "devotional:<id>" (a church devotional). Like member_plan_starts
--                it is a name, not a foreign key: deleting a devotional removes
--                its rows here in the same step as its starts (devotionals.py),
--                and the reminder sweep skips a devotional that isn't there
--   group_id     the group they read it with; null = on their own. A group
--                that is deleted lets the choice go (on delete set null)
--   remind_at    the time of day to be reminded, on the church's clock, on a
--                quarter hour; null = no reminder
--   reminded_on  the church's date the last reminder went (the sweep claims
--                a day by moving it, so one server copy sends it once)
--   updated_at
-- A group's members see how many of them read the plan with that group
-- (member_plan_prefs_group); the reminder sweep reads the rows with a time
-- (member_plan_prefs_remind).
--
-- Why server-only: the member app is drawn by the server, which checks the
-- signed-in member and that the group is one of theirs before it writes with
-- the service role. No app login reads this table, so there is no policy
-- (docs/RLS_MODEL.md: server code uses the service role; never an allow-all).
--
-- One new table, one trigger that keeps every row inside its own church (the
-- member and the group are the row's church's), one transaction,
-- lock_timeout 5s, safe to run twice, nothing dropped, no existing table
-- touched. Apply any time.
begin;

set local lock_timeout = '5s';

create table if not exists public.member_plan_prefs(
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  plan text not null check (plan ~ '^(reading:[a-z0-9-]{1,40}|devotional:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$'),
  group_id uuid references public.groups(id) on delete set null,
  remind_at time,
  reminded_on date,
  updated_at timestamptz not null default now(),
  primary key (business_id, contact_id, plan),
  constraint member_plan_prefs_quarter check (
    remind_at is null or (extract(second from remind_at) = 0 and extract(minute from remind_at)::int % 15 = 0))
);

-- The reminder sweep: the rows with a time.
create index if not exists member_plan_prefs_remind on public.member_plan_prefs(remind_at)
  where remind_at is not null;
-- "N reading this": a group's choices for one plan.
create index if not exists member_plan_prefs_group on public.member_plan_prefs(group_id, plan)
  where group_id is not null;
create index if not exists member_plan_prefs_contact on public.member_plan_prefs(contact_id);

-- Every row stays inside its own church: the member and the group are this
-- church's.
create or replace function public.member_plan_prefs_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this business';
  end if;
  if new.group_id is not null
     and not exists (select 1 from public.groups g where g.id = new.group_id and g.business_id = new.business_id) then
    raise exception 'That group is not in this business';
  end if;
  return new;
end $$;
revoke all on function public.member_plan_prefs_same_business() from public, anon, authenticated;
drop trigger if exists member_plan_prefs_same_business on public.member_plan_prefs;
create trigger member_plan_prefs_same_business before insert or update of business_id, contact_id, group_id
  on public.member_plan_prefs for each row execute function public.member_plan_prefs_same_business();

alter table public.member_plan_prefs enable row level security;
revoke all on public.member_plan_prefs from public, anon, authenticated;
grant all on public.member_plan_prefs to service_role;

commit;

notify pgrst, 'reload schema';

-- Check:
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('anon', c.oid, 'select') as anon_reads,
--          has_table_privilege('service_role', c.oid, 'insert') as server_writes
--     from pg_class c where c.oid = 'public.member_plan_prefs'::regclass;
--   -- 1 row: member_plan_prefs, true, 0, false, false, true
--   select conname, contype from pg_constraint where conrelid = 'public.member_plan_prefs'::regclass order by 1;
--   -- member_plan_prefs_quarter (c), the plan check (c), the primary key (p), and the foreign keys to
--   -- businesses, contacts and groups (f)
--   select indexname from pg_indexes where tablename = 'member_plan_prefs' order by 1;
--   -- member_plan_prefs_contact, member_plan_prefs_group, member_plan_prefs_pkey, member_plan_prefs_remind
--   select tgname, tgenabled from pg_trigger where tgrelid = 'public.member_plan_prefs'::regclass and not tgisinternal;
--   -- member_plan_prefs_same_business, O
--
-- Rollback (the members' choices of a group and a reminder go with it; nothing else reads them):
--   begin;
--   drop table if exists public.member_plan_prefs;
--   drop function if exists public.member_plan_prefs_same_business();
--   commit;
--   notify pgrst, 'reload schema';
