-- APPLY-2026-11-18-church-structure-drafts.sql
--
-- A church's structure draft: the standard start (church_structure.py,
-- chief_church_structure.py). Kevin, 2026-11-18: "will the system know what
-- to do with other churches? I want to make sure that other churches would
-- have the right type of setup when it comes to setting up there structure",
-- then "standard start first, then giving also consider adding the setup
-- with the church planning strategy".
--
-- church_structure_drafts (server-only: RLS on, no policies, browser roles
-- revoked): one row a church, the one draft of its office team.
--   business_id   the church; the primary key, so there is one draft a church
--   draft         the proposal as the server made it: the shape, the jobs it
--                 would use, each person with the login proposed for them,
--                 and what the pastor said about who handles the offering
--   made_by       the login that drafted it (no foreign key: a login that
--                 leaves leaves the draft)
--   made_at       when it was drafted
--   updated_at    when it last changed (a new draft, or an email typed on
--                 review)
--
-- Why its own table and not businesses.settings: every login that can read
-- the church's row reads its settings, and a draft names people and the
-- logins proposed for them (it may leave out, or lower, someone who can read
-- it). Here only the server reads it, for the owner, an Admin, or whoever
-- sets up jobs and people's sheets.
--
-- A draft grants nothing: no login, invitation, job or sheet is made or
-- changed by it. Each person is reviewed and saved through the writes that
-- are already behind the password.
--
-- One new table: one transaction, safe to run twice, nothing dropped, no
-- existing table touched. Apply any time. Until then the code reads "no
-- draft" (GET /church/structure answers ready: false, the standing check
-- still works) and the writes answer 503 "Team setup is being switched on.
-- Try again shortly."
begin;

set local lock_timeout = '5s';

create table if not exists public.church_structure_drafts(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  draft jsonb not null,
  made_by uuid,
  made_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'church_structure_drafts_is_object'
                 and conrelid = 'public.church_structure_drafts'::regclass) then
    alter table public.church_structure_drafts
      add constraint church_structure_drafts_is_object check (jsonb_typeof(draft) = 'object') not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_structure_drafts_size'
                 and conrelid = 'public.church_structure_drafts'::regclass) then
    alter table public.church_structure_drafts
      add constraint church_structure_drafts_size check (pg_column_size(draft) <= 1048576) not valid;
  end if;
end $$;

alter table public.church_structure_drafts enable row level security;
revoke all on public.church_structure_drafts from public, anon, authenticated;
grant all on public.church_structure_drafts to service_role;

commit;

notify pgrst, 'reload schema';

-- Check:
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('anon', c.oid, 'select') as anon_reads
--     from pg_class c
--    where c.oid = 'public.church_structure_drafts'::regclass;
--   -- 1 row: church_structure_drafts, true, 0, false, false
--   select conname, contype, convalidated from pg_constraint
--    where conrelid = 'public.church_structure_drafts'::regclass order by conname;
--   -- 4 rows: the primary key (p) and the foreign key to businesses (f), each true;
--   --         church_structure_drafts_is_object and church_structure_drafts_size (c), each false
--   --         (NOT VALID: enforced on every new write)
--   select count(*) from public.church_structure_drafts;
--   -- 0
--
-- Rollback (loses every draft waiting for review; no login, job or sheet changes, and a pastor drafts again):
--   drop table if exists public.church_structure_drafts;
