---
title: Class slides, part 1 (server) - every lesson's deck, presenting to a TV by code, and Chief making slides visual
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin approved the "One deck, every room" class-experience design: "Designs is good for starting off. let''s build it"'
status: shipped
prs: [kmj-intake-server#1474]
migrations: [supabase/APPLY-2026-10-17-academy-slides.sql (applied)]
left_undone:
  - "Phase 1 front end (Slides tab, presenter, TV page, phone clicker) is the solutionist-studio PR that follows"
  - "Students reading slides in the classroom (a token-scoped read without notes) comes with the student-side phase"
  - "Live class, recordings, classes in the member app, reminders: later phases of the same design"
decisions:
  - "A deck is stored only once someone edits it; until then the app builds it from the lesson text (no copy to drift)"
  - "Teacher notes live inside each slide and are stripped server-side from every presenting snapshot"
  - "Scripture on a Chief slide is never model-typed: an empty quote is filled from the server's WEB/KJV text, any other quote must be the lesson's own words"
  - "Chart numbers must appear in the lesson; pictures must already be the business's own storage or in the lesson"
  - "Chief reads slides through inspect_course (no new read verb); one new class-A write verb, save_lesson_slides"
  - "The TV reads by a 6-character code through academy_present_view (anon); the code is the key and expires with the class"
related: [2026-10-16-church-cards.md]
---
Every lesson now has a slide deck. The server keeps the edited decks
(`academy_decks`, written only through `academy_save_deck`, which checks the
teaching team, the layouts, the picture links and a revision so two editors
can't overwrite each other) and the presenting sessions a TV follows
(`academy_present_sessions`: a short code, a snapshot of the slides without
teacher notes, the slide showing now; `academy_present_start/_update/_view`).

Chief gets `save_lesson_slides` and reads saved slides through
`inspect_course`. The editor gets two small routes in
`academy_slides_router.py`: the verse text for a scripture slide and a public
copy of one of the business's own gallery images for a picture slide.

The migration was rehearsed on production inside a rolled-back transaction
as the Love City owner before it was applied.
