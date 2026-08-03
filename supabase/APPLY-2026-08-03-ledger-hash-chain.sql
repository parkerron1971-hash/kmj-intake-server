-- APPLY-2026-08-03-ledger-hash-chain.sql
-- THE ACTION LEDGER — Stage 2 (hash chain).
--
-- Each row's hash is computed from its own contents PLUS the previous
-- row's hash. Alter any historical row and every hash after it stops
-- matching, so tampering is detectable by re-walking the chain.
--
-- WHY THIS LIVES IN POSTGRES AND NOT IN PYTHON. The spec estimated
-- "roughly fifty lines of code" — right about the size, wrong about the
-- location. In the application, computing prev_hash means read-the-tip
-- then insert: two concurrent actions read the SAME tip and both claim
-- it, forking the chain. Under real load that is not hypothetical. It
-- also could not bind service_role, which bypasses RLS, nor the six
-- database triggers that now write rows without any Python involved.
-- Here, one BEFORE INSERT trigger holding a per-tenant advisory lock
-- serialises every writer — application, trigger, or psql session.
--
-- CANONICAL SERIALIZATION is the load-bearing decision in this file.
-- The byte representation fed to sha256 is frozen below. Stage 5's
-- Merkle proofs are recomputable from stored rows ONLY IF this never
-- silently changes — so it is versioned (v1) and the version travels
-- INSIDE the hashed material. Changing the recipe means a new version
-- and a documented chain break, never a quiet redefinition.

-- ─── The canonical form ─────────────────────────────────────────────
create or replace function public.ledger_canonical_v1(r public.audit_log)
returns text
language sql
immutable
as $$
  -- Field order is fixed and explicit. jsonb is normalised by ::jsonb
  -- (key order and whitespace are not significant in jsonb), NULLs
  -- collapse to '' via concat_ws, and the separator is a unit character
  -- that cannot appear in the values themselves.
  select concat_ws(
    chr(31),
    'v1',
    r.business_id::text,
    to_char(r.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
    r.sequence::text,
    coalesce(r.actor_type, ''),
    coalesce(r.actor_id, ''),
    coalesce(r.verb, ''),
    coalesce(r.target_type, ''),
    coalesce(r.target_id, ''),
    case when r.ok then 'true' else 'false' end,
    coalesce(r.error, ''),
    coalesce(r.summary, ''),
    coalesce(r.authorized_by, ''),
    coalesce(r.source, ''),
    coalesce(r.subject_refs::text, '[]'),
    coalesce(r.payload::text, '{}'),
    coalesce(r.result::text, '{}')
  );
$$;

comment on function public.ledger_canonical_v1(public.audit_log) is
  'FROZEN. The exact bytes hashed into row_hash. Stage 5 Merkle proofs '
  'recompute from stored rows, so any change here invalidates every '
  'existing proof — add ledger_canonical_v2 instead and record the '
  'version change as a deliberate chain break.';

-- ─── Sequence + chain, one trigger, one lock ────────────────────────
create or replace function public.ledger_assign_sequence()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_seq  bigint;
  v_prev text;
begin
  if new.business_id is null then
    return new;
  end if;

  -- Serialise per tenant for the rest of the transaction. Two writers
  -- cannot both read the same tip; the second waits and chains onto the
  -- first. Per-tenant (not global) so unrelated businesses never block
  -- each other.
  perform pg_advisory_xact_lock(hashtextextended(new.business_id::text, 0));

  insert into public.ledger_chain_state (business_id, last_sequence)
  values (new.business_id, 0)
  on conflict (business_id) do nothing;

  select last_sequence, last_row_hash into v_seq, v_prev
  from public.ledger_chain_state
  where business_id = new.business_id
  for update;

  new.sequence  := coalesce(v_seq, 0) + 1;
  new.prev_hash := v_prev;

  if new.verb_registered is null then
    new.verb_registered := exists (
      select 1 from public.action_types t where t.verb = new.verb);
  end if;

  -- created_at participates in the hash, so pin it now rather than
  -- letting the column default fire after this trigger.
  if new.created_at is null then
    new.created_at := now();
  end if;
  if new.id is null then
    new.id := gen_random_uuid();
  end if;

  new.row_hash := encode(
    sha256((coalesce(new.prev_hash, '') || chr(30)
            || public.ledger_canonical_v1(new.*))::bytea), 'hex');

  update public.ledger_chain_state
     set last_sequence = new.sequence,
         last_row_hash = new.row_hash,
         updated_at    = now()
   where business_id = new.business_id;

  return new;
end $$;

-- ─── Verification ───────────────────────────────────────────────────
-- Re-walks a tenant's chain and reports the first row whose stored hash
-- disagrees with a recomputation, plus any sequence gap. Reads a single
-- snapshot: the tip may move while this runs (the ledger is live), and
-- a verification that raced its own subject would be worthless.
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
  v_broken     bigint := null;
  v_reason     text := null;
  v_gaps       bigint[] := '{}';
  v_prev_seq   bigint := null;
  v_hashed     bigint := 0;
begin
  for r in
    select * from public.audit_log
    where business_id = p_business_id and sequence is not null
    order by sequence
  loop
    v_count := v_count + 1;
    if v_first is null then
      v_first := r.sequence;
      v_prev  := r.prev_hash;      -- start from whatever this row claims
    end if;

    if v_prev_seq is not null and r.sequence <> v_prev_seq + 1 then
      v_gaps := v_gaps || v_prev_seq;
    end if;
    v_prev_seq := r.sequence;
    v_last := r.sequence;

    -- Rows written before Stage 2 have no hash; they are honestly
    -- unprovable rather than silently counted as intact.
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

  if v_broken is null and array_length(v_gaps, 1) is not null then
    v_reason := 'sequence gap - see ledger_tombstones for erasures';
  end if;

  -- HONESTY GUARD. Found by running this against production: every real
  -- chain reported 'intact' while carrying ZERO hashes, because rows
  -- written before Stage 2 are skipped. "Verified" must never mean
  -- "there was nothing to verify" — that is the single most misleading
  -- thing a tamper-evidence check could say.
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

revoke all on function public.ledger_verify(uuid) from public, anon;
grant execute on function public.ledger_verify(uuid) to authenticated;

-- VERIFY (run after apply):
--   select * from ledger_verify('<business uuid>');
--   -- then prove detection: a direct UPDATE is impossible (append-only),
--   -- so tampering can only be simulated by disabling the guard, which
--   -- is itself the point.
