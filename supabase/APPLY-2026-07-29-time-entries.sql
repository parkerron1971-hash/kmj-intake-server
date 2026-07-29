-- APPLY-2026-07-29-time-entries.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Billable time. The other half of the lawyer money model.
--
-- THE GAP
--   The readiness audit scored lawyers 7/12 and noted the odd shape of what
--   was missing: IOLTA trust reconciliation with per-client sub-balances was
--   already BUILT (gl_reports_t4), but the ordinary half was not. A firm
--   could reconcile client trust funds to the penny and had nowhere to
--   record that someone worked 1.5 hours on a matter.
--
--   A grep for time_entries / billable_hours / hourly_rate returned zero
--   matches across the whole repo.
--
-- WHY MINUTES AND NOT HOURS
--   Legal billing runs in tenths of an hour — six-minute increments. Stored
--   as a float, 0.1 + 0.2 is famously not 0.3, and a drifted bill is not a
--   rounding curiosity, it is a fee dispute and potentially a bar complaint.
--   Minutes are integers. The tenths are presentation.
--
-- WHY THE RATE IS COPIED ONTO THE ROW
--   The rate is SNAPSHOT at entry time, not looked up when the bill prints.
--   A firm that raises its rate in March must not silently re-price
--   February's work. History is what it was.
--
-- RELATIONSHIP TO customer_ledger
--   They answer different questions and neither replaces the other:
--     time_entries    — what WORK was done (the narrative on the bill)
--     customer_ledger — what the client PREPAID and has left (retainer)
--   Billing an entry to a retainer writes to BOTH: the entry moves to
--   'billed', and a negative hour row lands in the ledger. The entry's
--   ledger_entry_id records the link so nothing can be billed twice.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

create table if not exists public.time_entries (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references public.businesses(id) on delete cascade,
  contact_id    uuid not null references public.contacts(id)   on delete cascade,

  -- What was done. This is the line the client reads on the bill, so it is
  -- required — "1.5 hours" with no narrative is what fee disputes are made
  -- of.
  description   text not null check (length(btrim(description)) > 0),

  -- Integer minutes. See the header on why this is not a float.
  minutes       integer not null check (minutes > 0 and minutes <= 1440),

  -- Snapshot of the hourly rate when the work was recorded. Null means
  -- "not yet priced" — a paralegal logging time before a rate is set.
  rate          numeric(12,2) check (rate is null or rate >= 0),
  currency      text not null default 'usd',

  -- Non-billable time is still worth recording (pro bono, admin, a write-off
  -- decided later). It just never reaches an invoice.
  billable      boolean not null default true,

  status        text not null default 'unbilled'
                check (status in ('unbilled','billed','written_off')),

  -- Optional link to whatever the firm calls the matter. Modules are the
  -- practitioner's own structures, so this is deliberately loose.
  matter_ref    text,
  module_entry_id uuid,

  -- Set when billed. invoice_id for a normal bill; ledger_entry_id when the
  -- time was drawn against a prepaid retainer instead.
  invoice_id      uuid references public.invoices(id) on delete set null,
  ledger_entry_id uuid references public.customer_ledger(id) on delete set null,

  occurred_on   date not null default (now() at time zone 'utc')::date,
  created_by    uuid,
  created_at    timestamptz not null default now(),

  -- Billed time must say HOW it was billed. An entry marked billed with
  -- neither an invoice nor a ledger draw behind it is unbillable money that
  -- looks collected.
  constraint time_entries_billed_has_a_source
    check (status <> 'billed' or invoice_id is not null or ledger_entry_id is not null)
);

-- The two reads this table exists for: "what's unbilled for this client"
-- and "what's unbilled across the firm".
create index if not exists idx_time_entries_unbilled
  on public.time_entries (business_id, status, occurred_on desc)
  where status = 'unbilled';
create index if not exists idx_time_entries_contact
  on public.time_entries (business_id, contact_id, occurred_on desc);

alter table public.time_entries enable row level security;

drop policy if exists time_entries_owner_select on public.time_entries;
create policy time_entries_owner_select on public.time_entries
  for select to authenticated
  using (exists (
    select 1 from public.businesses b
    where b.id = time_entries.business_id and b.owner_id = auth.uid()
  ));

comment on table public.time_entries is
  'Billable time. Minutes are integers because legal billing runs in tenths of an hour and float drift becomes a fee dispute. rate is snapshot at entry so a rate change never re-prices history. Billing to a retainer writes here AND to customer_ledger, linked by ledger_entry_id so nothing bills twice.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select
  (select count(*) from information_schema.tables
    where table_schema='public' and table_name='time_entries') as table_ok,
  (select count(*) from pg_constraint
    where conrelid='public.time_entries'::regclass and contype='c') as checks;
