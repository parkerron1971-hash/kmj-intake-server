-- Owner-configured external bots and their work inbox. Apply before deployment.
BEGIN;
CREATE TABLE IF NOT EXISTS public.connected_agents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  token_jti text NOT NULL UNIQUE,
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
  capabilities text NOT NULL CHECK (length(capabilities) BETWEEN 1 AND 4000),
  use_when text NOT NULL DEFAULT '',
  boundaries text NOT NULL DEFAULT '',
  enabled boolean NOT NULL DEFAULT false,
  approval_mode text NOT NULL DEFAULT 'ask' CHECK (approval_mode IN ('ask','automatic')),
  allowed_tools jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(allowed_tools) = 'array'),
  revision integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS connected_agents_business ON public.connected_agents(business_id);
CREATE TABLE IF NOT EXISTS public.agent_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  agent_id uuid NOT NULL REFERENCES public.connected_agents(id) ON DELETE CASCADE,
  request_id uuid NOT NULL,
  title text NOT NULL CHECK (length(title) BETWEEN 1 AND 160),
  objective text NOT NULL CHECK (length(objective) BETWEEN 1 AND 8000),
  context text NOT NULL DEFAULT '',
  expected_output text NOT NULL CHECK (length(expected_output) BETWEEN 1 AND 4000),
  deadline timestamptz NOT NULL,
  status text NOT NULL CHECK (status IN ('awaiting_approval','queued','running','submitted','accepted','cancelled','failed')),
  profile_revision integer NOT NULL,
  capability_snapshot jsonb NOT NULL,
  progress text NOT NULL DEFAULT '',
  result text NOT NULL DEFAULT '',
  review_note text NOT NULL DEFAULT '',
  claim_id uuid,
  claimed_at timestamptz,
  submitted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (business_id, request_id)
);
CREATE INDEX IF NOT EXISTS agent_assignments_inbox ON public.agent_assignments(business_id,agent_id,status,created_at);
-- Serialize claim/release against a profile edit, so a concurrent worker cannot
-- release work under a stale revision. The backend still enforces caller identity.
CREATE OR REPLACE FUNCTION public.guard_agent_assignment() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
DECLARE p public.connected_agents%ROWTYPE;
BEGIN
  SELECT * INTO p FROM public.connected_agents WHERE id = NEW.agent_id FOR UPDATE;
  IF NOT FOUND OR p.business_id <> NEW.business_id THEN
    RAISE EXCEPTION 'agent does not belong to assignment business';
  END IF;
  IF NEW.status IN ('awaiting_approval','queued','running','submitted') THEN
    IF NOT p.enabled OR p.revision <> NEW.profile_revision THEN
      RAISE EXCEPTION 'agent profile paused or changed';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.mcp_tokens WHERE jti = p.token_jti
       AND business_id = NEW.business_id AND revoked_at IS NULL
       AND (expires_at IS NULL OR expires_at > now())) THEN
      RAISE EXCEPTION 'agent key expired or revoked';
    END IF;
    IF NEW.deadline <= now() THEN RAISE EXCEPTION 'assignment expired'; END IF;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS guard_agent_assignment ON public.agent_assignments;
CREATE TRIGGER guard_agent_assignment BEFORE INSERT OR UPDATE ON public.agent_assignments
FOR EACH ROW EXECUTE FUNCTION public.guard_agent_assignment();
ALTER TABLE public.connected_agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_assignments ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.connected_agents, public.agent_assignments FROM anon, authenticated;
GRANT ALL ON public.connected_agents, public.agent_assignments TO service_role;
-- No client policies. Backend checks owner or the signed business + bot credential.
COMMIT;
