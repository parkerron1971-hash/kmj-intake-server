---
title: Logo uploads fixed — brand assets and site images write to storage as the service role
date: 2026-10-16
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin uploads a logo and keeps getting 'storage upload failed' … find the cause and fix it fast (KAI brief, Love City Church)"
status: waiting on Kevin
prs: [kmj-intake-server#1464, solutionist-studio#1238]
migrations: []
left_undone:
  - "Kevin to merge #1464 (then #1238) and re-upload the Love City logo in Brand Studio"
  - "Optional: sweep for any other server-side storage writer that still sends SUPABASE_ANON (none found today besides these two)"
decisions:
  - "Service role, not the user's JWT, for server-side storage writes: the route's assert_access is the access check (same as contract_agent/foundation_agent via storage_links.service_headers)"
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
plain words for a refused write. Before building more storage writers,
use `storage_links.service_headers()` and read `test_brand_asset_upload.py`.
