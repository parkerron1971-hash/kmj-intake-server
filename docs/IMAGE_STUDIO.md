# Image Studio release

Chief can create and refine business images through ordinary chat or the dedicated creative workspace. Both use the same private originals and server `OPENAI_API_KEY` already used by voice. Reference inputs are owned artwork IDs, never arbitrary fetch URLs.

## Enable

1. Merge the backend release.
2. Apply `supabase/APPLY-2026-09-08-image-studio.sql` and `supabase/APPLY-2026-09-08-conversation-desk.sql` for a new installation. Existing installations use the repeatable `supabase/APPLY-2026-09-09-image-upload-policy.sql` correction. All three are applied in production as of 2026-09-09 UTC; owner storage insertion and gallery/conversation reads were verified in a rollback-only transaction. Do not rerun the original setup over an existing installation: its initial policies are created once.
3. Confirm the deployed OpenAI project has access to `gpt-image-2.5-sunburst`. The API also allows `gpt-image-2.5-flare`; there is no silent model downgrade. Account access has not been tested with a paid generation.
4. Release the paired frontend, then smoke-test one requested image, a reference edit, gallery reload, and download under an authenticated business owner. Test publishing only to an explicitly chosen destination.

## Cost controls

High quality is the default. The server exposes quality credits through authenticated `GET /ai/images/config`. Opening credit prices use the existing hero regeneration baseline: low 7, medium 15, high 30, xhigh 60, max 90 when `PRICE_HERO_REGEN` is 30. Override with `PRICE_IMAGE_LOW`, `PRICE_IMAGE_MEDIUM`, `PRICE_IMAGE_HIGH`, `PRICE_IMAGE_XHIGH`, and `PRICE_IMAGE_MAX`.

Product credits are distinct from provider USD charges. Actual model usage is saved and logged using the published standard token rates recorded on 2026-09-08: text input $5, cached text $1.25, image input $8, cached image $2, image output $30 per million tokens. Costs vary with image size, quality and references; there is no fixed API-call price. Sources: [image generation guide](https://developers.openai.com/api/docs/guides/image-generation) and [API pricing](https://developers.openai.com/api/docs/pricing).

The database serializes reservations per business, limits generation to 20 jobs per day, and protects repeated request IDs. A worker must claim a queued job before contacting OpenAI. Transport fallback preserves the request ID. Interrupted paid jobs are reported without automatic regeneration.

## Storage and destinations

Originals remain in the private `image-originals` bucket with expiring signed previews. Uploads accept PNG/JPEG/WebP, up to 20 MB and 25 megapixels, and are normalized before storage. All writes check the business owner. Clients cannot mark a generation complete or replace billing records.

Account export includes image and publication records for the owner's archive. Generic import skips them because paid job state, publication claims and original private storage paths cannot be restored safely to a new business. Originals can be downloaded from the gallery; account deletion includes the private image bucket.

Publishing prepares a public JPEG delivery copy, disclosed in the UI, and hands off to existing website News or connected Facebook/Instagram publishing. Other apps use native sharing or download. Saving artwork does not publish it. Publication request IDs prevent repeat submission; partial Facebook/Instagram results are shown as partial.

## Verification

`python -m pytest __tests__/test_image_studio.py __tests__/test_action_registry.py -q`

`node scripts/image-studio-db-check.mjs` exercises the migration in PGlite. Install `@electric-sql/pglite` in a disposable test directory and set `PGLITE_MODULE` to its absolute file URL, or make the package available to Node. It verifies ownership, private storage, server-only status, daily limits, idempotency, atomic drafts and publication claims without connecting to production.
