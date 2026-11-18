-- APPLY-2026-11-18-church-money-holders.sql
--
-- Giving as its own tick on a person's sheet, the database half (step three
-- of "One sheet per person", piece 2 of 7). Kevin, 2026-11-18: "yes build
-- with C" (a holder asks, the owner taps yes), and on who holds it: a Member
-- or a Manager may hold Giving at Work or Lead, a Viewer only See; an Admin
-- asks like anyone else; only the owner says yes.
--
-- Until now the money rows opened for exactly three kinds of person: the
-- owner, an active Admin seat, the outside accountant
-- (ministry_finance_access, APPLY-2026-09-29-ministry-readiness.sql). This
-- adds a fourth: an active office login the owner has ticked. Apply with
-- zero holders. No door on the server decides by the tick yet
-- (church_money_gate, the next PR, behind a switch); but the moment a row
-- exists in church_money_holders, every read the app makes with the
-- person's own login goes through these policies and sees it.
--
-- TABLES (both server-only: RLS on, no policies, browser roles revoked)
--   church_money_holders   one row a login a church: the tick.
--     business_id   the church
--     user_id       the login
--     seat_id       the business_users row the tick was given to. The tick
--                   counts only while THAT row is active: a login taken off
--                   the team and invited again is a new row, so an old tick
--                   never comes back with it (the row goes with its seat)
--     level         see | work | lead. See reads; Work and Lead also change
--                   rows. Lead is the server's (it means nothing more here)
--     who_gave      may see gift rows, the giving events and the gift alerts
--                   (who gave, not only how much)
--     bank          may see the bank feed and its accounts
--     granted_by    the owner who said yes
--     granted_at    when
--     ask_id        the ask this answered, if it came from one
--   church_money_asks      a request for a tick, waiting for the owner.
--     id, business_id, user_id (who it is for), asked_by (never the same
--     person), wants {level, who_gave, bank}, status asked | approved |
--     declined | expired | withdrawn, asked_at, expires_at (7 days),
--     reminded_at (the 48-hour reminder went), answered_by, answered_at.
--     One open ask a login a church (church_money_asks_one_open).
--
-- THE OLD NAMES STAY NARROW. ministry_finance_access is NOT touched: it is
-- still the owner, an Admin seat and the accountant, and nothing else. The
-- tick is read only by functions this file makes, and by two bodies it
-- replaces. So running an older file again can only take the tick's reach
-- away, never add to it (see "RUNNING AN OLDER FILE AGAIN" below).
--
-- FUNCTIONS (each SECURITY DEFINER with a fixed search_path unless said;
-- each reads only businesses, business_users, business_collaborators and
-- church_money_holders, none of which has a policy that calls any of them:
-- nothing here can recurse, docs/RLS_MODEL.md, the 42P17 rule)
--   ministry_finance_walled(b)      NEW. The business is one the money wall
--                                   stands in front of (the 2026-09-29 type
--                                   list, the same one ministry_finance_guard
--                                   carries)
--   church_money_tick(b, part)      NEW. The caller holds the tick for
--                                   `part` on an ACTIVE seat: 'any' (a row),
--                                   'who_gave', 'bank', 'work' (level work or
--                                   lead AND the seat is not a Viewer)
--   ministry_finance_guard(b)       REPLACED: its 2026-09-29 text with one
--                                   clause added, "or the caller holds any
--                                   tick". ministry_financial_privacy and the
--                                   invoice/payment branch of the events and
--                                   alerts policies call it, unchanged
--   ministry_giving_access(b)       REPLACED: (ministry_finance_access OR
--                                   tick('who_gave')) AND church_giving_open.
--                                   It was ministry_finance_access AND
--                                   church_giving_open (2026-10-27).
--                                   gift_row_privacy, the relabel trigger and
--                                   the giving branch of the events and
--                                   alerts policies call it, unchanged. Only
--                                   replaced while church_giving_open exists
--   ministry_finance_write_guard(b) NEW. not walled, OR
--                                   ministry_finance_access, OR tick('work')
--   ministry_finance_bank_guard(b)  NEW. not walled, OR
--                                   ministry_finance_access, OR tick('bank')
--   church_money_giving_write(b)    NEW. May change a giving event or a gift
--                                   alert: ministry_giving_access (who may
--                                   see who gave, the keeper's lock included)
--                                   AND (ministry_finance_access OR
--                                   tick('work')). If the 2026-10-27 file has
--                                   been rolled back it is
--                                   ministry_finance_access, as the gift rows
--                                   are then
--   church_money_grant(...)         NEW, the server's alone, not SECURITY
--                                   DEFINER. Raises unless p_by is the
--                                   church's owner_id
--   church_money_answer(...)        NEW, the same. The owner's yes or no
--   church_money_ask(...)           NEW, the same. Opens an ask, first
--                                   marking one that ran out as expired (the
--                                   one-open index cannot read the clock)
--   ministry_finance_access, church_giving_open and the trigger function
--   protect_gift_classification are NOT touched.
--
-- POLICIES. Nothing existing is dropped or changed. Added, all RESTRICTIVE
-- (they only ever narrow), all TO authenticated:
--   ministry_financial_write_insert / _update / _delete   on the nine tables
--     that carry ministry_financial_privacy: a direct write takes the write
--     guard. Why: tenant_writer_write (2026-07-31) lets every Member, Manager
--     and Admin seat write invoices, bills, business_expenses,
--     plaid_transactions and customer_ledger straight through PostgREST, and
--     only the restrictive ministry_financial_privacy (FOR ALL, one guard for
--     reading and writing) stops them. Widening that one guard to a See tick
--     would have handed every See holder those writes.
--   church_money_bank   on plaid_transactions and plaid_accounts, FOR ALL:
--     the bank takes the bank guard, so a holder without the bank tick reads
--     the books and not the bank.
--   church_money_event_update / _delete on events, and
--   church_money_alert_update / _delete on chief_notifications: changing or
--     deleting a money row there (a giving event, an invoice or payment
--     event, a gift alert, an invoice-paid alert) takes the write rule for
--     its kind. Why: the two policies that hide those rows are SELECT-only
--     (2026-09-29, 2026-10-27) and both tables are tenant_writer_write's, so
--     a See tick that made the rows visible would have let a Member or
--     Manager seat edit and delete them. A row that fails is skipped, not an
--     error, so "mark all read" by an office login still works on the rest.
--     No INSERT policy is added: a tick never changes who may insert (a
--     working seat can insert an event of any type today, tick or not), a
--     refused insert is an error rather than a skipped row, and the app
--     itself inserts invoice_sent and invoice_paid events from the browser.
--     Closing forged inserts is its own change with its own check.
--
-- THE SIGNED-OUT ROLE (anon). Every restrictive money policy, the old ones
-- and these, is TO authenticated: none of them is ever consulted for anon,
-- on any of the nine tables or the two beside them. What keeps anon out is
-- that no permissive policy lets it in. That holds on ten of the eleven. On
-- business_expenses production has a permissive allow-all policy TO public
-- today (business_expenses_all, USING true), so anon reads and writes every
-- row there, a church's too, before this file and after it, exactly the
-- same: this file neither widens nor closes that. It is being dropped by a
-- separate change; until it is, the same policy also gives every signed-in
-- login the permissive half of a write there, and the restrictive guards
-- (the tick's Work rule, never on a Viewer seat) are what hold.
--
-- WITH ZERO HOLDERS, WHAT CHANGES. church_money_tick is `exists(... from
-- church_money_holders ...)`, so with no rows it is false for every part and
-- every caller. Then:
--   ministry_finance_guard       its old text OR false = its old answer
--   ministry_giving_access       (access OR false) AND church_giving_open
--                                = its old body
--   ministry_finance_write_guard = exists(business AND (not walled OR
--                                access)) = ministry_finance_guard, row for
--                                row; ministry_finance_bank_guard the same
--   the three write policies and church_money_bank
--                                restrictive policies AND together. Each
--                                write already had to pass
--                                ministry_financial_privacy (USING and WITH
--                                CHECK of ministry_finance_guard, FOR ALL);
--                                it now passes that AND an expression of the
--                                same value. X AND X = X. NO CHANGE
--   the four event and alert policies
--                                ONE DELIBERATE NARROWING, and the only
--                                change this file makes to anyone before a
--                                tick exists. Today a Member or Manager seat
--                                (and an Admin the Giving keeper has locked
--                                out) cannot see a money row in events or
--                                chief_notifications, and so cannot touch it
--                                with a filtered write; but an UNFILTERED one
--                                (`delete from events`, `update
--                                chief_notifications set status = ...` with
--                                no WHERE and no RETURNING) reads no column,
--                                so Postgres never consults the SELECT-only
--                                policy and the hidden money rows go with the
--                                rest. After this file those rows are skipped
--                                by such a write, and an unfiltered update
--                                that would turn a row INTO a money row is
--                                refused. Everyone who can see a money row
--                                today passes its write rule today, so
--                                nothing a person could do to a row they can
--                                see changes, and no other table changes.
-- __tests__/church_money_holders_db.mjs runs every select and every write
-- (filtered, unfiltered, upsert, RETURNING, FOR UPDATE, moving a row to
-- another business) as an owner, an Admin, the accountant, a Manager, a
-- Member, a Viewer, a stranger, a shop's own people, the signed-out role and
-- a login with no id, before and after, on a real Postgres, and holds the
-- difference to exactly that list.
--
-- WITH A HOLDER (what the tick opens, and what it cannot):
--   read the books     (the nine tables)        any tick, an active seat
--   read gift rows, giving events, gift alerts  + who_gave, and the Giving
--                                               keeper's lock still applies
--   read the bank                               + bank
--   write a money row through the browser       + level work or lead, AND a
--                                               Member, Manager or Admin
--                                               seat (tenant_writer_write
--                                               never let a Viewer write)
--   change or delete a money event or alert     the same; a giving one also
--                                               needs who_gave. A See holder
--                                               cannot mark a money alert
--                                               read (the app marks alerts
--                                               read with the person's own
--                                               login): the next PR answers
--                                               that on the server
--   the seat is revoked, or the login is taken off and invited again:
--                                               nothing, at once
--
-- KNOWN, AND LEFT FOR THE SERVER (the next PR):
--   * A Work holder lowered to a Viewer stops writing at once, but raised
--     back to a Member they write again without the owner. Nothing in a row
--     records that a seat was lowered and raised; the server must lower the
--     tick to See when it lowers the seat, and delete the row on a revoke.
--   * A tick the owner gave keeps working if businesses.owner_id ever
--     changes (no route transfers a business today). The new owner may take
--     it away; nobody else can add one.
--   * An ask that ran out stays "asked" until someone opens a new one
--     (church_money_ask marks it) or answers it (church_money_answer marks
--     it and says so).
--
-- RUNNING AN OLDER FILE AGAIN (each one only narrows; this file run once
-- more afterwards puts the tick back):
--   APPLY-2026-09-29-ministry-readiness.sql     resets ministry_finance_guard
--     to its 2026-09-29 body: every holder reads nothing until this file is
--     run again. (It also puts the gift rule back before the Giving keeper,
--     which is that file's own old hazard, not this one's.)
--   APPLY-2026-10-27-church-keys-gift-rows.sql  resets ministry_giving_access:
--     the who-gave tick opens nothing until this file is run again.
--   ROLLBACK-2026-10-27-church-keys-gift-rows.sql   drops
--     ministry_giving_access and church_giving_open: the who-gave tick opens
--     nothing, and this file and its rollback still run (the giving function
--     is only replaced while church_giving_open exists).
--
-- Cost: one more function call a row on reads of the two bank tables
-- (church_money_bank), and one more on a browser write of a money row, an
-- event or an alert.
-- Measured on PGlite, 4,000 rows, best of seven (relative only; real Postgres
-- is several times faster at both): an Admin's count of plaid_transactions
-- 173 ms before, 256 ms after; a count of bills 110 ms and 111 ms; an update
-- of 4,000 bills 226 ms before, 453 ms after; a count of events 62 ms and
-- 60 ms; an update of 4,000 events 197 ms before, 308 ms after. Reads of the
-- seven tables that are not the bank cost what they did.
--
-- Locks: CREATE POLICY takes a brief ACCESS EXCLUSIVE lock on each of the
-- nine tables, events and chief_notifications (catalog only, no rewrite, no
-- scan); the new tables' foreign keys take a brief SHARE ROW EXCLUSIVE lock
-- on businesses and business_users. lock_timeout stops this file rather than
-- queueing behind a long transaction: run it again. A table that is missing
-- stops the file (nothing is half applied).
--
-- One transaction, safe to run twice, nothing dropped that is not made again
-- in the same transaction. Undo: ROLLBACK-2026-11-18-church-money-holders.sql.
-- Instant stop without it: delete from public.church_money_holders;
--
-- Check before applying (read-only; stop if an answer differs and say what
-- you saw):
--   -- Q1. The restrictive policies on the fourteen tables. Expected, and no
--   --     other RESTRICTIVE row: ministry_financial_privacy ALL on each of
--   --     the nine; gift_row_privacy ALL on invoices; church_giving_bank ALL
--   --     on plaid_transactions and plaid_accounts; ministry_financial_events
--   --     SELECT on events; ministry_financial_notifications SELECT on
--   --     chief_notifications (read 2026-11-18: exactly these 14). The one
--   --     PERMISSIVE row whose qual is `true` is business_expenses_all (see
--   --     "THE SIGNED-OUT ROLE" above); any other is a stop.
--   select tablename, policyname, permissive, cmd, roles::text, qual, with_check
--     from pg_policies
--    where schemaname = 'public'
--      and tablename in ('invoices','journal_entries','ledger_entries','plaid_transactions','plaid_accounts',
--                        'customer_ledger','business_expenses','bills','chief_bookkeeping_proposals',
--                        'events','chief_notifications','businesses','business_users','business_collaborators')
--    order by tablename, permissive desc, policyname;
--   -- Q2. The functions this file builds on, as production has them.
--   --     Expected body_md5 (the repo's own files, checked by the test):
--   --       ministry_finance_access(uuid)      d70537830d8607c5cd1d3393cebd8bbd
--   --       ministry_finance_guard(uuid)       abb84e022e7e5ea2402b66a58ede7d25
--   --       ministry_giving_access(uuid)       29be8df9757f624ffb3fcd4d579cd92f
--   --       church_giving_open(uuid)           6d7029fe8d023ffbb01d362261c88e17
--   --       protect_gift_classification()      305e3d8399d8b0d17651c7eaee5ac7b4
--   --       is_business_writer(uuid)           167c6359afee0f18f2336179d4b6ec10
--   --     each definer true but protect_gift_classification; each with a
--   --     search_path of public; one owner for all of them; none of the
--   --     names this file makes exists yet.
--   select p.oid::regprocedure::text as fn, pg_get_userbyid(p.proowner) as owner, p.prosecdef as definer,
--          p.proconfig, p.proacl::text as acl,
--          md5(btrim(regexp_replace(p.prosrc, '[[:space:]]+', ' ', 'g'))) as body_md5
--     from pg_proc p join pg_namespace n on n.oid = p.pronamespace
--    where n.nspname = 'public'
--      and p.proname in ('ministry_finance_access','ministry_finance_guard','ministry_giving_access','church_giving_open',
--                        'protect_gift_classification','is_business_writer',
--                        'ministry_finance_walled','church_money_tick','ministry_finance_write_guard',
--                        'ministry_finance_bank_guard','church_money_giving_write','church_money_grant',
--                        'church_money_answer','church_money_ask')
--    order by 1;
--   -- Q3. Everything that calls the wall. Expected: the 14 policies of Q1,
--   --     and the functions ministry_finance_guard, ministry_giving_access
--   --     and protect_gift_classification. A view, a materialized view or
--   --     any other function here is something no file in the repo made.
--   select 'policy' as kind, schemaname || '.' || tablename || ' / ' || policyname as object, cmd as detail
--     from pg_policies
--    where coalesce(qual, '') || ' ' || coalesce(with_check, '') ~ 'ministry_finance_access|ministry_giving_access|ministry_finance_guard|church_giving_open'
--   union all
--   select 'function', p.oid::regprocedure::text, pg_get_userbyid(p.proowner)
--     from pg_proc p
--    where p.prosrc ~ 'ministry_finance_access|ministry_giving_access|ministry_finance_guard|church_giving_open'
--   union all
--   select 'view', schemaname || '.' || viewname, viewowner
--     from pg_views where definition ~ 'ministry_finance_access|ministry_giving_access|ministry_finance_guard|church_giving_open'
--   union all
--   select 'matview', schemaname || '.' || matviewname, matviewowner
--     from pg_matviews where definition ~ 'ministry_finance_access|ministry_giving_access|ministry_finance_guard|church_giving_open'
--    order by 1, 2;
--   -- Q4. Owners and RLS. Expected: every table there, rls true, forced
--   --     false, one owner (the same one as Q2's functions and as
--   --     current_user here, or a role current_user may act as).
--   select c.relname, pg_get_userbyid(c.relowner) as owner, c.relrowsecurity as rls, c.relforcerowsecurity as forced,
--          r.rolbypassrls as owner_bypasses, r.rolsuper as owner_super
--     from pg_class c join pg_namespace n on n.oid = c.relnamespace join pg_roles r on r.oid = c.relowner
--    where n.nspname = 'public' and c.relkind = 'r'
--      and c.relname in ('invoices','journal_entries','ledger_entries','plaid_transactions','plaid_accounts',
--                        'customer_ledger','business_expenses','bills','chief_bookkeeping_proposals','events',
--                        'chief_notifications','businesses','business_users','business_collaborators',
--                        'church_keepers','church_area_keys','church_money_holders','church_money_asks')
--    order by 1;
--   select current_user, session_user,
--          (select rolbypassrls from pg_roles where rolname = current_user) as i_bypass_rls;
--   -- Q5. The columns the file names. Expected: eleven rows, each there,
--   --     business_id uuid; then id, business_id, user_id uuid, role and
--   --     status text, joined_at a timestamp.
--   select t.name as table_name, to_regclass('public.' || t.name) is not null as there,
--          (select format_type(a.atttypid, a.atttypmod) from pg_attribute a
--            where a.attrelid = to_regclass('public.' || t.name) and a.attname = 'business_id' and not a.attisdropped) as business_id_type
--     from unnest(array['invoices','journal_entries','ledger_entries','plaid_transactions','plaid_accounts',
--                       'customer_ledger','business_expenses','bills','chief_bookkeeping_proposals',
--                       'events','chief_notifications']) as t(name);
--   select a.attname, format_type(a.atttypid, a.atttypmod) as type
--     from pg_attribute a
--    where a.attrelid = 'public.business_users'::regclass and a.attnum > 0 and not a.attisdropped
--      and a.attname in ('id','business_id','user_id','status','role','joined_at')
--    order by 1;
--   -- Q6. One login with two active seats at one church. Expected: no rows.
--   --     (If there are any, a tick lands on the newest seat.)
--   select business_id, user_id, count(*) as active_seats, array_agg(role order by joined_at) as roles
--     from public.business_users
--    where status = 'active' and user_id is not null
--    group by 1, 2 having count(*) > 1;
--   -- Q7. Nothing long is open (the file waits 5 seconds for a lock, then
--   --     stops). Expected: no rows.
--   select pid, usename, state, now() - xact_start as open_for, left(query, 80) as query
--     from pg_stat_activity
--    where xact_start is not null and pid <> pg_backend_pid() and now() - xact_start > interval '15 seconds'
--    order by xact_start;
begin;

set local lock_timeout = '5s';

-- ─── The two tables ──────────────────────────────────────────────────
create table if not exists public.church_money_asks(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  user_id uuid not null,
  asked_by uuid not null,
  wants jsonb not null,
  status text not null default 'asked',
  asked_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '7 days'),
  reminded_at timestamptz,
  answered_by uuid,
  answered_at timestamptz
);

create table if not exists public.church_money_holders(
  business_id uuid not null references public.businesses(id) on delete cascade,
  user_id uuid not null,
  seat_id uuid not null references public.business_users(id) on delete cascade,
  level text not null default 'see',
  who_gave boolean not null default false,
  bank boolean not null default false,
  granted_by uuid not null,
  granted_at timestamptz not null default now(),
  ask_id uuid references public.church_money_asks(id) on delete set null,
  primary key (business_id, user_id)
);

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'church_money_holders_level'
                 and conrelid = 'public.church_money_holders'::regclass) then
    alter table public.church_money_holders
      add constraint church_money_holders_level check (level in ('see', 'work', 'lead'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_money_asks_status'
                 and conrelid = 'public.church_money_asks'::regclass) then
    alter table public.church_money_asks
      add constraint church_money_asks_status
        check (status in ('asked', 'approved', 'declined', 'expired', 'withdrawn'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_money_asks_not_for_self'
                 and conrelid = 'public.church_money_asks'::regclass) then
    alter table public.church_money_asks
      add constraint church_money_asks_not_for_self check (asked_by <> user_id);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_money_asks_wants'
                 and conrelid = 'public.church_money_asks'::regclass) then
    alter table public.church_money_asks
      add constraint church_money_asks_wants check (
        jsonb_typeof(wants) = 'object'
        and coalesce(wants->>'level', '') in ('see', 'work', 'lead')
        and (not wants ? 'who_gave' or jsonb_typeof(wants->'who_gave') = 'boolean')
        and (not wants ? 'bank' or jsonb_typeof(wants->'bank') = 'boolean')
        and pg_column_size(wants) <= 2048);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_money_asks_answered'
                 and conrelid = 'public.church_money_asks'::regclass) then
    alter table public.church_money_asks
      add constraint church_money_asks_answered
        check (status not in ('approved', 'declined') or (answered_by is not null and answered_at is not null));
  end if;
end $$;

create unique index if not exists church_money_asks_one_open
  on public.church_money_asks(business_id, user_id) where status = 'asked';
create index if not exists church_money_asks_business_at
  on public.church_money_asks(business_id, asked_at desc);
create index if not exists church_money_holders_seat on public.church_money_holders(seat_id);

alter table public.church_money_holders enable row level security;
alter table public.church_money_asks enable row level security;
revoke all on public.church_money_holders from public, anon, authenticated;
revoke all on public.church_money_asks from public, anon, authenticated;
grant all on public.church_money_holders to service_role;
grant all on public.church_money_asks to service_role;

-- ─── The functions the policies read ─────────────────────────────────
-- The businesses the wall stands in front of: the 2026-09-29 type list, as
-- ministry_finance_guard carries it.
create or replace function public.ministry_finance_walled(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select exists(select 1 from businesses b where b.id=b_id and
  lower(regexp_replace(trim(coalesce(b.type,'')), '[-[:space:]]+', '_', 'g')) in
    ('ministry','ministries','church','churches','pastor','parachurch','faith','faith_based','religious','religious_org','synagogue','mosque','temple','congregation','nonprofit','non_profit','not_for_profit','nonprofit_org'));
$$;

-- The tick, for the caller. It counts only on the seat it was given to,
-- while that seat is active; 'work' never on a Viewer seat.
create or replace function public.church_money_tick(b_id uuid, part text)
returns boolean language sql stable security definer set search_path=public as $$
 select exists(
  select 1 from church_money_holders h
    join business_users u on u.id=h.seat_id and u.business_id=h.business_id and u.user_id=h.user_id and u.status='active'
   where h.business_id=b_id and h.user_id=auth.uid()
     and case part
          when 'any' then true
          when 'who_gave' then h.who_gave
          when 'bank' then h.bank
          when 'work' then h.level in ('work','lead') and u.role in ('member','manager','admin')
          else false end);
$$;

-- The 2026-09-29 text of ministry_finance_guard with one clause added, the
-- last: "or the caller holds any tick". Running the 2026-09-29 file again
-- takes that clause away.
create or replace function public.ministry_finance_guard(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select exists(select 1 from businesses b where b.id=b_id and
  (lower(regexp_replace(trim(coalesce(b.type,'')), '[-[:space:]]+', '_', 'g')) not in
    ('ministry','ministries','church','churches','pastor','parachurch','faith','faith_based','religious','religious_org','synagogue','mosque','temple','congregation','nonprofit','non_profit','not_for_profit','nonprofit_org')
   or public.ministry_finance_access(b_id) or public.church_money_tick(b_id, 'any')));
$$;

-- Who may see who gave. Replaced only while the Giving keeper's function
-- exists: if APPLY-2026-10-27-church-keys-gift-rows.sql has been rolled
-- back, the gift rows read ministry_finance_access and there is nothing here
-- to replace. Running that file again resets this to its narrow body.
do $$
begin
  if to_regprocedure('public.church_giving_open(uuid)') is not null then
    execute $f$
create or replace function public.ministry_giving_access(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $body$
 select (public.ministry_finance_access(b_id) or public.church_money_tick(b_id, 'who_gave'))
    and public.church_giving_open(b_id);
$body$;
    $f$;
  end if;
end $$;

create or replace function public.ministry_finance_write_guard(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select exists(select 1 from businesses b where b.id=b_id and
  (lower(regexp_replace(trim(coalesce(b.type,'')), '[-[:space:]]+', '_', 'g')) not in
    ('ministry','ministries','church','churches','pastor','parachurch','faith','faith_based','religious','religious_org','synagogue','mosque','temple','congregation','nonprofit','non_profit','not_for_profit','nonprofit_org')
   or public.ministry_finance_access(b_id) or public.church_money_tick(b_id, 'work')));
$$;

create or replace function public.ministry_finance_bank_guard(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select exists(select 1 from businesses b where b.id=b_id and
  (lower(regexp_replace(trim(coalesce(b.type,'')), '[-[:space:]]+', '_', 'g')) not in
    ('ministry','ministries','church','churches','pastor','parachurch','faith','faith_based','religious','religious_org','synagogue','mosque','temple','congregation','nonprofit','non_profit','not_for_profit','nonprofit_org')
   or public.ministry_finance_access(b_id) or public.church_money_tick(b_id, 'bank')));
$$;

-- May change a giving event or a gift alert. It asks ministry_giving_access
-- by name at run time, so it still answers (narrowly) when the 2026-10-27
-- file has been rolled back and that function is gone.
create or replace function public.church_money_giving_write(b_id uuid)
returns boolean language plpgsql stable security definer set search_path=public as $$
declare
  v_sees boolean;
begin
  if to_regprocedure('public.ministry_giving_access(uuid)') is null then
    return public.ministry_finance_access(b_id);
  end if;
  execute 'select public.ministry_giving_access($1)' into v_sees using b_id;
  return coalesce(v_sees, false)
     and (public.ministry_finance_access(b_id) or public.church_money_tick(b_id, 'work'));
end $$;

-- The policies call the guards as the browser's role; the tick and the type
-- list run inside them, as their owner.
revoke all on function public.ministry_finance_walled(uuid), public.church_money_tick(uuid, text)
  from public, anon, authenticated;
grant execute on function public.ministry_finance_walled(uuid), public.church_money_tick(uuid, text)
  to service_role;
revoke all on function public.ministry_finance_write_guard(uuid), public.ministry_finance_bank_guard(uuid),
  public.church_money_giving_write(uuid) from public, anon;
grant execute on function public.ministry_finance_write_guard(uuid), public.ministry_finance_bank_guard(uuid),
  public.church_money_giving_write(uuid) to authenticated, service_role;

-- ─── The owner's yes, written only by the server ─────────────────────
-- Not SECURITY DEFINER: the service role reads and writes these tables
-- itself, and a role that was ever handed EXECUTE by mistake still could not
-- touch a row.
create or replace function public.church_money_grant(
  p_business uuid, p_user uuid, p_level text, p_who_gave boolean, p_bank boolean, p_by uuid,
  p_ask uuid default null)
returns jsonb language plpgsql set search_path=public as $$
declare
  v_owner uuid;
  v_seat uuid;
  v_role text;
  v_row public.church_money_holders;
begin
  select b.owner_id into v_owner from public.businesses b where b.id = p_business;
  if v_owner is null or p_by is null or v_owner <> p_by then
    raise exception 'church_money: only the owner gives giving access' using errcode = '42501';
  end if;
  if p_user is null or p_user = v_owner then
    raise exception 'church_money: the owner holds giving already' using errcode = '22023';
  end if;
  if p_level is null then
    delete from public.church_money_holders where business_id = p_business and user_id = p_user;
    return jsonb_build_object('ok', true, 'holder', null);
  end if;
  if p_level not in ('see', 'work', 'lead') then
    raise exception 'church_money: level is see, work or lead' using errcode = '22023';
  end if;
  if not public.ministry_finance_walled(p_business) then
    raise exception 'church_money: not a church or nonprofit' using errcode = '22023';
  end if;
  if p_ask is not null and not exists (select 1 from public.church_money_asks a
       where a.id = p_ask and a.business_id = p_business and a.user_id = p_user) then
    raise exception 'church_money: that ask is not for this person at this church' using errcode = '22023';
  end if;
  select u.id, u.role into v_seat, v_role from public.business_users u
   where u.business_id = p_business and u.user_id = p_user and u.status = 'active'
   order by u.joined_at desc nulls last, u.id limit 1;
  if v_seat is null then
    raise exception 'church_money: no active login for that person' using errcode = '22023';
  end if;
  if v_role = 'viewer' and p_level <> 'see' then
    raise exception 'church_money: a Viewer login can only see' using errcode = '22023';
  end if;
  insert into public.church_money_holders as h
    (business_id, user_id, seat_id, level, who_gave, bank, granted_by, granted_at, ask_id)
  values (p_business, p_user, v_seat, p_level, coalesce(p_who_gave, false), coalesce(p_bank, false), p_by,
          clock_timestamp(), p_ask)
  on conflict (business_id, user_id) do update
    set seat_id = excluded.seat_id, level = excluded.level, who_gave = excluded.who_gave, bank = excluded.bank,
        granted_by = excluded.granted_by, granted_at = excluded.granted_at, ask_id = excluded.ask_id
  returning h.* into v_row;
  return jsonb_build_object('ok', true, 'holder', to_jsonb(v_row));
end $$;

-- The owner's yes or no. An ask that ran out is marked expired and said so
-- ('ok' false), never answered.
create or replace function public.church_money_answer(p_ask uuid, p_yes boolean, p_by uuid)
returns jsonb language plpgsql set search_path=public as $$
declare
  a public.church_money_asks;
  v_owner uuid;
  v_out jsonb := null;
begin
  select * into a from public.church_money_asks where id = p_ask for update;
  if not found then
    raise exception 'church_money: no such ask' using errcode = 'P0002';
  end if;
  select b.owner_id into v_owner from public.businesses b where b.id = a.business_id;
  if v_owner is null or p_by is null or v_owner <> p_by then
    raise exception 'church_money: only the owner answers an ask' using errcode = '42501';
  end if;
  if a.status <> 'asked' then
    raise exception 'church_money: that ask was already %', a.status using errcode = '22023';
  end if;
  if a.asked_by = a.user_id then
    raise exception 'church_money: nobody asks for their own access' using errcode = '22023';
  end if;
  if a.expires_at <= now() then
    update public.church_money_asks set status = 'expired' where id = a.id;
    return jsonb_build_object('ok', false, 'status', 'expired', 'holder', null);
  end if;
  if p_yes is true then
    v_out := public.church_money_grant(a.business_id, a.user_id, a.wants->>'level',
                                       coalesce((a.wants->>'who_gave')::boolean, false),
                                       coalesce((a.wants->>'bank')::boolean, false), p_by, a.id);
  end if;
  update public.church_money_asks
     set status = case when p_yes is true then 'approved' else 'declined' end,
         answered_by = p_by, answered_at = clock_timestamp()
   where id = a.id;
  return jsonb_build_object('ok', true, 'status', case when p_yes is true then 'approved' else 'declined' end,
                            'holder', v_out->'holder');
end $$;

-- Opens an ask. Who may ask is the server's to decide before it calls this;
-- here: a church or nonprofit, a person with an active login who is not the
-- owner, never for yourself, and one open ask a login. An ask that ran out
-- is marked expired first, so it does not hold the place of a new one.
create or replace function public.church_money_ask(
  p_business uuid, p_user uuid, p_by uuid, p_level text, p_who_gave boolean, p_bank boolean)
returns jsonb language plpgsql set search_path=public as $$
declare
  v_owner uuid;
  v_role text;
  v_row public.church_money_asks;
begin
  select b.owner_id into v_owner from public.businesses b where b.id = p_business;
  if v_owner is null then
    raise exception 'church_money: no such church' using errcode = 'P0002';
  end if;
  if not public.ministry_finance_walled(p_business) then
    raise exception 'church_money: not a church or nonprofit' using errcode = '22023';
  end if;
  if p_by is null or p_user is null or p_by = p_user then
    raise exception 'church_money: nobody asks for their own access' using errcode = '22023';
  end if;
  if p_user = v_owner then
    raise exception 'church_money: the owner holds giving already' using errcode = '22023';
  end if;
  if p_level is null or p_level not in ('see', 'work', 'lead') then
    raise exception 'church_money: level is see, work or lead' using errcode = '22023';
  end if;
  select u.role into v_role from public.business_users u
   where u.business_id = p_business and u.user_id = p_user and u.status = 'active'
   order by u.joined_at desc nulls last, u.id limit 1;
  if v_role is null then
    raise exception 'church_money: no active login for that person' using errcode = '22023';
  end if;
  if v_role = 'viewer' and p_level <> 'see' then
    raise exception 'church_money: a Viewer login can only see' using errcode = '22023';
  end if;
  update public.church_money_asks set status = 'expired'
   where business_id = p_business and user_id = p_user and status = 'asked' and expires_at <= now();
  insert into public.church_money_asks(business_id, user_id, asked_by, wants)
  values (p_business, p_user, p_by,
          jsonb_build_object('level', p_level, 'who_gave', coalesce(p_who_gave, false), 'bank', coalesce(p_bank, false)))
  returning * into v_row;
  return jsonb_build_object('ok', true, 'ask', to_jsonb(v_row));
end $$;

revoke all on function public.church_money_grant(uuid, uuid, text, boolean, boolean, uuid, uuid),
  public.church_money_answer(uuid, boolean, uuid),
  public.church_money_ask(uuid, uuid, uuid, text, boolean, boolean) from public, anon, authenticated;
grant execute on function public.church_money_grant(uuid, uuid, text, boolean, boolean, uuid, uuid),
  public.church_money_answer(uuid, boolean, uuid),
  public.church_money_ask(uuid, uuid, uuid, text, boolean, boolean) to service_role;

-- ─── The policies: added, restrictive, nothing existing touched ──────
do $$ declare t text; begin
 foreach t in array array['invoices','journal_entries','ledger_entries','plaid_transactions','plaid_accounts','customer_ledger','business_expenses','bills','chief_bookkeeping_proposals','events','chief_notifications'] loop
  if to_regclass('public.'||t) is null then
   raise exception 'church_money: public.% is missing; nothing was applied', t;
  end if;
 end loop;
 foreach t in array array['invoices','journal_entries','ledger_entries','plaid_transactions','plaid_accounts','customer_ledger','business_expenses','bills','chief_bookkeeping_proposals'] loop
  execute format('drop policy if exists ministry_financial_write_insert on public.%I', t);
  execute format('create policy ministry_financial_write_insert on public.%I as restrictive for insert to authenticated with check (public.ministry_finance_write_guard(business_id))', t);
  execute format('drop policy if exists ministry_financial_write_update on public.%I', t);
  execute format('create policy ministry_financial_write_update on public.%I as restrictive for update to authenticated using (public.ministry_finance_write_guard(business_id)) with check (public.ministry_finance_write_guard(business_id))', t);
  execute format('drop policy if exists ministry_financial_write_delete on public.%I', t);
  execute format('create policy ministry_financial_write_delete on public.%I as restrictive for delete to authenticated using (public.ministry_finance_write_guard(business_id))', t);
 end loop;
 foreach t in array array['plaid_transactions','plaid_accounts'] loop
  execute format('drop policy if exists church_money_bank on public.%I', t);
  execute format('create policy church_money_bank on public.%I as restrictive for all to authenticated using (public.ministry_finance_bank_guard(business_id)) with check (public.ministry_finance_bank_guard(business_id))', t);
 end loop;
end $$;

-- The money rows in events and in the bell: the same two kinds the
-- SELECT-only policies hide (2026-09-29, 2026-10-27), now for changing and
-- deleting as well.
drop policy if exists church_money_event_update on public.events;
create policy church_money_event_update on public.events as restrictive for update to authenticated
 using(case when event_type ~ '^giving' then public.church_money_giving_write(business_id)
  when event_type ~ '^(invoice|payment)' then public.ministry_finance_write_guard(business_id) else true end)
 with check(case when event_type ~ '^giving' then public.church_money_giving_write(business_id)
  when event_type ~ '^(invoice|payment)' then public.ministry_finance_write_guard(business_id) else true end);
drop policy if exists church_money_event_delete on public.events;
create policy church_money_event_delete on public.events as restrictive for delete to authenticated
 using(case when event_type ~ '^giving' then public.church_money_giving_write(business_id)
  when event_type ~ '^(invoice|payment)' then public.ministry_finance_write_guard(business_id) else true end);
drop policy if exists church_money_alert_update on public.chief_notifications;
create policy church_money_alert_update on public.chief_notifications as restrictive for update to authenticated
 using(case when data->>'kind' in ('gift_received','recurring_gift_ended') then public.church_money_giving_write(business_id)
  when data->>'kind'='invoice_paid' then public.ministry_finance_write_guard(business_id) else true end)
 with check(case when data->>'kind' in ('gift_received','recurring_gift_ended') then public.church_money_giving_write(business_id)
  when data->>'kind'='invoice_paid' then public.ministry_finance_write_guard(business_id) else true end);
drop policy if exists church_money_alert_delete on public.chief_notifications;
create policy church_money_alert_delete on public.chief_notifications as restrictive for delete to authenticated
 using(case when data->>'kind' in ('gift_received','recurring_gift_ended') then public.church_money_giving_write(business_id)
  when data->>'kind'='invoice_paid' then public.ministry_finance_write_guard(business_id) else true end);

commit;

notify pgrst, 'reload schema';

-- Check:
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('anon', c.oid, 'select') as anon_reads
--     from pg_class c
--    where c.oid in ('public.church_money_holders'::regclass, 'public.church_money_asks'::regclass)
--    order by 1;
--   -- 2 rows: each true, 0, false, false
--   select policyname, cmd, permissive, count(*) from pg_policies
--    where schemaname = 'public'
--      and (policyname like 'ministry_financial_%' or policyname like 'church_money_%'
--           or policyname in ('church_giving_bank', 'gift_row_privacy'))
--    group by 1, 2, 3 order by 1;
--   -- church_giving_bank ALL RESTRICTIVE 2; church_money_alert_delete DELETE RESTRICTIVE 1;
--   -- church_money_alert_update UPDATE RESTRICTIVE 1; church_money_bank ALL RESTRICTIVE 2;
--   -- church_money_event_delete DELETE RESTRICTIVE 1; church_money_event_update UPDATE RESTRICTIVE 1;
--   -- gift_row_privacy ALL RESTRICTIVE 1; ministry_financial_events SELECT RESTRICTIVE 1;
--   -- ministry_financial_notifications SELECT RESTRICTIVE 1; ministry_financial_privacy ALL RESTRICTIVE 9;
--   -- ministry_financial_write_delete DELETE RESTRICTIVE 9; _insert INSERT RESTRICTIVE 9;
--   -- _update UPDATE RESTRICTIVE 9
--   select p.proname, p.prosecdef, p.proconfig,
--          has_function_privilege('authenticated', p.oid, 'execute') as browser_runs,
--          has_function_privilege('anon', p.oid, 'execute') as anon_runs
--     from pg_proc p join pg_namespace n on n.oid = p.pronamespace
--    where n.nspname = 'public'
--      and p.proname in ('ministry_finance_walled', 'church_money_tick', 'ministry_finance_access',
--                        'ministry_finance_guard', 'ministry_giving_access', 'ministry_finance_write_guard',
--                        'ministry_finance_bank_guard', 'church_money_giving_write', 'church_money_grant',
--                        'church_money_answer', 'church_money_ask')
--    order by 1;
--   -- 11 rows, each with search_path=public and anon_runs false.
--   -- browser_runs true for: ministry_finance_access, ministry_finance_guard, ministry_giving_access,
--   --   ministry_finance_write_guard, ministry_finance_bank_guard, church_money_giving_write.
--   -- browser_runs false for: ministry_finance_walled, church_money_tick, church_money_grant,
--   --   church_money_answer, church_money_ask.
--   -- prosecdef true for all but church_money_grant, church_money_answer and church_money_ask.
--   select md5(btrim(regexp_replace(prosrc, '[[:space:]]+', ' ', 'g'))) from pg_proc
--    where oid = 'public.ministry_finance_access(uuid)'::regprocedure;
--   -- unchanged from Q2: this file does not touch it
--   select count(*) from public.church_money_holders;
--   -- 0  (and while it is 0, nothing has changed but the one narrowing the header names)
