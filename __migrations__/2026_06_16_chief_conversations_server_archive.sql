-- ═════════════════════════════════════════════════════════════════════
-- 2026_06_16_chief_conversations_server_archive.sql
-- STEP 1 (Chief memory build) — server-side archive spine.
-- ═════════════════════════════════════════════════════════════════════
-- Approach B: append-per-turn capture + atomic "one open row per business"
-- + race-safe lazy-close, so a session's history exists server-side the
-- instant a turn happens — independent of the client ever reopening. The
-- frontend archiver (ChiefOfStaff.tsx archiveToServer) is retired in the
-- SAME change so two writers can't race the open row.
--
-- Depends on (apply first): chief_conversations table (frontend supabase/),
--   is_business_owner / is_business_member (2026_06_10_hotfix_rls_recursion),
--   and Step 0 (2026_06_16_chief_conversations_rls.sql).
-- Apply via Supabase Studio. Idempotent.
-- ═════════════════════════════════════════════════════════════════════

-- ── Schema delta ────────────────────────────────────────────────────
-- An OPEN conversation = ended_at IS NULL. Drop the now() default so the
-- append RPC's explicit NULL means "open" (existing CLOSED rows keep their
-- ended_at untouched). updated_at = last-turn time → drives the 4h lazy-close.
ALTER TABLE public.chief_conversations ALTER COLUMN ended_at DROP DEFAULT;
ALTER TABLE public.chief_conversations
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- ── THE CONFLICT TARGET ─────────────────────────────────────────────
-- At most ONE open row per business. Partial unique index: closed rows
-- (ended_at NOT NULL) are unconstrained, so history accumulates while only
-- the live session is unique. This is what makes the append upsert atomic —
-- concurrent turns from one business serialize on this index.
CREATE UNIQUE INDEX IF NOT EXISTS chief_conversations_one_open_per_business
  ON public.chief_conversations (business_id)
  WHERE ended_at IS NULL;

-- ── Append-per-turn RPC (atomic upsert on the open-row key) ─────────
-- SECURITY DEFINER so it can resolve the partial-index conflict regardless of
-- RLS, but GUARDED on owner/member (auth.uid() under the caller's JWT) so a
-- user can only append to their OWN business's open conversation. Two
-- concurrent turns: the first INSERTs the open row, the rest take DO UPDATE
-- and append — the unique index guarantees there is never a second open row.
CREATE OR REPLACE FUNCTION public.chief_append_turn(
  p_business_id uuid,
  p_messages    jsonb           -- JSON array of {role, content} for THIS turn
) RETURNS uuid
LANGUAGE plpgsql STRICT SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_id uuid;
BEGIN
  IF NOT (public.is_business_owner(p_business_id)
          OR public.is_business_member(p_business_id)) THEN
    RAISE EXCEPTION 'not authorized for business %', p_business_id
      USING ERRCODE = '42501';
  END IF;

  INSERT INTO public.chief_conversations
      (business_id, messages, message_count, started_at, ended_at, updated_at)
  VALUES
      (p_business_id, p_messages, jsonb_array_length(p_messages), now(), NULL, now())
  ON CONFLICT (business_id) WHERE ended_at IS NULL
  DO UPDATE SET
      messages      = chief_conversations.messages || EXCLUDED.messages,
      message_count = chief_conversations.message_count + jsonb_array_length(EXCLUDED.messages),
      updated_at    = now()
  RETURNING id INTO v_id;

  RETURN v_id;
END $$;

REVOKE ALL ON FUNCTION public.chief_append_turn(uuid, jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.chief_append_turn(uuid, jsonb) TO authenticated;
GRANT EXECUTE ON FUNCTION public.chief_append_turn(uuid, jsonb) TO service_role;

-- ── Lazy-close claim (per-business, race-safe) ──────────────────────
-- Atomically CLAIMS a stale open row by setting ended_at, returning it so
-- EXACTLY ONE caller summarizes it. Returns no row if there's nothing stale
-- (already claimed, or still fresh). Used by the per-turn lazy-close (user
-- JWT → guarded) ahead of the append, so a >4h-idle session is closed and the
-- new turn starts a fresh open row.
CREATE OR REPLACE FUNCTION public.chief_claim_stale_conversation(
  p_business_id  uuid,
  p_idle_minutes int DEFAULT 240
) RETURNS TABLE (id uuid, messages jsonb)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF auth.uid() IS NOT NULL
     AND NOT (public.is_business_owner(p_business_id)
              OR public.is_business_member(p_business_id)) THEN
    RAISE EXCEPTION 'not authorized for business %', p_business_id
      USING ERRCODE = '42501';
  END IF;

  RETURN QUERY
  UPDATE public.chief_conversations c
     SET ended_at = now()
   WHERE c.business_id = p_business_id
     AND c.ended_at IS NULL
     AND c.updated_at < now() - make_interval(mins => p_idle_minutes)
  RETURNING c.id, c.messages;
END $$;

REVOKE ALL ON FUNCTION public.chief_claim_stale_conversation(uuid, int) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.chief_claim_stale_conversation(uuid, int) TO authenticated;
GRANT EXECUTE ON FUNCTION public.chief_claim_stale_conversation(uuid, int) TO service_role;

-- ── Hourly sweep claim (all businesses, service-role only) ──────────
-- Backstop for the never-reopen case: claims EVERY stale open row in one
-- atomic statement. service-role only (the sweep is a trusted server job);
-- the caller summarizes each returned row.
CREATE OR REPLACE FUNCTION public.chief_claim_all_stale(
  p_idle_minutes int DEFAULT 240
) RETURNS TABLE (id uuid, business_id uuid, messages jsonb)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  UPDATE public.chief_conversations c
     SET ended_at = now()
   WHERE c.ended_at IS NULL
     AND c.updated_at < now() - make_interval(mins => p_idle_minutes)
  RETURNING c.id, c.business_id, c.messages;
$$;

REVOKE ALL ON FUNCTION public.chief_claim_all_stale(int) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.chief_claim_all_stale(int) TO service_role;

-- ─── Verification (run AFTER applying) ───────────────────────────────
-- 1. One-open-row invariant holds (should never return >1 per business):
--      SELECT business_id, count(*) FROM chief_conversations
--      WHERE ended_at IS NULL GROUP BY business_id HAVING count(*) > 1;
-- 2. Append two turns for a test business via /rpc/chief_append_turn → one
--    open row, message_count grows, messages array concatenates.
-- 3. Set its updated_at back 5h, call chief_claim_stale_conversation →
--    returns the row once, ended_at set; a second call returns nothing.

SELECT 'chief_conversations server archive installed' AS status;
