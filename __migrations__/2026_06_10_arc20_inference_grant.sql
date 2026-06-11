-- ═════════════════════════════════════════════════════════════════════
-- HOTFIX (Finding 2) — match_inference_cache EXECUTE for service_role
-- ═════════════════════════════════════════════════════════════════════
-- The inference-layer migration revoked EXECUTE from PUBLIC/anon/
-- authenticated but granted nothing back — revoking PUBLIC removes the
-- implicit default grant, and service_role is not the function owner,
-- so the backend's /rpc/match_inference_cache calls were permission-
-- denied. Effect: semantic (vector) cache matches never fired; only
-- exact-hash hits worked (the gate failed open, as designed).
--
-- Idempotent. Verify after applying:
--   SELECT proacl FROM pg_proc WHERE proname = 'match_inference_cache';
--   -- expect an entry like: service_role=X/postgres
-- ═════════════════════════════════════════════════════════════════════

GRANT EXECUTE ON FUNCTION public.match_inference_cache(uuid, text, vector, float, int)
  TO service_role;

-- (anon + authenticated stay revoked — clients never call this directly.)

-- ─── Rollback ────────────────────────────────────────────────────────
--   REVOKE EXECUTE ON FUNCTION public.match_inference_cache(uuid, text, vector, float, int)
--     FROM service_role;

SELECT 'inference grant applied' AS status;
