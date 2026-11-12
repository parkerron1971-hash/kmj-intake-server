---
title: Church assignments, PR C2 — a leader's assignments on the member app's Lead tab
date: 2026-11-12
agent: Claude Code (Claude Opus 5.5)
asked: 'phone view idea is good. we can move forward with that.'
status: in progress
prs: ["kmj-intake-server#1805"]
migrations: ["supabase/APPLY-2026-11-12-church-lead-assignments.sql (not applied; apply before the PR merges)"]
left_undone: ["The migration isn't applied: it has to be before the PR merges, or the assignment routes and the Lead tab's assignments answer 503 where the switch is open", "My week's from_office (PR C1) still has no frontend", "PR D: the Chief verbs"]
decisions: ["The Lead tab's assignments live at /my/lead/tasks while CHURCH_ASSIGNMENTS is open for the church (the switcher says Assignments); closed, the tasks page is as it was, so every email's link keeps working", "Section order on a phone, as on the mock: Your people, Your assignments, Sent up to you, From the office; on a computer the first two sit beside the last two", "Every write is church_assignments' or church_handovers' own, with me as one of the church's people; the member routes add only the session (member_portal_church._signed_in: a cross-site POST is a 403, Origin null only with Sec-Fetch-Site same-origin), never the preview, the rate limit and a redirect with a short code", "The coordinator's yes (2026-11-12): tasks.handed_by_contact_id and tasks.raised_by_contact_id, so the page and the emails name a leader who gave, started or sent up from the member app; a login's own hand is read first", "Leader start-up titles reworded to read alone (Who's on your team or group, When you meet: the day and time, The room you meet in, What you need first); the office one-on-one too; startup_key values unchanged", "The hand-over email points a leader without an office login at the Lead tab now that it exists", "No ids and no office words on the screen; ids ride in form addresses only"]
related: [2026-11-12-church-handovers.md, 2026-11-12-church-assignments-done.md, 2026-11-12-church-assignments.md]
---
PR C2 of `docs/CHURCH_ASSIGNMENTS.md`, after #1804 (C1). Kevin approved the phone mock on
2026-11-12: "phone view idea is good. we can move forward with that."

Built: `member_portal_assign.py`, the Lead tab's assignments page (server-rendered, phone first,
`_shell(wide=True)` on a computer) with Your people (n of m, stuck with Send up, next, Give an
assignment, Start their first assignment), Your assignments (Done, Stuck with a note, Not stuck
until it's sent up), Sent up to you (No longer stuck) and From the office (Got it); its seven
POST routes; the switcher's Assignments count; the engine's person-aware writes
(`church_assignments`, `church_startup`); the person columns and their migration; the emails
naming the leader (`church_leader_tasks.person_handers`).
