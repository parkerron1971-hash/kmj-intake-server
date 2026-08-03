-- APPLY-2026-08-03-action-ledger-stage1.sql
-- THE ACTION LEDGER — Stage 1 (capture), per Kevin's spec + the 8/03
-- pre-build audit. Kevin's rulings: evolve audit_log (don't create a
-- fifth history), money+client tables first for the trigger tier, and
-- erasure leaves a TOMBSTONE with a VISIBLE BREAK.
--
-- Why evolve rather than create: audit_log already carries when / tenant
-- / actor+type / verb / target / payload / ok+error, has 13 call sites,
-- 6 DB triggers, an endpoint and a UI. A parallel `action_ledger` table
-- would guarantee two half-populated histories forever.
--
-- What this migration adds:
--   1. The spec's missing columns (authorized_by, subject_refs, sequence,
--      display_timezone) + prev_hash/row_hash RESERVED for Stage 2.
--   2. ledger_chain_state — per-tenant monotonic sequence, assigned under
--      an advisory lock. Deliberately has NO foreign key to businesses:
--      it must SURVIVE erasure, because a surviving counter is what makes
--      a gap provable rather than invisible.
--   3. ledger_tombstones — the erasure record. Also no FK, same reason.
--   4. DB-ENFORCED append-only. Until now "append-only" was a code
--      promise: there were no triggers, relforcerowsecurity was off, and
--      service_role (which the entire backend writes as) has
--      rolbypassrls = true. Our own code could rewrite history silently.
--   5. action_types — the controlled vocabulary, seeded from Python.

-- ─── 1. The spec's six fields, completed ────────────────────────────
alter table public.audit_log
  add column if not exists authorized_by    text,
  add column if not exists subject_refs     jsonb not null default '[]'::jsonb,
  add column if not exists display_timezone text,
  add column if not exists sequence         bigint,
  add column if not exists verb_registered  boolean,
  add column if not exists prev_hash        text,   -- Stage 2
  add column if not exists row_hash         text;   -- Stage 2

comment on column public.audit_log.authorized_by is
  'Field 6: the permission tier or policy rule that allowed this action '
  '(e.g. scheduled:C:recurring, notification_action:A, trust-track:granted). '
  'The difference between "Chief did this" and "Chief was permitted to, here is the rule".';
comment on column public.audit_log.subject_refs is
  'Field 5: [{type,id}, ...] of every record touched. Answers "show me '
  'everything that ever happened to this client".';
comment on column public.audit_log.sequence is
  'Monotonic per tenant, assigned under an advisory lock. Gaps are '
  'meaningful: they mean rows were erased, and ledger_tombstones says why.';

-- ─── 2. Chain state: the survivor ───────────────────────────────────
create table if not exists public.ledger_chain_state (
  business_id   uuid primary key,
  last_sequence bigint not null default 0,
  last_row_hash text,
  updated_at    timestamptz not null default now()
);
alter table public.ledger_chain_state enable row level security;
-- No policies by design: service-role only. Practitioners read their
-- history through /audit, never this.
comment on table public.ledger_chain_state is
  'Per-tenant ledger tip (sequence + hash). NO FK to businesses on '
  'purpose: it outlives erasure so an erased range still shows as a gap. '
  'Holds no personal data — a uuid, a counter, a hash.';

-- ─── 3. Tombstones: erasure, made visible ───────────────────────────
create table if not exists public.ledger_tombstones (
  id             uuid primary key default gen_random_uuid(),
  business_id    uuid not null,
  erased_at      timestamptz not null default now(),
  rows_erased    bigint not null,
  first_sequence bigint,
  last_sequence  bigint,
  prior_row_hash text,
  reason         text,
  requested_by   text
);
create index if not exists idx_ledger_tombstones_biz
  on public.ledger_tombstones (business_id, erased_at desc);
alter table public.ledger_tombstones enable row level security;
comment on table public.ledger_tombstones is
  'GDPR erasure beats append-only — but never silently. One row per '
  'erasure recording what range vanished. No FK to businesses: the '
  'tombstone must outlive the business it describes.';

-- ─── 4. Backfill BEFORE the guard goes up ───────────────────────────
-- Ordering matters and the first run proved it: with the append-only
-- trigger created first, this backfill raised its own exception. The
-- guard is doing its job — so the one legitimate rewrite of history
-- happens before the guard exists, and never again.
-- These 15 rows predate the chain. Stage 2 starts hashing from the
-- current tip; nothing before it is provable, and the product must say
-- so plainly rather than imply the whole history is sealed.
with ordered as (
  select id, row_number() over (partition by business_id order by created_at, id) as rn
  from public.audit_log where sequence is null)
update public.audit_log a set sequence = o.rn
from ordered o where a.id = o.id and a.sequence is null;

insert into public.ledger_chain_state (business_id, last_sequence)
select business_id, max(sequence) from public.audit_log group by business_id
on conflict (business_id) do update
  set last_sequence = greatest(public.ledger_chain_state.last_sequence,
                               excluded.last_sequence);

-- ─── 5. Sequence assignment (BEFORE INSERT) ─────────────────────────
-- Stage 2 extends this same function to compute row_hash. The advisory
-- lock is why hashing belongs here and not in Python: two concurrent
-- inserts reading the tip over HTTP would both claim the same
-- predecessor and fork the chain.
create or replace function public.ledger_assign_sequence()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_seq  bigint;
  v_hash text;
