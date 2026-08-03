-- APPLY-2026-08-03-ledger-verify-anchored.sql
-- THE ACTION LEDGER — closing the tamper-detection gap.
--
-- The adversarial review found that a chain could be BROKEN and still
-- report "Unaltered". Three separate holes, all in the same direction:
--
--  1. ledger_verify started the walk from whatever the FIRST SURVIVING
--     ROW claimed its predecessor was. Delete rows 1..N and the walk
--     begins at N+1, is internally consistent, and reports intact.
--  2. Gaps were only noticed BETWEEN two surviving rows, so deleting
--     the TAIL left a contiguous 1..M-1 and reported intact.
--  3. ledger_chain_state — the anchor deliberately kept alive across
--     erasure precisely so a gap stays provable — was never read by the
--     verifier at all.
--
-- And the append-only DELETE trigger trusted a bare session GUC: anyone
-- who could `set app.ledger_erasure = 'on'` could delete rows with no
-- tombstone written. The product tells auditors "the database refuses
-- deletions, including from the platform operator" (auditor_portal.py).
-- That sentence has to be true.
--
-- TRUNCATE was also unguarded: row-level triggers do not fire on it,
-- and service_role holds the grant.

-- ─── 1. Erasure needs a TICKET, not a flag ──────────────────────────
create table if not exists public.ledger_erasure_tickets (
  business_id uuid primary key,
  issued_at   timestamptz not null default now()
);
alter table public.ledger_erasure_tickets enable row level security;
revoke all on public.ledger_erasure_tickets from anon, authenticated;
comment on table public.ledger_erasure_tickets is
  'A one-shot permit written by ledger_erase_business immediately after '
  'the tombstone. The append-only trigger requires a matching row, so '
  'setting the session GUC alone no longer authorises a delete.';

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
    raise exception
      'audit_log is append-only: TRUNCATE is never permitted.'
      using errcode = 'restrict_violation';
  end if;

  if tg_op = 'UPDATE' then
    raise exception
      'audit_log is append-only: rows are never updated. Corrections are '
      'new rows referencing the original.'
      using errcode = 'restrict_violation';
  end if;

  -- DELETE: the flag alone is no longer enough. There must ALSO be a
  -- live ticket for this exact business, and only ledger_erase_business
  -- issues one — after it has written the tombstone.
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

drop trigger if exists trg_audit_log_append_only on public.audit_log;
create trigger trg_audit_log_append_only
  before update or delete on public.audit_log
  for each row execute function public.ledger_append_only();

-- Row triggers do not fire on TRUNCATE; this one is per-statement.
drop trigger if exists trg_audit_log_no_truncate on public.audit_log;
create trigger trg_audit_log_no_truncate
  before truncate on public.audit_log
  for each statement execute function public.ledger_append_only();

-- ─── 2. Erasure issues, then withdraws, its own ticket ──────────────
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

  -- Tombstone FIRST, in a table with no FK to businesses, so it
  -- survives both the rows and the tenant.
  insert into public.ledger_tombstones (
    business_id, rows_erased, first_sequence, last_sequence,
    prior_row_hash, reason, requested_by)
  values (p_business_id, coalesce(v_count, 0), v_first, v_last,
          v_hash, p_reason, p_requested_by);

  insert into public.ledger_erasure_tickets (business_id)
  values (p_business_id) on conflict (business_id) do nothing;

  perform set_config('app.ledger_erasure', 'on', true);
  delete from public.audit_log where business_id = p_business_id;
  perform set_config('app.ledger_erasure', 'off', true);

  delete from public.ledger_erasure_tickets where business_id = p_business_id;

  -- ledger_chain_state is deliberately NOT reset: the sequence carries
  -- on past the gap, and the tombstone explains it.
  return coalesce(v_count, 0);
end $$;

revoke all on function public.ledger_erase_business(uuid, text, text)
  from public, anon, authenticated;

-- ─── 3. The verifier anchors to the chain state ─────────────────────
drop function if exists public.ledger_verify(uuid);
create or replace function public.ledger_verify(p_business_id uuid)
returns table (
  checked        bigint,
  hashed         bigint,
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

    if r.prev_hash is distinct from v_prev and v_broken is null then
      v_broken := r.sequence;
      v_reason := 'prev_hash does not match the preceding row';
    end if;
    v_expected := encode(
      sha256((coalesce(r.prev_hash, '') || chr(30)
              || public.ledger_canonical_v1(r.*))::bytea), 'hex');
    if v_expected <> r.row_hash and v_broken is null then
      v_broken := r.sequence;
      v_reason := 'row contents do not match row_hash - this row was altered';
    end if;
    v_prev := r.row_hash;
  end loop;

  -- ANCHORING. Everything above only proves the surviving rows agree
  -- with each other. These three checks are what make a DELETION
  -- visible, and their absence is what let a truncated chain report
  -- "Unaltered".

  -- (a) A missing PREFIX. The first surviving sequence must be 1, or
  --     must pick up exactly where a recorded erasure left off.
  -- Qualify the column: `last_sequence` is also an OUT parameter of
  -- this function, and an unqualified reference is ambiguous.
  select coalesce(max(t.last_sequence), 0) + 1 into v_expect_first
  from public.ledger_tombstones t where t.business_id = p_business_id;
  if v_first is not null and v_first > greatest(v_expect_first, 1)
     and v_broken is null then
    v_broken := v_first;
    v_reason := format(
      'records before #%s are missing with no erasure on record', v_first);
  end if;

  -- (b) A missing TAIL. The chain tip survives erasure precisely so
  --     this comparison is possible.
  if v_tip_seq is not null and v_last is not null
     and v_last < v_tip_seq and v_broken is null then
    v_broken := v_last;
    v_reason := format(
      'the ledger ends at #%s but the chain tip is #%s - records were removed',
      v_last, v_tip_seq);
  end if;

  -- (c) The final hash must match the tip the database recorded.
  if v_tip_hash is not null and v_hashed > 0
     and v_prev is distinct from v_tip_hash and v_broken is null then
    v_broken := v_last;
    v_reason := 'the last record does not match the recorded chain tip';
  end if;

  if v_broken is null and array_length(v_gaps, 1) is not null then
    v_reason := 'sequence gap - see ledger_tombstones for erasures';
  end if;

  -- "Verified" must never quietly mean "there was nothing to verify".
  if v_hashed = 0 then
    return query select v_count, v_hashed, v_first, v_last,
                        false, null::bigint,
                        'nothing to verify - no row carries a hash yet '
                        '(these predate the chain)', v_gaps;
    return;
  end if;

  return query select v_count, v_hashed, v_first, v_last,
                      (v_broken is null), v_broken,
                      coalesce(v_reason, 'chain intact'), v_gaps;
end $$;

-- FINDING 4.5 — it was executable by any authenticated user against any
-- tenant's uuid, bypassing the API's own read gate. The backend calls it
-- as service_role; nothing else needs it.
revoke all on function public.ledger_verify(uuid) from public, anon, authenticated;

-- VERIFY:
--   truncate audit_log;                          -- must RAISE
--   set app.ledger_erasure='on'; delete from audit_log where ...;  -- must RAISE (no ticket)
--   select * from ledger_verify('<uuid>');
