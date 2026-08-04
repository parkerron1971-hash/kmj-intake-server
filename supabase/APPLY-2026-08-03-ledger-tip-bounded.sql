-- APPLY-2026-08-03-ledger-tip-bounded.sql
-- THE ACTION LEDGER — binding the chain tip to the rows it summarises.
--
-- FOUND IN THE POST-ARC AUDIT. ledger_tip_forward_only made
-- last_sequence monotonic, so the tip could not be rolled BACKWARDS.
-- Nothing bounded how far FORWARD it could go. Setting a tenant's tip
-- to 999999 made ledger_verify report
--
--   "the ledger ends at #2 but the chain tip is #999999
--    - records were removed"
--
-- about a ledger from which nothing had been removed. That is a FALSE
-- ACCUSATION OF TAMPERING against an honest practice, and it is
-- indistinguishable from the real thing. It cannot conceal anything —
-- it is the loud direction — but in a system whose product is trust, a
-- false alarm nobody can disprove is its own kind of damage.
--
-- Kevin's ruling: bound the tip to max(sequence).
--
-- THREE HOLES, NOT ONE. The audit found that guarding UPDATE alone
-- would have been theatre:
--
--   1. UPDATE could set any forward value.
--   2. DELETE + INSERT bypassed the UPDATE guard entirely — proven:
--      deleting the row and re-inserting one with last_sequence=999999
--      succeeded. A guard on one verb is not a guard.
--   3. (business_id, sequence) had NO unique index, so a reset tip
--      would happily mint DUPLICATE sequence numbers — the precise
--      ambiguity about ordering that the original tip guard was
--      written to prevent, still reachable by another road.
--
-- THE RULE: the tip may never exceed max(sequence) + 1 for its tenant.
--
-- Why "+ 1" and not "= max". ledger_assign_sequence is a BEFORE INSERT
-- trigger: it stamps new.sequence and moves the tip while the row it
-- describes does not exist yet. One ahead IS the correct steady state
-- for the duration of that trigger. It is also exactly enough room for
-- the legitimate repair path (rebuild the tip from the rows).
--
-- VERIFIED BEFORE WRITING THIS, not assumed: the concern was that a
-- multi-row INSERT would break the rule, since a statement's own rows
-- can be invisible to queries taken under the statement's snapshot.
-- Tested all three shapes against a live database — three separate
-- INSERTs, one multi-row INSERT on a covered table, and a multi-row
-- INSERT directly into audit_log — and all three pass, because a query
-- inside a plpgsql trigger runs under a fresh command-counter snapshot
-- and does see the earlier rows.
--
-- COST: one max(sequence) per ledger insert. It is an index-only
-- backward scan on the existing idx_audit_log_biz_sequence, which the
-- unique index below now serves instead.

-- ─── 1. The bound ───────────────────────────────────────────────────
create or replace function public.ledger_tip_forward_only()
returns trigger
language plpgsql
security definer set search_path = public
as $$
declare
  v_max bigint;
begin
  -- Backwards is still refused: a reused sequence makes the ledger
  -- ambiguous about order, and order is most of what a ledger is for.
  if tg_op = 'UPDATE' and new.last_sequence < old.last_sequence then
    raise exception
      'ledger_chain_state.last_sequence cannot move backwards '
      '(% -> %): a reused sequence would make the ledger ambiguous '
      'about order.', old.last_sequence, new.last_sequence
      using errcode = 'restrict_violation';
  end if;

  select max(a.sequence) into v_max
    from public.audit_log a
   where a.business_id = new.business_id;

  if new.last_sequence > coalesce(v_max, 0) + 1 then
    raise exception
      'ledger_chain_state.last_sequence (%) cannot exceed the tenant''s '
      'highest recorded sequence (%) by more than one. A tip ahead of '
      'the rows makes verification report removals that never happened.',
      new.last_sequence, coalesce(v_max, 0)
      using errcode = 'restrict_violation';
  end if;

  return new;
end $$;

-- ─── 2. Every verb, not just UPDATE ─────────────────────────────────
drop trigger if exists trg_ledger_tip_forward_only on public.ledger_chain_state;
create trigger trg_ledger_tip_forward_only
  before insert or update on public.ledger_chain_state
  for each row execute function public.ledger_tip_forward_only();

-- The DELETE half of the bypass. Nothing legitimately removes a tip
-- row: ledger_erase_business READS it and deliberately does not reset
-- it, precisely so an erased range stays visible afterwards as a gap.
-- So this needs no exception path at all.
create or replace function public.ledger_tip_no_delete()
returns trigger
language plpgsql
as $$
begin
  raise exception
    'ledger_chain_state rows are never deleted. The tip outlives the '
    'business on purpose: it is what makes an erased range still show '
    'as a gap rather than vanishing.'
    using errcode = 'restrict_violation';
  return null;
end $$;

drop trigger if exists trg_ledger_tip_no_delete on public.ledger_chain_state;
create trigger trg_ledger_tip_no_delete
  before delete on public.ledger_chain_state
  for each row execute function public.ledger_tip_no_delete();

-- Row triggers do not fire on TRUNCATE, which is how the ledger's own
-- TRUNCATE hole was found. Same lesson, applied here before anyone has
-- to find it twice.
drop trigger if exists trg_ledger_tip_no_truncate on public.ledger_chain_state;
create trigger trg_ledger_tip_no_truncate
  before truncate on public.ledger_chain_state
  for each statement execute function public.ledger_tip_no_delete();

-- ─── 3. Duplicate sequences become impossible ───────────────────────
-- Verified clean first: zero duplicate (business_id, sequence) pairs
-- and zero NULL sequences in production, so this cannot fail on apply.
-- The non-unique index it replaces covered the same columns in the
-- same order, so every plan that used it is still served.
create unique index if not exists idx_audit_log_biz_sequence_unique
  on public.audit_log (business_id, sequence);
drop index if exists idx_audit_log_biz_sequence;

comment on function public.ledger_tip_forward_only() is
  'The tip is bounded by the rows: monotonic, and never more than one '
  'ahead of max(sequence) for the tenant. One ahead is the steady '
  'state during the BEFORE INSERT that assigns a sequence.';
comment on function public.ledger_tip_no_delete() is
  'A tip row is never deleted or truncated - deleting it would reset a '
  'tenant sequence and reopen the forward-tip hole through INSERT.';

-- VERIFY (all must RAISE):
--   update ledger_chain_state set last_sequence = 999999 where business_id = '<biz>';
--   delete from ledger_chain_state where business_id = '<biz>';
--   truncate ledger_chain_state;
-- And these must still WORK:
--   insert into contacts (business_id, name) values ('<biz>', 'probe');
--   insert into contacts (business_id, name) values ('<biz>','a'),('<biz>','b');
