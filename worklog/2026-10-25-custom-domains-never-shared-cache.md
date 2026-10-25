---
title: Cloudflare never stores a custom domain's pages (churchsavvy.app showed on lovecityc.com)
date: 2026-10-25
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-25: "there is an issue that came up churchsavvy site is pulling up under lovecityc.com"'
status: done
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: ["churchsavvy.app goes back on (Vercel ALIAS @ and CNAME www to saas-origin.mysolutionist.app) only after this is live and checked", "the Worker could put the visitor's hostname into what it fetches so Cloudflare could cache per domain again; it is deployed by hand in Cloudflare's dashboard (Kevin), so not done here", "the server's CF_API_TOKEN cannot purge the cache (401); a purge permission would let a bad entry be cleared at once instead of waiting for it to expire"]
decisions: ["fixed at the origin, not the Worker: every request that arrives with X-Original-Host answers Cloudflare-CDN-Cache-Control: no-store, and Cache-Control loses public / s-maxage / proxy-revalidate and gains private (max-age, immutable and the rest stay, so the browser still keeps its own copy)", "pure ASGI and header-only, outermost, like sse_middleware.py, so streamed responses are untouched", "direct traffic (mysolutionist.app, platform subdomains, the API host) never carries X-Original-Host and keeps its headers"]
related: [2026-10-25-churchsavvy-every-service.md]
---
**What happened.** churchsavvy.app went live 13:13Z through Cloudflare for SaaS, like a church's own domain. The SaaS Worker fetches the Railway origin URL and passes the visitor's hostname in X-Original-Host, so Cloudflare cached that fetch under `kmj-intake-server-production.up.railway.app/` with no hostname in the key. ChurchSavvy's home page (`public, max-age=300, s-maxage=600`) was stored there and served to lovecityc.com and www.lovecityc.com as a HIT, with the same x-railway-request-id on both. A cache-busting query returned Love City's own page. Church pages (`s-maxage=60`) would have leaked into each other's domains the same way.

**Done at once.**
- Took churchsavvy.app's ALIAS and www CNAME out of Vercel so nothing refilled the entry.
- Tried a purge: the CF token answers 401 for purge. The entry expired on its own.

**This change.** `custom_domain_cache.py` (NoSharedCacheForCustomDomains), registered last in `kmj_intake_automation.py`. `__tests__/test_custom_domain_cache.py` has 11 tests:
- the mini app;
- ChurchSavvy's real pages through the routers;
- that it is registered outermost.

3 sabotages caught: no-op, keeps s-maxage, not registered. 44 tests green across this, sse_middleware, the ChurchSavvy site and the custom-domain tests.
