-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-08-10 — the ledger records WHICH machine decided
--
-- audit_log already answers "who did what, when, and did it work".
-- actor_type tells an auditor whether a human or Chief acted — 37 of the
-- first 61 rows are actor_type='chief' — but nothing anywhere records
-- WHICH model produced the decision.
--
-- That gap matters for the thing this ledger exists to support. "An AI
-- did it" is not a provenance claim; "claude-sonnet-5 did it, on this
-- date, under this prompt shape" is. When a practitioner disputes an
-- action a year from now, the model that made it will have been
-- superseded twice, and the ledger is the only place that could still
-- say which one it was.
--
-- Nullable, and deliberately so. Rows written before this column
-- existed cannot be back-filled with a fact nobody recorded, and
-- inferring "it was probably Sonnet" from a date would be a guess
-- wearing the costume of an audit record. NULL means NOT RECORDED, and
-- the reader is entitled to know the difference between that and "no
-- model was involved" — which is what actor_type is for.
--
-- Safe to re-run.
-- ══════════════════════════════════════════════════════════════════

alter table public.audit_log
  add column if not exists ai_model text;

comment on column public.audit_log.ai_model is
  'The model that produced this action, captured at write time (e.g. '
  'claude-sonnet-5). NULL means NOT RECORDED — either the row predates '
  '2026-08-10, or no model call was in scope. Whether a machine acted at '
  'all is actor_type; this says which one.';

-- Auditors ask "what did the AI do", not "what did row 4,891 do".
create index if not exists audit_log_ai_model_idx
  on public.audit_log (business_id, ai_model, created_at desc)
  where ai_model is not null;

-- The append-only guarantee is the whole point of this table: BEFORE
-- UPDATE/DELETE triggers raise, so even service_role cannot rewrite a
-- row. Adding a column must not have quietly loosened that.
do $$
declare n int;
begin
  select count(*) into n from pg_trigger t
    join pg_class c on c.oid = t.tgrelid
   where c.relname = 'audit_log' and not t.tgisinternal;
  raise notice 'audit_log non-internal triggers still present: %', n;
end $$;
