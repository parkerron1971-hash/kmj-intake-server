---
title: Prioritize useful invoice reminders in short Chief plans
date: 2026-10-02
agent: Codex (GPT-6)
asked: "Fix the short plan choosing two small same-client reminders instead of worthwhile overdue work"
status: in progress
prs: []
migrations: []
left_undone: ["Parent-managed review and release", "Production priority verification"]
decisions: ["Rank only the loaded scoped invoice sample", "At most one reminder per normalized client name", "No extra provider calls or new amount/date speech"]
related: [2026-10-02-chief-conversation-gaps.md]
---
The shipped short-plan path selected the first two eligible invoice rows, which
could spend both candidate slots on small invoices for one client. Candidates
now prefer overdue invoices, then invoices due today, unknown due dates, and
future invoices. Within that urgency group, larger known values come first;
age breaks value ties. A valid due date takes precedence over conflicting hints.
Missing dates can use validated overdue days or the explicit overdue status.

Only sent/viewed/overdue records with safe names and invoice identifiers qualify.
Invalid supplied amounts are rejected; sparse records with missing amounts remain
usable at lower value priority. The two-candidate limit remains, with at most one
invoice per client name after case/whitespace normalization. No record is classified
as a test fixture, and ranking never adds factual amounts or dates to speech.

Validation: 83 priority, quick-plan, direct-plan and request-integration tests passed.
Fictional regressions cover two early same-client $5 invoices versus later $150/$100
invoices, due today versus future, missing and malformed values, excluded statuses,
unsafe identities, client variety, and unchanged input records. Backend and frontend
voice recovery worklogs were reviewed; this change has no frontend impact.
Local commit is handed to the parent agent for review and release; no child PR/push.
