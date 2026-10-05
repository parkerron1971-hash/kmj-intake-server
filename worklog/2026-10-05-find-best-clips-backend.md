---
title: Find my best clips — backend (uploads, runs, clips into Video Clips)
date: 2026-10-05
agent: Claude Code (Claude Opus 5.5)
asked: "let's go with that — build the plan: engine, upload only, Growth level"
status: in progress
prs: [kmj-intake-server#1272, kmj-intake-server#PENDING]
migrations: [supabase/APPLY-2026-10-05-find-best-clips.sql (rehearsed on production with a rollback probe; apply before merge)]
left_undone: ["Frontend: the Video Clips screen (upload, options, progress, review grid with empty-spot notices, keep/skip) + mobile + whatsNew", "After the screen ships: remove ai_clips from feature_gates.UNANNOUNCED_FEATURES and marketing_pages._NOT_A_ROW and add its compare row", "PR 3: post kept clips through Post for Me with a caption Chief writes", "PR 4: Make clips on Sermons; Show the whole stage here"]
decisions: ["Upgrade Grow → Video Clips rather than a new screen; AI clips land in media_assets as ready clips so the existing review/handoff applies", "Uploads go browser → Supabase resumable (TUS, x-signature signed token, 6 MB chunks); no user JWT reaches storage", "Every bucket gets an explicit limit before the project-wide upload cap rises from 100 MB to 5 GB", "Runs resume after an API restart (clip-service job keeps the run id; clip asset ids are uuid5(run, index))", "Charge after the run is recorded complete: a crash can lose a charge, never double one", "ai_clips stays off plan cards (UNANNOUNCED_FEATURES) until the screen ships", "Pilot first: CLIP_FINDER_BUSINESSES allow-list, '*' opens it"]
related: [2026-10-05-clipper-service.md]
---
Backend half of Find my best clips. `clip_finder.py` adds uploads from a
computer (a private `uploading` row, a signed resumable-upload token, then a
size check and a range-request ffprobe before the row turns `ready`), runs
(`media_clip_runs`, one active per business and one working platform-wide,
claimed with a lease like video jobs), and the worker that drives the clip
service: start or resume the job, follow it, file each clip and poster into
program-media and media_assets with its empty-spot notices, record the run
complete, meter it (cost always; actions only past 10 hours a month), and
notify. Keep, skip and rename are a PATCH on the clip. A sweep every six hours
applies Kevin's storage rules: recordings 7 days after their clips, skipped
clips after 30 days, abandoned uploads after a day.

Found while building: `features_by_plan` would have put a raw `ai_clips`
on the Solutionist plan card (the cards fall back to the key), so the key is
held back until the screen ships. The migration ran fully against production
inside a forced rollback: new status check, three columns, the runs table,
the claim function, no bucket left without a limit, program-media at 5 GB;
a leftover check confirmed nothing remained.
