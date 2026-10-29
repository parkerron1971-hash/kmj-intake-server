-- Money levels for check requests (church_money_levels.py). Kevin
-- 2026-10-23 ("Church Areas and Keys", moving money: approval levels by
-- amount) and 2026-10-26 ("go with your picks"): under $500 the treasurer
-- alone, $500 to $2,500 the pastor too, over $2,500 a board member too;
-- 2026-10-28: "change check requests yourself". One table, server-only like
-- the requests (RLS on, no policies, browser roles revoked):
--
--   church_check_approvals   each yes a request has: the request, its church,
--                            the step it gives (treasurer, pastor, board), the
--                            login that gave it, and when. One yes a step and
--                            one step a person, so two steps never come from
--                            the same login
--
-- A yes belongs to its request's church (checked by a trigger). A request
-- that goes takes its yeses with it. Idempotent, and nothing here drops
-- anything.
begin;

create table if not exists public.church_check_approvals(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  request_id uuid not null references public.church_check_requests(id) on delete cascade,
  step text not null check (step in ('treasurer', 'pastor', 'board')),
  user_id uuid not null,
  created_at timestamptz not null default now(),
  constraint church_check_approvals_one_a_step unique (request_id, step),
  constraint church_check_approvals_one_a_person unique (request_id, user_id)
);

-- A yes is on its own church's request, whatever the caller passes.
create or replace function public.church_check_approval_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (
      select 1 from public.church_check_requests r where r.id = new.request_id and r.business_id = new.business_id) then
    raise exception 'That request is not in this church';
  end if;
  return new;
end $$;
create or replace trigger church_check_approval_same_business
  before insert or update of request_id, business_id
  on public.church_check_approvals for each row execute function public.church_check_approval_same_business();
revoke all on function public.church_check_approval_same_business() from public, anon, authenticated;

alter table public.church_check_approvals enable row level security;
revoke all on public.church_check_approvals from anon, authenticated;
grant all on public.church_check_approvals to service_role;

commit;

-- Check after applying (RLS on, no policies, both unique rules, the trigger):
--   select c.relrowsecurity,
--          (select count(*) from pg_policies p where p.tablename = 'church_check_approvals') as policies,
--          (select count(*) from pg_constraint k where k.conrelid = c.oid and k.contype = 'u') as unique_rules,
--          (select count(*) from pg_trigger t where t.tgrelid = c.oid and not t.tgisinternal) as triggers
--     from pg_class c where c.relname = 'church_check_approvals';
