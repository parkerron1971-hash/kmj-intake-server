-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-08-10 — business-documents and proposals stop being public
--
-- Step 3, after the write lockdown (#473) and two frontend changes.
-- Writes were closed on 2026-08-09; READS stayed open, deliberately,
-- because closing them would have broken things that were still using
-- public URLs. Those are now gone:
--
--   FE #455  every practitioner-facing read of their own documents goes
--            through a short-lived signed URL, and an events row that
--            persisted a permanent public_url no longer does
--   FE #456  a digital product's file moved to its own delivery bucket,
--            and DocumentRecord.publicUrl was deleted with its last
--            consumer
--
-- So nothing in the app mints a permanent unauthenticated link into
-- these buckets any more, and the read can close.
--
-- WHAT THE READ POLICY HAS TO BE
--
-- Not "drop the public one and stop". createSignedUrl asks Postgres for
-- SELECT on the object before it will sign anything, so a bucket with no
-- select policy at all cannot be read even by its owner — the panel
-- would go blank and it would look like the files had been deleted.
-- Owner-scoped SELECT replaces public SELECT; it does not merely remove
-- it.
--
-- product-files is created here as the deliberate opposite: public to
-- FETCH, because a buyer clicks that link from an email months later
-- with nobody signed in, and NOT listable, because there is no select
-- policy on it. A stranger can retrieve a file whose exact path they
-- already know and cannot discover any others.
--
-- Safe to re-run.
-- ══════════════════════════════════════════════════════════════════


-- ── The delivery bucket ────────────────────────────────────────────
insert into storage.buckets (id, name, public)
values ('product-files', 'product-files', true)
on conflict (id) do update set public = true;

-- Writes only, and only by someone who can act for the business named
-- in the path. Reads deliberately have NO policy: the public-object
-- route does not consult RLS, and listing does — which is exactly the
-- split we want.
drop policy if exists "product-files insert" on storage.objects;
create policy "product-files insert" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'product-files'
              and public.user_can_access_business(public.storage_business_id(name)));

drop policy if exists "product-files update" on storage.objects;
create policy "product-files update" on storage.objects
  for update to authenticated
  using (bucket_id = 'product-files'
         and public.user_can_access_business(public.storage_business_id(name)))
  with check (bucket_id = 'product-files'
              and public.user_can_access_business(public.storage_business_id(name)));

drop policy if exists "product-files delete" on storage.objects;
create policy "product-files delete" on storage.objects
  for delete to authenticated
  using (bucket_id = 'product-files'
         and public.user_can_access_business(public.storage_business_id(name)));


-- ── Close the two that hold client records ─────────────────────────
update storage.buckets set public = false
 where id in ('business-documents', 'proposals');

drop policy if exists "Allow public read business-documents" on storage.objects;
drop policy if exists "Allow public read proposals"          on storage.objects;

create policy "biz read: business-documents" on storage.objects
  for select to authenticated
  using (bucket_id = 'business-documents'
         and public.user_can_access_business(public.storage_business_id(name)));

create policy "biz read: proposals" on storage.objects
  for select to authenticated
  using (bucket_id = 'proposals'
         and public.user_can_access_business(public.storage_business_id(name)));
