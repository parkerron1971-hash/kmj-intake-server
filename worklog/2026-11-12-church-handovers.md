---
title: Church assignments, PR C1 — pastors and elders under the owner and the map only; From the office
date: 2026-11-12
agent: Claude Code (Claude Opus 5.5)
asked: 'admins can not give work to elders and pastors but they can give them things that is related to their area that they need for them to have'
status: in progress
prs: ["kmj-intake-server#1804"]
migrations: ["supabase/APPLY-2026-11-12-church-handovers.sql (not applied)"]
left_undone: ["The migration isn't applied: until it is, the hand-over routes answer 503 for the platform owner's church and the sweep's read fails quietly", "My week's from_office has no frontend yet (solutionist-studio): the owner sees nothing until it's built", "PR C2: the member app's Lead tab (Your assignments, Sent up to you, From the office, Your people), per the approved phone mock", "The database doesn't refuse a task the office writes straight to it for a pastor or an elder (known limit: a trigger would repeat who shepherds in SQL, not simple enough to be safe); the Hand to list no longer offers them"]
decisions: ["Who shepherds is each role's own switch (church_map.can), and a role that follows the Ministers setting by that setting; never a title word, map open or closed", "No office standing but the owner's (an Admin's, a lanes overseer's, the closed map's fallback) is over a shepherd or a senior, nor over a login whose person is one; the map's chain, walked from the login's own person, still is", "The seniors stay under the owner only (the #1801 rule): the new rule's 'or through the ministry chain' is read for the shepherds, not as a loosening for the seniors", "A hand-over goes to people only (a contact), never a login; a person whose login is an office seat (the owner's too) reads it on My week, anyone else in the Lead tab", "A Manager sends for a department whose support duty it holds (Church.held), else whose area is one of its areas; with Who sees what off, every area, as its duties read; the map closed, nobody", "The owner and Admins may send for any active department; a Manager only for one it may send for", "Links are https only, with no sign-in inside them; the email shows the link as text", "Excluded from the export: the sender is a sign-in user id, and a restore must not claim anything was seen or told", "One email a person a sweep; one older than a week and never told is left untold", "My week's from_office is null when it can't be read, and the week stands", "The old Hand to list (GET /church/my-week/people) follows the rule while assignments are open for the church: no shepherd or senior, nor a login whose person is one, for any seat but the owner; a task to yourself stays; an unreadable guard is a 503"]
related: [2026-11-12-church-assignments.md, 2026-11-12-church-assignments-done.md]
---
PR C1 of `docs/CHURCH_ASSIGNMENTS.md`, after #1802 merged. Kevin's words for it: "admins can not give
work to elders and pastors but they can give them things that is related to their area that they
need for them to have."

The rule: `church_over.Church.shepherds` (by each role's switch) and `guarded` (shepherds and
seniors). `_under` leaves them out of an Admin's, a lanes overseer's and the closed map's office
standing, logins whose person is one included, then walks the map from the login's own person, so
Marcus (an elder who answers to Jessica on the map) is still under her login. Tested at all four
fixture churches: Love City (Jessica's login is no longer under the Admin), Grace (its deacons
shepherd by their switch), New Hope (associate pastors and elders; an elder's Manager seat), and
Riverside (nothing guarded).

From the office: `church_handovers.py` (send, what I sent, the leaders I may send to with why, Got it
from My week, the hourly email), the new server-only table in
`supabase/APPLY-2026-11-12-church-handovers.sql` (PGlite check: 31), My week's `from_office`, the
worker job `church_handovers_sweep`, and the export exclusion. Never a task: nothing late,
escalated or judged.
