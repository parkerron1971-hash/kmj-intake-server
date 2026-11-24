-- Chief's saved conversations, one login's apart from another's (Kevin, 2026-11-23:
-- "check out a conversation Jessica was having with Chief"; her words could not be
-- read, because they were never saved).
--
-- Until now public.chief_conversations kept no login, and its one policy let only
-- the business's OWNER read or write a row. A turn is saved as the person who
-- asked, so every office login's save was refused without a word: at Love City,
-- 72 Chief turns in a week and 18 saved.
--
-- This file:
--   1. adds user_id (who asked). A row saved before today has none: it is the
--      owner's (only the owner's saves ever landed).
--   2. each login reads ITS OWN rows; the owner reads the owner's own and the rows
--      from before today. Nobody reads another login's rows through the app: an
--      owner reads the team's through the server, with each one named
--      (a later change), never mixed unnamed into the owner's own history.
--   3. the server writes every row (service role), with the login it verified.
--      The owner's own app still saves its four-hour sweep as before.
--
-- Safe to apply before or after the code: the code writes user_id only once the
-- column answers (schema_probe), and reads the same rows either way.
-- No cross-table policy is added: the own-rows rule calls the existing
-- SECURITY DEFINER helpers public.is_business_member and
-- public.is_business_collaborator (2026_06_10 hotfix), the same ones
-- businesses' own select policies call, so there is no 42P17 cycle.
--
-- CHECK BEFORE (expect: user_id absent; one policy, chief_conversations_business_owner):
--   select column_name from information_schema.columns
--    where table_schema='public' and table_name='chief_conversations' and column_name='user_id';
--   select policyname, cmd from pg_policies
--    where schemaname='public' and tablename='chief_conversations' order by 1;
--   select to_regprocedure('public.is_business_member(uuid)') is not null as member_helper,
--          to_regprocedure('public.is_business_collaborator(uuid)') is not null as collaborator_helper;
-- If CHECK BEFORE shows any other policy on this table, stop: this file drops every policy on it
-- and makes exactly two.

begin;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

alter table public.chief_conversations
  add column if not exists user_id uuid;

comment on column public.chief_conversations.user_id is
  'The login that asked (auth.users.id), written by the server from the verified session. '
  'Null: saved before 2026-11-24, or by the owner''s own app: the owner''s.';

create index if not exists chief_conversations_business_user
  on public.chief_conversations (business_id, user_id, ended_at desc);

alter table public.chief_conversations enable row level security;

do $$
declare p record;
begin
  for p in select policyname from pg_policies
            where schemaname = 'public' and tablename = 'chief_conversations'
  loop
    execute format('drop policy %I on public.chief_conversations', p.policyname);
  end loop;
end $$;

-- The owner: the owner's own rows and the ones from before a login was kept.
create policy chief_conversations_business_owner on public.chief_conversations
  for all to authenticated
  using (business_id in (select id from public.businesses where owner_id = auth.uid())
         and (user_id is null or user_id = auth.uid()))
  with check (business_id in (select id from public.businesses where owner_id = auth.uid())
              and (user_id is null or user_id = auth.uid()));

-- Any other login: its own rows, while it is still on the business's team (a seat, or
-- its outside accountant). Read only: the server writes them.
create policy chief_conversations_own_read on public.chief_conversations
  for select to authenticated
  using (user_id = auth.uid()
         and (public.is_business_member(business_id) or public.is_business_collaborator(business_id)));

notify pgrst, 'reload schema';
commit;

-- CHECK AFTER (expect: user_id uuid; two policies: chief_conversations_business_owner ALL,
-- chief_conversations_own_read SELECT; the index; every existing row with user_id null):
--   select data_type from information_schema.columns
--    where table_schema='public' and table_name='chief_conversations' and column_name='user_id';
--   select policyname, cmd from pg_policies
--    where schemaname='public' and tablename='chief_conversations' order by 1;
--   select count(*) filter (where user_id is null) as before_today, count(*) as all_rows
--     from public.chief_conversations;
--
-- ROLLBACK, in this order:
--   1. Railway, BOTH services (kmj-intake-server and kmj-intake-worker): CHIEF_TURNS_BY_LOGIN=off.
--      The server then stops saving turns itself: a turn is saved as the person again, so the
--      owner's lands and an office login's is refused, as before this file. (Without this step the
--      server keeps saving the team's turns whatever the row rules say.)
--   2. Nothing else is needed: with the two rules of this file left in place, the team's rows
--      already saved stay readable only by whoever asked, and never show in the owner's history.
--   Only if the one old rule must come back as well (it lets the owner read every row of the
--   business, so the team's rows would show unnamed in the owner's own history): remove them first.
--     begin;
--     delete from public.chief_conversations c
--      where c.user_id is not null
--        and c.user_id <> (select b.owner_id from public.businesses b where b.id = c.business_id);
--     drop policy if exists chief_conversations_own_read on public.chief_conversations;
--     drop policy if exists chief_conversations_business_owner on public.chief_conversations;
--     create policy chief_conversations_business_owner on public.chief_conversations
--       for all to authenticated
--       using (business_id in (select id from public.businesses where owner_id = auth.uid()))
--       with check (business_id in (select id from public.businesses where owner_id = auth.uid()));
--     notify pgrst, 'reload schema';
--     commit;
--   The column is kept either way: dropping it would lose who asked.
