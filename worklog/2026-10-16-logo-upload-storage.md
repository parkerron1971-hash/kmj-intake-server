---
title: Logo uploads fixed — brand assets and site images write to storage as the service role, confined to the caller's business
date: 2026-10-16
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin uploads a logo and keeps getting 'storage upload failed' … find the cause and fix it fast (KAI brief, Love City Church); then fix Codex's review findings on #1464, and its re-check (legacy build gate, decode-or-refuse)"
status: waiting on Kevin
prs: [kmj-intake-server#1464, solutionist-studio#1238]
migrations: []
left_undone:
  - "Kevin to merge #1464 (then #1238) and re-upload the Love City logo in Brand Studio"
  - "Optional: sweep for any other server-side storage writer that still sends SUPABASE_ANON (none found today besides these two)"
  - "SVG logos are refused, not sanitised; a vetted sanitiser could bring them back if anyone ever needs one (none uploaded to date)"
  - "The drop route's own access helper still answers 403 for a stranger (other routes say 404); left as it was"
  - "Slot upload (/slots/{id}/{slot}/upload) still checks dimensions from the header and stores the declared type; it could use upload_images.verified_image too"
decisions:
  - "Service role, not the user's JWT, for server-side storage writes: the route's assert_access is the access check (same as contract_agent/foundation_agent via storage_links.service_headers)"
  - "With the service role the storage key is the only fence: keys come only from storage_links.business_object_key (canonical business UUID + one plain file name) and both writers refuse anything else before sending"
  - "The DALL-E diagnostic takes only SLOT_DEFINITIONS slot names; generation refuses an unsafe slot name before the paid OpenAI call"
  - "Brand and drop uploads judge the file by its bytes (upload_images.verified_image) and store the MIME/extension found, never the declared one"
  - "Brand route errors: detail stays a plain sentence and a code is added, so either app version shows clean words in either merge order"
  - "Build routes check access on the canonical business id before EITHER engine runs: /director/build-with-loop used to skip it with LEGACY_SITE_ENGINES=1, and /sites/{id}/generate-html had no owner check under the same flag"
  - "A picture is stored only after it decodes, every frame, within a pixel budget (50 MP a frame, 200 frames, 100 MP total); a format this server can't decode (AVIF without libavif) is refused, never taken on its signature"
  - "A JPEG with a multi-picture block (Android Ultra HDR) opens in Pillow as MPO and is accepted as JPEG; round one had refused it"
  - "No database or storage setting changed; the 2026-10-15 dev_desk_service_only policy was ruled out"
related: [2026-10-15-dev-desk-relay.md]
---
Every Brand Studio logo upload had failed for every business since the
2026-08-09 storage write lockdown: `brand_engine._storage_upload` still sent
the anon key, and business-assets' only insert policy is `authenticated` +
business check. Live log: `400 {"statusCode":"403","message":"new row
violates row-level security policy"}`; last `brand/` object 2026-08-05.
`dalle_client._upload_site_image_debug` (site_images: Studio drop photos,
slot uploads) had the same fault. Both now use
`storage_links.service_headers()`; `storage_links.upload_refusal()` gives
plain words for a refused write.

Codex's review then found the service role made the key the only fence,
and `/slots/_diag/dalle` built it from the caller's slot name:
`../<other id>/existing.png#` overwrote another business's file (httpx
normalises the `..`). Reproduced first in `test_storage_path_confinement.py`
(the wire target was the other business's object), then fixed: keys come
from `storage_links.business_object_key`, the writers refuse any other key,
and uploads must be real pictures (`upload_images.py`; SVG refused). Before
building more storage writers, use `business_object_key` and
`service_headers()`, and read both test files.

Codex's re-check confirmed the traversal closed and found two more. With
`LEGACY_SITE_ENGINES=1`, `/director/build-with-loop` built onto any
business id without an access check, and that build fills picture slots
through the service-role image writer; `generate-html` had the same gap.
Both now check access first (`test_legacy_build_access.py`, both flag
settings). `verify()` decodes nothing, so truncated JPEGs were stored and
AVIF was trusted on its signature when Pillow couldn't decode it;
`upload_images` now decodes every frame within a pixel budget and refuses
what it can't decode.
