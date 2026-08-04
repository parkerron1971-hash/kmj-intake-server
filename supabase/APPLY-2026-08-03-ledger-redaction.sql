-- APPLY-2026-08-03-ledger-redaction.sql
-- THE ACTION LEDGER — honouring one person's erasure request without
-- destroying a whole practice's record.
--
-- THE PROBLEM. The db-trigger tier copies to_jsonb(old)/to_jsonb(new)
-- of contacts, invoices, sessions, orders and module_entries into
-- audit_log.payload. That is third-party personal data — a therapist's
-- client, a lawyer's client — sitting in a table that refuses deletion.
-- Until now the ONLY removal path was ledger_erase_business(), which
-- erases the entire practice. So a single client exercising their right
-- could not be honoured at all: the practice would have to destroy its
-- own audit trail to comply.
--
-- THE RESOLUTION, and why it keeps both promises:
--
--   The FACT of an action is the audit trail. The CONTENTS of the
--   records it touched are the personal data. Only the second has to go.
--
-- A redaction clears `payload` and `result` and stamps `redacted_at`.
-- Everything that makes the row an audit record — when, who, which verb,
-- which sequence, what authorised it — survives untouched.
--
-- CRITICALLY, row_hash is NOT recomputed. It remains the fingerprint of
-- the ORIGINAL contents. Three consequences, all of them wanted:
--
--   1. The CHAIN IS UNBROKEN. The next row's prev_hash still matches,
--      so redacting one row does not invalidate everything after it.
--      (Recomputing would have forced a rewrite of every later row —
--      which is exactly the tampering this design exists to prevent.)
--   2. The redacted row can no longer be recomputed, so verification
--      reports it as DECLARED-unverifiable rather than as tampering.
--      A gap you can see is not the same as a gap you cannot.
--   3. The erased content is still COMMITTED TO. Anyone holding a copy
--      — an earlier export, or the data subject themselves — can prove
--      it hashed to the recorded value, while the system no longer
--      stores it. Erasure without losing provability.
--
-- The UPDATE guard is the load-bearing part. Redaction is the first and
-- only permitted update to this table, so it must not become a general
-- edit hatch: the trigger requires a live ticket AND verifies that
-- every other column is byte-identical.

-- ─── 1. What was redacted, and why ──────────────────────────────────
create table if not exists public.ledger_redactions (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null,
  subject_type  text,
  subject_id    text,
  rows_redacted bigint not null default 0,
  sequences     bigint[],
  reason        text,
  requested_by  text,
  redacted_at   timestamptz not null default now()
);
create index if not exists idx_ledger_redactions_biz
  on public.ledger_redactions (business_id, redacted_at desc);
alter table public.ledger_redactions enable row level security;
revoke all on public.ledger_redactions from anon, authenticated;
comment on table public.ledger_redactions is
  'One row per erasure request honoured. The ledger keeps the FACT of '
  'each action; this records which contents were removed and for whom.';

create table if not exists public.ledger_redaction_tickets (
  business_id uuid primary key,
  issued_at   timestamptz not null default now()
);
alter table public.ledger_redaction_tickets enable row level security;
revoke all on public.ledger_redaction_tickets from anon, authenticated;

alter table public.audit_log
  add column if not exists redacted_at timestamptz;
comment on column public.audit_log.redacted_at is
  'Set when the row contents were removed under a data-erasure request. '
  'row_hash still fingerprints the ORIGINAL contents, so the chain holds '
  'and the removed data remains provable to anyone who has a copy.';

