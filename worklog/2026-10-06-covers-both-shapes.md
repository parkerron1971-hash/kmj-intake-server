---
title: Covers in both shapes, from a look you like, and designed along with the clips
date: 2026-10-06
agent: Claude Code (Claude Opus 5.5)
asked: "I would like for there to be an option to create the cover right along with the video clips as well. I like the full screen videos covers along with the story size. can we figure out a way to have both?"
status: done
prs: [kmj-intake-server covers-both-sizes]
migrations: []
left_undone: ["The Video Clips redesign in the app uses these fields (frontend PR)"]
decisions: ["Two shapes, each its own design: story 1088x1920 and wide 1920x1088", "Covers with the clips cover the best 6 clips by score, because a business can start 20 designs a day", "Auto covers run as the run's owner and only the owner can ask for them", "A cover that cannot start is tried twice, then the owner is told once and Make cover stays"]
related: [2026-10-06-covers-look-like-the-person.md, 2026-10-05-clip-covers.md, 2026-10-06-post-clip-with-cover.md]
---
Make cover can now design the story cover and the widescreen thumbnail in one
tap, follow a picture from the gallery as its style, and take a note about the
look. Find my best clips can design covers as the clips are made: once a run
completes, a scheduled step covers its best clips in the shapes the owner
chose. The library list returns each clip's covers by shape, and the clip
finder configuration prices them for the app.
