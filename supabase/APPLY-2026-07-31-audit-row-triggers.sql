-- APPLY-2026-07-31-audit-row-triggers.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Audit expansion: the two gaps the Arc 4 table couldn't close from
-- the application layer, closed at the database layer in one shot.
--
--   1. BEFORE/AFTER — the app never captures before-images (same
--      reason undo skips update verbs). A row-level trigger has OLD
--      and NEW for free.
--   2. NON-CHIEF WRITES — a practitioner editing an invoice through
--      the frontend goes straight to PostgREST; no backend code runs.
--      The trigger fires regardless of who writes: frontend (actor =
--      auth.uid()), backend service role (actor = system), Chief.
--
-- SCOPE: UPDATE + DELETE on the three money tables (invoices, bills,
-- business_expenses). INSERTs are excluded on purpose — creation is
-- already announced through events/chief paths and auditing every
-- insert would double row volume for no investigative value.
-- contractors is excluded on purpose: tin_encrypted must never be
-- copied into a second table, even as ciphertext.
--
-- The trigger NEVER blocks the write: any failure is swallowed.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

create or replace function public.audit_row_change() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  begin
    insert into public.audit_log
      (business_id, actor_type, actor_id, verb, target_type, target_id,
       ok, summary, payload, result, source)
    values (
      coalesce(new.business_id, old.business_id),
      case when auth.uid() is null then 'system' else 'user' end,
      auth.uid()::text,
      tg_table_name || '_' || lower(tg_op),
      tg_table_name,
      coalesce(new.id, old.id)::text,
      true,
      initcap(lower(tg_op)) || ' on ' || tg_table_name,
      case when tg_op = 'DELETE'
           then jsonb_build_object('before', to_jsonb(old))
           else jsonb_build_object('before', to_jsonb(old),
                                   'after',  to_jsonb(new)) end,
      '{}'::jsonb,
      'db_trigger'
    );
  exception when others then
    null;  -- an audit hiccup must never block the business write
  end;
  return coalesce(new, old);
end $$;

-- invoices
drop trigger if exists audit_invoices_update on public.invoices;
create trigger audit_invoices_update
  after update on public.invoices
  for each row when (old.* is distinct from new.*)
  execute function public.audit_row_change();
drop trigger if exists audit_invoices_delete on public.invoices;
create trigger audit_invoices_delete
  after delete on public.invoices
  for each row execute function public.audit_row_change();

-- bills
drop trigger if exists audit_bills_update on public.bills;
create trigger audit_bills_update
  after update on public.bills
  for each row when (old.* is distinct from new.*)
  execute function public.audit_row_change();
drop trigger if exists audit_bills_delete on public.bills;
create trigger audit_bills_delete
  after delete on public.bills
  for each row execute function public.audit_row_change();

-- business_expenses
drop trigger if exists audit_expenses_update on public.business_expenses;
create trigger audit_expenses_update
  after update on public.business_expenses
  for each row when (old.* is distinct from new.*)
  execute function public.audit_row_change();
drop trigger if exists audit_expenses_delete on public.business_expenses;
create trigger audit_expenses_delete
  after delete on public.business_expenses
  for each row execute function public.audit_row_change();

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select count(*) as audit_triggers_should_be_six
from pg_trigger
where tgname like 'audit_%'
  and tgrelid in ('public.invoices'::regclass,
                  'public.bills'::regclass,
                  'public.business_expenses'::regclass);
