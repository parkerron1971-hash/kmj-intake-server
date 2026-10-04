---
title: Acuity client and appointment migration with reviewed cutover
date: 2026-10-04
agent: Codex (GPT-6)
asked: "let's make it happen; vertical websites, logins and packages"
status: in progress
prs: [kmj-intake-server#1257 (draft)]
migrations: [supabase/APPLY-2026-10-04-acuity-migration.sql (not applied)]
left_undone: [Approved UI implementation, end-to-end booking rehearsal, concurrent standalone session review, customer identity and retention review, full CI rerun, merge and coordinated deployment, staff and class and prepaid migration support, Chief import orchestration and source connections]
decisions: ["First release targets solo providers", "Review before atomic import", "Imported reminders start paused", "One shared platform with proposed vertical presets and separate package entitlements"]
related: []
---
Built bounded CSV planning, owner-gated review/commit/receipt/reminder endpoints,
service-only migration tables and functions, source deduplication and an overlap
guard. Corrected stored booking timestamps and session mirroring/rescheduling
against the verified live schema. 199 focused tests pass. The live SQL rehearsal
at 10:52 UTC rolled back all schema and fixture changes; 13 checks passed and no
fixture contacts remained. Nothing has been deployed or imported for customers.

Kevin approved the UI design and clarified that import must work across all
verticals. People-only import now remains available even when a business uses
staff calendars/classes/prepaid balances; those dependencies gate appointment
migration. Chief-assisted import and Acuity OAuth are proposed next, not built.
Full CI initially passed 12,558 tests and failed the export-inventory guard;
explicit portability decisions were added for the two internal migration tables.
The follow-up focused suite passes 236 tests, including the export guard and
people-only imports for church, barber and lawyer business labels. People-only
imports do not activate the appointment overlap guard.
The draft, release gates and
vertical direction are documented in `docs/ACUITY_MIGRATION.md`. Other agents'
website work was not modified; this branch is in an isolated clone.
