---
title: Clean frame per clip (the source for clip covers)
date: 2026-10-05
agent: Claude Code (Claude Opus 5.5)
asked: 'Would work with clips we making or both separate and together? (build covers for clips)'
status: in progress
prs: [kmj-intake-server clip-clean-frames]
migrations: []
left_undone: ["Deploy the clip service (railway up --ci, see clipper_worker/README.md); until then results carry no frame and clips file as before", "Make-a-cover action on the Creative Director (after #1280)", "Cover rides on Post for Me thumbnail_url", "App buttons (frontend)"]
decisions: ["Frame = poster moment (speaker visible) taken from the recording, not the captioned clip", "Stored beside the poster as <clip id>-frame.jpg; configuration.frame says it exists"]
related: [2026-10-05-creative-director-every-business.md, 2026-10-05-clipper-service.md]
---
Today's clip posters are frames of the finished clip, so the title card and
captions are burned in; a designed cover needs the speaker clean. The clip
service now takes a frame from the recording at the poster's moment
(start + poster_at), keeps the recording until those frames exist, and serves
clip_NN_frame.jpg. The API files it as <clip id>-frame.jpg and sets
configuration.frame; the 30-day sweep of skipped clips removes it too.
Works with the current service unchanged (no frame in the result, nothing filed).
