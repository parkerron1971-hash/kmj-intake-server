-- Church duties, step 1 (church_duties.py, docs/CHURCH_DUTIES.md; Kevin
-- 2026-11-01: "allows for a general structure plan and customize roles as
-- well ... yes the duties part would be great"). A duty is one job an office
-- login does: the weekly text, the Monday leaders note, the books. A church
-- starts from its lanes' defaults (in the code, nothing here) and moves a
-- duty one at a time. Two tables and one function, server-only (RLS on, no
-- policies, browser roles revoked); church_duties.py reads and writes them.
--
--   church_duty_holders   who a church moved a duty to: one row a login a
--                         duty, with who gave it and when. A duty with no
--                         row follows the lanes' defaults; once any row
--                         names who does it, only those rows decide.
--   church_duty_changes   every move: from and to (the user ids, or null for
--                         the lanes' defaults), by whom and when. An undo is a
--                         change too (undoes = the one it put back, which
--                         gets undone_at).
--   church_duty_set()     one move in one transaction: the holders it no
--                         longer names go, the new ones come, the log row is
--                         written, and an undo marks what it put back.
--
-- A login that's deleted takes its rows with it (the log keeps the move,
-- with no one named as the mover). A church that goes takes everything.
-- Additive, idempotent, and nothing here drops anything.
begin;

create table if not exists public.church_duty_holders(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  duty text not null check (duty ~ '^[a-z][a-z0-9_]{1,39}$'),
  user_id uuid not null references auth.users(id) on delete cascade,
  given_by uuid references auth.users(id) on delete set null,
  given_at timestamptz not null default now(),
  constraint church_duty_holders_one unique (business_id, duty, user_id)
);

create table if not exists public.church_duty_changes(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  duty text not null check (duty ~ '^[a-z][a-z0-9_]{1,39}$'),
  from_holders jsonb check (from_holders is null or jsonb_typeof(from_holders) = 'array'),
  to_holders jsonb check (to_holders is null or jsonb_typeof(to_holders) = 'array'),
  changed_by uuid references auth.users(id) on delete set null,
  changed_at timestamptz not null default now(),
  undoes uuid references public.church_duty_changes(id) on delete set null,
  undone_at timestamptz
);

create index if not exists church_duty_changes_last
  on public.church_duty_changes(business_id, duty, changed_at desc);

create or replace function public.church_duty_set(
  p_business_id uuid, p_duty text, p_user_ids uuid[], p_by uuid, p_undoes uuid default null)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_to uuid[] := array(select distinct u from unnest(coalesce(p_user_ids, '{}'::uuid[])) as u
                       where u is not null order by u);
  v_from jsonb;
  v_row public.church_duty_changes;
begin
  -- One move at a time for a duty, so each log row's "from" is what it replaced.
  perform pg_advisory_xact_lock(hashtextextended('church_duty:' || p_business_id::text || ':' || p_duty, 0));
  select jsonb_agg(h.user_id::text order by h.user_id) into v_from
    from public.church_duty_holders h where h.business_id = p_business_id and h.duty = p_duty;
  if p_undoes is not null then
    update public.church_duty_changes c set undone_at = clock_timestamp()
     where c.id = p_undoes and c.business_id = p_business_id and c.duty = p_duty
       and c.undoes is null and c.undone_at is null;
    if not found then
      raise exception 'That change was already put back';
    end if;
  end if;
  delete from public.church_duty_holders h
   where h.business_id = p_business_id and h.duty = p_duty and not (h.user_id = any(v_to));
  insert into public.church_duty_holders(business_id, duty, user_id, given_by)
    select p_business_id, p_duty, u, p_by from unnest(v_to) as u
    on conflict (business_id, duty, user_id) do nothing;
  insert into public.church_duty_changes(business_id, duty, from_holders, to_holders, changed_by, changed_at, undoes)
    values (p_business_id, p_duty, v_from,
            case when cardinality(v_to) = 0 then null
                 else (select jsonb_agg(u::text order by u) from unnest(v_to) as u) end,
            p_by, clock_timestamp(), p_undoes)
    returning * into v_row;
  return to_jsonb(v_row);
end $$;
revoke all on function public.church_duty_set(uuid, text, uuid[], uuid, uuid) from public, anon, authenticated;
grant execute on function public.church_duty_set(uuid, text, uuid[], uuid, uuid) to service_role;

alter table public.church_duty_holders enable row level security;
alter table public.church_duty_changes enable row level security;
revoke all on public.church_duty_holders from anon, authenticated;
revoke all on public.church_duty_changes from anon, authenticated;
grant all on public.church_duty_holders to service_role;
grant all on public.church_duty_changes to service_role;

commit;

-- Check after applying (both tables, RLS on, no policies, the function only
-- the server can run, nothing moved yet):
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads
--     from pg_class c where c.relname in ('church_duty_holders', 'church_duty_changes');
--   select has_function_privilege('authenticated', 'public.church_duty_set(uuid, text, uuid[], uuid, uuid)', 'execute');
--   select count(*) from public.church_duty_holders;   -- 0 until a church moves a duty
