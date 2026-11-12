-- APPLY-2026-11-12-church-job-descriptions.sql
--
-- Everyone's job at a church, in its own words (church_job_descriptions.py,
-- chief_church_jobs.py; docs/CHURCH_JOB_DESCRIPTIONS.md). Kevin, 2026-11-12:
-- "I need to make sure chief is able to learn job descriptions for everyone.
-- this important because when a job is created and the leader is unaware,
-- Chief should know Jobs of each person."
--
-- church_job_descriptions (server-only: RLS on, no policies, browser roles
-- revoked): one written job description a person.
--   contact_id     the person (one of the church's own people:
--                  church_job_descriptions_same_business); goes with them
--   user_id        the login, for a login with no person behind it (and kept
--                  beside contact_id when the person is a login). No foreign
--                  key: a login that leaves leaves its row, which no reader
--                  shows once the seat is gone
--   title          80 at most; null = none written
--   description    1 to 8000, never empty (clearing deletes the row); line
--                  breaks kept as written (sections such as "On Sunday")
--   source         said | pasted | document | drafted
--   written_by/at  who first wrote one for this person, and when
--   updated_by/at  who wrote the words saved now, and when (an undo puts
--                  back the earlier writer's words with their name)
-- One row a person (church_job_descriptions_person), else one a login with no
-- person (church_job_descriptions_login).
--
-- church_job_description_changes (server-only, the same): the log, and undo.
--   before         the row as it was (null = there was none)
--   after          the row as it is now (null = cleared)
--   by, at         who changed it, when; undone_at when it was put back (only
--                  the last change is ever put back)
--
-- A church that goes takes everything; a person who goes takes their row and
-- its log.
--
-- New tables only: one transaction, safe to run twice, nothing dropped. Apply
-- before the code that reads it: until then every route answers 503 ("isn't
-- ready") and Chief's verbs say it isn't ready, for the platform owner's
-- church (the switch's default); people_under and one_on_one leave the job
-- line out.
--
-- The #1801 habit: the CHECKs and the foreign keys beyond the church's are
-- added after the table, each once (by name), NOT VALID: on a new table there
-- is nothing old to check, every row written from now on is checked, and a
-- second run adds nothing. Each can be validated later with
--   alter table public.<table> validate constraint <name>;
begin;

set local lock_timeout = '5s';

create table if not exists public.church_job_descriptions(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid,
  user_id uuid,
  title text,
  description text not null,
  source text not null default 'said',
  written_by uuid,
  written_at timestamptz not null default now(),
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table if not exists public.church_job_description_changes(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid,
  user_id uuid,
  before jsonb,
  after jsonb,
  by uuid,
  at timestamptz not null default now(),
  undone_at timestamptz
);

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'church_job_descriptions_contact_id_fkey'
                 and conrelid = 'public.church_job_descriptions'::regclass) then
    alter table public.church_job_descriptions
      add constraint church_job_descriptions_contact_id_fkey foreign key (contact_id)
        references public.contacts(id) on delete cascade not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_job_descriptions_written_by_fkey'
                 and conrelid = 'public.church_job_descriptions'::regclass) then
    alter table public.church_job_descriptions
      add constraint church_job_descriptions_written_by_fkey foreign key (written_by)
        references auth.users(id) on delete set null not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_job_descriptions_updated_by_fkey'
                 and conrelid = 'public.church_job_descriptions'::regclass) then
    alter table public.church_job_descriptions
      add constraint church_job_descriptions_updated_by_fkey foreign key (updated_by)
        references auth.users(id) on delete set null not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_job_descriptions_someone'
                 and conrelid = 'public.church_job_descriptions'::regclass) then
    alter table public.church_job_descriptions
      add constraint church_job_descriptions_someone check (contact_id is not null or user_id is not null) not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_job_descriptions_words'
                 and conrelid = 'public.church_job_descriptions'::regclass) then
    alter table public.church_job_descriptions
      add constraint church_job_descriptions_words check (
        (title is null or char_length(title) between 1 and 80)
        and char_length(btrim(description)) between 1 and 8000
        and source in ('said', 'pasted', 'document', 'drafted')) not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_job_description_changes_contact_id_fkey'
                 and conrelid = 'public.church_job_description_changes'::regclass) then
    alter table public.church_job_description_changes
      add constraint church_job_description_changes_contact_id_fkey foreign key (contact_id)
        references public.contacts(id) on delete cascade not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_job_description_changes_by_fkey'
                 and conrelid = 'public.church_job_description_changes'::regclass) then
    alter table public.church_job_description_changes
      add constraint church_job_description_changes_by_fkey foreign key (by)
        references auth.users(id) on delete set null not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_job_description_changes_someone'
                 and conrelid = 'public.church_job_description_changes'::regclass) then
    alter table public.church_job_description_changes
      add constraint church_job_description_changes_someone check (contact_id is not null or user_id is not null)
        not valid;
  end if;
