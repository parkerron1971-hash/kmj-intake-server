-- The weekly database health check (db_health.py; Mission Control → Systems
-- → Database, owner-only). Kevin, 2026-11-18, after moving production from
-- Nano to Small on a "Disk IO Budget" warning: a check every week that says
-- when to move the database up a size.
--
-- Two server-only tables (RLS on, no policies, the browser's roles revoked,
-- like the other platform tables) and one function the server calls:
--
--   db_health_samples  one row a reading: every 15 minutes on Sunday from
--                      7:45 AM to 1 PM Eastern, Wednesday 10:45 and 11 AM,
--                      and "Check now" from the card. `slot` is unique: the
--                      row is inserted first to claim the slot, so a reading
--                      is taken once whatever the number of server copies.
--                      Kept 8 weeks (the Monday report removes older rows).
--   db_health_weeks    one row a Sunday: the week's verdict, its peaks, the
--                      top writers, and told_at (the owner alert's once-claim).
--   db_health_pg(p_top) SECURITY DEFINER, service role only: connections
--                      against max_connections, the database's size, and the
--                      p_top (0-10) statements that wrote the most WAL and the
--                      most temp files, from pg_stat_statements. Query text
--                      is pg_stat_statements' normalized text (constants are
--                      $1, $2 ...), only SELECT/INSERT/UPDATE/DELETE/MERGE/WITH
--                      statements (utility statements aren't normalized), with
--                      any quoted literal left masked as '…', cut to 160
--                      characters. Never a parameter.
--
-- Until this is applied the card says the check isn't set up and the job
-- reads nothing; nothing 500s.
--
-- Safe twice: create if not exists, create or replace, grants re-run.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.db_health_samples (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slot timestamptz NOT NULL UNIQUE,
  kind text NOT NULL CHECK (kind IN ('sunday', 'weekday', 'manual')),
  taken_at timestamptz,
  metrics jsonb CHECK (metrics IS NULL OR jsonb_typeof(metrics) = 'object'),
  pg jsonb CHECK (pg IS NULL OR jsonb_typeof(pg) = 'object'),
  problem text CHECK (problem IS NULL OR char_length(problem) <= 300),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS db_health_samples_taken_at ON public.db_health_samples (taken_at);
CREATE INDEX IF NOT EXISTS db_health_samples_created_at ON public.db_health_samples (created_at);

CREATE TABLE IF NOT EXISTS public.db_health_weeks (
  week date PRIMARY KEY,                       -- the Sunday (US Eastern) it reports on
  size text NOT NULL CHECK (size IN ('nano', 'micro', 'small', 'medium', 'large', 'xl', '2xl', '4xl')),
  churches integer CHECK (churches IS NULL OR churches >= 0),
  level text NOT NULL CHECK (level IN ('fine', 'watch', 'move')),
  headline text NOT NULL CHECK (char_length(headline) BETWEEN 1 AND 200),
  reasons jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(reasons) = 'array'),
  peak jsonb,
  tops jsonb,
  told_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.db_health_samples ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.db_health_weeks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.db_health_samples, public.db_health_weeks FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.db_health_samples, public.db_health_weeks TO service_role;

CREATE OR REPLACE FUNCTION public.db_health_pg(p_top integer DEFAULT 0)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  n integer := least(greatest(coalesce(p_top, 0), 0), 10);
  result jsonb;
BEGIN
  SELECT jsonb_build_object(
    'connections', (SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE backend_type = 'client backend'),
    'active', (SELECT count(*) FROM pg_catalog.pg_stat_activity
                WHERE backend_type = 'client backend' AND state = 'active'),
    'max_connections', pg_catalog.current_setting('max_connections')::integer,
    'db_bytes', pg_catalog.pg_database_size(pg_catalog.current_database())
  ) INTO result;

  IF n > 0 THEN
    BEGIN
      result := result || jsonb_build_object(
        'top_wal', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
            SELECT left(btrim(regexp_replace(regexp_replace(s.query, '''[^'']*''', '''…''', 'g'), '\s+', ' ', 'g')), 160) AS query,
                   s.calls, s.wal_bytes::bigint AS wal_bytes
              FROM extensions.pg_stat_statements s
             WHERE s.dbid = (SELECT d.oid FROM pg_catalog.pg_database d WHERE d.datname = pg_catalog.current_database())
               AND s.query ~* '^\s*(select|insert|update|delete|merge|with)\M'
               AND s.wal_bytes > 0
             ORDER BY s.wal_bytes DESC
             LIMIT n) t),
        'top_temp', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
            SELECT left(btrim(regexp_replace(regexp_replace(s.query, '''[^'']*''', '''…''', 'g'), '\s+', ' ', 'g')), 160) AS query,
                   s.calls, (s.temp_blks_written * pg_catalog.current_setting('block_size')::bigint) AS temp_bytes
              FROM extensions.pg_stat_statements s
             WHERE s.dbid = (SELECT d.oid FROM pg_catalog.pg_database d WHERE d.datname = pg_catalog.current_database())
               AND s.query ~* '^\s*(select|insert|update|delete|merge|with)\M'
               AND s.temp_blks_written > 0
             ORDER BY s.temp_blks_written DESC
             LIMIT n) t));
    EXCEPTION WHEN undefined_table OR undefined_column OR invalid_schema_name OR insufficient_privilege THEN
      result := result || jsonb_build_object('top_problem', 'The statement counts (pg_stat_statements) aren''t readable here.');
    END;
    BEGIN
      result := result || jsonb_build_object('since', (SELECT i.stats_reset FROM extensions.pg_stat_statements_info i));
    EXCEPTION WHEN OTHERS THEN
      NULL;
    END;
  END IF;
  RETURN result;
END;
$$;

REVOKE ALL ON FUNCTION public.db_health_pg(integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.db_health_pg(integer) TO service_role;

-- PostgREST picks up the new tables and the function now, not on its next restart.
NOTIFY pgrst, 'reload schema';

COMMIT;

-- Verify (each line on its own):
--   select relname, relrowsecurity from pg_class
--    where oid in ('public.db_health_samples'::regclass, 'public.db_health_weeks'::regclass);   -- both true
--   select count(*) from pg_policies where tablename in ('db_health_samples', 'db_health_weeks');  -- 0
--   select has_table_privilege('anon', 'public.db_health_samples', 'select'),
--          has_table_privilege('authenticated', 'public.db_health_weeks', 'select'),
--          has_function_privilege('anon', 'public.db_health_pg(integer)', 'execute'),
--          has_function_privilege('authenticated', 'public.db_health_pg(integer)', 'execute'),
--          has_function_privilege('service_role', 'public.db_health_pg(integer)', 'execute');  -- f, f, f, f, t
--   select public.db_health_pg(5);  -- connections, max_connections, db_bytes, top_wal, top_temp, since
--
-- Rollback (the card goes back to "not set up"; the job reads nothing):
--   drop function if exists public.db_health_pg(integer);
--   drop table if exists public.db_health_weeks;
--   drop table if exists public.db_health_samples;
