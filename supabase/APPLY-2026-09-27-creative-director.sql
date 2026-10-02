BEGIN;
ALTER TABLE public.image_artworks ADD COLUMN IF NOT EXISTS director jsonb;
CREATE TABLE IF NOT EXISTS public.creative_director_profiles (
 business_id uuid PRIMARY KEY REFERENCES public.businesses(id) ON DELETE CASCADE,
 owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 source_image_id uuid NOT NULL REFERENCES public.image_artworks(id) ON DELETE CASCADE,
 preferences jsonb NOT NULL DEFAULT '{}',
 updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.creative_director_profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.creative_director_profiles FROM anon, authenticated;
GRANT SELECT ON public.creative_director_profiles TO authenticated;
GRANT ALL ON public.creative_director_profiles TO service_role;
DROP POLICY IF EXISTS creative_director_profile_owner ON public.creative_director_profiles;
CREATE POLICY creative_director_profile_owner ON public.creative_director_profiles
 FOR SELECT TO authenticated USING (owner_id=auth.uid() AND EXISTS (
   SELECT 1 FROM public.businesses b WHERE b.id=business_id AND b.owner_id=auth.uid()
 ));
NOTIFY pgrst, 'reload schema';
COMMIT;
