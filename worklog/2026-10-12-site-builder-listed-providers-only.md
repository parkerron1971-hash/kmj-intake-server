---
title: "The site builder uses Moonshot only once the privacy policy names it"
date: 2026-10-12
agent: Claude Code (Claude Opus 5.5)
asked: "go ... update the website and anything else you need to (Kevin, 2026-10-12, on the two legal calls)"
status: waiting on review
prs: [kmj-intake-server#1403]
migrations: []
left_undone: []
decisions: ["site_llm's provider(), provider_for(), judge_provider() and create_message all pass moonshot through lane_registry.listed_subprocessor; unlisted = Claude, said once per process", "scripts/design_acceptance.py lists the host for its own process in moonshot modes: running it is the operator's deliberate choice"]
related: [2026-10-11-lanes-only-to-listed-providers.md, 2026-10-12-privacy-says-how-chief-learns.md]
---
Raised by the PR reviewer on the privacy policy PR: Moonshot's key is set in
production and one env flip sent a business's site content to a company the
policy does not name. Moonshot now runs only when CHIEF_SUBPROCESSOR_HOSTS lists
its host, the same rule the Chief lanes follow, so the policy stays true whatever
the site-builder switches say.
