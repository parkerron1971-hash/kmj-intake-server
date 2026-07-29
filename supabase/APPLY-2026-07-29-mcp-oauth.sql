-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-07-29 — OAuth 2.1 in front of the MCP surface
--
-- WHY THIS EXISTS
-- Stage 1 authenticates with a hand-minted bearer token pasted into a
-- local config file. That works for Claude Code on a laptop and cannot
-- work anywhere else: claude.ai's custom-connector dialog speaks OAuth,
-- and remote MCP is the ONLY kind the iOS/Android app can use (a phone
-- cannot run a local server). No OAuth, no phone.
--
-- ─── What is NOT changing ────────────────────────────────────────────
-- The access token issued by /oauth/token IS an ordinary mcp_tokens
-- credential — same HMAC format, same table, same revocation, same row
-- in Mission Control → Agent Access. The OAuth layer is a way to OBTAIN
-- one, not a second credential system. `_caller_from_token` in
-- mcp_server.py needed no change at all, which is the strongest evidence
-- the seam is in the right place.
--
-- ─── Why three tables ────────────────────────────────────────────────
-- clients   RFC 7591 dynamic registration. Claude.ai registers itself
--           rather than the owner hand-managing a client secret in a
--           settings dialog. Open registration is per spec and safe HERE
--           because registering grants nothing: every code still requires
--           the owner to paste a live Agent Access key at /authorize.
--
-- codes     Authorization codes are single-use and live ~60 seconds. They
--           are in a table rather than in memory because Railway restarts
--           whenever it likes, and a restart mid-flow would otherwise
--           strand the owner on an error page with no idea why.
--
-- refresh   Without these the connector dies every 90 days — in practice,
--           mid-question, on a phone, with no explanation. Rotation on
--           every use means a stolen refresh token is detectable: the
--           legitimate client's next refresh fails because the row was
--           already consumed.
--
-- ─── Secrets are hashed, exactly as in mcp_tokens ────────────────────
-- Codes, refresh tokens and client secrets are stored as SHA-256. A dump
-- of these tables yields nothing usable. The pattern is deliberate: the
-- 2026-07-28 migration made the same choice for the same reason.
--
-- ─── Revoking the key kills the phone ────────────────────────────────
-- Each refresh row remembers the jti of the access token it last issued.
-- Refreshing re-checks that jti against mcp_tokens.revoked_at, so killing
-- a credential in Agent Access severs the phone at its next refresh
-- rather than leaving a connection alive against a credential the owner
-- believes they switched off.
--
-- Additive + idempotent. Service-role only, grants revoked (RLS with no
-- policies is a consequence of absence; a revoked grant is a decision).
-- ══════════════════════════════════════════════════════════════════

-- ─── Registered clients (RFC 7591) ───────────────────────────────────

CREATE TABLE IF NOT EXISTS public.mcp_oauth_clients (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id           text NOT NULL UNIQUE,
  -- NULL for public clients (PKCE-only). Never the secret itself.
  client_secret_hash  text,
  client_name         text NOT NULL DEFAULT 'unnamed',
  -- Exact-match allowlist. An open redirect here would let any site
  -- collect authorization codes meant for this server.
  redirect_uris       text[] NOT NULL DEFAULT ARRAY[]::text[],
  created_at          timestamptz NOT NULL DEFAULT now(),
  last_used_at        timestamptz
);

CREATE INDEX IF NOT EXISTS idx_mcp_oauth_clients_cid
  ON public.mcp_oauth_clients (client_id);

ALTER TABLE public.mcp_oauth_clients ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.mcp_oauth_clients FROM anon, authenticated;

COMMENT ON TABLE public.mcp_oauth_clients IS
  'OAuth clients registered via RFC 7591 dynamic registration. Registration alone grants nothing — an authorization code still requires the owner to present a live Agent Access key.';


-- ─── Authorization codes ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.mcp_oauth_codes (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  -- SHA-256 of the code. Never the code.
  code_hash             text NOT NULL UNIQUE,
  client_id             text NOT NULL,
  redirect_uri          text NOT NULL,
  -- PKCE. S256 only — 'plain' is not accepted by the token endpoint.
  code_challenge        text NOT NULL,
  code_challenge_method text NOT NULL DEFAULT 'S256',
  business_id           uuid NOT NULL,
  scope                 text NOT NULL DEFAULT 'read',
  created_at            timestamptz NOT NULL DEFAULT now(),
  expires_at            timestamptz NOT NULL,
  -- Set on first exchange. A second attempt with the same code fails,
  -- which is what makes "single use" true rather than merely intended.
  consumed_at           timestamptz
);

CREATE INDEX IF NOT EXISTS idx_mcp_oauth_codes_hash
  ON public.mcp_oauth_codes (code_hash);
CREATE INDEX IF NOT EXISTS idx_mcp_oauth_codes_expiry
  ON public.mcp_oauth_codes (expires_at) WHERE consumed_at IS NULL;

ALTER TABLE public.mcp_oauth_codes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.mcp_oauth_codes FROM anon, authenticated;

COMMENT ON TABLE public.mcp_oauth_codes IS
  'Single-use OAuth authorization codes, ~60s TTL, stored as SHA-256. In a table rather than memory so a Railway restart mid-flow does not strand the owner.';


-- ─── Refresh tokens ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.mcp_oauth_refresh (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  -- SHA-256 of the refresh token. Never the token.
  token_hash      text NOT NULL UNIQUE,
  client_id       text NOT NULL,
  business_id     uuid NOT NULL,
  scope           text NOT NULL DEFAULT 'read',
  -- The access token this row last issued. Checked against
  -- mcp_tokens.revoked_at on every refresh, so revoking the credential in
  -- Agent Access severs the connection instead of leaving it alive.
  access_jti      text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  expires_at      timestamptz NOT NULL,
  -- Rotation: consuming a refresh token issues a new one and stamps the
  -- old. A replayed token is therefore visible, not merely useless.
  consumed_at     timestamptz,
  revoked_at      timestamptz
);

CREATE INDEX IF NOT EXISTS idx_mcp_oauth_refresh_hash
  ON public.mcp_oauth_refresh (token_hash);
CREATE INDEX IF NOT EXISTS idx_mcp_oauth_refresh_live
  ON public.mcp_oauth_refresh (business_id)
  WHERE consumed_at IS NULL AND revoked_at IS NULL;

ALTER TABLE public.mcp_oauth_refresh ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.mcp_oauth_refresh FROM anon, authenticated;

COMMENT ON TABLE public.mcp_oauth_refresh IS
  'Rotating OAuth refresh tokens, stored as SHA-256. Rotation makes replay detectable; access_jti ties the chain to a revocable mcp_tokens row.';


-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.mcp_oauth_refresh;
--   DROP TABLE IF EXISTS public.mcp_oauth_codes;
--   DROP TABLE IF EXISTS public.mcp_oauth_clients;
