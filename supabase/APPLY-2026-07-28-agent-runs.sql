-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-07-28 — agent_runs (the agent audit spine)
--
-- Build 2 of Stage 1. Every call that reaches the MCP surface writes a
-- row here. No silent calls.
--
-- GENERALIZED FROM restricted_module_access_log, not invented. That table
-- (Fork 37, the ministry Giving trail) already had the right shape for
-- "who touched what, when, and was it allowed" — business_id, actor
-- identity, an action verb, a jsonb detail bag, a timestamp, RLS on with
-- zero policies. This keeps that spine and changes only what an agent
-- call needs that a UI click does not:
--
--   surface      which door the call came through ('mcp' today; the
--                extension tiers and the agent runtime later). Present
--                from day one so the table does not need widening the
--                moment a second caller exists.
--   tool         the verb requested. Recorded even when refused — the
--                refusals are the interesting rows.
--   allowed      whether authorization passed. A refused call is not an
--                error row; it is the audit trail doing its job.
--   ok           whether execution then succeeded.
--   duration_ms  how long it took.
--   error        a SHORT reason, never an exception dump.
--   arg_keys     argument NAMES only. See the privacy note below.
--
-- ─── What must never be written here ─────────────────────────────────
-- ARGUMENT VALUES. An argument can carry a customer's name, an email, a
-- search phrase, a note body. An audit trail that records values becomes
-- a second copy of the data it audits, held for longer, under weaker
-- scrutiny, and outside every deletion path. `arg_keys` is text[] rather
-- than jsonb precisely so there is nowhere convenient to put a value.
--
-- Same for `error`: a reason, not a traceback. Exception text in this
-- system routinely carries table names, ids and query fragments.
--
-- ─── Access ──────────────────────────────────────────────────────────
-- RLS enabled, ZERO policies — service-role only, exactly like the table
-- it is modelled on. Mission Control reads it through the backend.
--
-- Additive + idempotent.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.agent_runs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id   uuid,                      -- null when refused BEFORE a
                                           -- business could be resolved
  surface       text NOT NULL DEFAULT 'mcp',
  tool          text NOT NULL,
  actor_user_id text,
  actor_email   text,
  allowed       boolean NOT NULL DEFAULT true,
  ok            boolean NOT NULL DEFAULT true,
  duration_ms   integer,
  error         text,
  arg_keys      text[] NOT NULL DEFAULT '{}',
  detail        jsonb  NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- "what did this business's agents do lately" — the Mission Control read.
CREATE INDEX IF NOT EXISTS idx_agent_runs_biz_time
  ON public.agent_runs (business_id, created_at DESC);
-- "what got refused" — the security read, and the one worth being fast.
CREATE INDEX IF NOT EXISTS idx_agent_runs_refused
  ON public.agent_runs (created_at DESC) WHERE allowed = false;
CREATE INDEX IF NOT EXISTS idx_agent_runs_surface_tool
  ON public.agent_runs (surface, tool, created_at DESC);

ALTER TABLE public.agent_runs ENABLE ROW LEVEL SECURITY;
-- No policies, deliberately. Reachable only through the service role,
-- which means only through backend code that has been reviewed.

-- AND revoke the table grant, which RLS does not do for you.
--
-- Supabase grants SELECT on public tables to anon/authenticated by
-- default. With RLS on and no policies those roles get zero rows, so the
-- data is safe TODAY — but only because no policy exists. Add one
-- permissive policy later, for any reason, and the standing grant turns
-- it into a public table in the same breath. RLS-with-no-policies is a
-- consequence of absence; a revoked grant is a decision.
--
-- restricted_module_access_log and restricted_module_entries both revoke.
-- Verified 2026-07-28: anon=False, authenticated=False on both. This
-- matches them.
REVOKE ALL ON public.agent_runs FROM anon, authenticated;

-- ─── Same gap, closed at the same time ───────────────────────────────
-- vertical_knowledge (Feed 2, shipped 2026-07-27) has the identical
-- defect: RLS on, zero policies, grants left in place. Found while
-- verifying this table, and not worth leaving open for a tidier PR
-- boundary — it is one line and the same reasoning.
REVOKE ALL ON public.vertical_knowledge FROM anon, authenticated;

COMMENT ON TABLE public.agent_runs IS
  'Every call reaching an agent-facing surface (MCP today). Argument NAMES only, never values — see APPLY-2026-07-28-agent-runs.sql.';

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.agent_runs;
