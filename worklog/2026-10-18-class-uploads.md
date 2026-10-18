---
title: Uploads (server) - homework handed in as a photo, a PDF, a voice note or a short video, by the class link; the teacher opens it signed in
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "I''m happy with it. build it" for the approved Class Schedule design, whose Homework board offers Upload ("A photo, a file, a voice note or a video") and "Tick it off and add a photo"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the classroom and teacher side, next)]
migrations: [supabase/APPLY-2026-10-18-academy-uploads.sql (applied)]
left_undone:
  - "A file whose homework or student is deleted stays in the bucket until the account is deleted (storage objects can't be removed from SQL); a sweep can find paths no work row names"
  - "Classmates never see a file, even on homework shared with the class; their line still shows"
decisions:
  - "A private bucket with no storage policies: the service role is the only reader and writer, so every check a policy would make is made by academy_item_file_target / academy_item_attach or here"
  - "The bytes decide what a file is; the browser's type only chooses audio or video for a container that holds either, and never makes a file acceptable"
  - "Photos are decoded and saved again upright, at most 2400 px, without EXIF, so a phone photo's location never reaches the teacher; see-through pictures stay PNG, the rest JPEG; HEIC is refused with how to send it"
  - "Limits: a photo or PDF 20 MB, a voice note 25 MB, a video 50 MB (the bucket's own ceiling)"
  - "Path <business>/<course>/<enrollment>-<item>-<random>.<ext>, built only from ids the database returned; the database refuses any other; account deletion's one-level descent finds it"
  - "Rate limits per class link (hashed: the limiter's shared table never holds a link) and a wide per-IP ceiling, so a class on one church Wi-Fi isn't one budget"
  - "The teacher's read goes through their own token (academy_item_work's teacher-read policy), then a 15-minute signed link"
related: [2026-10-18-class-schedule.md, 2026-10-18-class-discussions.md]
---
- `academy_work.py`: `classify` (bytes to kind, the photo re-save), the
  path, the three routes; mounted in `kmj_intake_automation.py`.
- `rate_limit.py`: `academy_work_upload`, `academy_work_upload_ip`,
  `academy_work_file`.
- `account_lifecycle.py`: `academy-work` in `STORAGE_BUCKETS`.
- `supabase/APPLY-2026-10-18-academy-uploads.sql` (+ docs/MIGRATIONS.md):
  rehearsed with a rollback probe, applied, verified.
- `__tests__/test_class_uploads.py` (28): EXIF location gone and photo
  upright (fails if EXIF is passed through: rehearsed), sizes, HEIC, the
  bytes not the browser, the path, refusals before a byte is stored, a
  refused file deleted again, the replaced file deleted, the limiter keeps a
  hash, the teacher read with their own token.
