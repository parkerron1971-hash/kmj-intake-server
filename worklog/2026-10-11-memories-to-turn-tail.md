---
title: "Memories matched to the message move out of the cached snapshot"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "build the best path forward. and approved to do what is needed to get this working well (Kevin, 2026-10-11, Layer Two step 4)"
status: waiting on review
prs: [kmj-intake-server#1383]
migrations: []
left_undone: ["replacing slow-moving snapshot blocks with the nightly digest waits for a week of real digests"]
decisions: ["hits never join the cached block: the stable importance/recency set stays there unchanged turn to turn, every other hit goes to the uncached tail, so nothing is dropped and nothing busts the cache", "the answer check reads memories_for_message as evidence"]
related: [2026-10-11-business-brain.md]
---
The meaning-matched memories depend on the current message but sat in the cached
state block, so a hit outside the stable set paid a rewrite of the ~20k-token
snapshot, and the blend could then drop the hit anyway. Now they go to the turn
tail as SAVED MEMORIES MATCHING THIS MESSAGE. The 11 October probe measured
51-80% of Chief turns per week rewriting 20k+ tokens of cache; this removes one
of the causes.
