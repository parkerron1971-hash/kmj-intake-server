---
title: Site agent surface was dead since launch (wrong column names)
date: 2026-10-05
agent: Claude Code (Claude Opus 5.5)
asked: 'found while building designed flyers ("I would like to figure out how to build this")'
status: shipped
prs: [kmj-intake-server agent-site-facts-load]
migrations: []
left_undone: []
decisions: ["Read only columns the tables have; the logo stays in settings.brand_kit"]
related: [2026-10-05-creative-director-every-business.md]
---
agent_site._load_bundle asked businesses for logo_url and practitioner_profiles
for phone/address_city/address_state. None of those columns exist, so both reads
were 400s. The business read returning nothing made every site's JSON-LD,
/.well-known/agent.json, llms.txt and the /public/agent booking door answer
"no business at this address" from #812 (2026-09-03) until this fix. Verified
live: /public/agent/kmj-creative-solutions/services returned 404 before; the
fixed loader reads KMJ (7 offerings) from production. The Creative Director's
flyer facts read through the same loader.
