-- Gift corrections exposed a ledger encoding bug: text::bytea interprets JSON
-- backslashes as bytea escapes, so a newline in an audit payload aborts the write.
-- Preserve every existing v1 hash and canonical function. New rows use explicit
-- UTF-8 plus a versioned, unambiguous JSON array. Mixed chains verify by row version.
-- No ledger rows, anchors, tips, erasure/redaction rules, or capture guards change.
begin;
set local lock_timeout='5s';
set local statement_timeout='60s';
alter table public.audit_log add column if not exists hash_version smallint not null default 1
  constraint audit_log_hash_version_check check (hash_version in (1,2));
alter table public.audit_log alter column hash_version set default 2;
comment on column public.audit_log.hash_version is
 '1: frozen legacy bytea escape interpretation; 2: versioned JSON array encoded as UTF-8. Old rows are never rehashed.';

create or replace function public.ledger_canonical_v2(r public.audit_log)
returns text language sql immutable set search_path=public as $$
 select jsonb_build_array(
   'v2', r.business_id::text,
   to_char(r.created_at at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
   r.sequence::text, coalesce(r.actor_type,''), coalesce(r.actor_id,''),
   coalesce(r.verb,''),coalesce(r.target_type,''),coalesce(r.target_id,''),
   case when r.ok then 'true' else 'false' end, coalesce(r.error,''),
   coalesce(r.summary,''),coalesce(r.authorized_by,''),coalesce(r.source,''),
   coalesce(r.subject_refs,'[]'::jsonb),coalesce(r.payload,'{}'::jsonb),
   coalesce(r.result,'{}'::jsonb)
 )::text;
$$;
comment on function public.ledger_canonical_v2(public.audit_log) is
 'FROZEN v2: fixed JSON array, explicit UTF-8; version is inside the hashed material. Keep v1 unchanged for existing rows.';

create or replace function public.ledger_row_hash(r public.audit_log)
returns text language plpgsql immutable set search_path=public as $$
begin
 if r.hash_version=1 then
   return encode(sha256((coalesce(r.prev_hash,'')||chr(30)||public.ledger_canonical_v1(r))::bytea),'hex');
 elsif r.hash_version=2 then
   return encode(sha256(convert_to(coalesce(r.prev_hash,'')||chr(30)||public.ledger_canonical_v2(r),'UTF8')),'hex');
 end if;
 raise exception 'Unsupported ledger hash version: %',r.hash_version;
end $$;
revoke all on function public.ledger_canonical_v2(public.audit_log),public.ledger_row_hash(public.audit_log) from public,anon,authenticated;
grant execute on function public.ledger_canonical_v2(public.audit_log),public.ledger_row_hash(public.audit_log) to service_role;

CREATE OR REPLACE FUNCTION public.ledger_assign_sequence()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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

  -- The caller cannot downgrade the encoding for newly appended rows.
  new.hash_version := 2;
  new.row_hash := public.ledger_row_hash(new);

  update public.ledger_chain_state
     set last_sequence = new.sequence,
         last_row_hash = new.row_hash,
         updated_at    = now()
   where business_id = new.business_id;

  return new;
end $function$
;

-- Same verification/anchoring/redaction behavior; only hash dispatch is versioned.
CREATE OR REPLACE FUNCTION public.ledger_verify(p_business_id uuid)
 RETURNS TABLE(checked bigint, hashed bigint, redacted bigint, first_sequence bigint, last_sequence bigint, intact boolean, broken_at bigint, reason text, gaps bigint[])
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
      v_expected := public.ledger_row_hash(r);
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
end $function$
;
revoke all on function public.ledger_verify(uuid) from public,anon,authenticated;
grant execute on function public.ledger_verify(uuid) to service_role;
notify pgrst, 'reload schema';
commit;
