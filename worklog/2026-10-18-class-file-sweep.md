---
title: Homework files nothing points at any more leave the private bucket once a day
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "ok. let''s continue with those not done yet." (the uploads worklog left this undone: a deleted homework''s or student''s files stayed in the bucket until the account was deleted)'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-10-18-academy-work-sweep.sql (applied)]
left_undone:
  - "Classmates never see a file, even on homework shared with the class (by design)"
decisions:
  - "The database names the orphans (academy_work_orphans reads storage.objects against academy_item_work.file_path); the backend deletes through the storage API, since storage rows can't be deleted from SQL"
  - "Only files a day old or more: an upload is attached within seconds of being stored, so one in flight is never swept"
  - "Only names in the one stored shape, checked in SQL and again here; anything else in the bucket is left alone"
  - "500 a day in chunks of 100; the first refused delete stops the run and the rest wait for tomorrow"
related: [2026-10-18-class-uploads.md]
---
- `academy_work.py`: `sweep_tick`; scheduled daily 09:15 UTC in
  `kmj_intake_automation.py` (`academy_work_sweep`, leader only).
- `supabase/APPLY-2026-10-18-academy-work-sweep.sql` (+ docs/MIGRATIONS.md):
  rehearsed with a rollback probe, applied, verified.
- `__tests__/test_class_uploads.py` (+4): batches of 100, only the stored
  shape (fails if the shape check is dropped: rehearsed), a failed list or
  delete stops (fails if a refusal is skipped past: rehearsed), no key no
  sweep, the SQL's age/shape/grant lines and the job's wiring.
