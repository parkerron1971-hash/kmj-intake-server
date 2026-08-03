-- APPLY-2026-08-03-auditor-links.sql
-- THE ACTION LEDGER — L3: read-only links for an outside reviewer.
--
-- A practice gets audited. The auditor is not a Solutionist customer and
-- never will be — so a portal behind our login is not a proof to them.
-- This is the credential the OWNER mints, hands over, and revokes when
-- the review is done.
--
-- Deliberately the mcp_tokens shape, not a new invention:
--   THE SIGNATURE PROVES AUTHENTICITY. THE TABLE PROVIDES REVOCATION.
-- A stateless HMAC link (store_files' download tokens) is wrong here —
-- an audit link MUST be revocable the moment a review ends, must expire
-- on its own if forgotten, and must be nameable, because a credential
-- you cannot identify is one you will never revoke.
--
-- Scope is narrower than mcp_tokens: one business, ledger read only,
-- optionally pinned to a date window so "the 2026 review" cannot wander
-- into unrelated years.

CREATE TABLE IF NOT EXISTS public.auditor_links (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id   uuid NOT NULL,
  -- The jti claim, so a presented link finds its row without a scan.
  jti           text NOT NULL UNIQUE,
  -- SHA-256 of the full token string. Never the token itself.
  token_hash    text NOT NULL,
  -- Who it was given to: "Baker & Co, 2026 review". The name is what
  -- makes revocation possible months later.
  label         text NOT NULL DEFAULT 'unnamed',
  scopes        text[] NOT NULL DEFAULT ARRAY['ledger:read'],
  -- Optional window the link may see. NULL = the whole ledger.
  window_start  timestamptz,
  window_end    timestamptz,
  created_by    text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz,
  revoked_at    timestamptz,
  last_used_at  timestamptz,
  use_count     integer NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_auditor_links_jti
  ON public.auditor_links (jti);
CREATE INDEX IF NOT EXISTS idx_auditor_links_biz
  ON public.auditor_links (business_id, created_at DESC);
-- The list the owner reads: what is live right now.
CREATE INDEX IF NOT EXISTS idx_auditor_links_live
  ON public.auditor_links (business_id) WHERE revoked_at IS NULL;

ALTER TABLE public.auditor_links ENABLE ROW LEVEL SECURITY;
-- No policies, by design. This table is backend-mediated only: the
-- absence of a policy is the denial. Practitioners read their links
-- through the owner-gated endpoint, never directly.
REVOKE ALL ON public.auditor_links FROM anon, authenticated;

COMMENT ON TABLE public.auditor_links IS
  'Read-only ledger links for outside reviewers. Signature proves '
  'authenticity; this table provides revocation, expiry and a name. '
  'Every use is itself written to audit_log — who looked, and when, is '
  'part of the record.';

-- Rollback:
--   DROP TABLE IF EXISTS public.auditor_links;
