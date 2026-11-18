-- Help requests: the pastor says yes, the treasurer pays (church_help.py;
-- Kevin 2026-11-18: "requesting help shouldn't be directly tied to
-- treasurer. shouldn't the pastor handle that and submit approval to
-- treasurer?").
--
--   church_help_requests.pay_to          who the treasurer pays: the electric
--                                        company, the landlord, the store
--                                        (never the person). 120 at most.
--   church_help_requests.pay_ref         a reference for the treasurer: an
--                                        account ending, an invoice number.
--                                        120 at most.
--   church_help_requests.pay_due         the day the bill is due, if known.
--   church_help_requests.sent_to_pay_at  when the care side sent it to the
--                                        treasurer; null until then.
--   church_help_requests.sent_to_pay_by  who sent it (a login's user id).
--   church_help_given.reference          the treasurer's reference for a
--                                        payment: a check number. 120 at most.
--   church_help_given.how                gains 'transfer' (a bank payment).
--
-- A payee and a sent time go together (church_help_requests_sent_has_payee).
-- A partial index finds what waits on the treasurer.
--
-- Additive: no row changes, nothing anyone sees changes until a request is
-- sent. Server-only like the rest of the Help tables (RLS on, no policies,
-- browser roles revoked: APPLY-2026-10-27-church-help.sql), so no policy is
-- added. Safe to run twice; one transaction; lock_timeout 5s; ends with
-- NOTIFY pgrst so the API sees the columns at once. Until it is applied the
-- server leaves these columns out of every read, sending to the treasurer
-- and paying from the treasurer's side answer 503, and the rest of Help
-- requests works as before.
--
-- Check after applying (6 rows):
--   select table_name, column_name, data_type from information_schema.columns
--    where table_schema = 'public'
--      and ((table_name = 'church_help_requests'
--            and column_name in ('pay_to', 'pay_ref', 'pay_due', 'sent_to_pay_at', 'sent_to_pay_by'))
--        or (table_name = 'church_help_given' and column_name = 'reference'))
--    order by 1, 2;
-- and the how check names transfer:
--   select pg_get_constraintdef(oid) from pg_constraint where conname = 'church_help_given_how_check';
--
-- Rollback (take every request off the treasurer's list, and every bank
-- payment out, first):
--   drop index if exists public.church_help_requests_to_pay;
--   alter table public.church_help_requests drop constraint if exists church_help_requests_sent_has_payee,
--     drop column if exists sent_to_pay_by, drop column if exists sent_to_pay_at, drop column if exists pay_due,
--     drop column if exists pay_ref, drop column if exists pay_to;
--   alter table public.church_help_given drop column if exists reference;
--   alter table public.church_help_given drop constraint if exists church_help_given_how_check;
--   alter table public.church_help_given add constraint church_help_given_how_check
--     check (how in ('cash', 'check', 'gift_card', 'groceries', 'ride', 'other'));
begin;
set local lock_timeout = '5s';

alter table public.church_help_requests
  add column if not exists pay_to text,
  add column if not exists pay_ref text,
  add column if not exists pay_due date,
  add column if not exists sent_to_pay_at timestamptz,
  add column if not exists sent_to_pay_by uuid;

alter table public.church_help_given
  add column if not exists reference text;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'church_help_requests_pay_to_short') then
    alter table public.church_help_requests
      add constraint church_help_requests_pay_to_short check (pay_to is null or char_length(pay_to) between 1 and 120);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_help_requests_pay_ref_short') then
    alter table public.church_help_requests
      add constraint church_help_requests_pay_ref_short check (pay_ref is null or char_length(pay_ref) <= 120);
  end if;
  -- Sent to the treasurer means someone is to be paid.
  if not exists (select 1 from pg_constraint where conname = 'church_help_requests_sent_has_payee') then
    alter table public.church_help_requests
      add constraint church_help_requests_sent_has_payee check (sent_to_pay_at is null or pay_to is not null);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_help_given_reference_short') then
    alter table public.church_help_given
      add constraint church_help_given_reference_short check (reference is null or char_length(reference) <= 120);
  end if;
end $$;

-- A bank payment is a way the treasurer pays.
alter table public.church_help_given drop constraint if exists church_help_given_how_check;
alter table public.church_help_given add constraint church_help_given_how_check
  check (how in ('cash', 'check', 'gift_card', 'groceries', 'ride', 'transfer', 'other'));

create index if not exists church_help_requests_to_pay
  on public.church_help_requests (business_id, pay_due)
  where sent_to_pay_at is not null and status = 'approved';

commit;

notify pgrst, 'reload schema';