end $$;

-- The person is the description's own church's, whatever the caller passes
-- (as church_handovers_same_business holds a hand-over's leader).
create or replace function public.church_job_descriptions_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.contact_id is not null
     and (tg_op = 'INSERT' or new.contact_id is distinct from old.contact_id
          or new.business_id is distinct from old.business_id)
     and not exists (select 1 from public.contacts c
                     where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this church';
  end if;
  return new;
end $$;

drop trigger if exists church_job_descriptions_same_business on public.church_job_descriptions;
create trigger church_job_descriptions_same_business
  before insert or update of contact_id, business_id on public.church_job_descriptions
  for each row execute function public.church_job_descriptions_same_business();

revoke all on function public.church_job_descriptions_same_business() from public, anon, authenticated;

-- One a person; one a login with no person behind it.
create unique index if not exists church_job_descriptions_person
  on public.church_job_descriptions (business_id, contact_id)
  where contact_id is not null;
create unique index if not exists church_job_descriptions_login
  on public.church_job_descriptions (business_id, user_id)
  where contact_id is null;

-- A person's last change (undo reads only the last), by person or by login.
create index if not exists church_job_description_changes_person
  on public.church_job_description_changes (business_id, contact_id, at desc);
create index if not exists church_job_description_changes_login
  on public.church_job_description_changes (business_id, user_id, at desc);

alter table public.church_job_descriptions enable row level security;
alter table public.church_job_description_changes enable row level security;
revoke all on public.church_job_descriptions from anon, authenticated;
revoke all on public.church_job_description_changes from anon, authenticated;
grant all on public.church_job_descriptions to service_role;
grant all on public.church_job_description_changes to service_role;

comment on table public.church_job_descriptions is
  'Church job descriptions (church_job_descriptions.py): one person''s job in the church''s own words. Server-only (RLS on, no policies). Pay never goes in one (the server refuses it).';
comment on column public.church_job_descriptions.user_id is
  'The login, for a login with no person behind it (kept beside contact_id when the person is a login). No foreign key: a row of a login that left is shown by no reader.';
comment on column public.church_job_descriptions.updated_by is
  'Who wrote the words saved now. An undo puts back the earlier writer''s words with their name.';
comment on table public.church_job_description_changes is
  'Church job descriptions: every change (before and after, null = none), who and when; undone_at when it was put back. Only the last change is ever put back. Server-only (RLS on, no policies).';

commit;

-- Check:
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('anon', c.oid, 'select') as anon_reads
--     from pg_class c
--    where c.oid in ('public.church_job_descriptions'::regclass, 'public.church_job_description_changes'::regclass)
--    order by c.relname;
--   -- 2 rows, each: true, 0, false, false
--   select count(*) from pg_indexes where schemaname = 'public'
--      and indexname in ('church_job_descriptions_person', 'church_job_descriptions_login',
--                        'church_job_description_changes_person', 'church_job_description_changes_login');
--   -- 4
--   select conname, convalidated from pg_constraint
--    where conrelid in ('public.church_job_descriptions'::regclass, 'public.church_job_description_changes'::regclass)
--      and contype in ('c', 'f') order by conname;
--   -- 10 rows: the two businesses foreign keys convalidated true; the other 8 false (NOT VALID: enforced on
--   -- every new write)
--   select count(*) from pg_trigger where tgname = 'church_job_descriptions_same_business' and not tgisinternal;
--   -- 1
--
-- Rollback (loses every job description and its log):
--   drop table if exists public.church_job_description_changes;
--   drop table if exists public.church_job_descriptions;
--   drop function if exists public.church_job_descriptions_same_business();
