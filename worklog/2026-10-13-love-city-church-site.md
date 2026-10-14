---
title: Love City Church hand-built website
date: 2026-10-13
agent: Claude Code (Claude Opus 5.5)
asked: "Build the Love City Church site to the 2819church.org bar, from the old site's audit and the church's own photos"
status: shipped
prs: [kmj-intake-server#1408]
migrations: []
left_undone: ["Confirm the church's contact-form recipient: the connect card and prayer request get {ok:false} unless site_config.sections.contact.email, the brand footer contact_email or DEFAULT_CONTACT_FALLBACK_EMAIL is set (contacts are still captured)", "Prayer form asks for name and email until the church has its own back end", "If business 009e9a2c is a no-card trial without a card, the public address shows coming soon"]
decisions: ["Hand-built in sites/love-city-church/ and installed by site_sync, like KMJ", "The live page is /watch, not /live: GET /live is an authenticated API ahead of the site catch-all", "Thursday is 'Thursdays 6pm, Mid-week Bible study' and is never tied to 1084 Allen Ave", "The church's heart mark in site magenta, keep the brush logo, plum/magenta/cool-paper palette", "Forms count only {ok:true} as sent", "No recipient email address in any page"]
related: [2026-10-13-hand-built-site-pages.md, 2026-10-14-love-city-better-photos.md]
---
Love City Church's ten-page site (home, visit, about, beliefs, sermons, give,
ministries, events, connect, watch) lives in `sites/love-city-church/` and is
bound to business 009e9a2c-3e81-4bfc-a92a-205a8806aa99. Its business_sites
row (slug love-city-church) came from Giving. site_sync installs it on deploy
(all ten pages need #1407) and keeps the old row as manual_backup. Kevin
approved the design; Codex's front-end review findings 1-10 are fixed.
`__tests__/test_site_love_city.py` covers the build, content rules,
accessibility, both forms (four tests in Chromium), routing through the real
app on both hosts, and install safety. The deploy check opens the first four
pages only (DEPLOY_PAGE_LIMIT). Before changing the site, read the commits in
#1408. Kevin's design calls are listed in the PR.