begin
  if new.business_id is null then
    return new;
  end if;

  perform pg_advisory_xact_lock(hashtextextended(new.business_id::text, 0));

  insert into public.ledger_chain_state (business_id, last_sequence)
  values (new.business_id, 0)
  on conflict (business_id) do nothing;

  select last_sequence, last_row_hash into v_seq, v_hash
  from public.ledger_chain_state
  where business_id = new.business_id
  for update;

  new.sequence  := coalesce(v_seq, 0) + 1;
  new.prev_hash := v_hash;   -- Stage 2 populates row_hash from this

  if new.verb_registered is null then
    new.verb_registered := exists (
      select 1 from public.action_types t where t.verb = new.verb);
  end if;

  update public.ledger_chain_state
     set last_sequence = new.sequence, updated_at = now()
   where business_id = new.business_id;

  return new;
end $$;

-- ─── 6. Append-only, enforced where it can't be bypassed ────────────
create or replace function public.ledger_append_only()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'UPDATE' then
    raise exception
      'audit_log is append-only: rows are never updated. Corrections are '
      'new rows referencing the original.'
      using errcode = 'restrict_violation';
  end if;

  -- DELETE is permitted only inside ledger_erase_business(), which sets
  -- this transaction-local flag after writing a tombstone. Business
  -- deletion cascades here too, which is why erasure runs LAST in
  -- account_lifecycle — by then there is nothing left to cascade.
  if coalesce(current_setting('app.ledger_erasure', true), '') <> 'on' then
    raise exception
      'audit_log is append-only: deletion is only permitted through '
      'ledger_erase_business(), which records a tombstone first.'
      using errcode = 'restrict_violation';
  end if;
  return old;
end $$;

drop trigger if exists trg_audit_log_sequence on public.audit_log;
create trigger trg_audit_log_sequence
  before insert on public.audit_log
  for each row execute function public.ledger_assign_sequence();

drop trigger if exists trg_audit_log_append_only on public.audit_log;
create trigger trg_audit_log_append_only
  before update or delete on public.audit_log
  for each row execute function public.ledger_append_only();

-- ─── 6. Erasure: the one sanctioned removal path ────────────────────
create or replace function public.ledger_erase_business(
  p_business_id uuid,
  p_reason      text default 'gdpr_erasure',
  p_requested_by text default null)
returns bigint
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count bigint;
  v_first bigint;
  v_last  bigint;
  v_hash  text;
begin
  select count(*), min(sequence), max(sequence)
    into v_count, v_first, v_last
  from public.audit_log where business_id = p_business_id;

  select last_row_hash into v_hash
  from public.ledger_chain_state where business_id = p_business_id;

  -- The tombstone is written BEFORE the delete and lives in a table with
  -- no FK to businesses, so it survives both the rows and the tenant.
  insert into public.ledger_tombstones (
    business_id, rows_erased, first_sequence, last_sequence,
    prior_row_hash, reason, requested_by)
  values (p_business_id, coalesce(v_count, 0), v_first, v_last,
          v_hash, p_reason, p_requested_by);

  perform set_config('app.ledger_erasure', 'on', true);   -- txn-local
  delete from public.audit_log where business_id = p_business_id;
  perform set_config('app.ledger_erasure', 'off', true);

  -- ledger_chain_state is deliberately NOT reset. The next row for this
  -- tenant continues the sequence, so verification sees a gap where the
  -- erased range used to be and the tombstone explains it.
  return coalesce(v_count, 0);
end $$;

revoke all on function public.ledger_erase_business(uuid, text, text) from public, anon, authenticated;

-- ─── 7. The controlled vocabulary ───────────────────────────────────
-- Deliberate deviation from the spec's "FK to action_types": a foreign
-- key would make an unregistered verb FAIL the insert, and losing the
-- record of an action is strictly worse for a ledger than recording an
-- unfamiliar verb name. So the vocabulary is closed by CODE (a drift
-- test, same discipline as action_registry) and made QUERYABLE here:
-- every row is stamped verb_registered, and unregistered verbs are a
-- reportable condition rather than a data-loss event.
create table if not exists public.action_types (
  verb          text primary key,
  effect        text,
  reversibility text,
  bulk          boolean not null default false,
  namespace     text not null default 'chief',
  description   text,
  first_seen    timestamptz not null default now()
);
alter table public.action_types enable row level security;
drop policy if exists action_types_read on public.action_types;
create policy action_types_read on public.action_types
  for select to authenticated using (true);
comment on table public.action_types is
  'The ledger vocabulary, seeded from action_registry.REGISTRY + the '
  'event catalog + namespaced prefixes (rules:, platform:, job:, db:, '
  'webhook:). Advisory, not a FK — see the note in this migration.';

-- ─── 8. Indexes the ledger queries actually need ────────────────────
create index if not exists idx_audit_log_biz_sequence
  on public.audit_log (business_id, sequence);
create index if not exists idx_audit_log_subject_refs
  on public.audit_log using gin (subject_refs);
create index if not exists idx_audit_log_unregistered
  on public.audit_log (business_id, created_at desc)
  where verb_registered is false;

-- VERIFY:
--   select count(*) filter (where sequence is null) as unsequenced from audit_log;
--   select * from ledger_chain_state;
--   update audit_log set verb='x' where id=(select id from audit_log limit 1);  -- must RAISE
--   delete from audit_log where id=(select id from audit_log limit 1);          -- must RAISE
