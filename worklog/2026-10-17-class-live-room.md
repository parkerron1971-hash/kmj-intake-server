---
title: Class live room, part 2 (server) - the lobby, kept chat and questions, answers on screen without names, hands, and who is teaching
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, after the class slides went live: "ok cool. let''s keep working on the next phase." (phase 2 of the approved "One deck, every room" design: the live class)'
status: shipped
prs: [kmj-intake-server#1476]
migrations: [supabase/APPLY-2026-10-17-academy-live-room.sql (applied)]
left_undone:
  - "The room itself (lobby, stage following the slides, teacher console, phone) is the solutionist-studio PR that follows"
  - "Recording (Kevin: on from the start) needs its own storage bucket and keys, which only Kevin can create; it comes next, switched off until they exist"
  - "Prayer from the class to the care team, in-room check-in by scanning the TV, and attendance into church attendance belong to the church phase"
decisions:
  - "Messages reach the room from the backend only (LiveKit send_data), never peer to peer, so a held message or an answer can be kept from students"
  - "A student's message with a link is held for the teacher; a teacher's never is"
  - "Answers to a question slide are one per person per slide (a new one replaces the old) and only the teaching team sees names; on screen they go without a name or identity"
  - "The lobby is the same LiveKit room opened up to 15 minutes early without class metadata; Start sets the room's metadata to live, so a late lobby join can never put a started class back in its lobby"
  - "The teacher who scheduled the class goes by the name given when scheduling (Pastor Kevin); other teachers by their account name; no one is 'Teacher' unless nothing else is known"
  - "Kept messages are tied to the class session (deleted with it), like attendance; they are not part of the business export"
related: [2026-10-17-class-slides.md]
---
The server half of the live class room.

- **Migration** (applied): `academy_live_sessions.lesson_id` / `teacher_name`,
  `academy_live_messages`, `academy_live_post` (service only, paced),
  `academy_schedule_live` with lesson and teacher, `academy_live_access` and
  `academy_student_live` carry start time, lesson, teacher and business type,
  `academy_course_brand` for slide colors.
- **`academy_live_router.py`**: `join` works in the lobby window (opens the
  room without making it live); `start` sets the room live; new `post`,
  `history`, `moderate` (hide, show, pin, unpin, answered, on/off screen),
  `lower` (a hand) and `roster` (every enrolled student by name, for "not
  here yet"). Inviting someone to speak lowers their hand.
- **Tests**: `__tests__/test_academy_live.py` (77; two privacy rules
  sabotaged to prove the tests go red).
