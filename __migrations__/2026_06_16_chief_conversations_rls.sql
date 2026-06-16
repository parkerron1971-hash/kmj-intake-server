-- ═════════════════════════════════════════════════════════════════════
-- 2026_06_16_chief_conversations_rls.sql
-- STEP 0 (Chief memory build) — close the chief_conversations RLS hole.
-- ═════════════════════════════════════════════════════════════════════
-- chief_conversations holds the FULL Chief chat transcript per business
-- (messages JSONB + summary + key_topics + actions_taken). Its only policy
-- today is the wide-open `chief_convos_all` USING(true) (from the frontend
-- repo's supabase/schema-audit-fix.sql) — i.e. any authenticated caller can
-- read EVERY tenant's chat history. This scopes access to the owning
-- business. (Table is defined in the frontend supabase/ folder; this RLS fix
-- lives with the SECURITY DEFINER helper-based policies in the backend
-- __migrations__/, because it depends on those helpers.)
--
-- WHO TOUCHES THIS TABLE UNDER RLS (verified, 2026-06-16):
--   • Reader — chief_of_staff.handle_recall_conversation, dispatched inside
--     the /agents/chief/chat endpoint, which binds the practitioner's JWT
--     (sb_clients.set_user_jwt / _sb → sb_as_current_context). So reads run
--     as role `authenticated` and ARE governed by this policy. This policy is
--     therefore LOAD-BEARING for the existing reader, not merely
--     defense-in-depth: it must permit owner/member or recall_conversation
--     returns zero rows.
--   • Writer — the frontend archiver (ChiefOfStaff.tsx archiveToServer) POSTs
--     through the logged-in user's Supabase JWT → INSERT as `authenticated`
--     → governed by WITH CHECK below.
--   • Service-role (RLS-BYPASSING) applies only on server-initiated paths
--     with no JWT in context. None currently read/write this table; the
--     Step 1 server-side archiver may use service-role and will bypass RLS
--     by design (server is the trusted intermediary).
--
-- RECURSION-SAFE (R2 / 42P17 architecture lock): the cross-table check goes
-- through the SECURITY DEFINER STABLE helpers from
-- 2026_06_10_hotfix_rls_recursion.sql (public.is_business_owner /
-- is_business_member), which run as the function owner and bypass RLS during
-- evaluation, so no policy cycle can form. NEVER inline an EXISTS / IN
-- subquery against businesses here. The helpers read businesses +
-- business_users; neither references chief_conversations back, so there is
-- no A↔B cycle.
--
-- Scope = owner OR active team member. is_business_owner covers the owner
-- even if they have no business_users row; is_business_member covers active
-- multiseat teammates. Accountant collaborators are intentionally NOT granted
-- — Chief chat is the operator surface, not the books. Revisit if that
-- changes (would add: OR public.is_business_collaborator(...)).
--
-- Apply via Supabase Studio. Idempotent (safe to re-run).
-- ═════════════════════════════════════════════════════════════════════

ALTER TABLE public.chief_conversations ENABLE ROW LEVEL SECURITY;

-- Drop every prior policy that may exist on this table across installs, so
-- this migration converges to one policy regardless of the live starting
-- state (wide-open, phase-3 inline, or legacy):
DROP POLICY IF EXISTS "chief_convos_all"               ON public.chief_conversations; -- schema-audit-fix.sql (USING true)
DROP POLICY IF EXISTS "business_member_access"         ON public.chief_conversations; -- rls-hardening-phase-3 (inline subquery)
DROP POLICY IF EXISTS "Allow all for anon"             ON public.chief_conversations; -- legacy permissive
DROP POLICY IF EXISTS chief_conversations_owner_member ON public.chief_conversations; -- this migration (re-run safe)

CREATE POLICY chief_conversations_owner_member ON public.chief_conversations
  FOR ALL
  TO authenticated
  USING (
    public.is_business_owner(chief_conversations.business_id)
    OR public.is_business_member(chief_conversations.business_id)
  )
  WITH CHECK (
    public.is_business_owner(chief_conversations.business_id)
    OR public.is_business_member(chief_conversations.business_id)
  );

-- ─── Verification (run AFTER applying) ───────────────────────────────
-- 1. Exactly one policy, helper-based (no inline cross-table refs in qual):
--      SELECT policyname, cmd, qual, with_check FROM pg_policies
--      WHERE schemaname='public' AND tablename='chief_conversations';
-- 2. As the OWNER (real browser session): recall_conversation in Chief still
--    surfaces past chats, the frontend archiver still writes, and NO other
--    business's rows are visible.
-- 3. As anon (no JWT): SELECT on chief_conversations returns zero rows
--    (there is no policy granting anon).

SELECT 'chief_conversations RLS scoped to owner/member' AS status;
