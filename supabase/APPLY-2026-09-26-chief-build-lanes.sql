-- Chief's background jobs run side by side when they touch different things.
-- (Kevin, Dev Desk 2026-09-26: one message, several pieces of work, "like
-- agents building in the background".)
--
-- Before: one running build per business; the rest waited in line.
-- After:  one running build per business AND lane:
--           site  = workshops, forms with links, events pages (they share the
--                   Events collection, forms and the website)
--           image = flyers
--           plan  = background plans (ordinary Chief actions)
--         A flyer, a plan and a workshop from one message now run at once;
--         two workshops still take turns.
--
-- Replaces chief_build_claim only (same signature, same lease rules), so the
-- server code works before and after this is applied. Replayable.
-- Requires APPLY-2026-09-18-chief-builds.sql.
begin;

create or replace function public.chief_build_lane(p_kind text)
returns text language sql immutable set search_path=public as $$
  select case p_kind when 'flyer' then 'image' when 'plan' then 'plan' else 'site' end
$$;

create or replace function public.chief_build_claim(p_id uuid,p_token uuid)
returns setof public.chief_jobs language plpgsql security definer set search_path=public as $$
declare b uuid; l text;
begin
 select business_id, public.chief_build_lane(params->>'kind') into b, l
   from chief_jobs where id=p_id and kind='build';
 if b is null then return; end if;
 perform pg_advisory_xact_lock(hashtextextended(b::text||':'||l,918));
 -- Serialize builds within a business and lane, including across replicas.
 if exists(select 1 from chief_jobs where business_id=b and kind='build' and id<>p_id
   and status='running' and build_lease_until>now()
   and public.chief_build_lane(params->>'kind')=l) then return; end if;
 return query update chief_jobs set status='running',build_lease_token=p_token,
   build_lease_until=now()+interval '150 seconds',started_at=coalesce(started_at,now())
 where id=p_id and kind='build' and status in ('queued','running')
   and (build_lease_until is null or build_lease_until<now()) returning *;
end $$;

revoke all on function public.chief_build_lane(text) from public,anon,authenticated;
revoke all on function public.chief_build_claim(uuid,uuid) from public,anon,authenticated;
grant execute on function public.chief_build_lane(text),public.chief_build_claim(uuid,uuid) to service_role;
commit;