-- ─── 2. The guard: redaction is the ONE permitted update ────────────
create or replace function public.ledger_append_only()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_ticket boolean;
begin
  if tg_op = 'TRUNCATE' then
    raise exception 'audit_log is append-only: TRUNCATE is never permitted.'
      using errcode = 'restrict_violation';
  end if;

  if tg_op = 'UPDATE' then
    -- Only a redaction may update, and only through the RPC that
    -- issues a ticket after recording what it is doing.
    select exists (select 1 from public.ledger_redaction_tickets t
                   where t.business_id = old.business_id) into v_ticket;
    if not v_ticket then
      raise exception
        'audit_log is append-only: rows are never updated. Corrections are '
        'new rows referencing the original.'
        using errcode = 'restrict_violation';
    end if;
    -- The narrow gate. Redaction may empty the contents and stamp the
    -- time — nothing else. Without this, "redaction" becomes a way to
    -- rewrite a verb, an actor, or an outcome.
    if (to_jsonb(old) - 'payload' - 'result' - 'redacted_at')
       is distinct from
       (to_jsonb(new) - 'payload' - 'result' - 'redacted_at') then
      raise exception
        'redaction may only clear payload and result: every other column '
        'must be unchanged.'
        using errcode = 'restrict_violation';
    end if;
    if new.payload <> '{}'::jsonb or new.result <> '{}'::jsonb then
      raise exception
        'redaction may only EMPTY contents, never write them.'
        using errcode = 'restrict_violation';
    end if;
    if new.redacted_at is null then
      raise exception 'a redacted row must record when it was redacted.'
        using errcode = 'restrict_violation';
    end if;
    return new;
  end if;

  -- DELETE
  if coalesce(current_setting('app.ledger_erasure', true), '') <> 'on' then
    raise exception
      'audit_log is append-only: deletion is only permitted through '
      'ledger_erase_business(), which records a tombstone first.'
      using errcode = 'restrict_violation';
  end if;
  select exists (select 1 from public.ledger_erasure_tickets t
                 where t.business_id = old.business_id) into v_ticket;
  if not v_ticket then
    raise exception
      'audit_log deletion refused: no erasure ticket for this business. '
      'A tombstone must be recorded before any row is removed.'
      using errcode = 'restrict_violation';
  end if;
  return old;
end $$;

-- ─── 3. Honour one subject's request ────────────────────────────────
create or replace function public.ledger_redact_subject(
  p_business_id  uuid,
  p_subject_type text,
  p_subject_id   text,
  p_reason       text default 'data_subject_erasure',
  p_requested_by text default null)
returns bigint
language plpgsql
security definer
set search_path = public
as $$
declare
  v_seqs  bigint[];
  v_count bigint;
begin
  -- Rows that touched this subject: the queryable subject_refs array
  -- (GIN-indexed) OR the legacy single-target columns.
  select coalesce(array_agg(sequence order by sequence), '{}'), count(*)
    into v_seqs, v_count
  from public.audit_log
  where business_id = p_business_id
    and redacted_at is null
    and (payload <> '{}'::jsonb or result <> '{}'::jsonb)
    and (subject_refs @> jsonb_build_array(
           jsonb_build_object('type', p_subject_type, 'id', p_subject_id))
         or (target_type = p_subject_type and target_id = p_subject_id));

  if coalesce(v_count, 0) = 0 then
    -- Still record the request. "We looked and there was nothing" is a
    -- meaningful answer to give a data subject.
    insert into public.ledger_redactions (
      business_id, subject_type, subject_id, rows_redacted, sequences,
      reason, requested_by)
    values (p_business_id, p_subject_type, p_subject_id, 0, '{}',
            p_reason, p_requested_by);
    return 0;
  end if;

  insert into public.ledger_redactions (
    business_id, subject_type, subject_id, rows_redacted, sequences,
    reason, requested_by)
  values (p_business_id, p_subject_type, p_subject_id, v_count, v_seqs,
          p_reason, p_requested_by);

  insert into public.ledger_redaction_tickets (business_id)
  values (p_business_id) on conflict (business_id) do nothing;

  update public.audit_log
     set payload = '{}'::jsonb,
         result  = '{}'::jsonb,
         redacted_at = now()
   where business_id = p_business_id
     and sequence = any(v_seqs);

  delete from public.ledger_redaction_tickets where business_id = p_business_id;
  return v_count;
end $$;

revoke all on function public.ledger_redact_subject(uuid, text, text, text, text)
  from public, anon, authenticated;

