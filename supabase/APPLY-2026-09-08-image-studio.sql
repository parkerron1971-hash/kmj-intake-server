-- Private originals; public copies are created only by an explicit publishing request.
create table if not exists public.image_artworks (
 id uuid primary key, business_id uuid not null references public.businesses(id) on delete cascade,
 owner_id uuid not null default auth.uid(), prompt text not null default '',
 model text, quality text, size text, reference_ids jsonb not null default '[]',
 status text not null default 'queued' check (status in ('queued','working','ready','failed')),
 storage_path text, error text, usage jsonb, cost_usd numeric,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index if not exists image_artworks_business_created on public.image_artworks(business_id, created_at desc);
alter table public.image_artworks enable row level security;
create policy image_artworks_owner on public.image_artworks for select to authenticated
 using (exists(select 1 from public.businesses b where b.id=business_id and b.owner_id=auth.uid()));
revoke all on public.image_artworks from anon, authenticated;
grant select on public.image_artworks to authenticated;
grant all on public.image_artworks to service_role;
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
 values ('image-originals','image-originals',false,20971520,array['image/png','image/jpeg','image/webp']) on conflict(id) do nothing;
create policy image_originals_owner on storage.objects for all to authenticated
 using(bucket_id='image-originals' and exists(select 1 from public.businesses b where b.id::text=(storage.foldername(name))[1] and b.owner_id=auth.uid()))
 with check(bucket_id='image-originals' and exists(select 1 from public.businesses b where b.id::text=(storage.foldername(name))[1] and b.owner_id=auth.uid()));

-- Serialize reservations so parallel tabs cannot bypass the daily spend backstop.
create or replace function public.reserve_image_artwork(p_record jsonb, p_daily_limit integer default 20)
returns setof public.image_artworks language plpgsql security definer set search_path=public as $$
declare b uuid := (p_record->>'business_id')::uuid; existing public.image_artworks;
begin
 if not exists(select 1 from businesses where id=b and owner_id=auth.uid()) then raise exception 'Business access denied'; end if;
 perform pg_advisory_xact_lock(hashtextextended(b::text, 819));
 select * into existing from image_artworks where id=(p_record->>'id')::uuid;
 if found then
   if existing.business_id<>b then raise exception 'Image access denied'; end if;
   return next existing; return;
 end if;
 if (select count(*) from image_artworks where business_id=b and model is not null and created_at>=date_trunc('day',now()))>=least(greatest(p_daily_limit,1),20) then
   raise exception 'Daily image limit reached. Try again tomorrow.';
 end if;
 return query insert into image_artworks(id,business_id,prompt,model,quality,size,reference_ids)
 values((p_record->>'id')::uuid,b,p_record->>'prompt',p_record->>'model',p_record->>'quality',p_record->>'size',coalesce(p_record->'reference_ids','[]')) returning *;
end $$;

-- Atomic merge into the EXISTING content calendar, preserving concurrent settings updates.
create or replace function public.prepare_image_post(p_business_id uuid, p_post jsonb)
returns jsonb language plpgsql security invoker set search_path=public as $$
declare s jsonb; c jsonb; posts jsonb; existing jsonb;
begin
 select coalesce(settings,'{}') into s from businesses where id=p_business_id and owner_id=auth.uid() for update;
 if not found then raise exception 'Business access denied'; end if;
 c:=coalesce(s->'content_calendar','{}'); posts:=coalesce(c->'planned_posts','[]');
 select value into existing from jsonb_array_elements(posts) where value->>'id'=p_post->>'id';
 if existing is not null then return existing; end if;
 if exists(select 1 from jsonb_array_elements(coalesce(c->'posted','[]')) where value->>'id'=p_post->>'id') then raise exception 'This post has already been published'; end if;
 c:=jsonb_set(c,'{planned_posts}',posts||jsonb_build_array(p_post));
 update businesses set settings=jsonb_set(s,'{content_calendar}',c) where id=p_business_id;
 return p_post;
end $$;
revoke all on function public.reserve_image_artwork(jsonb,integer) from public;
grant execute on function public.reserve_image_artwork(jsonb,integer) to authenticated;
revoke all on function public.prepare_image_post(uuid,jsonb) from public;
grant execute on function public.prepare_image_post(uuid,jsonb) to authenticated;

create table if not exists public.image_publications (
 id uuid primary key, business_id uuid not null references public.businesses(id) on delete cascade,
 payload jsonb not null, status text not null default 'sending', result jsonb,
 created_at timestamptz not null default now()
);
alter table public.image_publications enable row level security;
create policy image_publications_owner on public.image_publications for select to authenticated
 using(exists(select 1 from public.businesses b where b.id=business_id and b.owner_id=auth.uid()));
revoke all on public.image_publications from anon, authenticated;
grant select on public.image_publications to authenticated;
grant all on public.image_publications to service_role;
create or replace function public.claim_image_publication(p_id uuid,p_business_id uuid,p_payload jsonb)
returns jsonb language plpgsql security definer set search_path=public as $$
declare r public.image_publications;
begin
 if not exists(select 1 from businesses where id=p_business_id and owner_id=auth.uid()) then raise exception 'Business access denied'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_id::text,821));
 select * into r from image_publications where id=p_id;
 if found then
   if r.business_id<>p_business_id or r.payload<>p_payload then raise exception 'Publication request conflicts with an existing request'; end if;
   return jsonb_build_object('claimed',false,'status',r.status,'result',r.result);
 end if;
 insert into image_publications(id,business_id,payload) values(p_id,p_business_id,p_payload);
 return jsonb_build_object('claimed',true);
end $$;
revoke all on function public.claim_image_publication(uuid,uuid,jsonb) from public;
grant execute on function public.claim_image_publication(uuid,uuid,jsonb) to authenticated;
