-- The Sunday match: recorded gifts matched to the bank deposits that carried
-- them (2026-10-31). Idempotent. Apply in the Supabase SQL editor BEFORE the
-- code: the ledger reads plaid_transactions.gift_match_fee.
--
-- Kevin: everybody gives on Sunday (cash, check, card, Cash App), each gift
-- is recorded by person, and the money reaches the bank over the next days;
-- "make sure that there is no duplicates".
--
--   gift_deposit_matches   one match: its kind, the gifts' and deposits'
--                          totals, any fee the platform kept (and the expense
--                          row booking it), who made it, Chief's batch
--   gift_deposit_items     the gifts and deposits in a match. Its primary
--                          key (business_id, side, ref) is the no-duplicates
--                          rule: a gift, or a deposit, is in ONE match, ever
--   plaid_transactions     money_kind gains 'gifts' (a deposit that carried
--                          recorded gifts: never income, never waiting) and
--                          gift_match_fee (the fee riding on that deposit,
--                          which the ledger adds back to clear the gifts)
--
-- Server-only like the funds: RLS on, no policies.
begin;

create table if not exists public.gift_deposit_matches (
  id              uuid primary key default gen_random_uuid(),
  business_id     uuid not null references public.businesses(id) on delete cascade,
  kind            text not null check (kind in ('plate', 'online', 'transfer', 'mixed')),
  gifts_total     numeric(14,2) not null check (gifts_total > 0),
  deposits_total  numeric(14,2) not null check (deposits_total > 0),
  fee             numeric(14,2) not null default 0 check (fee >= 0),
  fee_expense_id  uuid,
  made_by         text not null check (made_by in ('chief', 'person')),
  made_by_user    uuid,
  batch_id        text,
  note            text check (note is null or char_length(note) <= 300),
  created_at      timestamptz not null default now(),
  unique (business_id, id),
  check (gifts_total = deposits_total + fee)
);
create index if not exists gift_deposit_matches_by_batch
  on public.gift_deposit_matches (business_id, batch_id) where batch_id is not null;

create table if not exists public.gift_deposit_items (
  business_id  uuid not null,
  match_id     uuid not null,
  side         text not null check (side in ('gift', 'deposit')),
  ref          text not null check (char_length(ref) between 1 and 120),
  amount       numeric(14,2) not null check (amount > 0),
  primary key (business_id, side, ref),
  foreign key (business_id, match_id) references public.gift_deposit_matches(business_id, id) on delete cascade
);
create index if not exists gift_deposit_items_by_match on public.gift_deposit_items (business_id, match_id);

alter table public.plaid_transactions
  add column if not exists gift_match_fee numeric(14,2) not null default 0;

alter table public.plaid_transactions
  drop constraint if exists plaid_transactions_money_kind_check;
alter table public.plaid_transactions
  add constraint plaid_transactions_money_kind_check
  check (money_kind is null or money_kind in ('income', 'owner', 'transfer', 'gifts'));

-- The ledger re-posts a bank row when anything it books from changes; the
-- fee riding on a gift deposit now does. Same trigger as the live one
-- (APPLY-2026-10-02-bank-money-kind.sql) plus one line.
drop trigger if exists gl_enq_plaid_upd on public.plaid_transactions;
create trigger gl_enq_plaid_upd after update on public.plaid_transactions
  for each row when (
    old.reconciliation_status is distinct from new.reconciliation_status
    or old.business_category is distinct from new.business_category
    or old.business_subcategory is distinct from new.business_subcategory
    or old.excluded_from_books is distinct from new.excluded_from_books
    or old.amount is distinct from new.amount
    or old.money_kind is distinct from new.money_kind
    or old.gift_match_fee is distinct from new.gift_match_fee
  ) execute function public.gl_enqueue();

alter table public.gift_deposit_matches enable row level security;
alter table public.gift_deposit_items enable row level security;
revoke all on public.gift_deposit_matches from anon, authenticated;
revoke all on public.gift_deposit_items from anon, authenticated;
grant all on public.gift_deposit_matches to service_role;
grant all on public.gift_deposit_items to service_role;

commit;

notify pgrst, 'reload schema';

-- Check it landed:
--   select count(*) from information_schema.tables
--    where table_schema = 'public' and table_name in ('gift_deposit_matches', 'gift_deposit_items');   -- 2
--   select column_name from information_schema.columns
--    where table_name = 'plaid_transactions' and column_name = 'gift_match_fee';
