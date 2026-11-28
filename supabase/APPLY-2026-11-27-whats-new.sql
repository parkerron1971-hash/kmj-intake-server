-- APPLY-2026-11-27-whats-new.sql
--
-- What's New moves into the database (platform_updates.py). Kevin, 2026-11-27,
-- "yes to all" on the rework plan (solutionist-studio docs/whats-new-rework-plan.md):
-- the update list lives here instead of the frontend's whatsNew.ts, a PR's
-- update goes in its description and becomes a draft on merge, and Kevin
-- publishes from one Mission Control queue. Seen-state is kept per login and
-- business, so it follows a person across their devices.
--
-- Three new server-only tables (RLS on, no policies, browser roles revoked).
-- The app reads and writes them only through the backend's routes.
--
-- platform_updates       one row an update
--   id                   'YYYY-MM-DD-short-slug' (the old ledger's ids, kept)
--   date                 the day it shipped
--   status               draft | published | archived
--   source               ledger (imported from whatsNew.ts) | pr (a merged PR's
--                        whats-new block) | sweep (drafted for a merged PR that
--                        had none) | editor (written in Mission Control)
--   area                 the room it lives in ('Chief', 'Operate', 'Everywhere'…)
--   page                 'area:id' the Show me button opens, or null
--   kinds                canonical verticals it is for ('ministry'…); empty = all
--   areas                church office areas it is for; empty = all
--   roles                logins it is for ('owner'…); empty = all
--   weight               big (gets the tour, ranks up) | normal | small
--   group_key            several PRs of one feature fold into one line
--   title, line, body    short title, one line, the full words
--   church_title/_line/_body   the same in a church's words (null = use the above)
--   tour                 [{text, church_text?, anchor?}] steps for a big change
--   source_repo, source_pr     where a pr/sweep draft came from
--   notes                editor's notes (never shown to practitioners)
-- platform_update_seen   one row a login has seen an update in a business
--   how                  card | list | show_me | tour | listen | dismissed | all
-- platform_news_drafts   a news post drafted from an update, for Kevin to approve
--
-- New tables only, one transaction, safe to run twice. Checked on PGlite by
-- __tests__/whats_new_db.mjs.

begin;

set local lock_timeout = '5s';

create table if not exists public.platform_updates(
  id text primary key,
  date date not null,
  status text not null default 'draft',
  source text not null default 'editor',
  area text not null default 'Everywhere',
  page text,
  kinds text[] not null default '{}',
  areas text[] not null default '{}',
  roles text[] not null default '{}',
  weight text not null default 'normal',
  group_key text,
  title text not null,
  line text not null default '',
  body text not null default '',
  church_title text,
  church_line text,
  church_body text,
  tour jsonb not null default '[]'::jsonb,
  source_repo text,
  source_pr integer,
  notes text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  published_at timestamptz,
  constraint platform_updates_id_shape check (id ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]{1,70}$'),
  constraint platform_updates_status check (status in ('draft', 'published', 'archived')),
  constraint platform_updates_source check (source in ('ledger', 'pr', 'sweep', 'editor')),
  constraint platform_updates_weight check (weight in ('big', 'normal', 'small')),
  constraint platform_updates_page_shape check (page is null or page ~ '^[a-z0-9_-]{1,30}:[a-z0-9_-]{1,60}$'),
  constraint platform_updates_area_len check (char_length(area) between 1 and 40),
  constraint platform_updates_title_len check (char_length(title) between 1 and 200),
  constraint platform_updates_line_len check (char_length(line) <= 300),
  constraint platform_updates_body_len check (char_length(body) <= 6000),
  constraint platform_updates_church_title_len check (church_title is null or char_length(church_title) <= 200),
  constraint platform_updates_church_line_len check (church_line is null or char_length(church_line) <= 300),
  constraint platform_updates_church_body_len check (church_body is null or char_length(church_body) <= 6000),
  constraint platform_updates_group_len check (group_key is null or char_length(group_key) between 1 and 80),
  constraint platform_updates_notes_len check (char_length(notes) <= 2000),
  constraint platform_updates_tour_list check (jsonb_typeof(tour) = 'array'),
  constraint platform_updates_repo check (source_repo is null or source_repo in ('solutionist-studio', 'kmj-intake-server'))
);
create index if not exists platform_updates_status_date on public.platform_updates (status, date desc, id desc);
create index if not exists platform_updates_source_pr on public.platform_updates (source_repo, source_pr) where source_pr is not null;

create table if not exists public.platform_update_seen(
  user_id uuid not null,
  business_id uuid not null references public.businesses(id) on delete cascade,
  update_id text not null references public.platform_updates(id) on delete cascade,
  seen_at timestamptz not null default now(),
  how text not null default 'list',
  primary key (user_id, business_id, update_id),
  constraint platform_update_seen_how check (how in ('card', 'list', 'show_me', 'tour', 'listen', 'dismissed', 'all'))
);
create index if not exists platform_update_seen_update on public.platform_update_seen (update_id);

create table if not exists public.platform_news_drafts(
  id uuid primary key default gen_random_uuid(),
  update_id text references public.platform_updates(id) on delete set null,
  status text not null default 'draft',
  audience text not null default 'all',
  headline text not null,
  body text not null default '',
  church_headline text,
  church_body text,
  source_repo text,
  source_pr integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  decided_at timestamptz,
  constraint platform_news_drafts_status check (status in ('draft', 'approved', 'dropped')),
  constraint platform_news_drafts_audience check (audience in ('all', 'business', 'church')),
  constraint platform_news_drafts_headline_len check (char_length(headline) between 1 and 200),
  constraint platform_news_drafts_body_len check (char_length(body) <= 8000),
  constraint platform_news_drafts_church_headline_len check (church_headline is null or char_length(church_headline) <= 200),
  constraint platform_news_drafts_church_body_len check (church_body is null or char_length(church_body) <= 8000),
  constraint platform_news_drafts_repo check (source_repo is null or source_repo in ('solutionist-studio', 'kmj-intake-server'))
);
create index if not exists platform_news_drafts_status on public.platform_news_drafts (status, created_at desc);
create unique index if not exists platform_news_drafts_one_pr on public.platform_news_drafts (source_repo, source_pr)
  where source_pr is not null;

alter table public.platform_updates enable row level security;
alter table public.platform_update_seen enable row level security;
alter table public.platform_news_drafts enable row level security;

revoke all on public.platform_updates from anon, authenticated;
revoke all on public.platform_update_seen from anon, authenticated;
revoke all on public.platform_news_drafts from anon, authenticated;
grant all on public.platform_updates to service_role;
grant all on public.platform_update_seen to service_role;
grant all on public.platform_news_drafts to service_role;

comment on table public.platform_updates is
  'What''s New: one row an update (platform_updates.py). Server-only; the app reads it through /updates/for-me.';
comment on table public.platform_update_seen is
  'What''s New: which updates a login has seen in a business, and how. Server-only.';
comment on table public.platform_news_drafts is
  'What''s New: news posts drafted from updates, for the platform owner to approve. Server-only.';

commit;

-- ── CHECK AFTER ─────────────────────────────────────────────────────────
-- Three rows, each: rls true, policies 0, browser_reads false, server_writes true.
--
-- select c.relname, c.relrowsecurity as rls,
--        (select count(*) from pg_policies p where p.tablename = c.relname) as policies,
--        has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--        has_table_privilege('service_role', c.oid, 'insert') as server_writes
--   from pg_class c
--  where c.relname in ('platform_updates', 'platform_update_seen', 'platform_news_drafts');
