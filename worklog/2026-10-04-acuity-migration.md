---
title: Acuity client and appointment migration with reviewed cutover
date: 2026-10-04
agent: Codex (GPT-6)
asked: "let's make it happen; vertical websites, logins and packages"
status: in progress
prs: []
migrations: [supabase/APPLY-2026-10-04-acuity-migration.sql (not applied)]
left_undone: [UI design selection and implementation, end-to-end booking rehearsal, concurrent standalone session review, customer identity and retention review, full CI, merge and coordinated deployment, staff and class and prepaid migration support]
decisions: ["First release targets solo providers", "Review before atomic import", "Imported reminders start paused", "One shared platform with proposed vertical presets and separate package entitlements"]
related: []
---
Built bounded CSV planning, owner-gated review/commit/receipt/reminder endpoints,
service-only migration tables and functions, source deduplication and an overlap
guard. Corrected stored booking timestamps and session mirroring/rescheduling
against the verified live schema. 199 focused tests pass. The live SQL rehearsal
at 10:52 UTC rolled back all schema and fixture changes; 13 checks passed and no
fixture contacts remained. Nothing has been deployed or imported for customers.

UI remains pending the owner's design selection required by the Superdesign
workflow; backend work is preserved for review. The draft, release gates and
vertical direction are documented in `docs/ACUITY_MIGRATION.md`. Other agents'
website work was not modified; this branch is in an isolated clone.
