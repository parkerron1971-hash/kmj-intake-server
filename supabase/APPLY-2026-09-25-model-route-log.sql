-- APPLY-2026-09-25-model-route-log.sql
--
-- One row per streamed Chief request, written by route_ledger.finish()
-- (the two-track reply, chief_fast_track.py). What the routing thresholds
-- in model_router.py are tuned against, and where the first-token SLO is
-- measured: complexity score and how it was reached, the lane, the model
-- that answered, escalations and why, time to first token against its
-- budget, total time, and the request's cost across every model it used.
--
-- Server-owned rows: RLS on, NO policies, and no table grants for anon or
-- authenticated. The service role writes and the owner reads through
-- GET /platform/routing/stats. The code is fail-soft without this table:
-- the [route] log line carries every field.
--
-- Idempotent. Retention: prune rows older than 90 days when it matters
-- (one row per streamed turn).

create table if not exists public.model_route_log (
  id                 uuid primary key default gen_random_uuid(),
  created_at         timestamptz not null default now(),
  request_id         text,
  business_id        uuid,
  user_id            uuid,
  conversation_id    text,
  surface            text,
  lane               text not null,          -- fast | full | cache | off
  reason             text,
  complexity         real,
  confidence         real,
  kind               text,
  classifier         text,                   -- heuristic | haiku | haiku_failed
  classifier_ms      integer,
  signals            jsonb not null default '[]'::jsonb,
  opener_source      text,                   -- model | local | client | answer | cache | turn | none
  opener_cut         text,
  answer_model       text,
  models             jsonb not null default '{}'::jsonb,
  escalated          boolean not null default false,
  escalation_reason  text,
  cache_hit          boolean not null default false,
  cache_similarity   real,
  ttft_ms            integer,
  total_ms           integer,
  budget_ms          integer,
  slo_applies        boolean not null default true,
  slo_met            boolean,
  input_tokens       integer,
  output_tokens      integer,
  cache_read_tokens  integer,
  cache_write_tokens integer,
  cost_cents         numeric(12, 4),
  error              text
);

create index if not exists model_route_log_created_idx
  on public.model_route_log (created_at desc);
create index if not exists model_route_log_business_idx
  on public.model_route_log (business_id, created_at desc);

alter table public.model_route_log enable row level security;
revoke all on table public.model_route_log from anon, authenticated;

-- Verify:
--   select relrowsecurity from pg_class where relname = 'model_route_log';        -- true
--   select count(*) from pg_policies where tablename = 'model_route_log';         -- 0
--   select has_table_privilege('authenticated', 'public.model_route_log', 'select'); -- false
--
-- The number to beat (router on vs off — CHIEF_ROUTER=off keeps logging
-- with lane 'off' when ROUTER_LOG_WHEN_OFF is on):
--   select lane,
--          count(*) as turns,
--          percentile_cont(0.5)  within group (order by ttft_ms) as ttft_p50,
--          percentile_cont(0.95) within group (order by ttft_ms) as ttft_p95,
--          avg(cost_cents) as avg_cents
--     from public.model_route_log
--    where slo_applies and created_at > now() - interval '1 day'
--    group by lane;