-- ─── 4. Verification reports redactions as DECLARED ─────────────────
drop function if exists public.ledger_verify(uuid);
create or replace function public.ledger_verify(p_business_id uuid)
returns table (
  checked        bigint,
  hashed         bigint,
  redacted       bigint,
  first_sequence bigint,
  last_sequence  bigint,
  intact         boolean,
  broken_at      bigint,
  reason         text,
  gaps           bigint[]
)
language plpgsql
stable
security definer
set search_path = public
as $$
declare
  r            public.audit_log;
  v_prev       text := null;
  v_expected   text;
  v_first      bigint := null;
  v_last       bigint := null;
  v_count      bigint := 0;
  v_hashed     bigint := 0;
  v_redacted   bigint := 0;
  v_broken     bigint := null;
  v_reason     text := null;
  v_gaps       bigint[] := '{}';
  v_prev_seq   bigint := null;
  v_tip_seq    bigint;
  v_tip_hash   text;
  v_expect_first bigint;
begin
  select c.last_sequence, c.last_row_hash into v_tip_seq, v_tip_hash
  from public.ledger_chain_state c where c.business_id = p_business_id;

  for r in
    select * from public.audit_log
    where business_id = p_business_id and sequence is not null
    order by sequence
  loop
    v_count := v_count + 1;
    if v_first is null then
      v_first := r.sequence;
      v_prev  := r.prev_hash;
    end if;
    if v_prev_seq is not null and r.sequence <> v_prev_seq + 1 then
      v_gaps := v_gaps || v_prev_seq;
    end if;
    v_prev_seq := r.sequence;
    v_last := r.sequence;

    if r.row_hash is null then
      v_prev := null;
      continue;
    end if;
    v_hashed := v_hashed + 1;

    -- Chain LINKAGE is checked for every hashed row, redacted or not —
    -- row_hash is untouched by redaction, which is the whole reason the
    -- chain survives it.
    if r.prev_hash is distinct from v_prev and v_broken is null then
      v_broken := r.sequence;
      v_reason := 'prev_hash does not match the preceding row';
    end if;

    if r.redacted_at is not null then
      -- Contents are gone by request, so the hash cannot be recomputed.
      -- That is a DECLARED absence, not a discrepancy. The recorded
      -- fingerprint still commits to what was there, so anyone holding
      -- a copy can still prove it.
      v_redacted := v_redacted + 1;
    else
      v_expected := encode(
        sha256((coalesce(r.prev_hash, '') || chr(30)
                || public.ledger_canonical_v1(r.*))::bytea), 'hex');
      if v_expected <> r.row_hash and v_broken is null then
        v_broken := r.sequence;
        v_reason := 'row contents do not match row_hash - this row was altered';
      end if;
    end if;
    v_prev := r.row_hash;
  end loop;

  select coalesce(max(t.last_sequence), 0) + 1 into v_expect_first
  from public.ledger_tombstones t where t.business_id = p_business_id;
  if v_first is not null and v_first > greatest(v_expect_first, 1)
     and v_broken is null then
    v_broken := v_first;
    v_reason := format(
      'records before #%s are missing with no erasure on record', v_first);
  end if;

  if v_tip_seq is not null and v_last is not null
     and v_last < v_tip_seq and v_broken is null then
    v_broken := v_last;
    v_reason := format(
      'the ledger ends at #%s but the chain tip is #%s - records were removed',
      v_last, v_tip_seq);
  end if;

  if v_tip_hash is not null and v_hashed > 0
     and v_prev is distinct from v_tip_hash and v_broken is null then
    v_broken := v_last;
    v_reason := 'the last record does not match the recorded chain tip';
  end if;

  if v_broken is null and array_length(v_gaps, 1) is not null then
    v_reason := 'sequence gap - see ledger_tombstones for erasures';
  end if;

  if v_hashed = 0 then
    return query select v_count, v_hashed, v_redacted, v_first, v_last,
                        false, null::bigint,
                        'nothing to verify - no row carries a hash yet '
                        '(these predate the chain)', v_gaps;
    return;
  end if;

  return query select v_count, v_hashed, v_redacted, v_first, v_last,
                      (v_broken is null), v_broken,
                      coalesce(v_reason, 'chain intact'), v_gaps;
end $$;

revoke all on function public.ledger_verify(uuid) from public, anon, authenticated;

-- VERIFY:
--   update audit_log set verb='x' where ...;              -- must RAISE
--   update audit_log set payload='{"a":1}' where ...;     -- must RAISE
--   select ledger_redact_subject('<biz>','contacts','<id>');
--   select * from ledger_verify('<biz>');                 -- intact, redacted>0
