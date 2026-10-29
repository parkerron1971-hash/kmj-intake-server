---
title: A finished class recording reads as ready, from where LiveKit really reports its file
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "done" (the four CLASS_RECORDING_* storage settings in Railway, then the first test recording)'
status: shipped
prs: [kmj-intake-server (this PR)]
left_undone:
  - "The first real class recording with Kevin (a teacher, slides, a camera) is still the end-to-end test"
decisions:
  - "The first test recording (a throwaway room, 23 s, into Kevin's bucket, played back by a signed link, then deleted) finished EGRESS_COMPLETE with its file in EgressInfo's older `file` field and `file_results` empty, so ended_fields marked it failed: every real recording would have been failed. Now either field counts; an unset `file` reads as size 0, still no recording"
  - "Checked live before this PR: the key reads the bucket (a made-up file answers NoSuchKey), LiveKit writes to it, and LiveKit's webhook reaches /academy-live/webhook (8 calls, all 200, during the test)"
related: [2026-10-18-class-recordings.md]
---
- `academy_recordings.py` `ended_fields`: the file from `file_results` or `file`.
- `__tests__/test_class_recordings.py`: a real `EgressInfo` shaped as LiveKit
  sent it reads ready (red without the fix); one with no file reads failed.
