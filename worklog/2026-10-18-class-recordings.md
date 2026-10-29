---
title: Class recordings - a live class recorded from its start into the business's own private storage, watched by its students
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "let''s continue so we can finish up" (his 10/17 pick, settled: recording on from the start, "allows for people that need to go back to have that ability")'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the recorder page, the console, Watch the class, the Course setup switch, next)]
migrations: [supabase/APPLY-2026-10-18-academy-recordings.sql (applied)]
left_undone:
  - "Nothing records until Kevin adds the four storage settings in Railway (CLASS_RECORDING_BUCKET, _ACCESS_KEY_ID, _SECRET_ACCESS_KEY, _ENDPOINT: his own Cloudflare R2 bucket and a key for only it); the first real recording is the end-to-end test"
  - "No delete for a recording yet; files stay in his bucket"
decisions:
  - "Recorded through our own page (the app's /class-recorder): what the TV shows (slides, an answer put up, a shared screen) with the teacher's camera in the corner and everyone who speaks; LiveKit's own layout would have shown camera tiles without the slides"
  - "From the moment the teacher starts the class, unless the class's owner turned it off in Course setup; the teacher can stop it any night (the file so far is kept) and it doesn't start a second file that night"
  - "A recording that won't start never stops the class (it says failed); one that started but couldn't be written down is stopped, not left as a file nobody can find"
  - "Watched by a link signed for an hour, only for an ended night with a ready file, only for a student of that class (their link) or its teaching team, the live room's own access check"
  - "LiveKit's egress_ended marks the night ready with its length and size, or failed; an empty file is no recording"
  - "Review on #1501: the night is claimed (recording_status null or failed -> recording) before LiveKit is asked, so two starts never make two files; a database blip before the claim marks nothing failed (the teacher can press Record); a stop LiveKit says is already over sets the night from LiveKit's own record of it (ready or failed), never left recording"
  - "The signing is S3 SigV4 by hand (no boto3 on the server), checked against AWS's published example"
related: [2026-10-18-class-nights-counted.md, 2026-10-18-class-sum.md]
---
- `academy_recordings.py`: `settings`, `egress_request`, `presign_get`,
  `ended_fields`, `object_key`, `recorder_url`.
- `academy_live_router.py`: `start` records (`start_recording`), `record`
  (the teacher stops, or starts one tonight), `watch` (the signed link),
  `status` and the roster say whether the business can record, and
  `egress_ended` marks the night.
- `supabase/APPLY-2026-10-18-academy-recordings.sql` (+ MIGRATIONS):
  rehearsed with a rollback probe, applied, verified.
- `__tests__/test_class_recordings.py` (20; the owner's off switch and the
  claim rehearsed red); the status test in `test_academy_live.py` reads `recording`.
