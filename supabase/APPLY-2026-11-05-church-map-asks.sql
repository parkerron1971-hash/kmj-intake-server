-- "Is this right?" (docs/CHURCH_LEADERS_STEP2.md §10, PR B11; Kevin approved it 2026-11-03: "yes to both,
-- build it"). Chief already knows who's talking from the login. An office login (a Manager or an Admin) now
-- checks the work Chief has them doing, and what they say is wrong or missing comes back to the owner and
-- the admins as one-tap edits. This file adds the one table that keeps those asks.
--
--   church_map_asks   one row an ask, kind:
--                       confirmed  they said it's right. `work` keeps what they were shown, so a later
--                                  change to their work offers the check again. Saved done: it waits on no one
--                       fix        their words (`said`), and with them, when Chief could say it so, a waiting
--                                  change to the leaders map (`change_id`, a pending church_map_changes row
--                                  they made) and/or a duty that would move (`duty_move`: {duty, to_user_id,
--                                  was}). Who sees what stays words only
--                       gap        nobody seems to do something; the same words from the same church inside
--                                  7 days join the open one
--                     open until the owner or an admin applies, marks done or discards it (resolved_by, at);
--                     `told_at` once the login that asked has heard how it went.
--
-- Not made for any church, Love City included: no ask. Nothing reads it until B11's code and CHURCH_MAP open
-- for a church; before this file every verb and route says the feature isn't ready.
--
-- Server-only: RLS on with no policies, anon and authenticated revoked, service_role granted, as
-- church_map_changes. No trigger or function is added or changed. Additive and idempotent: a second run
-- changes nothing and drops nothing. Needs APPLY-2026-11-05-church-map-step2.sql (church_map_changes) first.
-- Applied by hand after review.
begin;

-- Fail fast rather than queue behind a long read (a waiting lock would stall every query behind it).
set local lock_timeout = '5s';

create table if not exists public.church_map_asks(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  kind text not null check (kind in ('confirmed', 'fix', 'gap')),
  said text not null default '' check (char_length(said) <= 400),
  asked_by uuid references auth.users(id) on delete set null,
  asked_at timestamptz not null default now(),
  change_id uuid references public.church_map_changes(id) on delete set null,
  duty_move jsonb check (duty_move is null or jsonb_typeof(duty_move) = 'object'),
  work jsonb check (work is null or jsonb_typeof(work) = 'object'),
  status text not null default 'open' check (status in ('open', 'applied', 'done', 'discarded')),
  resolved_by uuid references auth.users(id) on delete set null,
  resolved_at timestamptz,
  told_at timestamptz,
  -- A fix or a gap is their words; only a fix carries a change or a duty move; a confirmed check waits on no one.
  constraint church_map_asks_words check (kind = 'confirmed' or char_length(btrim(said)) > 0),
  constraint church_map_asks_parts check (kind = 'fix' or (change_id is null and duty_move is null)),
  constraint church_map_asks_checked check (kind <> 'confirmed' or status = 'done'),
  constraint church_map_asks_resolved check (status = 'open' or resolved_at is not null)
);
create index if not exists church_map_asks_open on public.church_map_asks(business_id) where status = 'open';
create index if not exists church_map_asks_mine on public.church_map_asks(business_id, asked_by, asked_at desc);
-- The change link's foreign key: deleting a church's changes sets each ask's link to null, and without this
-- every deleted change would scan the table.
create index if not exists church_map_asks_change on public.church_map_asks(change_id) where change_id is not null;

-- Server-only: RLS on, browser roles revoked, service role granted, no policies.
alter table public.church_map_asks enable row level security;
revoke all on public.church_map_asks from anon, authenticated;
grant all on public.church_map_asks to service_role;

notify pgrst, 'reload schema';

commit;

-- Check after applying (13 columns; RLS on, 0 policies, no browser select; 3 indexes; no ask yet):
--   select count(*) from information_schema.columns where table_schema = 'public' and table_name = 'church_map_asks';
--     -- 13
--   select c.relrowsecurity, (select count(*) from pg_policies p where p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads
--     from pg_class c where c.relname = 'church_map_asks';   -- true, 0, false
--   select indexname from pg_indexes where tablename = 'church_map_asks' order by 1;
--     -- church_map_asks_change, church_map_asks_mine, church_map_asks_open, church_map_asks_pkey
--   select count(*) from church_map_asks;   -- 0
--
-- Rollback, only after the code that reads it is gone (it drops every ask the churches made):
--   begin; drop table if exists public.church_map_asks; notify pgrst, 'reload schema'; commit;
