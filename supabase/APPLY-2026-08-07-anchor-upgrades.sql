-- APPLY-2026-08-07-anchor-upgrades.sql
-- THE ACTION LEDGER — Stage 5, seeing the Bitcoin confirmation.
--
-- THE BUG THIS CLOSES. An OpenTimestamps receipt is written at
-- SUBMISSION time, when its only attestation is "pending at a calendar
-- server". Hours later the calendars aggregate it into a Bitcoin block
-- and the proof becomes complete — but that upgrade lives at the
-- calendar, not in the bytes we stored. proof_status() only ever
-- re-parsed the stored bytes, so an anchor could be Bitcoin-confirmed
-- for years and every surface would keep reporting `submitted`.
--
-- Verified concretely: the 2026-08-04 anchor was confirmed in Bitcoin
-- block 961016, while the app reported it as merely submitted.
--
-- That mattered because `submitted` vs `confirmed` is the whole reason
-- there are two states. Submitted means independent calendars have
-- committed to including it. Confirmed means no party, us included, can
-- backdate it. Reporting the weaker one forever wastes the stronger.
--
-- WHY A SEPARATE TABLE, AND WHY THIS ONE IS MUTABLE.
--
-- ledger_anchors is append-only because it is EVIDENCE — a row there
-- asserts a proof exists, and a receipt that can be edited is not a
-- commitment. So the upgraded proof cannot be written back over the
-- original, and this cache sits beside it instead.
--
-- This table IS updatable, deliberately, and that is safe because
-- nothing here is a claim: every row is DERIVED data, refetchable from
-- the public calendars by anyone, at any time. Deleting the whole table
-- would cost nothing but a re-fetch. It is a cache in front of a public
-- network, not a record of anything.

create table if not exists public.ledger_anchor_upgrades (
  -- One row per receipt. No FK, matching ledger_anchors: the receipt
  -- must outlive an erased tenant, and so may its cached upgrade.
  anchor_id      uuid primary key,
  business_id    uuid not null,
  provider       text not null,
  -- The .ots WITH the Bitcoin attestation merged in. Strictly a
  -- superset of the stored receipt, so any reader can use it in place
  -- of the original with no special handling.
  upgraded_ref   text,
  bitcoin_block  bigint,
  confirmed      boolean not null default false,
  -- Bookkeeping, so a proof that never confirms is visible as such
  -- rather than being retried silently forever.
  attempts       integer not null default 0,
  last_error     text,
  checked_at     timestamptz not null default now(),
  upgraded_at    timestamptz
);

-- The upgrade job's driving query: unconfirmed first, least recently
-- checked first, so a backlog drains evenly instead of one row being
-- retried while another is never looked at.
create index if not exists idx_anchor_upgrades_todo
  on public.ledger_anchor_upgrades (confirmed, checked_at);
create index if not exists idx_anchor_upgrades_biz
  on public.ledger_anchor_upgrades (business_id);

alter table public.ledger_anchor_upgrades enable row level security;
revoke all on public.ledger_anchor_upgrades from anon, authenticated;

comment on table public.ledger_anchor_upgrades is
  'Cache of OpenTimestamps proofs upgraded with their Bitcoin '
  'attestation. DERIVED and refetchable from the public calendars - '
  'mutable on purpose, unlike ledger_anchors, because nothing here is '
  'a claim. Exists because a stored .ots is written at submission time '
  'and never learns about its own Bitcoin confirmation.';

-- VERIFY:
--   select confirmed, count(*) from public.ledger_anchor_upgrades group by 1;
--   select relrowsecurity from pg_class where relname='ledger_anchor_upgrades';
--     -> t
