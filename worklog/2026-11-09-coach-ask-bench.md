---
title: A bench of simulated owners for the Design Coach
date: 2026-11-09
agent: Claude Code (Claude Opus 5.5)
asked: "make sure chief can interpret what everyone is asking like you can so the design could be good"
status: shipped
prs: [kmj-intake-server#1782]
migrations: []
left_undone:
  - "The six held-out owners (one word, Spanish, impatient, impossible asks, daycare, food truck) have never run. The system stopped that run for low memory and nothing was saved. Run them before tuning anything on them."
  - "Results are written only when a run ends, so a stopped run saves nothing and its spend is unknown. Writing after each owner would fix that."
  - "Whether a question was a good one is still a judgment: read the transcripts, not only the scores."
decisions:
  - "A cheap model plays the owner from a private list of facts; the real run_turn plays the Coach, starting from Chief's real hand-off."
  - "Nothing can touch production: secrets other than the Anthropic key are deleted before import, the database address doesn't exist, the dossier lives in memory, and database, messaging and payment hosts are refused at the socket."
  - "Owners added after tuning go under the held-out line, so there is always a measure the fixes weren't fitted to."
related: [2026-11-09-coach-reads-the-ask.md, 2026-11-09-website-ask-goes-to-coach.md, 2026-11-09-layouts-follow-the-ask.md]
---
Fourteen owners who talk the way real owners do: a few words, vague, on a phone. Each
session is scored on what a strong brief needs: did the Coach hear the ask, ask what the
site needs (where they are, when they're open), skip what is already on file, recommend a
layout that fits the ask, and promise nothing nobody here can do.

On the eight tuned owners, main scored 41 of 70 and the first round of #1780 scored 68.
That second number flatters the fix, because the fix was tuned on those owners. The
transcripts found what the scores couldn't: the Coach telling an owner nobody could reach
the photos on their phone (the upload card reads from exactly there), whole sentences saved
as an address, and "your story carries the site" shown to an owner who answered "idk".

It costs real money on production's key, about 35 cents an owner (about $5 for all 14).
`--dry` proves the setup with no model calls; `--rescore <file>` scores a saved run again
for free; `--tree <worktree>` tests another checkout's Coach.
