-- APPLY-2026-11-15-sample-church.sql
--
-- The sample church (sample_church.py, BE-1). Kevin, 2026-11-14: a church that
-- signs up gets no working trial; it looks around a private copy of a made-up,
-- fully set-up church (Grace Street Fellowship) where nothing is saved or
-- sent, and choosing a plan starts its real church and deletes the sample.
--
-- Each church (its "home" business) gets its OWN sample: a second businesses
-- row, owned by the same person, is_active = false (out of the business list,
-- the business count and every is_active sweep), is_sample = true, sample_of =
-- the home. Every owner check and RLS policy works unchanged because the
-- visitor really owns it.
--
--   businesses   + is_sample  boolean not null default false
--                + sample_of  uuid, the home (on delete set null: a home's
--                             deletion orphans its sample for the cleanup,
--                             never deletes or blocks)
--                  check businesses_sample_shape: only a sample has a home,
--                    and never itself
--                  unique index businesses_one_sample_per_home: one sample
--                    per home, so racing ensure() calls make one row
--                  trigger businesses_guard_sample: the app's own logins
--                    (anon, authenticated) may never make a sample, turn a
--                    row into one or out of one, or change or delete one.
--                    The server (service_role) and the SQL editor (postgres)
--                    are not refused. Same test as the repo's other client
--                    guards (protect_gift_classification, 2026-09-29 /
--                    2026-10-27): current_user, which a client JWT cannot
--                    change, rather than request.jwt.claims, which a
--                    SECURITY DEFINER function can set. The function is
--                    SECURITY INVOKER (so current_user is the caller), reads
--                    no table, and is no policy: nothing here can recurse
--                    (docs/RLS_MODEL.md, the 42P17 rule). A foreign-key
--                    action runs as the table's owner, so a home's deletion
--                    can still null its sample's sample_of.
--   sample_church_questions   the questions Chief answers in a sample (ten a
--                    person; BE-4 writes them). RLS on; a person reads their
--                    own (select only); every write is the server's.
--
-- Additive: constant defaults (no table rewrite), one transaction, lock_timeout
-- 5s, safe to run twice. Apply BEFORE switching CHURCH_SAMPLE on for anyone;
-- the code probes the columns and behaves as off until they exist.
begin;

set local lock_timeout = '5s';

alter table public.businesses
  add column if not exists is_sample boolean not null default false,
  add column if not exists sample_of uuid null references public.businesses(id) on delete set null;

alter table public.businesses drop constraint if exists businesses_sample_shape;
alter table public.businesses add constraint businesses_sample_shape
  check (sample_of is null or (is_sample and sample_of <> id));

create unique index if not exists businesses_one_sample_per_home
  on public.businesses (sample_of) where sample_of is not null;

comment on column public.businesses.is_sample is
  'A sample church a church looks around before it starts (sample_church.py). Made and deleted by the server only (trigger businesses_guard_sample); never changes after insert.';
comment on column public.businesses.sample_of is
  'The church (home business) this sample belongs to; one sample per home. Set null when the home is deleted, which leaves the sample for the daily cleanup.';

create or replace function public.businesses_guard_sample() returns trigger
language plpgsql set search_path = public as $$
begin
  if current_user not in ('anon', 'authenticated') then
    return coalesce(new, old);
  end if;
  if tg_op = 'INSERT' then
    if new.is_sample or new.sample_of is not null then
      raise exception 'A sample church is made by Solutionist, not from the app'
        using errcode = '42501';
    end if;
    return new;
  end if;
  if old.is_sample then
    raise exception 'A sample church can''t be changed or deleted from the app'
      using errcode = '42501';
  end if;
  if tg_op = 'UPDATE' and (new.is_sample is distinct from old.is_sample
                           or new.sample_of is distinct from old.sample_of) then
    raise exception 'Only Solutionist makes a sample church'
      using errcode = '42501';
  end if;
  return coalesce(new, old);
end $$;

-- No revoke on the function: a trigger function can't be called directly,
-- and the trigger must fire for the app's own logins, which is its point.
drop trigger if exists businesses_guard_sample on public.businesses;
create trigger businesses_guard_sample
  before insert or update or delete on public.businesses
  for each row execute function public.businesses_guard_sample();

create table if not exists public.sample_church_questions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  home_business_id uuid references public.businesses(id) on delete set null,
  sample_business_id uuid references public.businesses(id) on delete set null,
  n smallint not null check (n between 1 and 50),
  question text,
  answer text,
  drafts jsonb,
  model text,
  input_tokens int check (input_tokens is null or input_tokens >= 0),
  output_tokens int check (output_tokens is null or output_tokens >= 0),
  cost_cents numeric check (cost_cents is null or cost_cents >= 0),
  created_at timestamptz not null default now(),
  unique (user_id, n)
);

-- The two business links are foreign keys with on delete set null: indexed,
-- so deleting a business never scans this table.
create index if not exists sample_church_questions_home
  on public.sample_church_questions (home_business_id) where home_business_id is not null;
create index if not exists sample_church_questions_sample
  on public.sample_church_questions (sample_business_id) where sample_business_id is not null;

comment on table public.sample_church_questions is
  'Questions Chief answered about the sample church (sample_church.py, BE-4 writes them): n is the person''s 1..10th question (50 at most), unique per person, so a new sample is never ten more. Read by the person; written by the server only.';

alter table public.sample_church_questions enable row level security;
revoke all on public.sample_church_questions from anon, authenticated;
grant select on public.sample_church_questions to authenticated;
grant all on public.sample_church_questions to service_role;

drop policy if exists sample_church_questions_own on public.sample_church_questions;
create policy sample_church_questions_own on public.sample_church_questions
  for select to authenticated using (user_id = (select auth.uid()));

commit;

-- Check:
--   select column_name, data_type, is_nullable, column_default from information_schema.columns
--    where table_schema = 'public' and table_name = 'businesses' and column_name in ('is_sample', 'sample_of')
--    order by 1;
--   -- 2 rows: is_sample boolean NO false; sample_of uuid YES
--   select conname from pg_constraint where conrelid = 'public.businesses'::regclass
--    and conname = 'businesses_sample_shape';                                   -- 1 row
--   select indexname from pg_indexes where tablename = 'businesses' and indexname = 'businesses_one_sample_per_home';  -- 1 row
--   select tgname from pg_trigger where tgrelid = 'public.businesses'::regclass and tgname = 'businesses_guard_sample'; -- 1 row
--   select count(*) from public.businesses where is_sample or sample_of is not null;  -- 0 (nothing is a sample yet)
--   select relrowsecurity from pg_class where oid = 'public.sample_church_questions'::regclass;  -- true
--   select policyname, cmd, roles, qual from pg_policies where tablename = 'sample_church_questions';
--   -- 1 row: sample_church_questions_own, SELECT, {authenticated}, (user_id = (SELECT auth.uid() AS uid))
--   select grantee, privilege_type from information_schema.role_table_grants
--    where table_name = 'sample_church_questions' and grantee in ('anon', 'authenticated') order by 1, 2;
--   -- 1 row: authenticated SELECT
--
-- Rollback (first delete every sample through the server, sample_church.end or
-- the daily cleanup, or each becomes an ordinary inactive business; loses the
-- questions asked):
--   begin;
--   drop trigger if exists businesses_guard_sample on public.businesses;
--   drop function if exists public.businesses_guard_sample();
--   drop table if exists public.sample_church_questions;
--   drop index if exists public.businesses_one_sample_per_home;
--   alter table public.businesses drop constraint if exists businesses_sample_shape;
--   alter table public.businesses drop column if exists sample_of, drop column if exists is_sample;
--   commit;
