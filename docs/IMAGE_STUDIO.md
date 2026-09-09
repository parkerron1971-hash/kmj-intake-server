# Image Studio release

Chief can create and refine business images through ordinary chat or the dedicated creative workspace. Both use the same private originals and server `OPENAI_API_KEY` already used by voice. Generation reference inputs are owned artwork IDs. Public website URLs are handled by a dedicated isolated capture tool, then saved as owned references.

## Enable

1. Merge the backend release.
2. Apply `supabase/APPLY-2026-09-08-image-studio.sql` and `supabase/APPLY-2026-09-08-conversation-desk.sql` for a new installation. Existing installations use the repeatable `supabase/APPLY-2026-09-09-image-upload-policy.sql` correction. All three are applied in production as of 2026-09-09 UTC; owner storage insertion and gallery/conversation reads were verified in a rollback-only transaction. Do not rerun the original setup over an existing installation: its initial policies are created once.
3. Set `OPENAI_IMAGE_MODEL` to an explicitly supported model: `gpt-image-2`, `gpt-image-2.5-sunburst`, or `gpt-image-2.5-flare`. The unset default remains Sunburst. The production key's model endpoint returned 404 for both 2.5 models and 200 for GPT Image 2 on 2026-09-09. Configure GPT Image 2 to use the available model; switch explicitly to 2.5 once the project gains access. New requests check project access before reserving a job, with no automatic model substitution or paid retry.
4. Release the paired frontend, then smoke-test one requested image, a reference edit, gallery reload, and download under an authenticated business owner. Test publishing only to an explicitly chosen destination.

## Cost controls

High quality is the default. The server exposes quality credits through authenticated `GET /ai/images/config`. Opening credit prices use the existing hero regeneration baseline: low 7, medium 15, high 30, xhigh 60, max 90 when `PRICE_HERO_REGEN` is 30. Override with `PRICE_IMAGE_LOW`, `PRICE_IMAGE_MEDIUM`, `PRICE_IMAGE_HIGH`, `PRICE_IMAGE_XHIGH`, and `PRICE_IMAGE_MAX`.

The configuration response also exposes the active model name and supported qualities. GPT Image 2 supports low, medium and high; 2.5 adds xhigh and max. Unsupported quality requests fail before any job reservation. The frontend uses these capabilities for its quality menu and identifies the active model in the composer.

Product credits are distinct from provider USD charges. Actual model usage is saved and logged using the published standard token rates recorded on 2026-09-08: text input $5, cached text $1.25, image input $8, cached image $2, image output $30 per million tokens. Costs vary with image size, quality and references; there is no fixed API-call price. Sources: [image generation guide](https://developers.openai.com/api/docs/guides/image-generation) and [API pricing](https://developers.openai.com/api/docs/pricing).

The database serializes reservations per business, limits generation to 20 jobs per day, and protects repeated request IDs. A worker must claim a queued job before contacting OpenAI. Transport fallback preserves the request ID. Interrupted paid jobs are reported without automatic regeneration.

## Storage and destinations

Originals remain in the private `image-originals` bucket with expiring signed previews. Uploads accept PNG/JPEG/WebP, up to 20 MB and 25 megapixels, and are normalized before storage. All writes check the business owner. Clients cannot mark a generation complete or replace billing records.

Account export includes image and publication records for the owner's archive. Generic import skips them because paid job state, publication claims and original private storage paths cannot be restored safely to a new business. Originals can be downloaded from the gallery; account deletion includes the private image bucket.

Publishing prepares a public JPEG delivery copy, disclosed in the UI, and hands off to existing website News or connected Facebook/Instagram publishing. Other apps use native sharing or download. Saving artwork does not publish it. Publication request IDs prevent repeat submission; partial Facebook/Instagram results are shown as partial.

## Verification

`python -m pytest __tests__/test_image_studio.py __tests__/test_action_registry.py -q`

`node scripts/image-studio-db-check.mjs` exercises the migration in PGlite. Install `@electric-sql/pglite` in a disposable test directory and set `PGLITE_MODULE` to its absolute file URL, or make the package available to Node. It verifies ownership, private storage, server-only status, daily limits, idempotency, atomic drafts and publication claims without connecting to production.


## Website references (2026-09-09)

Chief has a native `capture_website_references` tool (`url`, optional `include_logo`, default true). It captures a 1600x1100 desktop viewport and downloads the best identifiable website logo, preserving raster originals after PNG normalization. Rendered SVG/data logos use an element screenshot and may include the website background. Supply a page path or fragment to target the relevant offer. No model API is called for capture.

The saved images use the existing private gallery contract and appear in ordinary chat and Image Studio. They can be reused through `find_images`. `generate_image` also accepts `website_url` and optional `include_website_logo: false`: capture happens before generation, with role descriptions added to the prompt and real owned IDs supplied to the image API. Current-turn attachments are the fallback when the model omits IDs. There are still at most four generation references; overflow is rejected rather than silently dropping assets. Missing logos or capture failures stop the combined workflow before a paid generation.

Capture performs an owner check first, uses an isolated cookie-free browser, and intercepts every HTTP resource through a DNS-pinned public-IP fetcher. Login pages, non-default ports, private addresses, credentials in URLs, WebSockets, service workers and non-GET requests are blocked. Only public document/style/image/font/script resources load. Some sites that require API-driven rendering or bot challenges will need manual references. TLS verification remains enabled. Limits: 45 seconds, 100 requests, 8 MB per resource, 32 MB total, two simultaneous captures per process, and 40 saved capture assets per business per hour. Same-turn deterministic asset IDs reuse completed captures. Capture assets record zero model-provider cost; hosting/storage and Chief's planning calls are separate.

No migration or frontend deployment is needed. Regression checks:

`python -m pytest __tests__/test_website_image_references.py __tests__/test_image_studio.py __tests__/test_action_registry.py __tests__/test_native_writes.py __tests__/test_tool_loop.py __tests__/test_mcp_writes.py __tests__/test_mcp_server.py -q`
