---
title: Durable church website connect cards and private prayer requests
date: 2026-10-13
agent: Codex (GPT-6)
asked: "KAI brief: make Love City Church forms land properly in Solutionist"
status: waiting on review
prs: [kmj-intake-server#1409]
migrations: []
left_undone: ["Claude Code review and merge; do not merge in this session"]
decisions: ["Reuse contacts shown as Members and owner-only ministry_care_requests; no schema change", "A confirmed database write determines success; notification_sent reports email outcome", "Prayer requests never enter contacts, scoring, events, SMS consent or automated outreach", "Keep full messages and all structured answers; reject documented limits rather than truncate", "Church notifications use only the verified sending address"]
---
Added structured connect_card and prayer_request payloads to the existing public
contact-submit route, including compatibility with the initial hyphenated church
form labels. Contact history uses conditional updates and is never trimmed or
evicted. Prayer requests reuse the existing Prayer & care owner view. Legacy
contact callers keep their payload and notification routing.

Read backend worklogs before building; the related contact-box SMS disclosure
work is unaffected. The nested solutionist-studio checkout and current frontend were later located
and inspected: connect answers need contact_note events for the Members Notes
tab; private care already has an owner-only viewer. Rebased this branch onto origin/main before changes.

Final local validation: 276 tests passed across test_site_love_city,
test_website_forms,
test_outbound_integrity, test_lead_identity, test_lead_scoring and
test_site_manual_source, test_ministry_readiness, test_member_portal_church,
test_lead_door_defects and test_site_audit_fixes_0801. New tests cover durability, database and notification
failures, full limits, legacy payloads, server recipients, privacy and concurrent
updates. No live submissions or database changes were made.

After KAI confirmed #1408 merged, rebased onto origin/main at 61248292 before
editing forms.js. Both forms now send structured fields (including interests,
heard_from, notes and a boolean follow_up) alongside the readable message.
connect.html needed no change. Each connect card also writes a full contact_note
visible in Members → select the person → Notes; that write must succeed before
acknowledging the card. Prayer requests stay in the owner-only "Private prayer
and care requests" view under intake forms, with no contact or event writes.

Regression tests cover missing site email, footer email, verified sender and
fallback email: stored submissions return ok:true, notification_sent:false, and
the real browser shows success and clears the form. Failures keep the visitor's
input. The owner-only private-care read route returns the saved prayer request
and rejects a different owner. No live submissions or recipient settings changed.

The final local run included real Chromium tests (none skipped). JavaScript
syntax validation and git diff --check passed. PR #1409 is to leave draft only
after its final required test check passes; Claude Code reviews before merge.
