-- Every group has a leader (mission M-8; Kevin 2026-11-28 said GO on the
-- proposal in kai/reviews/leaders-roles-group-leaders.md). A group's leader
-- is the group's own leader row (group_members.role = 'leader'), the record
-- the member app, the Lead tab and the Sunday hub (M-7) already read. This
-- file adds what that record was missing:
--
--   group_members.co_leader      a leader row that is the group's co-leader,
--                                not its lead. It keeps role = 'leader', so
--                                every reader that means "leads it" (the Lead
--                                tab, messaging, the Sunday hub's team_leader)
--                                still counts them. A row that stops leading
--                                (role back to 'member') stops being a
--                                co-leader (trigger group_members_co_leader).
--   groups.answers_to_contact_id the one person this group's leaders answer to
--                                (Kevin: one person a group; co-leaders never
--                                answer to someone else). Null = the fallback:
--                                the group's department, then the role chain.
--   groups.course_id             a class group's Course Studio class (Kevin:
--                                the class group is where the teacher leads and
--                                talks with the class; Course Studio is where
--                                they get what they need to teach).
--   groups.serve_option          a team's choice on the Serve card, so a
--                                sign-up for it reaches this team's leader.
--   worship_ministries.leader_contact_id
--                                a ministry's leader as one of the church's
--                                people (Kevin: from the members list); the
--                                typed name and email stay for the links and
--                                emails that read them.
--
-- Each new column is checked against the row's own church by a trigger
-- (group_leads_same_business), only when a write names it. No table is made,
-- nothing is dropped, every existing row reads its default (not a co-leader;
-- answers to nobody; no class; no Serve choice; no ministry person). The
-- server never sends these columns until it reads them back
-- (church_group_leads.ready()), so the code is safe before the file.
--
-- One transaction, lock_timeout 5s, safe twice, ends with NOTIFY pgrst.
-- Checked on PGlite by __tests__/group_leads_db.mjs.

begin;

set local lock_timeout = '5s';

alter table public.group_members add column if not exists co_leader boolean not null default false;

alter table public.groups add column if not exists answers_to_contact_id uuid;
alter table public.groups add column if not exists course_id uuid;
alter table public.groups add column if not exists serve_option text;

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'groups_answers_to_fkey'
                   and conrelid = 'public.groups'::regclass) then
    alter table public.groups add constraint groups_answers_to_fkey
      foreign key (answers_to_contact_id) references public.contacts(id) on delete set null;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'groups_course_fkey'
                   and conrelid = 'public.groups'::regclass) then
    alter table public.groups add constraint groups_course_fkey
      foreign key (course_id) references public.academy_courses(id) on delete set null;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'groups_serve_option_len'
                   and conrelid = 'public.groups'::regclass) then
    alter table public.groups add constraint groups_serve_option_len
      check (serve_option is null or char_length(btrim(serve_option)) between 1 and 120);
  end if;
end $$;

create index if not exists groups_answers_to on public.groups(answers_to_contact_id)
  where answers_to_contact_id is not null;
create index if not exists groups_course on public.groups(course_id) where course_id is not null;

alter table public.worship_ministries add column if not exists leader_contact_id uuid;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'worship_ministries_leader_fkey'
                   and conrelid = 'public.worship_ministries'::regclass) then
    alter table public.worship_ministries add constraint worship_ministries_leader_fkey
      foreign key (leader_contact_id) references public.contacts(id) on delete set null;
  end if;
end $$;

-- A row that stops leading stops being a co-leader; a member row is never one.
create or replace function public.group_members_co_leader() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.role <> 'leader' then
    new.co_leader := false;
  end if;
  return new;
end $$;
revoke all on function public.group_members_co_leader() from public, anon, authenticated;
drop trigger if exists group_members_co_leader on public.group_members;
create trigger group_members_co_leader before insert or update of role, co_leader
  on public.group_members for each row execute function public.group_members_co_leader();

-- Each new column stays inside its row's own church.
create or replace function public.group_leads_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'groups' then
    if new.answers_to_contact_id is not null and (tg_op = 'INSERT'
        or new.answers_to_contact_id is distinct from old.answers_to_contact_id
        or new.business_id is distinct from old.business_id) then
      if not exists (select 1 from public.contacts c
                     where c.id = new.answers_to_contact_id and c.business_id = new.business_id) then
        raise exception 'The person this group answers to is not in this church';
      end if;
    end if;
    if new.course_id is not null and (tg_op = 'INSERT'
        or new.course_id is distinct from old.course_id
        or new.business_id is distinct from old.business_id) then
      if not exists (select 1 from public.academy_courses a
                     where a.id = new.course_id and a.business_id = new.business_id) then
        raise exception 'That class is not in this church';
      end if;
    end if;
  elsif tg_table_name = 'worship_ministries' then
    if new.leader_contact_id is not null and (tg_op = 'INSERT'
        or new.leader_contact_id is distinct from old.leader_contact_id
        or new.business_id is distinct from old.business_id) then
      if not exists (select 1 from public.contacts c
                     where c.id = new.leader_contact_id and c.business_id = new.business_id) then
        raise exception 'That ministry leader is not in this church';
      end if;
    end if;
  end if;
  return new;
end $$;
revoke all on function public.group_leads_same_business() from public, anon, authenticated;
drop trigger if exists group_leads_same_business on public.groups;
create trigger group_leads_same_business
  before insert or update of answers_to_contact_id, course_id, business_id
  on public.groups for each row execute function public.group_leads_same_business();
drop trigger if exists group_leads_same_business on public.worship_ministries;
create trigger group_leads_same_business
  before insert or update of leader_contact_id, business_id
  on public.worship_ministries for each row execute function public.group_leads_same_business();

commit;

notify pgrst, 'reload schema';

-- ─── Check after ───────────────────────────────────────────────────────
-- select table_name, column_name, data_type, column_default
--   from information_schema.columns
--  where table_schema = 'public'
--    and (table_name, column_name) in (('group_members', 'co_leader'), ('groups', 'answers_to_contact_id'),
--         ('groups', 'course_id'), ('groups', 'serve_option'), ('worship_ministries', 'leader_contact_id'))
--  order by 1, 2;                                                  -- 5 rows
-- select tgname, tgrelid::regclass from pg_trigger
--  where tgname in ('group_members_co_leader', 'group_leads_same_business') order by 1, 2;   -- 3 rows
-- select count(*) from public.group_members where co_leader;       -- 0
--
-- ─── Rollback ──────────────────────────────────────────────────────────
-- begin;
-- drop trigger if exists group_leads_same_business on public.groups;
-- drop trigger if exists group_leads_same_business on public.worship_ministries;
-- drop trigger if exists group_members_co_leader on public.group_members;
-- drop function if exists public.group_leads_same_business();
-- drop function if exists public.group_members_co_leader();
-- alter table public.worship_ministries drop column if exists leader_contact_id;
-- alter table public.groups drop column if exists serve_option, drop column if exists course_id,
--   drop column if exists answers_to_contact_id;
-- alter table public.group_members drop column if exists co_leader;
-- commit;
-- notify pgrst, 'reload schema';
