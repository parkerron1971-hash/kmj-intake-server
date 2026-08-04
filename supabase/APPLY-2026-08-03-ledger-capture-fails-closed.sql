-- APPLY-2026-08-03-ledger-capture-fails-closed.sql
-- THE ACTION LEDGER — closing the last silent gap in the provable tier.
--
-- THE HOLE. audit_row_change() wrapped its whole body in
--     exception when others then null;
-- with the comment "an audit hiccup must never block the business write".
-- That instinct is right about availability and wrong about this table.
-- The db_trigger tier's entire claim is the one written at the top of
-- APPLY-2026-08-03-ledger-coverage.sql: "PROVABLE. Transactional,
-- unbypassable." A swallowed exception makes that false. The business
-- write commits, the ledger row does not, and NOTHING says so — no gap
-- in the sequence (a sequence is only assigned to rows that made it),
-- no tombstone, no alert. It is the one failure mode a ledger cannot
-- have, because an absence you cannot detect is indistinguishable from
-- an action that never happened.
--
-- Reachable in practice: hold the per-tenant advisory lock that
-- ledger_assign_sequence takes and set a lock_timeout or
-- statement_timeout, and every write in that window commits unrecorded.
--
-- THE RULING: FAIL CLOSED. If the ledger cannot record the change, the
-- change does not happen. That is what makes "there is a row for every
-- write" true by construction rather than by hope — a write without a
-- row can no longer commit.
--
-- WHAT THIS COSTS, STATED PLAINLY. audit_log is now on the critical
-- path for writes to the eight audited tables: if it becomes
-- unwritable, those writes start failing. That is a deliberate trade.
-- The alternative is a ledger that quietly has holes, which is worth
-- less than no ledger at all — a ledger nobody can trust still gets
-- shown to auditors. Loud failure is recoverable; silent omission is
-- not. Note also that nothing here is expected to throw in normal
-- operation: lock contention WAITS, it does not error, and the insert's
-- columns are all satisfied. The handler was insurance, and insurance
-- that hides the accident is worse than none.

create or replace function public.audit_row_change() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  v_biz   uuid;
  v_id    text;
  v_state text;
  v_msg   text;
begin
  begin
    v_biz := coalesce(new.business_id, old.business_id);
    v_id  := coalesce(new.id, old.id)::text;
    if v_biz is null then
      -- Previously "nothing to file it under" and a silent skip. All
      -- eight audited tables declare business_id NOT NULL, so this is
      -- unreachable today; leaving it as a skip meant the FIRST table
      -- added with a nullable tenant would go quietly unrecorded. Now
      -- that mistake announces itself the moment the trigger is
      -- attached, which is the only time it is cheap to fix.
      raise exception
        'audit_row_change cannot file a % on % under any business: '
        'business_id is null. A row the ledger cannot attribute must '
        'not be written unattributed.', tg_op, tg_table_name
        using errcode = 'not_null_violation';
    end if;

    insert into public.audit_log
      (business_id, actor_type, actor_id, verb, target_type, target_id,
       ok, summary, payload, result, source, authorized_by, subject_refs)
    values (
      v_biz,
      case when auth.uid() is null then 'system' else 'user' end,
      auth.uid()::text,
      'db:' || tg_table_name || '_' || lower(tg_op),
      tg_table_name,
      v_id,
      true,
      initcap(lower(tg_op)) || ' on ' || tg_table_name,
      case when tg_op = 'DELETE'
           then jsonb_build_object('before', to_jsonb(old))
           when tg_op = 'INSERT'
           then jsonb_build_object('after', to_jsonb(new))
           else jsonb_build_object('before', to_jsonb(old),
                                   'after',  to_jsonb(new)) end,
      '{}'::jsonb,
      'db_trigger',
      'rls',
      jsonb_build_array(jsonb_build_object('type', tg_table_name, 'id', v_id))
    );
  exception when others then
    get stacked diagnostics v_state = returned_sqlstate,
                            v_msg   = message_text;
    -- The forensic copy goes to the Postgres log, where it survives the
    -- rollback that is about to happen. It carries the detail; the
    -- message the caller sees deliberately does not, because that one
    -- crosses a tenant boundary.
    raise warning
      '[ledger] capture failed for % on % (id %): % (SQLSTATE %). '
      'The business write is being rolled back.',
      tg_op, tg_table_name, v_id, v_msg, v_state;
    raise exception
      'This change was not saved because the action ledger could not '
      'record it. Nothing was written, so there is no unrecorded '
      'change — please try again.'
      using errcode = 'internal_error',
            hint = 'The server log holds the underlying database error.';
  end;
  return coalesce(new, old);
end $$;

comment on function public.audit_row_change() is
  'The provable tier. FAILS CLOSED: if the ledger row cannot be '
  'written the business write is rolled back with it, so "a row exists '
  'for every write" holds by construction. Underlying cause goes to '
  'the Postgres log, never to the caller.';

-- VERIFY (both halves, on a throwaway row):
--   -- 1. normal writes still work and still produce a row
--   insert into contacts (business_id, name) values ('<biz>', 'probe');
--   select verb from audit_log where target_id = '<the id>';
--   -- 2. make the ledger unwritable and confirm the write is REFUSED
--   --    rather than silently dropped:
--   alter table audit_log add constraint tmp_block check (false) not valid;
--   -- (validate it, attempt an insert -> must raise, then drop it)
