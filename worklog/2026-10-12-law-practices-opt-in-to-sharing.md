---
title: "Law practices share patterns only once they switch it on"
date: 2026-10-12
agent: Claude Code (Claude Opus 5.5)
asked: "agreed, set FEED2=off and draft the PR ... go (Kevin, 2026-10-12, on the two legal calls)"
status: waiting on review
prs: [kmj-intake-server#1399]
migrations: []
left_undone: ["Feed 2 is switched off platform-wide (FEED2=off on both services since 2026-10-12) until the privacy policy describes it; turning it back on is Kevin's call after the policy PR is live", "the Settings switch in the app should show off for a law practice that never touched it (frontend PR)"]
decisions: ["general businesses keep Kevin's 2026-07-27 on-by-default; law practices (vertical_family.is_legal_like) default off", "a malformed settings blob means the type's default, an explicit value always wins"]
related: [2026-10-11-distill-strips-known-names.md, 2026-10-12-no-new-health-practices.md]
---
Second of Kevin's two legal calls (2026-10-12). Lawyers owe their clients
confidentiality under their own professional rules, and the ABA's 2024 AI opinion
puts it on them to know where client information goes, so cross-business pattern
sharing starts off for a law practice and is theirs to switch on. Feed 2 itself is
paused platform-wide until the privacy policy describes it.
