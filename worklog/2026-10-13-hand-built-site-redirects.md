---
title: Redirects for a hand-built site's old addresses (Love City's SnapPages links)
date: 2026-10-13
agent: Claude Code (Claude Opus 5.5)
asked: "When the domain switches, old SnapPages links will 404: add a redirect map for hand-built sites, and /live to /watch if it can be done safely"
status: in progress
prs: [kmj-intake-server#1410]
migrations: []
left_undone: ["Codex reviews, then Kevin/KAI merge", "After the lovecityc.com cut-over, spot-check a few old links (/what-we-believe, /prayer-request, /live, a /media/ sermon link) on both hosts", "B1 in the domain runbook (http:// on custom domains bounces to a Railway 404) is separate and still open"]
decisions: ["Redirects answer only where a hand-built site would otherwise 404, so they never shadow a page, a hosted door or news", "build.py REDIRECTS -> site_sync validates and stores site_config.manual_redirects; a build without REDIRECTS leaves the row untouched (KMJ)", "Targets are only the site's own pages (optional ?query and #anchor): no open redirects", "'/x/*' covers everything under /x (the old /media sermon library)", "/live goes through an ASGI layer ahead of routing that acts only on an unauthenticated GET/HEAD of /live on a practitioner host whose hand-built site maps it", "A redirect-only change updates the row without a deploy browser check", "/my-love-nation (old members-only page) is left as a 404"]
related: [2026-10-13-love-city-church-site.md, 2026-10-13-hand-built-site-pages.md]
---
A hand-built site can declare `REDIRECTS = {old path: new page}` in its
build.py. site_sync checks each entry (site_page_helpers.clean_redirects:
lowercase paths, never a page, a reserved/API path or a hosted door; target
must be one of the site's own pages), prints any it skips, and stores the rest
as `site_config.manual_redirects`. public_site answers them with a 301 on the
platform subdomain and the custom domain, at the point where the site would
otherwise return its 404, for hand-built sites only. GET /live is an
authenticated API route ahead of the site catch-all, so
`public_site.LegacyApiPathRedirect` (registered in kmj_intake_automation)
checks that one path before routing. It passes everything else through, and
also lets through any request with a bearer token or business_id, any API or
platform host, any site that doesn't map /live, and any failure.

Love City maps 34 old SnapPages addresses plus `/media` and `/media/*`
(sermon share links). Old forms land on the connect card with the same
interest ticked. Tests: test_site_redirects (serving on both hosts, page and
door precedence, composed parity, no open redirect, the /live layer's limits,
KMJ unchanged), plus additions to test_site_page_helpers, test_site_sync and
test_site_love_city.
