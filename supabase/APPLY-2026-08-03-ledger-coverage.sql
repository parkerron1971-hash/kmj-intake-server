-- APPLY-2026-08-03-ledger-coverage.sql
-- THE ACTION LEDGER — Stage 1b (coverage). Kevin's ruling: money and
-- client tables first.
--
-- WHY A DATABASE TIER AT ALL. The pre-build audit found ~200 direct
-- PostgREST writes from React across 64 files. When a practitioner edits
-- an invoice in the UI, the browser talks straight to PostgREST and NO
-- application code runs — there is nothing for an app-level logger to
-- hook. There is also no database driver in the backend (every write is
-- an individual HTTP call), so "the ledger write is transactional with
-- the action" is achievable ONLY inside Postgres. A trigger is both the
-- transactional seam and the only vantage point that sees every writer.
--
-- TWO TIERS, ON PURPOSE:
--   db_trigger rows  = PROVABLE. Transactional, unbypassable, carries
--                      before/after. Cannot know intent or authority.
--   application rows = INTENT. Who, why, and under which rule
--                      (authorized_by) — things a trigger can't see.
-- A Chief-created invoice produces one of each. They correlate through
-- subject_refs; GET /audit hides the db tier by default so a
-- practitioner's history stays readable while the provable tier stays
-- complete underneath.

-- ─── The upgraded trigger ───────────────────────────────────────────
create or replace function public.audit_row_change() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  v_biz uuid;
  v_id  text;
begin
  begin
    v_biz := coalesce(new.business_id, old.business_id);
    v_id  := coalesce(new.id, old.id)::text;
    if v_biz is null then
      return coalesce(new, old);   -- nothing to file it under
    end if;

    insert into public.audit_log
      (business_id, actor_type, actor_id, verb, target_type, target_id,
       ok, summary, payload, result, source, authorized_by, subject_refs)
    values (
      v_biz,
      case when auth.uid() is null then 'system' else 'user' end,
      auth.uid()::text,
      -- Namespaced to match action_types, so db rows are registered
      -- vocabulary rather than permanent verb_registered=false noise.
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
      -- Honest about what actually permitted this write: row-level
      -- security did. The trigger cannot see a seat rank or a plan tier;
      -- claiming more would make field 6 a lie.
      'rls',
      jsonb_build_array(jsonb_build_object('type', tg_table_name, 'id', v_id))
    );
  exception when others then
    null;  -- an audit hiccup must never block the business write
  end;
  return coalesce(new, old);
end $$;

-- ─── Retire the July trigger names ──────────────────────────────────
-- The 7/31 migration named business_expenses' triggers audit_expenses_*
-- (short form). The generated names below are audit_business_expenses_*,
-- so a plain re-run would leave BOTH installed and double-log every
-- update and delete on that table. Caught by counting triggers after the
-- first apply — 5 where 3 were expected.
drop trigger if exists audit_expenses_update on public.business_expenses;
drop trigger if exists audit_expenses_delete on public.business_expenses;

-- ─── Coverage: money, then client ───────────────────────────────────
do $$
declare
  -- Money first, per Kevin's ruling. invoices/bills/business_expenses
  -- already had UPDATE+DELETE; INSERT is added because React creates
  -- these directly (InvoicesPanel alone has 11 direct write calls) and
  -- creation is exactly the event an app-tier logger never sees.
  t text;
  tables text[] := array[
    'invoices', 'bills', 'business_expenses', 'orders', 'outbound_transfers',
    'contacts', 'sessions', 'module_entries'];
  ops text[] := array['insert', 'update', 'delete'];
  op text;
begin
  foreach t in array tables loop
    if to_regclass('public.' || t) is null then
      raise notice 'skipping % (absent)', t;
      continue;
    end if;
    foreach op in array ops loop
      execute format('drop trigger if exists audit_%s_%s on public.%I', t, op, t);
      if op = 'update' then
        execute format(
          'create trigger audit_%s_update after update on public.%I '
          'for each row when (old.* is distinct from new.*) '
          'execute function public.audit_row_change()', t, t);
      else
        execute format(
          'create trigger audit_%s_%s after %s on public.%I '
          'for each row execute function public.audit_row_change()',
          t, op, op, t);
      end if;
    end loop;
  end loop;
end $$;

-- NOT covered, deliberately: contractors (the tax-profile columns hold
-- an encrypted TIN and a before/after payload would copy ciphertext into
-- a second table), restricted_module_entries (the clinical class keeps
-- its own access log), and the GL machine tables (journal_entries /
-- ledger_entries / gl_sync_queue — high-volume derived writes whose
-- source rows are already covered here).

-- VERIFY:
--   select event_object_table, count(*) from information_schema.triggers
--   where trigger_name like 'audit_%' group by 1 order by 1;   -- 8 × 3
