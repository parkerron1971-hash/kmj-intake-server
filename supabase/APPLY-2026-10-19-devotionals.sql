-- Plans & devotionals in the member app (member app round three, part 4;
-- Kevin approved the "Member App, Round Three" canvas 2026-10-19: "reading
-- plans plus church-made personal devotionals"). Three tables, all
-- server-only (RLS on, no policies, browser roles revoked):
--
--   devotionals          a church's own devotional: written in Solutionist
--                        (devotionals.py checks the seat), read by its members
--                        once published. Its days are one JSON array, so a
--                        devotional saves, exports and restores as one row.
--                        `audio` holds each day's Listen file, made once.
--   devotional_progress  a member's own day: done, the practices ticked, and
--                        their journal, which is private (no staff route
--                        reads it). Its devotional must be its church's.
--   member_plan_starts   the plans a member started on their own: a reading
--                        plan ("reading:gospels-30") or a devotional with no
--                        church start date ("devotional:<id>").
-- Idempotent.
begin;

create table if not exists public.devotionals(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  title text not null check (char_length(btrim(title)) between 1 and 120),
  kind text not null default '' check (char_length(kind) <= 60),
  author text not null default '' check (char_length(author) <= 120),
  about text not null default '' check (char_length(about) <= 6000),
  practices jsonb not null default '[]'::jsonb
    check (jsonb_typeof(practices) = 'array' and jsonb_array_length(practices) <= 8),
  days jsonb not null default '[]'::jsonb
    check (jsonb_typeof(days) = 'array' and jsonb_array_length(days) <= 90 and octet_length(days::text) <= 600000),
  day_count integer generated always as (jsonb_array_length(days)) stored,
  starts_on date,
  voice text not null default 'grace' check (voice in ('grace', 'elijah', 'jessica', 'reed')),
  audio jsonb not null default '{}'::jsonb check (jsonb_typeof(audio) = 'object'),
  status text not null default 'draft' check (status in ('draft', 'published')),
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  -- a published devotional has at least one day to read
  check (status = 'draft' or jsonb_array_length(days) >= 1),
  unique (id, business_id)
);

create index if not exists devotionals_by_church
  on public.devotionals (business_id, status, starts_on);

create table if not exists public.devotional_progress(
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  devotional_id uuid not null,
  day integer not null check (day between 1 and 90),
  done_at timestamptz,
  checks text[] not null default '{}' check (cardinality(checks) <= 8),
  journal text not null default '' check (char_length(journal) <= 4000),
  updated_at timestamptz not null default now(),
  primary key (business_id, contact_id, devotional_id, day),
  foreign key (devotional_id, business_id) references public.devotionals(id, business_id) on delete cascade
);

create index if not exists devotional_progress_by_devotional
  on public.devotional_progress (devotional_id);

create table if not exists public.member_plan_starts(
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  plan text not null check (plan ~ '^(reading:[a-z0-9-]{1,40}|devotional:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$'),
  started_on date not null,
  created_at timestamptz not null default now(),
  primary key (business_id, contact_id, plan)
);

alter table public.devotionals enable row level security;
alter table public.devotional_progress enable row level security;
alter table public.member_plan_starts enable row level security;
revoke all on public.devotionals, public.devotional_progress, public.member_plan_starts from anon, authenticated;
grant all on public.devotionals, public.devotional_progress, public.member_plan_starts to service_role;

commit;
