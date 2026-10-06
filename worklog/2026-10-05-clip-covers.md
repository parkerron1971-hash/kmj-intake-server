---
title: Make cover for a clip (Creative Director on the clip's clean frame)
date: 2026-10-05
agent: Claude Code (Claude Opus 5.5)
asked: 'Would work with clips we making or both separate and together? (covers for clips)'
status: in progress
prs: [kmj-intake-server clip-covers]
migrations: []
left_undone: ["Frontend: Make cover / Make covers for kept clips in Video Clips (FindBestClips.tsx ClipReview), cover preview from configuration.cover_image_id via /ai/images/{biz}/{id}, Remember this style, director stages on the card"]
decisions: ["Owner only (covers spend credits, like Image Studio)", "Words default to the clip title; the owner can pass up to four lines", "Cover id lives in configuration, so it is part of what an approval covers"]
related: [2026-10-05-creative-director-every-business.md, 2026-10-05-clip-clean-frames.md, 2026-10-06-post-clip-with-cover.md]
---
One engine, several doors: a clip's cover is a Creative Director design with
the clip's clean frame as the subject and its title as the words. The frame is
copied once into the business's image gallery; each request id is its own
design and its own 30 credits. Details in docs/CHIEF_FLYER_DESIGN.md.
