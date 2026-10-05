---
title: Creative Director for every business (designed flyers, covers groundwork)
date: 2026-10-05
agent: Claude Code (Claude Opus 5.5)
asked: 'could we use the same idea [BridgeClip] to produce thumbnails? ... a way to create flyers high quality; then: I would like to figure out how to build this. Would work with clips we making or both separate and together?'
status: in progress
prs: [kmj-intake-server PR A (this one)]
migrations: []
left_undone: ["PR B: clean source frame per clip (clipper_worker/service.py, not the vendored engine) + make-a-cover action on the Director + cover rides on Post for Me thumbnail_url", "PR C (frontend): Make cover / Make covers for kept clips in Video Clips; practitioner image card shows planning/drawing/checking; Remember this style button calling /ai/images/director/{business}/{image}/remember", "chief_plans plan steps still use generate_image for a flyer step"]
decisions: ["Keep GPT Image 2.5 and call OpenAI directly: OpenRouter sells the same models at the same token rates plus a fee", "One engine, several doors: clips, chat flyers and uploads all use the Creative Director", "30 credits a design, repair and planning free", "Covers are made on tap, never automatically (they show a real person)", "Switch PRACTITIONER_CREATIVE_DIRECTOR, default on"]
related: [2026-10-05-clipper-service.md, 2026-10-05-find-best-clips-backend.md]
---
Kevin asked whether the BridgeClip idea could make thumbnails and better flyers.
Proposal with three real GPT covers from the Separate Them clips ($0.048 each):
https://claude.ai/artifact/UbGa6kKpf44bYZhxtwijvC

The Creative Director (plan, GPT render, visual review, one repair) existed but
was wired to the platform business only. A practitioner's flyer was one GPT
call with no check. This PR runs it for any business through the flyer work
order: their own facts, limits and credits, owned references only, approved
wording only. Also opens 1088x1920 and 1920x1088 on the 2.5 models. Details in
docs/CHIEF_FLYER_DESIGN.md ("Every business").
