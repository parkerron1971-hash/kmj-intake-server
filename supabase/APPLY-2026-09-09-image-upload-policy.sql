-- The correlated subquery must reference the storage object's path explicitly.
-- Unqualified "name" resolves to businesses.name inside that subquery.
BEGIN;
DROP POLICY IF EXISTS image_originals_owner ON storage.objects;
CREATE POLICY image_originals_owner ON storage.objects FOR ALL TO authenticated
 USING(bucket_id='image-originals' AND EXISTS(
   SELECT 1 FROM public.businesses b
   WHERE b.id::text=(storage.foldername(storage.objects.name))[1]
     AND b.owner_id=auth.uid()
 ))
 WITH CHECK(bucket_id='image-originals' AND EXISTS(
   SELECT 1 FROM public.businesses b
   WHERE b.id::text=(storage.foldername(storage.objects.name))[1]
     AND b.owner_id=auth.uid()
 ));
NOTIFY pgrst, 'reload schema';
COMMIT;
