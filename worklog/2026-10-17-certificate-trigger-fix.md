---
title: An owner can mark a student's class finished again (certificate trigger ran as the signed-in user)
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Found while building phase 4 (programs) of "One deck, every room", after Kevin: "let''s start phase 4"'
status: shipped
prs: [kmj-intake-server#1479]
migrations: [supabase/APPLY-2026-10-17-academy-certificate-trigger-fix.sql (applied)]
left_undone: []
decisions:
  - "The trigger runs as its owner (SECURITY DEFINER) rather than opening the code maker to signed-in users"
related: [2026-10-17-class-student-side.md]
---
#1478 added a trigger that issues a certificate code when an enrollment is
finished. Course Studio marks a student finished with a signed-in PATCH
(status completed), and the trigger, running as that user, called
academy_new_certificate_code, which is server-only: the save failed. A
rollback probe as the Love City owner showed the error, and after the fix
the update passes with a code issued. Nobody had hit it yet.
