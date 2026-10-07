---
title: Tracked links on the business's own site, plus results (marketing suite B6)
date: 2026-10-07
agent: Claude Code (Claude Opus 5.5)
asked: "This will work. let's build this."
status: waiting on Kevin
prs: [kmj-intake-server#1316]
migrations: []
left_undone: ["Leads are a floor: business-site forms and the booking widget post cross-origin, so the Referer carries no utm_content and lead_attribution records none; counting leads needs them to send the session's tags (frontend and site-module work)", "Frontend F3 (Results tab) reads GET /marketing/{business_id}/results; nothing reads it yet", "B5's sender sends publish_text as stored; posts saved before this PR carry no link until they are edited", "Not proven against production: custom-domain /go/ through the Cloudflare worker (X-Original-Host) and the narrow business_sites select are tested with fakes only"]
decisions: ["The short link is {origin}/go/{code}: the verified custom domain, else slug.mysolutionist.app; code = business_marketing_store.link_code(post id)", "Where a post goes: its own link, else the desk's (while on the site), else /book when anything is bookable, else the published home, else no link", "tracked_url = landing + utm_source=social, utm_medium=organic_social, utm_campaign=marketing_desk, utm_content=<post id>; its host must be one of the business's own hosts", "publish_text = the caption with the short link (platform_marketing.caption_with_landing_link, now taking the business's hosts); network length limits are checked on it", "landing_url and publish_text are in content_hash, so a new link is a new revision; an edit whose stored link left the site is refused until the link changes", "/go/ on a business host: resolve the host's business, ask marketing_follow without counting, redirect only to that business's own post on its own hosts, then count for a person; anything else is the site's 404; the apex path is unchanged", "The business-site beacon keeps campaign tags for the session and sends them as c, so site_events carry utm_content (they carried none before)", "Results: 30 days, posts that went out; clicks, distinct-session visits, leads; unavailable is null and named, a limit hit is partial; worded came through"]
related: [2026-10-07-marketing-desk-api.md, 2026-10-07-marketing-suite-storage.md, 2026-10-02-marketing-desk.md]
---
B6 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md. business_marketing_links.py
builds a business post's short link, tagged destination and the words that go
out, and resolves /go/{code} on the business's own host (wired into
public_site's /go/ route before the site answer; the apex keeps calling
platform_marketing.follow). business_marketing.py sets landing_url,
tracked_url, link_code and publish_text on every new or edited post.
business_marketing_outcomes.py and GET /marketing/{business_id}/results
(owner + members) report clicks, visits and leads per post and in total over
30 days. The site beacon now carries campaign tags. No migration, job, Chief
action or frontend. Tests: __tests__/test_business_marketing_links.py (no live
calls). Docs: docs/MARKETING_DESK.md, "Tracked links and results (B6)".
