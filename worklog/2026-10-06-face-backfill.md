---
title: Older clips get a face close-up when their cover is made
date: 2026-10-06
agent: Claude Code (Claude Opus 5.5)
asked: "go look at the picture i made for don't judge a rightness by feelings. the face is 75 percent me"
status: done
prs: [kmj-intake-server face-backfill]
migrations: []
left_undone: ["The clip service must be redeployed with railway up for POST /faces (Kevin runs it)", "Choosing the expression that fits the title (a vision pick among the best frames) is not built; offered to Kevin"]
decisions: ["Read only the clip's stretch of the recording over the network (ffmpeg range reads), never the whole file", "Fall back to the clip's own video once the recording is removed", "Remember a no-face verdict only from the endpoint itself, so deploying the API first does no harm"]
related: [2026-10-06-better-face-frame.md, 2026-10-06-covers-both-shapes.md]
---
Kevin's cover was drawn from a wide shot because the clip predates close-ups.
The clip service now has POST /faces: it reads the clip's stretch of the
recording (or the clip) with one ffmpeg pass, picks the best face with the
same scoring as a run, and returns the close-up. clip_covers asks for it the
first time a cover is made for such a clip and saves it where a run would have.
On the real sermon it found an 86 px face, facing the camera, in about 4 s.
