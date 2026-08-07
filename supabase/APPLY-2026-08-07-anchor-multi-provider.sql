-- APPLY-2026-08-07-anchor-multi-provider.sql
-- THE ACTION LEDGER — Stage 5, anchoring to more than one network.
--
-- WHY TWO NETWORKS AND NOT ONE. The metric that matters for evidence is
-- not how often a provider breaks. It is how often we are left with
-- NOTHING. A gap is the failure you cannot recover from: you cannot
-- retroactively anchor last month at last month's timestamp. With one
-- provider, a month of silent breakage is a month with no proof. With
-- two independent providers, the same breakage still leaves the month
-- anchored by the other one.
--
-- The two also cover each other's specific objection. OpenTimestamps
-- involves no key of ours, so nobody can argue we wrote our own
-- attestation — but it spends hours merely `submitted` before Bitcoin
-- confirms it. Hedera is final in seconds — but it is written from our
-- own account, which is a line of attack OTS simply does not have.
--
-- This migration does two things, and deliberately keeps them apart.

-- ─── 1. A window may now be anchored once PER PROVIDER ───────────────
--
-- The old unique index was (business_id, first_sequence, last_sequence),
-- which encoded an assumption that is no longer true: that a window has
-- one anchor. Two providers anchoring the same window is not a duplicate
-- receipt — it is the entire point of running two. Re-running the job
-- must still be a no-op, so provider joins the key rather than replacing
-- the constraint.
--
-- Safe to re-run: dropping and recreating an index is DDL, so the
-- append-only row triggers on this table do not fire.

drop index if exists public.idx_ledger_anchors_window;
create unique index if not exists idx_ledger_anchors_window
  on public.ledger_anchors (business_id, provider, first_sequence, last_sequence);

comment on index public.idx_ledger_anchors_window is
  'One receipt per tenant per window PER PROVIDER. Two providers '
  'anchoring the same window is redundancy, not duplication; re-running '
  'the job for the same provider is still a no-op.';

-- ─── 2. Failures, recorded somewhere that is NOT the receipt table ───
--
-- THE RULE THIS PRESERVES. A row in ledger_anchors asserts that a proof
-- exists. That is why anchor_business() has always written nothing when
-- publishing failed — a receipt for an anchor that never published would
-- make the table lie in the one direction it must not. Adding a status
-- column to ledger_anchors would break exactly that guarantee, so
-- failures get their own table instead.
--
-- WHY THIS TABLE EXISTS AT ALL. Redundancy is worthless if nobody
-- notices a provider has gone quiet. Before this, a failed publish was a
-- log line on Railway — which means in practice it was invisible, and a
-- provider could stop working for a month without anyone knowing. This
-- table is what Mission Control reads to answer "is anchoring actually
-- working, on both networks?"
--
-- NOT APPEND-ONLY, ON PURPOSE. ledger_anchors is append-only because it
-- is evidence. This is diagnostics: operational telemetry about our own
-- infrastructure, containing no claim anyone relies on. Locking it would
-- buy nothing and would make it impossible to prune a table whose whole
-- job is to accumulate noise during an outage.

create table if not exists public.ledger_anchor_failures (
  id             uuid primary key default gen_random_uuid(),
  -- No FK, matching ledger_anchors: a failure record must survive an
  -- erased tenant, or erasing a business would also erase the evidence
  -- that its anchoring was broken at the time.
  business_id    uuid not null,
  provider       text not null,
  -- The root we were TRYING to publish, and the window it covered.
  -- Nullable because a provider can fail before a root is computed
  -- (missing credentials, package not installed), and recording that
  -- honestly is better than inventing a root to satisfy a constraint.
  merkle_root    text,
  first_sequence bigint,
  last_sequence  bigint,
  row_count      integer,
  -- The provider's own words. Truncated by the caller, never parsed:
  -- this is read by a human deciding whether to go fix something.
  error          text not null,
  failed_at      timestamptz not null default now()
);

create index if not exists idx_anchor_failures_recent
  on public.ledger_anchor_failures (failed_at desc);
create index if not exists idx_anchor_failures_provider
  on public.ledger_anchor_failures (provider, failed_at desc);
create index if not exists idx_anchor_failures_biz
  on public.ledger_anchor_failures (business_id, failed_at desc);

alter table public.ledger_anchor_failures enable row level security;
revoke all on public.ledger_anchor_failures from anon, authenticated;

comment on table public.ledger_anchor_failures is
  'Diagnostics, NOT evidence. Why an anchor did not publish, per '
  'provider. Deliberately separate from ledger_anchors: a row there '
  'asserts a proof exists, so a failed publish must never appear in it. '
  'Service-role only; read by Mission Control.';

-- VERIFY:
--   -- the widened key admits two providers for one window:
--   select indexdef from pg_indexes where indexname = 'idx_ledger_anchors_window';
--     -> must contain: (business_id, provider, first_sequence, last_sequence)
--
--   -- failures are reachable only as the service role:
--   select relrowsecurity from pg_class where relname = 'ledger_anchor_failures';
--     -> t
