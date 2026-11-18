---
title: Prayer & care handed to an office login gets a heads-up and a due time, server half
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "build the heads-up and due time for logins run supabase as well so I can click run if need be"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-11-18-care-login-due.sql]
left_undone:
  - "Frontend: the desk draws the due time, the heads-up and the late steps, and gives the login an \"I'm on it\" (solutionist-studio worklog 2026-11-18-care-login-due.md). Either order works: the app reads the new fields when they come"
decisions:
  - "Due a day after the hand-off, as the prayer team's is (church_prayer.DUE_DAYS). What's due is a first step, not the whole thing: a note, \"I'm on it\" (status reviewed), marked prayed or done. A visit can take a week; nobody should wait a week to hear it was seen"
  - "The heads-up: a push to the office app and an email to the login's sign-in address, the same two the leaders schedule uses for a login. Two minutes after the hand-off, so the desk's Undo tells nobody. Never in the church's quiet hours, except a request that needs a pastor, which goes at once"
  - "A notice says that a request is theirs, who handed it and when it's due. Never the request's words, the person's name or the kind of request: a lock screen isn't private and Prayer & care asks for a password. The sweep doesn't read submission at all"
  - "Late ladder, as the prayer team's: when due the login is reminded; a day late whoever handed it hears (else the owner); three days late the office's alerts ask to hand it to someone else. Late steps wait out quiet hours"
  - "Told once: every notice is a claim first (a conditional update that lands only while the request is still with the same login, handed at the same moment, with no first step), let go when nothing went"
  - "Taken back, given back or handed afresh: the timing clears and starts over. Handed to yourself (a keeper): nobody is told"
  - "A login that left the office: the office's alerts say so once, and the ladder carries on to whoever handed it"
  - "Old hand-offs: the migration marks them told with no due time, so applying it sends nothing about them"
  - "My week's care line says when the first step is due, then that it's past due"
  - "CARE_HEADS_UP=off is the rollback: nothing is sent or claimed; due times still show"
  - "History: two new verbs, church:care_told and church:care_late (church_history.VERBS and audit_log, pinned equal)"
related: [2026-11-18-care-desk-server.md]
---
The care desk (#1925) left one thing undone: a request handed to an office login
showed only on that login's My week, with no alert, no due time, and nobody told
when it waited. The prayer team has had all three since October.

`private_care.update_request` now stamps `assigned_due_at` a day out on a
hand-off and clears `assigned_told_at`, `assigned_acted_at` and
`assigned_late_level`. The login's first step, a note (`add_note`) or "I'm on
it", prayed or done, stamps `assigned_acted_at`. The owner's own steps don't.
Every read tries the new columns first and falls back, so nothing changes until
the migration is in.

`care_handoff.py` is the sweep, every five minutes on the worker. It reads only
ids, who and when, never the request. It claims, sends (`tell`: push + email),
and lets the claim go when nothing went. `church_my_week` shows the due time
and says when it's late.

Tests: `__tests__/test_care_handoff.py` (the hand-off, the first step, the
sweep, the ladder, quiet hours, the switch, before the migration) and a My week
case in `test_church_my_week.py`. The new job is in
`test_sample_church_no_sends.TICKS`.
