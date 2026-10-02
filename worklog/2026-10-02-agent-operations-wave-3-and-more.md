---
title: Support desk, Chief quality, Security steward, Customer health, Trial expiry
date: 2026-10-02
agent: Claude Code (Claude Opus 5.5)
asked: 'you can start (wave 3); I haven''t hired no one yet but doesn''t mean you can''t build it'
status: shipped
prs: [kmj-intake-server#1173, kmj-intake-server#1177, kmj-intake-server#1178, kmj-intake-server#1179, kmj-intake-server#1180, solutionist-studio#1087]
migrations: [supabase/APPLY-2026-10-02-support-drafts.sql (applied)]
left_undone: ["Agent 10 (trust & safety) waits until a church message-screening system exists", "Chief's error rate is 9-11% of turns (the first Chief-quality flag); not yet investigated", "the uncommitted 2026-09-30 security audit in Kevin's main backend checkout needs a PR"]
decisions: ["support drafts and customer check-ins never send", "app-granted trials end as canceled, like lapsed Stripe trials"]
related: [2026-10-01-agent-operations-waves-1-2.md]
---
Support desk drafts a reply for every ticket waiting on one, and the new
Mission Control Support Tickets screen sends through the endpoint that emails
(the old panel emailed nobody). Chief quality reports cost and speed nightly
and runs the Chief evals on Mondays. Security steward checks secrets, access
rules, a master key in the app and backups weekly. Customer health raises
businesses that stalled, with a suggested note. Trial expiry ends app-granted
trials.
