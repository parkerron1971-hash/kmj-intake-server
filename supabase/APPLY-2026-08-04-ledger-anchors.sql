-- APPLY-2026-08-04-ledger-anchors.sql
-- THE ACTION LEDGER — Stage 5, the receipt table.
--
-- THE GAP THIS CLOSES. A private hash chain has one honest weakness: we
-- control the whole database, so a determined skeptic can argue we
-- rebuilt the chain wholesale. Irrelevant for a salon. Material when
-- the ledger is offered as legal evidence.
--
-- The fix is publishing a single fingerprint — a Merkle root over a
-- window of rows — somewhere neither we nor the practitioner controls.
-- After that, everything in the window is frozen: altering any row
-- changes the root, and the old root is already public.
--
-- NEVER BUSINESS DATA. The root is a hash of hashes. It reveals no
-- verb, no client, no amount, and nothing can be reversed out of it.
-- What goes public is proof of non-alteration and nothing else.
--
-- WHY THE PROOF PATH IS NOT STORED. Rows are immutable and totally
-- ordered per tenant, and ledger_canonical_v1 froze the leaf bytes in
-- Stage 2. So the tree is RECOMPUTABLE from stored rows at any time —
-- the spec called the proof path the one thing painful to retrofit, and
-- freezing the canonical form is what closed it. This table therefore
-- holds only the receipt, never the tree.
--
-- APPEND-ONLY, LIKE EVERYTHING ELSE HERE. An anchor that can be edited
-- is not a commitment. The same discipline as audit_log: UPDATE and
-- DELETE raise, TRUNCATE raises, and the guard covers the statement
-- level because row triggers do not fire on TRUNCATE.

create table if not exists public.ledger_anchors (
  id             uuid primary key default gen_random_uuid(),
  -- No FK to businesses, for the same reason ledger_chain_state has
  -- none: the receipt must outlive an erased tenant, or erasure would
  -- quietly destroy the evidence that the erasure itself was declared.
  business_id    uuid not null,
  first_sequence bigint not null,
  last_sequence  bigint not null,
  row_count      integer not null,
  merkle_root    text not null,
  -- The algorithm identifier travels WITH the receipt, exactly as the
  -- version travels inside ledger_canonical_v1's material. A future
  -- tree shape gets a new name rather than silently reinterpreting
  -- roots that were already published.
  algorithm      text not null default 'merkle_sha256_v1',
  -- 'local' means recorded here and NOT published anywhere independent.
  -- It proves nothing a skeptic must accept, and every surface that
  -- displays it has to say so.
  provider       text not null default 'local',
  provider_ref   text,
  anchored_at    timestamptz not null default now(),
  constraint ledger_anchors_range check (last_sequence >= first_sequence),
  constraint ledger_anchors_count check (row_count > 0)
);

-- One anchor per tenant per exact window: re-running the job is a
-- no-op rather than a pile of duplicate receipts for the same root.
create unique index if not exists idx_ledger_anchors_window
  on public.ledger_anchors (business_id, first_sequence, last_sequence);
create index if not exists idx_ledger_anchors_biz_recent
  on public.ledger_anchors (business_id, last_sequence desc);

alter table public.ledger_anchors enable row level security;
revoke all on public.ledger_anchors from anon, authenticated;

create or replace function public.ledger_anchor_append_only()
returns trigger
language plpgsql
as $$
begin
  raise exception
    'ledger_anchors is append-only: an anchor that can be edited or '
    'removed is not a commitment. Publish a new anchor instead.'
    using errcode = 'restrict_violation';
  return null;
end $$;

drop trigger if exists trg_ledger_anchors_append_only on public.ledger_anchors;
create trigger trg_ledger_anchors_append_only
  before update or delete on public.ledger_anchors
  for each row execute function public.ledger_anchor_append_only();

drop trigger if exists trg_ledger_anchors_no_truncate on public.ledger_anchors;
create trigger trg_ledger_anchors_no_truncate
  before truncate on public.ledger_anchors
  for each statement execute function public.ledger_anchor_append_only();

comment on table public.ledger_anchors is
  'Stage 5 receipts. Holds a Merkle root over a sequence window, never '
  'the tree (recomputable) and never business data (a hash of hashes). '
  'provider=local means NOT independently published - surfaces must say so.';

-- VERIFY (all must RAISE):
--   update ledger_anchors set merkle_root = 'x';
--   delete from ledger_anchors;
--   truncate ledger_anchors;
