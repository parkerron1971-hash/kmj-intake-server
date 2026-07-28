-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-07-28 — mcp_tokens (scoped agent credentials)
--
-- Build 3 of Stage 1. Until now the MCP surface authenticated with the
-- owner's own Supabase JWT: correct for a single-tenant read-only
-- experiment, wrong the moment a credential needs to live in an external
-- client's config file. A JWT there cannot be scoped, cannot be named,
-- expires on its own schedule, and revoking it means changing the
-- password you log in with.
--
-- These tokens are the opposite of all four.
--
-- ─── The token is NOT stored here ────────────────────────────────────
-- Only its SHA-256 hash. The plaintext is shown once, at mint time, and
-- is then unrecoverable — which is why the UI copy says "copy it now".
-- A stolen database dump yields hashes, not working credentials.
--
-- This mirrors how the Tier-3 spec (docs/extensibility_and_autonomy.md
-- §1.2) describes API tokens: "revocable; hashed at rest".
--
-- ─── What the row is FOR ─────────────────────────────────────────────
-- The HMAC signature already proves the token is authentic and unexpired
-- without any database read. So this table exists for the one thing a
-- signature cannot do: REVOCATION. `revoked_at` is checked on every call,
-- which is what makes "revoke" mean "stops working now" rather than
-- "stops working when it expires".
--
-- `last_used_at` and `use_count` answer the question a security-minded
-- owner actually asks: is this thing still being used, and by how much?
-- An unused token is one you can revoke without thinking.
--
-- ─── Scopes ──────────────────────────────────────────────────────────
-- Stored as text[] and carried in the signed claims. Today the only
-- meaningful value is 'read'. It is a list from day one because the
-- alternative — a boolean — is the thing that always has to be migrated
-- later, and because a scope the server does not recognise must be
-- ignorable rather than fatal.
--
-- Additive + idempotent. Service-role only, grants revoked (RLS with no
-- policies is a consequence of absence; a revoked grant is a decision).
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.mcp_tokens (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id   uuid NOT NULL,
  -- The jti claim, so a presented token finds its row without a scan.
  jti           text NOT NULL UNIQUE,
  -- SHA-256 of the full token string. Never the token itself.
  token_hash    text NOT NULL,
  -- What the owner called it: "my laptop's Claude Desktop". A credential
  -- you cannot identify is one you will never revoke.
  label         text NOT NULL DEFAULT 'unnamed',
  scopes        text[] NOT NULL DEFAULT ARRAY['read'],
  created_by    text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz,
  revoked_at    timestamptz,
  last_used_at  timestamptz,
  use_count     integer NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_mcp_tokens_jti ON public.mcp_tokens (jti);
CREATE INDEX IF NOT EXISTS idx_mcp_tokens_biz
  ON public.mcp_tokens (business_id, created_at DESC);
-- The list the owner reads: what is live right now.
CREATE INDEX IF NOT EXISTS idx_mcp_tokens_live
  ON public.mcp_tokens (business_id) WHERE revoked_at IS NULL;

ALTER TABLE public.mcp_tokens ENABLE ROW LEVEL SECURITY;
-- No policies. Backend-mediated only.
REVOKE ALL ON public.mcp_tokens FROM anon, authenticated;

COMMENT ON TABLE public.mcp_tokens IS
  'Scoped credentials for the agent-facing MCP surface. Stores the SHA-256 hash, never the token. Exists for revocation and usage visibility — authenticity comes from the HMAC signature.';

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.mcp_tokens;
