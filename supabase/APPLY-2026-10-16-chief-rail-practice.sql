-- APPLY-2026-10-16-chief-rail-practice.sql
--
-- The rail's practice record (chief_rail.py, docs/CHIEF_RAIL.md). One row
-- per Chief records question after the reply went out: which shelf would
-- have taken it (money or schedule) or why none did, the answer the rail
-- would have given from a fresh read, how that answer was proved, and
-- whether Chief's own reply said the same. What Chief's turn cost and how
-- long it took ride along, so a shelf's case for live use is in one place.
--
-- Nothing reads this table to answer anyone. The rail is practice only.
--
-- Server-owned rows: RLS on, NO policies, and no table grants for anon or
-- authenticated. The service role writes; the owner reads counts through
-- GET /platform/rail/stats and scripts/rail_practice_report.py. The code is
-- fail-soft without this table: it prints one [rail] line per question.
--
-- rail_answer holds the rail's own sentence (a client's name and an
-- amount, the same facts chief_conversations already keeps). Retention:
-- prune rows older than 90 days when it matters.
--
-- Idempotent.

create table if not exists public.chief_rail_practice (
  id                uuid primary key default gen_random_uuid(),
  created_at        timestamptz not null default now(),
  request_id        text,
  business_id       uuid,
  surface           text,
  kind              text,                    -- model_router's label for the question
  shelf             text,                    -- money | schedule | null (no shelf)
  form              text,                    -- who_owes | owed_total | overdue | did_pay | client_balance | day | next | client_next
  took              boolean not null default false,
  decline_reason    text,                    -- phrasing | no_shelf | not_a_name | name_not_found | name_ambiguous | too_long | too_many_rows | ...
  proof             text,                    -- prover | empty_read | failed
  proof_sources     jsonb not null default '[]'::jsonb,
  rail_answer       text,
  rail_facts        jsonb not null default '{}'::jsonb,
  outcome           text,                    -- agrees | partial | differs | withheld | silent
  outcome_detail    jsonb not null default '{}'::jsonb,
  chief_grounding   text,                    -- the answer check's status on Chief's reply
  chief_wrote       boolean not null default false,
  chief_verbs       jsonb not null default '[]'::jsonb,
  chief_cost_cents  numeric(12, 4),
  chief_ms          integer,
  rail_ms           integer
);

create index if not exists chief_rail_practice_created_idx
  on public.chief_rail_practice (created_at desc);
create index if not exists chief_rail_practice_shelf_idx
  on public.chief_rail_practice (shelf, created_at desc);

alter table public.chief_rail_practice enable row level security;
revoke all on table public.chief_rail_practice from anon, authenticated;

-- Verify:
--   select relrowsecurity from pg_class where relname = 'chief_rail_practice';              -- true
--   select count(*) from pg_policies where tablename = 'chief_rail_practice';               -- 0
--   select has_table_privilege('authenticated', 'public.chief_rail_practice', 'select');    -- false
--   select has_table_privilege('anon', 'public.chief_rail_practice', 'select');             -- false
--
-- A week in (what graduation reads):
--   select shelf, form, outcome, proof, count(*), round(avg(chief_cost_cents), 2) as chief_cents
--   from public.chief_rail_practice
--   where took and created_at > now() - interval '7 days'
--   group by 1, 2, 3, 4 order by 1, 2, 5 desc;
