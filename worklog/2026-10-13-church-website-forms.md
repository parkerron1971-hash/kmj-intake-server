---
title: Durable church website connect cards and private prayer requests
date: 2026-10-13
agent: Codex (GPT-6)
asked: "KAI brief: make Love City Church forms land properly in Solutionist"
status: in progress
prs: [kmj-intake-server#1409]
migrations: []
left_undone: ["Update church forms.js after site PR #1408 merges, rebase first", "Run church site tests and await PR test check", "Claude Code review; do not merge"]
decisions: ["Reuse contacts shown as Members and owner-only ministry_care_requests; no schema change", "A confirmed database write determines success; notification_sent reports email outcome", "Prayer requests never enter contacts, scoring, events, SMS consent or automated outreach", "Keep full messages and all structured answers; reject documented limits rather than truncate", "Church notifications use only the verified sending address"]
---
Added structured connect_card and prayer_request payloads to the existing public
contact-submit route, including compatibility with the initial hyphenated church
form labels. Contact history uses conditional updates and is never trimmed or
evicted. Prayer requests reuse the existing Prayer & care owner view. Legacy
contact callers keep their payload and notification routing.

Read backend worklogs before building; the related contact-box SMS disclosure
work is unaffected. The local solutionist-studio folder has no Git checkout or
worklog to inspect. Rebased this branch onto origin/main before changes.

Validation so far: 242 tests passed across test_website_forms,
test_outbound_integrity, test_lead_identity, test_lead_scoring and
test_site_manual_source, test_ministry_readiness, test_member_portal_church,
test_lead_door_defects and test_site_audit_fixes_0801. New tests cover durability, database and notification
failures, full limits, legacy payloads, server recipients, privacy and concurrent
updates. No live submissions or database changes were made.
