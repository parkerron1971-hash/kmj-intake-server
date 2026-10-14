---
title: Redirects for a hand-built site's old addresses (Love City's SnapPages links)
date: 2026-10-13
agent: Claude Code (Claude Opus 5.5)
asked: "When the domain switches, old SnapPages links will 404: add a redirect map for hand-built sites, and /live to /watch if it can be done safely"
status: in progress
prs: [kmj-intake-server#1410]
migrations: []
left_undone: ["Codex re-reviews, then Kevin/KAI merge", "FOLLOW-UP /live -> /watch: needs a Worker shared secret. GET /live is the live-stream API ahead of the site catch-all, and X-Original-Host is client-supplied, so the app can't tell a request that came through the Cloudflare Worker for a church's domain from one sent straight to the API or platform host. Once the Worker adds a secret header (e.g. X-Solutionist-Edge) and the app checks it, a narrow pre-routing redirect for verified site hosts becomes safe; until then old /live links on lovecityc.com get the API's 401", "After the lovecityc.com cut-over, spot-check a few old links (/what-we-believe, /prayer-request, a /media/ sermon link, one with ?utm_source) on both hosts", "B1 in the domain runbook (http:// on custom domains bounces to a Railway 404) is separate and still open"]
decisions: ["Redirects answer only where a hand-built site would otherwise 404, so they never shadow a page, a hosted door or news", "build.py REDIRECTS -> site_sync validates and stores site_config.manual_redirects; a build without REDIRECTS leaves the row untouched (KMJ)", "Targets are only the site's own pages (optional ?query and #anchor): no open redirects", "'/x/*' covers everything under /x (the old /media sermon library)", "The visitor's query string (utm_*, fbclid) is kept on the redirect; where the map's target names the same parameter, the map's value wins", "No redirect for a path an API route answers first (/live): Codex's review showed the first version's pre-routing layer trusted X-Original-Host, so it was removed, and site_sync now refuses such paths", "A redirect-only change updates the row without a deploy browser check", "/my-love-nation (old members-only page) is left as a 404"]
related: [2026-10-13-love-city-church-site.md, 2026-10-13-hand-built-site-pages.md]
---
A hand-built site can declare `REDIRECTS = {old path: new page}` in its
build.py. site_sync checks each entry (site_page_helpers.clean_redirects:
lowercase paths, never a page, a reserved/API path or a hosted door; target
must be one of the site's own pages), prints any it skips, and stores the rest
as `site_config.manual_redirects`. public_site answers them with a 301 on the
platform subdomain and the custom domain, at the point where the site would
otherwise return its 404, for hand-built sites only. The redirect keeps the
visitor's query string (site_page_helpers.with_visitor_query), with the map's
own parameters winning on a clash.

The first version also redirected /live (an authenticated API route ahead of
the site catch-all) through an ASGI layer that picked the site from
X-Original-Host. Codex's review: that header is client-supplied, so anyone
could turn the API's answer on the Railway or platform host into a 301. With
no trusted signal that a request came through the Worker, the layer is gone,
/live is refused like any reserved path, and Love City's map no longer lists
it. See left_undone for the Worker-secret follow-up.

Love City maps 33 old SnapPages addresses plus `/media` and `/media/*`
(sermon share links). Old forms land on the connect card with the same
interest ticked. Tests: test_site_redirects (a stubbed database that answers
each lookup by slug or domain, so sites are told apart: both hosts, the
visitor's query kept, page and door precedence, each site only its own map,
unknown hosts, composed parity, no open redirect, /live always the API even
with a spoofed X-Original-Host, KMJ unchanged), plus additions to
test_site_page_helpers, test_site_sync and test_site_love_city.
