-- The Move-in room (church_move_in.py). Kevin, 2026-11-11, with the first
-- founding church signing up: "create upload areas of the information that
-- they need to hand into the system and I don't directly have to load it".
--
--   church_move_items   one row an item a church has touched (the eleven on
--                       the move handout): its answers, where it stands
--                       (todo, handed_in, checked, needs) and the note we
--                       wrote when we asked for a change.
--   church_move_files   one row a file handed in. The file itself is in the
--                       PRIVATE business-documents bucket (already there,
--                       APPLY-2026-08-10) at "<church>/move-in/<name>".
--
-- Both server-only: RLS on, no policies, browser roles revoked. Nothing is
-- written for any church until its office opens the room. Additive, one
-- transaction, safe to run twice.
begin;
set local lock_timeout = '5s';

create table if not exists public.church_move_items(
  business_id uuid not null references public.businesses(id) on delete cascade,
  item text not null check (char_length(item) between 1 and 40),
  state text not null default 'todo' check (state in ('todo', 'handed_in', 'checked', 'needs')),
  answers jsonb not null default '{}'::jsonb
    check (jsonb_typeof(answers) = 'object' and octet_length(answers::text) <= 60000),
  note text check (note is null or char_length(note) <= 600),
  handed_in_at timestamptz,
  handed_in_by uuid,
  checked_at timestamptz,
  updated_by uuid,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  primary key (business_id, item)
);

create table if not exists public.church_move_files(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  item text not null check (char_length(item) between 1 and 40),
  path text not null unique check (char_length(path) between 10 and 300),
  name text not null check (char_length(name) between 1 and 120),
  media_type text not null check (char_length(media_type) between 3 and 120),
  size_bytes integer not null check (size_bytes between 1 and 15728640),
  uploaded_by uuid,
  created_at timestamptz not null default now()
);
create index if not exists church_move_files_by_item
  on public.church_move_files (business_id, item, created_at);

alter table public.church_move_items enable row level security;
alter table public.church_move_files enable row level security;
revoke all on public.church_move_items from anon, authenticated;
revoke all on public.church_move_files from anon, authenticated;
grant all on public.church_move_items to service_role;
grant all on public.church_move_files to service_role;

commit;

-- Check:
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads
--     from pg_class c
--    where c.oid in ('public.church_move_items'::regclass, 'public.church_move_files'::regclass);
--   -- two rows, each: true, 0, false
--
-- Rollback (loses what churches handed in; the files stay in storage):
--   drop table if exists public.church_move_files; drop table if exists public.church_move_items;
