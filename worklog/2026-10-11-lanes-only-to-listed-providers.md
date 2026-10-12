---
title: "A lane moves only to a provider the privacy policy names"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "awesome. continue (Kevin, 2026-10-11, after the Layer Two build)"
status: waiting on review
prs: [kmj-intake-server#1390]
migrations: []
left_undone: ["CHIEF_SUBPROCESSOR_HOSTS is empty and no lane is moved; listing a host waits on the privacy policy naming that provider (Kevin's call)", "not exercised against a real provider yet"]
decisions: ["every lane carries some business's data, so route_for requires an https URL whose host is listed in CHIEF_SUBPROCESSOR_HOSTS (subdomains by whole labels)", "policy first, list second: listing a host is the record that the policy covers it", "an unlisted host keeps the lane on Claude and prints why, never fails closed"]
related: [2026-10-11-lane-registry.md]
---
Follow-up to the lane registry (#1388), for "client data never leaves the system
without authorization." Moving a lane had become a config change, and that change
could send client data to a company the privacy policy does not name. Now it also
needs the provider's host on the subprocessor list. Nothing changes in production.
