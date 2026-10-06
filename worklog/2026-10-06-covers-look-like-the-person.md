---
title: Covers look like the person (face close-up, likeness-first drawing and checking)
date: 2026-10-06
agent: Claude Code (Claude Opus 5.5)
asked: "my big issue is the person not looking like the original person ... we want over 90 percent looks ... tighten the checker but don't have it so tight nothing is produced"
status: in progress
prs: [kmj-intake-server covers-look-like-the-person]
migrations: []
left_undone: ["Redeploy the clip service (railway up) so new clips carry clip_NN_face.jpg", "Clips made before this have no close-up and use the frame alone"]
decisions: ["Letters overlapped by the person are not a flaw (Kevin)", "Likeness is judged against the subject photos and repaired once; the one-repair ceiling keeps output flowing", "input_fidelity=high is not available on GPT Image 2.5"]
related: [2026-10-06-cover-link-on-the-design.md, 2026-10-05-clip-clean-frames.md]
---
The stage frame is a wide 720p shot with a ~70 px face, so GPT redrew the
person from little detail (~80% like them, Kevin). The clip service now saves a
face close-up per clip; Make cover sends it first; the render prompt, planner
and checker put likeness first (the checker sees the subject photos and repairs
a miss once) and stop reporting overlapped letters. Side-by-side on the
Separate Them moment: the new cover kept the real braids, hairline, beard and
expression; yesterday's frame-only cover had a generic rounder face.
