---
title: The rail, practice mode — money and calendar lookups answered privately from the records, proved, and compared with Chief
date: 2026-10-16
agent: Claude Code (Claude Opus 5.5)
asked: "'start': build step 1 of the Instinct Layer brief (two shelves, invisible, across all businesses)"
status: in progress
prs: [kmj-intake-server#1462]
migrations: [supabase/APPLY-2026-10-16-chief-rail-practice.sql (table applied 2026-10-16; business foreign key pending a re-run)]
left_undone: ["Re-run the migration file so the business foreign key lands (the auto-mode classifier refused the editor run as Production Deploy)", "Read a week of practice rows (GET /platform/rail/stats or scripts/rail_practice_report.py) before any live step", "Live step (not built): answer the shapes that graduate from the rail, KMJ first, Chief unchanged otherwise"]
decisions: ["Practice only: nothing the rail writes is ever shown", "Runs after the reply on a worker thread, full turns only, at most 3 at once; no model calls", "Owner only: a service-role owner_id check before any read; collaborators are skipped, not logged", "An answer counts as proved only by chief_truth.fast_lane against the rows in the answer check's own shapes, or by an empty read that returned every row", "Chief's definitions: owed = sent and unpaid, drafts apart; overdue = sent and past due; days on the business clock", "Too long (over 6 clients, 8 sessions, 4 of a client's invoices), unnamed clients, ambiguous names and 'Friday' on a Friday are left to Chief"]
related: [2026-10-11-layer-two-foundation.md, 2026-10-11-business-brain.md]
---
Kevin's layer two picture (the librarian should not have to fetch every
book) became the "Instinct Layer" brief on 2026-10-16. Its first step is
this rail, in practice mode. After a full Chief turn on the stream endpoint,
`chief_rail.after_turn` (hooked in `chief_fast_track.TwoTrack.finish`)
reads the question. If a money or schedule shelf takes it whole (who owes,
how much is owed, overdue, did X pay, X's balance, a day's sessions, the
next session, X's next session), it does four things. It checks the asker
owns the business. It reads the rows fresh. It writes the answer from them,
one invoice or session per sentence. It proves that answer with Chief's own
free prover. Then it compares the answer with Chief's reply by dollar
amounts, the yes or no, or clock times. One row goes to `chief_rail_practice`.
Records questions off the shelves are kept as declines with a reason, so
coverage can be measured.

The rail probe (2026-10-16) found about 1 in 10 Chief questions on these
shapes, at about 19¢ each, with a third of them walled. So the case is
quality and speed first, and cost second.

Read docs/CHIEF_RAIL.md before building the live step. Codex's draft #1406
(an offline CPU model for appointment-request intents) is a related idea,
not wired in; no file overlap.
