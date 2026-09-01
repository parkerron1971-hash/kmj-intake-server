-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-08-31 — the two-sided doors
--
-- Two changes that are cheap now and unrecoverable later. Neither is
-- visible to a practitioner; both exist so the client-layer phases do
-- not have to undo them. See docs/plans/TWO_SIDED_CLIENT_LAYER_PLAN.md
-- §0.1 and §0.3.
--
-- ─── 1. audit_log gains a CLIENT actor ────────────────────────────
--
-- actor_type has allowed exactly four values since 2026-07-30:
-- user, chief, agent, system. The client layer introduces a fifth
-- party — the practitioner's client, acting on their own record inside
-- someone else's tenant — and there is no honest way to spell that in
-- the four we have.
--
-- The workaround that would otherwise happen is already in the file:
-- non-chat writers set actor_type='system' and carry their real
-- identity in actor_id ('scheduler', 'trust-track'). That is fine for a
-- sweep nobody will ever dispute. It is the wrong answer for a client,
-- because "who did this" would then be encoded by CONVENTION on the one
-- table in this system whose entire value proposition is that it does
-- not rely on convention.
--
-- And it cannot be deferred. audit_log is append-only for real —
-- BEFORE UPDATE/DELETE triggers raise, so even service_role cannot
-- rewrite a row. Rows written under the four-value constraint can never
-- be relabelled. A decision made after the first client action is a
-- decision made too late, permanently, for every row before it.
--
-- WHY 'client' AND NOT ALSO 'client_agent'. A client's AI agent acts
-- with exactly the client's authority; what differs is who typed. That
-- is authorship, not authority, and audit_log.ai_model already exists
-- to record which machine decided (APPLY-2026-08-10). Two actor types
-- would make every future question about client activity a two-value IN
-- list, forever, to record something a column already records.
--
-- ─── 2. business_customers gains a nullable platform identity ─────
--
-- One human who is a client of three practitioners is three unrelated
-- rows today: business_customers is ON DELETE CASCADE from one
-- business and uniquely keyed (business_id, lower(email)). There is no
-- cross-tenant key and deliberately so.
--
-- The client-identity phase needs one. This column costs nothing now —
-- nothing writes it, nothing reads it, no FK, no table behind it — and
-- cannot be added usefully later, because by then there will be client
-- rows across many tenants with no way to say two of them are the same
-- person.
--
-- WHAT THIS DELIBERATELY IS NOT: a cross-tenant email match. Nothing
-- here joins one practitioner's client list to another's. Populating
-- this column is a later, separate decision with a privacy posture
-- attached (plan §0.3, doors 4) — this migration only refuses to
-- foreclose it.
--
-- Safe to re-run.
-- ══════════════════════════════════════════════════════════════════

-- ─── 1. The client actor ──────────────────────────────────────────

alter table public.audit_log
  drop constraint if exists audit_log_actor_type_check;

alter table public.audit_log
  add constraint audit_log_actor_type_check
  check (actor_type in ('user', 'chief', 'agent', 'system', 'client'));

comment on column public.audit_log.actor_type is
  'Which PARTY acted: user (a seat on this business), chief, agent (an '
  'outside agent holding an mcp_tokens credential), system (scheduler, '
  'sweeps — real identity in actor_id), or client (the practitioner''s '
  'client acting on their own record). A client''s AI agent is also '
  '''client'' — it carries the client''s authority; ai_model records '
  'that a machine typed.';

-- ─── 2. The identity door ─────────────────────────────────────────

alter table public.business_customers
  add column if not exists platform_identity_id uuid;

comment on column public.business_customers.platform_identity_id is
  'Reserved for cross-tenant client identity. NULL for every row today '
  'and nothing reads it. When one person is a client of several '
  'practitioners, this is where "the same person" gets said. No FK yet '
  '— the identity table is a later phase, and a constraint pointing at '
  'nothing would have to be dropped to add it.';

-- Partial: every row is NULL today, so an unfiltered index would be
-- all dead weight and no lookups.
create index if not exists business_customers_platform_identity_idx
  on public.business_customers (platform_identity_id)
  where platform_identity_id is not null;

-- ─── Verification ─────────────────────────────────────────────────
--
-- The append-only guarantee is the whole point of audit_log. Replacing
-- a CHECK constraint must not have quietly loosened it.

do $$
declare
  n_trig int;
  n_vals int;
begin
  select count(*) into n_trig from pg_trigger t
    join pg_class c on c.oid = t.tgrelid
   where c.relname = 'audit_log' and not t.tgisinternal;
  raise notice 'audit_log non-internal triggers still present: %', n_trig;

  select count(*) into n_vals from pg_constraint
   where conname = 'audit_log_actor_type_check';
  raise notice 'actor_type check constraint present: % (expect 1)', n_vals;
end $$;
