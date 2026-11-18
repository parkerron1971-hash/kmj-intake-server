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
-- adds a fourth: an active office login the owner has ticked. NOTHING reads
-- the tick on the server yet (church_money_gate, the next PR, behind a
-- switch), and with no row in church_money_holders every answer below is the
-- answer it was. Apply with zero holders.
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
-- FUNCTIONS (each SECURITY DEFINER with a fixed search_path; each reads only
-- businesses, business_users, business_collaborators and
-- church_money_holders, none of which has a policy that calls any of them:
-- nothing here can recurse, docs/RLS_MODEL.md, the 42P17 rule)
--   ministry_finance_base(b)        NEW. The 2026-09-29 body of
--                                   ministry_finance_access, word for word:
--                                   owner, active Admin seat, active
--                                   accountant
--   ministry_finance_walled(b)      NEW. The business is one the money wall
--                                   stands in front of (the 2026-09-29 type
--                                   list, the same one ministry_finance_guard
--                                   carries)
--   church_money_tick(b, part)      NEW. The caller holds the tick for
--                                   `part` on an ACTIVE seat: 'any' (a row),
--                                   'who_gave', 'bank', 'work' (level work or
--                                   lead AND the seat is not a Viewer)
--   ministry_finance_access(b)      REPLACED: base OR tick('any')
--   ministry_giving_access(b)       REPLACED: (base OR tick('who_gave')) AND
--                                   church_giving_open(b). It was
--                                   ministry_finance_access AND
--                                   church_giving_open (2026-10-27); it does
--                                   NOT take the widened access, or any
--                                   holder would see who gave
--   ministry_finance_write_guard(b) NEW. not walled, OR base, OR tick('work')
--   ministry_finance_bank_guard(b)  NEW. not walled, OR base, OR tick('bank')
--   church_money_grant(...)         NEW, the server's alone. Raises unless
--                                   p_by is the church's owner_id
--   church_money_answer(...)        NEW, the server's alone. The owner's yes
--                                   or no to an ask
--   ministry_finance_guard, church_giving_open and the trigger
--   protect_gift_classification are NOT touched: they call the two replaced
--   functions by name.
--
-- POLICIES. Nothing existing is dropped or changed. Added, all RESTRICTIVE
-- (they only ever narrow):
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
--
-- WITH ZERO HOLDERS THIS IS A NO-OP, object by object. church_money_tick is
-- `exists(... from church_money_holders ...)`, so with no rows it is false
-- for every part and every caller. Then:
--   ministry_finance_access      = base OR false = base, its old body
--   ministry_giving_access       = (base OR false) AND church_giving_open
--                                = its old body (old access = base)
--   ministry_finance_guard       unchanged text over an unchanged answer
--   ministry_finance_write_guard = exists(business AND (not walled OR base))
--                                = ministry_finance_guard, row for row
--   ministry_finance_bank_guard  = the same
--   the three write policies     restrictive policies AND together. Each
--                                write already had to pass
--                                ministry_financial_privacy (USING and WITH
--                                CHECK of ministry_finance_guard, FOR ALL);
--                                it now passes that AND an expression that
--                                is the same value. X AND X = X
--   church_money_bank            the same argument on the two bank tables
--   gift_row_privacy, ministry_financial_events,
--   ministry_financial_notifications, church_giving_bank and the trigger
--                                not touched, over functions that answer as
--                                before
-- So for an owner, an Admin, the accountant, a Manager, a Member, a Viewer
-- and a stranger, every select and every write on every money table answers
-- as it did. __tests__/church_money_holders_db.mjs runs exactly that on a
-- real Postgres, before and after.
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
--   the seat is revoked, or the login is taken off and invited again:
--                                               nothing, at once
--
-- Locks: CREATE POLICY takes a brief ACCESS EXCLUSIVE lock on each of the
-- nine tables (catalog only, no rewrite, no scan); the new tables' foreign
-- keys take a brief SHARE ROW EXCLUSIVE lock on businesses and
-- business_users. lock_timeout stops this file rather than queueing behind a
-- long transaction: run it again.
--
-- One transaction, safe to run twice, nothing dropped that is not made again
-- in the same transaction. Undo: ROLLBACK-2026-11-18-church-money-holders.sql.
-- Instant stop without it: delete from public.church_money_holders;
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
-- The 2026-09-29 body of ministry_finance_access, word for word.
create or replace function public.ministry_finance_base(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select exists(select 1 from businesses b where b.id=b_id and b.owner_id=auth.uid())
 or exists(select 1 from business_users u where u.business_id=b_id and u.user_id=auth.uid() and u.status='active' and u.role='admin')
 or exists(select 1 from business_collaborators c where c.business_id=b_id and c.user_id=auth.uid() and c.status='active' and c.role='accountant');
$$;

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

create or replace function public.ministry_finance_access(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select public.ministry_finance_base(b_id) or public.church_money_tick(b_id, 'any');
$$;

create or replace function public.ministry_giving_access(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select (public.ministry_finance_base(b_id) or public.church_money_tick(b_id, 'who_gave'))
    and public.church_giving_open(b_id);
$$;

create or replace function public.ministry_finance_write_guard(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select exists(select 1 from businesses b where b.id=b_id)
    and (not public.ministry_finance_walled(b_id)
         or public.ministry_finance_base(b_id)
         or public.church_money_tick(b_id, 'work'));
$$;

create or replace function public.ministry_finance_bank_guard(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select exists(select 1 from businesses b where b.id=b_id)
    and (not public.ministry_finance_walled(b_id)
         or public.ministry_finance_base(b_id)
         or public.church_money_tick(b_id, 'bank'));
$$;

-- The policies call the two guards and the two replaced functions as the
-- browser's role; the rest run inside them, as their owner.
revoke all on function public.ministry_finance_base(uuid), public.ministry_finance_walled(uuid),
  public.church_money_tick(uuid, text) from public, anon, authenticated;
grant execute on function public.ministry_finance_base(uuid), public.ministry_finance_walled(uuid),
  public.church_money_tick(uuid, text) to service_role;
revoke all on function public.ministry_finance_write_guard(uuid), public.ministry_finance_bank_guard(uuid)
  from public, anon;
grant execute on function public.ministry_finance_write_guard(uuid), public.ministry_finance_bank_guard(uuid)
  to authenticated, service_role;

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
  if a.expires_at <= now() then
    raise exception 'church_money: that ask ran out' using errcode = '22023';
  end if;
  if a.asked_by = a.user_id then
    raise exception 'church_money: nobody asks for their own access' using errcode = '22023';
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

revoke all on function public.church_money_grant(uuid, uuid, text, boolean, boolean, uuid, uuid),
  public.church_money_answer(uuid, boolean, uuid) from public, anon, authenticated;
grant execute on function public.church_money_grant(uuid, uuid, text, boolean, boolean, uuid, uuid),
  public.church_money_answer(uuid, boolean, uuid) to service_role;

-- ─── The policies: added, restrictive, nothing existing touched ──────
do $$ declare t text; begin
 foreach t in array array['invoices','journal_entries','ledger_entries','plaid_transactions','plaid_accounts','customer_ledger','business_expenses','bills','chief_bookkeeping_proposals'] loop
  if to_regclass('public.'||t) is not null then
   execute format('drop policy if exists ministry_financial_write_insert on public.%I', t);
   execute format('create policy ministry_financial_write_insert on public.%I as restrictive for insert to authenticated with check (public.ministry_finance_write_guard(business_id))', t);
   execute format('drop policy if exists ministry_financial_write_update on public.%I', t);
   execute format('create policy ministry_financial_write_update on public.%I as restrictive for update to authenticated using (public.ministry_finance_write_guard(business_id)) with check (public.ministry_finance_write_guard(business_id))', t);
   execute format('drop policy if exists ministry_financial_write_delete on public.%I', t);
   execute format('create policy ministry_financial_write_delete on public.%I as restrictive for delete to authenticated using (public.ministry_finance_write_guard(business_id))', t);
  end if;
 end loop;
 foreach t in array array['plaid_transactions','plaid_accounts'] loop
  if to_regclass('public.'||t) is not null then
   execute format('drop policy if exists church_money_bank on public.%I', t);
   execute format('create policy church_money_bank on public.%I as restrictive for all to authenticated using (public.ministry_finance_bank_guard(business_id)) with check (public.ministry_finance_bank_guard(business_id))', t);
  end if;
 end loop;
end $$;

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
--      and policyname in ('ministry_financial_privacy', 'ministry_financial_write_insert',
--                         'ministry_financial_write_update', 'ministry_financial_write_delete',
--                         'church_money_bank', 'church_giving_bank', 'gift_row_privacy')
--    group by 1, 2, 3 order by 1;
--   -- church_giving_bank ALL RESTRICTIVE 2; church_money_bank ALL RESTRICTIVE 2;
--   -- gift_row_privacy ALL RESTRICTIVE 1; ministry_financial_privacy ALL RESTRICTIVE 9;
--   -- ministry_financial_write_delete DELETE RESTRICTIVE 9; _insert INSERT RESTRICTIVE 9;
--   -- _update UPDATE RESTRICTIVE 9
--   select p.proname, p.prosecdef, p.proconfig,
--          has_function_privilege('authenticated', p.oid, 'execute') as browser_runs,
--          has_function_privilege('anon', p.oid, 'execute') as anon_runs
--     from pg_proc p join pg_namespace n on n.oid = p.pronamespace
--    where n.nspname = 'public'
--      and p.proname in ('ministry_finance_base', 'ministry_finance_walled', 'church_money_tick',
--                        'ministry_finance_access', 'ministry_giving_access', 'ministry_finance_write_guard',
--                        'ministry_finance_bank_guard', 'church_money_grant', 'church_money_answer')
--    order by 1;
--   -- 9 rows, each with search_path=public and anon_runs false.
--   -- browser_runs true for: ministry_finance_access, ministry_giving_access,
--   --   ministry_finance_write_guard, ministry_finance_bank_guard.
--   -- browser_runs false for: ministry_finance_base, ministry_finance_walled, church_money_tick,
--   --   church_money_grant, church_money_answer.
--   -- prosecdef true for all but church_money_grant and church_money_answer.
--   select count(*) from public.church_money_holders;
--   -- 0  (and while it is 0, nobody's access has changed)
