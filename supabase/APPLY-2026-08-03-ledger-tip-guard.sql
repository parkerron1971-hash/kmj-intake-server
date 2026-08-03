-- APPLY-2026-08-03-ledger-tip-guard.sql
-- THE ACTION LEDGER — hardening the chain tip.
--
-- FOUND BY ACCIDENT, WHICH IS THE HONEST STORY: while verifying that
-- audit_log refuses tampering, a test statement ran
--   update ledger_chain_state set last_row_hash = 'forged';
-- and it SUCCEEDED. The ledger rows themselves were untouched (their
-- triggers held), and the damage was repaired from the rows — which is
-- the reassuring half: audit_log is authoritative and ledger_chain_state
-- is only its cached tip, so the tip can always be rebuilt from the
-- record.
--
-- But two real weaknesses were sitting there:
--
-- 1. NOTHING STOPPED THE SEQUENCE GOING BACKWARDS. Lower last_sequence
--    and the next insert reuses a sequence number that already exists.
--    Duplicate sequences would make the ledger ambiguous about order —
--    and order is most of what a ledger is for. A forged last_row_hash
--    is self-detecting (verify() compares each row's prev_hash against
--    the preceding row's actual hash, so the break is reported), but a
--    duplicated sequence is not.
--
-- 2. anon and authenticated still held the default Supabase grants on
--    ledger_chain_state and ledger_tombstones. RLS with no policies
--    already denies them every row, and PostgREST exposes no TRUNCATE,
--    so this was not reachable — but auditor_links revokes explicitly
--    and these two did not. Defence in depth should not be inconsistent
--    across three tables that guard the same thing.

-- ─── 1. The tip only ever moves forward ─────────────────────────────
create or replace function public.ledger_tip_forward_only()
returns trigger
language plpgsql
as $$
begin
  if new.last_sequence < old.last_sequence then
    raise exception
      'ledger_chain_state.last_sequence cannot move backwards '
      '(% -> %): a reused sequence would make the ledger ambiguous '
      'about order.', old.last_sequence, new.last_sequence
      using errcode = 'restrict_violation';
  end if;
  return new;
end $$;

drop trigger if exists trg_ledger_tip_forward_only on public.ledger_chain_state;
create trigger trg_ledger_tip_forward_only
  before update on public.ledger_chain_state
  for each row execute function public.ledger_tip_forward_only();

-- Deliberately NOT locked: last_row_hash stays writable, because the
-- legitimate repair path (rebuild the tip from the rows, exactly what
-- was done after the accident above) needs it, and a wrong hash is
-- self-detecting the next time the chain is walked.

-- ─── 2. Match auditor_links' explicit lockdown ──────────────────────
revoke all on public.ledger_chain_state from anon, authenticated;
revoke all on public.ledger_tombstones  from anon, authenticated;

comment on function public.ledger_tip_forward_only() is
  'Guards the chain tip: last_sequence is monotonic. A forged hash is '
  'self-detecting on the next walk; a reused sequence is not.';

-- VERIFY:
--   update ledger_chain_state set last_sequence = 0;   -- must RAISE
--   select count(*) from information_schema.role_table_grants
--    where table_name in ('ledger_chain_state','ledger_tombstones')
--      and grantee in ('anon','authenticated');        -- must be 0
